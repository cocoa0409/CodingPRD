"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints and uses the lenient success validator so that a broken precondition
surfaces as a setup failure rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, MIN_EO_COVERAGE_CENTS, TRUST_STATES
from .factories import (
    cancel_booking_payload,
    claim_denial_payload,
    claim_resolution_payload,
    commission_claim_payload,
    commission_receipt_payload,
    create_advisor_agreement_payload,
    create_advisor_payload,
    create_booking_payload,
    create_client_payload,
    create_consortium_payload,
    create_settlement_run_payload,
    create_split_schedule_payload,
    create_supplier_payload,
    credential_decision_payload,
    declare_departure_payload,
    eo_policy_credential_payload,
    pay_statement_payload,
    seller_of_travel_credential_payload,
    supplier_accreditation_credential_payload,
    training_cert_credential_payload,
    trust_ledger_entry_payload,
)
from .test_users import (
    COMPLIANCE_USER_ID,
    CONTROLLER_CALC_USER_ID,
    CONTROLLER_POST_USER_ID,
    OPS_USER_ID,
    make_advisor_headers,
    make_compliance_officer_headers,
    make_host_controller_headers,
    make_host_operations_headers,
    make_supplier_portal_headers,
)


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------


def ops():
    return make_host_operations_headers(OPS_USER_ID)


def controller(user_id=CONTROLLER_CALC_USER_ID):
    return make_host_controller_headers(user_id)


def controller_2():
    return make_host_controller_headers(CONTROLLER_POST_USER_ID)


def compliance():
    return make_compliance_officer_headers(COMPLIANCE_USER_ID)


def advisor_as(advisor):
    """Ownership-gated calls must carry the advisor row's own id."""
    return make_advisor_headers(advisor["id"] if isinstance(advisor, dict) else advisor)


def supplier_as(supplier):
    """Ownership-gated calls must carry the supplier row's own id."""
    return make_supplier_portal_headers(
        supplier["id"] if isinstance(supplier, dict) else supplier
    )


# ---------------------------------------------------------------------------
# Tier 1 — single-row primitives
# ---------------------------------------------------------------------------


def new_split_schedule(**overrides) -> dict:
    return get_success_data(
        api_client.create_split_schedule(create_split_schedule_payload(**overrides), ops())
    )


def new_consortium(**overrides) -> dict:
    return get_success_data(
        api_client.create_consortium(create_consortium_payload(**overrides), ops())
    )


def new_supplier(**overrides) -> dict:
    return get_success_data(
        api_client.create_supplier(create_supplier_payload(**overrides), ops())
    )


def new_advisor(**overrides) -> dict:
    return get_success_data(
        api_client.create_advisor(create_advisor_payload(**overrides), ops())
    )


def read_advisor(advisor_id) -> dict:
    return get_success_data(api_client.get_advisor(advisor_id, ops()))


def read_supplier(supplier_id) -> dict:
    return get_success_data(api_client.get_supplier(supplier_id, ops()))


def read_client(client_id) -> dict:
    return get_success_data(api_client.get_client(client_id, ops()))


def read_booking(booking_id) -> dict:
    return get_success_data(api_client.get_booking(booking_id, ops()))


def read_claim(claim_id) -> dict:
    return get_success_data(api_client.get_commission_claim(claim_id, ops()))


def read_run(run_id) -> dict:
    return get_success_data(api_client.get_settlement_run(run_id, ops()))


def read_statement(statement_id) -> dict:
    return get_success_data(api_client.get_advisor_statement(statement_id, ops()))


def read_credential(credential_id) -> dict:
    return get_success_data(api_client.get_compliance_credential(credential_id, ops()))


def read_agreement(agreement_id) -> dict:
    return get_success_data(api_client.get_advisor_agreement(agreement_id, ops()))


def set_clock(to_iso8601) -> dict:
    """Advance the logical clock. Returns current_utc, expired_credential_count
    and refreshed_claim_count."""
    return get_success_data(api_client.advance_clock_to(to_iso8601, ops()))


