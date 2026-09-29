"""Composite setup helpers.

Every test starts against an empty database, so each helper below builds its
preconditions from scratch through the published endpoints only. Helpers return
a mutable context dictionary that later helpers extend, so a test can start at
whatever state it needs and keep the identifiers it will assert on.

Context keys in use:
    concessionaire, concessionaire_id, cnr_headers,
    concession, concession_id,
    milestone, milestones,
    service_period, service_period_id,
    performance_report, performance_reports,
    deduction_events, dispute, relief_claims,
    reserve_transactions, refinancing_event, enforcement_action
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ACTUAL_COMMENCEMENT_DATE,
    CLOCK_AFTER_PERIOD_ONE,
    CLOCK_COMMENCEMENT,
    CLOCK_DRAFTING,
    FINANCIAL_CLOSE_DATE,
    TEST_DEFAULTS,
)
from .factories import (
    adjudicate_dispute_payload,
    approve_milestone_payload,
    calculate_compensation_payload,
    certify_service_commencement_payload,
    consent_refinancing_payload,
    create_concession_payload,
    create_concessionaire_payload,
    create_deduction_event_payload,
    create_dispute_payload,
    create_drawdown_milestone_payload,
    create_enforcement_action_payload,
    create_performance_report_payload,
    create_refinancing_event_payload,
    create_relief_claim_payload,
    create_reserve_transaction_payload,
    create_service_period_payload,
    cure_enforcement_action_payload,
    determine_relief_claim_payload,
    financial_close_payload,
    handback_survey_payload,
    reject_milestone_payload,
    pay_service_period_payload,
    refer_back_dispute_payload,
    reject_performance_report_payload,
    resubmit_dispute_payload,
    reverse_reserve_transaction_payload,
    settle_enforcement_action_payload,
    verify_service_period_payload,
    withdraw_deduction_event_payload,
)
from .test_users import TEST_USERS, make_concessionaire_headers

PERIOD_ONE_START = TEST_DEFAULTS["PERIOD_ONE_START"]
PERIOD_ONE_END = TEST_DEFAULTS["PERIOD_ONE_END"]
PERIOD_TWO_START = "2027-04-01"
PERIOD_TWO_END = "2027-05-01"

ADMIN = TEST_USERS["platform_admin_headers"]
ALPHA = TEST_USERS["officer_alpha_headers"]
BETA = TEST_USERS["officer_beta_headers"]
GAMMA = TEST_USERS["officer_gamma_headers"]
DELTA = TEST_USERS["officer_delta_headers"]
EPSILON = TEST_USERS["officer_epsilon_headers"]
LENDER = TEST_USERS["lender_agent_headers"]
CERTIFIER = TEST_USERS["independent_certifier_headers"]


# --- Primitives --------------------------------------------------------------


def set_clock(instant: str):
    """Move the logical clock. Creates and mutates no business row."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


def create_concessionaire(**overrides) -> dict:
    payload = create_concessionaire_payload(**overrides)
    return get_success_data(api_client.create_concessionaire(payload, ADMIN))


def create_concession(concessionaire_id: str, headers=None, **overrides) -> dict:
    payload = create_concession_payload(concessionaire_id, **overrides)
    return get_success_data(api_client.create_concession(payload, headers or ALPHA))


def refresh_concession(ctx: dict, headers=None) -> dict:
    """Re-read the concession so the caller holds its current version."""
    concession = get_success_data(
        api_client.get_concession(ctx["concession_id"], headers or ALPHA)
    )
    ctx["concession"] = concession
    return concession


def refresh_service_period(ctx: dict, headers=None) -> dict:
    period = get_success_data(
        api_client.get_service_period(ctx["service_period_id"], headers or ALPHA)
    )
    ctx["service_period"] = period
    return period


def reach_financial_close(
    ctx: dict, close_date: str = FINANCIAL_CLOSE_DATE, headers=None
) -> dict:
    concession = get_success_data(
        api_client.financial_close(
            ctx["concession_id"], financial_close_payload(close_date), headers or ALPHA
        )
    )
    ctx["concession"] = concession
    return concession


