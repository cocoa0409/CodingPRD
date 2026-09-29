"""Request payload builders.

Every builder returns the request body the PRD declares for its endpoint, with
plausible defaults that callers override by keyword. Note that several request
field names differ from the stored field names -- the request carries
`strategy_name`, `window_name`, `tranche_name`, `complaint_narrative`,
`gross_value_cents` and `security_lot_count`, while the resource exposes
`strategy_label`, `window_label`, `tranche_label`, `complaint_detail`,
`in_kind_market_value_cents` / `in_kind_lot_count` / `cash_amount_cents`.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import fame_for_zero_variance
from .types import (
    AmendmentAction,
    AuditBasis,
    AuditResolution,
    Cohort,
    ElectionChoice,
    ExpertReviewDecision,
    FilingReviewDecision,
    RatingGrade,
    ResponsibilityDetermination,
    SafestAvailableOpinion,
    SelectionBasis,
    StrategyDecision,
    StrategyType,
    SubmissionDecision,
    TransferMode,
)


_ein_counter = itertools.count(1)
_reference_counter = itertools.count(1)


def unique_plan_ein() -> str:
    """A distinct nine-digit EIN for each call within a test."""
    return "94{:07d}".format(next(_ein_counter))


def unique_reference(prefix: str = "REF") -> str:
    return "{}-{:05d}".format(prefix, next(_reference_counter))


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of `None` removes the key entirely."""
    merged = dict(payload)
    for key, value in overrides.items():
        if value is None and key in merged:
            merged.pop(key)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Pension plan
# ---------------------------------------------------------------------------


def plan_payload(**overrides: Any) -> Dict[str, Any]:
    """A well-funded ongoing plan: assets 92,000,000 against liability 100,000,000."""
    return _merge(
        {
            "sponsor_name": "Ridgeline Manufacturing Company",
            "plan_name": "Ridgeline Salaried Employees Pension Plan",
            "plan_ein": unique_plan_ein(),
            "total_liability_cents": 100000000,
            "plan_assets_cents": 92000000,
            "service_cost_cents": 3000000,
            "interest_cost_cents": 9000000,
            "unrecognized_actuarial_loss_cents": 4000000,
            "discount_rate_bps": 510,
        },
        overrides,
    )


def valuation_update_payload(expected_plan_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "expected_plan_version": expected_plan_version,
            "total_liability_cents": 100000000,
            "plan_assets_cents": 92000000,
            "service_cost_cents": 3000000,
            "interest_cost_cents": 9000000,
            "unrecognized_actuarial_loss_cents": 4000000,
            "discount_rate_bps": 510,
        },
        overrides,
    )


def amendment_adopt_payload(
    amendment_scope: str, amendment_effective_date: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "amendment_action": AmendmentAction.ADOPT.value,
            "amendment_scope": amendment_scope,
            "amendment_effective_date": amendment_effective_date,
        },
        overrides,
    )


def amendment_rescind_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"amendment_action": AmendmentAction.RESCIND.value}, overrides)


def termination_filing_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"filing_reference": unique_reference("PBGC")}, overrides)


def filing_review_payload(
    review_decision: str = FilingReviewDecision.APPROVE.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"review_decision": review_decision}, overrides)


# ---------------------------------------------------------------------------
# De-risking strategy
# ---------------------------------------------------------------------------


def strategy_payload(
    strategy_type: str = StrategyType.ANNUITY_BUYOUT.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "strategy_name": "Retiree Annuity Buyout Program",
            "strategy_type": strategy_type,
        },
        overrides,
    )


def strategy_decision_payload(
    decision: str = StrategyDecision.APPROVE.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "decision": decision,
            "decision_rationale": (
                "The fiduciary committee reviewed the projections and accepts the plan."
            ),
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Participant record
# ---------------------------------------------------------------------------


def participant_payload(
    cohort: str = Cohort.RETIREE_IN_PAY.value,
    stated_monthly_benefit_cents: int = 250000,
    credited_service_months: int = 400,
    **overrides: Any,
) -> Dict[str, Any]:
    """A participant whose recomputed benefit matches its stated benefit exactly."""
    return _merge(
        {
            "participant_reference": unique_reference("PTC"),
            "cohort": cohort,
            "stated_monthly_benefit_cents": stated_monthly_benefit_cents,
            "final_average_monthly_earnings_cents": fame_for_zero_variance(
                stated_monthly_benefit_cents, credited_service_months
            ),
            "credited_service_months": credited_service_months,
            "date_of_birth": "1958-04-11",
        },
        overrides,
    )


def address_search_confirmed_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "search_result": "CONFIRMED_MATCH",
            "confirmed_address_line1": "1420 Harbor View Road",
            "confirmed_postal_code": "06851",
        },
        overrides,
    )


def address_search_no_match_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"search_result": "NO_MATCH"}, overrides)


def mortality_check_payload(match_result: str = "NO_MATCH", **overrides: Any) -> Dict[str, Any]:
    return _merge({"match_result": match_result}, overrides)


