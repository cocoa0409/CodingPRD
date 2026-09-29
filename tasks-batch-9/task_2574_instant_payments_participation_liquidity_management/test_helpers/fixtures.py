"""Composite scenario builders.

The harness restarts the service before every single test, so every test starts
against an empty database and must build its own world through the declared
endpoints. These builders are the five tiers of that construction:

1. primitives - move the clock, read one record, read one collection;
2. single-record creators - one endpoint call each, with the success envelope
   already unwrapped and the status already validated;
3. lifecycle composites - take a bank from enrolment all the way to `LIVE`;
4. rail scenarios - a live bank (or two) with policy, customer and open cycle;
5. traffic scenarios - a scenario plus transfers in a named clearing state.

Nothing here asserts business outcomes: builders only assert that their own
setup calls succeeded, so a failing test always points at the behaviour under
test rather than at the fixture.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from . import constants as K
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    CORE_BANKING_SYSTEM,
    FRAUD_REVIEWER,
    LIQUIDITY_OFFICER,
    NETWORK_OPERATOR,
    PAYMENT_OPERATOR_ALPHA,
    PAYMENT_OPERATOR_BETA,
    make_participant_admin_headers,
)
from .types import Headers, Json, ParticipantBundle, RailScenario

# --------------------------------------------------------------- shared parameter sets
ALPHA_ACCOUNT: Dict[str, int] = {
    "opening_balance_cents": 1_200_000_000,
    "warning_threshold_cents": 1_100_000_000,
    "critical_threshold_cents": 1_000_000_000,
    "floor_cents": 200_000_000,
}
BETA_ACCOUNT: Dict[str, int] = {
    "opening_balance_cents": 500_000_000,
    "warning_threshold_cents": 300_000_000,
    "critical_threshold_cents": 200_000_000,
    "floor_cents": 100_000_000,
}
CORPORATE_POLICY: Dict[str, Any] = {
    "segment": "CORPORATE",
    "per_transaction_limit_cents": 250_000_000,
    "daily_aggregate_limit_cents": 500_000_000,
    "rolling_window_count_limit": 5,
    "rolling_window_amount_limit_cents": 400_000_000,
    "effective_from": K.CLOCK_2026_08_01,
}


# =============================================================== tier 1: primitives
def set_clock(api: ApiClient, instant: str) -> None:
    """Move the logical rail clock to `instant`, asserting the move was accepted."""
    response = api.set_clock(F.clock_payload(instant), NETWORK_OPERATOR)
    validate_success(response, expected_status=200)


def read_participant(api: ApiClient, participant_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_participant(participant_id, headers))


def participant_version(api: ApiClient, participant_id: str) -> int:
    """Re-read the participant to obtain a fresh `expected_participant_version`."""
    return read_participant(api, participant_id)["version"]


def read_account(api: ApiClient, account_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_position_account(account_id, headers))


def account_version(api: ApiClient, account_id: str) -> int:
    """Re-read the position account to obtain a fresh `expected_position_account_version`."""
    return read_account(api, account_id)["version"]


def read_customer_account(api: ApiClient, customer_account_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_customer_account(customer_account_id, headers))


def read_transfer(api: ApiClient, transfer_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_credit_transfer(transfer_id, headers))


def read_rfp(api: ApiClient, rfp_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_request_for_payment(rfp_id, headers))


def read_return_request(api: ApiClient, return_request_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_return_request(return_request_id, headers))


def read_cycle(api: ApiClient, cycle_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_settlement_cycle(cycle_id, headers))


def read_run(api: ApiClient, run_id: str, headers: Headers = NETWORK_OPERATOR) -> Json:
    return get_success_data(api.get_reconciliation_run(run_id, headers))


def read_projection(api: ApiClient, account_id: str, headers: Headers = LIQUIDITY_OFFICER) -> Json:
    return get_success_data(api.get_liquidity_projection(account_id, headers))


def list_ledger_entries(
    api: ApiClient, account_id: str, params: Optional[Json] = None, headers: Headers = NETWORK_OPERATOR
) -> List[Json]:
    data, _meta = validate_paginated(api.list_ledger_entries(account_id, headers, params))
    return data


def list_ledger_entries_with_meta(
    api: ApiClient, account_id: str, params: Optional[Json] = None, headers: Headers = NETWORK_OPERATOR
) -> Tuple[List[Json], Json]:
    return validate_paginated(api.list_ledger_entries(account_id, headers, params))


def list_alerts(
    api: ApiClient, account_id: str, params: Optional[Json] = None, headers: Headers = LIQUIDITY_OFFICER
) -> List[Json]:
    data, _meta = validate_paginated(api.list_account_alerts(account_id, headers, params))
    return data


def list_alerts_with_meta(
    api: ApiClient, account_id: str, params: Optional[Json] = None, headers: Headers = LIQUIDITY_OFFICER
) -> Tuple[List[Json], Json]:
    return validate_paginated(api.list_account_alerts(account_id, headers, params))


def list_fraud_reviews(
    api: ApiClient, transfer_id: str, params: Optional[Json] = None, headers: Headers = FRAUD_REVIEWER
) -> List[Json]:
    data, _meta = validate_paginated(api.list_transfer_fraud_reviews(transfer_id, headers, params))
    return data


def sole_fraud_review(api: ApiClient, transfer_id: str, headers: Headers = FRAUD_REVIEWER) -> Json:
    """Return the single fraud review the origination cascade raised for a transfer."""
    reviews = list_fraud_reviews(api, transfer_id, headers=headers)
    assert len(reviews) == 1, f"expected exactly one fraud review, found {len(reviews)}"
    return reviews[0]


def list_transfers(
    api: ApiClient, params: Optional[Json] = None, headers: Headers = NETWORK_OPERATOR
) -> List[Json]:
    data, _meta = validate_paginated(api.list_credit_transfers(headers, params))
    return data


def list_transfers_with_meta(
    api: ApiClient, params: Optional[Json] = None, headers: Headers = NETWORK_OPERATOR
) -> Tuple[List[Json], Json]:
    return validate_paginated(api.list_credit_transfers(headers, params))


def list_transfer_ledger_entries(
    api: ApiClient, transfer_id: str, params: Optional[Json] = None, headers: Headers = NETWORK_OPERATOR
) -> List[Json]:
    data, _meta = validate_paginated(api.list_transfer_ledger_entries(transfer_id, headers, params))
    return data


def list_return_requests(
    api: ApiClient, params: Optional[Json] = None, headers: Headers = NETWORK_OPERATOR
) -> List[Json]:
    data, _meta = validate_paginated(api.list_return_requests(headers, params))
    return data


def list_runs_with_meta(
    api: ApiClient, params: Optional[Json] = None, headers: Headers = CORE_BANKING_SYSTEM
) -> Tuple[List[Json], Json]:
    return validate_paginated(api.list_reconciliation_runs(headers, params))


def list_segment_policies_with_meta(
    api: ApiClient, participant_id: str, params: Optional[Json] = None, headers: Optional[Headers] = None
) -> Tuple[List[Json], Json]:
    headers = headers or make_participant_admin_headers(participant_id)
    return validate_paginated(api.list_participant_segment_policies(participant_id, headers, params))


def list_position_accounts_with_meta(
    api: ApiClient, participant_id: str, params: Optional[Json] = None, headers: Optional[Headers] = None
) -> Tuple[List[Json], Json]:
    headers = headers or make_participant_admin_headers(participant_id)
    return validate_paginated(api.list_participant_position_accounts(participant_id, headers, params))


# ==================================================== tier 2: single-record creators
def enroll_participant(
    api: ApiClient,
    legal_name: str = "Alpha National Bank",
    routing_number: str = K.ROUTING_ALPHA,
    settlement_agent_reference: str = "SA-ALPHA-01",
    participation_model: Any = F.OMIT,
) -> Json:
    """Enrol a bank; it lands in `DRAFT`."""
    payload = F.participant_payload(
        legal_name=legal_name,
        routing_number=routing_number,
        settlement_agent_reference=settlement_agent_reference,
        participation_model=participation_model,
    )
    return get_success_data(api.create_participant(payload, NETWORK_OPERATOR), expected_status=201)


def open_position_account(
    api: ApiClient,
    participant_id: str,
    officer: Headers = LIQUIDITY_OFFICER,
    **thresholds: int,
) -> Json:
    """Open the participant's single prefunded position account."""
    figures = dict(ALPHA_ACCOUNT)
    figures.update(thresholds)
    payload = F.position_account_payload(participant_id, **figures)
    return get_success_data(api.create_position_account(payload, officer), expected_status=201)