def sign_agreement(advisor_id, split_schedule_id, **overrides) -> dict:
    """Sign a new agreement, pinning the advisor's currently observed version."""
    current = read_advisor(advisor_id)
    payload = create_advisor_agreement_payload(
        split_schedule_id, current["version"], **overrides
    )
    return get_success_data(
        api_client.create_advisor_agreement(advisor_id, payload, ops())
    )


def file_credential(advisor_id, payload, headers=None) -> dict:
    return get_success_data(
        api_client.create_compliance_credential(advisor_id, payload, headers or ops())
    )


def decide_credential(credential_id, decision="VERIFY", **overrides) -> dict:
    return get_success_data(
        api_client.decide_compliance_credential(
            credential_id, credential_decision_payload(decision, **overrides), compliance()
        )
    )


def file_and_verify_credential(advisor_id, payload) -> dict:
    filed = file_credential(advisor_id, payload)
    return decide_credential(filed["id"], "VERIFY")


def activate_advisor(advisor_id) -> dict:
    return get_success_data(api_client.activate_advisor(advisor_id, ops()))


def suspend_advisor(advisor_id, reason="Documentation audit in progress") -> dict:
    return get_success_data(
        api_client.suspend_advisor(advisor_id, {"reason": reason}, compliance())
    )


def reinstate_advisor(advisor_id) -> dict:
    return get_success_data(api_client.reinstate_advisor(advisor_id, compliance()))


def new_client(owner_advisor_id, as_advisor=True, **overrides) -> dict:
    headers = make_advisor_headers(owner_advisor_id) if as_advisor else ops()
    return get_success_data(
        api_client.create_client(
            create_client_payload(owner_advisor_id, **overrides), headers
        )
    )


def append_trust_line(client_id, direction, amount_cents, headers, **extra) -> dict:
    """Append one ledger line, echoing the client's currently observed version."""
    current = read_client(client_id)
    payload = trust_ledger_entry_payload(
        direction, amount_cents, current["version"], **extra
    )
    return get_success_data(
        api_client.create_trust_ledger_entry(client_id, payload, headers)
    )


def advisor_deposit(client_id, advisor_id, amount_cents, memo="Trip funding") -> dict:
    """Role Advisor may append only DEPOSIT lines."""
    return append_trust_line(
        client_id, "DEPOSIT", amount_cents, make_advisor_headers(advisor_id), memo=memo
    )


def controller_disbursement(client_id, amount_cents, memo="Supplier payment", **extra) -> dict:
    return append_trust_line(
        client_id, "DISBURSEMENT", amount_cents, controller(), memo=memo, **extra
    )


def controller_refund(client_id, amount_cents, memo="Client refund", **extra) -> dict:
    return append_trust_line(
        client_id, "REFUND", amount_cents, controller(), memo=memo, **extra
    )


def list_client_ledger(client_id) -> list:
    body = api_client.list_client_trust_ledger_entries(client_id, ops()).json()
    return body["data"]


def list_booking_ledger(booking_id) -> list:
    body = api_client.list_booking_trust_ledger_entries(booking_id, ops()).json()
    return body["data"]


# ---------------------------------------------------------------------------
# Tier 1 — booking, claim and settlement primitives
# ---------------------------------------------------------------------------


def new_booking(advisor_id, supplier_id, client_id, **overrides) -> dict:
    payload = create_booking_payload(advisor_id, supplier_id, client_id, **overrides)
    return get_success_data(
        api_client.create_booking(payload, make_advisor_headers(advisor_id))
    )


def confirm_booking(booking_id, supplier_id) -> dict:
    return get_success_data(
        api_client.confirm_booking(booking_id, make_supplier_portal_headers(supplier_id))
    )


def mark_traveled(booking_id) -> dict:
    return get_success_data(api_client.mark_booking_traveled(booking_id, ops()))


def cancel_booking(booking_id, advisor_id, cancellation_reason="CLIENT_INITIATED") -> dict:
    return get_success_data(
        api_client.cancel_booking(
            booking_id,
            cancel_booking_payload(cancellation_reason),
            make_advisor_headers(advisor_id),
        )
    )


def record_receipt(booking_id, supplier_id, amount_cents, received_on) -> dict:
    return get_success_data(
        api_client.record_commission_receipt(
            booking_id,
            commission_receipt_payload(amount_cents, received_on),
            make_supplier_portal_headers(supplier_id),
        )
    )


