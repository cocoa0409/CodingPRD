"""Setup builders that drive the API from an empty database to a named state.

Every test starts against a freshly launched server with no rows at all, so all
preconditions have to be created through declared endpoints. The builders below
are layered:

* tier 1 -- single-step wrappers that create one resource or fire one transition
* tier 2 -- entity hierarchies (a plan with participants, an insurer panel)
* tier 3 -- full-lifecycle shortcuts (a settled tranche, a settled window)
* tier 4 -- accumulation and threshold targeting (capacity committed to a lock,
  a fee tier hit exactly, a variance sitting on the tolerance)
* tier 5 -- finalization and terminal states (an abandoned tranche, a residual
  plan, a reversed remediation)

Builders return the resource body as the API reported it, or a small dataclass
when a builder produces several correlated resources.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import PrtApiClient
from .constants import (
    CLOCK_EPOCH,
    fame_for_zero_variance,
    in_kind_transfer_expense,
)
from .test_users import (
    actuary_headers,
    administrator_headers,
    fiduciary_headers,
    make_expert_headers,
    make_insurer_rep_headers,
    make_participant_headers,
    regulator_headers,
    sponsor_headers,
)
from .types import (
    AmendmentScope,
    AuditResolution,
    Cohort,
    ElectionChoice,
    ExpertReviewDecision,
    ResponsibilityDetermination,
    SafestAvailableOpinion,
    SelectionBasis,
    StrategyDecision,
    StrategyType,
    TransferMode,
)


# ===========================================================================
# Tier 1 -- single-step builders
# ===========================================================================


def set_clock(api: PrtApiClient, current_utc: str) -> None:
    """Move the server's logical clock to `current_utc`."""
    get_success_data(api.set_clock(current_utc, administrator_headers()))


def reset_clock(api: PrtApiClient) -> None:
    """Return the logical clock to its startup instant."""
    set_clock(api, CLOCK_EPOCH)


