"""ResaleListing endpoints (PRD 3.5)."""
from flask import Blueprint, g, jsonify

import db
import engine
from auth import require, require_household_owner
from errors import (
    ApiError, ERR_EDUCATION_INCOMPLETE, ERR_FUNDS_NOT_CONFIRMED,
    ERR_HOUSEHOLD_INELIGIBLE, ERR_INVALID_STATE, ERR_NO_ELIGIBLE_BUYER,
    ERR_REFERENCE_NOT_FOUND, ERR_STALE_VERSION, ERR_UNIT_BLOCKED,
)
from scope import get_listing_or_404, get_program_or_404, get_unit_or_404
from util import (
    add_months, body, bump, new_entity, ok_object, paginated, query_str,
    req_int, req_str, ser_listing,
)

bp = Blueprint("resale", __name__)

LISTING_READ = ["PlatformAdmin", "ProgramAdmin", "ComplianceOfficer",
                "LeaseManager", "Household"]


@bp.post("/programs/<pid>/units/<uid>/resale-listings")
@require(["LeaseManager", "Household"])
def create_listing(pid, uid):
    program = get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    if program["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Program is not ACTIVE; new resale listings cannot be opened")
    data = body()
    seller_lease_id = req_str(data, "seller_lease_id")
    appraisal = req_int(data, "appraisal_at_listing_cents")

    lease = db.store.leases.get(seller_lease_id)
    if lease is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422,
                       "seller_lease_id does not resolve in this program scope")
    lease_unit = db.store.units.get(lease["unit_id"])
    if lease_unit is None or lease_unit["program_id"] != pid or lease["unit_id"] != uid:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422,
                       "seller_lease_id does not resolve in this program scope")

    # Household callers may only list their own leasehold.
    require_household_owner(lease["household_id"])

    seller = db.store.households.get(lease["household_id"])
    if seller is None or seller["eligibility_status"] != "ELIGIBLE":
        raise ApiError(ERR_HOUSEHOLD_INELIGIBLE, 409,
                       "Seller household must be ELIGIBLE to open a resale listing")
    if (unit["maintenance_flag"] == "UNSAFE"
            or unit["occupancy_status"] != "OCCUPIED"
            or lease["status"] != "ACTIVE"
            or unit["current_lease_id"] != lease["id"]):
        raise ApiError(ERR_UNIT_BLOCKED, 409,
                       "Unit is blocked from resale (UNSAFE flag, wrong occupancy, "
                       "or seller lease not active)")
    open_notices = [n for n in db.store.notices.values()
                    if n["lease_id"] == lease["id"] and n["status"] == "OPEN"]
    if open_notices:
        raise ApiError(ERR_UNIT_BLOCKED, 409,
                       "Seller lease has OPEN default notices")

    now = db.get_now()
    values = engine.compute_resale_values(program, unit, lease, appraisal, now)
    affordability = engine.compute_affordability_preserved(
        program, values["asking_price_cents"])

    listing = new_entity()
    listing.update({
        "unit_id": uid,
        "seller_lease_id": lease["id"],
        "listed_at": now,
        "appraisal_at_listing_cents": appraisal,
        "asking_price_cents": values["asking_price_cents"],
        "seller_proceeds_cents": values["seller_proceeds_cents"],
        "subsidy_retained_cents": values["subsidy_retained_cents"],
        "affordability_preserved": affordability,
        "status": "OPEN",
        "matched_waitlist_entry_id": None,
        "buyer_household_id": None,
    })
    db.store.listings[listing["id"]] = listing

    unit["occupancy_status"] = "LISTED_FOR_RESALE"
    unit["appraisal_value_cents"] = appraisal
    bump(unit)
    return jsonify(ok_object(ser_listing(listing))), 201


@bp.get("/programs/<pid>/units/<uid>/resale-listings")
@require(LISTING_READ)
def list_listings(pid, uid):
    get_unit_or_404(pid, uid)
    items = [l for l in db.store.listings.values() if l["unit_id"] == uid]
    status = query_str("status")
    if status:
        items = [l for l in items if l["status"] == status]
    return jsonify(paginated(items, ser_listing)), 200


