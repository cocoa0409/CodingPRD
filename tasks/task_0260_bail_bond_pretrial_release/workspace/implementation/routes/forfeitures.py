"""ForfeitureProceeding endpoints + ledger listing + the test clock."""
from flask import Blueprint, request

import db
from clock import parse_iso, set_clock
from errors import err
from helpers import paginate, require_fields, require_int
from lookup import (get_bond, get_court_date, get_defendant, get_forfeiture,
                    get_forfeiture_for_defendant)
from middleware import (authenticate, get_json_body, parse_pagination,
                        require_role)
from response import array_response, object_response
from services import domain
from views import view, view_list

bp = Blueprint("forfeitures", __name__)


@bp.route("/forfeitures/<proceeding_id>", methods=["GET"])
def fetch_forfeiture(proceeding_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer", "RecoveryAgent"})
    f = get_forfeiture(proceeding_id)
    return object_response(view(f), 200)


@bp.route("/bonds/<bond_id>/forfeitures", methods=["GET"])
def list_bond_forfeitures(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer", "RecoveryAgent"})
    get_bond(bond_id)
    limit, offset = parse_pagination()
    records = [f for f in db.forfeitures.values() if f["bond_id"] == bond_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/court-dates/<court_date_id>/forfeitures", methods=["GET"])
def list_court_date_forfeitures(court_date_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer", "RecoveryAgent"})
    get_court_date(court_date_id)
    limit, offset = parse_pagination()
    records = [f for f in db.forfeitures.values()
               if f["trigger_court_date_id"] == court_date_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/defendants/<defendant_id>/forfeitures/<proceeding_id>/open-recovery",
          methods=["POST"])
def open_recovery(defendant_id, proceeding_id):
    _, role = authenticate()
    require_role(role, {"RecoveryAgent"})
    proceeding = get_forfeiture_for_defendant(defendant_id, proceeding_id)
    defendant = db.defendants[defendant_id]
    domain.open_recovery(defendant, proceeding)
    return object_response(view(proceeding), 200)


@bp.route("/defendants/<defendant_id>/forfeitures/<proceeding_id>/reinstate", methods=["POST"])
def reinstate(defendant_id, proceeding_id):
    _, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    proceeding = get_forfeiture_for_defendant(defendant_id, proceeding_id)
    defendant = db.defendants[defendant_id]
    domain.reinstate(defendant, proceeding)
    return object_response(view(proceeding), 200)


@bp.route("/defendants/<defendant_id>/forfeitures/<proceeding_id>/enter-judgment",
          methods=["POST"])
def enter_judgment(defendant_id, proceeding_id):
    _, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    proceeding = get_forfeiture_for_defendant(defendant_id, proceeding_id)
    body = get_json_body()
    require_fields(body, ["expected_bond_version"])
    expected_version = require_int(body, "expected_bond_version")
    defendant = db.defendants[defendant_id]
    domain.enter_judgment(defendant, proceeding, expected_version)
    return object_response(view(proceeding), 200)


@bp.route("/defendants/<defendant_id>/forfeitures/<proceeding_id>/remit", methods=["POST"])
def remit(defendant_id, proceeding_id):
    _, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    proceeding = get_forfeiture_for_defendant(defendant_id, proceeding_id)
    body = get_json_body()
    require_fields(body, ["remission_pct"])
    remission_pct = body["remission_pct"]
    # numeric (int or float), in (0, 100]
    if isinstance(remission_pct, bool) or not isinstance(remission_pct, (int, float)):
        raise err("ERR_INVALID_REQUEST", "remission_pct must be a number.")
    if not (remission_pct > 0 and remission_pct <= 100):
        raise err("ERR_INVALID_REMISSION", "remission_pct must be in (0, 100].")
    defendant = db.defendants[defendant_id]
    domain.remit(defendant, proceeding, remission_pct)
    return object_response(view(proceeding), 200)


# ---- Ledger ----

@bp.route("/bonds/<bond_id>/ledger", methods=["GET"])
def list_ledger(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer"})
    get_bond(bond_id)
    limit, offset = parse_pagination()
    records = [l for l in db.ledger_entries.values() if l["bond_id"] == bond_id]
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        records = [l for l in records if l["entry_type"] == entry_type]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


# ---- Test-driving clock ----

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    require_role(role, {"SystemAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    value = body["to_iso8601"]
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a string.")
    dt = parse_iso(value)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    set_clock(dt)
    return object_response({}, 200)
