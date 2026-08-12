"""Routes: clock, orgs, rate cards, interpreters, certifications,
availability windows, strikes."""
from datetime import timedelta

from flask import Blueprint

import core
from core import (DB, now, auth_ctx, require_role, check_ownership, get_body,
                  envelope, paginate, sort_by_created, req_str, req_int,
                  req_enum, opt_bool, req_enum_list, req_dt, opt_dt, err,
                  new_id)
from domain import (MODALITIES, ADA_CONTEXTS, CRED_LEVELS, CREDENTIALS,
                    touch, ser_org, ser_rate_card, ser_interpreter,
                    ser_certification, ser_window, ser_strike, ser_complaint,
                    ser_credit_memo, get_org, get_rate_card, get_interpreter,
                    get_strike, run_clock_sweeps, suspend_interpreter,
                    interpreter_active_strikes, record_strike)

bp = Blueprint("admin", __name__)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth = auth_ctx()
    body = get_body(allowed_fields={"to_iso8601"}, require=True)
    require_role(auth[1], "PlatformAdmin")
    to = req_dt(body, "to_iso8601")
    core.CLOCK.current = to
    expired, verified, unfilled = run_clock_sweeps()
    return envelope({
        "current_utc": core.iso(now()),
        "expired_offer_count": expired,
        "auto_verified_encounter_count": verified,
        "unfilled_request_count": unfilled,
    })


# --------------------------------------------------------------------------
# RequestingOrg
# --------------------------------------------------------------------------
@bp.route("/orgs", methods=["POST"])
def create_org():
    auth = auth_ctx()
    body = get_body(allowed_fields={"name", "org_type", "credit_limit_cents"},
                    require=True)
    require_role(auth[1], "PlatformAdmin")
    org = {
        "id": new_id(),
        "name": req_str(body, "name"),
        "org_type": req_enum(body, "org_type", ADA_CONTEXTS),
        "credit_limit_cents": req_int(body, "credit_limit_cents", minimum=0),
        "status": "ACTIVE",
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.orgs[org["id"]] = org
    return envelope(ser_org(org), code=201)


@bp.route("/orgs/<oid>", methods=["GET"])
def get_org_route(oid):
    auth_ctx()
    return envelope(ser_org(get_org(oid)))


@bp.route("/orgs/<oid>/suspend", methods=["POST"])
def suspend_org(oid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    org = get_org(oid)
    if org["status"] != "ACTIVE":
        err(core.E_INVALID, 400, "Organization is not ACTIVE")
    org["status"] = "SUSPENDED"
    touch(org)
    return envelope(ser_org(org))


@bp.route("/orgs/<oid>/reinstate", methods=["POST"])
def reinstate_org(oid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    org = get_org(oid)
    if org["status"] != "SUSPENDED":
        err(core.E_INVALID, 400, "Organization is not SUSPENDED")
    org["status"] = "ACTIVE"
    touch(org)
    return envelope(ser_org(org))


@bp.route("/orgs/<oid>/complaints", methods=["GET"])
def org_complaints(oid):
    auth_ctx()
    get_org(oid)
    status = core.request.args.get("status")
    items = [c for c in DB.complaints.values() if c["org_id"] == oid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_complaint(c) for c in page], pagination=meta)


@bp.route("/orgs/<oid>/credit-memos", methods=["GET"])
def org_credit_memos(oid):
    auth_ctx()
    get_org(oid)
    status = core.request.args.get("status")
    items = [m for m in DB.credit_memos.values() if m["org_id"] == oid]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_credit_memo(m) for m in page], pagination=meta)


