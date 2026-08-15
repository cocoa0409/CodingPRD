"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch via PRD-declared endpoints and use
get_success_data() so setup failures surface as clear "Setup failed" errors.
The dominant preamble across the suite is: statutory profile -> payee ->
settlement agreement -> execute -> qualified assignment -> annuity policy ->
mark-in-force -> payment schedule -> payment rows -> activate -> logical clock.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_state_profile_payload,
    create_payee_payload,
    create_guardianship_case_payload,
    create_settlement_agreement_payload,
    create_qualified_assignment_payload,
    create_annuity_policy_payload,
    create_payment_schedule_payload,
    create_scheduled_payment_payload,
    create_transfer_petition_payload,
    create_death_claim_payload,
    create_commutation_request_payload,
    create_escheatment_batch_payload,
)
from .test_users import (
    TEST_USERS,
    make_case_manager_headers,
    make_operations_specialist_headers,
    make_compliance_officer_headers,
    make_judicial_recorder_headers,
    make_payee_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CASE_MGR = TEST_USERS["case_manager_headers"]
OPS = TEST_USERS["operations_specialist_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
RECORDER = TEST_USERS["judicial_recorder_headers"]
READER = TEST_USERS["reader_headers"]


# --- Tier 0: single-resource creators ----------------------------------------

def create_profile(**overrides):
    """Register a statutory profile. Returns the created profile."""
    return get_success_data(api_client.create_state_profile(create_state_profile_payload(**overrides), ADMIN))


def create_payee(**overrides):
    """Register a payee (its address_state_code profile must already exist)."""
    return get_success_data(api_client.create_payee(create_payee_payload(**overrides), CASE_MGR))


def set_clock(to_iso8601):
    """Advance the logical clock; runs the system sweep (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def get_agreement(agreement_id):
    return get_success_data(api_client.get_settlement_agreement(agreement_id, READER))


def get_policy(policy_id):
    return get_success_data(api_client.get_annuity_policy(policy_id, READER))


def get_payment(payment_id):
    return get_success_data(api_client.get_scheduled_payment(payment_id, READER))


def get_payee(payee_id):
    return get_success_data(api_client.get_payee(payee_id, READER))


def get_schedule(schedule_id):
    return get_success_data(api_client.get_payment_schedule(schedule_id, READER))


def get_petition(petition_id):
    return get_success_data(api_client.get_transfer_petition(petition_id, READER))


def get_batch(batch_id):
    return get_success_data(api_client.get_escheatment_batch(batch_id, READER))


def get_guardianship_case(case_id):
    return get_success_data(api_client.get_guardianship_case(case_id, READER))


def get_returned_case_for_payment(payment_id):
    """Fetch the returned-payment case opened against a payment (list filter)."""
    resp = api_client.list_returned_payment_cases(READER, params={"scheduled_payment_id": payment_id})
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1, f"Setup failed: no returned-payment case for payment {payment_id}"
    return data[0]


# --- Tier 1/2: agreement stack (state progression + hierarchy) ----------------

def setup_draft_agreement(profile_overrides=None, payee_overrides=None, agreement_overrides=None):
    """Profile + payee + DRAFT agreement. Returns ctx dict."""
    profile = create_profile(**(profile_overrides or {}))
    payee = create_payee(**(payee_overrides or {}))
    agreement = get_success_data(api_client.create_settlement_agreement(
        create_settlement_agreement_payload(payee["id"], **(agreement_overrides or {})), CASE_MGR))
    return {"profile": profile, "payee": payee, "agreement": agreement}


def setup_executed_agreement(profile_overrides=None, payee_overrides=None, agreement_overrides=None):
    """setup_draft_agreement + execute. Returns ctx dict."""
    ctx = setup_draft_agreement(profile_overrides, payee_overrides, agreement_overrides)
    ctx["agreement"] = get_success_data(
        api_client.execute_settlement_agreement(ctx["agreement"]["id"], CASE_MGR))
    return ctx


def setup_funded_agreement(profile_overrides=None, payee_overrides=None,
                           agreement_overrides=None, policy_overrides=None):
    """Full funding chain: agreement EXECUTED -> ASSIGNED -> FUNDED with policy IN_FORCE.
    Returns ctx dict with agreement/assignment/policy."""
    ctx = setup_executed_agreement(profile_overrides, payee_overrides, agreement_overrides)
    assignment = get_success_data(api_client.create_qualified_assignment(
        create_qualified_assignment_payload(ctx["agreement"]["id"]), CASE_MGR))
    ctx["assignment"] = assignment
    ctx["agreement"] = get_agreement(ctx["agreement"]["id"])
    policy = get_success_data(api_client.create_annuity_policy(
        create_annuity_policy_payload(ctx["agreement"]["id"], assignment["id"],
                                      **(policy_overrides or {})), CASE_MGR))
    ctx["policy"] = policy
    ctx["policy"] = get_success_data(api_client.mark_policy_in_force(
        policy["id"], {"in_force_date": "2026-01-25"}, CASE_MGR))
    ctx["agreement"] = get_agreement(ctx["agreement"]["id"])
    return ctx


def add_draft_schedule(ctx, payments, schedule_overrides=None):
    """Create a DRAFT schedule on ctx's agreement and add payment rows.

    payments: list of dicts with keys due_date/base_amount_cents (escalation_rate_bps
    optional). Sets ctx["schedule"] and ctx["payments"] (created rows, in order)."""
    schedule = get_success_data(api_client.create_payment_schedule(
        create_payment_schedule_payload(ctx["agreement"]["id"], **(schedule_overrides or {})), CASE_MGR))
    created = []
    for idx, spec in enumerate(payments, start=1):
        row = get_success_data(api_client.create_scheduled_payment(
            create_scheduled_payment_payload(
                schedule["id"], ctx["payee"]["id"], idx,
                spec["due_date"], spec["base_amount_cents"],
                **{k: v for k, v in spec.items() if k not in ("due_date", "base_amount_cents")}),
            CASE_MGR))
        created.append(row)
    ctx["schedule"] = schedule
    ctx["payments"] = created
    return ctx


def activate_schedule(ctx, schedule_id=None):
    """Activate a DRAFT schedule, presenting the agreement's freshly read version (PRD §2.7)."""
    schedule_id = schedule_id or ctx["schedule"]["id"]
    agreement = get_agreement(ctx["agreement"]["id"])
    schedule = get_success_data(api_client.activate_payment_schedule(
        schedule_id, {"expected_settlement_agreement_version": agreement["version"]}, CASE_MGR))
    ctx["schedule"] = schedule
    ctx["agreement"] = get_agreement(ctx["agreement"]["id"])
    return schedule


def setup_active_case(payments, clock_to=None, profile_overrides=None, payee_overrides=None,
                      agreement_overrides=None, policy_overrides=None, schedule_overrides=None):
    """Full stack: funded agreement + ACTIVE schedule holding `payments`.
    When clock_to is given, the logical clock is advanced (maturing due payments)."""
    ctx = setup_funded_agreement(profile_overrides, payee_overrides,
                                 agreement_overrides, policy_overrides)
    add_draft_schedule(ctx, payments, schedule_overrides)
    activate_schedule(ctx)
    if clock_to is not None:
        set_clock(clock_to)
        ctx["agreement"] = get_agreement(ctx["agreement"]["id"])
        ctx["payments"] = [get_payment(p["id"]) for p in ctx["payments"]]
    return ctx


def setup_executed_with_draft_schedule(payments, profile_overrides=None, payee_overrides=None,
                                       agreement_overrides=None, schedule_overrides=None):
    """Escalation-computation scope: EXECUTED agreement + DRAFT schedule with rows."""
    ctx = setup_executed_agreement(profile_overrides, payee_overrides, agreement_overrides)
    add_draft_schedule(ctx, payments, schedule_overrides)
    return ctx


# --- Tier 3: payment lifecycle shortcuts ---------------------------------------

def issue_payment(payment_id, method="CHECK", user_id="ops-1"):
    return get_success_data(api_client.issue_payment(
        payment_id, {"method": method}, make_operations_specialist_headers(user_id)))


def report_returned(payment_id, return_reason="BAD_ADDRESS", user_id="ops-1"):
    return get_success_data(api_client.report_payment_returned(
        payment_id, {"return_reason": return_reason}, make_operations_specialist_headers(user_id)))


def issue_and_return(payment_id, method="CHECK", return_reason="BAD_ADDRESS", user_id="ops-1"):
    """Issue then report returned; returns (payment, opened ReturnedPaymentCase)."""
    issue_payment(payment_id, method=method, user_id=user_id)
    payment = report_returned(payment_id, return_reason=return_reason, user_id=user_id)
    case = get_returned_case_for_payment(payment_id)
    return payment, case


# --- Tier 3: guardianship -------------------------------------------------------

def create_and_activate_guardianship(payee_id, guardian_full_name="Grace Guardian",
                                     effective_from_date="2026-01-01", court_state_code="CA"):
    """Open + activate a guardianship case. Returns the ACTIVE case."""
    case = get_success_data(api_client.create_guardianship_case(
        create_guardianship_case_payload(
            payee_id, guardian_full_name=guardian_full_name,
            effective_from_date=effective_from_date, court_state_code=court_state_code),
        CASE_MGR))
    return get_success_data(api_client.activate_guardianship_case(case["id"], COMPLIANCE))


# --- Tier 3/4: transfer petitions ----------------------------------------------

def create_petition(ctx, purchase_price_cents, transfer_start_date, transfer_end_date,
                    as_payee_self=False, factoring_company_name="FactorCo"):
    """Draft a petition (CaseManager on behalf, or the payee personally)."""
    payload = create_transfer_petition_payload(
        ctx["agreement"]["id"], ctx["payee"]["id"],
        purchase_price_cents=purchase_price_cents,
        transfer_start_date=transfer_start_date,
        transfer_end_date=transfer_end_date,
        factoring_company_name=factoring_company_name)
    headers = make_payee_headers(ctx["payee"]["id"]) if as_payee_self else CASE_MGR
    return get_success_data(api_client.create_transfer_petition(payload, headers))


def file_petition(petition_id, filer_user_id="cm-1"):
    return get_success_data(api_client.file_petition(
        petition_id, make_case_manager_headers(filer_user_id)))


def progress_petition_to_hearing(petition, ipa_completed_at=None, hearing_date="2029-02-01",
                                 cool_clock_to=None):
    """From FILED: serve disclosure, (optionally advance clock past cooling-off),
    schedule the hearing. Returns the HEARING_SCHEDULED petition."""
    get_success_data(api_client.serve_disclosure(petition["id"], CASE_MGR))
    if cool_clock_to is not None:
        set_clock(cool_clock_to)
    payload = {"hearing_date": hearing_date}
    if ipa_completed_at is not None:
        payload["ipa_completed_at"] = ipa_completed_at
    return get_success_data(api_client.schedule_hearing(petition["id"], payload, CASE_MGR))


def record_court_order(petition_id, outcome, court_order_date, recorder_user_id="jr-1", **extra):
    payload = {"outcome": outcome, "court_order_date": court_order_date}
    payload.update(extra)
    return get_success_data(api_client.record_court_order(
        petition_id, payload, make_judicial_recorder_headers(recorder_user_id)))


def setup_filed_petition(ctx, purchase_price_cents, transfer_start_date, transfer_end_date,
                         filer_user_id="cm-1"):
    """Draft + file a petition. Returns the FILED petition."""
    petition = create_petition(ctx, purchase_price_cents, transfer_start_date, transfer_end_date)
    return file_petition(petition["id"], filer_user_id=filer_user_id)


def setup_court_approved_petition(ctx, purchase_price_cents, transfer_start_date, transfer_end_date,
                                  hearing_date="2029-02-01", ipa_completed_at=None,
                                  cool_clock_to=None, order_date="2029-02-01",
                                  filer_user_id="cm-1", recorder_user_id="jr-1"):
    """Full adjudication path: FILED -> DISCLOSURE_SERVED -> HEARING_SCHEDULED -> COURT_APPROVED."""
    petition = setup_filed_petition(ctx, purchase_price_cents, transfer_start_date, transfer_end_date,
                                    filer_user_id=filer_user_id)
    petition = progress_petition_to_hearing(petition, ipa_completed_at=ipa_completed_at,
                                            hearing_date=hearing_date, cool_clock_to=cool_clock_to)
    return record_court_order(petition["id"], "APPROVED", order_date,
                              recorder_user_id=recorder_user_id)


# --- Tier 3: death claims --------------------------------------------------------

def create_claim(ctx, date_of_death="2028-12-20", claimant_type="ESTATE", claimant_name="Estate of Payee"):
    return get_success_data(api_client.create_death_claim(
        create_death_claim_payload(ctx["payee"]["id"], ctx["agreement"]["id"],
                                   date_of_death=date_of_death, claimant_type=claimant_type,
                                   claimant_name=claimant_name), CASE_MGR))


def settle_claim(claim_id):
    return get_success_data(api_client.settle_death_claim(claim_id, COMPLIANCE))


# --- Tier 3: commutations ---------------------------------------------------------

def create_commutation(ctx, reason, death_claim_id=None):
    """Create a commutation request with the policy's freshly read version (PRD §2.7)."""
    policy = get_policy(ctx["policy"]["id"])
    payload = create_commutation_request_payload(
        ctx["policy"]["id"], ctx["agreement"]["id"], reason, policy["version"],
        **({"death_claim_id": death_claim_id} if death_claim_id else {}))
    return get_success_data(api_client.create_commutation_request(payload, CASE_MGR))


# --- Tier 5: escheatment ------------------------------------------------------------

def open_batch(state_code, batch_period="2027-09", opener_user_id="co-1"):
    return get_success_data(api_client.create_escheatment_batch(
        create_escheatment_batch_payload(state_code, batch_period),
        make_compliance_officer_headers(opener_user_id)))


def finalize_batch(batch_id, finalizer_user_id="co-2"):
    return get_success_data(api_client.finalize_escheatment_batch(
        batch_id, make_compliance_officer_headers(finalizer_user_id)))


def reclaim_escheat(payment_id, user_id="ops-1"):
    return get_success_data(api_client.reclaim_payment_escheat(
        payment_id, make_operations_specialist_headers(user_id)))
