"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only endpoints the PRD declares.  Setup calls
go through ``get_success_data`` so a broken precondition surfaces as a clear
setup failure rather than a confusing assertion later on.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_audit_sample_payload,
    create_carrier_payload,
    create_coupon_payload,
    create_exchange_rate_payload,
    create_factor_payload,
    create_invoice_payload,
    create_memo_payload,
    create_period_payload,
    create_ticket_payload,
    prorate_payload,
)
from .test_users import (
    OPERATOR,
    make_accountant_headers,
    make_auditor_headers,
    make_billing_agent_headers,
)

BIG_LIMIT = TEST_DEFAULTS["BIG_CREDIT_LIMIT"]


# --------------------------------------------------------------------------- #
# Tier 0: single-call wrappers
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601):
    """Move the logical UTC clock. Returns the resulting current_utc payload."""
    return get_success_data(api_client.set_clock(to_iso8601, OPERATOR))


def new_carrier(code="AA", **overrides):
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(code, **overrides), OPERATOR)
    )


def new_period(**overrides):
    return get_success_data(
        api_client.create_period(create_period_payload(**overrides), OPERATOR)
    )


def new_exchange_rate(**overrides):
    return get_success_data(
        api_client.create_exchange_rate(create_exchange_rate_payload(**overrides), OPERATOR)
    )


def new_ticket(validating_carrier_id, ticket_number="0100000000001", **overrides):
    payload = create_ticket_payload(validating_carrier_id, ticket_number, **overrides)
    return get_success_data(
        api_client.create_ticket(payload, make_accountant_headers(validating_carrier_id))
    )


def add_coupon(ticket_id, validating_carrier_id, operating_carrier_id, coupon_number=1, **overrides):
    payload = create_coupon_payload(operating_carrier_id, coupon_number, **overrides)
    return get_success_data(
        api_client.create_coupon(
            ticket_id, payload, make_accountant_headers(validating_carrier_id)
        )
    )


def fly(coupon_id, validating_carrier_id):
    return get_success_data(
        api_client.fly_coupon(coupon_id, make_accountant_headers(validating_carrier_id))
    )


def void_coupon(coupon_id, validating_carrier_id):
    return get_success_data(
        api_client.void_coupon(coupon_id, make_accountant_headers(validating_carrier_id))
    )


def read_ticket(ticket_id):
    return get_success_data(api_client.get_ticket(ticket_id, OPERATOR))


def read_coupon(coupon_id):
    return get_success_data(api_client.get_coupon(coupon_id, OPERATOR))


def read_carrier(carrier_id):
    return get_success_data(api_client.get_carrier(carrier_id, OPERATOR))


def read_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, OPERATOR))


def read_memo(memo_id):
    return get_success_data(api_client.get_memo(memo_id, OPERATOR))


def read_agreement(agreement_id):
    return get_success_data(api_client.get_agreement(agreement_id, OPERATOR))


def read_period(period_id):
    return get_success_data(api_client.get_period(period_id, OPERATOR))


def read_sample(sample_id):
    return get_success_data(api_client.get_audit_sample(sample_id, OPERATOR))


def ticket_version(ticket_id):
    return read_ticket(ticket_id)["version"]


def invoice_version(invoice_id):
    return read_invoice(invoice_id)["version"]


def run_proration(ticket_id, validating_carrier_id, run_type="FINAL"):
    """Read the ticket's current version, then execute a proration run."""
    payload = prorate_payload(run_type, ticket_version(ticket_id))
    return get_success_data(
        api_client.prorate_ticket(
            ticket_id, payload, make_accountant_headers(validating_carrier_id)
        )
    )


def void_allocation(ticket_id, validating_carrier_id):
    payload = {"expected_ticket_version": ticket_version(ticket_id)}
    return get_success_data(
        api_client.void_proration(
            ticket_id, payload, make_accountant_headers(validating_carrier_id)
        )
    )


def draft_invoice(period_id, billing_carrier_id, billed_carrier_id, coupon_ids, **overrides):
    """Drafting is the RevenueAccountant's act, on the billing carrier's account."""
    payload = create_invoice_payload(
        period_id, billing_carrier_id, billed_carrier_id, coupon_ids, **overrides
    )
    return get_success_data(
        api_client.create_invoice(payload, make_accountant_headers(billing_carrier_id))
    )


def submit_invoice(invoice_id, billing_carrier_id):
    return get_success_data(
        api_client.submit_invoice(invoice_id, make_billing_agent_headers(billing_carrier_id))
    )


def recall_invoice(invoice_id, billing_carrier_id):
    return get_success_data(
        api_client.recall_invoice(invoice_id, make_billing_agent_headers(billing_carrier_id))
    )


def close_period(period_id):
    return get_success_data(api_client.close_period(period_id, OPERATOR))


