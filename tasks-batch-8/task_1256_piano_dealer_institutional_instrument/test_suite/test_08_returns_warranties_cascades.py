"""Completed-return cascade, consignment ledger conservation, warranty windows (PRD §3.1, §3.6, §3.8)."""
from datetime import datetime, timezone
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_consignor, create_instrument, create_available_instrument,
    create_order, order_line, create_order_payload, post_payment, pay_order_in_full,
    get_order, get_instrument, get_customer, get_consignor,
    create_delivery_crew, create_delivery_job, create_delivery_job_payload,
    install_order, create_warranty, confirm_warranty,
    set_clock, TEST_USERS,
)

ASSOCIATE = TEST_USERS["sales_associate_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
COORDINATOR = TEST_USERS["service_coordinator_headers"]


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _installed_paid_order(api, serial="SN-W-1", unit=500_000, name="Wendy Return",
                          email="wendy@x.com", job_day="2026-05-10"):
    """PAID_IN_FULL order delivered and installed with the clock at job_day 08:00."""
    customer = create_customer(full_name=name, email=email)
    instrument = create_available_instrument(
        serial_number=serial, category="GRAND", manufacturer="Steinway", model="A",
        year_built=2021, condition_grade="GOOD", list_price_cents=unit,
        floor_price_cents=unit - 100_000)
    order = create_order(customer["id"], [order_line(instrument["id"], unit)])
    order = pay_order_in_full(order)
    crew = create_delivery_crew(crew_name="Crew Beta", climate_certified=False)
    set_clock(f"{job_day}T08:00:00Z")
    job = create_delivery_job(order["id"], crew["id"],
                              f"{job_day}T09:00:00Z", f"{job_day}T12:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)
    validate_success(api.complete_delivery_job(job["id"], COORDINATOR), 200)
    order = install_order(order["id"])
    return customer, instrument, order


def test_complete_return_rewrites_both_tracks(api):
    """PRD §3.6: "A completed return is a full unwind: `payment_status` moves to `REFUNDED`
    and fulfillment to `RETURNED`; each line instrument moves from `DELIVERED` back to
    `IN_PREP`; every `REGISTERED` warranty covering one of those instruments is voided
    (`REGISTERED` → `VOID`), and each voided warranty subtracts 25 from the customer's
    `risk_score`, floored at 300; any `ACTIVE` financing agreement on the order is
    cancelled; and each consignment payout posted at sale is reversed out of
    `outstanding_payout_cents` by exactly the amount originally added."

    Design: Difficulty/transitive_cascade/complete_return_cascade_depth3
    """
    customer, instrument, order = _installed_paid_order(api)
    warranty = confirm_warranty(create_warranty(order["id"], instrument["id"])["id"])
    assert warranty["status"] == "REGISTERED"

    set_clock("2026-05-20T00:00:00Z")
    returned = validate_success(api.complete_return(order["id"], MANAGER), 200)
    assert returned["fulfillment_status"] == "RETURNED"
    assert returned["payment_status"] == "REFUNDED"
    assert get_instrument(instrument["id"])["status"] == "IN_PREP", "cascade link 1"


def test_complete_return_voids_warranty_and_docks_risk_score(api):
    """PRD §3.6: "every `REGISTERED` warranty covering one of those instruments is voided
    (`REGISTERED` → `VOID`), and each voided warranty subtracts 25 from the customer's
    `risk_score`, floored at 300".
    PRD §2.9: "`risk_score` begins at 700, loses 25 points per warranty voided by a return
    and 150 points per financing default, and is clamped to the band from 300 to 850."

    Design: Difficulty/transitive_cascade/complete_return_cascade_depth3
    """
    customer, instrument, order = _installed_paid_order(api)
    warranty = confirm_warranty(create_warranty(order["id"], instrument["id"])["id"])

    set_clock("2026-05-20T00:00:00Z")
    validate_success(api.complete_return(order["id"], MANAGER), 200)

    after_warranty = validate_success(
        api.get_warranty_registration(warranty["id"], ASSOCIATE), 200)
    assert after_warranty["status"] == "VOID", "cascade link 2"
    after_customer = get_customer(customer["id"])
    assert after_customer["risk_score"] == 675, "cascade link 3: 700 - 25"


def _consignment_sale(api, serial="SN-L-1"):
    """GROSS_SPLIT consignor, consignment instrument sold at 2000000, paid in full."""
    consignor = create_consignor(full_name="Lena Ledger", email="lena@x.com",
                                 commission_pct=0.20, split_mode="GROSS_SPLIT",
                                 payout_method="ACH")
    instrument = create_available_instrument(
        serial_number=serial, category="GRAND", manufacturer="Steinway", model="B",
        year_built=2012, condition_grade="GOOD", acquisition_type="CONSIGNMENT",
        consignor_id=consignor["id"], list_price_cents=2_000_000,
        floor_price_cents=1_500_000)
    customer = create_customer(full_name="Perry Pair", email="perry@x.com")
    order = create_order(customer["id"], [order_line(instrument["id"], 2_000_000)])
    assert order["total_cents"] == 2_015_000
    order = pay_order_in_full(order)
    return consignor, instrument, customer, order


def test_consignment_ledger_posts_payout_on_sale(api):
    """PRD §3.1: "Under `GROSS_SPLIT` the payout is that sale total multiplied by one minus
    the `commission_pct`, rounded half-up to whole cents." and "The payout is added to the
    consignor's `outstanding_payout_cents`."
    (2000000 * (1 - 0.20) == 1600000.)

    Design: Difficulty/compensating_invariant/consignment_payout_sell_then_return_conserves_ledger
    """
    consignor, instrument, _, order = _consignment_sale(api)
    assert get_instrument(instrument["id"])["status"] == "SOLD"
    after = get_consignor(consignor["id"])
    assert after["outstanding_payout_cents"] == 1_600_000, (
        f"forward action posts +1600000, got {after['outstanding_payout_cents']}")


def test_consignment_ledger_reverses_exactly_on_return(api):
    """PRD §3.1: "If the underlying sale is later completed as a return, the same payout is
    subtracted again as a compensating reversal, so the ledger returns exactly to its
    pre-sale balance."
    PRD §3.6: "each consignment payout posted at sale is reversed out of
    `outstanding_payout_cents` by exactly the amount originally added."

    Design: Difficulty/compensating_invariant/consignment_payout_sell_then_return_conserves_ledger
    """
    consignor, instrument, _, order = _consignment_sale(api)
    crew = create_delivery_crew(crew_name="Crew Theta", climate_certified=False)
    set_clock("2026-05-10T08:00:00Z")
    job = create_delivery_job(order["id"], crew["id"],
                              "2026-05-10T09:00:00Z", "2026-05-10T12:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)
    validate_success(api.complete_delivery_job(job["id"], COORDINATOR), 200)
    install_order(order["id"])

    set_clock("2026-05-18T00:00:00Z")
    returned = validate_success(api.complete_return(order["id"], MANAGER), 200)
    assert returned["payment_status"] == "REFUNDED"
    assert returned["fulfillment_status"] == "RETURNED"
    after = get_consignor(consignor["id"])
    assert after["outstanding_payout_cents"] == 0, (
        f"forward + compensating actions conserve the ledger at 0, "
        f"got {after['outstanding_payout_cents']}")


def _gross_vs_net_setup(api):
    g = create_consignor(full_name="Gail Gross", email="g@x.com", commission_pct=0.20,
                         split_mode="GROSS_SPLIT", payout_method="ACH")
    n = create_consignor(full_name="Ned Net", email="n@x.com", commission_pct=0.20,
                         split_mode="NET_SPLIT", payout_method="WIRE")
    ig = create_available_instrument(
        serial_number="SN-G-1", category="GRAND", manufacturer="Steinway", model="B",
        year_built=2010, condition_grade="GOOD", acquisition_type="CONSIGNMENT",
        consignor_id=g["id"], list_price_cents=2_000_000, floor_price_cents=1_500_000)
    in_ = create_available_instrument(
        serial_number="SN-N-1", category="GRAND", manufacturer="Steinway", model="B",
        year_built=2011, condition_grade="GOOD", acquisition_type="CONSIGNMENT",
        consignor_id=n["id"], list_price_cents=2_000_000, floor_price_cents=1_500_000,
        recoverable_costs_cents=80_000)
    customer = create_customer(full_name="Carl Buyer", email="carl@x.com")
    og = create_order(customer["id"], [order_line(ig["id"], 2_000_000)])
    pay_order_in_full(og)
    on = create_order(customer["id"], [order_line(in_["id"], 2_000_000)])
    pay_order_in_full(on)
    return g, n, ig, in_


def test_consignment_gross_split_payout(api):
    """PRD §3.1: "Under `GROSS_SPLIT` the payout is that sale total multiplied by one minus
    the `commission_pct`, rounded half-up to whole cents."
    PRD §3.5: "A payment exactly equal to the balance settles the order: `payment_status`
    moves to `PAID_IN_FULL`, every reserved line instrument moves from `RESERVED` to `SOLD`,
    and the consignment payouts of §3.1 are posted to the consignor ledgers."
    (2000000 * 0.80 == 1600000.)

    Design: Difficulty/dual_variant_calc/consignment_gross_vs_net_split
    """
    g, _, ig, in_ = _gross_vs_net_setup(api)
    assert get_consignor(g["id"])["outstanding_payout_cents"] == 1_600_000
    assert get_instrument(ig["id"])["status"] == "SOLD"
    assert get_instrument(in_["id"])["status"] == "SOLD"


def test_consignment_net_split_deducts_recoverable_costs(api):
    """PRD §3.1: "Under `NET_SPLIT` the instrument's `recoverable_costs_cents` is subtracted
    from the sale total first, and the remainder is multiplied by one minus the
    `commission_pct`, rounded half-up — a strictly lower payout for an identical sale
    price."
    ((2000000 - 80000) * 0.80 == 1536000; 64000 below the GROSS_SPLIT payout.)

    Design: Difficulty/dual_variant_calc/consignment_gross_vs_net_split
    """
    g, n, _, _ = _gross_vs_net_setup(api)
    gross_outstanding = get_consignor(g["id"])["outstanding_payout_cents"]
    net_outstanding = get_consignor(n["id"])["outstanding_payout_cents"]
    assert net_outstanding == 1_536_000, f"got {net_outstanding}"
    assert gross_outstanding - net_outstanding == 64_000, (
        "recoverable costs are taxed only in NET_SPLIT")


def test_complete_return_after_fourteen_days_rejected(api):
    """PRD §3.6: "a `StoreManager` may complete a return only while fulfillment is
    `INSTALLED`, the order is `PAID_IN_FULL`, and the logical clock is no later than
    fourteen days after `installed_at`. A return attempted against the wrong fulfillment
    state is `ERR_DELIVERY_NOT_ACTIONABLE`, against the wrong payment state is
    `ERR_ORDER_NOT_PAYABLE`, and after the window is `ERR_RETURN_WINDOW_CLOSED`
    (HTTP 422)."
    (Installed 2026-05-12; attempted 2026-05-27 is 15 days later.)

    Design: Corner/validations/complete_return_after_fourteen_days_rejected
    """
    customer = create_customer(full_name="Rick Late", email="rick@x.com")
    instrument = create_available_instrument(
        serial_number="SN-RT-1", category="GRAND", manufacturer="Steinway", model="A",
        year_built=2022, condition_grade="GOOD", list_price_cents=500_000,
        floor_price_cents=400_000)
    order = pay_order_in_full(create_order(customer["id"],
                                           [order_line(instrument["id"], 500_000)]))
    crew = create_delivery_crew(crew_name="Crew Pi", climate_certified=False)
    set_clock("2026-05-10T08:00:00Z")
    job = create_delivery_job(order["id"], crew["id"],
                              "2026-05-10T09:00:00Z", "2026-05-10T12:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)
    validate_success(api.complete_delivery_job(job["id"], COORDINATOR), 200)
    set_clock("2026-05-12T00:00:00Z")
    install_order(order["id"])

    set_clock("2026-05-27T00:00:00Z")
    res = api.complete_return(order["id"], MANAGER)
    validate_error(res, "ERR_RETURN_WINDOW_CLOSED")
    assert get_order(order["id"])["fulfillment_status"] == "INSTALLED"


def _delivered_on_may_10(api, serial, name, email):
    customer = create_customer(full_name=name, email=email)
    instrument = create_available_instrument(
        serial_number=serial, category="GRAND", manufacturer="Steinway", model="O",
        year_built=2024, condition_grade="EXCELLENT", list_price_cents=500_000,
        floor_price_cents=400_000)
    order = pay_order_in_full(create_order(customer["id"],
                                           [order_line(instrument["id"], 500_000)]))
    crew = create_delivery_crew(crew_name="Crew Nu", climate_certified=False)
    set_clock("2026-05-10T08:00:00Z")
    job = create_delivery_job(order["id"], crew["id"],
                              "2026-05-10T09:00:00Z", "2026-05-10T12:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)
    validate_success(api.complete_delivery_job(job["id"], COORDINATOR), 200)
    return customer, instrument, get_order(order["id"])


def test_warranty_registration_after_sixty_days_rejected(api):
    """PRD §3.8: "The order must be `DELIVERED` or `INSTALLED`; the instrument must appear
    among the order's items, else `ERR_INVALID_REQUEST`; and registration must occur within
    sixty days of the order's `delivered_at` — later than that is rejected with
    `ERR_WARRANTY_WINDOW_CLOSED` (HTTP 422)."
    (Delivered 2026-05-10; attempted 2026-07-15 is 66 days later.)

    Design: Corner/validations/warranty_registration_after_sixty_days_rejected
    """
    _, instrument, order = _delivered_on_may_10(api, "SN-LW-1", "Late Larry", "larry@x.com")
    set_clock("2026-07-15T00:00:00Z")
    res = api.create_warranty_registration(
        {"order_id": order["id"], "instrument_id": instrument["id"]}, ASSOCIATE)
    validate_error(res, "ERR_WARRANTY_WINDOW_CLOSED")


def test_warranty_extension_within_thirty_days(api):
    """PRD §3.8: "Confirmation by a `StoreManager` moves the registration from `PENDING` to
    `REGISTERED`, stamps `registered_at` from the logical clock, and computes
    `coverage_end`: the order's `delivered_at` plus 24 calendar months, extended by a
    further 12 months when the registration is confirmed no later than thirty days after
    delivery — prompt registration earns the longer coverage."
    PRD §2.6: "Date arithmetic for warranty coverage uses calendar months: adding a month
    advances the same day-of-month."
    (Delivered 2026-05-10T08:00Z; confirmed 2026-05-20 (day 10) -> coverage_end is
    2029-05-10T08:00Z, not the base 24-month 2028-05-10.)

    Design: Corner/calculations/warranty_extension_within_thirty_days
    """
    _, instrument, order = _delivered_on_may_10(api, "SN-WC-1", "Willa Warrant", "willa@x.com")
    warranty = create_warranty(order["id"], instrument["id"])
    set_clock("2026-05-20T00:00:00Z")
    confirmed = validate_success(api.confirm_warranty(warranty["id"], MANAGER), 200)
    assert confirmed["status"] == "REGISTERED"
    assert _ts(confirmed["registered_at"]) == _ts("2026-05-20T00:00:00Z")
    assert _ts(confirmed["coverage_end"]) == _ts("2029-05-10T08:00:00Z"), (
        f"24 base + 12 extension months from 2026-05-10T08:00Z, got {confirmed['coverage_end']}")


def test_consignment_return_terminal_lockdown(api):
    """PRD §3.1: "The full instrument lifecycle also includes sales (`AVAILABLE` →
    `RESERVED` → `SOLD` → `DELIVERED`), returns (`DELIVERED` → `IN_PREP`), restoration
    (`AVAILABLE` → `RESTORATION_HOLD` → `IN_PREP`), repossession (`DELIVERED` →
    `REPOSSESSION_HOLD` → `AVAILABLE`), and consignment wind-down (`AVAILABLE` →
    `RETURNED_TO_CONSIGNOR`, the terminal state)."
    PRD §3.1: "Listing for sale moves an instrument from `IN_PREP` to `AVAILABLE`; only
    `IN_PREP` instruments are eligible (an instrument in `REPOSSESSION_HOLD` in particular
    is not eligible here), and an instrument in any other state is rejected with
    `ERR_INSTRUMENT_NOT_AVAILABLE`."

    Design: Corner/state_machines/consignment_return_terminal_lockdown
    """
    consignor = create_consignor(full_name="Terry Terminal", email="terry@x.com",
                                 commission_pct=0.20, split_mode="GROSS_SPLIT",
                                 payout_method="CHECK")
    instrument = create_available_instrument(
        serial_number="SN-TM-1", category="GRAND", manufacturer="Steinway", model="B",
        year_built=2009, condition_grade="FAIR", acquisition_type="CONSIGNMENT",
        consignor_id=consignor["id"], list_price_cents=900_000, floor_price_cents=700_000)
    returned = validate_success(api.return_to_consignor(instrument["id"], MANAGER), 200)
    assert returned["status"] == "RETURNED_TO_CONSIGNOR"

    res = api.list_instrument_for_sale(instrument["id"], MANAGER)
    validate_error(res, "ERR_INSTRUMENT_NOT_AVAILABLE")
    assert get_instrument(instrument["id"])["status"] == "RETURNED_TO_CONSIGNOR"
