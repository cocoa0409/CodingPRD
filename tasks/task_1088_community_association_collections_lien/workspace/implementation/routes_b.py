"""Routes: liens, foreclosure-referrals, bankruptcy-cases, remittances."""
from datetime import timedelta

from flask import Blueprint, request

import store as S
import services as SV
import lookups as L
from web import (
    ApiError, authenticate, require_role, body, parse_pagination, paginate,
    success, list_response, require_str, require_int, require_datetime,
    require_enum,
)

bp_b = Blueprint("bp_b", __name__)

ALL_ROLES = {"CollectionsAgent", "ComplianceOfficer", "TrustAccountant", "AssociationManager"}
LIEN_STATUSES = {"RECORDED", "STAYED", "FORECLOSING", "RELEASED"}
REFERRAL_STATUSES = {"REFERRED", "FILED", "STAYED", "SALE_COMPLETED", "WITHDRAWN"}
BANKRUPTCY_STATUSES = {"FILED", "DISCHARGED", "DISMISSED"}
REMITTANCE_STATUSES = {"PENDING", "REMITTED", "VOID"}


def _child_list(all_items, role, uid, account_id, status, extra_filter=None):
    items = list(all_items)
    if account_id is not None:
        L.scope_child_by_account(role, uid, account_id)
        items = [x for x in items if x["account_id"] == account_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if extra_filter is not None:
        items = [x for x in items if extra_filter(x)]
    if role == "AssociationManager":
        items = [x for x in items if S.association_of_account(x["account_id"]) == uid]
    return items


# ==========================================================================
# liens
# ==========================================================================
@bp_b.route("/collections/liens", methods=["POST"])
def create_lien():
    uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    account_id = require_str(data, "account_id")
    acc = L.get_account(account_id)
    now = S.now_dt()
    # stay
    if acc["status"] == "BANKRUPTCY":
        raise ApiError("ERR_AUTOMATIC_STAY", 403, "Account under automatic stay")
    # dispute
    if any(n["status"] == "DISPUTED" for n in S.account_notices(acc["id"])):
        raise ApiError("ERR_ACTIVE_DISPUTE", 409, "Active dispute on account")
    # predecessor: a SENT INTENT_TO_LIEN notice must exist
    sent_intents = [n for n in S.account_notices(acc["id"])
                    if n["notice_type"] == "INTENT_TO_LIEN" and n["status"] == "SENT"]
    if not sent_intents:
        raise ApiError("ERR_DEMAND_NOTICE_REQUIRED", 409, "SENT INTENT_TO_LIEN notice required")
    # validation-period elapse
    elapsed = any(
        n["sent_date"] and (now - S.parse_iso(n["sent_date"])) >= timedelta(days=S.VALIDATION_PERIOD_DAYS)
        for n in sent_intents
    )
    if not elapsed:
        raise ApiError("ERR_VALIDATION_PERIOD_ACTIVE", 409, "Validation period not elapsed")
    # lien minimum
    total_balance = S.account_total_balance(acc["id"])
    if total_balance < S.LIEN_MINIMUM_BALANCE_CENTS:
        raise ApiError("ERR_LIEN_MINIMUM_NOT_MET", 422, "Balance below lien minimum")
    lien = {
        "account_id": account_id,
        "recorded_amount_cents": total_balance,
        "recorded_date": S.now_date(),
        "recorded_by_user_id": uid,
        "status": "RECORDED",
    }
    S.stamp_new(lien)
    S.liens[lien["id"]] = lien
    SV.set_account_status(acc, "LIEN")
    return success(S.ser_lien(lien), 201)


@bp_b.route("/collections/liens/<lien_id>", methods=["GET"])
def get_lien_ep(lien_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    l = L.get_lien(lien_id)
    L.scope_child_by_account(role, uid, l["account_id"])
    return success(S.ser_lien(l), 200)


@bp_b.route("/collections/liens", methods=["GET"])
def list_liens():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = _child_list(S.liens.values(), role, uid, account_id, status)
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_lien(x) for x in page], total, limit, offset)


@bp_b.route("/collections/liens/<lien_id>/transition", methods=["POST"])
def lien_transition(lien_id):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    l = L.get_lien(lien_id)
    data = body()
    to_status = require_enum(data, "to_status", LIEN_STATUSES)
    if to_status == "RELEASED":
        if l["status"] != "RECORDED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only RECORDED liens can be released")
        l["status"] = "RELEASED"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Status is system-managed")
    S.touch(l)
    return success(S.ser_lien(l), 200)