def settle_period(period_id):
    return get_success_data(api_client.settle_period(period_id, OPERATOR))


def raise_memo(invoice_id, coupon_id, billed_carrier_id, **overrides):
    payload = create_memo_payload(invoice_id, coupon_id, invoice_version(invoice_id), **overrides)
    return get_success_data(
        api_client.create_memo(payload, make_billing_agent_headers(billed_carrier_id))
    )


def counter_memo(memo_id, billing_carrier_id, counter_amount_minor, counter_reason="counter"):
    payload = {
        "counter_amount_minor": counter_amount_minor,
        "counter_reason": counter_reason,
    }
    return get_success_data(
        api_client.counter_memo(memo_id, payload, make_billing_agent_headers(billing_carrier_id))
    )


def re_reject_memo(memo_id, invoice_id, billed_carrier_id, amount_minor, reason_code):
    payload = {
        "amount_minor": amount_minor,
        "reason_code": reason_code,
        "expected_invoice_version": invoice_version(invoice_id),
    }
    return get_success_data(
        api_client.re_reject_memo(memo_id, payload, make_billing_agent_headers(billed_carrier_id))
    )


def accept_memo(memo_id, invoice_id, billing_carrier_id):
    payload = {"expected_invoice_version": invoice_version(invoice_id)}
    return get_success_data(
        api_client.accept_memo(memo_id, payload, make_billing_agent_headers(billing_carrier_id))
    )


def withdraw_memo(memo_id, invoice_id, billed_carrier_id):
    payload = {"expected_invoice_version": invoice_version(invoice_id)}
    return get_success_data(
        api_client.withdraw_memo(memo_id, payload, make_billing_agent_headers(billed_carrier_id))
    )


def escalate_memo(memo_id, acting_carrier_id):
    return get_success_data(
        api_client.escalate_memo(memo_id, make_billing_agent_headers(acting_carrier_id))
    )


def arbitrate_memo(memo_id, ruling):
    return get_success_data(api_client.arbitrate_memo(memo_id, ruling, OPERATOR))


def draw_sample(auditing_carrier_id, audited_carrier_id, period_id, coupon_ids, **overrides):
    payload = create_audit_sample_payload(
        auditing_carrier_id, audited_carrier_id, period_id, coupon_ids, **overrides
    )
    return get_success_data(
        api_client.create_audit_sample(payload, make_auditor_headers(auditing_carrier_id))
    )


def record_finding(sample_id, auditing_carrier_id, coupon_id, correct_amount_minor):
    payload = {"coupon_id": coupon_id, "correct_amount_minor": correct_amount_minor}
    return get_success_data(
        api_client.record_finding(sample_id, payload, make_auditor_headers(auditing_carrier_id))
    )


def close_sample(sample_id, auditing_carrier_id):
    return get_success_data(
        api_client.close_audit_sample(sample_id, make_auditor_headers(auditing_carrier_id))
    )


# --------------------------------------------------------------------------- #
# Tier 1: membership and agreement book
# --------------------------------------------------------------------------- #
def setup_two_carriers(billed_credit_limit=BIG_LIMIT, billing_credit_limit=BIG_LIMIT):
    """AA (validating / billed) and BB (operating / billing), both ACTIVE."""
    aa = new_carrier("AA", credit_limit_minor=billed_credit_limit)
    bb = new_carrier("BB", credit_limit_minor=billing_credit_limit)
    return aa, bb


def setup_three_carriers(**overrides):
    aa = new_carrier("AA", credit_limit_minor=overrides.get("aa_limit", BIG_LIMIT))
    bb = new_carrier("BB", credit_limit_minor=overrides.get("bb_limit", BIG_LIMIT))
    cc = new_carrier("CC", credit_limit_minor=overrides.get("cc_limit", BIG_LIMIT))
    return aa, bb, cc


def setup_agreement(
    issuing_carrier_id,
    partner_carrier_id,
    agreement_type="SPA_FLAT",
    factors=(),
    activate=True,
    suspend_after_activate=False,
    **overrides,
):
    """Draft an agreement, attach its factors while still DRAFT, then optionally
    bring it into force (and optionally take it back out again)."""
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(
                issuing_carrier_id,
                partner_carrier_id,
                agreement_type=agreement_type,
                **overrides,
            ),
            make_accountant_headers(issuing_carrier_id),
        )
    )
    created_factors = []
    for factor in factors:
        created_factors.append(
            get_success_data(
                api_client.create_factor(
                    agreement["id"],
                    dict(factor),
                    make_accountant_headers(issuing_carrier_id),
                )
            )
        )
    if activate:
        agreement = get_success_data(
            api_client.activate_agreement(agreement["id"], OPERATOR)
        )
    if suspend_after_activate:
        agreement = get_success_data(
            api_client.suspend_agreement(agreement["id"], OPERATOR)
        )
    return agreement, created_factors