def file_attestation(
    api: ApiClient, participant_id: str, attestation_document_reference: str = "ATT-ALPHA-2026-08"
) -> Json:
    """File the operational readiness attestation as the bank's own administrator."""
    payload = F.attestation_payload(attestation_document_reference=attestation_document_reference)
    response = api.file_attestation(participant_id, payload, make_participant_admin_headers(participant_id))
    return get_success_data(response, expected_status=200)


def open_certification_window(
    api: ApiClient, participant_id: str, certification_test_suite_version: str = "CERT-2026.2"
) -> Json:
    payload = F.certification_window_payload(certification_test_suite_version)
    return get_success_data(api.open_certification_window(participant_id, payload, NETWORK_OPERATOR))


def record_certification_result(api: ApiClient, participant_id: str, outcome: str = "PASS") -> Json:
    payload = F.certification_result_payload(outcome)
    return get_success_data(api.record_certification_result(participant_id, payload, NETWORK_OPERATOR))


def activate_participant(
    api: ApiClient, participant_id: str, go_live_business_date: str = K.BUSINESS_DATE_2026_08_03
) -> Json:
    payload = F.activation_payload(go_live_business_date)
    return get_success_data(api.activate_participant(participant_id, payload, NETWORK_OPERATOR))


def change_participant_status(
    api: ApiClient, participant_id: str, target_status: str, suspension_reason: Any = F.OMIT
) -> Json:
    payload = F.status_change_payload(target_status, suspension_reason)
    return get_success_data(api.change_participant_status(participant_id, payload, NETWORK_OPERATOR))