# ==========================================================================
# foreclosure referrals
# ==========================================================================
@bp_b.route("/collections/foreclosure-referrals", methods=["POST"])
def create_referral():
    uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    account_id = require_str(data, "account_id")
    acc = L.get_account(account_id)
    lien_id = require_str(data, "lien_id")
    lien = L.get_lien(lien_id)
    # SoD (maker-checker)
    if lien["recorded_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Referrer must differ from lien recorder")
    # stay
    if acc["status"] == "BANKRUPTCY":
        raise ApiError("ERR_AUTOMATIC_STAY", 403, "Account under automatic stay")
    # dispute
    if any(n["status"] == "DISPUTED" for n in S.account_notices(acc["id"])):
        raise ApiError("ERR_ACTIVE_DISPUTE", 409, "Active dispute on account")
    # predecessor: a RECORDED lien must exist on the account
    if not any(x["status"] == "RECORDED" for x in S.account_liens(acc["id"])):
        raise ApiError("ERR_LIEN_REQUIRED", 409, "A RECORDED lien is required")
    attorney_name = require_str(data, "attorney_name")
    r = {
        "account_id": account_id,
        "lien_id": lien_id,
        "attorney_name": attorney_name,
        "referred_by_user_id": uid,
        "referred_date": S.now_date(),
        "status": "REFERRED",
    }
    S.stamp_new(r)
    S.referrals[r["id"]] = r
    return success(S.ser_referral(r), 201)


@bp_b.route("/collections/foreclosure-referrals/<referral_id>", methods=["GET"])
def get_referral_ep(referral_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    r = L.get_referral(referral_id)
    L.scope_child_by_account(role, uid, r["account_id"])
    return success(S.ser_referral(r), 200)


@bp_b.route("/collections/foreclosure-referrals", methods=["GET"])
def list_referrals():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    account_id = request.args.get("account_id")
    lien_id = request.args.get("lien_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    extra = (lambda x: x["lien_id"] == lien_id) if lien_id is not None else None
    items = _child_list(S.referrals.values(), role, uid, account_id, status, extra)
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_referral(x) for x in page], total, limit, offset)


@bp_b.route("/collections/foreclosure-referrals/<referral_id>/transition", methods=["POST"])
def referral_transition(referral_id):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    r = L.get_referral(referral_id)
    data = body()
    to_status = require_enum(data, "to_status", REFERRAL_STATUSES)
    acc = S.accounts[r["account_id"]]
    lien = S.liens.get(r["lien_id"])

    if to_status == "FILED":
        if r["status"] != "REFERRED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only REFERRED can be filed")
        if lien is None or lien["status"] != "RECORDED":
            raise ApiError("ERR_INVALID_STATE", 409, "Referenced lien not RECORDED")
        if acc["status"] == "BANKRUPTCY":
            raise ApiError("ERR_AUTOMATIC_STAY", 403, "Account under automatic stay")
        r["status"] = "FILED"
        SV.set_account_status(acc, "FORECLOSURE")
        lien["status"] = "FORECLOSING"
        S.touch(lien)
    elif to_status == "SALE_COMPLETED":
        if r["status"] != "FILED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only FILED can complete sale")
        if acc["status"] == "BANKRUPTCY":
            raise ApiError("ERR_AUTOMATIC_STAY", 403, "Account under automatic stay")
        r["status"] = "SALE_COMPLETED"
        SV.set_account_status(acc, "CHARGED_OFF")
        SV.waive_open_assessments(acc)
        if lien is not None and lien["status"] == "FORECLOSING":
            lien["status"] = "RELEASED"
            S.touch(lien)
    elif to_status == "WITHDRAWN":
        if r["status"] == "REFERRED":
            r["status"] = "WITHDRAWN"
            if lien is not None and lien["status"] == "FORECLOSING":
                lien["status"] = "RELEASED"
                S.touch(lien)
        elif r["status"] == "FILED":
            r["status"] = "WITHDRAWN"
            SV.set_account_status(acc, "DELINQUENT")
            if lien is not None and lien["status"] == "FORECLOSING":
                lien["status"] = "RECORDED"
                S.touch(lien)
        else:
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot withdraw from this state")
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Status is system-managed")
    S.touch(r)
    return success(S.ser_referral(r), 200)


# ==========================================================================
# bankruptcy cases
# ==========================================================================
@bp_b.route("/collections/bankruptcy-cases", methods=["POST"])
def create_bankruptcy():
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    account_id = require_str(data, "account_id")
    acc = L.get_account(account_id)
    chapter = require_enum(data, "chapter", set(S.CHAPTERS))
    case_number = require_str(data, "case_number")
    filed_date = require_datetime(data, "filed_date")
    b = {
        "account_id": account_id,
        "chapter": chapter,
        "case_number": case_number,
        "filed_date": filed_date,
        "status": "FILED",
    }
    S.stamp_new(b)
    S.bankruptcies[b["id"]] = b
    SV.bankruptcy_filed_cascade(acc)
    return success(S.ser_bankruptcy(b), 201)


@bp_b.route("/collections/bankruptcy-cases/<case_id>", methods=["GET"])
def get_bankruptcy_ep(case_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    b = L.get_bankruptcy(case_id)
    L.scope_child_by_account(role, uid, b["account_id"])
    return success(S.ser_bankruptcy(b), 200)


@bp_b.route("/collections/bankruptcy-cases", methods=["GET"])
def list_bankruptcies():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = _child_list(S.bankruptcies.values(), role, uid, account_id, status)
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_bankruptcy(x) for x in page], total, limit, offset)


