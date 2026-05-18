"""Appeal decision reconciliation cascade (PRD §3.5).

Covers the cascade hops that are reachable from the PRD-documented
endpoint surface: Appeal DECIDED → Assessment.capped_value update
(hop 1), and Assessment auto-FINALIZE when no other open Appeal
remains (hop 4 in PRD §3.5).

PRD §3.5 also describes hop 2 (TaxBill recompute) and hop 3
(Payment refund). PRD §3.4 first sentence says: 'A TaxBill is
created by the Treasurer once the underlying Assessment is
FINALIZED.' PRD §3.5 says Appeals require ISSUED or UNDER_APPEAL —
not FINALIZED. So at decide-time, the Assessment has not yet been
FINALIZED via the natural path, which means the TaxBill cannot have
been created via the Treasurer endpoint. The PRD §3.2 auto-create on
clock-driven Assessment auto-FINALIZE applies only when no Appeal
was filed; it does not specify whether the deciding-appeal-driven
auto-FINALIZE in PRD §3.5 hop 4 also auto-creates a bill. PRD §3.5
hop 2 says 'The TaxBill ... if one exists — is recomputed', which
phrasing handles both cases. The recompute and refund variants
therefore exercise behavior that requires a bill EXISTING
pre-decide — a state the PRD prose does not constructively
describe a path to reach. The recompute+refund branches are
PRD-silent on the reachable construction path; this is flagged
below.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    decide_appeal,
    file_appeal,
    get_assessment,
    setup_heard_appeal,
    validate_error,
)


# ===========================================================================
# Hop 1 — Appeal DECIDED updates Assessment.capped_value (PRD §3.5).
# ===========================================================================
class TestCascadeHop1AssessmentUpdate:

    def test_reduced_updates_capped_value(self, api):
        """PRD §3.5: "The Assessment's capped_value is updated to
        decided_value if the outcome is REDUCED or INCREASED
        (unchanged if UPHELD); the Assessment's version and
        updated_at are bumped."

        Claim: REDUCED decide updates Assessment.capped_value to
        decided_value.

        # difficulty: transitive_cascade/appeal_decided_cascade_depth_3
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        prev_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="REDUCED", decided_value=400_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        assert re_asmt["capped_value"] == pytest.approx(
            400_000.00, abs=0.01,
        )
        # PRD §3.5: "the Assessment's version and updated_at are
        # bumped" — strict > on version.
        assert re_asmt["version"] > prev_asmt["version"]

    def test_increased_updates_capped_value(self, api):
        """PRD §3.5: "The Assessment's capped_value is updated to
        decided_value if the outcome is REDUCED or INCREASED
        (unchanged if UPHELD)".

        Claim: INCREASED decide updates Assessment.capped_value to
        decided_value (here 600000).

        # difficulty: non_linear_state_machine/appeal_branching_decisions
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="INCREASED", decided_value=600_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        assert re_asmt["capped_value"] == pytest.approx(
            600_000.00, abs=0.01,
        )

    def test_upheld_does_not_modify_capped_value(self, api):
        """PRD §3.5: "The Assessment's capped_value is updated to
        decided_value if the outcome is REDUCED or INCREASED
        (unchanged if UPHELD)".

        Claim: UPHELD decide leaves Assessment.capped_value
        unchanged.

        # difficulty: non_linear_state_machine/appeal_branching_decisions
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        prev_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="UPHELD", decided_value=500_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        assert re_asmt["capped_value"] == pytest.approx(
            prev_asmt["capped_value"], abs=0.01,
        )


# ===========================================================================
# Hop 4 — Last DECIDED auto-FINALIZES Assessment (PRD §3.5).
# ===========================================================================
class TestCascadeHop4AssessmentAutoFinalize:

    def test_decide_last_open_appeal_auto_finalizes_assessment(self, api):
        """PRD §3.5: "Finally, if no Appeal against the Assessment
        remains in FILED, SCHEDULED, or HEARD after this decision,
        the Assessment auto-transitions UNDER_APPEAL → FINALIZED."

        Claim: deciding the only open Appeal flips the Assessment
        from UNDER_APPEAL to FINALIZED.

        # difficulty: transitive_cascade/appeal_decided_cascade_depth_3
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="UPHELD", decided_value=500_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        assert re_asmt["status"] == "FINALIZED"

    def test_decide_one_of_two_open_appeals_keeps_under_appeal(self, api):
        """PRD §3.5: "Finally, if no Appeal against the Assessment
        remains in FILED, SCHEDULED, or HEARD after this decision,
        the Assessment auto-transitions UNDER_APPEAL → FINALIZED."

        Claim (negative form): when ANOTHER Appeal still remains in
        FILED on the Assessment, deciding the first does NOT
        auto-FINALIZE the Assessment.
        """
        ctx = setup_heard_appeal(market_value=500_000.00)
        # File a second Appeal so the Assessment has TWO open Appeals.
        a2 = file_appeal(
            owner=ctx["owner"], property_id=ctx["property"]["id"],
            assessment_id=ctx["assessment"]["id"],
            claimed_value=200_000.00,
        )
        # Decide the FIRST appeal.
        decide_appeal(
            property_id=ctx["property"]["id"],
            appeal_id=ctx["appeal"]["id"],
            officer=ctx["officer"],
            decision_outcome="UPHELD", decided_value=500_000.00,
        )
        re_asmt = get_assessment(
            ctx["property"]["id"], ctx["assessment"]["id"],
        )
        # Other open Appeal still in FILED → Assessment stays
        # UNDER_APPEAL.
        assert re_asmt["status"] == "UNDER_APPEAL", (
            f"Assessment must remain UNDER_APPEAL while Appeal {a2['id']} "
            f"is still open in FILED; got {re_asmt['status']}"
        )