def file_claim(booking_id, advisor_id, claimed_amount_cents) -> dict:
    return get_success_data(
        api_client.create_commission_claim(
            booking_id,
            commission_claim_payload(claimed_amount_cents),
            make_advisor_headers(advisor_id),
        )
    )


def deny_claim(claim_id, supplier_id, denial_reason="Commission already remitted in full") -> dict:
    return get_success_data(
        api_client.deny_commission_claim(
            claim_id,
            claim_denial_payload(denial_reason),
            make_supplier_portal_headers(supplier_id),
        )
    )


def resubmit_claim(claim_id, advisor_id, **payload) -> dict:
    return get_success_data(
        api_client.resubmit_commission_claim(
            claim_id, make_advisor_headers(advisor_id), payload or {}
        )
    )


def resolve_claim(claim_id, resolution="PAID", recovered_amount_cents=None) -> dict:
    return get_success_data(
        api_client.resolve_commission_claim(
            claim_id, claim_resolution_payload(resolution, recovered_amount_cents), ops()
        )
    )


def open_run(period_month="2026-08") -> dict:
    return get_success_data(
        api_client.create_settlement_run(create_settlement_run_payload(period_month), ops())
    )


def calculate_run(run_id, user_id=CONTROLLER_CALC_USER_ID) -> dict:
    return get_success_data(api_client.calculate_settlement_run(run_id, controller(user_id)))


def post_run(run_id, user_id=CONTROLLER_POST_USER_ID) -> dict:
    return get_success_data(api_client.post_settlement_run(run_id, controller(user_id)))


def run_full_settlement(period_month, calc_user=CONTROLLER_CALC_USER_ID,
                        post_user=CONTROLLER_POST_USER_ID) -> dict:
    """Open, calculate and post one monthly run. Returns the posted run."""
    run = open_run(period_month)
    calculate_run(run["id"], calc_user)
    return post_run(run["id"], post_user)


def statements_for_run(run_id) -> list:
    body = api_client.list_advisor_statements(ops(), {"settlement_run_id": run_id}).json()
    return body["data"]


def statements_for_advisor(advisor_id) -> list:
    body = api_client.list_advisor_statements(ops(), {"advisor_id": advisor_id}).json()
    return body["data"]


def pay_statement(statement_id, payment_reference="ACH-2026-0001") -> dict:
    return get_success_data(
        api_client.pay_advisor_statement(
            statement_id, pay_statement_payload(payment_reference), controller()
        )
    )


def declare_departure(advisor_id, transition_advisor_id, effective_date="2026-09-01",
                      as_advisor=True) -> dict:
    headers = make_advisor_headers(advisor_id) if as_advisor else ops()
    return get_success_data(
        api_client.declare_departure(
            advisor_id,
            declare_departure_payload(transition_advisor_id, effective_date),
            headers,
        )
    )


def finalize_departure(advisor_id) -> dict:
    return get_success_data(api_client.finalize_departure(advisor_id, compliance()))


# ---------------------------------------------------------------------------
# Tier 2 — credentialed and activated advisors
# ---------------------------------------------------------------------------


def file_core_credentials(
    advisor_id,
    state="NY",
    number_prefix="A",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    eo_coverage_amount_cents=MIN_EO_COVERAGE_CENTS,
    sot_expires_on=None,
    verify=True,
) -> dict:
    """File the state registration, the E&O policy and the training certificate.

    Returns a dict keyed seller_of_travel / eo_policy / training_cert.
    """
    filed = {}
    sot = seller_of_travel_credential_payload(
        jurisdiction_state_code=state,
        credential_number=f"{state}-SOT-{number_prefix}",
        effective_on=effective_on,
        expires_on=sot_expires_on or expires_on,
    )
    eo = eo_policy_credential_payload(
        coverage_amount_cents=eo_coverage_amount_cents,
        credential_number=f"EO-{number_prefix}",
        effective_on=effective_on,
        expires_on=expires_on,
    )
    trn = training_cert_credential_payload(
        credential_number=f"TRN-{number_prefix}",
        effective_on=effective_on,
        expires_on=expires_on,
    )
    for key, payload in (
        ("seller_of_travel", sot),
        ("eo_policy", eo),
        ("training_cert", trn),
    ):
        row = file_credential(advisor_id, payload)
        filed[key] = decide_credential(row["id"], "VERIFY") if verify else row
    return filed