def publish_segment_policy(api: ApiClient, participant_id: str, **overrides: Any) -> Json:
    """Publish a segment policy, re-reading the participant for a fresh version pin.

    Every successful publication increments the owning participant's `version`, so
    a fresh read immediately before the write is what a compliant caller does.
    """
    values = dict(CORPORATE_POLICY)
    values.update(overrides)
    expected_version = values.pop("expected_participant_version", None)
    if expected_version is None:
        expected_version = participant_version(api, participant_id)
    payload = F.segment_policy_payload(
        participant_id, expected_participant_version=expected_version, **values
    )
    response = api.create_segment_policy(payload, make_participant_admin_headers(participant_id))
    return get_success_data(response, expected_status=201)


def register_customer_account(
    api: ApiClient,
    participant_id: str,
    account_reference: str = "CUST-ALPHA-0001",
    segment: str = "CORPORATE",
    fraud_risk_baseline: int = 20,
) -> Json:
    payload = F.customer_account_payload(
        participant_id,
        account_reference=account_reference,
        segment=segment,
        fraud_risk_baseline=fraud_risk_baseline,
    )
    response = api.create_customer_account(payload, make_participant_admin_headers(participant_id))
    return get_success_data(response, expected_status=201)


def open_settlement_cycle(api: ApiClient, business_date: str = K.BUSINESS_DATE_2026_08_03) -> Json:
    payload = F.settlement_cycle_payload(business_date)
    return get_success_data(api.create_settlement_cycle(payload, NETWORK_OPERATOR), expected_status=201)


def post_ledger_adjustment(
    api: ApiClient,
    account_id: str,
    entry_type: str,
    magnitude_cents: int,
    reference: Any = F.OMIT,
    officer: Headers = LIQUIDITY_OFFICER,
) -> Json:
    payload = F.ledger_adjustment_payload(entry_type, magnitude_cents, reference)
    response = api.post_ledger_adjustment(account_id, payload, officer)
    return get_success_data(response, expected_status=201)


def fund_account(
    api: ApiClient, account_id: str, magnitude_cents: int, reference: Any = F.OMIT, officer: Headers = LIQUIDITY_OFFICER
) -> Json:
    return post_ledger_adjustment(api, account_id, "FUNDING_CREDIT", magnitude_cents, reference, officer)


def withdraw_from_account(
    api: ApiClient, account_id: str, magnitude_cents: int, reference: Any = F.OMIT, officer: Headers = LIQUIDITY_OFFICER
) -> Json:
    return post_ledger_adjustment(api, account_id, "WITHDRAWAL_DEBIT", magnitude_cents, reference, officer)