# --------------------------------------------------------------------------- #
# Tier 2: tickets, coupons and allocations
# --------------------------------------------------------------------------- #
def setup_ticket_with_coupons(
    validating_carrier_id,
    coupon_specs,
    ticket_number="0100000000001",
    total_fare_minor=TEST_DEFAULTS["DEFAULT_FARE_MINOR"],
    sale_currency="USD",
    fly_all=False,
    **ticket_overrides,
):
    """Issue a ticket and append its coupons in unbroken ascending sequence.

    `coupon_specs` is a list of dicts, each carrying at least
    `operating_carrier_id` and optionally origin/destination/class_of_service/tpm_miles.
    Returns (ticket, [coupons]) with the ticket re-read after the appends.
    """
    ticket = new_ticket(
        validating_carrier_id,
        ticket_number,
        total_fare_minor=total_fare_minor,
        sale_currency=sale_currency,
        **ticket_overrides,
    )
    coupons = []
    for index, spec in enumerate(coupon_specs, start=1):
        spec = dict(spec)
        operating = spec.pop("operating_carrier_id")
        coupons.append(
            add_coupon(ticket["id"], validating_carrier_id, operating, index, **spec)
        )
    if fly_all:
        coupons = [fly(c["id"], validating_carrier_id) for c in coupons]
    return read_ticket(ticket["id"]), coupons


def setup_three_sector_ticket(
    aa, bb, cc, ticket_number="0100000000001", total_fare_minor=100000, fly_all=True
):
    """The canonical JFK-LHR / LHR-CDG / CDG-FCO interline itinerary:
    coupon 1 operated by AA (ECONOMY, 3451 tpm), coupon 2 by BB (ECONOMY, 216 tpm)
    and coupon 3 by CC (BUSINESS, 693 tpm)."""
    return setup_ticket_with_coupons(
        aa,
        [
            {
                "operating_carrier_id": aa,
                "origin": "JFK",
                "destination": "LHR",
                "class_of_service": "ECONOMY",
                "tpm_miles": 3451,
            },
            {
                "operating_carrier_id": bb,
                "origin": "LHR",
                "destination": "CDG",
                "class_of_service": "ECONOMY",
                "tpm_miles": 216,
            },
            {
                "operating_carrier_id": cc,
                "origin": "CDG",
                "destination": "FCO",
                "class_of_service": "BUSINESS",
                "tpm_miles": 693,
            },
        ],
        ticket_number=ticket_number,
        total_fare_minor=total_fare_minor,
        fly_all=fly_all,
    )


def setup_flown_final_prorated_ticket(
    validating_carrier_id,
    operating_carrier_id,
    ticket_number="0100000000001",
    total_fare_minor=TEST_DEFAULTS["DEFAULT_FARE_MINOR"],
    sale_currency="USD",
    tpm_miles=TEST_DEFAULTS["DEFAULT_TPM_MILES"],
    class_of_service="ECONOMY",
    coupon_count=1,
    origin="JFK",
    destination="LHR",
):
    """A ticket whose coupons have all flown and which has been FINAL-prorated."""
    specs = []
    for index in range(coupon_count):
        specs.append(
            {
                "operating_carrier_id": operating_carrier_id,
                "origin": origin if index % 2 == 0 else destination,
                "destination": destination if index % 2 == 0 else origin,
                "class_of_service": class_of_service,
                "tpm_miles": tpm_miles,
            }
        )
    ticket, coupons = setup_ticket_with_coupons(
        validating_carrier_id,
        specs,
        ticket_number=ticket_number,
        total_fare_minor=total_fare_minor,
        sale_currency=sale_currency,
        fly_all=True,
    )
    run = run_proration(ticket["id"], validating_carrier_id, "FINAL")
    coupons = [read_coupon(c["id"]) for c in coupons]
    return read_ticket(ticket["id"]), coupons, run


