"""Council endpoints + clock (PRD §3.1, §3.9, §2.10)."""
from datetime import datetime, timezone

from flask import Blueprint

from db import db
from clock import clock
from errors import err, ERR_INVALID_REQUEST
from middleware import authenticate, require_roles, REGISTRAR_ONLY, BOTH_ROLES
from response import object_response, array_response
from serializers import serialize_council, serialize_troop, serialize_fund_ledger_entry
from util import new_id, iso_now, parse_iso_datetime
from routes import helpers as h
from services import recompute

bp = Blueprint("councils", __name__)


@bp.post("/councils")
def create_council():
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    body = h.get_json_body()

    name = h.require_string(body, "name")
    charter_fee_cents = h.require_int(body, "charter_fee_cents")
    youth_dues_cents = h.require_int(body, "youth_dues_cents")
    adult_dues_cents = h.require_int(body, "adult_dues_cents")
    program_year = h.require_int(body, "program_year")

    # PRD §3.1: fee and both dues amounts must be >= 0; program year >= 2000.
    if charter_fee_cents < 0 or youth_dues_cents < 0 or adult_dues_cents < 0:
        raise err(ERR_INVALID_REQUEST, "fee and dues amounts must be >= 0")
    if program_year < 2000:
        raise err(ERR_INVALID_REQUEST, "program_year must be >= 2000")

    now = iso_now(datetime.now(timezone.utc))
    council = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "name": name,
        "charter_fee_cents": charter_fee_cents,
        "youth_dues_cents": youth_dues_cents,
        "adult_dues_cents": adult_dues_cents,
        # PRD §3.1: council begins with both balances at zero.
        "fund_cash_cents": 0,
        "fund_liability_cents": 0,
        "program_year": program_year,
        "_seq": db.next_seq(),
    }
    db.councils[council["id"]] = council
    return object_response(serialize_council(council), status=201)


@bp.get("/councils/<council_id>")
def get_council(council_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    council = h.get_or_404(db.councils, council_id)
    recompute.refresh_council_read(council)
    return object_response(serialize_council(council))


@bp.get("/councils/<council_id>/ledger")
def list_council_ledger(council_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    council = h.get_or_404(db.councils, council_id)
    from flask import request

    account = request.args.get("account")
    troop_id = request.args.get("troop_id")
    limit, offset = h.parse_pagination()

    rows = [
        e for e in db.fund_ledger_entries.values()
        if e["council_id"] == council["id"]
        and (account is None or e["account"] == account)
        and (troop_id is None or e["troop_id"] == troop_id)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response(
        [serialize_fund_ledger_entry(e) for e in page], limit, offset, total
    )


@bp.get("/councils/<council_id>/report")
def council_report(council_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    council = h.get_or_404(db.councils, council_id)
    # Recompute all derived counts/balances at read time (PRD §3.9).
    recompute.refresh_council_read(council)
    troops = [t for t in db.troops.values() if t["council_id"] == council["id"]]
    for t in troops:
        recompute.refresh_troop_read(t)
    return object_response(serialize_council(council))


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.10)
# ---------------------------------------------------------------------------
clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    body = h.get_json_body()
    to_iso = h.require_field(body, "to_iso8601")
    new_now = parse_iso_datetime(to_iso)
    clock.set(new_now)
    # Re-evaluate any troop whose charter may now be expired/valid for posture.
    for t in db.troops.values():
        recompute.refresh_troop_read(t)
    # PRD §4: clock-set returns 200; data is an empty object for no-data 2xx.
    return object_response({}, status=200)