def request_milestone(
    ctx: dict,
    milestone_name: str,
    requested_amount_cents: int,
    expected_concession_version=None,
    headers=None,
) -> dict:
    version = (
        expected_concession_version
        if expected_concession_version is not None
        else ctx["concession"]["version"]
    )
    payload = create_drawdown_milestone_payload(
        milestone_name, requested_amount_cents, version
    )
    milestone = get_success_data(
        api_client.create_drawdown_milestone(
            ctx["concession_id"], payload, headers or ctx["cnr_headers"]
        )
    )
    ctx.setdefault("milestones", []).append(milestone)
    ctx["milestone"] = milestone
    return milestone


def approve_milestone(ctx: dict, milestone_id: str, certified_cost_cents: int, headers=None) -> dict:
    milestone = get_success_data(
        api_client.approve_drawdown_milestone(
            milestone_id,
            approve_milestone_payload(certified_cost_cents),
            headers or CERTIFIER,
        )
    )
    ctx["milestone"] = milestone
    return milestone


def reject_milestone(ctx: dict, milestone_id: str, rejection_reason: str, headers=None) -> dict:
    milestone = get_success_data(
        api_client.reject_drawdown_milestone(
            milestone_id,
            reject_milestone_payload(rejection_reason),
            headers or CERTIFIER,
        )
    )
    ctx["milestone"] = milestone
    return milestone


def disburse_milestone(ctx: dict, milestone_id: str, headers=None) -> dict:
    milestone = get_success_data(
        api_client.disburse_drawdown_milestone(milestone_id, headers or LENDER)
    )
    ctx["milestone"] = milestone
    return milestone


def certify_service_commencement(
    ctx: dict, actual_commencement_date: str = ACTUAL_COMMENCEMENT_DATE, headers=None
) -> dict:
    concession = get_success_data(
        api_client.certify_service_commencement(
            ctx["concession_id"],
            certify_service_commencement_payload(actual_commencement_date),
            headers or CERTIFIER,
        )
    )
    ctx["concession"] = concession
    return concession


def add_service_period(
    ctx: dict,
    period_index: int = 1,
    period_start: str = PERIOD_ONE_START,
    period_end: str = PERIOD_ONE_END,
    headers=None,
) -> dict:
    period = get_success_data(
        api_client.create_service_period(
            ctx["concession_id"],
            create_service_period_payload(period_index, period_start, period_end),
            headers or ALPHA,
        )
    )
    ctx.setdefault("service_periods", []).append(period)
    ctx["service_period"] = period
    ctx["service_period_id"] = period["id"]
    return period


def submit_performance_report(
    ctx: dict,
    unavailable_minutes: int = 100,
    category_a_failures: int = 2,
    category_b_failures: int = 4,
    expected_service_period_version=None,
    service_period_id: str = None,
    headers=None,
) -> dict:
    period_id = service_period_id or ctx["service_period_id"]
    if expected_service_period_version is None:
        period = get_success_data(api_client.get_service_period(period_id, ALPHA))
        expected_service_period_version = period["version"]
    payload = create_performance_report_payload(
        unavailable_minutes,
        category_a_failures,
        category_b_failures,
        expected_service_period_version,
    )
    report = get_success_data(
        api_client.create_performance_report(
            period_id, payload, headers or ctx["cnr_headers"]
        )
    )
    ctx.setdefault("performance_reports", []).append(report)
    ctx["performance_report"] = report
    return report


def reject_performance_report(ctx: dict, report_id: str, rejection_reason: str, headers=None) -> dict:
    report = get_success_data(
        api_client.reject_performance_report(
            report_id, reject_performance_report_payload(rejection_reason), headers or BETA
        )
    )
    ctx["performance_report"] = report
    return report


