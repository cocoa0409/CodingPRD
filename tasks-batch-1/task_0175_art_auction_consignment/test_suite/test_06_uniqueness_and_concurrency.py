"""Uniqueness partitions (lot_number per sale, one paddle per bidder per sale)
and optimistic-concurrency stale-version rejection on the two OCC-guarded
writes.
"""
from test_helpers import validate_error, validate_error_is_one_of, get_success_data
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    setup_base_scene, setup_open_lot, setup_sold_lot,
    create_seller, create_active_consignment, create_premium_schedule,
    create_cataloging_sale, create_bidder, register_paddle, place_bid,
    ADMIN, AUCTIONEER, FINANCE,
)
from test_helpers.factories import (
    create_lot_payload, create_paddle_registration_payload, FLAT_TIERS, STANDARD_TIERS,
)


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================
def test_duplicate_lot_number_in_sale_rejected(api):
    """PRD §3.3: "The `lot_number` must be unique among the non-withdrawn lots
    of the same sale; a collision yields `ERR_DUPLICATE`."

    A second non-withdrawn lot claiming lot_number 5 in the same sale collides.

    Design: Difficulty/resource_temporal_overlap/overlap_unique_lot_number_in_sale
    """
    scene = setup_base_scene(lot_number=5)
    sale_id = scene["sale"]["id"]
    cons_id = scene["consignment"]["id"]
    resp = api.create_lot(sale_id, create_lot_payload(cons_id, lot_number=5), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_distinct_lot_numbers_in_same_sale_allowed(api):
    """PRD §3.3: "The `lot_number` must be unique among the non-withdrawn lots
    of the same sale; a collision yields `ERR_DUPLICATE`."

    The uniqueness is scoped to a single lot_number slot: a different
    lot_number in the same sale is accepted, confirming the conflict is
    point-occupancy, not blanket.

    Design: Difficulty/resource_temporal_overlap/overlap_unique_lot_number_in_sale
    """
    scene = setup_base_scene(lot_number=5)
    sale_id = scene["sale"]["id"]
    cons_id = scene["consignment"]["id"]
    second = get_success_data(api.create_lot(sale_id, create_lot_payload(cons_id, lot_number=6), ADMIN))
    assert second["lot_number"] == 6
    assert second["sale_status"] == "CATALOGED"


def test_second_paddle_for_bidder_in_sale_rejected(api):
    """PRD §3.4: "A given bidder may hold only one paddle per sale; attempting
    to register the same bidder a second time for the same sale is rejected
    with `ERR_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/overlap_one_paddle_per_bidder_per_sale
    """
    schedule = create_premium_schedule(tiers=STANDARD_TIERS)
    bidder = create_bidder()
    sale = create_cataloging_sale(schedule["id"])
    register_paddle(sale["id"], bidder["id"], registration_type="FLOOR")
    resp = api.create_paddle_registration(
        create_paddle_registration_payload(sale["id"], bidder["id"], registration_type="PHONE"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_same_bidder_can_register_in_different_sales(api):
    """PRD §3.4: "A given bidder may hold only one paddle per sale; attempting
    to register the same bidder a second time for the same sale is rejected
    with `ERR_DUPLICATE`."

    The composite {auction_sale_id, bidder_id} partition means the same bidder
    may hold a paddle in each of two distinct sales without collision.

    Design: Difficulty/resource_temporal_overlap/overlap_one_paddle_per_bidder_per_sale
    """
    schedule = create_premium_schedule(tiers=STANDARD_TIERS)
    bidder = create_bidder()
    sale_a = create_cataloging_sale(schedule["id"])
    sale_b = create_cataloging_sale(schedule["id"])
    p_a = register_paddle(sale_a["id"], bidder["id"], registration_type="FLOOR")
    p_b = get_success_data(api.create_paddle_registration(
        create_paddle_registration_payload(sale_b["id"], bidder["id"], registration_type="FLOOR"),
        ADMIN))
    assert p_a["auction_sale_id"] == sale_a["id"]
    assert p_b["auction_sale_id"] == sale_b["id"]


# ===========================================================================
# Queue B — cross_cutting_complexity_layers (OCC)
# ===========================================================================
def test_stale_version_on_knockdown_rejected(api):
    """PRD §2.8: "Knocking a lot down requires `expected_lot_version` carrying
    the client's last observed `version` of the target `Lot`. If that value
    does not match the lot's current `version` — for instance because a further
    bid was accepted on the lot after the auctioneer read it, advancing the
    lot's version and raising the standing high — the knock-down is rejected
    with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_knockdown
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=1000000)
    lot_id = scene["lot"]["id"]
    paddle_id = scene["paddle"]["id"]
    place_bid(lot_id, paddle_id, 1100000)
    stale = get_success_data(api.get_lot(lot_id, AUCTIONEER))
    # A further accepted bid advances the lot version, making `stale` outdated.
    place_bid(lot_id, paddle_id, 1250000)
    resp = api.knock_down_lot(lot_id, {"expected_lot_version": stale["version"]}, AUCTIONEER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_version_on_second_invoice_rejected(api):
    """PRD §2.8: "Issuing the buyer invoice for a sold lot likewise requires
    `expected_lot_version` carrying the client's last observed `version` of the
    target `Lot`. If that value does not match the lot's current `version` —
    for instance because the lot's settlement dimension has already advanced
    (an invoice was already created, which legitimately supersedes a second
    attempt) — the invoice creation is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_invoice
    """
    scene = setup_sold_lot(hammer_cents=1250000, tiers=FLAT_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    pre = get_success_data(api.get_lot(lot_id, FINANCE))
    get_success_data(api.invoice_lot(lot_id, {"expected_lot_version": pre["version"]}, FINANCE))
    # Reuse the now-stale pre-invoice version for a second invoice attempt. The
    # first invoice advanced both the lot's settlement dimension (NONE ->
    # INVOICED, §3 line 176) and its version. The second attempt therefore
    # trips two checks at once: the single-entity state precondition
    # (settlement_status must be NONE, now INVOICED -> ERR_INVALID_STATE) and
    # the OCC version match (stale pre-invoice version -> ERR_STALE_VERSION).
    # PRD §2.8 narrates this scenario yielding ERR_STALE_VERSION, while §2.9
    # ranks ERR_INVALID_STATE strictly ahead of ERR_STALE_VERSION in the fixed
    # priority order; a PRD-faithful implementer may surface either, so accept
    # both.
    resp = api.invoice_lot(lot_id, {"expected_lot_version": pre["version"]}, FINANCE)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


def test_version_increments_on_mutation(api):
    """PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by exactly 1 on every mutation"
    PRD §3.2: "Activation ... increments the consignment's `version` by 1."

    A consignment's version is 1 on create and 2 after activate.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_mutation
    """
    seller = create_seller()
    cons = get_success_data(api.create_consignment(
        {"seller_id": seller["id"], "seller_commission_bps": 1000}, ADMIN))
    assert cons["version"] == 1
    activated = get_success_data(api.activate_consignment(
        cons["id"], {"expected_consignment_version": cons["version"]}, ADMIN))
    assert activated["version"] == 2
