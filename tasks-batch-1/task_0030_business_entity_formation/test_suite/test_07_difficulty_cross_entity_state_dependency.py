"""Difficulty Rule 7 — cross_entity_state_dependency.

Two cross-entity pairs:
  (a) AnnualReport.file requires BusinessEntity.status != DISSOLVED.
  (b) BOIDisclosure.submit requires exactly one ACTIVE RegisteredAgent.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    set_clock,
    setup_active_llc,
    create_draft_annual_report,
    create_draft_boi_disclosure,
    make_filer_headers,
)


class TestAnnualReportFileRequiresNonDissolvedParent:
    """PRD §3.12: dissolved-parent lockdown. PRD §2.10 priority places
    ERR_INVALID_STATE (P40) before ERR_ENTITY_DISSOLVED (P45), so when an
    AnnualReport has been cascade-voided by dissolution, the file attempt
    fails either with ERR_INVALID_STATE (the voided AR cannot transition to
    FILED) or with ERR_ENTITY_DISSOLVED (the parent is dissolved). Either
    is a faithful PRD reading.
    """

    def test_file_after_dissolve_rejects(self, api):
        """PRD §3.12: "On a legal dissolve, the parent's `status` transitions to
        `DISSOLVED`, the `compliance_posture` is reset to `FROZEN`, every
        `AnnualReport` in `DRAFT` or `DELINQUENT` is flipped to `VOIDED`"
        PRD §3.12: "Once `DISSOLVED`, every subsequent child mutation is rejected
        with `ERR_ENTITY_DISSOLVED` — the entity becomes read-only."
        PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`), then the
        dissolved-parent gate (`ERR_ENTITY_DISSOLVED`)"

        Design: Difficulty/cross_entity_state_dependency/cesd_annual_report_file_requires_non_dissolved_business_entity
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="QUEBEC LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        # Dissolve the parent — cascade voids the DRAFT report.
        api.dissolve_business_entity(be["id"], make_filer_headers(be["id"]))
        # Attempt to file the (now-VOIDED) report on the (now-DISSOLVED) parent.
        res = api.file_annual_report(ar["id"], make_filer_headers(be["id"]))
        # PRD §2.10 binds ERR_INVALID_STATE before ERR_ENTITY_DISSOLVED; the
        # cascade in §3.12 makes the AR VOIDED so the state precondition is
        # violated; the parent is also DISSOLVED. Two faithful PRD readers
        # could reasonably surface either error_id.
        validate_error_is_one_of(res, ["ERR_INVALID_STATE", "ERR_ENTITY_DISSOLVED"])

    def test_post_dissolve_create_annual_report_returns_entity_dissolved(self, api):
        """PRD §3.12: "Once `DISSOLVED`, every subsequent child mutation is rejected
        with `ERR_ENTITY_DISSOLVED` — the entity becomes read-only."

        Design: Difficulty/cross_entity_state_dependency/cesd_annual_report_file_requires_non_dissolved_business_entity
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="QUEBEC2 LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        api.dissolve_business_entity(be["id"], make_filer_headers(be["id"]))
        # Attempting any further child mutation on the dissolved parent is
        # rejected with ERR_ENTITY_DISSOLVED per §3.12 (no state-machine path
        # competes here: no AR yet exists, so the dissolved-gate is the only
        # rule that bites).
        res = api.create_annual_report(
            be["id"], {"period_year": 2025}, make_filer_headers(be["id"])
        )
        validate_error(res, "ERR_ENTITY_DISSOLVED")


class TestBOISubmitRequiresActiveRegisteredAgent:
    """PRD §3.11: submit precondition — exactly one RegisteredAgent in ACTIVE
    for the parent. When the only ACTIVE agent has resigned, submit fails.
    """

    def test_boi_submit_without_active_agent_returns_invalid_state(self, api):
        """PRD §3.11: "Submission re-checks the member-list integrity, requires
        that the parent's `status` is not `DISSOLVED`, requires exactly one
        `RegisteredAgent` in `ACTIVE` for the parent, and enforces the deadline
        check."
        PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/cesd_boi_submit_requires_active_registered_agent
        """
        set_clock("2026-01-01T00:00:00Z")
        be, ra = setup_active_llc(
            legal_name="ROMEO LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        boi = create_draft_boi_disclosure(be, triggering_event="FORMATION")
        # Resign the only ACTIVE agent.
        api.resign_registered_agent(ra["id"], make_filer_headers(be["id"]))
        # Now submit — no ACTIVE agent for the parent.
        res = api.submit_boi_disclosure(boi["id"], make_filer_headers(be["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_boi_submit_succeeds_when_active_agent_present(self, api):
        """PRD §3.11: "The filer submits it (`DRAFT → SUBMITTED`), at which point
        `submitted_at` is stamped from the current clock UTC"
        PRD §3.11: "requires exactly one `RegisteredAgent` in `ACTIVE` for the parent"

        Design: Difficulty/cross_entity_state_dependency/cesd_boi_submit_requires_active_registered_agent
        """
        set_clock("2026-01-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="ROMEO ALIVE LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        boi = create_draft_boi_disclosure(be, triggering_event="FORMATION")
        # Active agent IS present from setup_active_llc.
        res = api.submit_boi_disclosure(boi["id"], make_filer_headers(be["id"]))
        body = validate_success(res, 200)
        assert body["status"] == "SUBMITTED"