def acknowledge_alert(
    api: ApiClient, alert_id: str, remediation_plan: str = "Correspondent funding requested for same-day value.",
    officer: Headers = LIQUIDITY_OFFICER,
) -> Json:
    payload = F.alert_acknowledgement_payload(remediation_plan)
    return get_success_data(api.acknowledge_alert(alert_id, payload, officer))


def originate_transfer(
    api: ApiClient,
    participant_id: str,
    account_id: str,
    customer_account_id: str,
    amount_cents: int,
    operator: Headers = PAYMENT_OPERATOR_ALPHA,
    receiver_routing_number: str = K.ROUTING_BETA,
    expected_position_account_version: Optional[int] = None,
    rfp_id: Any = F.OMIT,
    remittance_reference: Any = F.OMIT,
) -> Json:
    """Originate a transfer, pinning a freshly read position account version."""
    if expected_position_account_version is None:
        expected_position_account_version = account_version(api, account_id)
    payload = F.credit_transfer_payload(
        originator_participant_id=participant_id,
        customer_account_id=customer_account_id,
        amount_cents=amount_cents,
        expected_position_account_version=expected_position_account_version,
        receiver_routing_number=receiver_routing_number,
        rfp_id=rfp_id,
        remittance_reference=remittance_reference,
    )
    return get_success_data(api.create_credit_transfer(payload, operator), expected_status=201)


def accept_transfer(api: ApiClient, transfer_id: str) -> Json:
    return get_success_data(api.accept_credit_transfer(transfer_id, NETWORK_OPERATOR))


def settle_transfer(api: ApiClient, transfer_id: str) -> Json:
    return get_success_data(api.settle_credit_transfer(transfer_id, NETWORK_OPERATOR))


def divert_transfer(
    api: ApiClient, transfer_id: str, fallback_rail: str = "FALLBACK_ACH", headers: Headers = NETWORK_OPERATOR
) -> Json:
    return get_success_data(api.divert_credit_transfer(transfer_id, F.diversion_payload(fallback_rail), headers))


def assign_review(api: ApiClient, review_id: str, reviewer: Headers = FRAUD_REVIEWER) -> Json:
    return get_success_data(api.assign_fraud_review(review_id, reviewer))


def decide_review(
    api: ApiClient,
    review_id: str,
    decision: str,
    decision_rationale: Any = F.OMIT,
    reviewer: Headers = FRAUD_REVIEWER,
) -> Json:
    payload = F.fraud_decision_payload(decision, decision_rationale)
    return get_success_data(api.decide_fraud_review(review_id, payload, reviewer))


def raise_request_for_payment(
    api: ApiClient,
    requestor_participant_id: str,
    debtor_customer_account_id: str,
    amount_cents: int,
    expiry_at: str,
    operator: Headers = PAYMENT_OPERATOR_ALPHA,
    memo: Any = F.OMIT,
) -> Json:
    payload = F.request_for_payment_payload(
        requestor_participant_id, debtor_customer_account_id, amount_cents, expiry_at, memo
    )
    return get_success_data(api.create_request_for_payment(payload, operator), expected_status=201)


def deliver_request_for_payment(api: ApiClient, rfp_id: str) -> Json:
    return get_success_data(api.deliver_request_for_payment(rfp_id, NETWORK_OPERATOR))


def respond_to_request_for_payment(
    api: ApiClient,
    rfp_id: str,
    response: str,
    decline_reason_code: Any = F.OMIT,
    operator: Headers = PAYMENT_OPERATOR_BETA,
) -> Json:
    payload = F.rfp_response_payload(response, decline_reason_code)
    return get_success_data(api.respond_to_request_for_payment(rfp_id, payload, operator))


def amend_request_for_payment(
    api: ApiClient, rfp_id: str, amount_cents: int, memo: Any = F.OMIT, operator: Headers = PAYMENT_OPERATOR_ALPHA
) -> Json:
    payload = F.rfp_amendment_payload(amount_cents, memo)
    return get_success_data(api.amend_request_for_payment(rfp_id, payload, operator))


def lodge_return_request(
    api: ApiClient,
    credit_transfer_id: str,
    requested_by_participant_id: str,
    reason_code: str = "DUPLICATE_PAYMENT",
    returned_amount_cents: Any = F.OMIT,
    narrative: Any = F.OMIT,
    operator: Headers = PAYMENT_OPERATOR_BETA,
) -> Json:
    payload = F.return_request_payload(
        credit_transfer_id, requested_by_participant_id, reason_code, returned_amount_cents, narrative
    )
    return get_success_data(api.create_return_request(payload, operator), expected_status=201)