def accredit_with_suppliers(
    advisor_id,
    suppliers,
    number_prefix="A",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    verify=True,
) -> list:
    """File one SUPPLIER_ACCREDITATION credential per supplier."""
    rows = []
    for index, supplier in enumerate(suppliers, start=1):
        supplier_id = supplier["id"] if isinstance(supplier, dict) else supplier
        payload = supplier_accreditation_credential_payload(
            supplier_id,
            credential_number=f"ACC-{number_prefix}-{index}",
            effective_on=effective_on,
            expires_on=expires_on,
        )
        row = file_credential(advisor_id, payload)
        rows.append(decide_credential(row["id"], "VERIFY") if verify else row)
    return rows


def setup_active_advisor(
    state="NY",
    legal_name="Dana Reyes",
    email="dana.reyes@example.com",
    consortium_id=None,
    schedule=None,
    schedule_overrides=None,
    agreement_overrides=None,
    suppliers=(),
    number_prefix="A",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    sot_expires_on=None,
    eo_coverage_amount_cents=MIN_EO_COVERAGE_CENTS,
    activate=True,
) -> dict:
    """Onboard an advisor, sign its agreement, verify all credentials and activate.

    Returns {"schedule", "advisor", "agreement", "credentials", "accreditations"}.
    """
    schedule = schedule or new_split_schedule(**(schedule_overrides or {}))
    advisor_kwargs = {
        "legal_name": legal_name,
        "email": email,
        "seller_of_travel_state": state,
    }
    if consortium_id is not None:
        advisor_kwargs["consortium_id"] = consortium_id
    advisor = new_advisor(**advisor_kwargs)
    agreement = sign_agreement(
        advisor["id"], schedule["id"], **(agreement_overrides or {})
    )
    credentials = file_core_credentials(
        advisor["id"],
        state=state,
        number_prefix=number_prefix,
        effective_on=effective_on,
        expires_on=expires_on,
        sot_expires_on=sot_expires_on,
        eo_coverage_amount_cents=eo_coverage_amount_cents,
    )
    accreditations = accredit_with_suppliers(
        advisor["id"],
        suppliers,
        number_prefix=number_prefix,
        effective_on=effective_on,
        expires_on=expires_on,
    )
    if activate:
        advisor = activate_advisor(advisor["id"])
    else:
        advisor = read_advisor(advisor["id"])
    return {
        "schedule": schedule,
        "advisor": advisor,
        "agreement": agreement,
        "credentials": credentials,
        "accreditations": accreditations,
    }


# ---------------------------------------------------------------------------
# Tier 3 — booking-ready scenarios
# ---------------------------------------------------------------------------


def setup_booking_scenario(
    state="NY",
    supplier_overrides=None,
    schedule_overrides=None,
    client_overrides=None,
    consortium_overrides=None,
    advisor_in_consortium=False,
    supplier_in_consortium=False,
    legal_name="Dana Reyes",
    email="dana.reyes@example.com",
    number_prefix="A",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    sot_expires_on=None,
) -> dict:
    """One schedule, one supplier, one ACTIVE accredited advisor and one client.

    Set advisor_in_consortium / supplier_in_consortium to give the pair genuine
    co-membership of a freshly registered consortium.
    """
    consortium = None
    if advisor_in_consortium or supplier_in_consortium:
        consortium = new_consortium(**(consortium_overrides or {}))
    supplier_kwargs = dict(supplier_overrides or {})
    if supplier_in_consortium:
        supplier_kwargs.setdefault("consortium_id", consortium["id"])
    supplier = new_supplier(**supplier_kwargs)
    ctx = setup_active_advisor(
        state=state,
        legal_name=legal_name,
        email=email,
        consortium_id=consortium["id"] if advisor_in_consortium else None,
        schedule_overrides=schedule_overrides,
        suppliers=[supplier],
        number_prefix=number_prefix,
        effective_on=effective_on,
        expires_on=expires_on,
        sot_expires_on=sot_expires_on,
    )
    client_kwargs = dict(client_overrides or {})
    client_kwargs.setdefault("home_state_code", state)
    client = new_client(ctx["advisor"]["id"], **client_kwargs)
    ctx.update({"supplier": supplier, "client": client, "consortium": consortium})
    return ctx