def verify_period(
    ctx: dict,
    verified_unavailable_minutes: int = 100,
    verified_category_a_failures: int = 2,
    verified_category_b_failures: int = 4,
    service_period_id: str = None,
    headers=None,
) -> dict:
    period = get_success_data(
        api_client.verify_service_period(
            service_period_id or ctx["service_period_id"],
            verify_service_period_payload(
                verified_unavailable_minutes,
                verified_category_a_failures,
                verified_category_b_failures,
            ),
            headers or BETA,
        )
    )
    ctx["service_period"] = period
    return period


def invoice_period(ctx: dict, service_period_id: str = None, headers=None) -> dict:
    period = get_success_data(
        api_client.invoice_service_period(
            service_period_id or ctx["service_period_id"],
            headers or ctx["cnr_headers"],
        )
    )
    ctx["service_period"] = period
    return period


def pay_period(
    ctx: dict,
    payment_reference: str = "BACS-2027-04-0001",
    service_period_id: str = None,
    headers=None,
) -> dict:
    period = get_success_data(
        api_client.pay_service_period(
            service_period_id or ctx["service_period_id"],
            pay_service_period_payload(payment_reference),
            headers or BETA,
        )
    )
    ctx["service_period"] = period
    return period


def issue_deduction_event(
    ctx: dict,
    points: int,
    deduction_type: str = "UNAVAILABILITY",
    service_period_id: str = None,
    headers=None,
) -> dict:
    event = get_success_data(
        api_client.create_deduction_event(
            service_period_id or ctx["service_period_id"],
            create_deduction_event_payload(deduction_type, points),
            headers or GAMMA,
        )
    )
    ctx.setdefault("deduction_events", []).append(event)
    ctx["deduction_event"] = event
    return event


def withdraw_deduction_event(ctx: dict, event_id: str, withdrawal_reason: str, headers=None) -> dict:
    event = get_success_data(
        api_client.withdraw_deduction_event(
            event_id, withdraw_deduction_event_payload(withdrawal_reason), headers or GAMMA
        )
    )
    ctx["deduction_event"] = event
    return event


def raise_dispute(ctx: dict, event_id: str, grounds: str, headers=None) -> dict:
    dispute = get_success_data(
        api_client.create_deduction_dispute(
            event_id, create_dispute_payload(grounds), headers or ctx["cnr_headers"]
        )
    )
    ctx["dispute"] = dispute
    return dispute


def refer_dispute_back(ctx: dict, dispute_id: str, referred_back_reason: str, headers=None) -> dict:
    dispute = get_success_data(
        api_client.refer_back_deduction_dispute(
            dispute_id, refer_back_dispute_payload(referred_back_reason), headers or BETA
        )
    )
    ctx["dispute"] = dispute
    return dispute


def resubmit_dispute(ctx: dict, dispute_id: str, grounds: str, headers=None) -> dict:
    dispute = get_success_data(
        api_client.resubmit_deduction_dispute(
            dispute_id, resubmit_dispute_payload(grounds), headers or ctx["cnr_headers"]
        )
    )
    ctx["dispute"] = dispute
    return dispute


def adjudicate_dispute(
    ctx: dict, dispute_id: str, decision: str, outcome_note: str, headers=None
) -> dict:
    dispute = get_success_data(
        api_client.adjudicate_deduction_dispute(
            dispute_id, adjudicate_dispute_payload(decision, outcome_note), headers or BETA
        )
    )
    ctx["dispute"] = dispute
    return dispute


def add_relief_claim(
    ctx: dict,
    claim_type: str,
    event_start: str,
    event_end: str,
    claimed_relief_days: int,
    claimed_cost_cents: int,
    headers=None,
) -> dict:
    claim = get_success_data(
        api_client.create_relief_claim(
            ctx["concession_id"],
            create_relief_claim_payload(
                claim_type,
                event_start,
                event_end,
                claimed_relief_days,
                claimed_cost_cents,
            ),
            headers or ctx["cnr_headers"],
        )
    )
    ctx.setdefault("relief_claims", []).append(claim)
    ctx["relief_claim"] = claim
    return claim


