"""Composite setup helpers for the heavy equipment auction platform.

Every test starts against an empty database, so each helper here builds its whole
precondition chain from PRD-declared endpoints only. The helpers are layered:

* single-step creators (``new_yard``, ``new_consignor``, ...) wrap one endpoint;
* stage builders (``catalog_ready_lot``, ``open_auction_with_catalogue``, ...) walk a
  multi-step lifecycle;
* scenario builders (``hammered_sale``, ``confirmed_invoice``, ``paid_invoice``,
  ``release_authorized_invoice``, ``booked_loadout_slot``, ``defaulted_invoice``,
  ``abandonment_ready_invoice``) reach the deep states that most assertions need.

Setup calls use the lenient success reader so a broken precondition surfaces as a
setup failure rather than as a confusing assertion inside the test body.

Identity threading: a Consignor acts under its own consignor id and a Bidder under
its own bidder id, so every ownership-gated call below uses the per-instance header
builders, never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    check_in_loadout_slot_payload,
    complete_loadout_slot_payload,
    counter_response_payload,
    counteroffer_payload,
    create_auction_payload,
    create_bid_payload,
    create_bidder_payload,
    create_bidder_registration_payload,
    create_condition_report_payload,
    create_consignment_payload,
    create_consignor_payload,
    create_consignor_settlement_payload,
    create_deposit_payload,
    create_export_packet_payload,
    create_loadout_bay_payload,
    create_loadout_slot_payload,
    create_lot_payload,
    create_payment_payload,
    create_refurbishment_order_payload,
    create_yard_payload,
    credit_decision_payload,
    export_packet_transition_payload,
    intake_decision_payload,
    lien_result_payload,
    lien_search_payload,
    lot_assignment_payload,
    next_serial_number,
    refurbishment_transition_payload,
)
from .constants import CLOCK_EPOCH
from .test_users import (
    TEST_USERS,
    make_bidder_headers,
    make_consignor_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["auction_operator_headers"]
INSPECTOR = TEST_USERS["intake_inspector_headers"]
SECOND_INSPECTOR = TEST_USERS["second_intake_inspector_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SETTLEMENT = TEST_USERS["settlement_officer_headers"]
SECOND_SETTLEMENT = TEST_USERS["second_settlement_officer_headers"]


# ===========================================================================
# Clock
# ===========================================================================

def set_clock(instant: str, api=api_client) -> dict:
    """Pin the logical clock to an exact instant."""
    return get_success_data(api.set_clock(instant, ADMIN))


def reset_clock(api=api_client) -> dict:
    """Pin the logical clock to the instant it reads before any administrative set."""
    return set_clock(CLOCK_EPOCH, api=api)


# ===========================================================================
# Single-step creators
# ===========================================================================

def new_yard(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_yard(create_yard_payload(**overrides), ADMIN))


def new_loadout_bay(yard_id: str, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_loadout_bay(create_loadout_bay_payload(yard_id, **overrides), ADMIN)
    )


def new_consignor(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_consignor(create_consignor_payload(**overrides), ADMIN)
    )


def new_consignment(consignor: dict, api=api_client, **overrides) -> dict:
    headers = make_consignor_headers(consignor["id"])
    return get_success_data(
        api.create_consignment(
            create_consignment_payload(consignor["id"], **overrides), headers
        )
    )


def new_lot(consignment: dict, consignor: dict, api=api_client, **overrides) -> dict:
    headers = make_consignor_headers(consignor["id"])
    overrides.setdefault("serial_number", next_serial_number())
    return get_success_data(
        api.create_lot(create_lot_payload(consignment["id"], **overrides), headers)
    )


def new_bidder(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_bidder(create_bidder_payload(**overrides), ADMIN)
    )


def new_auction(yard: dict, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_auction(create_auction_payload(yard["id"], **overrides), OPERATOR)
    )


# ===========================================================================
# Lot preparation: title, inspection, refurbishment, publication
# ===========================================================================

def clear_lot_title(lot: dict, api=api_client, reference: str = "LS-0001") -> dict:
    """Order the lien search and record a clean outcome, leaving the lot LIEN_CLEAR."""
    get_success_data(
        api.order_lien_search(lot["id"], lien_search_payload(lien_search_reference=reference), COMPLIANCE)
    )
    return get_success_data(
        api.record_lien_result(lot["id"], lien_result_payload(False), COMPLIANCE)
    )


def encumber_lot_title(
    lot: dict, api=api_client, lienholder_name: str = "First Equipment Bank"
) -> dict:
    """Order the lien search and record an encumbrance, leaving the lot LIEN_ENCUMBERED."""
    get_success_data(
        api.order_lien_search(lot["id"], lien_search_payload(), COMPLIANCE)
    )
    return get_success_data(
        api.record_lien_result(
            lot["id"], lien_result_payload(True, lienholder_name=lienholder_name), COMPLIANCE
        )
    )


def file_condition_report(
    lot: dict, api=api_client, inspector_headers=None, **overrides
) -> dict:
    """File a condition report against the lot, advancing it INTAKE -> INSPECTED."""
    overrides.setdefault("observed_hour_meter_reading", lot["hour_meter_reading"])
    return get_success_data(
        api.create_condition_report(
            lot["id"],
            create_condition_report_payload(**overrides),
            inspector_headers or INSPECTOR,
        )
    )


def publish_condition_report(report: dict, api=api_client, inspector_headers=None) -> dict:
    """Publish the report, advancing the lot INSPECTED -> CATALOG_READY."""
    return get_success_data(
        api.publish_condition_report(report["id"], inspector_headers or INSPECTOR)
    )


def completed_refurbishment_order(
    lot: dict,
    api=api_client,
    estimated_cost_cents: int = 300_000,
    actual_cost_cents: int = 300_000,
    qa_headers=None,
) -> dict:
    """Open a refurbishment order on an INSPECTED lot and walk it to COMPLETED.

    QA pass is signed by a different inspector identity than the one that authored the
    lot's condition report, as separation of duties requires.
    """
    order = get_success_data(
        api.create_refurbishment_order(
            create_refurbishment_order_payload(
                lot["id"], estimated_cost_cents=estimated_cost_cents
            ),
            INSPECTOR,
        )
    )
    get_success_data(
        api.transition_refurbishment_order(
            order["id"], refurbishment_transition_payload("START"), INSPECTOR
        )
    )
    get_success_data(
        api.transition_refurbishment_order(
            order["id"],
            refurbishment_transition_payload(
                "SUBMIT_QA", actual_cost_cents=actual_cost_cents
            ),
            INSPECTOR,
        )
    )
    return get_success_data(
        api.transition_refurbishment_order(
            order["id"],
            refurbishment_transition_payload("QA_PASS"),
            qa_headers or SECOND_INSPECTOR,
        )
    )


# ===========================================================================
# Tier 2: a consignment whose single lot is ready for the catalogue
# ===========================================================================

def catalog_ready_lot(
    api=api_client,
    yard=None,
    consignor=None,
    consignment=None,
    yard_overrides=None,
    consignor_overrides=None,
    consignment_overrides=None,
    lot_overrides=None,
    report_overrides=None,
    clear_title=True,
    set_epoch=True,
) -> dict:
    """Build yard -> consignor -> consignment -> lot -> submit -> accept -> inspect ->
    publish, leaving the lot CATALOG_READY and the consignment CATALOGED.

    Returns a dict with ``yard``, ``consignor``, ``consignor_headers``, ``consignment``,
    ``lot`` and ``report``.
    """
    if set_epoch:
        reset_clock(api=api)
    yard = yard or new_yard(api=api, **(yard_overrides or {}))
    consignor = consignor or new_consignor(api=api, **(consignor_overrides or {}))
    consignor_headers = make_consignor_headers(consignor["id"])
    consignment = consignment or new_consignment(
        consignor, api=api, **(consignment_overrides or {})
    )
    lot = new_lot(consignment, consignor, api=api, **(lot_overrides or {}))

    get_success_data(api.submit_consignment(consignment["id"], consignor_headers))
    get_success_data(
        api.decide_consignment_intake(
            consignment["id"], intake_decision_payload("ACCEPT"), OPERATOR
        )
    )
    if clear_title:
        clear_lot_title(lot, api=api)
    report = file_condition_report(lot, api=api, **(report_overrides or {}))
    publish_condition_report(report, api=api)

    return {
        "yard": yard,
        "consignor": consignor,
        "consignor_headers": consignor_headers,
        "consignment": consignment,
        "lot": get_success_data(api.get_lot(lot["id"], OPERATOR)),
        "report": get_success_data(api.get_condition_report(report["id"], OPERATOR)),
    }


def catalog_ready_batch(
    lot_specs,
    api=api_client,
    yard_overrides=None,
    consignor_overrides=None,
    consignment_overrides=None,
    report_overrides=None,
    set_epoch=True,
    publish_count: int = None,
) -> dict:
    """Same as :func:`catalog_ready_lot` but for several lots in one consignment.

    ``lot_specs`` is a list of per-lot override dicts. Returns ``yard``, ``consignor``,
    ``consignor_headers``, ``consignment``, ``lots`` and ``reports``.

    ``publish_count`` publishes only the reports of the first N lots, which leaves the
    consignment short of the bubble-up condition; the default publishes every report.
    """
    if set_epoch:
        reset_clock(api=api)
    yard = new_yard(api=api, **(yard_overrides or {}))
    consignor = new_consignor(api=api, **(consignor_overrides or {}))
    consignor_headers = make_consignor_headers(consignor["id"])
    consignment = new_consignment(consignor, api=api, **(consignment_overrides or {}))

    lots = [new_lot(consignment, consignor, api=api, **spec) for spec in lot_specs]

    get_success_data(api.submit_consignment(consignment["id"], consignor_headers))
    get_success_data(
        api.decide_consignment_intake(
            consignment["id"], intake_decision_payload("ACCEPT"), OPERATOR
        )
    )
    to_publish = len(lots) if publish_count is None else publish_count
    reports = []
    for index, lot in enumerate(lots):
        clear_lot_title(lot, api=api, reference=f"LS-{index + 1:04d}")
        report = file_condition_report(lot, api=api, **(report_overrides or {}))
        if index < to_publish:
            publish_condition_report(report, api=api)
        reports.append(get_success_data(api.get_condition_report(report["id"], OPERATOR)))

    return {
        "yard": yard,
        "consignor": consignor,
        "consignor_headers": consignor_headers,
        "consignment": get_success_data(api.get_consignment(consignment["id"], OPERATOR)),
        "lots": [get_success_data(api.get_lot(lot["id"], OPERATOR)) for lot in lots],
        "reports": reports,
    }


# ===========================================================================
# Buyer admission
# ===========================================================================

def funded_bidder(
    deposit_cents: int, api=api_client, reference: str = "WIRE-1", **bidder_overrides
) -> dict:
    """Register a bidder and record a deposit, so the cash is available to hold."""
    bidder = new_bidder(api=api, **bidder_overrides)
    get_success_data(
        api.create_deposit(
            bidder["id"], create_deposit_payload(deposit_cents, reference=reference), SETTLEMENT
        )
    )
    return get_success_data(api.get_bidder(bidder["id"], SETTLEMENT))


def pending_registration(
    bidder: dict,
    auction: dict,
    deposit_hold_cents: int,
    api=api_client,
    financing_requested: bool = False,
    **registration_overrides,
) -> dict:
    """Create a registration and stop there, so it stays in its initial requested state
    with the deposit already held but no credit decision recorded."""
    return get_success_data(
        api.create_bidder_registration(
            create_bidder_registration_payload(
                bidder["id"],
                auction["id"],
                deposit_hold_cents,
                financing_requested=financing_requested,
                **registration_overrides,
            ),
            make_bidder_headers(bidder["id"]),
        )
    )


def approved_registration(
    bidder: dict,
    auction: dict,
    deposit_hold_cents: int,
    api=api_client,
    financing_requested: bool = False,
    approved_credit_limit_cents: int = 0,
    credit_headers=None,
    **registration_overrides,
) -> dict:
    """Create a registration for the bidder at the auction and approve its credit."""
    bidder_headers = make_bidder_headers(bidder["id"])
    registration = get_success_data(
        api.create_bidder_registration(
            create_bidder_registration_payload(
                bidder["id"],
                auction["id"],
                deposit_hold_cents,
                financing_requested=financing_requested,
                **registration_overrides,
            ),
            bidder_headers,
        )
    )
    get_success_data(
        api.decide_credit(
            registration["id"],
            credit_decision_payload(
                "APPROVE", approved_credit_limit_cents=approved_credit_limit_cents
            ),
            credit_headers or SETTLEMENT,
        )
    )
    return get_success_data(api.get_bidder_registration(registration["id"], SETTLEMENT))


# ===========================================================================
# Tier 3: an open auction holding a catalogued lot, with an approved paddle
# ===========================================================================

def open_auction_with_catalogue(
    api=api_client,
    yard_overrides=None,
    consignor_overrides=None,
    consignment_overrides=None,
    lot_overrides=None,
    report_overrides=None,
    auction_overrides=None,
    bidder_overrides=None,
    deposit_cents: int = 1_500_000,
    deposit_hold_cents: int = 1_500_000,
    financing_requested: bool = False,
    approved_credit_limit_cents: int = 0,
    open_clock: str = None,
    open_now: bool = True,
    approve_credit: bool = True,
) -> dict:
    """Full chain from reference data through to an OPEN auction with one ASSIGNED lot
    and one APPROVED paddle.

    Returns everything built along the way: ``yard``, ``consignor``,
    ``consignor_headers``, ``consignment``, ``lot``, ``report``, ``auction``,
    ``bidder``, ``bidder_headers`` and ``registration``.
    """
    stage = catalog_ready_lot(
        api=api,
        yard_overrides=yard_overrides,
        consignor_overrides=consignor_overrides,
        consignment_overrides=consignment_overrides,
        lot_overrides=lot_overrides,
        report_overrides=report_overrides,
    )
    auction = new_auction(stage["yard"], api=api, **(auction_overrides or {}))
    get_success_data(
        api.assign_lot_to_auction(
            auction["id"], lot_assignment_payload(stage["lot"]["id"]), OPERATOR
        )
    )
    bidder = funded_bidder(deposit_cents, api=api, **(bidder_overrides or {}))
    if approve_credit:
        registration = approved_registration(
            bidder,
            auction,
            deposit_hold_cents,
            api=api,
            financing_requested=financing_requested,
            approved_credit_limit_cents=approved_credit_limit_cents,
        )
    else:
        registration = pending_registration(
            bidder,
            auction,
            deposit_hold_cents,
            api=api,
            financing_requested=financing_requested,
        )
    if open_now:
        get_success_data(api.open_auction(auction["id"], OPERATOR))
    if open_clock:
        set_clock(open_clock, api=api)

    stage.update(
        {
            "auction": get_success_data(api.get_auction(auction["id"], OPERATOR)),
            "bidder": get_success_data(api.get_bidder(bidder["id"], SETTLEMENT)),
            "bidder_headers": make_bidder_headers(bidder["id"]),
            "registration": registration,
            "lot": get_success_data(api.get_lot(stage["lot"]["id"], OPERATOR)),
        }
    )
    return stage


def open_auction_with_catalogue_batch(
    lot_specs,
    api=api_client,
    yard_overrides=None,
    consignor_overrides=None,
    consignment_overrides=None,
    report_overrides=None,
    auction_overrides=None,
    bidder_overrides=None,
    deposit_cents: int = 1_500_000,
    deposit_hold_cents: int = 1_500_000,
    financing_requested: bool = False,
    approved_credit_limit_cents: int = 0,
    open_clock: str = None,
    assign_lots=None,
) -> dict:
    """Multi-lot variant: every lot of the batch is assigned to one auction, then the
    auction is opened and one paddle is approved."""
    stage = catalog_ready_batch(
        lot_specs,
        api=api,
        yard_overrides=yard_overrides,
        consignor_overrides=consignor_overrides,
        consignment_overrides=consignment_overrides,
        report_overrides=report_overrides,
    )
    auction = new_auction(stage["yard"], api=api, **(auction_overrides or {}))
    to_assign = stage["lots"] if assign_lots is None else assign_lots
    for lot in to_assign:
        get_success_data(
            api.assign_lot_to_auction(
                auction["id"], lot_assignment_payload(lot["id"]), OPERATOR
            )
        )
    bidder = funded_bidder(deposit_cents, api=api, **(bidder_overrides or {}))
    registration = approved_registration(
        bidder,
        auction,
        deposit_hold_cents,
        api=api,
        financing_requested=financing_requested,
        approved_credit_limit_cents=approved_credit_limit_cents,
    )
    get_success_data(api.open_auction(auction["id"], OPERATOR))
    if open_clock:
        set_clock(open_clock, api=api)

    stage.update(
        {
            "auction": get_success_data(api.get_auction(auction["id"], OPERATOR)),
            "bidder": get_success_data(api.get_bidder(bidder["id"], SETTLEMENT)),
            "bidder_headers": make_bidder_headers(bidder["id"]),
            "registration": registration,
            "lots": [get_success_data(api.get_lot(l["id"], OPERATOR)) for l in stage["lots"]],
        }
    )
    return stage


# ===========================================================================
# Bidding and hammering
# ===========================================================================

def place_bid(registration: dict, lot: dict, amount_cents: int, bidder: dict, api=api_client):
    """Place one bid under the owning bidder's identity. Returns the raw response."""
    return api.create_bid(
        create_bid_payload(registration["id"], lot["id"], amount_cents),
        make_bidder_headers(bidder["id"]),
    )


