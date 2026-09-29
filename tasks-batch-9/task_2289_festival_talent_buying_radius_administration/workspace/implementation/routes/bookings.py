"""Booking reads, rider lines, countersignature, amendment and cancellation."""

from flask import Blueprint, g

from db import db, new_row, public, public_list, touch
from errors import fail
from middleware import endpoint, is_artist_rep, require_artist_scope
from response import paginate, respond_array, respond_object
from services import calc, derive
from validators import (
    body,
    check_version,
    load,
    opt_bool,
    opt_int,
    opt_string,
    pagination,
    query_enum,
    query_string,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("bookings", __name__)

CONTRACT_STATUSES = (
    "PENDING_RIDER",
    "RIDER_SETTLED",
    "COUNTERSIGNED",
    "CLOSED_OUT",
    "CANCELLED",
)
SETTLEMENT_STATUSES = (
    "UNFUNDED",
    "DEPOSIT_PAID",
    "BALANCE_DUE",
    "SETTLED",
    "WITHHELD",
    "RECOVERY_PENDING",
    "RECOVERED",
)
RIDER_CATEGORIES = ("TECHNICAL", "HOSPITALITY", "TRAVEL")
RIDER_STATUSES = ("PROPOSED", "APPROVED", "REJECTED", "SUBSTITUTED")
CANCELLING_PARTIES = ("ARTIST", "PROMOTER", "FORCE_MAJEURE")
ALL_READ_ROLES = [
    "TalentBuyer",
    "ArtistRep",
    "BusinessAffairs",
    "ProductionManager",
    "FinanceController",
]


def _booking_of(row):
    return db.bookings.get(row["booking_id"])


# --------------------------------------------------------------------------- #
# Booking reads
# --------------------------------------------------------------------------- #
@bp.get("/bookings/<booking_id>")
@endpoint(ALL_READ_ROLES)
def get_booking(booking_id):
    booking = load("bookings", booking_id)
    require_artist_scope(booking["artist_id"])
    return respond_object(public(booking))


@bp.get("/bookings")
@endpoint(ALL_READ_ROLES)
def list_bookings():
    festival_id = query_string("festival_id")
    artist_id = query_string("artist_id")
    offer_id = query_string("offer_id")
    budget_tier_id = query_string("budget_tier_id")
    stage_id = query_string("stage_id")
    replaces_booking_id = query_string("replaces_booking_id")
    wave_id = query_string("announcement_wave_id")
    contract_status = query_enum("contract_status", CONTRACT_STATUSES)
    settlement_status = query_enum("settlement_status", SETTLEMENT_STATUSES)
    limit, offset = pagination()

    rows = list(db.bookings.values())
    if is_artist_rep():
        rows = [r for r in rows if r["artist_id"] == g.user_id]
    if festival_id is not None:
        rows = [r for r in rows if r["festival_id"] == festival_id]
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if offer_id is not None:
        rows = [r for r in rows if r["offer_id"] == offer_id]
    if budget_tier_id is not None:
        rows = [r for r in rows if r["budget_tier_id"] == budget_tier_id]
    if stage_id is not None:
        rows = [r for r in rows if r["stage_id"] == stage_id]
    if replaces_booking_id is not None:
        rows = [r for r in rows if r["replaces_booking_id"] == replaces_booking_id]
    if wave_id is not None:
        rows = [r for r in rows if r["announcement_wave_id"] == wave_id]
    if contract_status is not None:
        rows = [r for r in rows if r["contract_status"] == contract_status]
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]

    rows = calc.sorted_rows(rows, [("slot_start_utc", False)])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.get("/bookings/<booking_id>/rider-estimate")
@endpoint(ALL_READ_ROLES)
def rider_estimate(booking_id):
    variant = query_enum(
        "variant", ("PROPOSED_SCOPE", "CONTRACTED_SCOPE", "BOTH")
    ) or "BOTH"
    booking = load("bookings", booking_id)
    require_artist_scope(booking["artist_id"])
    totals = calc.rider_totals(booking["id"])
    return respond_object(
        {
            "variant": variant,
            "proposed_scope_cents": totals["proposed_scope_cents"],
            "contracted_scope_cents": totals["contracted_scope_cents"],
            "variant_delta_cents": totals["proposed_scope_cents"]
            - totals["contracted_scope_cents"],
            "priced_line_count": totals["priced_line_count"],
            "capped_line_count": totals["capped_line_count"],
            "zeroed_line_count": totals["zeroed_line_count"],
        }
    )


