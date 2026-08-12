"""State-machine transitions, auto-transitions, and terminal lockdowns (PRD §3)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_agreement,
    create_and_deliver_drop,
    create_and_reconcile_drop,
    create_dealer_station_payload,
    create_draft_agreement,
    create_drop,
    create_posted_price,
    create_product_payload,
    create_set_clock_payload,
    create_station,
    create_supply_agreement_payload,
    make_admin_headers,
    make_dealer_operator_headers,
    open_reconciliation,
    record_audit,
    report_loss,
    schedule_drop,
    dispatch_drop,
    deliver_drop,
    reconcile_drop,
    create_storage_tank_payload,
    create_tank,
    create_truck,
    create_gasoline_product,
    setup_full_drop_fixture,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
PRICING = TEST_USERS["pricing_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CREDIT = TEST_USERS["credit_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Invalid transitions / terminal lockdowns (Corner/state_machines)
# ---------------------------------------------------------------------------


def test_deliver_planned_drop_rejected(api):
    """PRD §3.6: "Execution walks a strict chain, each step performed by a
    `Dispatcher` and each requiring the exact from-state on pain of
    `ERR_INVALID_STATE`: scheduling moves `PLANNED` to `SCHEDULED`; dispatch
    moves `SCHEDULED` to `EN_ROUTE`. Delivery moves `EN_ROUTE` to `DELIVERED`..."

    Design: Corner/state_machines/deliver_planned_drop_rejected
    """
    fixture = setup_full_drop_fixture()
    drop = create_drop(fixture, planned_gallons=1000)
    resp = api.deliver_transport_drop(drop["id"], {"delivered_gallons": 1000}, DISPATCH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    drop_now = get_success_data(api.get_transport_drop(drop["id"], DISPATCH))
    assert drop_now["status"] == "PLANNED"
    assert drop_now["invoice_id"] is None


def test_cancel_reconciled_drop_rejected(api):
    """PRD §3.6: "A drop still in `PLANNED` or `SCHEDULED` may instead be
    cancelled outright into `CANCELLED`, which is terminal."
    PRD §3.6: "The last step is reconciliation: a delivered drop moves from
    `DELIVERED` to `RECONCILED`, folding the delivery into the station's
    inventory truth."

    Design: Corner/state_machines/cancel_reconciled_drop_rejected
    """
    fixture = setup_full_drop_fixture()
    reconciled = create_and_reconcile_drop(fixture, planned_gallons=1000)
    resp = api.cancel_transport_drop(reconciled["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    drop_now = get_success_data(api.get_transport_drop(reconciled["id"], DISPATCH))
    assert drop_now["status"] == "RECONCILED"


def test_post_superseded_posting_rejected(api):
    """PRD §3.5: "A draft that will never be posted may be discarded, moving
    it from `DRAFT` to `DISCARDED`; both `SUPERSEDED` and `DISCARDED` are
    terminal."
    PRD §3.5: "Posting a draft moves it to `POSTED`..."

    Design: Corner/state_machines/post_superseded_posting_rejected
    """
    product = create_gasoline_product()
    posting = create_posted_price(product["id"], price_tc_per_gal=2000)
    # Supersede once (moves posting to SUPERSEDED).
    get_success_data(api.supersede_rack_price_posting(
        posting["id"],
        {
            "expected_superseded_posting_version": posting["version"],
            "new_price_tc_per_gal": 2050,
            "effective_date": "2026-05-01",
        },
        PRICING,
    ))
    resp = api.post_rack_price_posting(posting["id"], PRICING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_invoice_auto_overdue_on_clock_advance(api):
    """PRD §3.8: "An invoice ages automatically: when the logical clock
    advances past its `due_date`, an `ISSUED` invoice becomes `OVERDUE`."
    PRD §3.6: "The invoice's `due_date` is its `invoice_date` plus the
    station's `credit_terms_days`."

    Design: Corner/state_machines/invoice_auto_overdue_on_clock_advance
    """
    fixture = setup_full_drop_fixture(credit_terms_days=10)
    # Delivered at default clock 2026-05-01 -> invoice_date 2026-05-01, due 2026-05-11.
    delivered = create_and_deliver_drop(fixture, planned_gallons=1000)
    invoice_id = delivered["invoice_id"]
    assert invoice_id is not None
    set_clock("2026-05-12T00:00:00Z")
    invoice = get_success_data(api.get_invoice(invoice_id, ADMIN))
    assert invoice["due_date"] == "2026-05-11"
    assert invoice["status"] == "OVERDUE"


def test_agreement_auto_expired_on_clock_advance(api):
    """PRD §3.3: "If the logical clock advances past `term_end_date` while the
    agreement sits in `ACTIVE` or `RENEWAL_PENDING` — a renewal opened but
    never completed — the agreement moves to `EXPIRED`."
    PRD §3.3: "A `JobberAdmin` may open renewal on an `ACTIVE` agreement only
    when the current clock date lies within the renewal window..."

    Design: Corner/state_machines/agreement_auto_expired_on_clock_advance
    """
    station = create_station(credit_limit_cents=500000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-05-10",
        committed_gallons=1000,
        imaging_allowance_cents=1000,
        margin_tc_per_gal=10,
        shortfall_penalty_tc_per_gal=10,
    )
    set_clock("2026-05-11T00:00:00Z")
    agreement_now = get_success_data(api.get_supply_agreement(agreement["id"], ADMIN))
    assert agreement_now["status"] == "EXPIRED"
    # EXPIRED is terminal: start-renewal must fail with ERR_INVALID_STATE.
    resp = api.start_renewal(agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cure_period_expiry_defaults_station_and_agreement(api):
    """PRD §3.4: "The cure window is 30 days: if the logical clock advances
    past `cure_started_at` plus 30 days without a passing audit, or if another
    `FAIL` is recorded while the station is already in `CURE_PERIOD`, the
    station falls into `DEFAULT`."
    PRD §3.4: "Falling into `DEFAULT` is the sharpest cascade in the system:
    at the same instant, every supply agreement of the station that is in
    `ACTIVE` moves to `DEFAULT_NOTICE`, and `cure_started_at` is cleared."

    Design: Corner/state_machines/cure_period_expiry_defaults_station_and_agreement
    """
    station = create_station(credit_limit_cents=500000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        committed_gallons=1000,
        imaging_allowance_cents=1000,
        margin_tc_per_gal=10,
        shortfall_penalty_tc_per_gal=10,
    )
    set_clock("2026-05-10T00:00:00Z")
    record_audit(station["id"], score=60, audit_date="2026-05-10")
    # Advance past 2026-05-10 + 30 days = 2026-06-09.
    set_clock("2026-06-10T00:00:00Z")
    station_now = get_success_data(api.get_dealer_station(station["id"], ADMIN))
    assert station_now["compliance_status"] == "DEFAULT"
    agreement_now = get_success_data(api.get_supply_agreement(agreement["id"], ADMIN))
    assert agreement_now["status"] == "DEFAULT_NOTICE"


def test_cancel_buyout_returns_active(api):
    """PRD §3.3: "cancelling the buyout returns the agreement to `ACTIVE`."
    PRD §3.3: "Executing the buyout settles the economics and moves the
    agreement to the terminal `BOUGHT_OUT` state, recording the result in
    `buyout_settlement_cents`."

    Design: Corner/state_machines/cancel_buyout_returns_active
    """
    station = create_station(credit_limit_cents=500000)
    agreement = create_active_agreement(
        station["id"],
        committed_gallons=1000,
        imaging_allowance_cents=1000,
        margin_tc_per_gal=10,
        shortfall_penalty_tc_per_gal=10,
    )
    get_success_data(api.initiate_buyout(agreement["id"], ADMIN))
    after_cancel = validate_success(api.cancel_buyout(agreement["id"], ADMIN))
    assert after_cancel["status"] == "ACTIVE"
    assert after_cancel["buyout_settlement_cents"] is None


def test_loss_dispute_then_verify_cycle(api):
    """PRD §3.7: "The dealer may dispute a `REPORTED` event for their own
    station — ownership is enforced, with `ERR_STATION_OWNERSHIP_MISMATCH`
    (HTTP 403) for another station's event — moving it to `DISPUTED`."
    PRD §3.7: "verification moves an event from `REPORTED` or `DISPUTED` to
    `VERIFIED`, deducting its gallons from the tank's book when a `tank_id` is
    present..."

    Design: Corner/state_machines/loss_dispute_then_verify_cycle
    """
    product = create_gasoline_product()
    station = create_station(credit_limit_cents=500000, activate=False)
    tank = create_tank(station["id"], product["id"],
                       capacity_gallons=20000, opening_physical_gallons=10000)
    dealer = make_dealer_operator_headers(station["id"])
    loss = get_success_data(api.create_loss_event(
        {
            "station_id": station["id"],
            "tank_id": tank["id"],
            "loss_type": "DRIVE_OFF",
            "gallons": 300,
            "occurred_at": "2026-05-03T09:00:00Z",
        },
        dealer,
    ))
    disputed = validate_success(api.dispute_loss_event(loss["id"], dealer))
    assert disputed["status"] == "DISPUTED"
    tank_mid = get_success_data(api.get_storage_tank(tank["id"], ADMIN))
    assert tank_mid["book_inventory_gallons"] == 10000
    verified = validate_success(api.verify_loss_event(loss["id"], ADMIN))
    assert verified["status"] == "VERIFIED"
    tank_end = get_success_data(api.get_storage_tank(tank["id"], ADMIN))
    assert tank_end["book_inventory_gallons"] == 9700