def bid_and_hammer(
    registration: dict, lot: dict, amount_cents: int, bidder: dict, api=api_client
) -> dict:
    """Place a winning bid and hammer the lot. Returns the created sale."""
    get_success_data(place_bid(registration, lot, amount_cents, bidder, api=api))
    return get_success_data(api.hammer_lot(lot["id"], OPERATOR))


def find_invoice_for_sale(sale_id: str, api=api_client) -> dict:
    """Read back the invoice the server minted for a confirmed sale."""
    body = get_success_data(api.list_invoices(SETTLEMENT, params={"sale_id": sale_id}))
    rows = body if isinstance(body, list) else body.get("data", body)
    assert rows, f"expected an invoice for sale {sale_id}, found none"
    return get_success_data(api.get_invoice(rows[0]["id"], SETTLEMENT))


# ===========================================================================
# Tier 3/4: a hammered sale and its invoice
# ===========================================================================

def hammered_sale(
    api=api_client,
    bid_amount_cents: int = 12_000_000,
    hammer_clock: str = "2026-08-10T16:00:00Z",
    **stage_overrides,
) -> dict:
    """Walk the whole chain to a hammered lot. Adds ``sale`` to the stage dict."""
    stage = open_auction_with_catalogue(api=api, open_clock=hammer_clock, **stage_overrides)
    sale = bid_and_hammer(
        stage["registration"], stage["lot"], bid_amount_cents, stage["bidder"], api=api
    )
    stage["sale"] = get_success_data(api.get_sale(sale["id"], OPERATOR))
    stage["lot"] = get_success_data(api.get_lot(stage["lot"]["id"], OPERATOR))
    return stage


