"""Award cascade, originality cross-check, and prize-withholding
calculation (PRD §3.7).

This file targets several difficulty-design instances:
- prize_withholding_resident_vs_non_resident
- submission_originality_preliminary_vs_final
- award_to_copyright_to_payment_chain
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PO,
    award_payload,
    setup_in_final_aggregating,
    setup_prize_withholding_pair,
    validate_paginated,
    validate_success,
)


class TestAwardCascade:

    def test_award_transitions_project_to_AWARDED(self, api):
        """PRD §3.7: 'The transition moves the project from IN_FINAL to
        AWARDED.'

        Claim: a valid award call leaves Project.status == AWARDED.
        """
        ctx = setup_in_final_aggregating(n_submissions=1)
        project = ctx["project"]
        sub = ctx["submissions"][0]
        tier = ctx["tiers"][0]
        resp = api.award_project(
            project["id"],
            award_payload(tier_assignments=[
                {"prize_tier_id": tier["id"], "submission_id": sub["id"]},
            ]),
            PO,
        )
        data = validate_success(resp)
        assert data["status"] == "AWARDED"

    def test_award_sets_anonymity_unmasked_at(self, api):
        """PRD §3.7: 'Project.anonymity_unmasked_at is set to the
        server clock, lifting the anonymity regime described in §2.10.'

        Claim: after award, Project.anonymity_unmasked_at is non-null.
        """
        ctx = setup_in_final_aggregating(n_submissions=1)
        project = ctx["project"]
        sub = ctx["submissions"][0]
        tier = ctx["tiers"][0]
        resp = api.award_project(
            project["id"],
            award_payload(tier_assignments=[
                {"prize_tier_id": tier["id"], "submission_id": sub["id"]},
            ]),
            PO,
        )
        data = validate_success(resp)
        assert data.get("anonymity_unmasked_at") is not None, (
            "anonymity_unmasked_at must be set after AWARDED transition"
        )

    def test_award_cascades_winner_status_for_MAIN(self, api):
        """PRD §3.7: 'Each selected submission's status flips to WINNER
        if the tier's tier_kind is MAIN or to RUNNER_UP if CONSOLATION.'

        Claim: after award, the selected MAIN-tier submission has
        status=WINNER.

        # difficulty: transitive_cascade/award_to_copyright_to_payment_chain
        """
        ctx = setup_in_final_aggregating(n_submissions=1)
        project = ctx["project"]
        sub = ctx["submissions"][0]
        tier = ctx["tiers"][0]
        validate_success(api.award_project(
            project["id"],
            award_payload(tier_assignments=[
                {"prize_tier_id": tier["id"], "submission_id": sub["id"]},
            ]),
            PO,
        ))
        sub_after = validate_success(api.get_submission(sub["id"], PO))
        assert sub_after["status"] == "WINNER", (
            f"Selected MAIN-tier submission must be WINNER, got "
            f"{sub_after['status']!r}"
        )

    def test_award_cascades_PrizePayment_creation(self, api):
        """PRD §3.7: 'for each PrizeTier with a selected winner a
        PrizePayment is auto-created in SCHEDULED.'

        Claim: after award, a PrizePayment exists for the project with
        status=SCHEDULED.

        # difficulty: transitive_cascade/award_to_copyright_to_payment_chain
        """
        ctx = setup_in_final_aggregating(n_submissions=1)
        project = ctx["project"]
        sub = ctx["submissions"][0]
        tier = ctx["tiers"][0]
        validate_success(api.award_project(
            project["id"],
            award_payload(tier_assignments=[
                {"prize_tier_id": tier["id"], "submission_id": sub["id"]},
            ]),
            PO,
        ))
        resp = api.list_prize_payments(PO,
                                        params={"project_id": project["id"]})
        items, _ = validate_paginated(resp)
        assert len(items) >= 1, "PrizePayment must be auto-created on award"
        pp = items[0]
        assert pp["status"] == "SCHEDULED", (
            f"PrizePayment must be SCHEDULED on creation; got {pp['status']!r}"
        )
        assert pp["prize_tier_id"] == tier["id"]
        assert pp["gross_amount_cents"] == tier["gross_amount_cents"]


class TestPrizeWithholding:
    """PRD §3.7: 'When the residency is RESIDENT, the withholding is
    the gross multiplied by the resident rate of 0.20 and then rounded
    half up to integer cents; when the residency is NON_RESIDENT, the
    withholding is split across two tiers measured in cents — the
    portion at or below the tier-break boundary of 400,000 cents (i.e.,
    4,000.00 in major units) is multiplied by the non-resident tier-1
    rate of 0.20 and rounded half up to integer cents, the portion
    strictly above the boundary is multiplied by the non-resident
    tier-2 rate of 0.30 and rounded half up to integer cents, and the
    two rounded tier amounts are then summed.'"""

    def test_resident_flat_20_withholding(self, api):
        """PRD §3.7: 'When the residency is RESIDENT, the withholding
        is the gross multiplied by the resident rate of 0.20 and then
        rounded half up to integer cents.'

        Claim: gross 1_000_000 cents, RESIDENT -> withholding=200_000,
        net=800_000.

        # difficulty: dual_variant_calc/prize_withholding_resident_vs_non_resident
        """
        ctx = setup_prize_withholding_pair(gross_amount_cents=1_000_000)
        pp = ctx["resident"]["payment"]
        assert pp["gross_amount_cents"] == 1_000_000
        assert pp["withholding_cents"] == 200_000, (
            f"RESIDENT 20% on 1_000_000 must yield 200_000; got "
            f"{pp['withholding_cents']}"
        )
        assert pp["net_amount_cents"] == 800_000

    def test_non_resident_tiered_withholding(self, api):
        """PRD §3.7: 'when the residency is NON_RESIDENT, the
        withholding is split across two tiers measured in cents — the
        portion at or below the tier-break boundary of 400,000 cents
        ... is multiplied by ... 0.20 ... the portion strictly above the
        boundary is multiplied by ... 0.30 ... and the two rounded tier
        amounts are then summed.'

        Claim: gross 1_000_000 cents, NON_RESIDENT ->
        tier1 = 400_000 * 0.20 = 80_000
        tier2 = 600_000 * 0.30 = 180_000
        withholding = 260_000, net = 740_000.

        # difficulty: dual_variant_calc/prize_withholding_resident_vs_non_resident
        """
        ctx = setup_prize_withholding_pair(gross_amount_cents=1_000_000)
        pp = ctx["non_resident"]["payment"]
        assert pp["gross_amount_cents"] == 1_000_000
        assert pp["withholding_cents"] == 260_000, (
            f"NON_RESIDENT 1_000_000 must yield withholding=260_000 "
            f"(80_000 + 180_000); got {pp['withholding_cents']}"
        )
        assert pp["net_amount_cents"] == 740_000


