"""Routes: logical clock, Indenture, Tranche, NoteholderAccount, Position."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_DUPLICATE_CONSTRAINT,
                    ERR_PRINCIPAL_EXCEEDS_POSITION, ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, now_iso, mutate, fmt_ts, CLOCK
from validate import (req_str, req_int, opt_int, req_enum, req_date,
                      parse_datetime)
from domain import (recompute_indenture_outstanding, recompute_posture,
                    sweep, tranches_of)

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    body = get_body()
    to = body.get("to_iso8601")
    dt = parse_datetime(to)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    with LOCK:
        CLOCK["now"] = dt
        sweep()
    return ok({"current_utc": fmt_ts(CLOCK["now"])})


# ---------------------------------------------------------------------------
# Indenture
# ---------------------------------------------------------------------------

@bp.route("/indentures", methods=["POST"])
@require_roles("PlatformAdmin")
def create_indenture():
    body = get_body()
    # Shape validation (rule 26, last). No existence/state/business rules apply.
    name = req_str(body, "name")
    issuer_ref = req_str(body, "issuer_ref")
    governing_law = req_str(body, "governing_law")
    initial_trustee_ref = req_str(body, "initial_trustee_ref")
    admin_fee = req_int(body, "annual_admin_fee_cents")
    ext_rate = req_int(body, "extraordinary_hourly_rate_cents")
    def_rate = req_int(body, "default_hourly_rate_cents")
    with LOCK:
        e = new_entity("indentures")
        e.update({
            "name": name,
            "issuer_ref": issuer_ref,
            "governing_law": governing_law,
            "initial_trustee_ref": initial_trustee_ref,
            "current_trustee_ref": None,
            "status": "DRAFT",
            "annual_admin_fee_cents": admin_fee,
            "extraordinary_hourly_rate_cents": ext_rate,
            "default_hourly_rate_cents": def_rate,
            "outstanding_principal_cents": 0,
            "covenant_posture": "CURRENT",
            "active_default_count": 0,
        })
    return ok(public(e), 201)


@bp.route("/indentures", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_indentures():
    return list_response(DB["indentures"].values(), {
        "status": request.args.get("status"),
        "issuer_ref": request.args.get("issuer_ref"),
    })


@bp.route("/indentures/<iid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_indenture(iid):
    e = DB["indentures"].get(iid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "Indenture not found")
    return ok(public(e))


@bp.route("/indentures/<iid>/activate", methods=["POST"])
@require_roles("PlatformAdmin")
def activate_indenture(iid):
    with LOCK:
        e = DB["indentures"].get(iid)
        if e is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        if e["status"] == "SATISFIED":
            raise_err(ERR_ALREADY_TERMINAL, "Indenture is terminal (SATISFIED)")
        if e["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT indenture can be activated")
        if not tranches_of(iid):
            raise_err(ERR_INVALID_STATE,
                      "Activation requires at least one tranche")
        mutate(e, status="ACTIVE",
               current_trustee_ref=e["initial_trustee_ref"])
    return ok(public(e))


# ---------------------------------------------------------------------------
# Tranche
# ---------------------------------------------------------------------------

@bp.route("/tranches", methods=["POST"])
@require_roles("PlatformAdmin")
def create_tranche():
    body = get_body()
    with LOCK:
        # Rule 4: existence of the payload FK reference.
        indenture_id = body.get("indenture_id")
        ind = DB["indentures"].get(indenture_id) if isinstance(indenture_id, str) else None
        if ind is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        # Rule 5: indenture must be DRAFT or ACTIVE.
        if ind["status"] not in ("DRAFT", "ACTIVE"):
            raise_err(ERR_INVALID_STATE,
                      "Tranches may be created only on DRAFT or ACTIVE indentures")
        # Rule 9: series_code unique within the indenture.
        series = body.get("series_code")
        if isinstance(series, str):
            for t in tranches_of(ind["id"]):
                if t["series_code"] == series:
                    raise_err(ERR_DUPLICATE_CONSTRAINT,
                              "series_code already exists within this indenture")
        # Rule 26: shape.
        req_str(body, "indenture_id")
        series = req_str(body, "series_code")
        original = req_int(body, "original_principal_cents")
        rate = req_int(body, "interest_rate_bps")
        dcc = req_enum(body, "day_count_convention",
                       ["ACT_360", "ACT_365", "THIRTY_360"])
        freq = req_enum(body, "payment_frequency",
                        ["QUARTERLY", "SEMI_ANNUAL", "ANNUAL"])
        maturity = req_date(body, "maturity_date")
        notice = opt_int(body, "notice_period_days", 30)
        e = new_entity("tranches")
        e.update({
            "indenture_id": indenture_id,
            "series_code": series,
            "original_principal_cents": original,
            "outstanding_principal_cents": original,
            "interest_rate_bps": rate,
            "day_count_convention": dcc,
            "payment_frequency": freq,
            "maturity_date": maturity,
            "notice_period_days": notice,
            "status": "ACTIVE",
        })
        recompute_indenture_outstanding(ind)
    return ok(public(e), 201)


@bp.route("/tranches", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_tranches():
    return list_response(DB["tranches"].values(), {
        "indenture_id": request.args.get("indenture_id"),
        "status": request.args.get("status"),
    })


@bp.route("/tranches/<tid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_tranche(tid):
    e = DB["tranches"].get(tid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "Tranche not found")
    return ok(public(e))


# ---------------------------------------------------------------------------
# NoteholderAccount
# ---------------------------------------------------------------------------

@bp.route("/noteholder-accounts", methods=["POST"])
@require_roles("PlatformAdmin")
def create_account():
    body = get_body()
    with LOCK:
        # Rule 9: holder_ref globally unique.
        holder_ref = body.get("holder_ref")
        if isinstance(holder_ref, str):
            for a in DB["noteholder_accounts"].values():
                if a["holder_ref"] == holder_ref:
                    raise_err(ERR_DUPLICATE_CONSTRAINT,
                              "holder_ref already registered")
        holder_ref = req_str(body, "holder_ref")
        legal_name = req_str(body, "legal_name")
        contact_email = req_str(body, "contact_email")
        e = new_entity("noteholder_accounts")
        e.update({
            "holder_ref": holder_ref,
            "legal_name": legal_name,
            "contact_email": contact_email,
            "status": "ACTIVE",
            "total_unpaid_cents": 0,
            "total_received_cents": 0,
        })
    return ok(public(e), 201)


@bp.route("/noteholder-accounts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_accounts():
    return list_response(DB["noteholder_accounts"].values(), {
        "status": request.args.get("status"),
    })


@bp.route("/noteholder-accounts/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_account(aid):
    e = DB["noteholder_accounts"].get(aid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "NoteholderAccount not found")
    return ok(public(e))


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@bp.route("/positions", methods=["POST"])
@require_roles("PlatformAdmin")
def create_position():
    body = get_body()
    with LOCK:
        # Rule 4: payload FK references, left to right.
        tranche_id = body.get("tranche_id")
        tr = DB["tranches"].get(tranche_id) if isinstance(tranche_id, str) else None
        if tr is None:
            raise_err(ERR_NOT_FOUND, "Tranche not found")
        account_id = body.get("noteholder_account_id")
        acc = DB["noteholder_accounts"].get(account_id) if isinstance(account_id, str) else None
        if acc is None:
            raise_err(ERR_NOT_FOUND, "NoteholderAccount not found")
        # Rule 12: aggregate original principal cap.
        new_orig = body.get("original_principal_cents")
        if isinstance(new_orig, int) and not isinstance(new_orig, bool):
            existing = sum(p["original_principal_cents"]
                           for p in DB["positions"].values()
                           if p["tranche_id"] == tr["id"])
            if existing + new_orig > tr["original_principal_cents"]:
                raise_err(ERR_PRINCIPAL_EXCEEDS_POSITION,
                          "Aggregate position principal exceeds tranche size")
        # Rule 26: shape.
        req_str(body, "tranche_id")
        req_str(body, "noteholder_account_id")
        new_orig = req_int(body, "original_principal_cents")
        e = new_entity("positions")
        e.update({
            "tranche_id": tranche_id,
            "noteholder_account_id": account_id,
            "original_principal_cents": new_orig,
            "principal_amount_cents": new_orig,
            "principal_history": [{
                "effective_from": now_iso(),
                "principal_cents": new_orig,
            }],
            "status": "ACTIVE",
        })
    return ok(public(e), 201)


@bp.route("/positions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_positions():
    return list_response(DB["positions"].values(), {
        "tranche_id": request.args.get("tranche_id"),
        "noteholder_account_id": request.args.get("noteholder_account_id"),
        "status": request.args.get("status"),
    })


@bp.route("/positions/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_position(pid):
    e = DB["positions"].get(pid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "Position not found")
    return ok(public(e))