def confirmed_invoice(
    api=api_client,
    bid_amount_cents: int = 12_000_000,
    hammer_clock: str = "2026-08-10T16:00:00Z",
    **stage_overrides,
) -> dict:
    """A hammer above reserve, so the sale is CONFIRMED and its provisional invoice
    exists. Adds ``sale`` and ``invoice`` to the stage dict."""
    stage = hammered_sale(
        api=api,
        bid_amount_cents=bid_amount_cents,
        hammer_clock=hammer_clock,
        **stage_overrides,
    )
    stage["invoice"] = find_invoice_for_sale(stage["sale"]["id"], api=api)
    return stage


def sequential_sales_batch(
    lot_specs,
    bid_amounts,
    hammer_clocks,
    api=api_client,
    place_all_bids_first: bool = True,
    **stage_overrides,
) -> dict:
    """Several lots of one consignment sold one after another on the same auction.

    ``bid_amounts`` and ``hammer_clocks`` are positionally aligned with ``lot_specs``; a
    ``None`` bid amount leaves that lot unbid. Every bid is placed while the ring is still
    empty of hammers by default, because a hammer immediately consumes the paddle's
    headroom and would otherwise refuse the later bids.

    Adds ``sales`` and ``invoices`` (``None`` where no invoice was minted) to the stage.
    """
    stage = open_auction_with_catalogue_batch(
        lot_specs, api=api, open_clock=hammer_clocks[0], **stage_overrides
    )
    lots = stage["lots"]
    if place_all_bids_first:
        for lot, amount in zip(lots, bid_amounts):
            if amount is not None:
                get_success_data(
                    place_bid(stage["registration"], lot, amount, stage["bidder"], api=api)
                )

    sales, invoices = [], []
    for index, lot in enumerate(lots):
        clock = hammer_clocks[index]
        if clock:
            set_clock(clock, api=api)
        if not place_all_bids_first and bid_amounts[index] is not None:
            get_success_data(
                place_bid(
                    stage["registration"], lot, bid_amounts[index], stage["bidder"], api=api
                )
            )
        if bid_amounts[index] is None:
            sales.append(None)
            invoices.append(None)
            continue
        sale = get_success_data(api.hammer_lot(lot["id"], OPERATOR))
        sales.append(get_success_data(api.get_sale(sale["id"], OPERATOR)))
        body = get_success_data(api.list_invoices(SETTLEMENT, params={"sale_id": sale["id"]}))
        rows = body if isinstance(body, list) else body.get("data", body)
        invoices.append(
            get_success_data(api.get_invoice(rows[0]["id"], SETTLEMENT)) if rows else None
        )

    stage["sales"] = sales
    stage["invoices"] = invoices
    stage["lots"] = [get_success_data(api.get_lot(l["id"], OPERATOR)) for l in lots]
    return stage


