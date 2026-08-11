"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints,
because each test starts against an empty database. Party-backed roles always
act through per-instance headers carrying the real Party id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_bid_payload,
    create_buyer_registration_payload,
    create_consignment_payload,
    create_drover_crew_payload,
    create_inspection_record_payload,
    create_load_manifest_payload,
    create_lot_payload,
    create_party_payload,
    create_pen_move_payload,
    create_pen_payload,
    create_sale_day_payload,
    create_scale_payload,
    create_weigh_ticket_payload,
)
from .test_users import (
    AUCTIONEER,
    BARN_ADMIN,
    INSPECTOR,
    RING_CLERK,
    SETTLEMENT_CLERK,
    YARD_OPERATOR,
    make_carrier_headers,
    make_consignor_headers,
)


class Scenario(dict):
    """Dict with attribute access, so tests can read scn.lot["id"]."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ---------------------------------------------------------------------------
# Tier 1 — primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, BARN_ADMIN))


def create_party(**overrides) -> dict:
    return get_success_data(
        api_client.create_party(create_party_payload(**overrides), BARN_ADMIN)
    )


def create_consignor_party(**overrides) -> dict:
    return create_party(**overrides)


def create_buyer_party(**overrides) -> dict:
    defaults = {
        "legal_name": "Midwest Packing",
        "party_type": "PACKER",
        "origin_state_code": "NE",
        "origin_county": "Douglas",
        "tax_id": "47-2222222",
    }
    defaults.update(overrides)
    return create_party(**defaults)


def create_carrier_party(**overrides) -> dict:
    defaults = {
        "legal_name": "Plains Livestock Hauling",
        "party_type": "CARRIER",
        "origin_state_code": "NE",
        "origin_county": "Dawson",
        "tax_id": "47-6666666",
    }
    defaults.update(overrides)
    return create_party(**defaults)


def set_party_status(party_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.set_party_status(party_id, {"to_status": to_status}, BARN_ADMIN)
    )


def create_sale_day(**overrides) -> dict:
    return get_success_data(
        api_client.create_sale_day(create_sale_day_payload(**overrides), BARN_ADMIN)
    )


def advance_sale_day(sale_day_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.advance_sale_day(sale_day_id, {"to_status": to_status}, BARN_ADMIN)
    )


def create_pen(**overrides) -> dict:
    return get_success_data(api_client.create_pen(create_pen_payload(**overrides), BARN_ADMIN))


def set_pen_status(pen_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.set_pen_status(pen_id, {"to_status": to_status}, BARN_ADMIN)
    )


def create_scale(**overrides) -> dict:
    return get_success_data(
        api_client.create_scale(create_scale_payload(**overrides), BARN_ADMIN)
    )


def create_crew(on_duty: bool = True, **overrides) -> dict:
    crew = get_success_data(
        api_client.create_drover_crew(create_drover_crew_payload(**overrides), YARD_OPERATOR)
    )
    if on_duty:
        crew = set_crew_duty(crew["id"], "ON_DUTY")
    return crew


def set_crew_duty(crew_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.set_crew_duty(crew_id, {"to_status": to_status}, YARD_OPERATOR)
    )


def create_consignment(sale_day_id: str, consignor_party_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_consignment(
            create_consignment_payload(sale_day_id, consignor_party_id, **overrides),
            make_consignor_headers(consignor_party_id),
        )
    )


def check_in_consignment(consignment_id: str) -> dict:
    return get_success_data(api_client.check_in_consignment(consignment_id, YARD_OPERATOR))


def report_loss(consignment_id: str, consignor_party_id: str, **payload) -> dict:
    return get_success_data(
        api_client.report_loss(
            consignment_id, payload, make_consignor_headers(consignor_party_id)
        )
    )


def create_lot(consignment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(create_lot_payload(consignment_id, **overrides), YARD_OPERATOR)
    )


def assign_pen(lot_id: str, pen_id: str) -> dict:
    return get_success_data(api_client.assign_pen(lot_id, {"pen_id": pen_id}, YARD_OPERATOR))


def open_weigh_ticket(lot_id: str, scale_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_weigh_ticket(
            create_weigh_ticket_payload(lot_id, scale_id, **overrides), YARD_OPERATOR
        )
    )


def capture_weigh_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.capture_weigh_ticket(ticket_id, YARD_OPERATOR))


def weigh_lot(lot_id: str, scale_id: str, **overrides) -> dict:
    """Open a draft and capture it in one step. Returns the captured ticket."""
    ticket = open_weigh_ticket(lot_id, scale_id, **overrides)
    return capture_weigh_ticket(ticket["id"])


def mark_lot_ready(lot_id: str) -> dict:
    return get_success_data(api_client.mark_lot_ready(lot_id, YARD_OPERATOR))


def enter_ring(lot_id: str) -> dict:
    return get_success_data(api_client.enter_ring(lot_id, AUCTIONEER))


def register_buyer(party_id: str, sale_day_id: str, approve: bool = True, **overrides) -> dict:
    registration = get_success_data(
        api_client.create_buyer_registration(
            create_buyer_registration_payload(party_id, sale_day_id, **overrides), BARN_ADMIN
        )
    )
    if approve:
        registration = get_success_data(
            api_client.approve_buyer_registration(registration["id"], BARN_ADMIN)
        )
    return registration


def place_bid(lot_id: str, registration_id: str, unit_price, headers=None) -> dict:
    return get_success_data(
        api_client.create_bid(
            create_bid_payload(lot_id, registration_id, unit_price), headers or RING_CLERK
        )
    )


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, YARD_OPERATOR))


def read_consignment(consignment_id: str) -> dict:
    return get_success_data(api_client.get_consignment(consignment_id, YARD_OPERATOR))


def read_sale_day(sale_day_id: str) -> dict:
    return get_success_data(api_client.get_sale_day(sale_day_id, BARN_ADMIN))


def read_pen(pen_id: str) -> dict:
    return get_success_data(api_client.get_pen(pen_id, BARN_ADMIN))


def read_scale(scale_id: str) -> dict:
    return get_success_data(api_client.get_scale(scale_id, BARN_ADMIN))


def read_crew(crew_id: str) -> dict:
    return get_success_data(api_client.get_drover_crew(crew_id, YARD_OPERATOR))


def read_weigh_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_weigh_ticket(ticket_id, YARD_OPERATOR))


def read_pen_move(move_id: str) -> dict:
    return get_success_data(api_client.get_pen_move(move_id, YARD_OPERATOR))


def read_bid(bid_id: str) -> dict:
    return get_success_data(api_client.get_bid(bid_id, RING_CLERK))


def read_purchase(purchase_id: str) -> dict:
    return get_success_data(api_client.get_purchase(purchase_id, SETTLEMENT_CLERK))


def read_buyer_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_buyer_registration(registration_id, BARN_ADMIN))


def read_buyer_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_buyer_invoice(invoice_id, SETTLEMENT_CLERK))


def read_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, SETTLEMENT_CLERK))


def read_inspection_record(record_id: str) -> dict:
    return get_success_data(api_client.get_inspection_record(record_id, INSPECTOR))


def read_load_manifest(manifest_id: str) -> dict:
    return get_success_data(api_client.get_load_manifest(manifest_id, BARN_ADMIN))


def read_load_line(line_id: str) -> dict:
    return get_success_data(api_client.get_load_line(line_id, BARN_ADMIN))


def lot_version(lot_id: str) -> int:
    return read_lot(lot_id)["version"]


def list_data(response) -> list:
    body = response.json()
    return body["data"]


def list_charge_lines(**params) -> list:
    return list_data(api_client.list_charge_lines(SETTLEMENT_CLERK, params=params))


def purchase_for_lot(lot_id: str) -> dict:
    rows = list_data(api_client.list_purchases(SETTLEMENT_CLERK, params={"lot_id": lot_id}))
    assert rows, f"expected a purchase for lot {lot_id}"
    return rows[-1]


def invoice_for_registration(registration_id: str) -> dict:
    rows = list_data(
        api_client.list_buyer_invoices(
            SETTLEMENT_CLERK, params={"buyer_registration_id": registration_id}
        )
    )
    assert rows, f"expected an invoice for registration {registration_id}"
    return rows[-1]


def settlement_for_consignment(consignment_id: str) -> dict:
    rows = list_data(
        api_client.list_settlements(
            SETTLEMENT_CLERK, params={"consignment_id": consignment_id}
        )
    )
    assert rows, f"expected a settlement for consignment {consignment_id}"
    return rows[0]


def close_sale_day(sale_day_id: str) -> dict:
    return get_success_data(api_client.close_sale_day(sale_day_id, SETTLEMENT_CLERK))


# ---------------------------------------------------------------------------
# Tier 2 — yard furniture and a checked-in consignment
# ---------------------------------------------------------------------------


def setup_yard(
    clock: str = TEST_DEFAULTS["CLOCK_START"],
    sale_date: str = TEST_DEFAULTS["SALE_DATE"],
    barn_state_code: str = TEST_DEFAULTS["BARN_STATE_CODE"],
    pen_capacity: int = TEST_DEFAULTS["PEN_CAPACITY"],
    pen_species_class: str = "CATTLE",
    with_pen: bool = True,
    with_scale: bool = True,
    scale_overrides: dict = None,
    open_check_in: bool = True,
) -> Scenario:
    """Clock, a consignor party, a sale day and the yard furniture."""
    set_clock(clock)
    scn = Scenario()
    scn.clock = clock
    scn.consignor = create_consignor_party()
    scn.consignor_headers = make_consignor_headers(scn.consignor["id"])
    scn.sale_day = create_sale_day(sale_date=sale_date, barn_state_code=barn_state_code)
    scn.pen = (
        create_pen(head_capacity=pen_capacity, species_class=pen_species_class)
        if with_pen
        else None
    )
    scn.scale = create_scale(**(scale_overrides or {})) if with_scale else None
    if open_check_in:
        scn.sale_day = advance_sale_day(scn.sale_day["id"], "CHECK_IN_OPEN")
    return scn


def setup_checked_in_consignment(
    head_received: int = 10, consignment_overrides: dict = None, **yard_kwargs
) -> Scenario:
    """A yard plus one checked-in consignment ready to be sorted into lots."""
    scn = setup_yard(**yard_kwargs)
    scn.consignment = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=head_received,
        **(consignment_overrides or {}),
    )
    scn.consignment = check_in_consignment(scn.consignment["id"])
    return scn


# ---------------------------------------------------------------------------
# Tier 3 — a weighed, penned, ready lot and the ring
# ---------------------------------------------------------------------------


def setup_ready_lot(
    head_received: int = 10,
    head_count: int = 10,
    consignment_overrides: dict = None,
    lot_overrides: dict = None,
    gross_weight_lb: int = TEST_DEFAULTS["GROSS_WEIGHT_LB"],
    tare_weight_lb: int = TEST_DEFAULTS["TARE_WEIGHT_LB"],
    weigh: bool = True,
    pen: bool = True,
    ready: bool = True,
    **yard_kwargs,
) -> Scenario:
    """One lot drawn from a checked-in consignment, optionally penned, weighed
    and marked ready for the ring."""
    scn = setup_checked_in_consignment(
        head_received=head_received,
        consignment_overrides=consignment_overrides,
        **yard_kwargs,
    )
    scn.lot = create_lot(
        scn.consignment["id"], head_count=head_count, **(lot_overrides or {})
    )
    if pen and scn.pen:
        scn.lot = assign_pen(scn.lot["id"], scn.pen["id"])
    if weigh:
        scn.ticket = weigh_lot(
            scn.lot["id"],
            scn.scale["id"],
            head_on_draft=head_count,
            gross_weight_lb=gross_weight_lb,
            tare_weight_lb=tare_weight_lb,
        )
    if ready:
        scn.lot = mark_lot_ready(scn.lot["id"])
    scn.consignment = read_consignment(scn.consignment["id"])
    return scn


def add_buyer(
    scn: Scenario,
    bond_type: str = "BONDED",
    credit_limit=TEST_DEFAULTS["CREDIT_LIMIT"],
    buyer_number: int = 101,
    approve: bool = True,
    buyer_party: dict = None,
    buyer_party_overrides: dict = None,
    **registration_overrides,
) -> Scenario:
    """Register (and by default approve) one bidder for the scenario's sale day."""
    scn.buyer_party = buyer_party or create_buyer_party(**(buyer_party_overrides or {}))
    scn.registration = register_buyer(
        scn.buyer_party["id"],
        scn.sale_day["id"],
        approve=approve,
        buyer_number=buyer_number,
        bond_type=bond_type,
        credit_limit=credit_limit,
        **registration_overrides,
    )
    return scn