def determine_relief_claim(ctx: dict, claim_id: str, decision: str, headers=None, **extra) -> dict:
    claim = get_success_data(
        api_client.determine_relief_claim(
            claim_id, determine_relief_claim_payload(decision, **extra), headers or ALPHA
        )
    )
    ctx["relief_claim"] = claim
    return claim


def add_reserve_transaction(
    ctx: dict, txn_type: str, amount_cents: int, reason: str, headers=None
) -> dict:
    row = get_success_data(
        api_client.create_reserve_transaction(
            ctx["concession_id"],
            create_reserve_transaction_payload(txn_type, amount_cents, reason),
            headers or ctx["cnr_headers"],
        )
    )
    ctx.setdefault("reserve_transactions", []).append(row)
    ctx["reserve_transaction"] = row
    return row


def reverse_reserve_transaction(ctx: dict, transaction_id: str, reason: str, headers=None) -> dict:
    row = get_success_data(
        api_client.reverse_reserve_transaction(
            transaction_id, reverse_reserve_transaction_payload(reason), headers or ADMIN
        )
    )
    ctx.setdefault("reserve_transactions", []).append(row)
    ctx["reserve_transaction"] = row
    return row


def run_handback_survey(
    ctx: dict,
    handback_survey_date: str,
    handback_rectification_cost_cents: int,
    headers=None,
) -> dict:
    concession = get_success_data(
        api_client.handback_survey(
            ctx["concession_id"],
            handback_survey_payload(
                handback_survey_date, handback_rectification_cost_cents
            ),
            headers or CERTIFIER,
        )
    )
    ctx["concession"] = concession
    return concession


def propose_refinancing(
    ctx: dict,
    refinancing_date: str,
    new_senior_debt_cents: int,
    outstanding_senior_debt_cents: int,
    refinancing_cost_cents: int,
    headers=None,
) -> dict:
    event = get_success_data(
        api_client.create_refinancing_event(
            ctx["concession_id"],
            create_refinancing_event_payload(
                refinancing_date,
                new_senior_debt_cents,
                outstanding_senior_debt_cents,
                refinancing_cost_cents,
            ),
            headers or ctx["cnr_headers"],
        )
    )
    ctx["refinancing_event"] = event
    return event


def consent_refinancing(
    ctx: dict, refinancing_event_id: str, decision: str = "CONSENT", expected_concession_version=None, headers=None
) -> dict:
    version = (
        expected_concession_version
        if expected_concession_version is not None
        else ctx["concession"]["version"]
    )
    event = get_success_data(
        api_client.consent_refinancing_event(
            refinancing_event_id,
            consent_refinancing_payload(decision, version),
            headers or DELTA,
        )
    )
    ctx["refinancing_event"] = event
    return event


def raise_enforcement_action(
    ctx: dict, action_type: str, trigger_reason: str, effective_date: str, headers=None
) -> dict:
    action = get_success_data(
        api_client.create_enforcement_action(
            ctx["concession_id"],
            create_enforcement_action_payload(action_type, trigger_reason, effective_date),
            headers or ALPHA,
        )
    )
    ctx.setdefault("enforcement_actions", []).append(action)
    ctx["enforcement_action"] = action
    return action


def cure_enforcement_action(ctx: dict, action_id: str, cure_note: str, headers=None) -> dict:
    action = get_success_data(
        api_client.cure_enforcement_action(
            action_id, cure_enforcement_action_payload(cure_note), headers or LENDER
        )
    )
    ctx["enforcement_action"] = action
    return action


def escalate_enforcement_action(ctx: dict, action_id: str, headers=None) -> dict:
    action = get_success_data(
        api_client.escalate_enforcement_action(action_id, headers or LENDER)
    )
    ctx["enforcement_action"] = action
    return action


def calculate_compensation(
    ctx: dict,
    action_id: str,
    termination_date: str,
    outstanding_senior_debt_cents: int,
    headers=None,
    **extra,
) -> dict:
    action = get_success_data(
        api_client.calculate_compensation(
            action_id,
            calculate_compensation_payload(
                termination_date, outstanding_senior_debt_cents, **extra
            ),
            headers or ALPHA,
        )
    )
    ctx["enforcement_action"] = action
    return action