def default_payment_method_for(state) -> str:
    """PRD §3.5 pairs the payment method with the advisor's trust obligation."""
    return "CLIENT_TRUST" if state in TRUST_STATES else "MERCHANT_DIRECT"


def submit_booking_in_scenario(ctx, **overrides) -> dict:
    overrides.setdefault(
        "payment_method",
        default_payment_method_for(ctx["advisor"]["seller_of_travel_state"]),
    )
    return new_booking(
        ctx["advisor"]["id"], ctx["supplier"]["id"], ctx["client"]["id"], **overrides
    )


def setup_confirmed_booking(ctx=None, booking_overrides=None, **scenario_kwargs) -> tuple:
    """Submit one booking and have its supplier confirm it. Returns (ctx, booking)."""
    ctx = ctx or setup_booking_scenario(**scenario_kwargs)
    booking = submit_booking_in_scenario(ctx, **(booking_overrides or {}))
    booking = confirm_booking(booking["id"], ctx["supplier"]["id"])
    return ctx, booking


def setup_received_booking(
    ctx=None, booking_overrides=None, received_on="2026-08-01",
    amount_cents=None, **scenario_kwargs
) -> tuple:
    """Submit, confirm and record the supplier's remittance. Returns (ctx, booking)."""
    ctx, booking = setup_confirmed_booking(
        ctx=ctx, booking_overrides=booking_overrides, **scenario_kwargs
    )
    paid = booking["expected_commission_cents"] if amount_cents is None else amount_cents
    booking = record_receipt(booking["id"], ctx["supplier"]["id"], paid, received_on)
    return ctx, booking


def setup_settled_booking(
    ctx=None, booking_overrides=None, received_on="2026-08-01",
    period_month="2026-08", amount_cents=None, **scenario_kwargs
) -> tuple:
    """Take one booking all the way through a posted settlement run.

    Returns (ctx, booking, run, statement).
    """
    ctx, booking = setup_received_booking(
        ctx=ctx,
        booking_overrides=booking_overrides,
        received_on=received_on,
        amount_cents=amount_cents,
        **scenario_kwargs,
    )
    run = run_full_settlement(period_month)
    statements = statements_for_advisor(ctx["advisor"]["id"])
    booking = read_booking(booking["id"])
    return ctx, booking, run, (statements[0] if statements else None)


# ---------------------------------------------------------------------------
# Tier 4 — receivable, claim and trust targeting
# ---------------------------------------------------------------------------


def setup_short_paid_booking(
    ctx=None, gross_sale_cents=1_000_000, paid_cents=60_000,
    received_on="2026-08-01", **scenario_kwargs
) -> tuple:
    """A CONFIRMED booking whose supplier remitted less than it owed.

    Returns (ctx, booking) with the booking in RECEIVED carrying a shortfall.
    """
    booking_overrides = {"gross_sale_cents": gross_sale_cents}
    return setup_received_booking(
        ctx=ctx,
        booking_overrides=booking_overrides,
        received_on=received_on,
        amount_cents=paid_cents,
        **scenario_kwargs,
    )


def setup_claimable_unpaid_booking(
    ctx=None,
    gross_sale_cents=1_000_000,
    travel_start_date="2026-06-01",
    travel_end_date="2026-06-10",
    **scenario_kwargs,
) -> tuple:
    """A TRAVELED booking with nothing remitted, past its supplier due date.

    Returns (ctx, booking) with commission_status EXPECTED.
    """
    ctx, booking = setup_confirmed_booking(
        ctx=ctx,
        booking_overrides={
            "gross_sale_cents": gross_sale_cents,
            "travel_start_date": travel_start_date,
            "travel_end_date": travel_end_date,
        },
        **scenario_kwargs,
    )
    booking = mark_traveled(booking["id"])
    return ctx, booking