def honor_return_request(api: ApiClient, return_request_id: str) -> Json:
    return get_success_data(api.honor_return_request(return_request_id, NETWORK_OPERATOR))


def decline_return_request(api: ApiClient, return_request_id: str, decline_reason_code: str) -> Json:
    payload = F.return_decline_payload(decline_reason_code)
    return get_success_data(api.decline_return_request(return_request_id, payload, NETWORK_OPERATOR))


def cutoff_cycle(api: ApiClient, cycle_id: str) -> Json:
    return get_success_data(api.cutoff_settlement_cycle(cycle_id, NETWORK_OPERATOR))


def close_cycle(api: ApiClient, cycle_id: str) -> Json:
    return get_success_data(api.close_settlement_cycle(cycle_id, NETWORK_OPERATOR))


def submit_reconciliation_run(
    api: ApiClient,
    cycle_id: str,
    participant_id: str,
    core_deposit_total_cents: int,
    variant: str = "FINAL",
    platform: Headers = CORE_BANKING_SYSTEM,
) -> Json:
    payload = F.reconciliation_run_payload(cycle_id, participant_id, core_deposit_total_cents, variant)
    return get_success_data(api.create_reconciliation_run(payload, platform), expected_status=201)


def declare_outage(
    api: ApiClient,
    started_at: str,
    scope: str = "PARTICIPANT",
    severity: str = "FULL_OUTAGE",
    fallback_rail: str = "FALLBACK_ACH",
    participant_id: Any = F.OMIT,
    ended_at: Any = F.OMIT,
) -> Json:
    payload = F.outage_event_payload(
        started_at=started_at,
        scope=scope,
        severity=severity,
        fallback_rail=fallback_rail,
        participant_id=participant_id,
        ended_at=ended_at,
    )
    return get_success_data(api.create_outage_event(payload, NETWORK_OPERATOR), expected_status=201)


def resolve_outage(api: ApiClient, event_id: str, ended_at: str) -> Json:
    payload = F.outage_resolution_payload(ended_at)
    return get_success_data(api.resolve_outage_event(event_id, payload, NETWORK_OPERATOR))


def run_sweep(api: ApiClient) -> Json:
    return get_success_data(api.run_network_sweep(NETWORK_OPERATOR))


# =============================================== tier 3: enrolment-to-live composites
def bring_participant_live(
    api: ApiClient,
    legal_name: str = "Alpha National Bank",
    routing_number: str = K.ROUTING_ALPHA,
    settlement_agent_reference: str = "SA-ALPHA-01",
    participation_model: str = "SEND_AND_RECEIVE",
    attestation_document_reference: str = "ATT-ALPHA-2026-08",
    go_live_business_date: str = K.BUSINESS_DATE_2026_08_03,
    account: Optional[Dict[str, int]] = None,
    with_account: bool = True,
) -> ParticipantBundle:
    """Walk one bank from enrolment through certification to `LIVE`.

    The hops are the declared ones: enrolment, opening the prefunded position,
    the administrator's attestation, a certification window, a `PASS` result and
    activation. The bundle returned carries the activated participant record, so
    its `version` is the one a caller would pin on a first policy publication.
    """
    participant = enroll_participant(
        api,
        legal_name=legal_name,
        routing_number=routing_number,
        settlement_agent_reference=settlement_agent_reference,
        participation_model=participation_model,
    )
    participant_id = participant["id"]
    position_account = None
    if with_account:
        position_account = open_position_account(api, participant_id, **(account or ALPHA_ACCOUNT))
    file_attestation(api, participant_id, attestation_document_reference)
    open_certification_window(api, participant_id)
    record_certification_result(api, participant_id, "PASS")
    activated = activate_participant(api, participant_id, go_live_business_date)
    if position_account is not None:
        position_account = read_account(api, position_account["id"])
    return ParticipantBundle(participant=activated, account=position_account)


def live_alpha(api: ApiClient, **overrides: Any) -> ParticipantBundle:
    """Alpha National Bank, routing 021000021, `SEND_AND_RECEIVE` and `LIVE`."""
    return bring_participant_live(api, **overrides)