def multi_lot_release_authorized(
    lot_specs, bid_amounts, hammer_clocks, api=api_client, **stage_overrides
) -> dict:
    """Every invoice of a multi-lot sale run paid in full and moved to
    ``RELEASE_AUTHORIZED``, which is the state a load-out booking requires."""
    stage = sequential_sales_batch(
        lot_specs, bid_amounts, hammer_clocks, api=api, **stage_overrides
    )
    refreshed = []
    for invoice in stage["invoices"]:
        if invoice is None:
            refreshed.append(None)
            continue
        pay_invoice_in_full(
            invoice, stage["bidder"], api=api, currency_code=stage["yard"]["currency_code"]
        )
        get_success_data(api.authorize_release(invoice["id"], SETTLEMENT))
        refreshed.append(get_success_data(api.get_invoice(invoice["id"], SETTLEMENT)))
    stage["invoices"] = refreshed
    return stage


def provisional_sale_below_reserve(
    api=api_client,
    reserve_price_cents: int = 15_000_000,
    bid_amount_cents: int = 12_000_000,
    hammer_clock: str = "2026-08-10T16:00:00Z",
    **stage_overrides,
) -> dict:
    """A hammer that missed the lot's reserve, leaving the sale PROVISIONAL with no
    invoice. Adds ``sale`` to the stage dict."""
    lot_overrides = dict(stage_overrides.pop("lot_overrides", None) or {})
    lot_overrides["reserve_price_cents"] = reserve_price_cents
    return hammered_sale(
        api=api,
        bid_amount_cents=bid_amount_cents,
        hammer_clock=hammer_clock,
        lot_overrides=lot_overrides,
        **stage_overrides,
    )


