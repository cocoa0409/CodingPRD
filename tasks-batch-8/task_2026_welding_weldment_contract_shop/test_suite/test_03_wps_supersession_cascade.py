"""WPS revision cycle and the supersession cascade: prior revision flips to
SUPERSEDED, PENDING joints are placed ON_HOLD, and tied qualifications are
re-evaluated for continuity lapse."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_wps,
    create_and_approve_pqr,
    create_fixture,
    create_joint,
    create_pqr,
    create_shop,
    create_shop_order,
    create_weldment,
    create_wps,
    get_success_data,
    reserve_fixture,
    setup_supersession_scenario,
    validate_error,
)

ADMIN = TEST_USERS["shop_admin_headers"]
QC_MANAGER = TEST_USERS["qc_manager_headers"]
WELD_LEAD = TEST_USERS["weld_lead_headers"]


class TestWpsRevisionCycle:
    """The WPS revision cycle runs DRAFT → APPROVED → SUPERSEDED (PRD §3.1)."""

    def _three_revisions(self, api):
        shop = create_shop(shop_name="Revision Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-5",
                                     reviewer_id="qc-reviewer-1")
        r1 = create_wps(shop["id"], pqr["id"], wps_number="WPS-5", revision=1)
        r1 = approve_wps(shop["id"], r1["id"], "qc-approver-1")
        r2 = create_wps(shop["id"], pqr["id"], wps_number="WPS-5", revision=2)
        r3 = create_wps(shop["id"], pqr["id"], wps_number="WPS-5", revision=3)
        return shop, pqr, r1, r2, r3

    def test_second_revision_supersedes_first(self, api):
        """PRD §3.1: "Any prior WPS revision in the same shop carrying the
        same `wps_number` at a lower `revision` that is still `APPROVED` is
        cascaded to `SUPERSEDED`, with its `superseded_by_id` pointed at the
        newly approved revision and its own `version` incremented."

        Design: Difficulty/non_linear_state_machine/wps_revision_cycle
        """
        shop, pqr, r1, r2, _ = self._three_revisions(api)

        r2_approved = approve_wps(shop["id"], r2["id"], "qc-approver-1")
        assert r2_approved["status"] == "APPROVED"
        # PRD §3.1: "The revision pins its supporting evidence:
        # `pinned_pqr_version` captures the PQR's `version` at approval time"
        pqr_now = get_success_data(api.get_pqr(shop["id"], pqr["id"], ADMIN))
        assert r2_approved["pinned_pqr_version"] == pqr_now["version"]
        assert r2_approved["approved_by_user_id"] == "qc-approver-1"

        r1_now = get_success_data(api.get_wps(shop["id"], r1["id"], ADMIN))
        assert r1_now["status"] == "SUPERSEDED"
        assert r1_now["superseded_by_id"] == r2["id"]

    def test_third_revision_continues_cycle(self, api):
        """PRD §3.1: "`REJECTED` and `SUPERSEDED` are terminal; `APPROVED` is
        not, because a newer revision can supersede it — the cycle runs
        `DRAFT` to `APPROVED` to `SUPERSEDED`, with a fresh `DRAFT` created
        for the next revision."
        PRD §3.1: "Any prior WPS revision in the same shop carrying the same
        `wps_number` at a lower `revision` that is still `APPROVED` is
        cascaded to `SUPERSEDED`, with its `superseded_by_id` pointed at the
        newly approved revision and its own `version` incremented."

        Design: Difficulty/non_linear_state_machine/wps_revision_cycle
        """
        shop, _, r1, r2, r3 = self._three_revisions(api)
        approve_wps(shop["id"], r2["id"], "qc-approver-1")
        approve_wps(shop["id"], r3["id"], "qc-approver-1")

        r1_now = get_success_data(api.get_wps(shop["id"], r1["id"], ADMIN))
        r2_now = get_success_data(api.get_wps(shop["id"], r2["id"], ADMIN))
        r3_now = get_success_data(api.get_wps(shop["id"], r3["id"], ADMIN))

        assert r1_now["status"] == "SUPERSEDED"
        assert r1_now["superseded_by_id"] == r2["id"], (
            "Rev 1 was already terminal when rev 3 approved, so its pointer "
            "still names rev 2")
        assert r2_now["status"] == "SUPERSEDED"
        assert r2_now["superseded_by_id"] == r3["id"]
        assert r3_now["status"] == "APPROVED"


class TestWpsSupersedeCascadeDepth3:
    """Depth-3 cascade driven by approving a higher revision (PRD §3.1/§3.2)."""

    def test_link1_prior_revision_superseded(self, api):
        """PRD §3.1: "Any prior WPS revision in the same shop carrying the
        same `wps_number` at a lower `revision` that is still `APPROVED` is
        cascaded to `SUPERSEDED`, with its `superseded_by_id` pointed at the
        newly approved revision and its own `version` incremented."

        Design: Difficulty/transitive_cascade/wps_supersede_cascade_depth_3
        """
        sc = setup_supersession_scenario(shop_name="Cascade Shop L1")
        shop_id = sc["shop"]["id"]

        approve_wps(shop_id, sc["wps_r2"]["id"], "qc-approver-1")

        r1_now = get_success_data(
            api.get_wps(shop_id, sc["wps_r1"]["id"], ADMIN))
        assert r1_now["status"] == "SUPERSEDED"
        assert r1_now["superseded_by_id"] == sc["wps_r2"]["id"]
        assert r1_now["version"] == sc["wps_r1"]["version"] + 1

    def test_link2_pending_joint_placed_on_hold(self, api):
        """PRD §3.1: "Supersession ripples outward: every joint still
        `PENDING` in fabrication that references a superseded WPS is flipped
        to `ON_HOLD` until a `QCManager` rebinds it, and every welder
        qualification tied to a superseded WPS that is still `QUALIFIED` is
        re-evaluated for continuity lapse as of the shop's current clock
        (see §3.2)."

        Design: Difficulty/transitive_cascade/wps_supersede_cascade_depth_3
        """
        sc = setup_supersession_scenario(shop_name="Cascade Shop L2")
        shop_id = sc["shop"]["id"]

        approve_wps(shop_id, sc["wps_r2"]["id"], "qc-approver-1")

        joint_now = get_success_data(
            api.get_joint(shop_id, sc["joint"]["id"], ADMIN))
        assert joint_now["fabrication_status"] == "ON_HOLD", (
            "PENDING joint referencing the superseded WPS must flip to "
            f"ON_HOLD, got {joint_now['fabrication_status']}")

    def test_link3_tied_qualification_lapsed(self, api):
        """PRD §3.2: "Retrospectively, two sweeps re-evaluate every
        `QUALIFIED` row against the clock without any new weld activity:
        advancing the shop clock runs the continuity sweep, and the
        WPS-supersession cascade of §3.1 re-evaluates all `QUALIFIED`
        qualifications tied to a superseded WPS, flipping to `LAPSED` those
        whose welder's `last_weld_at_utc` lies more than 183 days in the past
        relative to `current_utc`."

        The qualification baseline is 2026-01-01 and the shop clock is
        2026-08-01, more than 183 days later, so the cascade lapses it.

        Design: Difficulty/transitive_cascade/wps_supersede_cascade_depth_3
        """
        sc = setup_supersession_scenario(shop_name="Cascade Shop L3")
        shop_id = sc["shop"]["id"]
        assert sc["qualification"]["status"] == "QUALIFIED"

        approve_wps(shop_id, sc["wps_r2"]["id"], "qc-approver-1")

        qual_now = get_success_data(
            api.get_qualification(shop_id, sc["qualification"]["id"], ADMIN))
        assert qual_now["status"] == "LAPSED", (
            "Qualification tied to the superseded WPS whose baseline is "
            f">183 days old must lapse, got {qual_now['status']}")


class TestSupersededWpsReferences:
    def test_start_fab_with_draft_wps_rejected(self, api):
        """PRD §3.5: "The referenced WPS must be `APPROVED` at that moment —
        a superseded or still-draft document is rejected with
        `ERR_WPS_NOT_APPROVED`."

        Design: Corner/state_machines/joint_start_fab_with_superseded_wps_returns_error
        """
        shop = create_shop(shop_name="Draft WPS Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-Q9")
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-Q9")  # DRAFT
        fixture = create_fixture(shop["id"], fixture_code="FQ9")
        reserve_fixture(shop["id"], fixture["id"])
        order = create_shop_order(shop["id"], po_number="PO-Q9")
        weldment = create_weldment(shop["id"], order["id"], fixture["id"])
        joint = create_joint(shop["id"], weldment["id"], wps["id"],
                             joint_number="J-Q9")

        resp = api.start_fabrication(
            shop["id"], joint["id"],
            {"expected_joint_version": joint["version"]},
            WELD_LEAD)
        validate_error(resp, ApiErrorId.ERR_WPS_NOT_APPROVED)

    def test_rebind_to_superseded_wps_rejected(self, api):
        """PRD §3.7: "Joints placed `ON_HOLD` by the WPS-supersession cascade
        of §3.1 are recovered by the `QCManager` through rebinding: the joint
        must currently be `ON_HOLD` in fabrication, the supplied `new_wps_id`
        must reference an `APPROVED` WPS in the same shop (otherwise
        `ERR_WPS_NOT_APPROVED`), and the joint's `base_metal_thickness_mm`
        must fall within the new document's thickness envelope, boundaries
        inclusive (otherwise `ERR_JOINT_THICKNESS_OUTSIDE_WPS`)."

        Design: Corner/state_machines/joint_start_fab_with_superseded_wps_returns_error
        """
        sc = setup_supersession_scenario(shop_name="Rebind Shop")
        shop_id = sc["shop"]["id"]
        # Cascade: approving rev 2 supersedes rev 1 and holds the joint.
        approve_wps(shop_id, sc["wps_r2"]["id"], "qc-approver-1")
        held = get_success_data(
            api.get_joint(shop_id, sc["joint"]["id"], ADMIN))
        assert held["fabrication_status"] == "ON_HOLD"

        resp = api.rebind_wps(
            shop_id, sc["joint"]["id"],
            {"new_wps_id": sc["wps_r1"]["id"]},
            QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_WPS_NOT_APPROVED)


class TestJointStartFabricationOcc:
    def test_occ_stale_version_on_joint_start_fab(self, api):
        """PRD §2.6: "A WPS-supersession cascade that flipped the joint to
        `ON_HOLD` advances the joint's `version`; a start-fabrication request
        still carrying the pre-cascade version is rejected with
        `ERR_STALE_VERSION` (HTTP 412) so the client re-reads and discovers
        the hold."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_joint_start_fab
        """
        sc = setup_supersession_scenario(shop_name="Joint OCC Shop")
        shop_id = sc["shop"]["id"]
        pre_cascade_version = sc["joint"]["version"]

        # The supersession cascade flips the joint to ON_HOLD and advances
        # its version.
        approve_wps(shop_id, sc["wps_r2"]["id"], "qc-approver-1")

        resp = api.start_fabrication(
            shop_id, sc["joint"]["id"],
            {"expected_joint_version": pre_cascade_version},
            WELD_LEAD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # The client re-reads and discovers the hold.
        joint_now = get_success_data(
            api.get_joint(shop_id, sc["joint"]["id"], ADMIN))
        assert joint_now["fabrication_status"] == "ON_HOLD"