def live_beta(api: ApiClient, **overrides: Any) -> ParticipantBundle:
    """Beta Trust Bank, routing 021000089 - the counterparty side of the rail."""
    defaults: Dict[str, Any] = {
        "legal_name": "Beta Trust Bank",
        "routing_number": K.ROUTING_BETA,
        "settlement_agent_reference": "SA-BETA-01",
        "attestation_document_reference": "ATT-BETA-2026-08",
        "account": BETA_ACCOUNT,
    }
    defaults.update(overrides)
    return bring_participant_live(api, **defaults)


def live_gamma(api: ApiClient, **overrides: Any) -> ParticipantBundle:
    """Gamma Savings Bank, routing 021000109 - `RECEIVE_ONLY` by default."""
    defaults: Dict[str, Any] = {
        "legal_name": "Gamma Savings Bank",
        "routing_number": K.ROUTING_GAMMA,
        "settlement_agent_reference": "SA-GAMMA-01",
        "attestation_document_reference": "ATT-GAMMA-2026-08",
        "participation_model": "RECEIVE_ONLY",
    }
    defaults.update(overrides)
    return bring_participant_live(api, **defaults)


def live_delta(api: ApiClient, **overrides: Any) -> ParticipantBundle:
    """Delta Community Bank, routing 021000208 - the consumer-segment bank."""
    defaults: Dict[str, Any] = {
        "legal_name": "Delta Community Bank",
        "routing_number": K.ROUTING_DELTA,
        "settlement_agent_reference": "SA-DELTA-01",
        "attestation_document_reference": "ATT-DELTA-2026-08",
    }
    defaults.update(overrides)
    return bring_participant_live(api, **defaults)


# ==================================================== tier 4: configured rail scenarios
def configure_participant(
    api: ApiClient,
    bundle: ParticipantBundle,
    policy: Optional[Dict[str, Any]] = None,
    customer_reference: str = "CUST-ALPHA-0001",
    customer_segment: str = "CORPORATE",
    fraud_risk_baseline: int = 20,
    with_customer: bool = True,
) -> ParticipantBundle:
    """Publish one segment policy and register one customer account on a live bank."""
    published = publish_segment_policy(api, bundle.id, **(policy or {}))
    bundle.policies.append(published)
    if with_customer:
        customer = register_customer_account(
            api,
            bundle.id,
            account_reference=customer_reference,
            segment=customer_segment,
            fraud_risk_baseline=fraud_risk_baseline,
        )
        bundle.customer_accounts.append(customer)
    bundle.participant = read_participant(api, bundle.id)
    return bundle


def alpha_scenario(
    api: ApiClient,
    clock: str = K.CLOCK_2026_08_03_13_00,
    account: Optional[Dict[str, int]] = None,
    policy: Optional[Dict[str, Any]] = None,
    customer_reference: str = "CUST-ALPHA-0001",
    customer_segment: str = "CORPORATE",
    fraud_risk_baseline: int = 20,
    business_date: str = K.BUSINESS_DATE_2026_08_03,
    with_cycle: bool = True,
    with_beta: bool = False,
) -> RailScenario:
    """The canonical single-bank world: Alpha `LIVE` with policy, customer and cycle.

    The clock is set first, because every downstream deadline, window and business
    date is read from it, and the settlement cycle is opened for the business date
    of that clock so that settlement has somewhere to land.
    """
    set_clock(api, clock)
    alpha = live_alpha(api, account=account, go_live_business_date=business_date)
    configure_participant(
        api,
        alpha,
        policy=policy,
        customer_reference=customer_reference,
        customer_segment=customer_segment,
        fraud_risk_baseline=fraud_risk_baseline,
    )
    beta = None
    if with_beta:
        beta = live_beta(api, go_live_business_date=business_date)
    cycle = open_settlement_cycle(api, business_date) if with_cycle else None
    return RailScenario(alpha=alpha, beta=beta, cycle=cycle)


def alpha_and_beta_scenario(api: ApiClient, **overrides: Any) -> RailScenario:
    """Alpha configured for sending plus Beta enrolled as the receiving side."""
    overrides.setdefault("with_beta", True)
    return alpha_scenario(api, **overrides)