@bp.get("/programs/<pid>/units/<uid>/resale-listings/<rid>")
@require(LISTING_READ)
def get_listing(pid, uid, rid):
    get_unit_or_404(pid, uid)
    return jsonify(ok_object(ser_listing(get_listing_or_404(pid, uid, rid)))), 200


def _eligible_candidates(pid, unit, listing):
    now = db.get_now()
    pool = []
    for entry in db.store.waitlist.values():
        if entry["status"] != "ACTIVE":
            continue
        household = db.store.households.get(entry["household_id"])
        if household is None or household["program_id"] != pid:
            continue
        if household["eligibility_status"] != "ELIGIBLE":
            continue
        if household["education_completed_at"] is None:
            continue
        if listing["asking_price_cents"] > entry["max_price_cents"]:
            continue
        if unit["bedrooms"] < entry["desired_bedrooms"]:
            continue
        pool.append(entry)
    return pool


@bp.post("/programs/<pid>/units/<uid>/resale-listings/<rid>/run-matching")
@require(["LeaseManager"])
def run_matching(pid, uid, rid):
    get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    listing = get_listing_or_404(pid, uid, rid)
    if listing["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OPEN listing can run matching")
    data = body()
    expected_listing_version = req_int(data, "expected_listing_version")

    if unit["maintenance_flag"] == "UNSAFE" or unit["occupancy_status"] != "LISTED_FOR_RESALE":
        raise ApiError(ERR_UNIT_BLOCKED, 409,
                       "Unit is blocked from matching (UNSAFE flag or wrong occupancy)")

    pool = _eligible_candidates(pid, unit, listing)
    if not pool:
        raise ApiError(ERR_NO_ELIGIBLE_BUYER, 422,
                       "No eligible waitlist entry matches this listing")

    if expected_listing_version != listing["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_listing_version does not match the listing's current version")

    now = db.get_now()
    ordered = sorted(pool, key=lambda e: (-engine.effective_score(e, unit),
                                          e["created_at"], e["id"]))
    winner = ordered[0]

    # Rank among all ACTIVE entries in the program (1 = highest priority).
    all_active = [e for e in db.store.waitlist.values()
                  if e["status"] == "ACTIVE"
                  and (db.store.households.get(e["household_id"]) or {}).get("program_id") == pid]
    ranked = sorted(all_active, key=lambda e: (-engine.effective_score(e, unit),
                                               e["created_at"], e["id"]))
    rank = next((i + 1 for i, e in enumerate(ranked) if e["id"] == winner["id"]), 1)

    winner["status"] = "MATCHED"
    winner["matched_at"] = now
    winner["matched_unit_id"] = uid
    winner["match_rank_at_match"] = rank
    bump(winner)

    listing["status"] = "MATCHED"
    listing["matched_waitlist_entry_id"] = winner["id"]
    listing["buyer_household_id"] = winner["household_id"]
    bump(listing)
    return jsonify(ok_object(ser_listing(listing))), 200


@bp.post("/programs/<pid>/units/<uid>/resale-listings/<rid>/open-contract")
@require(["LeaseManager"])
def open_contract(pid, uid, rid):
    get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    listing = get_listing_or_404(pid, uid, rid)
    if listing["status"] != "MATCHED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a MATCHED listing can open a purchase contract")
    data = body()
    expected_listing_version = req_int(data, "expected_listing_version")

    now = db.get_now()
    buyer = db.store.households.get(listing["buyer_household_id"])
    if buyer is None or buyer["eligibility_status"] != "ELIGIBLE":
        raise ApiError(ERR_HOUSEHOLD_INELIGIBLE, 409,
                       "Buyer household must still be ELIGIBLE")
    if unit["maintenance_flag"] == "UNSAFE":
        raise ApiError(ERR_UNIT_BLOCKED, 409, "Unit is UNSAFE")
    if (buyer["education_completed_at"] is None
            or not engine.required_courses_satisfied(pid, buyer["id"], now)):
        raise ApiError(ERR_EDUCATION_INCOMPLETE, 409,
                       "Buyer required education completions are missing or expired")

    if expected_listing_version != listing["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_listing_version does not match the listing's current version")

    listing["status"] = "UNDER_CONTRACT"
    bump(listing)
    unit["occupancy_status"] = "UNDER_CONTRACT"
    bump(unit)
    return jsonify(ok_object(ser_listing(listing))), 200