def open_the_ring(scn: Scenario, enter: bool = True) -> Scenario:
    """Advance the sale day to RINGING and bring the lot into the ring."""
    scn.sale_day = advance_sale_day(scn.sale_day["id"], "RINGING")
    if enter:
        scn.lot = enter_ring(scn.lot["id"])
    return scn


def hammer_lot(scn: Scenario, unit_price=TEST_DEFAULTS["UNIT_PRICE"], buy_back=None) -> Scenario:
    """Record a bid at unit_price and drop the hammer on it."""
    scn.bid = place_bid(scn.lot["id"], scn.registration["id"], unit_price)
    payload = {
        "winning_bid_id": scn.bid["id"],
        "expected_lot_version": lot_version(scn.lot["id"]),
    }
    if buy_back is not None:
        payload["buy_back"] = buy_back
    get_success_data(api_client.hammer_down(scn.lot["id"], payload, AUCTIONEER))
    scn.lot = read_lot(scn.lot["id"])
    scn.purchase = purchase_for_lot(scn.lot["id"])
    scn.invoice = invoice_for_registration(scn.registration["id"])
    scn.bid = read_bid(scn.bid["id"])
    return scn


def setup_sold_lot(
    unit_price=TEST_DEFAULTS["UNIT_PRICE"],
    bond_type: str = "BONDED",
    credit_limit=TEST_DEFAULTS["CREDIT_LIMIT"],
    buyer_party_overrides: dict = None,
    registration_overrides: dict = None,
    buy_back=None,
    **ready_lot_kwargs,
) -> Scenario:
    """The canonical chain: a weighed, penned, ready lot hammered down to one
    approved bidder. Leaves the sale day in RINGING."""
    scn = setup_ready_lot(**ready_lot_kwargs)
    add_buyer(
        scn,
        bond_type=bond_type,
        credit_limit=credit_limit,
        buyer_party_overrides=buyer_party_overrides,
        **(registration_overrides or {}),
    )
    open_the_ring(scn)
    hammer_lot(scn, unit_price=unit_price, buy_back=buy_back)
    return scn