def setup_client_with_trust_deposit(
    deposit_cents=300_000, state="CA", **scenario_kwargs
) -> dict:
    """A trust-state advisor with one client already holding a funded balance."""
    scenario_kwargs.setdefault("state", state)
    ctx = setup_booking_scenario(**scenario_kwargs)
    advisor_deposit(ctx["client"]["id"], ctx["advisor"]["id"], deposit_cents)
    ctx["client"] = read_client(ctx["client"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — settlement lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_empty_calculated_run(period_month="2026-08", calc_user=CONTROLLER_CALC_USER_ID) -> dict:
    """A run with no advisors and no bookings, calculated and awaiting a poster."""
    run = open_run(period_month)
    return calculate_run(run["id"], calc_user)


def setup_posted_statement(
    ctx=None, booking_overrides=None, received_on="2026-08-01",
    period_month="2026-08", amount_cents=None, **scenario_kwargs
) -> tuple:
    """One advisor with a single POSTED statement awaiting payment.

    Returns (ctx, booking, run, statement).
    """
    return setup_settled_booking(
        ctx=ctx,
        booking_overrides=booking_overrides,
        received_on=received_on,
        period_month=period_month,
        amount_cents=amount_cents,
        **scenario_kwargs,
    )


def setup_calculated_run_awaiting_post(
    ctx=None, booking_overrides=None, received_on="2026-08-01",
    period_month="2026-08", amount_cents=None, **scenario_kwargs
) -> tuple:
    """One advisor with received commission and a CALCULATED run.

    Returns (ctx, booking, run).
    """
    ctx, booking = setup_received_booking(
        ctx=ctx,
        booking_overrides=booking_overrides,
        received_on=received_on,
        amount_cents=amount_cents,
        **scenario_kwargs,
    )
    run = open_run(period_month)
    run = calculate_run(run["id"], CONTROLLER_CALC_USER_ID)
    return ctx, booking, run


def setup_departing_advisor(
    successor_email="sam.ortega@example.com",
    successor_name="Sam Ortega",
    state="NY",
    effective_date="2026-09-01",
    schedule=None,
    supplier=None,
    **scenario_kwargs,
) -> dict:
    """Two ACTIVE advisors where the first has armed its departure toward the second.

    Returns the departing advisor's scenario plus "successor" and
    "successor_agreement".
    """
    scenario_kwargs.setdefault("state", state)
    ctx = setup_booking_scenario(**scenario_kwargs)
    successor_ctx = setup_active_advisor(
        state=state,
        legal_name=successor_name,
        email=successor_email,
        schedule=schedule or ctx["schedule"],
        suppliers=[supplier or ctx["supplier"]],
        number_prefix="S",
        agreement_overrides={"effective_date": "2026-02-01"},
    )
    declare_departure(
        ctx["advisor"]["id"], successor_ctx["advisor"]["id"], effective_date
    )
    ctx["advisor"] = read_advisor(ctx["advisor"]["id"])
    ctx["successor"] = successor_ctx["advisor"]
    ctx["successor_agreement"] = successor_ctx["agreement"]
    ctx["successor_credentials"] = successor_ctx["credentials"]
    return ctx


def advisor_bookings(advisor_id, **params) -> list:
    params["advisor_id"] = advisor_id
    body = api_client.list_bookings(ops(), params).json()
    return body["data"]


def client_bookings(client_id, **params) -> list:
    params["client_id"] = client_id
    body = api_client.list_bookings(ops(), params).json()
    return body["data"]


def advisor_credentials(advisor_id, **params) -> list:
    params["advisor_id"] = advisor_id
    body = api_client.list_compliance_credentials(ops(), params).json()
    return body["data"]


def advisor_agreements(advisor_id, **params) -> list:
    params["advisor_id"] = advisor_id
    body = api_client.list_advisor_agreements(ops(), params).json()
    return body["data"]


def booking_claims(booking_id, **params) -> list:
    params["booking_id"] = booking_id
    body = api_client.list_commission_claims(ops(), params).json()
    return body["data"]