class TestFinalCrossCheckOriginality:

    def test_final_crosscheck_originality_score_recomputed(self, api):
        """PRD §3.7: 'At the same instant, the originality cross-check
        is recomputed for every winning submission: originality_variant
        is set to FINAL_CROSSCHECK, and a new originality_score is
        produced by the formula described next.'

        Claim: after award, the winning submission's
        originality_variant == 'FINAL_CROSSCHECK'.

        # difficulty: dual_variant_calc/submission_originality_preliminary_vs_final
        """
        ctx = setup_in_final_aggregating(n_submissions=1)
        project = ctx["project"]
        sub = ctx["submissions"][0]
        tier = ctx["tiers"][0]
        validate_success(api.award_project(
            project["id"],
            award_payload(tier_assignments=[
                {"prize_tier_id": tier["id"], "submission_id": sub["id"]},
            ]),
            PO,
        ))
        sub_after = validate_success(api.get_submission(sub["id"], PO))
        assert sub_after.get("originality_variant") == "FINAL_CROSSCHECK", (
            f"originality_variant must flip to FINAL_CROSSCHECK on award; "
            f"got {sub_after.get('originality_variant')!r}"
        )

    def test_final_crosscheck_score_not_higher_than_preliminary(self, api):
        """PRD §3.7: 'Because the peer term can only raise the combined
        similarity above the public-only number, the final-cross-check
        score is never higher than the original preliminary-scan score
        on the same asset and can be strictly lower.'

        Claim: final-crosscheck originality_score <= preliminary scan
        score for the same submission.

        # difficulty: dual_variant_calc/submission_originality_preliminary_vs_final
        """
        ctx = setup_in_final_aggregating(n_submissions=2)
        project = ctx["project"]
        # Both submissions are ADVANCING_FINAL; capture their
        # preliminary scores via the sub status BEFORE award.
        prelim_scores = {}
        for s in ctx["submissions"]:
            s_now = validate_success(api.get_submission(s["id"], PO))
            prelim_scores[s["id"]] = s_now.get("originality_score")

        # Award only the first as winner (MAIN tier).
        tier = ctx["tiers"][0]
        first_sub = ctx["submissions"][0]
        validate_success(api.award_project(
            project["id"],
            award_payload(tier_assignments=[
                {"prize_tier_id": tier["id"],
                 "submission_id": first_sub["id"]},
            ]),
            PO,
        ))
        sub_after = validate_success(api.get_submission(first_sub["id"], PO))
        # Final-cross-check should be <= preliminary on the same asset.
        prelim = prelim_scores[first_sub["id"]]
        final_score = sub_after.get("originality_score")
        assert isinstance(prelim, (int, float))
        assert isinstance(final_score, (int, float))
        assert final_score <= prelim + 1e-9, (
            f"final-cross-check originality_score ({final_score}) must "
            f"not exceed preliminary score ({prelim})"
        )
