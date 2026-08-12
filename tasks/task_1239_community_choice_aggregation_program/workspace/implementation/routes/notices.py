"""EnrollmentNotice waves and OptOutRequest audit-trail endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import (ApiError, ERR_AUTHORITY_POSTURE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NO_DEFAULT_PRODUCT,
                    ERR_REFERENCED_NOT_FOUND, ERR_REFERENTIAL_STATE,
                    ERR_STALE_AUTHORITY_VERSION, ERR_STATUTE_WINDOW_VIOLATION)
from serializers import ser_notice, ser_opt_out
from services import (ENROLLMENT_LAG_DAYS, NOTICE_COOLING_OFF_DAYS,
                      default_product_ok, get_or_404)
from store import STORE
from util import (as_enum, as_int, as_list, as_str, fmt_dt, get_body, parse_dt)

bp = Blueprint("notices", __name__)

from routes.accounts import SERVICE_CLASSES

ELECTION_TYPES = {"OPT_OUT", "OPT_BACK_TO_BUNDLED"}
CHANNELS = {"WEB", "PHONE", "MAIL"}


@bp.post("/cca/enrollment-notices")
@require_roles("ProgramOperator")
def create_notice():
    body = get_body(request)
    label = as_str(_present(body, "wave_label"), "wave_label")
    mailed = parse_dt(_present(body, "notice_mailed_on"), "notice_mailed_on")
    classes = as_list(_present(body, "target_service_classes"), "target_service_classes")
    for c in classes:
        as_enum(c, "target_service_classes", SERVICE_CLASSES)
    deadline = mailed + timedelta(days=NOTICE_COOLING_OFF_DAYS)
    effective = deadline + timedelta(days=ENROLLMENT_LAG_DAYS)
    rec = STORE.new_record()
    rec.update({
        "wave_label": label,
        "notice_mailed_on": fmt_dt(mailed),
        "_notice_mailed_on": mailed,
        "opt_out_deadline": fmt_dt(deadline),
        "_opt_out_deadline": deadline,
        "enrollment_effective_on": fmt_dt(effective),
        "_enrollment_effective_on": effective,
        "status": "DRAFT",
        "target_service_classes": list(classes),
        "account_count_noticed": 0,
        "account_count_opted_out": 0,
        "account_count_enrolled": 0,
    })
    STORE.notices[rec["id"]] = rec
    return ok_object(ser_notice(rec), status=201)


def _present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
    return body[field]


@bp.get("/cca/enrollment-notices")
@require_roles("ProgramOperator", "CustomerService", "ComplianceOfficer")
def list_notices():
    items = list(STORE.notices.values())
    st = request.args.get("status")
    if st is not None:
        items = [n for n in items if n["status"] == st]
    items.sort(key=lambda n: (n["_created_dt"], n["_seq"]))
    return paginate(items, ser_notice)


@bp.get("/cca/enrollment-notices/<nid>")
@require_roles("ProgramOperator", "CustomerService", "ComplianceOfficer")
def get_notice(nid):
    return ok_object(ser_notice(get_or_404(STORE.notices, nid, "EnrollmentNotice")))


@bp.post("/cca/enrollment-notices/<nid>/issue")
@require_roles("ProgramOperator")
def issue_notice(nid):
    notice = get_or_404(STORE.notices, nid, "EnrollmentNotice")
    if notice["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Notice in status {notice['status']} cannot be issued")
    auth = STORE.authority()
    if auth is None or auth["status"] != "ACTIVE":
        raise ApiError(ERR_AUTHORITY_POSTURE, 409,
                       "Authority must be ACTIVE to issue a notice wave")
    now = STORE.now()
    if notice["_notice_mailed_on"] < now:
        raise ApiError(ERR_STATUTE_WINDOW_VIOLATION, 422,
                       "notice_mailed_on is earlier than the current logical-clock date")
    if not default_product_ok(notice["_enrollment_effective_on"]):
        raise ApiError(ERR_NO_DEFAULT_PRODUCT, 422,
                       "No ADOPTED default product with an ADOPTED rate schedule covering "
                       "enrollment_effective_on")
    if not notice["target_service_classes"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "target_service_classes must be non-empty")
    body = get_body(request)
    expected = _present(body, "expected_authority_version")
    expected = as_int(expected, "expected_authority_version")
    if expected != auth["version"]:
        raise ApiError(ERR_STALE_AUTHORITY_VERSION, 412,
                       "expected_authority_version does not match the authority's current version")

    # Sweep: PROSPECT, not direct-access, class in target set -> NOTICED.
    count = 0
    accounts = sorted(STORE.accounts.values(), key=lambda a: (a["_created_dt"], a["_seq"]))
    for acct in accounts:
        if (acct["enrollment_state"] == "PROSPECT"
                and not acct["da_eligible"]
                and acct["service_class"] in notice["target_service_classes"]):
            acct["enrollment_state"] = "NOTICED"
            acct["current_enrollment_notice_id"] = notice["id"]
            STORE.touch(acct)
            count += 1
    notice["account_count_noticed"] = count
    notice["status"] = "ISSUED"
    STORE.touch(notice)
    # Issuance increments the Authority version by 1.
    auth["version"] += 1
    auth["updated_at"] = STORE.now_iso()
    auth["_updated_dt"] = STORE.now()
    return ok_object(ser_notice(notice))


@bp.post("/cca/enrollment-notices/<nid>/close")
@require_roles("ProgramOperator")
def close_notice(nid):
    notice = get_or_404(STORE.notices, nid, "EnrollmentNotice")
    if notice["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Notice in status {notice['status']} cannot be closed")
    if STORE.now() < notice["_opt_out_deadline"]:
        raise ApiError(ERR_STATUTE_WINDOW_VIOLATION, 422,
                       "Notice cannot be closed before its opt-out deadline")
    count = 0
    for r in STORE.opt_outs.values():
        if (r["enrollment_notice_id"] == notice["id"]
                and r["election_type"] == "OPT_OUT"
                and r["reversal_of_request_id"] is None):
            reversed_ = any(x["reversal_of_request_id"] == r["id"]
                            for x in STORE.opt_outs.values())
            if not reversed_:
                count += 1
    notice["account_count_opted_out"] = count
    notice["status"] = "CLOSED"
    STORE.touch(notice)
    return ok_object(ser_notice(notice))


@bp.post("/cca/enrollment-notices/<nid>/cancel")
@require_roles("ProgramOperator")
def cancel_notice(nid):
    notice = get_or_404(STORE.notices, nid, "EnrollmentNotice")
    now = STORE.now()
    if notice["status"] == "ISSUED":
        if now >= notice["_opt_out_deadline"]:
            raise ApiError(ERR_STATUTE_WINDOW_VIOLATION, 422,
                           "ISSUED notice may only be cancelled before its opt-out deadline")
    elif notice["status"] == "CLOSED":
        if now >= notice["_enrollment_effective_on"]:
            raise ApiError(ERR_STATUTE_WINDOW_VIOLATION, 422,
                           "CLOSED notice may only be cancelled before enrollment_effective_on")
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Notice in status {notice['status']} cannot be cancelled")
    for acct in STORE.accounts.values():
        if (acct["current_enrollment_notice_id"] == notice["id"]
                and acct["enrollment_state"] == "NOTICED"):
            acct["enrollment_state"] = "PROSPECT"
            acct["current_enrollment_notice_id"] = None
            STORE.touch(acct)
    notice["status"] = "CANCELLED"
    STORE.touch(notice)
    return ok_object(ser_notice(notice))


@bp.get("/cca/enrollment-notices/<nid>/opt-out-requests")
@require_roles("ProgramOperator", "CustomerService")
def notice_opt_outs(nid):
    notice = get_or_404(STORE.notices, nid, "EnrollmentNotice")
    items = [r for r in STORE.opt_outs.values()
             if r["enrollment_notice_id"] == notice["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    return paginate(items, ser_opt_out)


# --- opt-out requests ---------------------------------------------------------

@bp.post("/cca/opt-out-requests")
@require_roles("CustomerService")
def create_opt_out():
    body = get_body(request)
    acct_id = _present(body, "service_account_id")
    notice_id = _present(body, "enrollment_notice_id")
    acct = STORE.accounts.get(acct_id)
    if acct is None:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                       f"ServiceAccount '{acct_id}' not found")
    notice = STORE.notices.get(notice_id)
    if notice is None:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                       f"EnrollmentNotice '{notice_id}' not found")
    reversal_id = body.get("reversal_of_request_id")
    ref = None
    if reversal_id is not None:
        ref = STORE.opt_outs.get(reversal_id)
        if ref is None:
            raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                           f"OptOutRequest '{reversal_id}' not found")
    election_type = _present(body, "election_type")
    if not isinstance(election_type, str) or election_type not in ELECTION_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "election_type must be one of ['OPT_BACK_TO_BUNDLED', 'OPT_OUT']")
    channel = _present(body, "channel")
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "channel must be one of ['MAIL', 'PHONE', 'WEB']")
    now = STORE.now()

    if ref is not None:
        # Rescission of an earlier opt-out before the wave closes.
        if acct["enrollment_state"] != "OPTED_OUT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           f"Account in enrollment_state {acct['enrollment_state']} has no opt-out to rescind")
        if now >= notice["_opt_out_deadline"]:
            raise ApiError(ERR_STATUTE_WINDOW_VIOLATION, 422,
                           "Rescission received after the opt-out deadline")
        if (ref["election_type"] != "OPT_OUT"
                or ref["service_account_id"] != acct["id"]
                or notice_id != acct["current_enrollment_notice_id"]):
            raise ApiError(ERR_REFERENTIAL_STATE, 422,
                           "reversal_of_request_id must reference an OPT_OUT request by this "
                           "account under its governing notice")
        acct["enrollment_state"] = "NOTICED"
        STORE.touch(acct)
    elif election_type == "OPT_OUT":
        if acct["enrollment_state"] != "NOTICED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           f"Account in enrollment_state {acct['enrollment_state']} cannot opt out")
        if now >= notice["_opt_out_deadline"]:
            raise ApiError(ERR_STATUTE_WINDOW_VIOLATION, 422,
                           "Opt-out received after the opt-out deadline")
        if notice_id != acct["current_enrollment_notice_id"]:
            raise ApiError(ERR_REFERENTIAL_STATE, 422,
                           "enrollment_notice_id does not match the notice governing this account")
        acct["enrollment_state"] = "OPTED_OUT"
        STORE.touch(acct)
    else:  # OPT_BACK_TO_BUNDLED
        if acct["enrollment_state"] != "ENROLLED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           f"Account in enrollment_state {acct['enrollment_state']} cannot return to bundled service")
        acct["enrollment_state"] = "OPTED_BACK_TO_BUNDLED"
        STORE.touch(acct)

    rec = STORE.new_record(with_version=False)
    rec.update({
        "service_account_id": acct["id"],
        "enrollment_notice_id": notice["id"],
        "election_type": election_type,
        "received_at": STORE.now_iso(),
        "channel": channel,
        "reversal_of_request_id": reversal_id,
    })
    STORE.opt_outs[rec["id"]] = rec
    return ok_object(ser_opt_out(rec), status=201)


@bp.get("/cca/opt-out-requests")
@require_roles("CustomerService", "ProgramOperator")
def list_opt_outs():
    items = list(STORE.opt_outs.values())
    aid = request.args.get("service_account_id")
    if aid is not None:
        items = [r for r in items if r["service_account_id"] == aid]
    nid = request.args.get("enrollment_notice_id")
    if nid is not None:
        items = [r for r in items if r["enrollment_notice_id"] == nid]
    et = request.args.get("election_type")
    if et is not None:
        items = [r for r in items if r["election_type"] == et]
    rid = request.args.get("reversal_of_request_id")
    if rid is not None:
        items = [r for r in items if r["reversal_of_request_id"] == rid]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    return paginate(items, ser_opt_out)


@bp.get("/cca/opt-out-requests/<rid>")
@require_roles("CustomerService", "ProgramOperator")
def get_opt_out(rid):
    return ok_object(ser_opt_out(get_or_404(STORE.opt_outs, rid, "OptOutRequest")))