# ---------------------------------------------------------------------------
# Tier 4 — papers, trailers and the gate
# ---------------------------------------------------------------------------


def record_inspection(
    lot_id: str,
    inspection_type: str,
    issue_date: str,
    inspected_head: int = 10,
    result: str = "CLEARED",
    document_number: str = None,
    destination_state_code: str = None,
) -> dict:
    payload = create_inspection_record_payload(
        lot_id,
        inspection_type,
        issue_date=issue_date,
        inspected_head=inspected_head,
        document_number=document_number or f"{inspection_type}-0001",
    )
    if destination_state_code is not None:
        payload["destination_state_code"] = destination_state_code
    record = get_success_data(api_client.create_inspection_record(payload, INSPECTOR))
    if result is not None:
        record = get_success_data(
            api_client.result_inspection_record(record["id"], {"result": result}, INSPECTOR)
        )
    return record


def open_manifest(scn: Scenario, **overrides) -> Scenario:
    """Open a load manifest for the scenario's sale day under a fresh carrier."""
    if scn.get("carrier") is None:
        scn.carrier = create_carrier_party()
    scn.carrier_headers = make_carrier_headers(scn.carrier["id"])
    scn.manifest = get_success_data(
        api_client.create_load_manifest(
            create_load_manifest_payload(scn.sale_day["id"], scn.carrier["id"], **overrides),
            scn.carrier_headers,
        )
    )
    return scn


