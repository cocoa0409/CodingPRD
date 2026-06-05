"""State transitions, precondition enforcement, terminal lockdown, side effects.

Queue B (Corner) translations: state_machines, validations, endpoints.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_tenant_headers,
    setup_activated, setup_auction_opened, setup_auction_scheduled,
    setup_transfer_requested, set_clock, create_facility, create_unit, create_tenant,
    create_lease, pay,
    api_client,
)

FM = TEST_USERS["facility_manager_headers"]
LIEN = TEST_USERS["lien_administrator_headers"]


def test_activate_already_active_lease_invalid_state(api):
    """PRD §3.3: "Activation is only defined from the `PENDING` state; attempting it
    from any other state gives `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_lease_from_active_returns_invalid_state
    """
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    resp = api.activate_lease(ctx["lease"]["id"], FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert refreshed["status"] == "ACTIVE"


def test_file_lien_before_notice_window_rejected(api):
    """PRD §3.8: "Filing is defined only from `NOTICE_SENT`, and is permitted only when
    the current clock is at least 14 days after the `notice_sent_date`; an earlier
    attempt gives `ERR_WINDOW_NOT_ELAPSED`."

    Design: Corner/state_machines/file_lien_before_notice_window_returns_window_not_elapsed
    """
    # Notice sent at 2026-07-02; attempt file-lien only 5 days later (< 14).
    ctx = setup_auction_opened(climate=True, rate=10000,
                               past_due_date="2026-07-02T00:00:00Z")
    set_clock("2026-07-07T00:00:00Z")
    resp = api.file_lien(ctx["auction"]["id"], LIEN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_ELAPSED.value)
    a = validate_success(api.get_auction_proceeding(ctx["auction"]["id"], LIEN), 200)
    assert a["status"] == "NOTICE_SENT"


def test_schedule_before_cooling_off_rejected(api):
    """PRD §3.8: "Scheduling is defined only from `LIEN_FILED`, and the supplied
    `scheduled_sale_date` must be at least 14 days after the `lien_filed_date` — a
    cooling-off window; an earlier date gives `ERR_WINDOW_NOT_ELAPSED`."

    Design: Corner/state_machines/schedule_before_cooling_off_returns_window_not_elapsed
    """
    ctx = setup_auction_opened(climate=True, rate=10000,
                               past_due_date="2026-07-02T00:00:00Z")
    set_clock("2026-07-16T00:00:00Z")
    validate_success(api.file_lien(ctx["auction"]["id"], LIEN), 200)
    # lien_filed_date = 2026-07-16; sale date 2026-07-20 is only 4 days later (< 14).
    resp = api.schedule_auction(
        ctx["auction"]["id"], {"scheduled_sale_date": "2026-07-20T00:00:00Z"}, LIEN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_ELAPSED.value)
    a = validate_success(api.get_auction_proceeding(ctx["auction"]["id"], LIEN), 200)
    assert a["status"] == "LIEN_FILED"


def test_close_already_closed_lease_invalid_state(api):
    """PRD §3.11: "Closing is defined from `ACTIVE` or `DELINQUENT` status only."
    PRD §2.8: "For state-transition endpoints, the target resource being in a state from
    which the requested transition is not defined is checked fifth, giving
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminal_lease_closed_cannot_transition
    """
    # Climate lease, pay first invoice 12000 to zero, close, then close again.
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    pay(ctx["lease"]["id"], 12000, ctx["tenant"]["id"])
    validate_success(api.close_lease(ctx["lease"]["id"], FM), 200)
    resp = api.close_lease(ctx["lease"]["id"], FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert refreshed["status"] == "CLOSED"


def test_waive_open_invoice_credits_remainder(api):
    """PRD §3.4: "Waiving moves the invoice to `WAIVED`, appends a `CREDIT` ledger entry
    for the invoice's unpaid remainder, and decreases the lease's `balance_cents` by that
    same unpaid remainder."

    Design: Corner/state_machines/waive_invoice_credits_remainder_and_reduces_balance
    """
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    invoices, _ = validate_paginated(
        api.list_invoices(FM, params={"lease_id": ctx["lease"]["id"]}))
    inv0 = invoices[0]
    assert inv0["total_amount_cents"] == 12000
    waived = validate_success(api.waive_invoice(inv0["id"], FM), 200)
    assert waived["status"] == "WAIVED"
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease["balance_cents"] == 0
    entries, _ = validate_paginated(
        api.list_ledger_entries(FM, params={"lease_id": ctx["lease"]["id"]}))
    credits = [e for e in entries if e["entry_type"] == "CREDIT"]
    assert len(credits) == 1 and credits[0]["amount_cents"] == -12000, \
        f"expected one CREDIT of -12000, got {entries}"


def test_insurance_lapses_then_reactivates_on_cure(api):
    """PRD §3.5: "When the invoice that carries an active policy's premium becomes
    `OVERDUE`, that `InsurancePolicy` moves `ACTIVE → LAPSED` on the billing run."
    PRD §3.5: "a `LAPSED` insurance policy returns to `ACTIVE` once the arrears are cured
    and the balance reaches zero."

    Design: Corner/state_machines/insurance_lapse_and_reactivate_on_cure
    """
    # Climate lease @10000 + STANDARD insurance (1500/mo): first invoice 13500.
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000},
                          lease_overrides={"insurance_required": True},
                          with_insurance="STANDARD")
    policy_id = ctx["policy"]["id"]
    # Advance past grace (5 days) and run billing-cycle -> invoice OVERDUE, policy LAPSED.
    set_clock("2026-04-20T00:00:00Z")
    validate_success(api.run_billing_cycle(ctx["facility"]["id"], FM), 200)
    lapsed = validate_success(api.get_insurance_policy(policy_id, FM), 200)
    assert lapsed["status"] == "LAPSED"
    # Pay 13500 invoice + 2000 late fee = 15500 to cure to zero -> policy ACTIVE.
    pay(ctx["lease"]["id"], 15500, ctx["tenant"]["id"])
    cured = validate_success(api.get_insurance_policy(policy_id, FM), 200)
    assert cured["status"] == "ACTIVE"


def test_insurance_required_blocks_activation(api):
    """PRD §3.3: "when the lease's `insurance_required` is true, an `InsurancePolicy` with
    `status` equal to `ACTIVE` must already exist for this lease; if none does, activation
    is rejected with `ERR_INSURANCE_REQUIRED` (HTTP 409)."

    Design: Corner/validations/insurance_required_blocks_activation
    """
    fac = create_facility(name="FV1", state_code="CA", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="Z-13", climate_controlled=True,
                       monthly_rate_cents=10000)
    ten = create_tenant(email="fv1@x.com", full_name="F V1", state_code="CA")
    set_clock("2026-04-01T00:00:00Z")
    lease = create_lease(unit["id"], ten["id"], insurance_required=True)
    resp = api.activate_lease(lease["id"], FM)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_REQUIRED.value)
    refreshed = validate_success(api.get_lease(lease["id"], FM), 200)
    assert refreshed["status"] == "PENDING"


def test_existence_before_state_on_unknown_lease_activate(api):
    """PRD §2.8: "Existence of all referenced resources is checked third, giving
    `ERR_NOT_FOUND`. ... For state-transition endpoints, the target resource being in a
    state from which the requested transition is not defined is checked fifth, giving
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/validations/existence_before_state_on_unknown_lease_activate
    """
    resp = api.activate_lease("11111111-1111-4111-8111-111111111111", FM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_redeem_requires_balance_cleared(api):
    """PRD §3.9: "Redemption requires that a payment covering the redemption amount has
    been applied so that the lease's `balance_cents` equals zero; a redemption attempted
    while the balance is non-zero is rejected with `ERR_BALANCE_NOT_CLEARED`."

    Design: Corner/validations/redeem_requires_balance_cleared
    """
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  past_due_date="2026-07-02T00:00:00Z")
    # No redemption payment made; balance still > 0.
    resp = api.redeem_auction(ctx["auction"]["id"], make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_BALANCE_NOT_CLEARED.value)
    a = validate_success(api.get_auction_proceeding(ctx["auction"]["id"], LIEN), 200)
    assert a["status"] == "SCHEDULED"


def test_list_units_filter_by_facility_and_status(api):
    """PRD §2.3: "The pagination fields surfaced in the `meta` object are `limit`,
    `offset`, `total_count`, and `has_more`, where `total_count` is the count of all
    records matching the query before pagination and `has_more` indicates whether records
    remain beyond the current page."
    PRD §4: "List units; filter by facility, status, current lease"

    Design: Corner/endpoints/list_units_filter_by_facility_and_status
    """
    fac = create_facility(name="FE1", state_code="CA", climate_premium_pct=0.20)
    u1 = create_unit(fac["id"], unit_number="Q-1", monthly_rate_cents=10000)
    create_unit(fac["id"], unit_number="Q-2", size_class="SIZE_5X5", monthly_rate_cents=5000)
    ten = create_tenant(email="fe1@x.com", full_name="F E1", state_code="CA")
    set_clock("2026-04-01T00:00:00Z")
    lease = create_lease(u1["id"], ten["id"])
    validate_success(api.activate_lease(lease["id"], FM), 200)
    resp = api.list_units(FM, params={"facility_id": fac["id"], "status": "AVAILABLE"})
    data, meta = validate_paginated(resp)
    numbers = {u["unit_number"] for u in data}
    assert numbers == {"Q-2"}, f"expected only AVAILABLE Q-2, got {numbers}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_transfer_cancel_releases_request(api):
    """PRD §3.10: "A requested transfer may instead be cancelled by a `FacilityManager`,
    which moves the order `REQUESTED → CANCELLED`, releases the destination unit from its
    hold, and changes no rate."

    Design: Corner/endpoints/transfer_cancel_releases_request
    """
    ctx = setup_transfer_requested(from_rate=10000, to_rate=18000)
    cancelled = validate_success(api.cancel_transfer(ctx["transfer"]["id"], FM), 200)
    assert cancelled["status"] == "CANCELLED"
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease["unit_id"] == ctx["u1"]["id"], "lease keeps its current unit after cancel"