def settle_enforcement_action(
    ctx: dict, action_id: str, settlement_reference: str, headers=None
) -> dict:
    action = get_success_data(
        api_client.settle_enforcement_action(
            action_id,
            settle_enforcement_action_payload(settlement_reference),
            headers or EPSILON,
        )
    )
    ctx["enforcement_action"] = action
    return action


# --- Tier 1: concession state progression ------------------------------------


def setup_drafted_concession(
    clock: str = CLOCK_DRAFTING,
    legal_name: str = None,
    sponsor_equity_commitment_cents: int = None,
    **concession_overrides,
) -> dict:
    """A registered sponsor with one concession in DRAFTED."""
    if clock is not None:
        set_clock(clock)
    sponsor_kwargs = {}
    if legal_name is not None:
        sponsor_kwargs["legal_name"] = legal_name
    if sponsor_equity_commitment_cents is not None:
        sponsor_kwargs["sponsor_equity_commitment_cents"] = sponsor_equity_commitment_cents
    concessionaire = create_concessionaire(**sponsor_kwargs)
    concession = create_concession(concessionaire["id"], **concession_overrides)
    return {
        "concessionaire": concessionaire,
        "concessionaire_id": concessionaire["id"],
        "cnr_headers": make_concessionaire_headers(concessionaire["id"]),
        "concession": concession,
        "concession_id": concession["id"],
    }


def setup_concession_at_financial_close(
    close_date: str = FINANCIAL_CLOSE_DATE, **kwargs
) -> dict:
    """A concession whose financial close has been recorded, so its charge is fixed."""
    ctx = setup_drafted_concession(**kwargs)
    reach_financial_close(ctx, close_date)
    return ctx


def setup_concession_in_construction(
    milestone_name: str = "M1 Design Complete",
    requested_amount_cents: int = 120000000,
    certified_cost_cents: int = None,
    **kwargs,
) -> dict:
    """A concession driven into CONSTRUCTION by a first disbursed milestone."""
    ctx = setup_concession_at_financial_close(**kwargs)
    milestone = request_milestone(ctx, milestone_name, requested_amount_cents)
    approve_milestone(
        ctx,
        milestone["id"],
        certified_cost_cents if certified_cost_cents is not None else requested_amount_cents,
    )
    disburse_milestone(ctx, milestone["id"])
    refresh_concession(ctx)
    return ctx


def setup_concession_in_operations(
    commencement_clock: str = CLOCK_COMMENCEMENT,
    actual_commencement_date: str = ACTUAL_COMMENCEMENT_DATE,
    **kwargs,
) -> dict:
    """A concession whose service commencement has been certified: status OPERATIONS."""
    ctx = setup_concession_in_construction(**kwargs)
    if commencement_clock is not None:
        set_clock(commencement_clock)
    certify_service_commencement(ctx, actual_commencement_date)
    return ctx


# --- Tier 2: service period hierarchy ----------------------------------------


def setup_pending_service_period(
    period_index: int = 1,
    period_start: str = PERIOD_ONE_START,
    period_end: str = PERIOD_ONE_END,
    advance_clock_to: str = CLOCK_AFTER_PERIOD_ONE,
    **kwargs,
) -> dict:
    """An operational concession with one service period awaiting its return."""
    ctx = setup_concession_in_operations(**kwargs)
    add_service_period(ctx, period_index, period_start, period_end)
    if advance_clock_to is not None:
        set_clock(advance_clock_to)
    return ctx


def setup_self_reported_period(
    unavailable_minutes: int = 100,
    category_a_failures: int = 2,
    category_b_failures: int = 4,
    **kwargs,
) -> dict:
    """A service period carrying one SUBMITTED performance return."""
    ctx = setup_pending_service_period(**kwargs)
    submit_performance_report(
        ctx,
        unavailable_minutes,
        category_a_failures,
        category_b_failures,
        expected_service_period_version=ctx["service_period"]["version"],
    )
    refresh_service_period(ctx)
    return ctx


