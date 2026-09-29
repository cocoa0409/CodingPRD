"""The two deepest cascades: five levels forward from a result, four levels back."""
import pytest

from test_helpers import fixtures as fx, parse_instant


#: A property whose first-party capacity is deliberately smaller than the
#: mobilization charge, so the overflow reaches the liability bucket.
NARROW_COVERAGE = {
    "first_party_coverage_limit_cents": 100000,
    "third_party_sublimit_cents": 5000000,
}


def _project_with_live_tenders():
    """Confirmation sampling open, with both carrier files already tendered."""
    ctx = fx.project_at_sampling(property_overrides=NARROW_COVERAGE)
    ctx["first_party_notification"] = fx.create_notification(
        ctx["project"]["id"], "FIRST_PARTY"
    )
    ctx["third_party_notification"] = fx.create_notification(
        ctx["project"]["id"], "THIRD_PARTY_LIABILITY"
    )
    return ctx


class TestCascadeFromLaboratoryResult:
    def test_result_cascades_through_sample_classification_volume_and_cost(self, api):
        """PRD §2.7: "The deepest cascade in the system runs five levels from a single laboratory result posting: the sample reaches `RESULTED`; the project's confirmation round completes and the project advances to `ASSESSED` with its classification recomputed; the classification routes the project onward to `CLEARED` or to `REMEDIATION_ACTIVE` with a fresh remediation volume and cost; the new cost re-runs the insurance waterfall over the project's notifications; and each rewritten notification then re-derives its own status."
        PRD §3.6: "Otherwise `max_tph_mg_kg` is the highest `tph_mg_kg` in the set and `max_benzene_mg_kg` the highest `benzene_mg_kg`, and the class is decided by two tiers of strictly-greater-than comparisons: the class is `GROSS` when `max_tph_mg_kg` exceeds 5000.0 mg/kg or `max_benzene_mg_kg` exceeds 5.0 mg/kg; failing that it is `ELEVATED` when `max_tph_mg_kg` exceeds the 500.0 mg/kg action level or `max_benzene_mg_kg` exceeds the 0.5 mg/kg action level; and failing both it is `CLEAN`."
        PRD §2.7: "Second, project-level flags that record that something *has happened* are latches: `remediation_started` is set true the first time a project enters `REMEDIATION_ACTIVE` and is never reset, and `contamination_disclosure_required` is set true the first time the project's `contamination_class` becomes `ELEVATED` or `GROSS` and is likewise never reset, even when a later round classifies `CLEAN`."
        PRD §3.6: "On success the sample transitions `AT_LAB → RESULTED`, `reported_at` is stamped from the logical clock, and two timing figures are derived: `turnaround_hours` is the interval from `received_at` to `reported_at` in hours rounded half up to two decimal places, and `turnaround_breach` is true only when that figure strictly exceeds the lab's `committed_turnaround_hours` — a turnaround landing exactly on the commitment is not a breach."

        Design: Difficulty/transitive_cascade/cascade_depth_five_from_lab_result_to_insurance_notification_status
        """
        ctx = _project_with_live_tenders()
        sample = fx.collect_sample_with_result(ctx, 6200.0, 1.2, "TANK_BOTTOM", 96)

        assert sample["status"] == "RESULTED", (
            f"level one: the sample must reach RESULTED, got {sample['status']}"
        )
        assert sample["turnaround_hours"] == pytest.approx(0.0, abs=0.01), (
            "receipt and reporting happened at the same logical instant, so the "
            f"turnaround is 0.0 hours, got {sample['turnaround_hours']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["contamination_class"] == "GROSS", (
            "6200.0 mg/kg strictly exceeds the 5000.0 mg/kg gross level, got "
            f"{project['contamination_class']}"
        )
        assert project["max_tph_mg_kg"] == pytest.approx(6200.0, abs=0.01), (
            f"the round maximum must be the posted figure, got {project['max_tph_mg_kg']}"
        )
        assert project["status"] == "REMEDIATION_ACTIVE", (
            "a gross classification routes the project onward from ASSESSED, got "
            f"{project['status']}"
        )
        assert project["remediation_started"] is True, (
            "entering REMEDIATION_ACTIVE latches the remediation flag"
        )
        assert project["contamination_disclosure_required"] is True, (
            "a gross classification latches the disclosure requirement"
        )
        assert project["remediation_volume_cubic_yards"] == pytest.approx(
            29.63, abs=0.01
        ), (
            "one impacted sample at 96 inches gives 29.63 cubic yards, got "
            f"{project['remediation_volume_cubic_yards']}"
        )
        assert project["remediation_volume_basis"] == "PROVISIONAL_GRID", (
            f"nothing has been dug yet, got {project['remediation_volume_basis']}"
        )
        assert project["remediation_cost_cents"] == 185000, (
            "with the latch set and no change orders the cost is the flat "
            f"mobilization charge, got {project['remediation_cost_cents']}"
        )

    def test_result_cascade_reaches_the_waterfall_and_the_notification_status(
        self, api
    ):
        """PRD §3.8: "Bucket one is first-party property coverage, whose capacity is the property's `first_party_coverage_limit_cents`. `first_party_allocated_cents` is the smaller of the project's `remediation_cost_cents` and that capacity."
        PRD §3.8: "It equals the property's `third_party_sublimit_cents` **only if** the project has at least one notification whose `notification_kind` is `THIRD_PARTY_LIABILITY` and whose `status` is `OPEN`, `RESERVED` or `THIRD_PARTY_REVIEW`; with no such live tender on the project, bucket two's capacity is zero."
        PRD §3.8: "Each time the waterfall rewrites a notification, that notification re-derives its own `status` from the freshly written figures, and the rule is a strict cascade with no memory: the status becomes `THIRD_PARTY_REVIEW` when `third_party_allocated_cents` is greater than zero; failing that, `RESERVED` when `reserve_amount_cents` is greater than zero; and failing both, `OPEN`."
        PRD §3.8: "Every non-closed notification on the project carries the identical triple, and the three parts always sum exactly to the project's `remediation_cost_cents`."

        Design: Difficulty/transitive_cascade/cascade_depth_five_from_lab_result_to_insurance_notification_status
        """
        ctx = _project_with_live_tenders()
        fx.collect_sample_with_result(ctx, 6200.0, 1.2, "TANK_BOTTOM", 96)

        first_party = fx.read_notification(ctx["first_party_notification"]["id"])
        assert first_party["first_party_allocated_cents"] == 100000, (
            "bucket one fills to the 100,000-cent first-party capacity, got "
            f"{first_party['first_party_allocated_cents']}"
        )
        assert first_party["third_party_allocated_cents"] == 85000, (
            "the 85,000-cent remainder falls into the liability sublimit, got "
            f"{first_party['third_party_allocated_cents']}"
        )
        assert first_party["homeowner_out_of_pocket_cents"] == 0, (
            "nothing is left for the homeowner, got "
            f"{first_party['homeowner_out_of_pocket_cents']}"
        )
        assert first_party["reserve_amount_cents"] == 185000, (
            "the carrier's total exposure is the sum of the first two buckets, got "
            f"{first_party['reserve_amount_cents']}"
        )
        assert first_party["status"] == "THIRD_PARTY_REVIEW", (
            "a positive third-party share takes precedence in the status cascade, got "
            f"{first_party['status']}"
        )

        third_party = fx.read_notification(ctx["third_party_notification"]["id"])
        assert third_party["status"] == "THIRD_PARTY_REVIEW", (
            "every non-closed notification carries the identical triple and therefore "
            f"the identical derived status, got {third_party['status']}"
        )
        assert (
            third_party["first_party_allocated_cents"]
            + third_party["third_party_allocated_cents"]
            + third_party["homeowner_out_of_pocket_cents"]
        ) == 185000, "the three parts must sum exactly to the remediation cost"


