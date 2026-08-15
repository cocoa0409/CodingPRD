"""Title transfers: draft, execute, revoke."""
from flask import Blueprint, request
from db import db, clock
from errors import (err_invalid_state, err_invalid_request, err_title_encumbered,
                    err_not_found)
from middleware import (get_caller, require_roles, get_json_body, require_fields,
                        check_enum, parse_pagination, paginate)
from response import success_object, success_list
from services.common import (new_entity, touch, get_or_404, serialize_title_transfer,
                             serialize_domain_event)
from services.events import emit

bp = Blueprint("title", __name__)

WARRANTIES = {"FULL", "QUITCLAIM", "SPECIAL"}


@bp.route("/yacht/closing-statements/<sid>/title-transfers", methods=["POST"])
def create_transfer(sid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    s = get_or_404(db.statements, sid, "ClosingStatement")
    body = get_json_body()
    require_fields(body, ["vessel_id", "from_client_id", "to_client_id", "warranty_of_title"])
    vessel = get_or_404(db.vessels, body["vessel_id"], "Vessel")
    get_or_404(db.clients, body["from_client_id"], "Client")
    get_or_404(db.clients, body["to_client_id"], "Client")
    check_enum(body, "warranty_of_title", WARRANTIES)
    # Vessel must equal the offer's listing vessel
    offer = db.offers.get(s["offer_id"])
    listing = db.listings.get(offer["listing_id"]) if offer else None
    if listing is None or listing["vessel_id"] != vessel["id"]:
        raise err_invalid_request("vessel_id must equal the offer's listing vessel")

    t = new_entity()
    t["closing_statement_id"] = s["id"]
    t["vessel_id"] = vessel["id"]
    t["from_client_id"] = body["from_client_id"]
    t["to_client_id"] = body["to_client_id"]
    t["warranty_of_title"] = body["warranty_of_title"]
    t["executed_at"] = None
    t["status"] = "DRAFT"
    db.title_transfers[t["id"]] = t
    return success_object(serialize_title_transfer(t), 201)


@bp.route("/yacht/title-transfers/<tid>", methods=["GET"])
def get_transfer(tid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    t = get_or_404(db.title_transfers, tid, "TitleTransfer")
    return success_object(serialize_title_transfer(t))


@bp.route("/yacht/title-transfers", methods=["GET"])
def list_transfers():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    limit, offset = parse_pagination()
    items = sorted(db.title_transfers.values(), key=lambda x: x["created_at"])
    for f in ("closing_statement_id", "vessel_id", "from_client_id", "to_client_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t[f] == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_title_transfer(t) for t in page], limit, offset, total)


@bp.route("/yacht/title-transfers/<tid>/execute", methods=["POST"])
def execute_transfer(tid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    t = get_or_404(db.title_transfers, tid, "TitleTransfer")
    get_json_body()
    if t["status"] != "DRAFT":
        raise err_invalid_state("Transfer must be DRAFT to execute")
    stmt = db.statements.get(t["closing_statement_id"])
    if stmt is None or stmt["status"] != "APPROVED":
        raise err_invalid_state("Statement must be APPROVED to execute the transfer")
    vessel = db.vessels.get(t["vessel_id"])
    # FULL warranty requires CLEAN liens
    if t["warranty_of_title"] == "FULL" and vessel is not None \
            and vessel["liens_status"] != "CLEAN":
        raise err_title_encumbered()
    # Paperwork must be in order per documentation mode
    if vessel is not None:
        if vessel["documentation_mode"] == "USCG":
            ok = any(d["vessel_id"] == vessel["id"] and d["record_kind"] == "USCG_COD"
                     and d["status"] == "VALID" for d in db.doc_records.values())
            if not ok:
                raise err_invalid_state("A VALID USCG_COD documentation record is required")
        else:
            ok = any(d["vessel_id"] == vessel["id"] and d["record_kind"] == "STATE_TITLE"
                     and d["status"] == "VALID" for d in db.doc_records.values())
            if not ok:
                raise err_invalid_state("A VALID STATE_TITLE documentation record is required")
    t["status"] = "EXECUTED"
    t["executed_at"] = clock.iso()
    touch(t)
    return success_object(serialize_title_transfer(t))


@bp.route("/yacht/title-transfers/<tid>/revoke", methods=["POST"])
def revoke_transfer(tid):
    caller = get_caller()
    require_roles(caller, ["ClosingOfficer"])
    t = get_or_404(db.title_transfers, tid, "TitleTransfer")
    get_json_body()
    if t["status"] != "EXECUTED":
        raise err_invalid_state("Transfer must be EXECUTED to revoke")
    stmt = db.statements.get(t["closing_statement_id"])
    if stmt is not None and stmt["status"] == "DISBURSED":
        raise err_invalid_state("Cannot revoke after disbursement")
    t["status"] = "REVOKED"
    touch(t)
    return success_object(serialize_title_transfer(t))


# ---------------------------------------------------------------------------
# Audit log + logical clock
# ---------------------------------------------------------------------------

@bp.route("/yacht/domain-events", methods=["GET"])
def list_domain_events():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    limit, offset = parse_pagination()
    items = sorted(db.domain_events.values(), key=lambda x: x["created_at"])
    at = request.args.get("aggregate_type")
    if at is not None:
        items = [e for e in items if e["aggregate_type"] == at]
    aid = request.args.get("aggregate_id")
    if aid is not None:
        items = [e for e in items if e["aggregate_id"] == aid]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_domain_event(e) for e in page], limit, offset, total)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    from db import parse_iso
    try:
        dt = parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err_invalid_request("to_iso8601 must be an ISO-8601 datetime")
    clock.set(dt)
    # Advancing the clock runs the automated expiry sweeps
    from services.sweep import run_sweeps
    run_sweeps()
    return success_object({"current_utc": clock.iso()})
