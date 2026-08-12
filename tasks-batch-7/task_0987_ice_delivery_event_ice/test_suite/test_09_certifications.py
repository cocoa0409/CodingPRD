"""Handler certifications and the dry-ice safety gate (PRD §3.2, §3.5, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    confirm,
    full_book_payload,
    get_success_data,
    make_active_book,
    make_certification,
    make_customer,
    make_depot,
    order_line,
    quoted_order,
    run_ops,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def _setup(customer_name, depot_name, limit=500000):
    depot = make_depot(10, depot_name)
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name=customer_name, kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=limit,
    )
    return depot, cust


def test_cert_expiry_sweep(api):
    """PRD §3.9: "Second, certification expiry: `ACTIVE` and `SUSPENDED`
    certifications whose `expires_at` has passed the clock become `EXPIRED`."

    Design: Corner/state_machines/cert_expiry_sweep
    """
    depot = make_depot(10, "Depot S13")
    set_logical_clock()
    cust = make_customer(
        account_name="S13", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    cert = make_certification(
        cust["id"], handler_name="E Expiring", certificate_number="CERT-EXP",
        max_dry_ice_lbs=500, expires_at="2026-05-02T00:00:00Z",
    )
    set_logical_clock("2026-05-03T09:00:00Z")
    ops = run_ops(depot["id"])
    assert cert["id"] in ops["expired_cert_ids"]

    certs, _meta = validate_paginated(api.list_certifications(cust["id"], SAFETY))
    assert certs[0]["status"] == "EXPIRED"


def test_reinstate_expired_cert_rejected(api):
    """PRD §3.2: "reinstating moves `SUSPENDED` back to `ACTIVE`, but only
    while the certificate remains temporally valid — reinstating one whose
    `expires_at` has passed the logical clock is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/validations/reinstate_expired_cert_rejected
    """
    depot = make_depot(10, "Depot V38")
    set_logical_clock()
    cust = make_customer(
        account_name="V38", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    cert = make_certification(
        cust["id"], handler_name="Lapsed Larry", certificate_number="CERT-38",
        max_dry_ice_lbs=500, expires_at="2026-05-02T00:00:00Z",
    )
    suspended = validate_success(api.suspend_certification(cert["id"], SAFETY))
    assert suspended["status"] == "SUSPENDED"
    # Advance the clock past expiry WITHOUT an ops checkpoint: the cert is
    # still SUSPENDED (not yet swept), but reinstatement must be refused.
    set_logical_clock("2026-05-03T09:00:00Z")
    resp = api.reinstate_certification(cert["id"], SAFETY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ----------------- difficulty: cert status gates the confirm ---------------------

def test_dry_ice_confirm_gated_by_cert_status(api):
    """PRD §3.2: "A certification qualifies an order when three conditions all
    hold: its status is `ACTIVE`; its `expires_at` is no earlier than the end
    of the order's event window; and its `max_dry_ice_lbs` is at least the
    order's total `dry_ice_lbs`."
    PRD §3.2: "An order containing dry ice that finds no qualifying
    certification at confirm time is rejected with `ERR_DRY_ICE_CERT_REQUIRED`
    — whether because none exists, the only candidate is `SUSPENDED`, its
    poundage cap is too small, or it lapses before the event window ends."

    Design: Difficulty/cross_entity_state_dependency/dry_ice_confirm_gated_by_cert_status
    """
    depot, cust = _setup("CE2 Events", "Depot CE2")
    cert = make_certification(
        cust["id"], handler_name="Hank Handler", certificate_number="CERT-9",
        max_dry_ice_lbs=1000, expires_at="2026-12-31T00:00:00Z",
    )
    assert cert["status"] == "ACTIVE", "new certifications are ACTIVE"
    order = quoted_order(
        cust["id"], depot["id"], [order_line("DRY_ICE", "BAG", 13)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )

    validate_success(api.suspend_certification(cert["id"], SAFETY))
    resp = api.confirm_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_DRY_ICE_CERT_REQUIRED)

    validate_success(api.reinstate_certification(cert["id"], SAFETY))
    confirmed = confirm(order["id"], cust["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED"
    assert confirmed["dry_ice_lbs"] == 130, (
        "cert gate satisfied: ACTIVE, 1000 >= 130, expiry beyond window end"
    )


def test_dry_ice_confirm_rejected_when_poundage_cap_too_small(api):
    """PRD §3.2: "An order containing dry ice that finds no qualifying
    certification at confirm time is rejected with `ERR_DRY_ICE_CERT_REQUIRED`
    — whether because none exists, the only candidate is `SUSPENDED`, its
    poundage cap is too small, or it lapses before the event window ends."
    PRD §3.4: "`dry_ice_lbs` sums, across `DRY_ICE` lines only, the quantity
    times the unit weight: ten pounds per bag unit, five hundred per pallet
    unit."

    Design: Difficulty/cross_entity_state_dependency/dry_ice_confirm_gated_by_cert_status
    """
    depot, cust = _setup("CE2b Events", "Depot CE2b")
    make_certification(
        cust["id"], handler_name="Light Lift", certificate_number="CERT-10",
        max_dry_ice_lbs=100, expires_at="2027-01-01T00:00:00Z",
    )
    order = quoted_order(
        cust["id"], depot["id"], [order_line("DRY_ICE", "BAG", 13)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    assert order["dry_ice_lbs"] == 130
    resp = api.confirm_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_DRY_ICE_CERT_REQUIRED)
    # ACTIVE but 100 lbs covered < 130 lbs ordered


# ----------------- difficulty: safety beats temporal on confirm -------------------

def test_missing_cert_surfaces_before_stale_event(api):
    """PRD §3.5: "First stands dry-ice safety: when the order's `dry_ice_lbs`
    is positive, the customer must hold a qualifying certification as defined
    in §3.2, else `ERR_DRY_ICE_CERT_REQUIRED`. Next, the lead-time check is
    re-run: the `event_date` must still be at least one day beyond the current
    logical date, else `ERR_EVENT_TOO_SOON`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_confirm
    """
    depot, cust = _setup("PP2 Events", "Depot PP2")
    order = quoted_order(
        cust["id"], depot["id"], [order_line("DRY_ICE", "BAG", 5)],
        channel="WILL_CALL", event_date="2026-05-03",
        window_start="10:00", window_end="12:00",
    )
    # Both gates now fail: no certification exists, and 2026-05-03 is no
    # longer at least one day beyond the advanced logical date.
    set_logical_clock("2026-05-03T09:00:00Z")
    resp = api.confirm_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_DRY_ICE_CERT_REQUIRED)


def test_stale_event_rejected_when_cert_valid(api):
    """PRD §3.5: "Next, the lead-time check is re-run: the `event_date` must
    still be at least one day beyond the current logical date, else
    `ERR_EVENT_TOO_SOON`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_confirm
    """
    depot, cust = _setup("PP2b Events", "Depot PP2b")
    make_certification(
        cust["id"], handler_name="Hank Handler", certificate_number="CERT-11",
        max_dry_ice_lbs=1000, expires_at="2027-01-01T00:00:00Z",
    )
    order = quoted_order(
        cust["id"], depot["id"], [order_line("DRY_ICE", "BAG", 5)],
        channel="WILL_CALL", event_date="2026-05-03",
        window_start="10:00", window_end="12:00",
    )
    # Safety now passes; only the re-checked lead time fails.
    set_logical_clock("2026-05-03T09:00:00Z")
    resp = api.confirm_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_TOO_SOON)