def countered_sale(
    api=api_client,
    counter_price_cents: int = 14_000_000,
    reserve_price_cents: int = 15_000_000,
    bid_amount_cents: int = 12_000_000,
    **stage_overrides,
) -> dict:
    """A provisional sale that the seller has countered once, so the sale is
    CONSIGNOR_COUNTERED at ``counter_round`` 1."""
    stage = provisional_sale_below_reserve(
        api=api,
        reserve_price_cents=reserve_price_cents,
        bid_amount_cents=bid_amount_cents,
        **stage_overrides,
    )
    sale = stage["sale"]
    get_success_data(
        api.counteroffer_sale(
            sale["id"],
            counteroffer_payload(counter_price_cents, sale["version"]),
            stage["consignor_headers"],
        )
    )
    stage["sale"] = get_success_data(api.get_sale(sale["id"], OPERATOR))
    return stage


def counter_accepted_invoice(
    api=api_client, counter_price_cents: int = 14_000_000, **stage_overrides
) -> dict:
    """The buyer accepts the seller's counteroffer, confirming the sale and minting the
    invoice at the countered price."""
    stage = countered_sale(api=api, counter_price_cents=counter_price_cents, **stage_overrides)
    get_success_data(
        api.respond_to_counteroffer(
            stage["sale"]["id"], counter_response_payload("ACCEPT"), stage["bidder_headers"]
        )
    )
    stage["sale"] = get_success_data(api.get_sale(stage["sale"]["id"], OPERATOR))
    stage["invoice"] = find_invoice_for_sale(stage["sale"]["id"], api=api)
    return stage


