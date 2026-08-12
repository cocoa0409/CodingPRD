"""Credit exposure ledger, EFT drafts, and the WATCH band (PRD §2.10, §3.8)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_deliver_drop,
    execute_draft,
    schedule_eft_draft,
    set_clock,
    setup_full_drop_fixture,
    void_invoice,
)

ADMIN = TEST_USERS["admin_headers"]
CREDIT = TEST_USERS["credit_headers"]


# ---------------------------------------------------------------------------
# Difficulty / compensating_invariant / invoice_void_restores_exposure
# ---------------------------------------------------------------------------


def test_invoice_void_restores_exposure_forward_action(api):
    """PRD §2.10: "Each dealer station carries `current_exposure_cents`, the
    sum of `total_cents` over that station's invoices in `ISSUED` or
    `OVERDUE` status — paid and voided invoices never count. Exposure is
    recomputed whenever an invoice is created at delivery, whenever an
    invoice is voided, and whenever an EFT draft settles..."

    Design: Difficulty/compensating_invariant/invoice_void_restores_exposure
    """
    fixture = setup_full_drop_fixture(
        state_code="TX", state_excise_tc_per_gal=200, price_tc_per_gal=3059,
        tank_capacity=30000, opening_physical=0, category="DIESEL",
    )
    delivered = create_and_deliver_drop(
        fixture, planned_gallons=5500, delivered_gallons=5500
    )
    station_now = get_success_data(api.get_dealer_station(
        fixture["station"]["id"], ADMIN
    ))
    assert station_now["current_exposure_cents"] == 1_948_650


def test_invoice_void_restores_exposure_compensating_action(api):
    """PRD §3.8: "A `CreditManager` may void an invoice in `ISSUED` or
    `OVERDUE`, moving it to `VOID`: the station's `current_exposure_cents`
    is recomputed to remove the invoice, the credit band is re-evaluated,
    and any draft still `SCHEDULED` for that invoice is cancelled to
    `CANCELLED` in the same request."
    PRD §2.10: "Exposure is recomputed whenever an invoice is created at
    delivery, whenever an invoice is voided, and whenever an EFT draft
    settles; every recompute is immediate and visible in the same request's
    reads."

    Design: Difficulty/compensating_invariant/invoice_void_restores_exposure
    """
    fixture = setup_full_drop_fixture(
        state_code="TX", state_excise_tc_per_gal=200, price_tc_per_gal=3059,
        tank_capacity=30000, opening_physical=0, category="DIESEL",
    )
    delivered = create_and_deliver_drop(
        fixture, planned_gallons=5500, delivered_gallons=5500
    )
    voided = validate_success(api.void_invoice(delivered["invoice_id"], CREDIT))
    assert voided["status"] == "VOID"
    station_now = get_success_data(api.get_dealer_station(
        fixture["station"]["id"], ADMIN
    ))
    assert station_now["current_exposure_cents"] == 0


# ---------------------------------------------------------------------------
# Corner / complexity_layers / credit_watch_band_at_exactly_80pct
# ---------------------------------------------------------------------------


def test_credit_watch_band_at_exactly_80pct_entry(api):
    """PRD §2.10: "On every recompute the station's credit band is
    re-evaluated against `credit_limit_cents`: exposure reaching at least 80
    percent of the limit places the station in `WATCH` (the boundary is
    inclusive), and exposure below that line keeps or returns the station to
    `GOOD_STANDING`."

    Design: Corner/complexity_layers/credit_watch_band_at_exactly_80pct
    """
    fixture = setup_full_drop_fixture(
        state_code="NM", state_excise_tc_per_gal=0,
        credit_limit_cents=1_000_000, price_tc_per_gal=1376,
        tank_capacity=20000, opening_physical=0,
    )
    create_and_deliver_drop(fixture, planned_gallons=5000, delivered_gallons=5000)
    station_now = get_success_data(api.get_dealer_station(
        fixture["station"]["id"], ADMIN
    ))
    # 5000 gal at 1376 tc = fuel 688000; freight 20000 (mid tier);
    # tax 5000*184/10 = 92000 -> total 800000 == 80% of 1000000 exactly.
    assert station_now["current_exposure_cents"] == 800_000
    assert station_now["credit_status"] == "WATCH"


def test_credit_watch_band_settle_returns_to_good_standing(api):
    """PRD §2.10: "exposure below that line keeps or returns the station to
    `GOOD_STANDING`."
    PRD §3.8: "When the outcome is `SUCCEEDED`, the draft becomes `SETTLED`,
    the invoice moves from `ISSUED` or `OVERDUE` to `PAID`, the station's
    exposure is recomputed to remove the settled invoice, and the credit
    band is re-evaluated."

    Design: Corner/complexity_layers/credit_watch_band_at_exactly_80pct
    """
    fixture = setup_full_drop_fixture(
        state_code="NM", state_excise_tc_per_gal=0,
        credit_limit_cents=1_000_000, price_tc_per_gal=1376,
        tank_capacity=20000, opening_physical=0,
    )
    delivered = create_and_deliver_drop(
        fixture, planned_gallons=5000, delivered_gallons=5000
    )
    invoice_id = delivered["invoice_id"]
    draft = schedule_eft_draft(invoice_id, scheduled_date="2026-05-02")
    set_clock("2026-05-02T00:00:00Z")
    execute_draft(draft["id"], outcome="SUCCEEDED")
    invoice_now = get_success_data(api.get_invoice(invoice_id, ADMIN))
    assert invoice_now["status"] == "PAID"
    station_now = get_success_data(api.get_dealer_station(
        fixture["station"]["id"], ADMIN
    ))
    assert station_now["current_exposure_cents"] == 0
    assert station_now["credit_status"] == "GOOD_STANDING"


# ---------------------------------------------------------------------------
# Corner / validations / draft_execute_before_scheduled_date_rejected
# ---------------------------------------------------------------------------


def test_draft_execute_before_scheduled_date_rejected(api):
    """PRD §3.8: "The draft must be `SCHEDULED` (else `ERR_INVALID_STATE`)
    and the current clock date must be on or after its `scheduled_date`
    (else `ERR_DRAFT_NOT_EXECUTABLE`, HTTP 409)."

    Design: Corner/validations/draft_execute_before_scheduled_date_rejected
    """
    fixture = setup_full_drop_fixture()
    delivered = create_and_deliver_drop(fixture, planned_gallons=1000)
    draft = schedule_eft_draft(delivered["invoice_id"], scheduled_date="2026-05-10")
    # Clock is still at default 2026-05-01, before the scheduled date.
    resp = api.execute_eft_draft(draft["id"], {"outcome": "SUCCEEDED"}, CREDIT)
    validate_error(resp, ApiErrorId.ERR_DRAFT_NOT_EXECUTABLE)
