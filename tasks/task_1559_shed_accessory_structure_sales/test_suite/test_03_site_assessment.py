"""Site assessment: dual-variant access verdict, assessor half-open window conflicts,
conditional report fields, and the cancel cascade (PRD §3.3, §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_book, create_draft_order, submit_site_check, file_report,
    get_order,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]


class TestAccessVerdictDualVariant:
    """Identical measurements (access 120in, width 10ft) yield opposite verdicts for
    PRE_BUILT (needs 132in) vs ON_SITE_BUILD (needs 36in)."""

    def _pair(self, api):
        jur, model, cust = setup_book()
        pb = create_draft_order(cust["id"], model["id"], jur["id"], delivery_mode="PRE_BUILT")
        osb = create_draft_order(
            cust["id"], model["id"], jur["id"], delivery_mode="ON_SITE_BUILD"
        )
        asm_pb = submit_site_check(pb["id"], window_start_hour=10)
        asm_osb = submit_site_check(osb["id"], window_start_hour=14)
        return pb, osb, asm_pb, asm_osb

    def _measurements(self):
        return dict(
            measured_access_width_in=120, measured_slope_pct=4,
            setback_front_ft=12, setback_side_ft=6, setback_rear_ft=8,
            ground_prep_needed=False,
        )

    def test_prebuilt_access_shortfall_unsuitable(self, api):
        """PRD §3.3: "a `PRE_BUILT` delivery must fit the whole structure through the
        gate, so the requirement is the order's width converted to inches plus a
        twelve-inch margin"
        PRD §3.3: "On `UNSUITABLE`, the order falls back from `SITE_REVIEW` to `DRAFT`
        for reconfiguration, and a later submission creates an entirely new assessment
        rather than resurrecting the old one."

        Design: Difficulty/dual_variant_calc/site_access_verdict_prebuilt_vs_onsite
        """
        pb, _, asm_pb, _ = self._pair(api)
        filed = file_report(asm_pb["id"], **self._measurements())
        # 120 < 10*12+12 = 132 -> hard fail
        assert filed["verdict"] == "UNSUITABLE"
        assert get_order(pb["id"])["status"] == "DRAFT"

    def test_onsite_carry_in_path_suitable(self, api):
        """PRD §3.3: "an `ON_SITE_BUILD` needs only a thirty-six-inch carry-in path for
        materials — identical site measurements can therefore pass one delivery mode and
        fail the other."
        PRD §3.3: "On `SUITABLE` or `SUITABLE_WITH_PREP`, the order advances from
        `SITE_REVIEW` to `PERMIT_REVIEW` and a permit application is created as described
        in §3.4"

        Design: Difficulty/dual_variant_calc/site_access_verdict_prebuilt_vs_onsite
        """
        _, osb, _, asm_osb = self._pair(api)
        filed = file_report(asm_osb["id"], **self._measurements())
        # 120 >= 36 -> passes access; all other checks pass
        assert filed["verdict"] == "SUITABLE"
        # area 120 >= threshold 120 -> permit required -> PERMIT_REVIEW
        assert get_order(osb["id"])["status"] == "PERMIT_REVIEW"


class TestAssessorHalfOpenWindowOverlap:
    """Half-open 2-hour windows [h, h+2): [10,12) collides with [11,13) but not [12,14)."""

    def _two_drafts(self, api):
        jur, model, cust = setup_book()
        o1 = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
        o2 = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
        return o1, o2

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "The visit occupies a half-open two-hour window: the start hour
        itself is included, the hour two later is not, and the start hour must be at
        least 6 and at most 20."
        PRD §3.3: "if another assessment with the same `assessor_id` on the same date is
        still in `REQUESTED` and its window overlaps the proposed one, the submission is
        rejected with `ERR_ASSESSOR_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/assessor_halfopen_window_overlap
        """
        o1, o2 = self._two_drafts(api)
        asm1 = submit_site_check(
            o1["id"], assessor_id="asr-7", scheduled_date="2026-08-05", window_start_hour=10
        )
        assert asm1["status"] == "REQUESTED"
        res = api.submit_site_check(
            o2["id"],
            {"assessor_id": "asr-7", "scheduled_date": "2026-08-05", "window_start_hour": 11},
            SALES,
        )
        validate_error(res, ApiErrorId.ERR_ASSESSOR_WINDOW_CONFLICT, expected_status=409)
        assert get_order(o2["id"])["status"] == "DRAFT"

    def test_adjacent_window_accepted(self, api):
        """PRD §3.3: "The visit occupies a half-open two-hour window: the start hour
        itself is included, the hour two later is not, and the start hour must be at
        least 6 and at most 20."
        PRD §3.3: "A successful submission moves the order from `DRAFT` to `SITE_REVIEW`,
        increments the order's `version`, and creates the linked `SiteAssessment` in
        `REQUESTED`"

        Design: Difficulty/resource_temporal_overlap/assessor_halfopen_window_overlap
        """
        o1, o2 = self._two_drafts(api)
        submit_site_check(
            o1["id"], assessor_id="asr-7", scheduled_date="2026-08-05", window_start_hour=10
        )
        # [12,14) is adjacent to [10,12): half-open => 12 is not < 12, no overlap
        asm2 = submit_site_check(
            o2["id"], assessor_id="asr-7", scheduled_date="2026-08-05", window_start_hour=12
        )
        assert asm2["status"] == "REQUESTED"
        assert get_order(o2["id"])["status"] == "SITE_REVIEW"


def test_report_missing_prep_cost_rejected(api):
    """PRD §3.3: "Flagging prep work makes `prep_cost_cents` mandatory; omitting it is
    rejected with `ERR_INVALID_REQUEST`."
    PRD §3.3: "An `InstallCrew` member later files the report — allowed only while the
    assessment is in `REQUESTED`"

    Design: Corner/validations/report_missing_prep_cost_returns_invalid_request
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    asm = submit_site_check(order["id"])
    payload = {
        "measured_access_width_in": 140, "measured_slope_pct": 4,
        "setback_front_ft": 12, "setback_side_ft": 6, "setback_rear_ft": 8,
        "ground_prep_needed": True,
    }
    res = api.report_site_assessment(asm["id"], payload, TEST_USERS["install_crew_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    refreshed = validate_success(
        api.get_site_assessment(asm["id"], SALES), 200
    )
    assert refreshed["status"] == "REQUESTED", "rejected report leaves the assessment open"


def test_cancel_cascades_requested_assessment(api):
    """PRD §3.6: "An assessment still `REQUESTED` moves to `CANCELLED`, while a
    `REPORTED` one is left untouched, and a permit application still `SUBMITTED` moves
    to `WITHDRAWN`."

    Design: Corner/state_machines/cancel_cascades_requested_assessment
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    asm = submit_site_check(order["id"])
    res = api.cancel_order(order["id"], {"reason": "customer backed out"}, SALES)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    refreshed = validate_success(api.get_site_assessment(asm["id"], SALES), 200)
    assert refreshed["status"] == "CANCELLED"