def refresh(api: ApiClient, scenario: RailScenario) -> RailScenario:
    """Re-read every record a scenario holds so a test sees post-cascade state."""
    scenario.alpha.participant = read_participant(api, scenario.alpha.id)
    if scenario.alpha.account is not None:
        scenario.alpha.account = read_account(api, scenario.alpha.account_id)
    if scenario.alpha.customer_accounts:
        scenario.alpha.customer_accounts = [
            read_customer_account(api, customer["id"]) for customer in scenario.alpha.customer_accounts
        ]
    if scenario.beta is not None:
        scenario.beta.participant = read_participant(api, scenario.beta.id)
        if scenario.beta.account is not None:
            scenario.beta.account = read_account(api, scenario.beta.account_id)
    if scenario.cycle is not None:
        scenario.cycle = read_cycle(api, scenario.cycle["id"])
    return scenario


# ==================================================== tier 5: traffic-in-flight scenarios
def send_from_alpha(
    api: ApiClient,
    scenario: RailScenario,
    amount_cents: int,
    operator: Headers = PAYMENT_OPERATOR_ALPHA,
    receiver_routing_number: str = K.ROUTING_BETA,
    rfp_id: Any = F.OMIT,
    remittance_reference: Any = F.OMIT,
    customer_account_id: Optional[str] = None,
) -> Json:
    """Originate one transfer out of the scenario's Alpha bank."""
    return originate_transfer(
        api,
        scenario.alpha.id,
        scenario.alpha.account_id,
        customer_account_id or scenario.alpha.customer_account_id,
        amount_cents,
        operator=operator,
        receiver_routing_number=receiver_routing_number,
        rfp_id=rfp_id,
        remittance_reference=remittance_reference,
    )


def settled_transfer_scenario(
    api: ApiClient,
    amount_cents: int = 250_000_000,
    settlement_clock: str = "2026-08-03T13:10:00Z",
    **scenario_overrides: Any,
) -> Tuple[RailScenario, Json]:
    """Alpha and Beta live; one transfer originated, accepted and settled.

    Settlement is the point at which the money actually leaves the position, so
    this is the shared precondition for every exception-side scenario.
    """
    scenario_overrides.setdefault("with_beta", True)
    scenario = alpha_scenario(api, **scenario_overrides)
    transfer = send_from_alpha(api, scenario, amount_cents)
    accept_transfer(api, transfer["id"])
    set_clock(api, settlement_clock)
    settle_transfer(api, transfer["id"])
    return refresh(api, scenario), read_transfer(api, transfer["id"])


def return_requested_scenario(
    api: ApiClient,
    amount_cents: int = 250_000_000,
    returned_amount_cents: Any = F.OMIT,
    reason_code: str = "TECHNICAL_ERROR",
    narrative: Any = F.OMIT,
    lodgement_clock: str = "2026-08-03T13:20:00Z",
    settlement_clock: str = "2026-08-03T13:10:00Z",
    **scenario_overrides: Any,
) -> Tuple[RailScenario, Json, Json]:
    """A settled transfer with the receiving side's return request already lodged."""
    scenario, transfer = settled_transfer_scenario(
        api, amount_cents=amount_cents, settlement_clock=settlement_clock, **scenario_overrides
    )
    set_clock(api, lodgement_clock)
    assert scenario.beta is not None, "a return request needs the receiving participant"
    request = lodge_return_request(
        api,
        transfer["id"],
        scenario.beta.id,
        reason_code=reason_code,
        returned_amount_cents=returned_amount_cents,
        narrative=narrative,
    )
    return refresh(api, scenario), read_transfer(api, transfer["id"]), request


def held_transfer_scenario(
    api: ApiClient,
    amount_cents: int = 50_000_000,
    fraud_risk_baseline: int = 25,
    customer_reference: str = "CUST-ALPHA-0002",
    operator: Headers = PAYMENT_OPERATOR_ALPHA,
    **scenario_overrides: Any,
) -> Tuple[RailScenario, Json, Json]:
    """A transfer that scored into the hold band, plus the review it raised."""
    scenario_overrides.setdefault("customer_reference", customer_reference)
    scenario_overrides.setdefault("fraud_risk_baseline", fraud_risk_baseline)
    scenario = alpha_scenario(api, **scenario_overrides)
    transfer = send_from_alpha(api, scenario, amount_cents, operator=operator)
    review = sole_fraud_review(api, transfer["id"])
    return refresh(api, scenario), read_transfer(api, transfer["id"]), review


