"""Difficulty Rule 4 — transitive_cascade.

Two cascade chains with different origins:
  (a) Clock-advance origin: clock → AR DRAFT→DELINQUENT → BE ACTIVE→DELINQUENT
      → posture RESTRICTED (3 hops).
  (b) Resign origin: POST /registered-agents/{id}/resign → RA ACTIVE→RESIGNED →
      posture GOOD_STANDING→RESTRICTED (2 hops).
"""
from test_helpers import (
    validate_success,
    set_clock,
    setup_active_llc,
    create_draft_annual_report,
    make_filer_headers,
    make_compliance_officer_headers,
)


class TestClockAdvanceThreeHopChain:
    """PRD §3.7 + §3.6: clock advance triggers AR→DELINQUENT, which cascades
    BE→DELINQUENT and posture→RESTRICTED.
    """

    def test_annual_report_flips_to_delinquent_after_clock_advance(self, api):
        """PRD §3.7: "Whenever the current clock UTC moves strictly past that
        deadline and the report is still in `DRAFT`, the system flips the report
        automatically from `DRAFT` to `DELINQUENT`"

        Design: Difficulty/transitive_cascade/tc_clock_advance_drives_three_hop_chain
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="JULIET HOP1 LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        assert ar["status"] == "DRAFT"
        set_clock("2025-05-01T00:00:00Z")
        ar_list = validate_success(
            api.list_annual_reports(be["id"], make_compliance_officer_headers()), 200
        )
        assert any(r["id"] == ar["id"] and r["status"] == "DELINQUENT" for r in ar_list)

    def test_business_entity_cascades_to_delinquent_with_restricted_posture(self, api):
        """PRD §3.6: "When a `DRAFT` annual report flips automatically to `DELINQUENT`
        (the deadline-driven transition described in §3.7), the parent is
        recomputed: `compliance_posture` moves to `RESTRICTED` and, if the parent was
        `ACTIVE`, its `status` also flips to `DELINQUENT` (the second hop of the
        cascade)."

        Design: Difficulty/transitive_cascade/tc_clock_advance_drives_three_hop_chain
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="JULIET HOP23 LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        create_draft_annual_report(be, 2024)
        set_clock("2025-05-01T00:00:00Z")
        be_after = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        # Hop 2 — BusinessEntity status ACTIVE → DELINQUENT.
        assert be_after["status"] == "DELINQUENT"
        # Hop 3 — posture recomputed to RESTRICTED.
        assert be_after["compliance_posture"] == "RESTRICTED"


class TestRegisteredAgentResignTwoHopChain:
    """PRD §3.3: voluntary resignation transitions RA ACTIVE→RESIGNED and
    recomputes parent posture; with no ACTIVE agent remaining, posture falls
    to RESTRICTED per §3.6.
    """

    def test_resign_transitions_agent_to_resigned(self, api):
        """PRD §3.3: "A `Filer` can resign a `RegisteredAgent`; the resource
        transitions from `ACTIVE` to `RESIGNED`, `resigned_at` is stamped from the
        current clock UTC, and the parent's `compliance_posture` is recomputed."

        Design: Difficulty/transitive_cascade/tc_registered_agent_resign_drives_two_hop_chain
        """
        set_clock("2026-02-01T00:00:00Z")
        be, ra = setup_active_llc(
            legal_name="KILO RA1 LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        assert ra["status"] == "ACTIVE"
        res = api.resign_registered_agent(ra["id"], make_filer_headers(be["id"]))
        resigned = validate_success(res, 200)
        assert resigned["status"] == "RESIGNED"

    def test_posture_flips_to_restricted_when_only_active_agent_resigns(self, api):
        """PRD §3.6: "if no `RegisteredAgent` for the parent is in `ACTIVE` status,
        the posture is `RESTRICTED`"
        PRD §3.3: "With no `ACTIVE` agent left, the posture typically falls to
        `RESTRICTED`."

        Design: Difficulty/transitive_cascade/tc_registered_agent_resign_drives_two_hop_chain
        """
        set_clock("2026-02-01T00:00:00Z")
        be, ra = setup_active_llc(
            legal_name="KILO RA2 LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        be_pre = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        assert be_pre["compliance_posture"] == "GOOD_STANDING"
        api.resign_registered_agent(ra["id"], make_filer_headers(be["id"]))
        be_post = validate_success(
            api.get_business_entity(be["id"], make_compliance_officer_headers()), 200
        )
        assert be_post["compliance_posture"] == "RESTRICTED"
