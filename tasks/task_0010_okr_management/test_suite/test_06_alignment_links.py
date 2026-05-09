"""Alignment graph: declare, accept, reject, impact scores, circular reference (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_alignment_link_payload, create_reject_link_payload,
    setup_alignment_pair, setup_accepted_alignment_pair,
    make_employee_headers,
)


# ---------------------------------------------------------------------------
# Difficulty-design: non_linear_state_machine/alignment_link_branching_fork
# ---------------------------------------------------------------------------

class TestAlignmentLinkBranching:
    """# difficulty: non_linear_state_machine/alignment_link_branching_fork"""

    def test_accept_link_advances_to_accepted_with_impact_scores(self, api):
        """PRD §3.5: "Accepting the link advances `AlignmentLink.status` from `PENDING` to `ACCEPTED`".
        PRD §3.5: "On success, `accepted_at` is set, and the two impact scores are computed".

        Claim: A.progress=0.8, B.progress=0.5, single accepted upstream → accept →
        L.status=ACCEPTED, accepted_at set, forward_impact=0.5600, backward_impact=0.2500,
        rejection_reason is null.
        # difficulty: non_linear_state_machine/alignment_link_branching_fork
        # difficulty: dual_variant_calc/alignment_impact_forward_vs_backward
        """
        s = setup_alignment_pair(progress_a=0.8, progress_b=0.5)
        # Accept as B's owner
        b_headers = make_employee_headers(s["employee_b"]["id"])
        resp = api.accept_alignment_link(s["link"]["id"], b_headers)
        link = validate_success(resp)
        assert link["status"] == "ACCEPTED"
        assert link.get("accepted_at") is not None
        assert link.get("rejection_reason") is None
        # Impact scores
        assert float(link["forward_impact_score"]) == pytest.approx(0.5600, abs=1e-6)
        assert float(link["backward_impact_score"]) == pytest.approx(0.2500, abs=1e-6)

    def test_reject_link_advances_to_rejected_with_reason(self, api):
        """PRD §3.5: "Rejecting the link advances it from `PENDING` to `REJECTED`; the `rejection_reason` field must be supplied as a non-empty string."

        Claim: reject by downstream owner with reason → L.status=REJECTED, accepted_at null,
        rejection_reason set, both impact scores null.
        # difficulty: non_linear_state_machine/alignment_link_branching_fork
        """
        s = setup_alignment_pair(progress_a=0.6, progress_b=0.4)
        b_headers = make_employee_headers(s["employee_b"]["id"])
        resp = api.reject_alignment_link(
            s["link"]["id"],
            create_reject_link_payload("out of scope"),
            b_headers,
        )
        link = validate_success(resp)
        assert link["status"] == "REJECTED"
        assert link.get("accepted_at") is None
        assert link.get("forward_impact_score") in (None,)
        assert link.get("backward_impact_score") in (None,)
        assert link["rejection_reason"] == "out of scope"


# ---------------------------------------------------------------------------
# Difficulty-design: dual_variant_calc/alignment_impact_forward_vs_backward
# ---------------------------------------------------------------------------

class TestAlignmentImpactDualVariant:
    """# difficulty: dual_variant_calc/alignment_impact_forward_vs_backward"""

    def test_forward_and_backward_impact_diverge_for_same_link(self, api):
        """PRD §3.5: "the upstream objective's current `Objective.progress` multiplied by an attenuation factor of seven-tenths (0.7), rounded half up to 4 decimal places".
        PRD §3.5: "the downstream objective's current `Objective.progress` multiplied by an upstream-influence factor of one-half (0.5) and divided by the count of `ACCEPTED` upstream links flowing into the downstream objective".

        Claim: A.progress=0.8, B.progress=0.5, accepted-upstream-count=1 →
        forward=0.8*0.7=0.5600; backward=0.5*0.5/1=0.2500. Different numbers.
        # difficulty: dual_variant_calc/alignment_impact_forward_vs_backward
        """
        s = setup_accepted_alignment_pair(progress_a=0.8, progress_b=0.5)
        link = s["link"]
        assert float(link["forward_impact_score"]) == pytest.approx(0.5600, abs=1e-6)
        assert float(link["backward_impact_score"]) == pytest.approx(0.2500, abs=1e-6)
        assert float(link["forward_impact_score"]) != float(link["backward_impact_score"])


# ---------------------------------------------------------------------------
# Duplicate links and circular reference
# ---------------------------------------------------------------------------

class TestLinkConstraints:
    def test_duplicate_link_declaration_rejected(self, api):
        """PRD §3.5: "duplicate declarations are rejected with `ERR_DUPLICATE_LINK`".

        Claim: same upstream/downstream pair declared twice → second → ERR_DUPLICATE_LINK.
        """
        s = setup_alignment_pair()
        # Try to create another link with same pair
        payload = create_alignment_link_payload(
            s["objective_a"]["id"], s["objective_b"]["id"], "SUPPORTS"
        )
        a_headers = make_employee_headers(s["employee_a"]["id"])
        resp = api.create_alignment_link(payload, a_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINK.value)

    def test_circular_reference_two_cycle_rejected(self, api):
        """PRD §3.5: "if accepting would introduce any directed cycle (including a 2-cycle, where another `ACCEPTED` link already runs in the opposite direction), the request is rejected with `ERR_CIRCULAR_REFERENCE`."

        Claim: link A→B accepted; declare reverse B→A; accept B→A → ERR_CIRCULAR_REFERENCE.
        """
        s = setup_accepted_alignment_pair(progress_a=0.5, progress_b=0.5)
        # Declare reverse link B→A
        a_headers = make_employee_headers(s["employee_a"]["id"])
        b_headers = make_employee_headers(s["employee_b"]["id"])
        reverse_payload = create_alignment_link_payload(
            s["objective_b"]["id"], s["objective_a"]["id"], "INFORMS"
        )
        rev_resp = api.create_alignment_link(reverse_payload, b_headers)
        rev_link = validate_success(rev_resp, expected_status=201)
        # Accepting reverse must fail with ERR_CIRCULAR_REFERENCE (acceptor is A's owner)
        accept_resp = api.accept_alignment_link(rev_link["id"], a_headers)
        validate_error(accept_resp, ApiErrorId.ERR_CIRCULAR_REFERENCE.value)


# ---------------------------------------------------------------------------
# Accept by non-owner is rejected
# ---------------------------------------------------------------------------

class TestAcceptOwnership:
    def test_accept_by_upstream_owner_rejected(self, api):
        """PRD §3.5: "the acting user to be the downstream objective's primary owner or an active co-owner".
        PRD §2.1: "When ownership is required but the acting user is neither the objective's `owner_user_id` nor an active co-owner, the response is `ERR_NOT_OWNER` (HTTP 403)."

        Claim: upstream owner attempts to accept → ERR_NOT_OWNER.
        """
        s = setup_alignment_pair(progress_a=0.5, progress_b=0.5)
        a_headers = make_employee_headers(s["employee_a"]["id"])
        resp = api.accept_alignment_link(s["link"]["id"], a_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)
