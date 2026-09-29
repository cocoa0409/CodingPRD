"""Target-market definitions and accountability seats."""
import services as svc
import shape
from auth import authenticate, scope
from envelope import created, ok, page, pagination, qs
from errors import fail
from flask import Blueprint
from store import base_row, db, fmt_dt, now, ordered, touch

bp = Blueprint("governance", __name__)

MARKET_TYPES = ("INVESTMENT_AREA", "LOW_INCOME_TARGETED_POPULATION",
                "OTHER_TARGETED_POPULATION")
STRUCTURES = ("GOVERNING_BOARD", "ADVISORY_BOARD")
MARKET_READ_ROLES = ("InstitutionOfficer", "CertificationReviewer",
                     "ComplianceAnalyst")
MARKET_LIST_ROLES = ("CertificationReviewer", "ComplianceAnalyst")
SEAT_READ_ROLES = ("InstitutionOfficer", "CertificationReviewer",
                   "ComplianceAnalyst")


# --------------------------------------------------------------------------- #
# target markets
# --------------------------------------------------------------------------- #
@bp.post("/institutions/<institution_id>/target-markets")
def create_target_market(institution_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    data = shape.body()
    market_type = shape.req_enum(data, "market_type", MARKET_TYPES)
    name = shape.req_str(data, "name", 1)
    tracts = shape.opt_str_array(data, "census_tract_codes", default=[])
    threshold = shape.opt_dec(data, "ami_threshold_pct", places=2, minimum=0)
    if market_type == "INVESTMENT_AREA":
        if not tracts:
            fail("ERR_INVALID_REQUEST")
    elif tracts:
        fail("ERR_INVALID_REQUEST")
    if market_type == "LOW_INCOME_TARGETED_POPULATION":
        if threshold is None:
            fail("ERR_INVALID_REQUEST")
    elif threshold is not None:
        fail("ERR_INVALID_REQUEST")
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "market_type": market_type,
        "name": name,
        "census_tract_codes": tracts,
        "ami_threshold_pct": threshold,
        "state": "DRAFT",
        "approved_at": None,
    })
    db.target_markets[row["id"]] = row
    return created(row)


@bp.get("/institutions/<institution_id>/target-markets")
def list_institution_markets(institution_id):
    caller = authenticate(MARKET_READ_ROLES)
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    limit, offset = pagination()
    rows = svc.institution_markets(institution_id)
    rows = _filter_markets(rows)
    return page(rows, limit, offset)


@bp.get("/target-markets")
def list_markets():
    authenticate(MARKET_LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.target_markets.values())
    institution_id = qs("institution_id")
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    rows = _filter_markets(rows)
    return page(rows, limit, offset)


def _filter_markets(rows):
    market_type = qs("market_type")
    state = qs("state")
    if market_type is not None:
        rows = [r for r in rows if r["market_type"] == market_type]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return rows


@bp.get("/target-markets/<target_market_id>")
def read_target_market(target_market_id):
    caller = authenticate(MARKET_READ_ROLES)
    existing = db.target_markets.get(target_market_id)
    scope(caller, existing["institution_id"] if existing else None)
    return ok(svc.get_market(target_market_id))


@bp.post("/target-markets/<target_market_id>/approve")
def approve_target_market(target_market_id):
    authenticate(("CertificationReviewer",))
    market = svc.get_market(target_market_id)
    if market["state"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")
    if market["market_type"] == "INVESTMENT_AREA" and not market["census_tract_codes"]:
        fail("ERR_INVALID_STATE_TRANSITION")
    if (market["market_type"] == "LOW_INCOME_TARGETED_POPULATION"
            and market["ami_threshold_pct"] is None):
        fail("ERR_INVALID_STATE_TRANSITION")
    market["state"] = "APPROVED"
    market["approved_at"] = fmt_dt(now())
    touch(market)
    inst = db.institutions.get(market["institution_id"])
    if inst is not None:
        # Seats pointing at this definition now begin to count.
        svc.recompute_accountability(inst)
        touch(inst)
    return ok(market)


# --------------------------------------------------------------------------- #
# board seats
# --------------------------------------------------------------------------- #
def _recount_seats(inst):
    governing = advisory = 0
    for seat in db.board_seats.values():
        if seat["institution_id"] != inst["id"] or seat["status"] != "ACTIVE":
            continue
        if seat["structure"] == "GOVERNING_BOARD":
            governing += 1
        elif seat["structure"] == "ADVISORY_BOARD":
            advisory += 1
    inst["governing_seats_active"] = governing
    inst["advisory_seats_active"] = advisory


@bp.post("/institutions/<institution_id>/board-seats")
def create_board_seat(institution_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    data = shape.body()
    supplied_market = shape.body_id(data, "target_market_id")
    if supplied_market is not None:
        svc.get_market(supplied_market, institution_id)
    structure = shape.req_enum(data, "structure", STRUCTURES)
    holder_name = shape.req_str(data, "holder_name", 1)
    represents = shape.opt_bool(data, "represents_target_market", default=False)
    market_id = shape.opt_id(data, "target_market_id")
    if represents and market_id is None:
        fail("ERR_INVALID_REQUEST")
    if not represents and market_id is not None:
        fail("ERR_INVALID_REQUEST")
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "target_market_id": market_id,
        "structure": structure,
        "holder_name": holder_name,
        "represents_target_market": represents,
        "status": "ACTIVE",
        "resigned_at": None,
    })
    db.board_seats[row["id"]] = row
    inst = db.institutions[institution_id]
    _recount_seats(inst)
    svc.recompute_accountability(inst)
    touch(inst)
    return created(row)


@bp.get("/board-seats/<board_seat_id>")
def read_board_seat(board_seat_id):
    caller = authenticate(SEAT_READ_ROLES)
    existing = db.board_seats.get(board_seat_id)
    scope(caller, existing["institution_id"] if existing else None)
    return ok(svc.get_seat(board_seat_id))


@bp.get("/board-seats")
def list_board_seats():
    caller = authenticate(SEAT_READ_ROLES)
    institution_id = qs("institution_id")
    scope(caller, institution_id)
    limit, offset = pagination()
    rows = ordered(db.board_seats.values())
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    market_id = qs("target_market_id")
    structure = qs("structure")
    status = qs("status")
    if market_id is not None:
        rows = [r for r in rows if r["target_market_id"] == market_id]
    if structure is not None:
        rows = [r for r in rows if r["structure"] == structure]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, limit, offset)


@bp.post("/board-seats/<board_seat_id>/resign")
def resign_board_seat(board_seat_id):
    caller = authenticate(("InstitutionOfficer",))
    existing = db.board_seats.get(board_seat_id)
    scope(caller, existing["institution_id"] if existing else None)
    seat = svc.get_seat(board_seat_id)
    if seat["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")
    seat["status"] = "RESIGNED"
    seat["resigned_at"] = fmt_dt(now())
    touch(seat)
    inst = db.institutions.get(seat["institution_id"])
    if inst is not None:
        before = inst["accountability_satisfied"]
        _recount_seats(inst)
        after = svc.recompute_accountability(inst)
        touch(inst)
        if before and not after:
            svc.accountability_failure_cascade(inst)
    return ok(seat)