def create_plan(api: PrtApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = factories.plan_payload(**overrides)
    return get_success_data(api.create_plan(payload, sponsor_headers()))


def read_plan(api: PrtApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_plan(plan_id, sponsor_headers()))


def read_funded_status(api: PrtApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_funded_status(plan_id, sponsor_headers()))


def update_valuation(api: PrtApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    """Post a valuation update using the plan's current version."""
    plan = read_plan(api, plan_id)
    fields: Dict[str, Any] = {
        "total_liability_cents": plan["total_liability_cents"],
        "plan_assets_cents": plan["plan_assets_cents"],
        "service_cost_cents": plan["service_cost_cents"],
        "interest_cost_cents": plan["interest_cost_cents"],
        "unrecognized_actuarial_loss_cents": plan["unrecognized_actuarial_loss_cents"],
        "discount_rate_bps": plan["discount_rate_bps"],
    }
    fields.update(overrides)
    payload = factories.valuation_update_payload(plan["version"], **fields)
    return get_success_data(api.post_valuation_update(plan_id, payload, actuary_headers()))


def create_strategy(
    api: PrtApiClient,
    plan_id: str,
    strategy_type: str = StrategyType.ANNUITY_BUYOUT.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.strategy_payload(strategy_type, **overrides)
    return get_success_data(api.create_strategy(plan_id, payload, actuary_headers()))


def submit_strategy(
    api: PrtApiClient, strategy_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.post_strategy_submission(strategy_id, {}, headers or actuary_headers())
    )


def decide_strategy(
    api: PrtApiClient,
    strategy_id: str,
    decision: str = StrategyDecision.APPROVE.value,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.strategy_decision_payload(decision, **overrides)
    return get_success_data(
        api.post_strategy_decision(strategy_id, payload, headers or fiduciary_headers())
    )


def list_strategies(api: PrtApiClient, plan_id: str, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_strategies(plan_id, actuary_headers(), params or None)
    rows, _meta = validate_paginated(response)
    return rows


def read_strategy(api: PrtApiClient, plan_id: str, strategy_id: str) -> Dict[str, Any]:
    """Re-read one strategy through the plan's strategy listing."""
    rows = list_strategies(api, plan_id)
    for row in rows:
        if row["id"] == strategy_id:
            return row
    raise AssertionError("strategy {} not listed under plan {}".format(strategy_id, plan_id))


def create_approved_strategy(
    api: PrtApiClient,
    plan_id: str,
    strategy_type: str = StrategyType.ANNUITY_BUYOUT.value,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create, submit and approve a strategy; the decider differs from the submitter."""
    strategy = create_strategy(api, plan_id, strategy_type, **overrides)
    submit_strategy(api, strategy["id"])
    return decide_strategy(api, strategy["id"], StrategyDecision.APPROVE.value)


def adopt_amendment(
    api: PrtApiClient,
    plan_id: str,
    amendment_scope: str = AmendmentScope.BUYOUT_ONLY.value,
    amendment_effective_date: str = "2026-08-15T00:00:00Z",
) -> Dict[str, Any]:
    payload = factories.amendment_adopt_payload(amendment_scope, amendment_effective_date)
    return get_success_data(
        api.post_settlement_amendment(plan_id, payload, sponsor_headers())
    )


def rescind_amendment(api: PrtApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_settlement_amendment(
            plan_id, factories.amendment_rescind_payload(), sponsor_headers()
        )
    )


def create_participant(api: PrtApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.participant_payload(**overrides)
    return get_success_data(api.create_participant(plan_id, payload, administrator_headers()))


def read_participant(api: PrtApiClient, participant_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_participant(participant_id, administrator_headers()))


def confirm_address(api: PrtApiClient, participant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.address_search_confirmed_payload(**overrides)
    return get_success_data(
        api.post_address_search(participant_id, payload, administrator_headers())
    )


def record_address_no_match(api: PrtApiClient, participant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_address_search(
            participant_id, factories.address_search_no_match_payload(), administrator_headers()
        )
    )


def record_mortality(
    api: PrtApiClient, participant_id: str, match_result: str = "NO_MATCH", **overrides: Any
) -> Dict[str, Any]:
    payload = factories.mortality_check_payload(match_result, **overrides)
    return get_success_data(
        api.post_mortality_check(participant_id, payload, administrator_headers())
    )


def confirm_alive(api: PrtApiClient, participant_id: str) -> Dict[str, Any]:
    """A `NO_MATCH` against the death master file affirms life."""
    return record_mortality(api, participant_id, "NO_MATCH")


def open_benefit_audit(api: PrtApiClient, participant_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open an audit against the participant's current version."""
    participant = read_participant(api, participant_id)
    payload = factories.benefit_audit_payload(participant["version"], **overrides)
    return get_success_data(
        api.create_benefit_audit(participant_id, payload, actuary_headers())
    )


def resolve_audit(
    api: PrtApiClient,
    audit_id: str,
    resolution: str = AuditResolution.ACCEPT_AS_IS.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.audit_resolution_payload(resolution, **overrides)
    return get_success_data(api.post_audit_resolution(audit_id, payload, actuary_headers()))


def list_benefit_audits(
    api: PrtApiClient, participant_id: str, **params: Any
) -> List[Dict[str, Any]]:
    response = api.list_benefit_audits(participant_id, actuary_headers(), params or None)
    rows, _meta = validate_paginated(response)
    return rows


def latest_audit(api: PrtApiClient, participant_id: str) -> Dict[str, Any]:
    """The participant's highest-sequence audit."""
    rows = list_benefit_audits(api, participant_id)
    assert rows, "participant {} has no audits".format(participant_id)
    return max(rows, key=lambda row: row["audit_sequence"])


def create_insurer(
    api: PrtApiClient,
    insurer_name: str = "Aurora Life Assurance",
    rating_grade: str = "AA_PLUS",
    capital_ratio_bp: int = 4200,
    capacity_cents: int = 200000000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.insurer_payload(
        insurer_name, rating_grade, capital_ratio_bp, capacity_cents, **overrides
    )
    return get_success_data(api.create_insurer(payload, regulator_headers()))


def read_insurer(api: PrtApiClient, insurer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_insurer(insurer_id, sponsor_headers()))


def change_rating(
    api: PrtApiClient, insurer_id: str, rating_grade: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.rating_change_payload(rating_grade, **overrides)
    return get_success_data(api.post_rating_change(insurer_id, payload, regulator_headers()))


def create_expert(
    api: PrtApiClient,
    plan_id: str,
    expert_firm_name: str = "Kestrel Fiduciary Advisors LLP",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.expert_payload(expert_firm_name, **overrides)
    return get_success_data(api.create_expert(plan_id, payload, headers or sponsor_headers()))


def review_expert(
    api: PrtApiClient,
    expert_id: str,
    review_decision: str = ExpertReviewDecision.ENGAGE.value,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = factories.expert_review_payload(review_decision)
    return get_success_data(
        api.post_independence_review(expert_id, payload, headers or fiduciary_headers())
    )


def issue_opinion(
    api: PrtApiClient,
    expert_id: str,
    safest_available_opinion: str = SafestAvailableOpinion.AFFIRMATIVE.value,
) -> Dict[str, Any]:
    """The expert speaks for itself: the acting identity is the expert's own id."""
    payload = factories.expert_opinion_payload(safest_available_opinion)
    return get_success_data(
        api.post_expert_opinion(expert_id, payload, make_expert_headers(expert_id))
    )


def read_expert(api: PrtApiClient, expert_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_expert(expert_id, sponsor_headers()))


def create_tranche(
    api: PrtApiClient,
    plan_id: str,
    target_cohort: str = Cohort.RETIREE_IN_PAY.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.tranche_payload(target_cohort, **overrides)
    return get_success_data(api.create_tranche(plan_id, payload, fiduciary_headers()))


def read_tranche(api: PrtApiClient, tranche_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_tranche(tranche_id, sponsor_headers()))


def assign_participant(api: PrtApiClient, tranche_id: str, participant_id: str) -> Dict[str, Any]:
    payload = factories.participant_assignment_payload(participant_id)
    return get_success_data(
        api.post_participant_assignment(tranche_id, payload, administrator_headers())
    )


def start_quoting(api: PrtApiClient, tranche_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_tranche_quoting(tranche_id, {}, fiduciary_headers()))


def request_quote(api: PrtApiClient, tranche_id: str, insurer_id: str) -> Dict[str, Any]:
    payload = factories.quote_request_payload(insurer_id)
    return get_success_data(api.create_quote(tranche_id, payload, fiduciary_headers()))


def submit_quote(
    api: PrtApiClient,
    quote_id: str,
    insurer_id: str,
    premium_cents: int = 12000000,
    lock_days: int = 90,
    quote_valid_days: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    """The insurer submits its own quote, acting as itself."""
    payload = factories.quote_submit_payload(
        premium_cents, lock_days, quote_valid_days, **overrides
    )
    return get_success_data(
        api.post_quote_submission(quote_id, payload, make_insurer_rep_headers(insurer_id))
    )


def request_and_submit_quote(
    api: PrtApiClient,
    tranche_id: str,
    insurer_id: str,
    premium_cents: int = 12000000,
    lock_days: int = 90,
    quote_valid_days: int = 60,
) -> Dict[str, Any]:
    quote = request_quote(api, tranche_id, insurer_id)
    return submit_quote(api, quote["id"], insurer_id, premium_cents, lock_days, quote_valid_days)


def read_quote(api: PrtApiClient, quote_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_quote(quote_id, sponsor_headers()))


def select_insurer(
    api: PrtApiClient,
    tranche_id: str,
    selection_basis: str = SelectionBasis.SAFETY_WEIGHTED.value,
) -> Dict[str, Any]:
    payload = factories.insurer_selection_payload(selection_basis)
    return get_success_data(api.post_insurer_selection(tranche_id, payload, fiduciary_headers()))


def lock_pricing(api: PrtApiClient, tranche_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_pricing_lock(tranche_id, {}, fiduciary_headers()))


def initiate_in_kind_transfer(
    api: PrtApiClient,
    tranche_id: str,
    gross_value_cents: int,
    security_lot_count: int = 2,
    expected_tranche_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_tranche_version
        if expected_tranche_version is not None
        else read_tranche(api, tranche_id)["version"]
    )
    payload = factories.in_kind_transfer_payload(version, gross_value_cents, security_lot_count)
    return get_success_data(api.create_asset_transfer(tranche_id, payload, sponsor_headers()))


def initiate_cash_transfer(
    api: PrtApiClient,
    tranche_id: str,
    gross_value_cents: int,
    expected_tranche_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_tranche_version
        if expected_tranche_version is not None
        else read_tranche(api, tranche_id)["version"]
    )
    payload = factories.cash_transfer_payload(version, gross_value_cents)
    return get_success_data(api.create_asset_transfer(tranche_id, payload, sponsor_headers()))


def review_transfer(
    api: PrtApiClient,
    transfer_id: str,
    insurer_id: str,
    insurer_decision: str = "ACCEPT",
    **overrides: Any,
) -> Dict[str, Any]:
    """The receiving insurer reviews the delivery, acting as itself."""
    payload = factories.insurer_review_payload(insurer_decision, **overrides)
    return get_success_data(
        api.post_insurer_review(transfer_id, payload, make_insurer_rep_headers(insurer_id))
    )


def settle_tranche(api: PrtApiClient, tranche_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_tranche_settlement(tranche_id, {}, sponsor_headers()))


def abandon_tranche(api: PrtApiClient, tranche_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.abandonment_payload(**overrides)
    return get_success_data(api.post_tranche_abandonment(tranche_id, payload, fiduciary_headers()))


def list_asset_transfers(api: PrtApiClient, tranche_id: str, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_asset_transfers(tranche_id, sponsor_headers(), params or None)
    rows, _meta = validate_paginated(response)
    return rows


def create_window(api: PrtApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.window_payload(**overrides)
    return get_success_data(api.create_window(plan_id, payload, administrator_headers()))


def open_window(api: PrtApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_window_opening(window_id, {}, administrator_headers()))


def close_window(api: PrtApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_window_closing(window_id, {}, administrator_headers()))


def settle_window(api: PrtApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_window_settlement(window_id, {}, sponsor_headers()))


def list_windows(api: PrtApiClient, plan_id: str, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_windows(plan_id, sponsor_headers(), params or None)
    rows, _meta = validate_paginated(response)
    return rows


def list_elections(api: PrtApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_elections(administrator_headers(), params or None)
    rows, _meta = validate_paginated(response)
    return rows


def read_election(api: PrtApiClient, election_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_election(election_id, administrator_headers()))


def election_for(api: PrtApiClient, window_id: str, participant_id: str) -> Dict[str, Any]:
    """The notice row minted for `participant_id` when `window_id` opened."""
    rows = list_elections(api, window_id=window_id, participant_id=participant_id)
    assert len(rows) == 1, "expected one election for participant {}, found {}".format(
        participant_id, len(rows)
    )
    return rows[0]


def elect(
    api: PrtApiClient,
    election_id: str,
    participant_id: str,
    election_choice: str = ElectionChoice.LUMP_SUM.value,
) -> Dict[str, Any]:
    """The participant elects for themselves."""
    payload = factories.election_payload(election_choice)
    return get_success_data(
        api.post_election(election_id, payload, make_participant_headers(participant_id))
    )


def revoke_election(api: PrtApiClient, election_id: str, participant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.post_election_revocation(election_id, {}, make_participant_headers(participant_id))
    )


def file_complaint(
    api: PrtApiClient,
    participant_id: str,
    complaint_category: str = "BENEFIT_AMOUNT",
    tranche_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """The participant files for themselves."""
    payload = factories.complaint_payload(complaint_category, tranche_id, **overrides)
    return get_success_data(
        api.create_complaint(participant_id, payload, make_participant_headers(participant_id))
    )


def triage_complaint(
    api: PrtApiClient,
    complaint_id: str,
    responsibility_determination: str = ResponsibilityDetermination.SPONSOR_RESPONSIBLE.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.triage_payload(responsibility_determination, **overrides)
    return get_success_data(
        api.post_complaint_triage(complaint_id, payload, administrator_headers())
    )


def resolve_complaint(
    api: PrtApiClient, complaint_id: str, remediation_amount_cents: int
) -> Dict[str, Any]:
    payload = factories.complaint_resolution_payload(remediation_amount_cents)
    return get_success_data(
        api.post_complaint_resolution(complaint_id, payload, administrator_headers())
    )


def read_complaint(api: PrtApiClient, complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_complaint(complaint_id, sponsor_headers()))


def list_settlement_entries(api: PrtApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_settlement_entries(sponsor_headers(), params or None)
    rows, _meta = validate_paginated(response)
    return rows


def submit_termination_filing(api: PrtApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.termination_filing_payload(**overrides)
    return get_success_data(api.post_termination_filing(plan_id, payload, sponsor_headers()))


def review_filing(api: PrtApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.filing_review_payload(**overrides)
    return get_success_data(api.post_filing_review(plan_id, payload, regulator_headers()))


# ===========================================================================
# Tier 2 -- entity hierarchies
# ===========================================================================


@dataclass
class ParticipantSpec:
    """A participant to build, described in the terms the API accepts."""

    stated_monthly_benefit_cents: int
    cohort: str = Cohort.RETIREE_IN_PAY.value
    credited_service_months: int = 400
    final_average_monthly_earnings_cents: Optional[int] = None
    date_of_birth: str = "1958-04-11"

    def payload_kwargs(self) -> Dict[str, Any]:
        fame = self.final_average_monthly_earnings_cents
        if fame is None:
            fame = fame_for_zero_variance(
                self.stated_monthly_benefit_cents, self.credited_service_months
            )
        return {
            "cohort": self.cohort,
            "stated_monthly_benefit_cents": self.stated_monthly_benefit_cents,
            "credited_service_months": self.credited_service_months,
            "final_average_monthly_earnings_cents": fame,
            "date_of_birth": self.date_of_birth,
        }


def create_clean_participant(
    api: PrtApiClient, plan_id: str, spec: Optional[ParticipantSpec] = None, **overrides: Any
) -> Dict[str, Any]:
    """Build a participant and walk all three data dimensions to a clean record.

    The address is confirmed, life is affirmed against the death master file,
    and an audit is opened and resolved, leaving no deduction outstanding.
    """
    kwargs = spec.payload_kwargs() if spec is not None else {}
    kwargs.update(overrides)
    participant = create_participant(api, plan_id, **kwargs)
    confirm_address(api, participant["id"])
    confirm_alive(api, participant["id"])
    audit = open_benefit_audit(api, participant["id"])
    resolve_audit(api, audit["id"], _resolution_for(audit))
    return read_participant(api, participant["id"])


def _resolution_for(audit: Dict[str, Any]) -> str:
    """Accept a passing audit as it stands; correct one that demands correction."""
    if audit["audit_status"] == "CORRECTION_REQUIRED":
        return AuditResolution.APPLY_CORRECTION.value
    return AuditResolution.ACCEPT_AS_IS.value


def create_clean_participants(
    api: PrtApiClient, plan_id: str, specs: Sequence[ParticipantSpec]
) -> List[Dict[str, Any]]:
    return [create_clean_participant(api, plan_id, spec) for spec in specs]


@dataclass
class InsurerSpec:
    insurer_name: str
    rating_grade: str
    capital_ratio_bp: int
    capacity_cents: int = 200000000


def create_insurer_panel(
    api: PrtApiClient, specs: Sequence[InsurerSpec]
) -> List[Dict[str, Any]]:
    """Register several insurers in one call, preserving order."""
    return [
        create_insurer(
            api,
            spec.insurer_name,
            spec.rating_grade,
            spec.capital_ratio_bp,
            spec.capacity_cents,
        )
        for spec in specs
    ]


#: The three-insurer panel the pricing scenarios lean on.
STANDARD_INSURER_PANEL = (
    InsurerSpec("Aurora Life Assurance", "AA_PLUS", 4200),
    InsurerSpec("Beacon Mutual Annuity", "AA_MINUS", 3800),
    InsurerSpec("Cardinal Guaranty Life", "AAA", 5100),
)


# ===========================================================================
# Tier 3 -- full-lifecycle shortcuts
# ===========================================================================


@dataclass
class AuthorizedPlan:
    """A plan carrying an approved strategy, an adopted amendment and an expert."""

    plan: Dict[str, Any]
    strategy: Dict[str, Any]
    expert: Dict[str, Any]
    participants: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def participant_ids(self) -> List[str]:
        return [participant["id"] for participant in self.participants]


def build_authorized_plan(
    api: PrtApiClient,
    participants: Sequence[ParticipantSpec] = (),
    strategy_type: str = StrategyType.ANNUITY_BUYOUT.value,
    amendment_scope: str = AmendmentScope.BUYOUT_ONLY.value,
    amendment_effective_date: str = "2026-08-15T00:00:00Z",
    expert_opinion: Optional[str] = SafestAvailableOpinion.AFFIRMATIVE.value,
    expert_firm_name: str = "Kestrel Fiduciary Advisors LLP",
    **plan_overrides: Any,
) -> AuthorizedPlan:
    """Drive a fresh plan all the way to settlement-authorized with an expert opinion.

    Pass `expert_opinion=None` to leave the expert merely engaged, which is what
    the scenarios that probe the opinion gate need.
    """
    plan = create_plan(api, **plan_overrides)
    built = create_clean_participants(api, plan["id"], participants)
    strategy = create_approved_strategy(api, plan["id"], strategy_type)
    plan = adopt_amendment(api, plan["id"], amendment_scope, amendment_effective_date)
    expert = create_expert(api, plan["id"], expert_firm_name)
    expert = review_expert(api, expert["id"], ExpertReviewDecision.ENGAGE.value)
    if expert_opinion is not None:
        expert = issue_opinion(api, expert["id"], expert_opinion)
    return AuthorizedPlan(plan=plan, strategy=strategy, expert=expert, participants=built)


@dataclass
class QuotingTranche:
    """A tranche that has been opened for quoting with its participants assigned."""

    tranche: Dict[str, Any]
    participants: List[Dict[str, Any]]

    @property
    def tranche_id(self) -> str:
        return self.tranche["id"]


def build_quoting_tranche(
    api: PrtApiClient,
    plan_id: str,
    participants: Sequence[Dict[str, Any]],
    target_cohort: str = Cohort.RETIREE_IN_PAY.value,
    **tranche_overrides: Any,
) -> QuotingTranche:
    """Create a tranche, assign the given participants, and open it for quoting."""
    tranche = create_tranche(api, plan_id, target_cohort, **tranche_overrides)
    for participant in participants:
        assign_participant(api, tranche["id"], participant["id"])
    tranche = start_quoting(api, tranche["id"])
    return QuotingTranche(tranche=tranche, participants=list(participants))


@dataclass
class QuoteSpec:
    insurer_id: str
    premium_cents: int
    lock_days: int = 90
    quote_valid_days: int = 60


def collect_quotes(
    api: PrtApiClient, tranche_id: str, specs: Sequence[QuoteSpec]
) -> List[Dict[str, Any]]:
    """Request and submit one quote per spec, preserving order."""
    return [
        request_and_submit_quote(
            api,
            tranche_id,
            spec.insurer_id,
            spec.premium_cents,
            spec.lock_days,
            spec.quote_valid_days,
        )
        for spec in specs
    ]


def build_selected_tranche(
    api: PrtApiClient,
    plan_id: str,
    participants: Sequence[Dict[str, Any]],
    quotes: Sequence[QuoteSpec],
    selection_basis: str = SelectionBasis.SAFETY_WEIGHTED.value,
    target_cohort: str = Cohort.RETIREE_IN_PAY.value,
    **tranche_overrides: Any,
) -> Dict[str, Any]:
    """Take a tranche from creation through insurer selection."""
    quoting = build_quoting_tranche(
        api, plan_id, participants, target_cohort, **tranche_overrides
    )
    collect_quotes(api, quoting.tranche_id, quotes)
    return select_insurer(api, quoting.tranche_id, selection_basis)


def build_locked_tranche(
    api: PrtApiClient,
    plan_id: str,
    participants: Sequence[Dict[str, Any]],
    quotes: Sequence[QuoteSpec],
    selection_basis: str = SelectionBasis.SAFETY_WEIGHTED.value,
    target_cohort: str = Cohort.RETIREE_IN_PAY.value,
    **tranche_overrides: Any,
) -> Dict[str, Any]:
    """Take a tranche from creation through the pricing lock."""
    tranche = build_selected_tranche(
        api, plan_id, participants, quotes, selection_basis, target_cohort, **tranche_overrides
    )
    return lock_pricing(api, tranche["id"])


def build_settled_tranche(
    api: PrtApiClient,
    plan_id: str,
    participants: Sequence[Dict[str, Any]],
    quotes: Sequence[QuoteSpec],
    winning_insurer_id: str,
    gross_value_cents: int,
    security_lot_count: int = 2,
    transfer_mode: str = TransferMode.IN_KIND.value,
    selection_basis: str = SelectionBasis.SAFETY_WEIGHTED.value,
    target_cohort: str = Cohort.RETIREE_IN_PAY.value,
    **tranche_overrides: Any,
) -> Dict[str, Any]:
    """Take a tranche all the way to `SETTLED` through an accepted delivery."""
    tranche = build_locked_tranche(
        api, plan_id, participants, quotes, selection_basis, target_cohort, **tranche_overrides
    )
    if transfer_mode == TransferMode.IN_KIND.value:
        transfer = initiate_in_kind_transfer(
            api, tranche["id"], gross_value_cents, security_lot_count, tranche["version"]
        )
    else:
        transfer = initiate_cash_transfer(
            api, tranche["id"], gross_value_cents, tranche["version"]
        )
    review_transfer(api, transfer["id"], winning_insurer_id, "ACCEPT")
    return settle_tranche(api, tranche["id"])


@dataclass
class OpenWindow:
    """An open window with one notice row per in-scope participant."""

    window: Dict[str, Any]
    elections: List[Dict[str, Any]]
    participants: List[Dict[str, Any]]

    @property
    def window_id(self) -> str:
        return self.window["id"]

    def election_for(self, participant_id: str) -> Dict[str, Any]:
        for election in self.elections:
            if election["participant_id"] == participant_id:
                return election
        raise AssertionError("no election for participant {}".format(participant_id))


def build_open_window(
    api: PrtApiClient,
    plan_id: str,
    participants: Sequence[Dict[str, Any]],
    opens_at: str = "2026-09-01T00:00:00Z",
    closes_at: str = "2026-10-31T00:00:00Z",
    **window_overrides: Any,
) -> OpenWindow:
    """Schedule a window, move the clock to its opening instant, and open it."""
    window = create_window(api, plan_id, opens_at=opens_at, closes_at=closes_at, **window_overrides)
    set_clock(api, opens_at)
    window = open_window(api, window["id"])
    elections = [
        election_for(api, window["id"], participant["id"]) for participant in participants
    ]
    return OpenWindow(window=window, elections=elections, participants=list(participants))


def build_settled_window(
    api: PrtApiClient,
    plan_id: str,
    participants: Sequence[Dict[str, Any]],
    opens_at: str = "2026-09-01T00:00:00Z",
    closes_at: str = "2026-10-31T00:00:00Z",
    election_choice: str = ElectionChoice.LUMP_SUM.value,
    **window_overrides: Any,
) -> OpenWindow:
    """Open a window, have every participant elect, then close and settle it."""
    opened = build_open_window(
        api, plan_id, participants, opens_at, closes_at, **window_overrides
    )
    for participant in participants:
        election = opened.election_for(participant["id"])
        elect(api, election["id"], participant["id"], election_choice)
    set_clock(api, closes_at)
    close_window(api, opened.window_id)
    window = settle_window(api, opened.window_id)
    elections = [
        election_for(api, opened.window_id, participant["id"]) for participant in participants
    ]
    return OpenWindow(window=window, elections=elections, participants=list(participants))


# ===========================================================================
# Tier 4 -- accumulation and threshold targeting
# ===========================================================================


def gross_value_for_exact_credit(target_credited_cents: int, lot_count: int) -> int:
    """The smallest in-kind gross value whose credited value reaches the target.

    Used to sit an in-kind delivery exactly on -- or one cent under -- the
    shortfall boundary.
    """
    gross = target_credited_cents
    while gross - in_kind_transfer_expense(gross, lot_count) < target_credited_cents:
        gross += 1
    return gross


def commit_capacity(
    api: PrtApiClient,
    authorized: AuthorizedPlan,
    insurer_id: str,
    premium_cents: int,
    participants: Sequence[Dict[str, Any]],
    lock_days: int = 90,
    quote_valid_days: int = 90,
    target_cohort: str = Cohort.RETIREE_IN_PAY.value,
    **tranche_overrides: Any,
) -> Dict[str, Any]:
    """Consume `premium_cents` of the insurer's capacity through a pricing lock."""
    return build_locked_tranche(
        api,
        authorized.plan_id,
        participants,
        [QuoteSpec(insurer_id, premium_cents, lock_days, quote_valid_days)],
        SelectionBasis.SAFETY_WEIGHTED.value,
        target_cohort,
        **tranche_overrides,
    )


def reopen_audit_via_complaint(
    api: PrtApiClient,
    participant_id: str,
    tranche_id: Optional[str] = None,
    complaint_category: str = "BENEFIT_AMOUNT",
) -> Dict[str, Any]:
    """File a complaint and triage it as sponsor-responsible, reopening the audit."""
    complaint = file_complaint(api, participant_id, complaint_category, tranche_id)
    return triage_complaint(
        api, complaint["id"], ResponsibilityDetermination.SPONSOR_RESPONSIBLE.value
    )


# ===========================================================================
# Tier 5 -- finalization and terminal states
# ===========================================================================


def build_abandoned_tranche(
    api: PrtApiClient,
    plan_id: str,
    participants: Sequence[Dict[str, Any]],
    quotes: Sequence[QuoteSpec],
    selection_basis: str = SelectionBasis.SAFETY_WEIGHTED.value,
    target_cohort: str = Cohort.RETIREE_IN_PAY.value,
    **tranche_overrides: Any,
) -> Dict[str, Any]:
    """Lock a tranche's pricing and then abandon it."""
    tranche = build_locked_tranche(
        api, plan_id, participants, quotes, selection_basis, target_cohort, **tranche_overrides
    )
    return abandon_tranche(api, tranche["id"])


def build_remediated_complaint(
    api: PrtApiClient,
    participant_id: str,
    remediation_amount_cents: int,
    tranche_id: Optional[str] = None,
) -> Dict[str, Any]:
    """File, triage, correct the reopened audit, and resolve with a remediation."""
    complaint = file_complaint(api, participant_id, "BENEFIT_AMOUNT", tranche_id)
    triage_complaint(
        api, complaint["id"], ResponsibilityDetermination.SPONSOR_RESPONSIBLE.value
    )
    audit = latest_audit(api, participant_id)
    resolve_audit(api, audit["id"], AuditResolution.APPLY_CORRECTION.value)
    return resolve_complaint(api, complaint["id"], remediation_amount_cents)


def build_terminated_plan(api: PrtApiClient, plan_id: str) -> Dict[str, Any]:
    """File for termination and have the regulator approve the filing."""
    submit_termination_filing(api, plan_id)
    return review_filing(api, plan_id)
