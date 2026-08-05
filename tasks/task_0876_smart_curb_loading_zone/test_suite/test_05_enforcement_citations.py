"""Enforcement: citation fine ISSUE vs UPHELD-late variant, dismiss receivable invariant.

Covers difficulty queue A: dual_variant_calc (citation fine), compensating_invariant
(outstanding_fines_cents restored on dismiss). Plus corner case: adjudicate a
non-disputed citation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_curb_planner_headers,
    make_enforcement_officer_headers,
    advance_clock,
    make_policy,
    make_zone,
    make_permittee,
    make_citation,
    setup_disputed_citation,
)


class TestCitationFineIssueVsUpheldLate:
    """The same citation's fine is the base at ISSUE but base+25% when UPHELD past due."""

    def test_base_fine_stamped_at_issue(self, api):
        """PRD §3.6: "computes its base fine_due_cents from the violation type: an OVERSTAY
        is 7,500 cents, a NO_PERMIT is 15,000 cents, an UNAUTHORIZED_ZONE is 10,000 cents,
        and a WRONG_DESIGNATION is 5,000 cents."

        Design: Difficulty/dual_variant_calc/citation_issue_vs_upheld_late
        """
        ctx = setup_disputed_citation(api, violation_type="OVERSTAY")
        assert ctx["base_fine_cents"] == 7500

    def test_late_upheld_applies_25_percent_penalty(self, api):
        """PRD §3.6: "if the logical clock is now past the citation's due_at, a 25% late
        penalty is applied by multiplying the base fine by 12500 basis points and rounding
        half-up — so a late-upheld OVERSTAY rises from 7,500 to 9,375 cents".

        Design: Difficulty/dual_variant_calc/citation_issue_vs_upheld_late
        """
        ctx = setup_disputed_citation(api, violation_type="OVERSTAY")  # issued at 2026-05-20, due 2026-06-03
        advance_clock(api, "2026-06-20T00:00:00Z")  # strictly past due_at
        upheld = get_success_data(
            api.adjudicate_citation(ctx["citation_id"], "UPHELD", make_enforcement_officer_headers("officer1")))
        assert upheld["status"] == "UPHELD"
        assert upheld["fine_due_cents"] == 9375


class TestCitationDismissReceivable:
    """outstanding_fines_cents rises on issue and is restored to pre-issue value on dismiss."""

    def test_outstanding_reflects_open_citation_before_dismiss(self, api):
        """PRD §3.1: "That outstanding balance is computed on demand as the sum of
        fine_due_cents across the permittee's citations whose status is ISSUED, DISPUTED,
        or UPHELD; citations that are PAID or DISMISSED leave the open set and no longer
        contribute."

        Design: Difficulty/compensating_invariant/citation_issue_dismiss_receivable
        """
        ctx = setup_disputed_citation(api, violation_type="OVERSTAY")
        permittee = validate_success(
            api.get_permittee(ctx["permittee_id"], make_curb_planner_headers("planner1")))
        assert permittee["outstanding_fines_cents"] == 7500

    def test_dismiss_restores_pre_issue_receivable(self, api):
        """PRD §3.6: "A decision of DISMISSED moves the citation to the terminal DISMISSED
        state and recomputes the permittee's outstanding_fines_cents, restoring the
        pre-issue receivable as the citation leaves the open set."

        Design: Difficulty/compensating_invariant/citation_issue_dismiss_receivable
        """
        ctx = setup_disputed_citation(api, violation_type="OVERSTAY")
        dismissed = get_success_data(
            api.adjudicate_citation(ctx["citation_id"], "DISMISSED", make_enforcement_officer_headers("officer1")))
        assert dismissed["status"] == "DISMISSED"
        permittee = validate_success(
            api.get_permittee(ctx["permittee_id"], make_curb_planner_headers("planner1")))
        assert permittee["outstanding_fines_cents"] == 0


def test_adjudicate_issued_citation_rejected_invalid_state(api):
    """PRD §3.6: "Any of these citation actions attempted from a state where it is not
    defined is refused with ERR_INVALID_STATE."

    Design: Corner/state_machines/adjudicate_non_disputed_invalid
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    permittee = make_permittee(api)
    citation = make_citation(api, zone["id"], permittee["id"], "NO_PERMIT")  # ISSUED, never disputed
    resp = api.adjudicate_citation(citation["id"], "UPHELD", make_enforcement_officer_headers("officer1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_citation(citation["id"], make_enforcement_officer_headers("officer1")))
    assert fetched["status"] == "ISSUED"