# ===========================================================================
# Money: paying, finalising, release
# ===========================================================================

def pay_invoice_in_full(invoice: dict, bidder: dict, api=api_client, currency_code="USD") -> dict:
    """Tender exactly the invoice's outstanding balance. Returns the refreshed invoice."""
    outstanding = invoice["outstanding_cents"]
    get_success_data(
        api.create_payment(
            create_payment_payload(invoice["id"], outstanding, currency_code=currency_code),
            make_bidder_headers(bidder["id"]),
        )
    )
    return get_success_data(api.get_invoice(invoice["id"], SETTLEMENT))


def paid_invoice(api=api_client, **stage_overrides) -> dict:
    """A confirmed sale whose invoice has been settled in one instrument."""
    stage = confirmed_invoice(api=api, **stage_overrides)
    stage["invoice"] = pay_invoice_in_full(
        stage["invoice"], stage["bidder"], api=api,
        currency_code=stage["yard"]["currency_code"],
    )
    return stage


def cleared_export_packet(invoice: dict, destination_country_code: str, api=api_client) -> dict:
    """Open an export packet on a cross-border invoice and walk it to EXPORT_CLEARED."""
    packet = get_success_data(
        api.create_export_packet(
            create_export_packet_payload(invoice["id"], destination_country_code), COMPLIANCE
        )
    )
    get_success_data(
        api.transition_export_packet(
            packet["id"],
            export_packet_transition_payload("ATTACH_TITLE", title_document_ref="TTL-0001"),
            COMPLIANCE,
        )
    )
    get_success_data(
        api.transition_export_packet(
            packet["id"],
            export_packet_transition_payload("FILE_CUSTOMS", customs_entry_ref="CST-0001"),
            COMPLIANCE,
        )
    )
    return get_success_data(
        api.transition_export_packet(
            packet["id"], export_packet_transition_payload("CLEAR"), COMPLIANCE
        )
    )


