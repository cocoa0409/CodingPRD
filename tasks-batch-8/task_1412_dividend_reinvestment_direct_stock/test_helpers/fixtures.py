"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build complete precondition chains —
plan -> publish -> participant -> enrollment -> activation -> deposits ->
dividends / windows / orders — out of PRD-declared endpoints only.

Identity threading: Participant is entity-backed by the Participant entity,
so every ownership-gated call uses make_participant_headers(participant["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_AVG5_PRICE,
    DEFAULT_CLOSING_PRICE,
    DEFAULT_DIVIDEND_AMOUNT_PER_SHARE,
    DEFAULT_EXECUTION_CLOCK,
    DEFAULT_PAYABLE_DATE,
    DEFAULT_RECORD_DATE,
    DEFAULT_WINDOW_CLOSE_CLOCK,
    DEFAULT_WINDOW_CLOSES,
    DEFAULT_WINDOW_OPEN_CLOCK,
    DEFAULT_WINDOW_OPENS,
    DEFAULT_WINDOW_PRICE_CENTS,
)
from .factories import (
    create_deposit_payload,
    create_dividend_payload,
    create_enrollment_payload,
    create_notice_payload,
    create_order_payload,
    create_participant_payload,
    create_plan_payload,
    create_price_payload,
    create_transfer_payload,
    create_window_payload,
)
from .test_users import TEST_USERS, make_participant_headers

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: plan state progression
# ---------------------------------------------------------------------------

def create_plan(**overrides):
    """Create a plan (starts DRAFT). Returns the plan."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides),
                                                   ADMIN))


def create_active_plan(**overrides):
    """Create a plan and publish it to ACTIVE. Returns the published plan."""
    plan = create_plan(**overrides)
    return get_success_data(api_client.publish_plan(plan["id"], ADMIN))


def get_plan(plan_id):
    return get_success_data(api_client.get_plan(plan_id, ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: participants and enrollments
# ---------------------------------------------------------------------------

def register_participant(full_name="Pat Example", email="pat@example.com",
                         fee_waiver_eligible=None):
    """Register a participant. Returns the participant."""
    overrides = {"full_name": full_name, "email": email}
    if fee_waiver_eligible is not None:
        overrides["fee_waiver_eligible"] = fee_waiver_eligible
    return get_success_data(
        api_client.create_participant(create_participant_payload(**overrides), ADMIN))


def enroll_participant(plan_id, participant_id, election="FULL_REINVEST",
                       reinvest_pct=None):
    """Self-enroll a participant into a plan. Returns the PENDING enrollment."""
    payload = create_enrollment_payload(participant_id, election, reinvest_pct)
    return get_success_data(
        api_client.create_enrollment(plan_id, payload,
                                     make_participant_headers(participant_id)))


def activate_enrollment(enrollment_id):
    return get_success_data(api_client.activate_enrollment(enrollment_id, ADMIN))


def create_active_enrollment(plan_id, participant_id, election="FULL_REINVEST",
                             reinvest_pct=None):
    """Enroll + activate. Returns the ACTIVE enrollment."""
    enrollment = enroll_participant(plan_id, participant_id, election, reinvest_pct)
    return activate_enrollment(enrollment["id"])


def setup_active_enrollment(plan_overrides=None, election="FULL_REINVEST",
                            reinvest_pct=None, participant_email="pat@example.com",
                            participant_name="Pat Example",
                            fee_waiver_eligible=None):
    """ACTIVE plan + registered participant + ACTIVE enrollment.

    Returns (plan, participant, enrollment).
    """
    plan = create_active_plan(**(plan_overrides or {}))
    participant = register_participant(participant_name, participant_email,
                                       fee_waiver_eligible)
    enrollment = create_active_enrollment(plan["id"], participant["id"],
                                          election, reinvest_pct)
    return plan, participant, enrollment


def get_enrollment(enrollment_id):
    return get_success_data(api_client.get_enrollment(enrollment_id, ADMIN))


def deposit_shares(enrollment_id, quantity, cost_per_share_cents):
    """Record an initial share deposit. Returns the created ledger entry."""
    return get_success_data(
        api_client.create_deposit(enrollment_id,
                                  create_deposit_payload(quantity,
                                                         cost_per_share_cents),
                                  ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: dividend lifecycle
# ---------------------------------------------------------------------------

def declare_dividend(plan_id, amount_per_share_cents=DEFAULT_DIVIDEND_AMOUNT_PER_SHARE,
                     record_date=DEFAULT_RECORD_DATE, payable_date=DEFAULT_PAYABLE_DATE):
    """Declare a dividend (starts DECLARED). Returns the dividend event."""
    return get_success_data(
        api_client.create_dividend_event(
            plan_id,
            create_dividend_payload(amount_per_share_cents, record_date, payable_date),
            ADMIN))


def price_dividend(dividend_id, closing_price_cents=DEFAULT_CLOSING_PRICE,
                   avg5_price_cents=DEFAULT_AVG5_PRICE):
    """Price a DECLARED dividend. Returns the PRICED dividend event."""
    return get_success_data(
        api_client.price_dividend_event(
            dividend_id, create_price_payload(closing_price_cents, avg5_price_cents),
            ADMIN))


def get_dividend_event(plan_id, dividend_id):
    """Read one dividend via the plan's dividend list (no single-GET exists)."""
    data, _meta = validate_paginated(api_client.list_dividend_events(plan_id, ADMIN))
    matches = [d for d in data if d["id"] == dividend_id]
    assert len(matches) == 1, f"Expected dividend {dividend_id} in plan list"
    return matches[0]


def execute_dividend_at(dividend_id, at=DEFAULT_EXECUTION_CLOCK):
    """Advance the logical clock to `at` (>= payable_date) and execute.

    Returns the REINVESTED dividend event.
    """
    set_clock(at)
    return get_success_data(api_client.execute_dividend_event(dividend_id, ADMIN))


def setup_priced_dividend_scenario(plan_overrides=None, election="FULL_REINVEST",
                                   reinvest_pct=None, deposit_quantity=100.0,
                                   deposit_cost_per_share=1500,
                                   amount_per_share_cents=DEFAULT_DIVIDEND_AMOUNT_PER_SHARE,
                                   closing_price_cents=DEFAULT_CLOSING_PRICE,
                                   avg5_price_cents=DEFAULT_AVG5_PRICE,
                                   participant_email="pat@example.com"):
    """ACTIVE plan + ACTIVE enrollment with one deposit + PRICED dividend.

    The logical clock is left at its startup default so the deposit lands
    before the record date. Returns (plan, participant, enrollment, dividend).
    """
    plan, participant, enrollment = setup_active_enrollment(
        plan_overrides=plan_overrides, election=election, reinvest_pct=reinvest_pct,
        participant_email=participant_email)
    deposit_shares(enrollment["id"], deposit_quantity, deposit_cost_per_share)
    dividend = declare_dividend(plan["id"], amount_per_share_cents)
    dividend = price_dividend(dividend["id"], closing_price_cents, avg5_price_cents)
    return plan, participant, enrollment, dividend


# ---------------------------------------------------------------------------
# Tier 4: purchase windows and orders
# ---------------------------------------------------------------------------

def create_window(plan_id, opens_at=DEFAULT_WINDOW_OPENS,
                  closes_at=DEFAULT_WINDOW_CLOSES,
                  price_cents=DEFAULT_WINDOW_PRICE_CENTS):
    """Create a purchase window (starts SCHEDULED). Returns the window."""
    return get_success_data(
        api_client.create_purchase_window(
            plan_id, create_window_payload(opens_at, closes_at, price_cents), ADMIN))


def get_window(window_id):
    return get_success_data(api_client.get_purchase_window(window_id, ADMIN))


def open_window_at(window_id, at=DEFAULT_WINDOW_OPEN_CLOCK):
    """Advance the logical clock into the window and open it. Returns OPEN window."""
    set_clock(at)
    return get_success_data(api_client.open_purchase_window(window_id, ADMIN))


def close_window_at(window_id, at=DEFAULT_WINDOW_CLOSE_CLOCK):
    """Advance the logical clock to/past closes_at and close. Returns CLOSED window."""
    set_clock(at)
    return get_success_data(api_client.close_purchase_window(window_id, ADMIN))


def settle_window(window_id):
    return get_success_data(api_client.settle_purchase_window(window_id, ADMIN))


def submit_order(window_id, enrollment_id, participant_id, amount_cents):
    """Submit an order as the owning participant. Returns the raw response so
    callers can assert on failures; use submit_order_ok for the success path."""
    return api_client.create_purchase_order(
        window_id, create_order_payload(enrollment_id, amount_cents),
        make_participant_headers(participant_id))


def submit_order_ok(window_id, enrollment_id, participant_id, amount_cents):
    """Submit an order expected to succeed. Returns the SUBMITTED order."""
    return get_success_data(
        submit_order(window_id, enrollment_id, participant_id, amount_cents))


def get_order(order_id):
    return get_success_data(api_client.get_purchase_order(order_id, ADMIN))


def setup_open_window_scenario(plan_overrides=None, window_overrides=None,
                               open_clock=DEFAULT_WINDOW_OPEN_CLOCK,
                               participant_email="pat@example.com",
                               fee_waiver_eligible=None):
    """ACTIVE plan + ACTIVE enrollment + OPEN window.

    Returns (plan, participant, enrollment, window).
    """
    plan, participant, enrollment = setup_active_enrollment(
        plan_overrides=plan_overrides,
        participant_email=participant_email,
        fee_waiver_eligible=fee_waiver_eligible)
    window = create_window(plan["id"], **(window_overrides or {}))
    window = open_window_at(window["id"], open_clock)
    return plan, participant, enrollment, window


# ---------------------------------------------------------------------------
# Tier 5: transfers, termination, fees, notices
# ---------------------------------------------------------------------------

def create_transfer(source_enrollment_id, source_participant_id, **kwargs):
    """Create a transfer/gift instruction as the source owner. Raw response."""
    return api_client.create_transfer(
        source_enrollment_id, create_transfer_payload(**kwargs),
        make_participant_headers(source_participant_id))


def create_transfer_ok(source_enrollment_id, source_participant_id, **kwargs):
    return get_success_data(
        create_transfer(source_enrollment_id, source_participant_id, **kwargs))


def execute_transfer(instruction_id, fmv_per_share_cents):
    return get_success_data(
        api_client.execute_transfer_instruction(instruction_id, fmv_per_share_cents,
                                                ADMIN))


def terminate_enrollment(enrollment_id, participant_id, sale_price_cents):
    """Terminate an enrollment as its owning participant. Raw response."""
    return api_client.terminate_enrollment(
        enrollment_id, {"sale_price_cents": sale_price_cents},
        make_participant_headers(participant_id))


def create_notice(plan_id, notice_type="MODIFICATION",
                  effective_at="2026-08-20T00:00:00Z", message="Plan communication"):
    return get_success_data(
        api_client.create_notice(
            plan_id, create_notice_payload(notice_type, effective_at, message), ADMIN))


# ---------------------------------------------------------------------------
# Read-back helpers (admin reads of the books)
# ---------------------------------------------------------------------------

def list_ledger_entries(enrollment_id, entry_type=None):
    params = {"entry_type": entry_type} if entry_type else None
    data, _meta = validate_paginated(
        api_client.list_ledger_entries(enrollment_id, ADMIN, params=params))
    return data


def list_tax_lots(enrollment_id):
    data, _meta = validate_paginated(api_client.list_tax_lots(enrollment_id, ADMIN))
    return data


def list_fees(enrollment_id, fee_type=None):
    params = {"fee_type": fee_type} if fee_type else None
    data, _meta = validate_paginated(
        api_client.list_fees(enrollment_id, ADMIN, params=params))
    return data


def list_notices(plan_id, params=None):
    data, _meta = validate_paginated(api_client.list_notices(plan_id, ADMIN,
                                                             params=params))
    return data


def get_tax_report(enrollment_id, year):
    return get_success_data(api_client.get_tax_report(enrollment_id, year, ADMIN))
