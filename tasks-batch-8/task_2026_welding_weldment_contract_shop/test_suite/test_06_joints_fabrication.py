"""Joint fabrication floor: weldment creation defaults, the joint's parallel
status dimensions, first-pass and weld-out transitions, and the weld-pass
role gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_joint,
    assert_weldment,
    create_fixture,
    create_joint,
    create_shop,
    create_shop_order,
    create_weldment,
    get_success_data,
    record_weld_pass,
    reserve_fixture,
    setup_fab_workspace,
    start_fabrication,
    validate_error,
    validate_success,
    weld_out,
)

ADMIN = TEST_USERS["shop_admin_headers"]
WELD_LEAD = TEST_USERS["weld_lead_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]


class TestWeldmentCreation:
    def test_weldment_system_fields_server_managed(self, api):
        """PRD §3.4: "A weldment is born with `posture` `OPEN`; its posture
        vocabulary is `OPEN`, `RESTRICTED`, `FROZEN`, `REPAIR_REVIEW`,
        `SHIPPED`, and `CANCELLED`, and the terminal postures are `SHIPPED`
        and `CANCELLED`."
        PRD §3.4: "Its audit counters all begin at zero —
        `repair_pass_count`, `total_pass_count`, `repair_rate_pct`, and
        `distortion_count` — and `signed_off_at_utc` stays null until the
        traveler is completed at shipment."
        PRD §3.4: "Creating a weldment also advances its parent order from
        `OPEN` to `IN_PROGRESS` when the order was still `OPEN`."

        Design: Corner/entities/weldment_system_fields_server_managed
        """
        shop = create_shop(shop_name="Weldment Defaults Shop")
        shop_id = shop["id"]
        fixture = create_fixture(shop_id, fixture_code="FY")
        reserve_fixture(shop_id, fixture["id"])
        order = create_shop_order(shop_id, po_number="PO-Y")
        assert order["status"] == "OPEN"

        resp = api.create_weldment(
            shop_id, order["id"],
            {"weldment_serial": "WM-Y", "fixture_id": fixture["id"],
             "drawing_revision": "R1"},
            PRODUCTION_PLANNER)
        weldment = validate_success(resp, 201)
        assert_weldment(weldment)
        assert weldment["posture"] == "OPEN"
        assert weldment["repair_pass_count"] == 0
        assert weldment["total_pass_count"] == 0
        assert weldment["repair_rate_pct"] == 0
        assert weldment["distortion_count"] == 0
        assert weldment["signed_off_at_utc"] is None
        assert weldment["shop_id"] == shop_id
        assert weldment["shop_order_id"] == order["id"]

        order_now = get_success_data(
            api.get_shop_order(shop_id, order["id"], ADMIN))
        assert order_now["status"] == "IN_PROGRESS", (
            "Creating the first weldment advances the order OPEN → "
            "IN_PROGRESS")


class TestJointParallelDimensions:
    def test_get_joint_returns_parallel_dimensions(self, api):
        """PRD §3.5: "A joint carries two parallel status dimensions from
        birth: `fabrication_status` begins at `PENDING` (vocabulary
        `PENDING`, `IN_PROGRESS`, `WELDED_OUT`, `ON_HOLD`, `CANCELLED`) while
        `inspection_status` begins at `NOT_READY` (vocabulary `NOT_READY`,
        `READY_FOR_VT`, `VT_PASSED`, `NDT_IN_PROGRESS`, `NDT_PASSED`,
        `NDT_FAILED`, `REPAIR_REQUIRED`, `REPAIR_WELDED_OUT`)."

        Design: Corner/endpoints/get_joint_returns_parallel_dimensions
        """
        ws = setup_fab_workspace(shop_name="Parallel Birth Shop",
                                 start_joints=False)
        shop_id = ws["shop"]["id"]
        joint = ws["joints"][0]

        fetched = validate_success(api.get_joint(shop_id, joint["id"], ADMIN),
                                   200)
        assert_joint(fetched)
        assert fetched["fabrication_status"] == "PENDING"
        assert fetched["inspection_status"] == "NOT_READY"
        assert fetched["repair_cycle_count"] == 0

    def test_first_weld_pass_marks_ready_for_vt(self, api):
        """PRD §3.5: "A recorded pass is stamped with `welded_at_utc` from
        the shop clock and fans out: the qualification's `last_weld_at_utc`
        advances to the clock and its continuity expiry is recomputed; the
        lot's `remaining_kg` is drawn down by `consumable_used_kg`; the
        weldment's `total_pass_count` increments by one, and its
        `repair_pass_count` increments by one when `is_repair` is true; the
        weldment's `repair_rate_pct` is recomputed (see §3.7) and the
        repair-review gate evaluated; and the first pass recorded on a joint
        moves that joint's `inspection_status` from `NOT_READY` to
        `READY_FOR_VT`."

        Design: Difficulty/non_linear_state_machine/joint_parallel_dimensions
        """
        ws = setup_fab_workspace(shop_name="First Pass Shop")
        shop_id = ws["shop"]["id"]
        joint = ws["joints"][0]
        assert joint["fabrication_status"] == "IN_PROGRESS"
        assert joint["inspection_status"] == "NOT_READY"

        record_weld_pass(shop_id, joint["id"], ws["welder"]["id"],
                         ws["qualification"]["id"], ws["lot"]["id"])

        joint_now = get_success_data(api.get_joint(shop_id, joint["id"],
                                                   ADMIN))
        # Fabrication axis holds while the inspection axis advances.
        assert joint_now["fabrication_status"] == "IN_PROGRESS"
        assert joint_now["inspection_status"] == "READY_FOR_VT", (
            "The first weld pass flips the inspection axis NOT_READY → "
            "READY_FOR_VT")

    def test_weld_out_completes_fabrication_keeps_ready_for_vt(self, api):
        """PRD §3.5: "Welding out moves `fabrication_status` to `WELDED_OUT`
        and sets `inspection_status` to `READY_FOR_VT` when it is not already
        further along."

        Design: Difficulty/non_linear_state_machine/joint_parallel_dimensions
        """
        ws = setup_fab_workspace(shop_name="Weld Out Shop")
        shop_id = ws["shop"]["id"]
        joint = ws["joints"][0]
        record_weld_pass(shop_id, joint["id"], ws["welder"]["id"],
                         ws["qualification"]["id"], ws["lot"]["id"])

        out = weld_out(shop_id, joint["id"])
        assert out["fabrication_status"] == "WELDED_OUT"
        assert out["inspection_status"] == "READY_FOR_VT", (
            "Weld-out sets the inspection axis to READY_FOR_VT")

        joint_now = get_success_data(api.get_joint(shop_id, joint["id"],
                                                   ADMIN))
        assert joint_now["fabrication_status"] == "WELDED_OUT"
        assert joint_now["inspection_status"] == "READY_FOR_VT"


class TestWeldOutPreconditions:
    def test_joint_weld_out_with_no_passes_returns_error(self, api):
        """PRD §3.5: "The joint must be `IN_PROGRESS` in fabrication and must
        have at least one recorded weld pass (`ERR_NO_WELD_PASSES`); the
        parent weldment must again be `OPEN` (`ERR_WELDMENT_NOT_OPEN`)."

        Design: Corner/state_machines/joint_weld_out_with_no_passes_returns_error
        """
        ws = setup_fab_workspace(shop_name="No Passes Shop")
        shop_id = ws["shop"]["id"]
        joint = ws["joints"][0]  # IN_PROGRESS, zero passes

        resp = api.weld_out(shop_id, joint["id"], WELD_LEAD)
        validate_error(resp, ApiErrorId.ERR_NO_WELD_PASSES)


class TestWeldPassRbac:
    def test_production_planner_cannot_record_weld_pass(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "`Welder` records weld passes, and does so under its own
        identity (see the identity rule below)."

        Design: Corner/validations/production_planner_cannot_record_weld_pass
        """
        ws = setup_fab_workspace(shop_name="Pass RBAC Shop")
        shop_id = ws["shop"]["id"]
        joint = ws["joints"][0]

        resp = api.record_weld_pass(
            shop_id, joint["id"],
            {"welder_id": ws["welder"]["id"],
             "qualification_id": ws["qualification"]["id"],
             "consumable_lot_id": ws["lot"]["id"],
             "consumable_used_kg": 1.0,
             "is_repair": False},
            PRODUCTION_PLANNER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