@bp_b.route("/collections/bankruptcy-cases/<case_id>/transition", methods=["POST"])
def bankruptcy_transition(case_id):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    b = L.get_bankruptcy(case_id)
    data = body()
    to_status = require_enum(data, "to_status", BANKRUPTCY_STATUSES)
    acc = S.accounts[b["account_id"]]
    if to_status == "DISCHARGED":
        if b["status"] != "FILED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only FILED can be discharged")
        b["status"] = "DISCHARGED"
        SV.bankruptcy_discharge_cascade(acc)
    elif to_status == "DISMISSED":
        if b["status"] != "FILED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only FILED can be dismissed")
        b["status"] = "DISMISSED"
        SV.bankruptcy_dismiss_cascade(acc)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Unsupported transition")
    S.touch(b)
    return success(S.ser_bankruptcy(b), 200)


# ==========================================================================
# remittances
# ==========================================================================
REMIT_READ_ROLES = {"TrustAccountant", "ComplianceOfficer", "AssociationManager"}


@bp_b.route("/collections/remittances", methods=["POST"])
def create_remittance():
    _uid, role = authenticate()
    require_role(role, {"TrustAccountant"})
    data = body()
    association_id = require_str(data, "association_id")
    assoc = L.get_association(association_id)
    # OCC
    eav = data.get("expected_association_version")
    if eav is not None:
        if isinstance(eav, bool) or not isinstance(eav, int):
            raise ApiError("ERR_VALIDATION", 422, "expected_association_version must be an integer")
        if eav != assoc["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "Stale association version")
    # period validity (before enum/presence)
    ps = data.get("period_start")
    pe = data.get("period_end")
    if isinstance(ps, str) and isinstance(pe, str):
        try:
            if S.parse_iso(pe) < S.parse_iso(ps):
                raise ApiError("ERR_PERIOD_INVALID", 422, "period_end before period_start")
        except ApiError:
            raise
        except Exception:
            pass
    # basis enum
    if "basis" in data and data.get("basis") is not None and data.get("basis") not in S.REMITTANCE_BASIS:
        raise ApiError("ERR_INVALID_ENUM", 422, "Invalid basis")
    basis = data.get("basis") or "CASH"
    # presence/typing
    period_start = require_datetime(data, "period_start")
    period_end = require_datetime(data, "period_end")
    if data.get("expected_association_version") is None:
        raise ApiError("ERR_VALIDATION", 422, "expected_association_version is required")
    gross, fee, net = SV.compute_remittance_amounts(assoc, period_start, period_end, basis)
    r = {
        "association_id": association_id,
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
        "gross_amount_cents": gross,
        "management_fee_cents": fee,
        "net_amount_cents": net,
        "status": "PENDING",
    }
    S.stamp_new(r)
    S.remittances[r["id"]] = r
    S.touch(assoc)  # OCC-guarded create advances association version by 1
    return success(S.ser_remittance(r), 201)


@bp_b.route("/collections/remittances/<remittance_id>", methods=["GET"])
def get_remittance_ep(remittance_id):
    uid, role = authenticate()
    require_role(role, REMIT_READ_ROLES)
    r = L.get_remittance(remittance_id)
    L.scope_association(role, uid, r["association_id"])
    return success(S.ser_remittance(r), 200)


@bp_b.route("/collections/remittances", methods=["GET"])
def list_remittances():
    uid, role = authenticate()
    require_role(role, REMIT_READ_ROLES)
    association_id = request.args.get("association_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = list(S.remittances.values())
    if role == "AssociationManager":
        if association_id is not None and association_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "AssociationManager scope violation")
        items = [x for x in items if x["association_id"] == uid]
    elif association_id is not None:
        items = [x for x in items if x["association_id"] == association_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_remittance(x) for x in page], total, limit, offset)


@bp_b.route("/collections/remittances/<remittance_id>/transition", methods=["POST"])
def remittance_transition(remittance_id):
    _uid, role = authenticate()
    require_role(role, {"TrustAccountant"})
    r = L.get_remittance(remittance_id)
    data = body()
    to_status = require_enum(data, "to_status", REMITTANCE_STATUSES)
    assoc = S.associations[r["association_id"]]
    if to_status == "REMITTED":
        if r["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Only PENDING can be remitted")
        if S.association_trust_balance(assoc["id"]) < r["gross_amount_cents"]:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "Insufficient trust balance")
        r["status"] = "REMITTED"
        S.touch(assoc)  # trust position changed
    elif to_status == "VOID":
        if r["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Only PENDING can be voided")
        r["status"] = "VOID"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Unsupported transition")
    S.touch(r)
    return success(S.ser_remittance(r), 200)