@bp.post("/programs/<pid>/units/<uid>/resale-listings/<rid>/close")
@require(["LeaseManager"])
def close_listing(pid, uid, rid):
    program = get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    listing = get_listing_or_404(pid, uid, rid)
    if listing["status"] != "UNDER_CONTRACT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an UNDER_CONTRACT listing can be closed")
    data = body()
    expected_listing_version = req_int(data, "expected_listing_version")
    confirmed_funds = data.get("confirmed_funds")
    if confirmed_funds is not True:
        raise ApiError(ERR_FUNDS_NOT_CONFIRMED, 402,
                       "Buyer purchase funds must be confirmed to close")
    if expected_listing_version != listing["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_listing_version does not match the listing's current version")

    now = db.get_now()

    # Seller lease terminates (resale path: resale_count increments).
    seller_lease = db.store.leases.get(listing["seller_lease_id"])
    if seller_lease is not None:
        seller_lease["status"] = "TERMINATED"
        seller_lease["resale_count"] += 1
        bump(seller_lease)
        seller = db.store.households.get(seller_lease["household_id"])
        if seller and seller["active_lease_id"] == seller_lease["id"]:
            seller["active_lease_id"] = None
            bump(seller)

    # Buyer waitlist entry is fulfilled.
    buyer_entry = db.store.waitlist.get(listing["matched_waitlist_entry_id"])
    if buyer_entry is not None and buyer_entry["status"] == "MATCHED":
        buyer_entry["status"] = "FULFILLED"
        bump(buyer_entry)
    buyer = db.store.households.get(listing["buyer_household_id"])
    if buyer and buyer_entry and buyer["waitlist_entry_id"] == buyer_entry["id"]:
        buyer["waitlist_entry_id"] = None
        bump(buyer)

    # Buyer successor lease is auto-created in DRAFT; the retained subsidy is
    # rolled into it and locked at activation.
    buyer_lease = new_entity()
    buyer_lease.update({
        "unit_id": uid,
        "household_id": listing["buyer_household_id"],
        "start_date": now,
        "end_date": add_months(now, program["ground_lease_term_years"] * 12),
        "monthly_fee_cents": None,
        "subsidy_locked_cents": None,
        "purchase_price_cents": listing["asking_price_cents"],
        "status": "DRAFT",
        "fee_arrears_cents": 0,
        "last_fee_charged_at": None,
        "resale_count": 0,
        "_pending_subsidy_cents": listing["subsidy_retained_cents"],
        "_purchase_appraisal_cents": None,
    })
    db.store.leases[buyer_lease["id"]] = buyer_lease

    listing["status"] = "CLOSED"
    bump(listing)

    unit["occupancy_status"] = "VACANT"
    unit["current_lease_id"] = None
    bump(unit)
    return jsonify(ok_object(ser_listing(listing))), 200


@bp.post("/programs/<pid>/units/<uid>/resale-listings/<rid>/cancel")
@require(["LeaseManager"])
def cancel_listing(pid, uid, rid):
    get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    listing = get_listing_or_404(pid, uid, rid)
    if listing["status"] not in ("OPEN", "MATCHED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OPEN or MATCHED listing can be cancelled")

    if listing["status"] == "MATCHED":
        entry = db.store.waitlist.get(listing["matched_waitlist_entry_id"])
        if entry is not None and entry["status"] == "MATCHED":
            entry["status"] = "ACTIVE"
            entry["matched_unit_id"] = None
            entry["matched_at"] = None
            entry["match_rank_at_match"] = None
            bump(entry)
        listing["matched_waitlist_entry_id"] = None
        listing["buyer_household_id"] = None

    listing["status"] = "CANCELLED"
    bump(listing)
    unit["occupancy_status"] = "OCCUPIED"
    bump(unit)
    return jsonify(ok_object(ser_listing(listing))), 200