# --------------------------------------------------------------------------- #
# Tier 3: billing lifecycle shortcuts
# --------------------------------------------------------------------------- #
def setup_draft_invoice(
    billed_credit_limit=BIG_LIMIT,
    total_fare_minor=TEST_DEFAULTS["DEFAULT_FARE_MINOR"],
    tpm_miles=TEST_DEFAULTS["DEFAULT_TPM_MILES"],
    class_of_service="ECONOMY",
    ticket_number="0100000000001",
    clock=TEST_DEFAULTS["CLOCK_TRADING_DAY"],
    coupon_count=1,
    billing_currency="USD",
    sale_currency="USD",
    period_overrides=None,
):
    """Clock set, AA + BB registered, an OPEN period, a flown FINAL-prorated
    ticket and a DRAFT invoice from BB (operating) to AA (validating)."""
    set_clock(clock)
    aa, bb = setup_two_carriers(billed_credit_limit=billed_credit_limit)
    period = new_period(**(period_overrides or {}))
    ticket, coupons, run = setup_flown_final_prorated_ticket(
        aa["id"],
        bb["id"],
        ticket_number=ticket_number,
        total_fare_minor=total_fare_minor,
        tpm_miles=tpm_miles,
        class_of_service=class_of_service,
        coupon_count=coupon_count,
        sale_currency=sale_currency,
    )
    invoice = draft_invoice(
        period["id"],
        bb["id"],
        aa["id"],
        [c["id"] for c in coupons],
        billing_currency=billing_currency,
    )
    return {
        "aa": aa,
        "bb": bb,
        "period": period,
        "ticket": ticket,
        "coupons": coupons,
        "coupon": coupons[0],
        "run": run,
        "invoice": invoice,
    }


def setup_submitted_invoice(**kwargs):
    """As `setup_draft_invoice`, then submitted by BB's BillingAgent."""
    ctx = setup_draft_invoice(**kwargs)
    ctx["invoice"] = submit_invoice(ctx["invoice"]["id"], ctx["bb"]["id"])
    return ctx


def setup_cleared_invoice(close_clock=TEST_DEFAULTS["CLOCK_FIXING_DAY"], **kwargs):
    """As `setup_submitted_invoice`, then cleared by the settlement-period close."""
    ctx = setup_submitted_invoice(**kwargs)
    set_clock(close_clock)
    ctx["period"] = close_period(ctx["period"]["id"])
    ctx["invoice"] = read_invoice(ctx["invoice"]["id"])
    return ctx


def setup_cleared_invoice_with_raised_memo(
    amount_minor=10000, reason_code="PRORATE_FACTOR_DISPUTE", **kwargs
):
    """A cleared invoice against which AA's BillingAgent has raised a stage-1 memo."""
    ctx = setup_cleared_invoice(**kwargs)
    ctx["memo"] = raise_memo(
        ctx["invoice"]["id"],
        ctx["coupon"]["id"],
        ctx["aa"]["id"],
        amount_minor=amount_minor,
        reason_code=reason_code,
    )
    ctx["invoice"] = read_invoice(ctx["invoice"]["id"])
    return ctx


# --------------------------------------------------------------------------- #
# Tier 4: audit population and sampling
# --------------------------------------------------------------------------- #
def setup_audit_population(
    ticket_specs=((100000, 2),),
    clock=TEST_DEFAULTS["CLOCK_TRADING_DAY"],
    close_clock=TEST_DEFAULTS["CLOCK_FIXING_DAY"],
    close=True,
):
    """AA validates, CC operates.  Each entry of `ticket_specs` is
    (total_fare_minor, coupon_count); every coupon is a 1000-tpm ECONOMY sector.
    All coupons are flown, FINAL-prorated, attached to one invoice CC->AA which is
    submitted and (by default) cleared by the period close."""
    set_clock(clock)
    aa = new_carrier("AA")
    cc = new_carrier("CC")
    period = new_period()
    tickets, all_coupons = [], []
    for index, (fare, count) in enumerate(ticket_specs, start=1):
        ticket, coupons, _run = setup_flown_final_prorated_ticket(
            aa["id"],
            cc["id"],
            ticket_number="01500000000%02d" % index,
            total_fare_minor=fare,
            coupon_count=count,
        )
        tickets.append(ticket)
        all_coupons.extend(coupons)
    invoice = draft_invoice(
        period["id"], cc["id"], aa["id"], [c["id"] for c in all_coupons]
    )
    invoice = submit_invoice(invoice["id"], cc["id"])
    if close:
        set_clock(close_clock)
        period = close_period(period["id"])
        invoice = read_invoice(invoice["id"])
    return {
        "aa": aa,
        "cc": cc,
        "period": period,
        "tickets": tickets,
        "coupons": [read_coupon(c["id"]) for c in all_coupons],
        "invoice": invoice,
    }


def setup_audit_sample_in_review(
    sample_index=0, correct_amount_minor=51000, ticket_specs=((100000, 2),), **kwargs
):
    """An audit population, a sample drawn over one of its coupons, and one
    recorded finding, so the sample sits at IN_REVIEW ready to be closed."""
    ctx = setup_audit_population(ticket_specs=ticket_specs, **kwargs)
    sampled = ctx["coupons"][sample_index]
    ctx["sampled_coupon"] = sampled
    ctx["sample"] = draw_sample(
        ctx["aa"]["id"], ctx["cc"]["id"], ctx["period"]["id"], [sampled["id"]]
    )
    ctx["sample"] = record_finding(
        ctx["sample"]["id"], ctx["aa"]["id"], sampled["id"], correct_amount_minor
    )
    return ctx
