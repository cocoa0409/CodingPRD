"""Timber sales and bids: offering, bidding, evaluation, award, reoffer."""
from decimal import Decimal

from flask import Blueprint, g

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_int, f_enum, f_date, f_datetime, f_array, bad_request, err,
    paginate, get_tract, get_stand, get_prescription, get_sale, get_bid,
    get_cruise, is_int, is_num, D, rhu, check_transition, now, today,
    parse_date_str, parse_iso_datetime, add_months, now_iso, tract_of_sale,
)

bp = Blueprint("sales", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

SALE_TYPES = {"LUMP_SUM", "PER_UNIT"}
SCALING_RULES = {"DOYLE", "INTERNATIONAL_14"}
SALE_TERMINAL = {"AWARDED", "CANCELLED"}
BID_TERMINAL = {"WITHDRAWN", "DISQUALIFIED", "WINNING", "LOST", "SUPERSEDED"}

CRUISE_MAX_AGE_MONTHS = 24

BOND_FLOOR_CENTS = 500000
BOND_CAP_CENTS = 10000000


def _validate_rate_rows(rows, rate_key):
    for row in rows:
        if not isinstance(row, dict):
            bad_request("rate entries must be objects")
        check_known(row, {"species", rate_key})
        if not isinstance(row.get("species"), str):
            bad_request("rate entry species must be a string")
        if not is_int(row.get(rate_key)) or row.get(rate_key) < 0:
            bad_request("rate entry %s must be a non-negative integer"
                        % rate_key)


def _enrollment_conflict(tract, hw_start, hw_end):
    """Closed-interval day semantics: overlap iff harvest_start <=
    enrollment_end AND enrollment_start <= harvest_end."""
    if tract["status"] != "OPEN":
        return True
    es = tract.get("conservation_enrollment_start")
    ee = tract.get("conservation_enrollment_end")
    if not es or not ee:
        return False
    hs = parse_date_str(hw_start)
    he = parse_date_str(hw_end)
    return hs <= parse_date_str(ee) and parse_date_str(es) <= he


def performance_bond_amount(awarded_value_cents, prior_defaults):
    if awarded_value_cents <= 10000000:
        pct = Decimal("0.10")
    elif awarded_value_cents <= 50000000:
        pct = Decimal("0.07")
    else:
        pct = Decimal("0.05")
    amount = rhu(D(awarded_value_cents) * pct *
                 (Decimal("1") + Decimal("0.25") * D(prior_defaults)))
    return min(BOND_CAP_CENTS, max(BOND_FLOOR_CENTS, amount))


@bp.route("/forestry/sales", methods=["POST"])
@require_roles("Forester")
def create_sale():
    body = get_body()
    # referenced-resource existence, left to right: tract, stand, prescription
    tr = body.get("tract_id")
    if isinstance(tr, str):
        get_tract(tr)
    st = body.get("stand_id")
    if isinstance(st, str):
        get_stand(st)
    pr = body.get("prescription_id")
    if isinstance(pr, str):
        get_prescription(pr)
    check_known(body, {"tract_id", "stand_id", "prescription_id", "sale_type",
                       "scaling_rule", "advertised_minimum_cents",
                       "species_minimum_rates", "bid_open_at", "bid_close_at",
                       "harvest_window_start", "harvest_window_end"})
    tract_id = f_str(body, "tract_id")
    tract = get_tract(tract_id)
    stand_id = f_str(body, "stand_id")
    stand = get_stand(stand_id)
    prescription_id = f_str(body, "prescription_id")
    prescription = get_prescription(prescription_id)
    sale_type = f_enum(body, "sale_type", SALE_TYPES)
    scaling_rule = f_enum(body, "scaling_rule", SCALING_RULES)
    advertised = f_int(body, "advertised_minimum_cents", minv=0)
    raw_rates = body.get("species_minimum_rates")
    if raw_rates is not None:
        if not isinstance(raw_rates, list):
            bad_request("species_minimum_rates must be an array")
        _validate_rate_rows(raw_rates, "min_rate_cents_per_mbf")
    bid_open = f_datetime(body, "bid_open_at")
    bid_close = f_datetime(body, "bid_close_at")
    if parse_iso_datetime(bid_close) <= parse_iso_datetime(bid_open):
        bad_request("bid_close_at must be after bid_open_at")
    hw_start = f_date(body, "harvest_window_start")
    hw_end = f_date(body, "harvest_window_end")
    if parse_date_str(hw_end) <= parse_date_str(hw_start):
        bad_request("harvest_window_end must be after harvest_window_start")
    # structural: geometry agreement
    if prescription["stand_id"] != stand_id or stand["tract_id"] != tract_id:
        err("ERR_SALE_PRESCRIPTION_STAND_MISMATCH", 422,
            "sale stand/tract do not match the prescription")
    # per-species floor rates required iff PER_UNIT
    if sale_type == "PER_UNIT":
        if raw_rates is None:
            err("ERR_SPECIES_RATE_MISSING", 422,
                "PER_UNIT sale requires species_minimum_rates")
        species_minimum_rates = raw_rates
    else:
        if raw_rates is not None:
            err("ERR_SPECIES_RATE_MISSING", 422,
                "LUMP_SUM sale must not carry species_minimum_rates")
        species_minimum_rates = None
    ent = new_common({
        "tract_id": tract_id,
        "stand_id": stand_id,
        "prescription_id": prescription_id,
        "sale_type": sale_type,
        "scaling_rule": scaling_rule,
        "advertised_minimum_cents": advertised,
        "species_minimum_rates": species_minimum_rates,
        "bid_open_at": bid_open,
        "bid_close_at": bid_close,
        "harvest_window_start": hw_start,
        "harvest_window_end": hw_end,
        "status": "DRAFT",
        "winning_bid_id": None,
        "awarded_value_cents": None,
    })
    ent["_open_dt"] = parse_iso_datetime(bid_open)
    ent["_close_dt"] = parse_iso_datetime(bid_close)
    db["sales"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/sales/<sid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_sale_ep(sid):
    return success(pub(get_sale(sid)), 200)


@bp.route("/forestry/sales", methods=["GET"])
@require_roles(*READ_ROLES)
def list_sales():
    page, meta = paginate(db["sales"].values(), {
        "tract_id": "tract_id",
        "stand_id": "stand_id",
        "prescription_id": "prescription_id",
        "status": "status",
    })
    return success([pub(s) for s in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/sales/<sid>/offer", methods=["POST"])
@require_roles("Forester")
def offer(sid):
    sale = get_sale(sid)
    body = get_body()
    check_known(body, set())
    check_transition(sale, {"DRAFT"}, SALE_TERMINAL, "sale")
    tract = tract_of_sale(sale)
    if _enrollment_conflict(tract, sale["harvest_window_start"],
                            sale["harvest_window_end"]):
        err("ERR_CONSERVATION_ENROLLMENT_CONFLICT", 409,
            "harvest window conflicts with conservation enrollment")
    prescription = get_prescription(sale["prescription_id"])
    if prescription["status"] != "APPROVED":
        err("ERR_PRESCRIPTION_NOT_APPROVED", 409,
            "prescription is not APPROVED")
    cruise = db["cruises"][prescription["cruise_id"]]
    if cruise["status"] != "CERTIFIED":
        err("ERR_CRUISE_NOT_CERTIFIED", 409, "cruise is not CERTIFIED")
    certified_dt = parse_iso_datetime(cruise["certified_at"])
    if now() > add_months(certified_dt, CRUISE_MAX_AGE_MONTHS):
        err("ERR_CRUISE_EXPIRED", 422,
            "cruise certification is older than 24 months")
    sale["status"] = "OFFERED"
    bump(sale)
    return success(pub(sale), 200)


@bp.route("/forestry/sales/<sid>/open-bidding", methods=["POST"])
@require_roles("Forester")
def open_bidding(sid):
    sale = get_sale(sid)
    body = get_body()
    check_known(body, set())
    check_transition(sale, {"OFFERED"}, SALE_TERMINAL, "sale")
    sale["status"] = "BIDDING_OPEN"
    bump(sale)
    return success(pub(sale), 200)


@bp.route("/forestry/sales/<sid>/close-bidding", methods=["POST"])
@require_roles("Forester")
def close_bidding(sid):
    sale = get_sale(sid)
    body = get_body()
    check_known(body, set())
    check_transition(sale, {"BIDDING_OPEN"}, SALE_TERMINAL, "sale")
    if now() < sale["_close_dt"]:
        err("ERR_INVALID_TRANSITION", 409,
            "bid window has not closed yet")
    submitted = [b for b in db["bids"].values()
                 if b["sale_id"] == sale["id"] and b["status"] == "SUBMITTED"]
    qualifying = []
    for b in submitted:
        if b["bid_total_cents"] < sale["advertised_minimum_cents"]:
            b["status"] = "DISQUALIFIED"
            bump(b)
        else:
            qualifying.append(b)
            bump(b)
    winner = None
    for b in qualifying:
        buyer = db["buyers"].get(b["buyer_id"])
        key = (-b["bid_total_cents"], -b["deposit_cents"],
               b["submitted_at"],
               buyer["created_at"] if buyer else "")
        if winner is None or key < winner[0]:
            winner = (key, b)
    sale["winning_bid_id"] = winner[1]["id"] if winner else None
    sale["status"] = "BIDDING_CLOSED"
    bump(sale)
    return success(pub(sale), 200)


@bp.route("/forestry/sales/<sid>/award", methods=["POST"])
@require_roles("Forester")
def award(sid):
    sale = get_sale(sid)
    body = get_body()
    bid_ref = body.get("bid_id")
    if isinstance(bid_ref, str) and bid_ref not in db["bids"]:
        err("ERR_BID_NOT_FOUND", 404, "bid not found: %s" % bid_ref)
    check_known(body, {"bid_id"})
    bid_id = f_str(body, "bid_id")
    if bid_id not in db["bids"]:
        err("ERR_BID_NOT_FOUND", 404, "bid not found: %s" % bid_id)
    check_transition(sale, {"BIDDING_CLOSED"}, SALE_TERMINAL, "sale")
    if sale["winning_bid_id"] is None or bid_id != sale["winning_bid_id"]:
        err("ERR_NOT_WINNING_BID", 409,
            "bid_id does not match the computed winning bid")
    winner = db["bids"][bid_id]
    sale["status"] = "AWARDED"
    sale["awarded_value_cents"] = winner["bid_total_cents"]
    bump(sale)
    for b in db["bids"].values():
        if b["sale_id"] != sale["id"] or b["status"] != "SUBMITTED":
            continue
        b["status"] = "WINNING" if b["id"] == bid_id else "LOST"
        bump(b)
    buyer = db["buyers"][winner["buyer_id"]]
    required = performance_bond_amount(sale["awarded_value_cents"],
                                       buyer["prior_defaults"])
    contract = new_common({
        "sale_id": sale["id"],
        "buyer_id": winner["buyer_id"],
        "contractor_id": None,
        "status": "PENDING_BOND",
        "awarded_value_cents": sale["awarded_value_cents"],
        "governing_scaling_rule": sale["scaling_rule"],
        "required_bond_amount_cents": required,
        "billed_total_cents": 0,
        "disbursed_total_cents": 0,
        "refunded_total_cents": 0,
        "holdback_balance_cents": 0,
        "consulting_fee_total_cents": 0,
        "defaulted_at": None,
        "harvest_completed_at": None,
    })
    db["contracts"][contract["id"]] = contract
    return success(pub(sale), 200)


@bp.route("/forestry/sales/<sid>/no-sale", methods=["POST"])
@require_roles("Forester")
def no_sale(sid):
    sale = get_sale(sid)
    body = get_body()
    check_known(body, set())
    check_transition(sale, {"BIDDING_CLOSED"}, SALE_TERMINAL, "sale")
    if sale["winning_bid_id"] is not None:
        err("ERR_INVALID_TRANSITION", 409,
            "a qualifying winning bid exists; award instead")
    for b in db["bids"].values():
        if b["sale_id"] == sale["id"] and b["status"] == "SUBMITTED":
            b["status"] = "LOST"
            bump(b)
    sale["status"] = "NO_SALE"
    bump(sale)
    return success(pub(sale), 200)


@bp.route("/forestry/sales/<sid>/reoffer", methods=["POST"])
@require_roles("Forester")
def reoffer(sid):
    sale = get_sale(sid)
    body = get_body()
    check_known(body, {"bid_open_at", "bid_close_at",
                       "advertised_minimum_cents"})
    bid_open = f_datetime(body, "bid_open_at")
    bid_close = f_datetime(body, "bid_close_at")
    if parse_iso_datetime(bid_close) <= parse_iso_datetime(bid_open):
        bad_request("bid_close_at must be after bid_open_at")
    new_min = f_int(body, "advertised_minimum_cents", required=False,
                    minv=0)
    check_transition(sale, {"NO_SALE"}, SALE_TERMINAL, "sale")
    tract = tract_of_sale(sale)
    if _enrollment_conflict(tract, sale["harvest_window_start"],
                            sale["harvest_window_end"]):
        err("ERR_CONSERVATION_ENROLLMENT_CONFLICT", 409,
            "harvest window conflicts with conservation enrollment")
    sale["bid_open_at"] = bid_open
    sale["bid_close_at"] = bid_close
    sale["_open_dt"] = parse_iso_datetime(bid_open)
    sale["_close_dt"] = parse_iso_datetime(bid_close)
    if new_min is not None:
        sale["advertised_minimum_cents"] = new_min
    sale["status"] = "OFFERED"
    bump(sale)
    return success(pub(sale), 200)


def cancel_sale(sale):
    """Sale -> CANCELLED; SUBMITTED bids -> WITHDRAWN."""
    for b in db["bids"].values():
        if b["sale_id"] == sale["id"] and b["status"] == "SUBMITTED":
            b["status"] = "WITHDRAWN"
            bump(b)
    sale["status"] = "CANCELLED"
    bump(sale)


@bp.route("/forestry/sales/<sid>/cancel", methods=["POST"])
@require_roles("Forester", "Landowner")
def cancel(sid):
    sale = get_sale(sid)
    body = get_body()
    check_known(body, set())
    if g.role == "Landowner":
        tract = tract_of_sale(sale)
        if tract["landowner_id"] != g.uid:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "landowner does not own this tract")
    check_transition(
        sale, {"DRAFT", "OFFERED", "BIDDING_OPEN", "BIDDING_CLOSED",
               "NO_SALE"}, SALE_TERMINAL, "sale")
    cancel_sale(sale)
    return success(pub(sale), 200)


# ------------------------------- bids -------------------------------

def _certified_species_volumes(sale):
    """species -> certified volume from the sale's underpinning cruise."""
    prescription = db["prescriptions"].get(sale["prescription_id"])
    if not prescription:
        return {}
    cruise = db["cruises"].get(prescription["cruise_id"])
    if not cruise or not cruise.get("certified_volume_by_species"):
        return {}
    return {e["species"]: e["volume_bf"]
            for e in cruise["certified_volume_by_species"]}


@bp.route("/forestry/sales/<sale_id>/bids", methods=["POST"])
@require_roles("Buyer")
def create_bid(sale_id):
    sale = get_sale(sale_id)
    if g.uid not in db["buyers"]:
        err("ERR_PARTY_NOT_FOUND", 404, "buyer not found: %s" % g.uid)
    body = get_body()
    check_known(body, {"expected_sale_version", "deposit_cents",
                       "lump_sum_amount_cents", "species_rates"})
    expected = f_int(body, "expected_sale_version")
    deposit = f_int(body, "deposit_cents", minv=0)
    lump = f_int(body, "lump_sum_amount_cents", required=False, minv=0)
    raw_rates = body.get("species_rates")
    if raw_rates is not None:
        if not isinstance(raw_rates, list):
            bad_request("species_rates must be an array")
        _validate_rate_rows(raw_rates, "rate_cents_per_mbf")
    if sale["status"] != "BIDDING_OPEN":
        err("ERR_SALE_NOT_OPEN_FOR_BIDDING", 409,
            "sale is not open for bidding")
    # pricing payload shape per sale type
    if sale["sale_type"] == "LUMP_SUM":
        if lump is None or raw_rates is not None:
            err("ERR_SPECIES_RATE_MISSING", 422,
                "LUMP_SUM bid requires lump_sum_amount_cents only")
    else:
        if raw_rates is None or lump is not None:
            err("ERR_SPECIES_RATE_MISSING", 422,
                "PER_UNIT bid requires species_rates only")
        advertised = {e["species"]
                      for e in sale["species_minimum_rates"] or []}
        offered = {e["species"] for e in raw_rates}
        if not advertised.issubset(offered):
            err("ERR_SPECIES_RATE_MISSING", 422,
                "species_rates must cover every advertised species")
    # bid window: open <= clock < close
    if not (sale["_open_dt"] <= now() < sale["_close_dt"]):
        err("ERR_BID_WINDOW_NOT_OPEN", 409,
            "bid submitted outside the bid window")
    # per-species floor rates
    if sale["sale_type"] == "PER_UNIT":
        floors = {e["species"]: e["min_rate_cents_per_mbf"]
                  for e in sale["species_minimum_rates"]}
        for e in raw_rates:
            floor = floors.get(e["species"])
            if floor is not None and e["rate_cents_per_mbf"] < floor:
                err("ERR_BID_BELOW_MINIMUM", 422,
                    "rate for %s below advertised minimum" % e["species"])
    if expected != sale["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_sale_version does not match sale version")
    # compute bid total
    if sale["sale_type"] == "LUMP_SUM":
        total = lump
    else:
        volumes = _certified_species_volumes(sale)
        total = 0
        for e in sale["species_minimum_rates"]:
            species = e["species"]
            rate = next(r["rate_cents_per_mbf"] for r in raw_rates
                        if r["species"] == species)
            vol = volumes.get(species, 0)
            total += rhu(D(rate) * D(vol) / D(1000))
    # supersede this buyer's prior SUBMITTED bid on the sale
    for b in db["bids"].values():
        if (b["sale_id"] == sale["id"] and b["buyer_id"] == g.uid
                and b["status"] == "SUBMITTED"):
            b["status"] = "SUPERSEDED"
            bump(b)
    ent = new_common({
        "sale_id": sale["id"],
        "buyer_id": g.uid,
        "deposit_cents": deposit,
        "lump_sum_amount_cents": lump,
        "species_rates": raw_rates,
        "bid_total_cents": total,
        "submitted_at": now_iso(),
        "status": "SUBMITTED",
    })
    db["bids"][ent["id"]] = ent
    bump(sale)
    return success(pub(ent), 201)


@bp.route("/forestry/bids/<bid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_bid_ep(bid):
    return success(pub(get_bid(bid)), 200)


@bp.route("/forestry/bids", methods=["GET"])
@require_roles(*READ_ROLES)
def list_bids():
    page, meta = paginate(db["bids"].values(), {
        "sale_id": "sale_id",
        "buyer_id": "buyer_id",
        "status": "status",
    })
    return success([pub(b) for b in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/bids/<bid>/withdraw", methods=["POST"])
@require_roles("Buyer")
def withdraw_bid(bid):
    b = get_bid(bid)
    body = get_body()
    check_known(body, set())
    if b["buyer_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "bid does not belong to buyer")
    check_transition(b, {"SUBMITTED"}, BID_TERMINAL, "bid")
    sale = db["sales"][b["sale_id"]]
    if sale["status"] != "BIDDING_OPEN":
        err("ERR_SALE_NOT_OPEN_FOR_BIDDING", 409,
            "sale is not open for bidding")
    if now() >= sale["_close_dt"]:
        err("ERR_BID_WINDOW_NOT_OPEN", 409, "bid window has closed")
    b["status"] = "WITHDRAWN"
    bump(b)
    return success(pub(b), 200)
