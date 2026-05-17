"""Refill-too-soon: half-open day-granularity interval check.

PRD §3.5 refill-too-soon, §2.8 rung 9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    SECONDS_PER_DAY,
    adjudicate_claim,
    advance_clock,
    occ_payload,
    re_get_claim,
    setup_adjudicated_claim,
    setup_paid_claim,
    setup_reference_data,
    submit_claim,
    validate_error,
    validate_success,
)


class TestRefillTooSoon:
    """PRD §3.5: "The refill-too-soon check applies half-open interval
    semantics at one-day granularity. … Two half-open intervals
    [a, a+da) and [b, b+db) overlap when a is strictly less than
    b+db and b is strictly less than a+da; adjacency at the
    boundary — a candidate that starts exactly when the prior
    interval ends — is allowed and does not count as overlap.\""""

    def test_overlap_within_prior_supply_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "Any overlap with a non-self prior claim yields
        ERR_REFILL_TOO_SOON."
        PRD §2.8 rung 9: "Refill-too-soon — for claim adjudicate, the
        candidate's projected supply window must not overlap any
        existing ADJUDICATED or PAID claim for the same member-drug
        pair; otherwise ERR_REFILL_TOO_SOON (409)."

        Claim: with C1 adjudicated at T=0 (30-day supply, window
        [0,30)), adjudicating C2 at T=29 (window [29,59)) overlaps
        and is rejected.
        """
        _, drug, _, member = setup_reference_data()
        c1_adj = setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        c2 = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        # Advance to T=29d.
        advance_clock(29 * SECONDS_PER_DAY)
        res = api.adjudicate_claim(
            c2["id"], occ_payload(version=c2["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_REFILL_TOO_SOON")

    def test_adjacent_supply_window_accepted(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "adjacency at the boundary — a candidate that
        starts exactly when the prior interval ends — is allowed and
        does not count as overlap."

        Claim: with C1 adjudicated at T=0 (30-day supply, [0,30)),
        adjudicating C3 at T=30 (window [30,60)) is allowed.
        """
        _, drug, _, member = setup_reference_data()
        setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        c3 = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        advance_clock(30 * SECONDS_PER_DAY)
        res = api.adjudicate_claim(
            c3["id"], occ_payload(version=c3["version"]),
            claims_adjudicator_headers,
        )
        adj = validate_success(res, 200)
        assert adj["status"] == "ADJUDICATED"

    def test_different_drug_no_overlap(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "For each existing Claim whose member_id and
        drug_id match the candidate …".

        Claim: a different drug for the same member does NOT trip
        refill-too-soon.
        """
        from test_helpers import (
            create_drug, create_formulary_entry, create_member,
            create_plan,
        )
        plan, drug_a, _, member = setup_reference_data()
        # Add a second drug + formulary entry on the same plan.
        drug_b = create_drug()
        create_formulary_entry(plan_id=plan["id"], drug_id=drug_b["id"],
                               tier=3, copay_cents=0)
        setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug_a["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        c2 = submit_claim(
            member_id=member["id"], drug_id=drug_b["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        # Same instant — different drug should be fine.
        res = api.adjudicate_claim(
            c2["id"], occ_payload(version=c2["version"]),
            claims_adjudicator_headers,
        )
        adj = validate_success(res, 200)
        assert adj["status"] == "ADJUDICATED"

    def test_rejected_prior_claim_does_not_block(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §3.5: "REJECTED and REVERSED claims are not consulted
        in this check."

        Claim: a prior REJECTED claim for the same (member, drug)
        does not block a same-instant adjudicate on a fresh claim.
        """
        plan, drug, _, member = setup_reference_data()
        # Create a specialty=False drug, then create another claim
        # that will be REJECTED due to wrong channel. Easiest path:
        # adjudicate twice and let the second one be REJECTED, then
        # submit a third and try.
        # Use a specialty drug so the rejection cause is clean.
        from test_helpers import create_drug, create_formulary_entry
        special_drug = create_drug(is_specialty=True)
        create_formulary_entry(plan_id=plan["id"],
                               drug_id=special_drug["id"],
                               tier=3, copay_cents=0)
        bad = submit_claim(
            member_id=member["id"], drug_id=special_drug["id"],
            channel="RETAIL_30",  # wrong channel for specialty drug
            days_supply=30, quantity=1,
        )
        rej = api.adjudicate_claim(
            bad["id"], occ_payload(version=bad["version"]),
            claims_adjudicator_headers,
        )
        validate_error(rej, "ERR_SPECIALTY_CHANNEL_REQUIRED")
        # After rejection, claim status -> REJECTED.
        rejected_claim = re_get_claim(bad["id"])
        assert rejected_claim["status"] == "REJECTED"
        # Now submit a fresh claim with the right channel and
        # adjudicate — should succeed because the REJECTED row is
        # not consulted.
        c_ok = submit_claim(
            member_id=member["id"], drug_id=special_drug["id"],
            channel="SPECIALTY", days_supply=30, quantity=1,
        )
        ok_res = api.adjudicate_claim(
            c_ok["id"], occ_payload(version=c_ok["version"]),
            claims_adjudicator_headers,
        )
        adj = validate_success(ok_res, 200)
        assert adj["status"] == "ADJUDICATED"