# --- Tier 3: full-lifecycle shortcuts ----------------------------------------


def setup_verified_period(
    verified_unavailable_minutes: int = 100,
    verified_category_a_failures: int = 2,
    verified_category_b_failures: int = 4,
    **kwargs,
) -> dict:
    """A verified service period: the money is settled and deductions may be issued."""
    ctx = setup_self_reported_period(**kwargs)
    verify_period(
        ctx,
        verified_unavailable_minutes,
        verified_category_a_failures,
        verified_category_b_failures,
    )
    refresh_concession(ctx)
    return ctx


def setup_invoiced_period(**kwargs) -> dict:
    """A verified period that has been invoiced."""
    ctx = setup_verified_period(**kwargs)
    invoice_period(ctx)
    return ctx


def setup_paid_period(payment_reference: str = "BACS-2027-04-0001", **kwargs) -> dict:
    """A verified period that has been invoiced and paid."""
    ctx = setup_invoiced_period(**kwargs)
    pay_period(ctx, payment_reference)
    return ctx


# --- Tier 4: accumulation and threshold targeting ----------------------------


def setup_period_with_two_deduction_events(**kwargs) -> dict:
    """A verified period already carrying two issued deductions worth 1250000 raw."""
    ctx = setup_verified_period(**kwargs)
    issue_deduction_event(ctx, 400, "UNAVAILABILITY")
    issue_deduction_event(ctx, 600, "PERFORMANCE_FAILURE")
    refresh_service_period(ctx)
    refresh_concession(ctx)
    return ctx


def setup_period_at_deduction_cap(**kwargs) -> dict:
    """A verified period whose three deductions exceed the period cap in the raw."""
    ctx = setup_period_with_two_deduction_events(**kwargs)
    issue_deduction_event(ctx, 500, "PERFORMANCE_FAILURE")
    refresh_service_period(ctx)
    refresh_concession(ctx)
    return ctx


def setup_period_with_breaching_deduction(**kwargs) -> dict:
    """A verified period carrying a single 600-point performance deduction."""
    ctx = setup_verified_period(**kwargs)
    issue_deduction_event(ctx, 600, "PERFORMANCE_FAILURE")
    refresh_service_period(ctx)
    refresh_concession(ctx)
    return ctx


def setup_disputed_deduction(
    points: int = 400,
    deduction_type: str = "UNAVAILABILITY",
    grounds: str = "unavailability minutes double counted in the March log",
    **kwargs,
) -> dict:
    """A verified period with one deduction under an open dispute."""
    ctx = setup_verified_period(**kwargs)
    event = issue_deduction_event(ctx, points, deduction_type)
    raise_dispute(ctx, event["id"], grounds)
    refresh_service_period(ctx)
    refresh_concession(ctx)
    return ctx


def setup_two_service_periods(
    advance_clock_to: str = "2027-05-02T00:00:00Z", **kwargs
) -> dict:
    """An operational concession with two adjacent monthly periods awaiting returns."""
    ctx = setup_concession_in_operations(**kwargs)
    first = add_service_period(ctx, 1, PERIOD_ONE_START, PERIOD_ONE_END)
    second = add_service_period(ctx, 2, PERIOD_TWO_START, PERIOD_TWO_END)
    ctx["service_period_one"] = first
    ctx["service_period_two"] = second
    if advance_clock_to is not None:
        set_clock(advance_clock_to)
    return ctx


# --- Tier 5: enforcement and finalisation ------------------------------------


def setup_active_step_in(
    trigger_reason: str = "PERSISTENT_BREACH",
    effective_date: str = "2027-04-02",
    headers=None,
    **kwargs,
) -> dict:
    """An operational concession moved into STEP_IN by an active step-in action."""
    ctx = setup_concession_in_operations(**kwargs)
    raise_enforcement_action(ctx, "STEP_IN", trigger_reason, effective_date, headers or LENDER)
    refresh_concession(ctx)
    return ctx