def frozen_alpha_scenario(
    api: ApiClient,
    withdrawal_cents: int = 250_000_000,
    reference: Any = F.OMIT,
    officer: Headers = LIQUIDITY_OFFICER,
    **scenario_overrides: Any,
) -> RailScenario:
    """Alpha driven to `RED` (and therefore `SEND_FROZEN`) by a treasury withdrawal."""
    scenario = alpha_scenario(api, **scenario_overrides)
    withdraw_from_account(api, scenario.alpha.account_id, withdrawal_cents, reference, officer)
    return refresh(api, scenario)


def parked_transfer_scenario(
    api: ApiClient,
    transfer_amounts: Tuple[int, ...] = (250_000_000,),
    withdrawal_cents: int = 250_000_000,
    freeze_clock: str = "2026-08-03T13:05:00Z",
    reference: Any = F.OMIT,
    officer: Headers = LIQUIDITY_OFFICER,
    **scenario_overrides: Any,
) -> Tuple[RailScenario, List[Json]]:
    """Transfers originated in `INITIATED`, then parked by a freeze on the same bank.

    Freezing runs the parking pass before any release pass could consume the
    liquidity it frees, which is what leaves every listed transfer queued.
    """
    scenario = alpha_scenario(api, **scenario_overrides)
    transfers = [send_from_alpha(api, scenario, amount) for amount in transfer_amounts]
    set_clock(api, freeze_clock)
    withdraw_from_account(api, scenario.alpha.account_id, withdrawal_cents, reference, officer)
    return refresh(api, scenario), [read_transfer(api, transfer["id"]) for transfer in transfers]


def delivered_rfp_scenario(
    api: ApiClient,
    amount_cents: int = 5_000_000,
    expiry_at: str = "2026-08-04T13:00:00Z",
    debtor_reference: str = "CUST-BETA-0001",
    debtor_segment: str = "CORPORATE",
    memo: Any = F.OMIT,
    deliver: bool = True,
    **scenario_overrides: Any,
) -> Tuple[RailScenario, Json]:
    """Alpha asks Beta's customer to pay; the request is raised and delivered.

    Beta needs its own segment policy and customer account because the debtor of a
    request for payment legitimately belongs to the other bank.
    """
    scenario_overrides.setdefault("with_beta", True)
    scenario = alpha_scenario(api, **scenario_overrides)
    assert scenario.beta is not None
    configure_participant(
        api,
        scenario.beta,
        policy={"segment": debtor_segment},
        customer_reference=debtor_reference,
        customer_segment=debtor_segment,
    )
    rfp = raise_request_for_payment(
        api,
        scenario.alpha.id,
        scenario.beta.customer_account_id,
        amount_cents,
        expiry_at,
        memo=memo,
    )
    if deliver:
        rfp = deliver_request_for_payment(api, rfp["id"])
    return refresh(api, scenario), rfp


def accepted_rfp_scenario(api: ApiClient, **overrides: Any) -> Tuple[RailScenario, Json]:
    """A delivered request that Beta's operator has accepted, ready to be fulfilled."""
    scenario, rfp = delivered_rfp_scenario(api, **overrides)
    accepted = respond_to_request_for_payment(api, rfp["id"], "ACCEPT")
    return scenario, accepted


def outage_scenario(
    api: ApiClient,
    started_at: str = "2026-08-03T13:05:00Z",
    scope: str = "PARTICIPANT",
    severity: str = "FULL_OUTAGE",
    fallback_rail: str = "FALLBACK_ACH",
    transfer_amounts: Tuple[int, ...] = (),
    **scenario_overrides: Any,
) -> Tuple[RailScenario, Json, List[Json]]:
    """Alpha taken `OFFLINE` by a declared outage, with its traffic parked."""
    scenario = alpha_scenario(api, **scenario_overrides)
    transfers = [send_from_alpha(api, scenario, amount) for amount in transfer_amounts]
    set_clock(api, started_at)
    event = declare_outage(
        api,
        started_at=started_at,
        scope=scope,
        severity=severity,
        fallback_rail=fallback_rail,
        participant_id=scenario.alpha.id if scope == "PARTICIPANT" else F.OMIT,
    )
    return (
        refresh(api, scenario),
        event,
        [read_transfer(api, transfer["id"]) for transfer in transfers],
    )