class TestCascadeFromClosureRescission:
    def test_rescission_walks_the_project_back_into_remediation(self, api):
        """PRD §2.7: "A mirror-image cascade runs four levels from the rescission of a closure letter: the letter becomes `RESCINDED`; the project returns to `REMEDIATION_ACTIVE`; every approved trust-fund claim on the project is walked back to review; and the notifications' allocations and statuses are rewritten."
        PRD §3.9: "The letter transitions `ISSUED → RESCINDED` with `rescinded_at` stamped from the logical clock, and a four-level cascade follows."
        PRD §3.9: "The project transitions `CLOSED_NFA → REMEDIATION_ACTIVE`, its `contamination_class` is reset to `UNCLASSIFIED`, both `remediation_volume_cubic_yards` and `remediation_volume_basis` are reset to null, and `remediation_started` remains true."

        Design: Difficulty/transitive_cascade/cascade_depth_four_from_nfa_rescission_to_claim_and_reserve_revert
        """
        ctx = fx.project_closed_after_remediation()
        letter = fx.rescind_nfa_letter(ctx["nfa_letter"]["id"])

        assert letter["status"] == "RESCINDED", (
            f"the letter must reach RESCINDED, got {letter['status']}"
        )
        assert parse_instant(letter["rescinded_at"]) == parse_instant(
            "2026-08-06T13:00:00Z"
        ), (
            "the rescission instant is stamped from the logical clock, got "
            f"{letter['rescinded_at']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "REMEDIATION_ACTIVE", (
            f"the project must reopen remediation, got {project['status']}"
        )
        assert project["contamination_class"] == "UNCLASSIFIED", (
            "the classification no longer describes the site, got "
            f"{project['contamination_class']}"
        )
        assert project["remediation_volume_cubic_yards"] is None, (
            "the volume is cleared, got "
            f"{project['remediation_volume_cubic_yards']}"
        )
        assert project["remediation_volume_basis"] is None, (
            f"the basis is cleared with it, got {project['remediation_volume_basis']}"
        )
        assert project["remediation_started"] is True, (
            "the latch records that remediation happened and is never reset"
        )
        assert project["remediation_cost_cents"] == 185000, (
            "the recomputed cost is the mobilization charge with no change orders, got "
            f"{project['remediation_cost_cents']}"
        )

    def test_rescission_returns_the_approved_claim_to_review_and_reverts_the_reserve(
        self, api
    ):
        """PRD §3.9: "The project's departure from `CLOSED_NFA` then walks back every `TrustFundClaim` on it whose `status` is `APPROVED`: each is transitioned `APPROVED → UNDER_REVIEW`, its `reimbursed_amount_cents` is reset to 0, its `decided_at` is cleared to null, its `unreimbursed_balance_cents` is recomputed — which, with nothing reimbursed, restores it to the full `eligible_amount_cents` — and the code `NFA_RESCINDED_REVALIDATION_REQUIRED` is appended to its `eligibility_findings`, which like all finding lists is kept sorted ascending."
        PRD §3.9: "Finally the project's re-entry into `REMEDIATION_ACTIVE` recomputes `remediation_cost_cents`, which re-runs the insurance waterfall over every notification of the project whose `status` is not `CLOSED`, and each rewritten notification re-derives its `status` exactly as described in §3.8."

        Design: Difficulty/transitive_cascade/cascade_depth_four_from_nfa_rescission_to_claim_and_reserve_revert
        """
        ctx = fx.project_closed_after_remediation()
        fx.rescind_nfa_letter(ctx["nfa_letter"]["id"])

        claim = fx.read_claim(ctx["claim"]["id"])
        assert claim["status"] == "UNDER_REVIEW", (
            f"an approved claim is walked back to review, got {claim['status']}"
        )
        assert claim["decided_at"] is None, (
            f"the decision instant is cleared, got {claim['decided_at']}"
        )
        assert claim["reimbursed_amount_cents"] == 0, (
            f"nothing stands reimbursed, got {claim['reimbursed_amount_cents']}"
        )
        assert claim["unreimbursed_balance_cents"] == 818500, (
            "with nothing reimbursed the balance is the full eligible amount, got "
            f"{claim['unreimbursed_balance_cents']}"
        )
        assert (
            "NFA_RESCINDED_REVALIDATION_REQUIRED" in claim["eligibility_findings"]
        ), (
            "the revalidation requirement must be recorded on the claim, got "
            f"{claim['eligibility_findings']}"
        )

        notification = fx.read_notification(ctx["notification"]["id"])
        assert notification["first_party_allocated_cents"] == 185000, (
            "the default 2,000,000-cent capacity absorbs the whole cost, got "
            f"{notification['first_party_allocated_cents']}"
        )
        assert notification["third_party_allocated_cents"] == 0, (
            "with no live liability tender bucket two's capacity is zero, got "
            f"{notification['third_party_allocated_cents']}"
        )
        assert notification["homeowner_out_of_pocket_cents"] == 0, (
            "nothing overflows to the homeowner, got "
            f"{notification['homeowner_out_of_pocket_cents']}"
        )
        assert notification["status"] == "RESERVED", (
            "a reserve with no third-party share derives RESERVED, got "
            f"{notification['status']}"
        )