def setup_notified_termination(
    trigger_reason: str = "AUTHORITY_VOLUNTARY",
    effective_date: str = "2027-04-02",
    headers=None,
    **kwargs,
) -> dict:
    """An operational concession with a notified termination freezing further change."""
    ctx = setup_concession_in_operations(**kwargs)
    raise_enforcement_action(
        ctx, "TERMINATION", trigger_reason, effective_date, headers or ALPHA
    )
    refresh_concession(ctx)
    return ctx


def setup_calculated_compensation(
    trigger_reason: str = "AUTHORITY_VOLUNTARY",
    effective_date: str = "2028-01-21",
    termination_date: str = "2028-01-21",
    outstanding_senior_debt_cents: int = 180000000,
    clock: str = "2028-01-21T00:00:00Z",
    calculate_headers=None,
    **kwargs,
) -> dict:
    """A termination whose compensation has been calculated and awaits settlement."""
    ctx = setup_concession_in_operations(**kwargs)
    if clock is not None:
        set_clock(clock)
    action = raise_enforcement_action(ctx, "TERMINATION", trigger_reason, effective_date, ALPHA)
    calculate_compensation(
        ctx,
        action["id"],
        termination_date,
        outstanding_senior_debt_cents,
        calculate_headers or ALPHA,
    )
    return ctx


def setup_proposed_refinancing(
    refinancing_date: str = "2027-01-25",
    new_senior_debt_cents: int = 232000000,
    outstanding_senior_debt_cents: int = 180000000,
    refinancing_cost_cents: int = 2000000,
    **kwargs,
) -> dict:
    """An operational concession with a refinancing awaiting the authority's consent."""
    ctx = setup_concession_in_operations(**kwargs)
    propose_refinancing(
        ctx,
        refinancing_date,
        new_senior_debt_cents,
        outstanding_senior_debt_cents,
        refinancing_cost_cents,
    )
    return ctx


def setup_seeded_reserve_with_withdrawal(
    amount_cents: int = 3000000,
    reason: str = "carriageway resurfacing tranche 1",
    **kwargs,
) -> dict:
    """A construction-seeded reserve ledger carrying one withdrawal on top of the seed."""
    ctx = setup_concession_in_construction(**kwargs)
    add_reserve_transaction(ctx, "WITHDRAWAL", amount_cents, reason)
    refresh_concession(ctx)
    return ctx


def setup_notified_relief_claim(
    claim_type: str = "RELIEF_EVENT",
    event_start: str = "2027-02-01",
    event_end: str = "2027-02-10",
    claimed_relief_days: int = 10,
    claimed_cost_cents: int = 400000,
    notification_clock: str = "2027-02-05T00:00:00Z",
    **kwargs,
) -> dict:
    """An operational concession with one claim notified inside its window."""
    ctx = setup_concession_in_operations(**kwargs)
    if notification_clock is not None:
        set_clock(notification_clock)
    add_relief_claim(
        ctx, claim_type, event_start, event_end, claimed_relief_days, claimed_cost_cents
    )
    return ctx


# --- Listing helpers ---------------------------------------------------------


def list_deduction_events_for_period(service_period_id: str, headers=None, **params) -> tuple:
    """Return (rows, meta) for one period's deduction events, oldest first."""
    query = {"service_period_id": service_period_id}
    query.update(params)
    body = api_client.list_deduction_events(headers or ALPHA, params=query).json()
    return body["data"], body["meta"]


def list_reserve_rows(concession_id: str, headers=None, **params) -> tuple:
    """Return (rows, meta) for one concession's reserve ledger, oldest first."""
    query = {"concession_id": concession_id}
    query.update(params)
    body = api_client.list_reserve_transactions(headers or ALPHA, params=query).json()
    return body["data"], body["meta"]


def list_enforcement_rows(concession_id: str, headers=None, **params) -> tuple:
    """Return (rows, meta) for one concession's enforcement actions, oldest first."""
    query = {"concession_id": concession_id}
    query.update(params)
    body = api_client.list_enforcement_actions(headers or ALPHA, params=query).json()
    return body["data"], body["meta"]