@bp.get("/bookings/<booking_id>/settlement")
@endpoint(["TalentBuyer", "BusinessAffairs", "FinanceController"])
def booking_settlement(booking_id):
    booking = load("bookings", booking_id)
    return respond_object(calc.settlement_breakdown(booking))


# --------------------------------------------------------------------------- #
# Rider lines
# --------------------------------------------------------------------------- #
@bp.post("/bookings/<booking_id>/rider-items")
@endpoint(["ArtistRep"])
def create_rider_item(booking_id):
    payload = body()
    category = req_enum(payload, "category", RIDER_CATEGORIES)
    description = req_string(payload, "description", 1, 200)
    quantity = req_int(payload, "quantity", 1, 500)
    unit_cost_cents = req_int(payload, "unit_cost_cents", 0, None)
    is_promoter_provided = opt_bool(payload, "is_promoter_provided", False)

    booking = load("bookings", booking_id)
    require_artist_scope(booking["artist_id"])
    if booking["contract_status"] != "PENDING_RIDER":
        fail("ERR_INVALID_BOOKING_STATE", "rider lines close once the rider is settled")

    item = new_row(
        booking_id=booking["id"],
        category=category,
        description=description,
        quantity=quantity,
        unit_cost_cents=unit_cost_cents,
        is_promoter_provided=is_promoter_provided,
        approval_status="PROPOSED",
        substitute_unit_cost_cents=None,
        line_cost_cents=0,
    )
    item["line_cost_cents"] = calc.rider_line_cost(item)
    db.rider_items[item["id"]] = item

    derive.recompute_booking_money(booking)
    touch(booking)

    item["version"] = 1
    item["updated_at"] = item["created_at"]
    return respond_object(public(item), 201)


@bp.get("/bookings/<booking_id>/rider-items")
@endpoint(ALL_READ_ROLES)
def list_rider_items(booking_id):
    category = query_enum("category", RIDER_CATEGORIES)
    approval_status = query_enum("approval_status", RIDER_STATUSES)
    limit, offset = pagination()
    booking = load("bookings", booking_id)
    require_artist_scope(booking["artist_id"])

    rows = calc.booking_rider_items(booking["id"])
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if approval_status is not None:
        rows = [r for r in rows if r["approval_status"] == approval_status]
    rows = calc.sorted_rows(rows, [("category", False)])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.get("/rider-items/<item_id>")
@endpoint(["TalentBuyer", "ArtistRep", "BusinessAffairs", "ProductionManager"])
def get_rider_item(item_id):
    item = load("rider_items", item_id)
    booking = _booking_of(item)
    if booking is not None:
        require_artist_scope(booking["artist_id"])
    return respond_object(public(item))


@bp.post("/rider-items/<item_id>/decision")
@endpoint(["ProductionManager"])
def decide_rider_item(item_id):
    payload = body()
    decision = req_enum(payload, "decision", ("APPROVED", "REJECTED", "SUBSTITUTED"))
    substitute = opt_int(payload, "substitute_unit_cost_cents", None, 0, None)
    opt_string(payload, "decision_note", None, 1, None)
    if decision == "SUBSTITUTED" and substitute is None:
        fail(
            "ERR_INVALID_REQUEST",
            "substitute_unit_cost_cents is required for a substitution",
        )

    item = load("rider_items", item_id)
    if item["approval_status"] != "PROPOSED":
        fail("ERR_RIDER_ITEM_ALREADY_DECIDED", "this rider line is already decided")
    booking = _booking_of(item)
    if booking is None or booking["contract_status"] not in (
        "PENDING_RIDER",
        "RIDER_SETTLED",
    ):
        fail("ERR_INVALID_BOOKING_STATE", "the booking no longer accepts rider decisions")

    item["approval_status"] = decision
    if decision == "SUBSTITUTED":
        item["substitute_unit_cost_cents"] = substitute
    item["line_cost_cents"] = calc.rider_line_cost(item)
    touch(item)

    siblings = calc.booking_rider_items(booking["id"])
    still_proposed = any(r["approval_status"] == "PROPOSED" for r in siblings)
    changed = derive.recompute_booking_money(booking)
    if (
        not still_proposed
        and siblings
        and booking["contract_status"] == "PENDING_RIDER"
    ):
        booking["contract_status"] = "RIDER_SETTLED"
        changed = True
    if changed:
        touch(booking)
    return respond_object(public(item))