def release_authorized_invoice(
    api=api_client, settle_consignor: bool = True, **stage_overrides
) -> dict:
    """A paid, domestic invoice whose custody axis has been moved to RELEASE_AUTHORIZED.

    When ``settle_consignor`` is true the seller settlement is posted first, which moves
    the sale to SETTLED and the lot to SETTLED — the state load-out completion needs.
    """
    stage = paid_invoice(api=api, **stage_overrides)
    if settle_consignor:
        stage["settlement"] = get_success_data(
            api.create_consignor_settlement(
                create_consignor_settlement_payload(stage["sale"]["id"]), SETTLEMENT
            )
        )
    get_success_data(api.authorize_release(stage["invoice"]["id"], SETTLEMENT))
    stage["invoice"] = get_success_data(api.get_invoice(stage["invoice"]["id"], SETTLEMENT))
    stage["sale"] = get_success_data(api.get_sale(stage["sale"]["id"], OPERATOR))
    stage["lot"] = get_success_data(api.get_lot(stage["lot"]["id"], OPERATOR))
    return stage


# ===========================================================================
# Tier 5: load-out
# ===========================================================================

def booked_loadout_slot(
    api=api_client,
    bay_overrides=None,
    slot_start: str = "2026-08-11T08:00:00Z",
    slot_end: str = "2026-08-11T10:00:00Z",
    tonnage_kg: int = None,
    transport_mode: str = "HOUSE_BROKERED",
    **stage_overrides,
) -> dict:
    """A release-authorised invoice with one BOOKED load-out slot in a bay at the
    selling yard. Adds ``bay`` and ``slot`` to the stage dict."""
    stage = release_authorized_invoice(api=api, **stage_overrides)
    bay = new_loadout_bay(stage["yard"]["id"], api=api, **(bay_overrides or {}))
    invoice = stage["invoice"]
    payload_tonnage = stage["lot"]["weight_kg"] if tonnage_kg is None else tonnage_kg
    slot = get_success_data(
        api.create_loadout_slot(
            create_loadout_slot_payload(
                invoice["id"],
                bay["id"],
                invoice["version"],
                slot_start,
                slot_end,
                payload_tonnage,
                transport_mode=transport_mode,
            ),
            stage["bidder_headers"],
        )
    )
    stage["bay"] = get_success_data(api.get_loadout_bay(bay["id"], ADMIN))
    stage["slot"] = slot
    stage["invoice"] = get_success_data(api.get_invoice(invoice["id"], SETTLEMENT))
    return stage