def benefit_audit_payload(expected_participant_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "expected_participant_version": expected_participant_version,
            "audit_basis": AuditBasis.PLAN_DOCUMENT.value,
        },
        overrides,
    )


def audit_resolution_payload(
    resolution: str = AuditResolution.ACCEPT_AS_IS.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"resolution": resolution}, overrides)


# ---------------------------------------------------------------------------
# Lump sum window and elections
# ---------------------------------------------------------------------------


def window_payload(
    opens_at: str = "2026-09-01T00:00:00Z",
    closes_at: str = "2026-10-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "window_name": "Autumn Lump Sum Offer",
            "opens_at": opens_at,
            "closes_at": closes_at,
            "lump_sum_cap_cents": 40000000,
            "eligibility_max_lump_sum_cents": 20000000,
        },
        overrides,
    )


def election_payload(
    election_choice: str = ElectionChoice.LUMP_SUM.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"election_choice": election_choice}, overrides)


# ---------------------------------------------------------------------------
# Buyout tranche
# ---------------------------------------------------------------------------


def tranche_payload(
    target_cohort: str = Cohort.RETIREE_IN_PAY.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "tranche_name": "Retiree In Pay Tranche One",
            "target_cohort": target_cohort,
        },
        overrides,
    )


def participant_assignment_payload(participant_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"participant_id": participant_id}, overrides)


def insurer_selection_payload(
    selection_basis: str = SelectionBasis.SAFETY_WEIGHTED.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"selection_basis": selection_basis}, overrides)


def abandonment_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "abandonment_reason": (
                "Sponsor deferred the transaction to the next fiscal year."
            )
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Insurers and quotes
# ---------------------------------------------------------------------------


def insurer_payload(
    insurer_name: str = "Aurora Life Assurance",
    rating_grade: str = RatingGrade.AA_PLUS.value,
    capital_ratio_bp: int = 4200,
    capacity_cents: int = 200000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "insurer_name": insurer_name,
            "rating_grade": rating_grade,
            "capital_ratio_bp": capital_ratio_bp,
            "capacity_cents": capacity_cents,
        },
        overrides,
    )


def rating_change_payload(rating_grade: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"rating_grade": rating_grade}, overrides)


def quote_request_payload(insurer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"insurer_id": insurer_id}, overrides)


def quote_submit_payload(
    premium_cents: int = 12000000,
    lock_days: int = 90,
    quote_valid_days: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "submission_decision": SubmissionDecision.SUBMIT.value,
            "premium_cents": premium_cents,
            "lock_days": lock_days,
            "quote_valid_days": quote_valid_days,
        },
        overrides,
    )


def quote_decline_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "submission_decision": SubmissionDecision.DECLINE.value,
            "decline_reason": "The cohort falls outside our current underwriting appetite.",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Independent expert
# ---------------------------------------------------------------------------


def expert_payload(
    expert_firm_name: str = "Kestrel Fiduciary Advisors LLP", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "expert_firm_name": expert_firm_name,
            "engagement_scope": (
                "Independent evaluation of the safest available annuity provider."
            ),
        },
        overrides,
    )


def expert_review_payload(
    review_decision: str = ExpertReviewDecision.ENGAGE.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"review_decision": review_decision}, overrides)


def expert_opinion_payload(
    safest_available_opinion: str = SafestAvailableOpinion.AFFIRMATIVE.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"safest_available_opinion": safest_available_opinion}, overrides)


# ---------------------------------------------------------------------------
# Asset transfers
# ---------------------------------------------------------------------------


def in_kind_transfer_payload(
    expected_tranche_version: int,
    gross_value_cents: int,
    security_lot_count: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "expected_tranche_version": expected_tranche_version,
            "transfer_mode": TransferMode.IN_KIND.value,
            "gross_value_cents": gross_value_cents,
            "security_lot_count": security_lot_count,
        },
        overrides,
    )


def cash_transfer_payload(
    expected_tranche_version: int, gross_value_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "expected_tranche_version": expected_tranche_version,
            "transfer_mode": TransferMode.CASH.value,
            "gross_value_cents": gross_value_cents,
        },
        overrides,
    )


def insurer_review_payload(insurer_decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    return _merge({"insurer_decision": insurer_decision}, overrides)


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------


def complaint_payload(
    complaint_category: str = "BENEFIT_AMOUNT",
    tranche_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "complaint_category": complaint_category,
        "complaint_narrative": (
            "The monthly annuity payment I received is lower than the amount stated "
            "in the notice I was sent before the transfer."
        ),
    }
    if tranche_id is not None:
        payload["tranche_id"] = tranche_id
    return _merge(payload, overrides)


def triage_payload(
    responsibility_determination: str = ResponsibilityDetermination.SPONSOR_RESPONSIBLE.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "responsibility_determination": responsibility_determination,
            "determination_rationale": (
                "The administrator's benefit file understated the accrued benefit."
            ),
        },
        overrides,
    )


def complaint_resolution_payload(remediation_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"remediation_amount_cents": remediation_amount_cents}, overrides)