def add_lot_to_manifest(scn: Scenario, lot_id: str) -> dict:
    manifest = read_load_manifest(scn.manifest["id"])
    line = get_success_data(
        api_client.add_load_line(
            manifest["id"],
            {"lot_id": lot_id, "expected_load_manifest_version": manifest["version"]},
            scn.carrier_headers,
        )
    )
    scn.manifest = read_load_manifest(manifest["id"])
    return line


def dispatch_manifest(scn: Scenario) -> dict:
    scn.manifest = get_success_data(
        api_client.dispatch_load_manifest(scn.manifest["id"], scn.carrier_headers)
    )
    return scn.manifest


def load_and_dispatch(scn: Scenario, lot_id: str = None, **manifest_overrides) -> Scenario:
    """Put the scenario's lot on a trailer and roll the truck, leaving the lot
    in LOADED custody."""
    open_manifest(scn, **manifest_overrides)
    scn.load_line = add_lot_to_manifest(scn, lot_id or scn.lot["id"])
    dispatch_manifest(scn)
    scn.lot = read_lot(lot_id or scn.lot["id"])
    return scn


# ---------------------------------------------------------------------------
# Tier 5 — closing the day and the money tail
# ---------------------------------------------------------------------------


def close_day_and_settle(scn: Scenario, close_clock: str = "2026-06-02T10:00:00Z") -> Scenario:
    """Advance to BIDDING_CLOSED, move the clock and run the close cascade."""
    if read_sale_day(scn.sale_day["id"])["status"] == "RINGING":
        advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    if close_clock:
        set_clock(close_clock)
    scn.sale_day = close_sale_day(scn.sale_day["id"])
    scn.settlement = settlement_for_consignment(scn.consignment["id"])
    if scn.get("registration"):
        scn.invoice = invoice_for_registration(scn.registration["id"])
    scn.consignment = read_consignment(scn.consignment["id"])
    return scn


def setup_closed_day_with_settlement(
    close_clock: str = "2026-06-02T10:00:00Z", **sold_lot_kwargs
) -> Scenario:
    """One sold lot, the day closed, one settlement and one issued invoice."""
    scn = setup_sold_lot(**sold_lot_kwargs)
    return close_day_and_settle(scn, close_clock=close_clock)


def release_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.release_settlement(settlement_id, SETTLEMENT_CLERK))


def apply_payment(registration_id: str, invoice_id: str, amount) -> dict:
    return get_success_data(
        api_client.apply_payment(
            registration_id,
            {"buyer_invoice_id": invoice_id, "amount": amount},
            SETTLEMENT_CLERK,
        )
    )


def book_pen_move(lot_id: str, to_pen_id: str, crew_id: str, scheduled_start_at: str) -> dict:
    return get_success_data(
        api_client.create_pen_move(
            create_pen_move_payload(lot_id, to_pen_id, crew_id, scheduled_start_at),
            YARD_OPERATOR,
        )
    )


def set_pen_move_status(move_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.set_pen_move_status(move_id, {"to_status": to_status}, YARD_OPERATOR)
    )