# --------------------------------------------------------------------------- #
# Countersignature
# --------------------------------------------------------------------------- #
@bp.post("/bookings/<booking_id>/countersign")
@endpoint(["BusinessAffairs"])
def countersign(booking_id):
    booking = load("bookings", booking_id)
    if booking["contract_status"] != "RIDER_SETTLED":
        fail("ERR_INVALID_BOOKING_STATE", "countersignature requires a settled rider")
    if any(
        c["enforcement_status"] == "BREACHED"
        for c in calc.clauses_for_booking(booking["id"])
    ):
        fail("ERR_RADIUS_BREACH_ACTIVE", "a breached radius clause blocks execution")
    if not any(
        p["status"] == "APPROVED" for p in calc.booking_advance_packets(booking["id"])
    ):
        fail("ERR_ADVANCE_NOT_APPROVED", "an approved technical advance is required")

    booking["contract_status"] = "COUNTERSIGNED"
    derive.recompute_booking_money(booking)
    touch(booking)
    return respond_object(public(booking))


# --------------------------------------------------------------------------- #
# Guarantee amendment
# --------------------------------------------------------------------------- #
@bp.patch("/bookings/<booking_id>/guarantee-amendment")
@endpoint(["TalentBuyer"])
def guarantee_amendment(booking_id):
    payload = body()
    guarantee_cents = req_int(payload, "guarantee_cents", 0, None)
    req_int(payload, "expected_booking_version")
    production_fee_cents = opt_int(payload, "production_fee_cents", None, 0, None)
    opt_string(payload, "amendment_reason", None, 1, None)

    booking = load("bookings", booking_id)
    check_version(
        payload, "expected_booking_version", booking, "ERR_STALE_BOOKING_VERSION"
    )
    if booking["contract_status"] in ("CANCELLED", "CLOSED_OUT"):
        fail("ERR_INVALID_BOOKING_STATE", "a closed booking cannot be amended")

    new_fee = (
        booking["production_fee_cents"]
        if production_fee_cents is None
        else production_fee_cents
    )
    old_total = booking["guarantee_cents"] + booking["production_fee_cents"]
    new_total = guarantee_cents + new_fee

    offer = db.offers.get(booking["offer_id"])
    ceiling = offer["guarantee_ceiling_cents"] if offer is not None else 0
    if new_total > ceiling:
        fail(
            "ERR_GUARANTEE_CEILING_EXCEEDED",
            "the amended terms exceed the stamped ceiling",
        )
    tier = db.budget_tiers.get(booking["budget_tier_id"])
    if tier is not None:
        if tier["committed_cents"] - old_total + new_total > tier["allocation_cents"]:
            fail(
                "ERR_TIER_ALLOCATION_EXCEEDED",
                "the amendment would overcommit the tier",
            )

    booking["guarantee_cents"] = guarantee_cents
    booking["production_fee_cents"] = new_fee
    festival = db.festivals.get(booking["festival_id"])
    derive.rebuild_schedule(booking, festival)
    derive.recompute_booking_money(booking)
    touch(booking)
    derive.reconcile_ledgers(booking)
    return respond_object(public(booking))


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #
@bp.post("/bookings/<booking_id>/cancel")
@endpoint(["TalentBuyer", "BusinessAffairs"])
def cancel_booking(booking_id):
    payload = body()
    cancelling_party = req_enum(payload, "cancelling_party", CANCELLING_PARTIES)
    cancellation_reason = req_string(payload, "cancellation_reason", 1, None)

    booking = load("bookings", booking_id)
    if booking["contract_status"] not in (
        "PENDING_RIDER",
        "RIDER_SETTLED",
        "COUNTERSIGNED",
    ):
        fail("ERR_INVALID_BOOKING_STATE", "this booking can no longer be cancelled")

    festival = db.festivals.get(booking["festival_id"])
    derive.cascade_cancel(booking, festival, cancelling_party, cancellation_reason)
    return respond_object(public(booking))
