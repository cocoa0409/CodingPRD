"""Difficulty Rule 3 — non_linear_state_machine.

BusinessEntity cycle ACTIVE → DELINQUENT → ACTIVE (annual-report delinquency
and cure) and BOIDisclosure cycle SUBMITTED ↔ AMENDED ↔ SUBMITTED.
"""
from test_helpers import (
    validate_success,
    set_clock,
    setup_active_llc,
    create_draft_annual_report,
    file_annual_report,
    create_draft_boi_disclosure,
    submit_boi_disclosure,
    make_filer_headers,
    make_compliance_officer_headers,
    amend_boi_disclosure_payload,
)


class TestBusinessEntityActiveDelinquentActiveCycle:
    """PRD §3.6 cascade: AR DRAFT→DELINQUENT cascades parent ACTIVE→DELINQUENT;
    filing the cured report returns the parent DELINQUENT→ACTIVE.
    """

    def test_entity_traverses_active_delinquent_active_deterministically(self, api):
        """PRD §3.6: "When a `DRAFT` annual report flips automatically to `DELINQUENT`
        (the deadline-driven transition described in §3.7), the parent is
        recomputed: `compliance_posture` moves to `RESTRICTED` and, if the parent was
        `ACTIVE`, its `status` also flips to `DELINQUENT` (the second hop of the
        cascade)."
        PRD §3.6: "When every delinquent report has been cured for every `period_year`
        strictly less than the current clock year, the parent's `status` automatically
        returns from `DELINQUENT` to `ACTIVE` and the posture is recomputed toward
        `GOOD_STANDING`."

        Design: Difficulty/non_linear_state_machine/nlsm_business_entity_cycle_active_delinquent_active
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="HOTEL CYCLE LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        assert be["status"] == "ACTIVE"
        ar = create_draft_annual_report(be, 2024)
        # Advance past April-15-2025 deadline.
        set_clock("2025-05-01T00:00:00Z")
        mid = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        assert mid["status"] == "DELINQUENT"
        # File the delinquent report — cures the cycle.
        file_annual_report(be, ar["id"])
        after = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        assert after["status"] == "ACTIVE"

    def test_entity_posture_returns_to_good_standing_after_cure(self, api):
        """PRD §3.6: "the parent's `status` automatically returns from `DELINQUENT`
        to `ACTIVE` and the posture is recomputed toward `GOOD_STANDING`."

        Design: Difficulty/non_linear_state_machine/nlsm_business_entity_cycle_active_delinquent_active
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="HOTEL POSTURE LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        set_clock("2025-05-01T00:00:00Z")
        file_annual_report(be, ar["id"])
        after = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        assert after["compliance_posture"] == "GOOD_STANDING"


class TestBOIDisclosureSubmittedAmendedSubmittedCycle:
    """PRD §3.11: the SUBMITTED ↔ AMENDED ↔ SUBMITTED loop has no terminal state.
    """

    def test_boi_resubmits_with_refreshed_submitted_at(self, api):
        """PRD §3.11: "An `AMENDED` disclosure can then be re-submitted (`AMENDED → SUBMITTED`)
        by the same submit call, restamping `submitted_at`, re-emitting `BOI_SUBMITTED`,
        and again incrementing the disclosure's `version` by 1."

        Design: Difficulty/non_linear_state_machine/nlsm_boi_disclosure_cycle_submitted_amended_submitted
        """
        set_clock("2026-01-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="INDIA CYCLE LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        boi = create_draft_boi_disclosure(be, triggering_event="FORMATION")
        sub1 = submit_boi_disclosure(be, boi["id"])
        assert sub1["status"] == "SUBMITTED"
        # Amend with a new owners array (sum still 100).
        amend_res = api.amend_boi_disclosure(
            boi["id"],
            amend_boi_disclosure_payload(
                owners=[
                    {"name": "Owner One", "dob": "1980-01-01", "ownership_pct": 60,
                     "control_role": "OWNER"},
                    {"name": "Owner Two", "dob": "1985-05-05", "ownership_pct": 40,
                     "control_role": "CONTROLLER"},
                ]
            ),
            make_filer_headers(be["id"]),
        )
        amended = validate_success(amend_res, 200)
        assert amended["status"] == "AMENDED"
        # Move the clock forward (still inside 90-day FORMATION grace).
        set_clock("2026-01-15T00:00:00Z")
        sub2 = submit_boi_disclosure(be, boi["id"])
        assert sub2["status"] == "SUBMITTED"
        assert sub2["submitted_at"] != sub1["submitted_at"]
        # The disclosure carries the same id across the round-trip.
        assert sub2["id"] == boi["id"]

    def test_boi_version_increments_on_each_cycle_step(self, api):
        """PRD §3.11: "A new disclosure enters `DRAFT`. The filer submits it
        (`DRAFT → SUBMITTED`), at which point `submitted_at` is stamped from the
        current clock UTC, a `ComplianceEvent` with `event_type` of `BOI_SUBMITTED`
        is emitted, and the disclosure's `version` is incremented by 1."
        PRD §3.11: "An `AMENDED` disclosure can then be re-submitted (`AMENDED → SUBMITTED`)
        by the same submit call, restamping `submitted_at`, re-emitting `BOI_SUBMITTED`,
        and again incrementing the disclosure's `version` by 1."

        Design: Difficulty/non_linear_state_machine/nlsm_boi_disclosure_cycle_submitted_amended_submitted
        """
        set_clock("2026-01-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="INDIA VERSION LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        boi = create_draft_boi_disclosure(be, triggering_event="FORMATION")
        v_draft = boi["version"]
        sub1 = submit_boi_disclosure(be, boi["id"])
        assert sub1["version"] == v_draft + 1
        amend_res = api.amend_boi_disclosure(
            boi["id"],
            amend_boi_disclosure_payload(
                owners=[
                    {"name": "Owner One", "dob": "1980-01-01", "ownership_pct": 100,
                     "control_role": "BOTH"},
                ]
            ),
            make_filer_headers(be["id"]),
        )
        amended = validate_success(amend_res, 200)
        assert amended["version"] == sub1["version"] + 1
        sub2 = submit_boi_disclosure(be, boi["id"])
        assert sub2["version"] == amended["version"] + 1
