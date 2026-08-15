"""Stackup locking, the DFM gate, and the drill-program review loop.

Covers PRD §3.2 (stackups, DFM) and §3.4 (drill programs, SoD, review cycle).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_customer, create_order, create_stackup, create_and_lock_stackup,
    submit_dfm,
    create_drill_program, submit_drill_program, approve_drill_program,
    create_laminate_lot, create_laminate_lot_payload,
    make_customer_headers, make_cam_operator_headers, make_process_engineer_headers,
    TEST_USERS,
)

FAB_ADMIN = TEST_USERS["fab_admin_headers"]
CAM = TEST_USERS["cam_operator_headers"]
ENG = TEST_USERS["process_engineer_headers"]
QI = TEST_USERS["quality_inspector_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def _quoted_order_with_locked_stackup(company="Sup Co", email="sup@co.example"):
    cust = create_customer(company, email, 5000)
    order = create_order(cust["id"], quantity_boards=10)
    return cust, order


class TestInitialStates:
    def test_initial_states_on_create(self, api):
        """PRD §3.1: "A newly created order opens with `fab_status` of `QUOTED`
        and an independent `quality_disposition` of `PENDING`, a `boards_scrapped`
        counter of zero, and a `provisional_total_cents` of null". PRD §3.2:
        "A stackup is born in `DRAFT` status." PRD §3.4: "The program opens in
        `DRAFT`." PRD §3.5: "The lot opens in `RECEIVED` status".

        Design: Corner/state_machines/initial_states_on_create
        """
        cust = create_customer("Init Co", "init@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        assert order["fab_status"] == "QUOTED"
        assert order["quality_disposition"] == "PENDING"
        assert order["boards_scrapped"] == 0
        assert order["provisional_total_cents"] is None

        stackup = create_stackup(order["id"])
        assert stackup["status"] == "DRAFT"

        program = create_drill_program(order["id"])
        assert program["status"] == "DRAFT"

        lot = create_laminate_lot("LOT-I1", panels_total=10)
        assert lot["status"] == "RECEIVED"


class TestStackupLocking:
    def test_stackup_lock_supersedes_older_locked(self, api):
        """PRD §3.2: "Locking supersedes: any other `LOCKED` stackup on the same
        order immediately becomes `SUPERSEDED`".

        Design: Corner/state_machines/stackup_lock_supersedes_older
        """
        cust = create_customer("Sup Co", "sup@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        s1 = create_stackup(order["id"], revision=1, total_thickness_mils=62)
        s1 = get_success_data(api.lock_stackup(s1["id"], ENG))
        assert s1["status"] == "LOCKED"

        s2 = create_stackup(order["id"], revision=2, total_thickness_mils=64)
        s2 = get_success_data(api.lock_stackup(s2["id"], ENG))
        assert s2["status"] == "LOCKED"

        s1_after = get_success_data(api.get_stackup(s1["id"], ENG))
        assert s1_after["status"] == "SUPERSEDED", (
            f"older locked stackup must be superseded, got {s1_after['status']}"
        )


class TestDfmGate:
    def test_dfm_reject_cycle(self, api):
        """PRD §3.2: "rejection — which may carry an optional `reason` — returns
        it from `DFM_REVIEW` to `QUOTED` for another engineering pass." and
        "Submitting the order for DFM ... moves `fab_status` from `QUOTED` to
        `DFM_REVIEW`".

        Design: Corner/state_machines/dfm_reject_cycle
        """
        cust, order = _quoted_order_with_locked_stackup("Cyc Co", "cyc@co.example")
        stackup, _ = create_and_lock_stackup(order["id"])
        order = submit_dfm(order["id"], cust["id"])
        assert order["fab_status"] == "DFM_REVIEW"

        order = get_success_data(
            api.dfm_reject(order["id"], {"reason": "stackup ambiguous"}, ENG)
        )
        assert order["fab_status"] == "QUOTED", (
            f"dfm-reject must return the order to QUOTED, got {order['fab_status']}"
        )

        order = submit_dfm(order["id"], cust["id"])
        assert order["fab_status"] == "DFM_REVIEW", (
            "the QUOTED -> DFM_REVIEW leg must be repeatable after a rejection"
        )

    def test_double_submit_dfm_rejected(self, api):
        """PRD §3.2: "Submitting the order for DFM — allowed to a `Customer` or
        `SalesEngineer` — moves `fab_status` from `QUOTED` to `DFM_REVIEW`"; the
        transition does not exist from DFM_REVIEW, and PRD §2.9 names "the
        generic transition-legality guard (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/double_submit_dfm_rejected
        """
        cust, order = _quoted_order_with_locked_stackup("Idem Co", "idem@co.example")
        create_and_lock_stackup(order["id"])
        submit_dfm(order["id"], cust["id"])

        resp = api.submit_dfm(order["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        order = get_success_data(api.get_fab_order(order["id"], PLANNER))
        assert order["fab_status"] == "DFM_REVIEW"

    def test_ship_from_quoted_rejected(self, api):
        """PRD §3.9: "A `ProductionPlanner` ships a `COMPLETED` order" — no ship
        transition exists from QUOTED, so PRD §2.9's "generic transition-legality
        guard (`ERR_INVALID_STATE`)" applies.

        Design: Corner/state_machines/ship_from_quoted_rejected
        """
        cust = create_customer("Ship Co", "ship@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        resp = api.ship_order(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        order = get_success_data(api.get_fab_order(order["id"], PLANNER))
        assert order["fab_status"] == "QUOTED"


class TestDrillReviewLoop:
    def test_drill_program_revision_cycle(self, api):
        """PRD §3.4: "Rejection requires a non-empty `reason` in the payload; the
        program moves from `UNDER_REVIEW` to `REJECTED` and the reason is
        preserved on `rejection_reason`. A `CAMOperator` may then revise: the
        program returns from `REJECTED` to `DRAFT`, its `revision` increments by
        one, any `min_hole_mils` or `hole_count` present in the revise payload
        replace the prior values, and `rejection_reason` is cleared back to null."
        PRD §3.4: "the program's `plated_aspect_ratio` is computed as the owning
        order's locked stackup `total_thickness_mils` divided by `min_hole_mils`".

        Design: Difficulty/non_linear_state_machine/drill_program_revision_cycle
        """
        cust = create_customer("Epsilon Circuits", "ops@epsilon.example", 1_000_000)
        order = create_order(cust["id"])
        create_and_lock_stackup(order["id"])

        program = create_drill_program(order["id"], min_hole_mils=5, hole_count=1200)
        submit_drill_program(program["id"])
        program = get_success_data(
            api.reject_drill_program(
                program["id"], {"reason": "min hole below process minimum"},
                make_process_engineer_headers("eng_1"),
            )
        )
        assert program["status"] == "REJECTED"
        assert program["rejection_reason"] == "min hole below process minimum"

        program = get_success_data(
            api.revise_drill_program(
                program["id"], {"min_hole_mils": 10},
                make_cam_operator_headers("cam_1"),
            )
        )
        assert program["status"] == "DRAFT"
        assert program["revision"] == 2, (
            f"revise must increment revision to 2, got {program['revision']}"
        )
        assert program["rejection_reason"] is None
        assert program["min_hole_mils"] == 10

        submit_drill_program(program["id"])
        program = approve_drill_program(program["id"])
        assert program["status"] == "APPROVED", (
            "the DRAFT -> UNDER_REVIEW -> REJECTED -> DRAFT -> UNDER_REVIEW -> "
            f"APPROVED loop must close, got {program['status']}"
        )
        assert program["plated_aspect_ratio"] == 6.2, (
            f"62 mils / 10 mils must compute to 6.2, got {program['plated_aspect_ratio']}"
        )

    def test_drill_program_revise_keeps_unsupplied_fields(self, api):
        """PRD §3.4: "any `min_hole_mils` or `hole_count` present in the revise
        payload replace the prior values" — fields absent from the revise payload
        are retained, while "its `revision` increments by one, ... and
        `rejection_reason` is cleared back to null."

        Design: Difficulty/non_linear_state_machine/drill_program_revision_cycle
        """
        cust = create_customer("Epsilon Two", "ops@epsilon2.example", 1_000_000)
        order = create_order(cust["id"])
        create_and_lock_stackup(order["id"])

        program = create_drill_program(order["id"], min_hole_mils=8, hole_count=1200)
        submit_drill_program(program["id"])
        program = get_success_data(
            api.reject_drill_program(
                program["id"], {"reason": "needs re-panelization"},
                make_process_engineer_headers("eng_1"),
            )
        )
        program = get_success_data(
            api.revise_drill_program(program["id"], {}, make_cam_operator_headers("cam_1"))
        )
        assert program["status"] == "DRAFT"
        assert program["revision"] == 2
        assert program["rejection_reason"] is None
        assert program["min_hole_mils"] == 8, (
            f"min_hole_mils absent from the revise payload must be retained, got {program['min_hole_mils']}"
        )
        assert program["hole_count"] == 1200

    def test_sod_creator_cannot_approve(self, api):
        """PRD §3.4: "the approver's `X-User-ID` must differ from the program's
        `created_by_user_id`, else `ERR_SOD_VIOLATION`". PRD §2.1: "The server
        may record it (for example, as `created_by_user_id` on a `DrillProgram`,
        where it anchors the segregation-of-duties check at approval time)".

        Design: Corner/validations/sod_creator_cannot_approve
        """
        cust = create_customer("SoD Co", "sod@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        create_and_lock_stackup(order["id"])

        program = create_drill_program(order["id"], min_hole_mils=8, hole_count=400,
                                       author_id="cam_1")
        assert program["created_by_user_id"] == "cam_1"
        submit_drill_program(program["id"], author_id="cam_1")

        resp = api.approve_drill_program(
            program["id"], make_process_engineer_headers("cam_1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        program = approve_drill_program(program["id"], approver_id="eng_1")
        assert program["status"] == "APPROVED"

    def test_hole_below_min_rejected(self, api):
        """PRD §3.4: "approval enforces three gates, evaluated in this order when
        several fail together: first, segregation of duties ...; second, the
        process minimum — a `min_hole_mils` below 6 is rejected with
        `ERR_HOLE_BELOW_MIN`; third, the plating aspect ratio".

        Design: Corner/validations/hole_below_min_rejected
        """
        cust = create_customer("Hole Co", "hole@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        create_and_lock_stackup(order["id"])  # 62 mils, 1oz

        # min_hole 5 violates both the floor (5 < 6) and the aspect ceiling
        # (62/5 = 12.4 > 8.0); the earlier hole-minimum gate is the one reported.
        program = create_drill_program(order["id"], min_hole_mils=5, hole_count=400)
        submit_drill_program(program["id"])
        resp = api.approve_drill_program(program["id"], make_process_engineer_headers("eng_1"))
        validate_error(resp, ApiErrorId.ERR_HOLE_BELOW_MIN)

    def test_rbac_exclusive_operation_denials(self, api):
        """PRD §2.1: "A request whose role is well-formed but not on the
        endpoint's authorized-role list is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /pcb/drill-programs/{id}/approve is
        ProcessEngineer-only; POST /pcb/laminate-lots is ProcessEngineer-only.

        Design: Corner/rbac/rbac_exclusive_operation_denials
        """
        cust = create_customer("Rbac Co", "rbac@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        create_and_lock_stackup(order["id"])
        program = create_drill_program(order["id"], min_hole_mils=8, hole_count=400)
        submit_drill_program(program["id"])

        # Even the owning Customer cannot approve a drill program.
        resp = api.approve_drill_program(
            program["id"], make_customer_headers(cust["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        # A CAMOperator cannot receive laminate lots.
        resp = api.create_laminate_lot(
            create_laminate_lot_payload(lot_code="LOT-RB1", panels_total=10), CAM,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