# --------------------------------------------------------------------------
# RateCard
# --------------------------------------------------------------------------
@bp.route("/rate-cards", methods=["POST"])
def create_rate_card():
    auth = auth_ctx()
    body = get_body(allowed_fields={
        "modality", "ada_context", "credential_level", "hourly_rate_cents",
        "minimum_billable_minutes", "travel_rate_cents_per_hour",
        "mileage_rate_cents_per_mile", "vri_platform_fee_cents_per_min",
        "cancel_full_refund_notice_hours", "cancel_partial_notice_hours",
        "late_cancel_fee_pct", "effective_from"}, require=True)
    require_role(auth[1], "PlatformAdmin")
    pct = core.opt_num(body, "late_cancel_fee_pct", minimum=0, maximum=1)
    if pct is None:
        err(core.E_INVALID, 400, "Field 'late_cancel_fee_pct' is required")
    card = {
        "id": new_id(),
        "modality": req_enum(body, "modality", MODALITIES),
        "ada_context": req_enum(body, "ada_context", ADA_CONTEXTS),
        "credential_level": req_enum(body, "credential_level", CRED_LEVELS),
        "hourly_rate_cents": req_int(body, "hourly_rate_cents", minimum=0),
        "minimum_billable_minutes": req_int(body, "minimum_billable_minutes", minimum=0),
        "travel_rate_cents_per_hour": req_int(body, "travel_rate_cents_per_hour", minimum=0),
        "mileage_rate_cents_per_mile": req_int(body, "mileage_rate_cents_per_mile", minimum=0),
        "vri_platform_fee_cents_per_min": req_int(body, "vri_platform_fee_cents_per_min", minimum=0),
        "cancel_full_refund_notice_hours": req_int(body, "cancel_full_refund_notice_hours", minimum=0),
        "cancel_partial_notice_hours": req_int(body, "cancel_partial_notice_hours", minimum=0),
        "late_cancel_fee_pct": pct,
        "effective_from": req_dt(body, "effective_from"),
        "status": "ACTIVE",
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.rate_cards[card["id"]] = card
    return envelope(ser_rate_card(card), code=201)


@bp.route("/rate-cards/<cid>", methods=["GET"])
def get_rate_card_route(cid):
    auth_ctx()
    return envelope(ser_rate_card(get_rate_card(cid)))


@bp.route("/rate-cards/<cid>/retire", methods=["POST"])
def retire_rate_card(cid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    card = get_rate_card(cid)
    if card["status"] != "ACTIVE":
        err(core.E_CARD_RETIRED, 409, "Rate card is already RETIRED")
    card["status"] = "RETIRED"
    touch(card)
    return envelope(ser_rate_card(card))


# --------------------------------------------------------------------------
# Interpreter
# --------------------------------------------------------------------------
@bp.route("/interpreters", methods=["POST"])
def create_interpreter():
    auth = auth_ctx()
    body = get_body(allowed_fields={"full_name", "modalities_offered",
                                    "home_zip", "vri_platform_certified"},
                    require=True)
    require_role(auth[1], "PlatformAdmin")
    interp = {
        "id": new_id(),
        "full_name": req_str(body, "full_name"),
        "modalities_offered": req_enum_list(body, "modalities_offered", MODALITIES),
        "home_zip": req_str(body, "home_zip"),
        "vri_platform_certified": opt_bool(body, "vri_platform_certified", False),
        "status": "PENDING_ONBOARD",
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.interpreters[interp["id"]] = interp
    return envelope(ser_interpreter(interp), code=201)


@bp.route("/interpreters/<iid>", methods=["GET"])
def get_interpreter_route(iid):
    auth_ctx()
    return envelope(ser_interpreter(get_interpreter(iid)))


@bp.route("/interpreters/<iid>/activate", methods=["POST"])
def activate_interpreter(iid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    interp = get_interpreter(iid)
    if interp["status"] != "PENDING_ONBOARD":
        err(core.E_INVALID, 400, "Interpreter is not PENDING_ONBOARD")
    verified = [c for c in DB.certifications.values()
                if c["interpreter_id"] == iid and c["verified"]]
    if not verified:
        err(core.E_CREDENTIAL, 422,
            "Activation requires at least one verified certification")
    interp["status"] = "ACTIVE"
    touch(interp)
    return envelope(ser_interpreter(interp))


@bp.route("/interpreters/<iid>/suspend", methods=["POST"])
def suspend_interpreter_route(iid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    interp = get_interpreter(iid)
    if interp["status"] != "ACTIVE":
        err(core.E_INVALID, 400, "Interpreter is not ACTIVE")
    suspend_interpreter(interp)
    return envelope(ser_interpreter(interp))


@bp.route("/interpreters/<iid>/reinstate", methods=["POST"])
def reinstate_interpreter(iid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    interp = get_interpreter(iid)
    if interp["status"] != "SUSPENDED":
        err(core.E_INVALID, 400, "Interpreter is not SUSPENDED")
    if interpreter_active_strikes(iid) >= 3:
        err(core.E_STRIKES_AT_LIMIT, 409,
            "Reinstatement blocked while active_strike_count >= 3")
    interp["status"] = "ACTIVE"
    touch(interp)
    return envelope(ser_interpreter(interp))


# --------------------------------------------------------------------------
# Certification
# --------------------------------------------------------------------------
@bp.route("/interpreters/<iid>/certifications", methods=["POST"])
def create_certification(iid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"credential", "level", "issued_on",
                                    "expires_on"}, require=True)
    require_role(auth[1], "PlatformAdmin", "Interpreter")
    if auth[1] == "Interpreter":
        check_ownership(auth[0] == iid)
    get_interpreter(iid)
    cert = {
        "id": new_id(), "interpreter_id": iid,
        "credential": req_enum(body, "credential", CREDENTIALS),
        "level": req_enum(body, "level", CRED_LEVELS),
        "issued_on": req_dt(body, "issued_on"),
        "expires_on": req_dt(body, "expires_on"),
        "verified": False,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.certifications[cert["id"]] = cert
    return envelope(ser_certification(cert), code=201)


@bp.route("/interpreters/<iid>/certifications", methods=["GET"])
def list_certifications(iid):
    auth_ctx()
    get_interpreter(iid)
    items = [c for c in DB.certifications.values() if c["interpreter_id"] == iid]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_certification(c) for c in page], pagination=meta)


@bp.route("/interpreters/<iid>/certifications/<cid>/verify", methods=["POST"])
def verify_certification(iid, cid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    get_interpreter(iid)
    cert = DB.certifications.get(cid)
    if cert is None or cert["interpreter_id"] != iid:
        err(core.E_CERT_NF, 404, f"Certification {cid} not found under interpreter {iid}")
    cert["verified"] = True
    touch(cert)
    return envelope(ser_certification(cert))


# --------------------------------------------------------------------------
# AvailabilityWindow
# --------------------------------------------------------------------------
@bp.route("/interpreters/<iid>/availability-windows", methods=["POST"])
def create_window(iid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"start_at", "end_at", "modalities"}, require=True)
    require_role(auth[1], "Interpreter")
    check_ownership(auth[0] == iid)
    get_interpreter(iid)
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    if end_at <= start_at:
        err(core.E_INVALID, 400, "Field 'end_at' must be later than 'start_at'")
    modalities = req_enum_list(body, "modalities", MODALITIES)
    for w in DB.availability_windows.values():
        if w["interpreter_id"] != iid:
            continue
        if start_at < w["end_at"] and end_at > w["start_at"]:
            err(core.E_WINDOW_OVERLAP, 409,
                "New window overlaps an existing availability window")
    window = {
        "id": new_id(), "interpreter_id": iid,
        "start_at": start_at, "end_at": end_at, "modalities": modalities,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.availability_windows[window["id"]] = window
    return envelope(ser_window(window), code=201)


@bp.route("/interpreters/<iid>/availability-windows", methods=["GET"])
def list_windows(iid):
    auth_ctx()
    get_interpreter(iid)
    items = [w for w in DB.availability_windows.values()
             if w["interpreter_id"] == iid]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_window(w) for w in page], pagination=meta)


@bp.route("/interpreters/<iid>/availability-windows/<wid>", methods=["DELETE"])
def delete_window(iid, wid):
    auth = auth_ctx()
    require_role(auth[1], "Interpreter")
    check_ownership(auth[0] == iid)
    get_interpreter(iid)
    window = DB.availability_windows.get(wid)
    if window is None or window["interpreter_id"] != iid:
        err(core.E_WINDOW_NF, 404, f"Availability window {wid} not found under interpreter {iid}")
    del DB.availability_windows[wid]
    return "", 204


# --------------------------------------------------------------------------
# Interpreter reverse-lookup listings
# --------------------------------------------------------------------------
@bp.route("/interpreters/<iid>/strikes", methods=["GET"])
def interpreter_strikes(iid):
    auth_ctx()
    get_interpreter(iid)
    status = core.request.args.get("status")
    items = [s for s in DB.strikes.values() if s["interpreter_id"] == iid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_strike(s) for s in page], pagination=meta)


@bp.route("/interpreters/<iid>/complaints", methods=["GET"])
def interpreter_complaints(iid):
    auth_ctx()
    get_interpreter(iid)
    status = core.request.args.get("status")
    items = [c for c in DB.complaints.values() if c["interpreter_id"] == iid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_complaint(c) for c in page], pagination=meta)


# --------------------------------------------------------------------------
# StrikeRecord
# --------------------------------------------------------------------------
@bp.route("/strikes", methods=["POST"])
def create_strike():
    auth = auth_ctx()
    body = get_body(allowed_fields={"interpreter_id", "occurred_at",
                                    "assignment_id"}, require=True)
    require_role(auth[1], "PlatformAdmin")
    iid = req_str(body, "interpreter_id")
    occurred_at = req_dt(body, "occurred_at")
    assignment_id = body.get("assignment_id")
    if assignment_id is not None and not isinstance(assignment_id, str):
        err(core.E_INVALID, 400, "Field 'assignment_id' must be a string")
    get_interpreter(iid)
    if assignment_id is not None:
        from domain import get_assignment
        get_assignment(assignment_id)
    if occurred_at > now():
        err(core.E_INVALID, 400, "Field 'occurred_at' must not lie in the future")
    strike = record_strike(iid, occurred_at, assignment_id)
    return envelope(ser_strike(strike), code=201)


@bp.route("/strikes/<sid>/rescind", methods=["POST"])
def rescind_strike(sid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    strike = get_strike(sid)
    if strike["status"] != "ACTIVE":
        err(core.E_STRIKE_NOT_ACTIVE, 409, "Strike is not ACTIVE")
    strike["status"] = "RESCINDED"
    strike["rescinded_at"] = now()
    return envelope(ser_strike(strike))
