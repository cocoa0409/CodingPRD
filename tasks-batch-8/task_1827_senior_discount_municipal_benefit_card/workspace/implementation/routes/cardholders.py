from flask import Blueprint

import services
import store
from auth import authenticate, authorize, require_cardholder_self
from errors import (
    ERR_CARDHOLDER_ALREADY_TERMINAL,
    ERR_CARDHOLDER_NOT_ACTIVE,
    ERR_CARDHOLDER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REPLACEMENT_NOT_ALLOWED,
    ERR_STALE_VERSION,
    ERR_WAIVER_WINDOW_INVALID,
    ERR_WAIVER_WINDOW_OVERLAP,
    raise_err,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_enum_query,
    req_date,
    req_enum,
    success_object,
)

bp = Blueprint("cardholders", __name__)

WAIVER_TYPES = ("TRANSIT_FARE", "FACILITY_FEE")
CARD_ISSUE_REASONS = ("REPLACEMENT", "RENEWAL")


def _get_cardholder(rid):
    return get_or_404(store.cardholders, rid, ERR_CARDHOLDER_NOT_FOUND, "Cardholder")


@bp.route("/cardholders/<rid>", methods=["GET"])
def get_cardholder(rid):
    uid, role = authenticate()
    authorize(role, ["Cardholder", "EligibilitySpecialist", "ProgramAdministrator",
                     "FraudAnalyst"])
    rec = _get_cardholder(rid)
    if role == "Cardholder":
        require_cardholder_self(uid, rid)
    return success_object(services.cardholder_out(rec))


@bp.route("/cardholders/<rid>/applications", methods=["GET"])
def list_cardholder_applications(rid):
    uid, role = authenticate()
    authorize(role, ["Cardholder", "EligibilitySpecialist", "ProgramAdministrator"])
    rec = _get_cardholder(rid)
    if role == "Cardholder":
        require_cardholder_self(uid, rid)
    apps = [a for a in store.applications.values() if a["cardholder_id"] == rec["id"]]
    return list_response(apps, services.application_out)


@bp.route("/cardholders/<rid>/cards", methods=["POST"])
def issue_card(rid):
    uid, role = authenticate()
    authorize(role, ["Cardholder", "ProgramAdministrator"])
    ch = _get_cardholder(rid)
    if ch["status"] not in ("ACTIVE", "RECERTIFICATION_DUE"):
        raise_err(ERR_CARDHOLDER_NOT_ACTIVE,
                  "Card issuance requires cardholder status ACTIVE or "
                  "RECERTIFICATION_DUE")
    if role == "Cardholder":
        require_cardholder_self(uid, rid)
    body = body_json()
    reason = req_enum(body, "reason", CARD_ISSUE_REASONS)
    expected = body.get("expected_cardholder_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_cardholder_version is required and must be an integer")
    if expected != ch["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_cardholder_version does not match the cardholder's "
                  "current version")

    cards = services.cardholder_cards(ch["id"])
    live = [c for c in cards if c["status"] in services.CARD_LIVE_STATUSES]
    expired = [c for c in cards if c["status"] == "EXPIRED"]
    if reason == "REPLACEMENT":
        if not live:
            raise_err(ERR_REPLACEMENT_NOT_ALLOWED,
                      "REPLACEMENT requires an ACTIVE or SUSPENDED card")
        prior = max(live, key=lambda c: (c["created_at"], c["_seq"]))
        prior["status"] = "REPLACED"
        bump(prior)
        card = services.issue_card(ch, "REPLACEMENT", prior["id"])
    else:
        if live or not expired:
            raise_err(ERR_REPLACEMENT_NOT_ALLOWED,
                      "RENEWAL requires no ACTIVE/SUSPENDED card and at least one "
                      "EXPIRED card")
        prior = max(expired, key=lambda c: (c["created_at"], c["_seq"]))
        card = services.issue_card(ch, "RENEWAL", prior["id"])
    bump(ch)
    return success_object(services.card_out(card), 201)


@bp.route("/cardholders/<rid>/cards", methods=["GET"])
def list_cards(rid):
    uid, role = authenticate()
    authorize(role, ["Cardholder", "ProgramAdministrator", "FraudAnalyst",
                     "EligibilitySpecialist"])
    ch = _get_cardholder(rid)
    if role == "Cardholder":
        require_cardholder_self(uid, rid)
    return list_response(services.cardholder_cards(ch["id"]), services.card_out)


@bp.route("/cardholders/<rid>/revoke", methods=["POST"])
def revoke(rid):
    _, role = authenticate()
    authorize(role, ["FraudAnalyst"])
    ch = _get_cardholder(rid)
    if ch["status"] == "REVOKED":
        raise_err(ERR_CARDHOLDER_ALREADY_TERMINAL, "Cardholder is already REVOKED")
    ch["status"] = "REVOKED"
    ch["pre_suspension_status"] = None
    bump(ch)
    for card in services.cardholder_cards(ch["id"]):
        if card["status"] in services.CARD_LIVE_STATUSES:
            card["status"] = "REVOKED"
            bump(card)
    return success_object(services.cardholder_out(ch))


@bp.route("/cardholders/<rid>/fee-waivers", methods=["POST"])
def grant_waiver(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    ch = _get_cardholder(rid)
    if ch["status"] not in ("ACTIVE", "RECERTIFICATION_DUE"):
        raise_err(ERR_CARDHOLDER_NOT_ACTIVE,
                  "Fee waivers require cardholder status ACTIVE or "
                  "RECERTIFICATION_DUE")
    body = body_json()
    waiver_type = req_enum(body, "waiver_type", WAIVER_TYPES)
    start = req_date(body, "start_date")
    end = req_date(body, "end_date")
    if start > end:
        raise_err(ERR_WAIVER_WINDOW_INVALID, "start_date must be on or before end_date")
    for w in store.waivers.values():
        if w["cardholder_id"] != ch["id"] or w["waiver_type"] != waiver_type:
            continue
        # closed intervals: touching dates conflict
        if start <= w["end_date"] and w["start_date"] <= end:
            raise_err(ERR_WAIVER_WINDOW_OVERLAP,
                      "Window overlaps an existing grant of the same waiver type")
    rec = new_record()
    rec.update({
        "cardholder_id": ch["id"],
        "waiver_type": waiver_type,
        "start_date": start,
        "end_date": end,
    })
    store.waivers[rec["id"]] = rec
    return success_object(services.waiver_out(rec), 201)


@bp.route("/cardholders/<rid>/fee-waivers", methods=["GET"])
def list_waivers(rid):
    uid, role = authenticate()
    authorize(role, ["Cardholder", "ProgramAdministrator", "EligibilitySpecialist"])
    ch = _get_cardholder(rid)
    if role == "Cardholder":
        require_cardholder_self(uid, rid)
    waiver_type = opt_enum_query("waiver_type", WAIVER_TYPES)
    items = [w for w in store.waivers.values() if w["cardholder_id"] == ch["id"]]
    if waiver_type is not None:
        items = [w for w in items if w["waiver_type"] == waiver_type]
    return list_response(items, services.waiver_out)