def checked_in_loadout_slot(api=api_client, check_in_clock: str = None, **kwargs) -> dict:
    """A booked slot whose transporter has arrived inside the slot window."""
    stage = booked_loadout_slot(api=api, **kwargs)
    set_clock(check_in_clock or stage["slot"]["slot_start"], api=api)
    stage["slot"] = get_success_data(
        api.check_in_loadout_slot(
            stage["slot"]["id"], check_in_loadout_slot_payload(), stage["bidder_headers"]
        )
    )
    return stage


def completed_loadout_slot(api=api_client, **kwargs) -> dict:
    """A checked-in slot closed out against a gate pass, releasing the machine."""
    stage = checked_in_loadout_slot(api=api, **kwargs)
    stage["slot"] = get_success_data(
        api.complete_loadout_slot(
            stage["slot"]["id"], SETTLEMENT, complete_loadout_slot_payload()
        )
    )
    stage["invoice"] = get_success_data(api.get_invoice(stage["invoice"]["id"], SETTLEMENT))
    stage["lot"] = get_success_data(api.get_lot(stage["lot"]["id"], OPERATOR))
    return stage


# ===========================================================================
# Tier 5: default and abandonment
# ===========================================================================

def defaulted_invoice(
    api=api_client, default_clock: str = None, partial_payment_cents: int = None,
    **stage_overrides,
) -> dict:
    """A confirmed invoice pushed past ``payment_due_at`` and marked IN_DEFAULT.

    ``partial_payment_cents`` optionally tenders part of the balance first, so the
    deficiency calculation has cash to net off.
    """
    stage = confirmed_invoice(api=api, **stage_overrides)
    invoice = stage["invoice"]
    if partial_payment_cents:
        get_success_data(
            api.create_payment(
                create_payment_payload(
                    invoice["id"], partial_payment_cents,
                    currency_code=stage["yard"]["currency_code"],
                ),
                stage["bidder_headers"],
            )
        )
    set_clock(default_clock or "2026-09-30T16:00:00Z", api=api)
    stage["invoice"] = get_success_data(api.default_invoice(invoice["id"], SETTLEMENT))
    return stage


def settled_then_defaulted_invoice(
    api=api_client, default_clock: str = None, partial_payment_cents: int = None,
    **stage_overrides,
) -> dict:
    """A confirmed sale with a POSTED consignor settlement, whose invoice is then pushed
    into default — the precondition for the deepest abandonment cascade, where a
    settlement actually exists to reverse."""
    stage = confirmed_invoice(api=api, **stage_overrides)
    stage["settlement"] = get_success_data(
        api.create_consignor_settlement(
            create_consignor_settlement_payload(stage["sale"]["id"]), SETTLEMENT
        )
    )
    invoice = stage["invoice"]
    if partial_payment_cents:
        get_success_data(
            api.create_payment(
                create_payment_payload(
                    invoice["id"], partial_payment_cents,
                    currency_code=stage["yard"]["currency_code"],
                ),
                stage["bidder_headers"],
            )
        )
    set_clock(default_clock or "2026-09-30T16:00:00Z", api=api)
    stage["invoice"] = get_success_data(api.default_invoice(invoice["id"], SETTLEMENT))
    stage["sale"] = get_success_data(api.get_sale(stage["sale"]["id"], OPERATOR))
    # PRD 3.9: posting the settlement "moves the sale `CONFIRMED -> SETTLED` and the
    # lot `HAMMERED -> SETTLED`", so the staged lot must be re-read too.
    stage["lot"] = get_success_data(api.get_lot(stage["lot"]["id"], OPERATOR))
    return stage
