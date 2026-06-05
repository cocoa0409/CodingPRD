"""FoiaRequest intake, lifecycle, fees, determinations, Glomar."""

from flask import Blueprint, g

import db
import services
from clock import parse_iso, now
from errors import (
    api_error,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_REQUEST_VERSION, ERR_EXTENSION_ALREADY_USED,
    ERR_WAIVER_INELIGIBLE_COMMERCIAL, ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_GLOMAR_NOT_AUTHORIZED, ERR_GLOMAR_PRECONDITION,
    ERR_EXEMPTION_REQUIRED, ERR_REVERSE_FOIA_PENDING,
    ERR_VALIDATION_NOT_PERFECTED,
)
from helpers import (
    get_json_body, require_str, require_bool, require_enum, require_int,
    require_number, get_or_404, fk_or_404, serialize, parse_pagination,
    sort_by_creation, paginate,
)
from middleware import require_roles
from response import ok_object, ok_array
from flask import request as flask_request

bp = Blueprint("requests", __name__)

FEE_CATEGORIES = {"COMMERCIAL", "EDUCATIONAL", "NEWS_MEDIA", "OTHER"}
DETERMINATION_STATES = {"GRANTED", "PARTIALLY_GRANTED", "DENIED", "GLOMAR_INVOKED"}


# ---- Submit / fetch / list -------------------------------------------------
@bp.post("/requests")
def submit_request():
    require_roles("Requester", "FoiaOfficer")
    body = get_json_body()
    # Body-FK existence (priority 5) is checked before the remaining structural
    # validity of the body (priority 6), per PRD §2.6.
    requester_id = require_str(body, "requester_id")
    fk_or_404(db.requesters, requester_id)
    subject_description = require_str(body, "subject_description")
    received_at = require_str(body, "received_at")
    expedited = require_bool(body, "expedited", default=False)
    fee_waiver_requested = require_bool(body, "fee_waiver_requested", default=False)
    if parse_iso(received_at) is None:
        raise api_error(ERR_INVALID_REQUEST, "received_at must be a valid ISO 8601 instant.")

    obj = {
        "requester_id": requester_id,
        "assigned_officer_id": None,
        "subject_description": subject_description,
        "fee_category": None,
        "expedited": expedited,
        "fee_waiver_requested": fee_waiver_requested,
        "fee_waiver_granted": False,
        "status": "SUBMITTED",
        "deadline_status": "RUNNING",
        "glomar_exemption_basis": None,
        "fee_payment_status": "NONE",
        "received_at": received_at,
    }
    db.stamp_create(obj)
    db.requests[obj["id"]] = obj
    services.append_audit(obj["id"], "SUBMITTED", "request submitted", g.user_role)
    return ok_object(serialize("FoiaRequest", obj), status=201)


@bp.get("/requests/<rid>")
def get_request(rid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.requests, rid)
    return ok_object(serialize("FoiaRequest", obj), status=200)


@bp.get("/requests")
def list_requests():
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    limit, offset = parse_pagination()
    requester_id = flask_request.args.get("requester_id")
    assigned_officer_id = flask_request.args.get("assigned_officer_id")
    status = flask_request.args.get("status")
    items = list(db.requests.values())
    if requester_id is not None:
        items = [r for r in items if r["requester_id"] == requester_id]
    if assigned_officer_id is not None:
        items = [r for r in items if r["assigned_officer_id"] == assigned_officer_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_creation(items)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("FoiaRequest", r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


# ---- Perfect ---------------------------------------------------------------
@bp.post("/requests/<rid>/perfect")
def perfect_request(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    body = get_json_body()
    fee_category = require_enum(body, "fee_category", FEE_CATEGORIES)
    if req["status"] != "SUBMITTED":
        raise api_error(ERR_INVALID_STATE, "Request must be SUBMITTED to perfect.")
    if not req["subject_description"] or not req["subject_description"].strip():
        raise api_error(ERR_INVALID_REQUEST, "subject_description must be non-empty.")

    req["fee_category"] = fee_category
    req["status"] = "PERFECTED"
    req["deadline_status"] = "RUNNING"
    db.touch(req)

    base_due = services.compute_base_due_at(req["received_at"])
    deadline = {
        "request_id": rid,
        "base_due_at": base_due,
        "extension_days_added": 0,
        "tolled_working_days": 0,
        "effective_due_at": None,
    }
    services.recompute_effective_due_at(deadline)
    db.stamp_create(deadline)
    db.deadlines[deadline["id"]] = deadline

    services.append_audit(rid, "PERFECTED", "request perfected; clock started", "FoiaOfficer")
    return ok_object(serialize("FoiaRequest", req), status=200)


# ---- Assign ----------------------------------------------------------------
@bp.post("/requests/<rid>/assign")
def assign_request(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    if req["status"] != "PERFECTED":
        # Operation requires a perfected request; still-SUBMITTED is the
        # dedicated not-perfected error (PRD §3.2), other states are generic.
        if req["status"] == "SUBMITTED":
            raise api_error(ERR_VALIDATION_NOT_PERFECTED, "Request must be perfected before assignment.")
        raise api_error(ERR_INVALID_STATE, "Request must be PERFECTED to assign.")
    req["assigned_officer_id"] = g.user_id
    req["status"] = "PROCESSING"
    db.touch(req)
    services.append_audit(rid, "ASSIGNED", "request assigned for processing", "FoiaOfficer")
    return ok_object(serialize("FoiaRequest", req), status=200)


# ---- Extend ----------------------------------------------------------------
@bp.post("/requests/<rid>/extend")
def extend_request(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    if req["status"] != "PROCESSING":
        raise api_error(ERR_INVALID_STATE, "Request must be PROCESSING to extend.")
    deadline = services.get_deadline(rid)
    if deadline is None or deadline["extension_days_added"] != 0:
        raise api_error(ERR_EXTENSION_ALREADY_USED, "Only one extension is permitted.")
    deadline["extension_days_added"] = services.EXTENSION_WORKING_DAYS
    services.recompute_effective_due_at(deadline)
    db.touch(deadline)
    req["deadline_status"] = "EXTENDED"
    db.touch(req)
    services.append_audit(rid, "EXTENDED", "10-working-day extension applied", "FoiaOfficer")
    return ok_object(serialize("FoiaRequest", req), status=200)


# ---- Withdraw --------------------------------------------------------------
@bp.post("/requests/<rid>/withdraw")
def withdraw_request(rid):
    require_roles("Requester")
    req = get_or_404(db.requests, rid)
    if req["requester_id"] != g.user_id:
        raise api_error(ERR_NOT_RESOURCE_OWNER, "Only the owning requester may withdraw.")
    if req["status"] not in ("SUBMITTED", "PERFECTED", "PROCESSING", "AWAITING_PAYMENT"):
        raise api_error(ERR_INVALID_STATE, "Request is not in a withdrawable state.")
    req["status"] = "WITHDRAWN"
    req["deadline_status"] = "MET"
    db.touch(req)
    services.append_audit(rid, "DETERMINATION", "withdrawn by requester", "Requester")
    return ok_object(serialize("FoiaRequest", req), status=200)


# ---- Fee estimate ----------------------------------------------------------
@bp.post("/requests/<rid>/fee-estimate")
def fee_estimate(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    body = get_json_body()
    search_hours = require_number(body, "search_hours", minimum=0)
    review_hours = require_number(body, "review_hours", minimum=0)
    billable_pages = require_int(body, "billable_pages", minimum=0)
    expected_version = require_int(body, "expected_request_version")

    if req["status"] != "PROCESSING":
        raise api_error(ERR_INVALID_STATE, "Request must be PROCESSING to assess a fee.")
    if expected_version != req["version"]:
        raise api_error(ERR_STALE_REQUEST_VERSION, "expected_request_version does not match.")

    assessed, requires_advance = services.assess_fee(
        req["fee_category"], search_hours, review_hours, billable_pages,
        req["fee_waiver_granted"],
    )

    # Single current fee estimate per request: replace the prior one.
    for fe_id in [k for k, v in db.fee_estimates.items() if v["request_id"] == rid]:
        del db.fee_estimates[fe_id]

    fe = {
        "request_id": rid,
        "search_hours": search_hours,
        "review_hours": review_hours,
        "billable_pages": billable_pages,
        "assessed_fee_cents": assessed,
        "requires_advance_payment": requires_advance,
    }
    db.stamp_create(fe)
    db.fee_estimates[fe["id"]] = fe

    # Determine fee posture + tolling.
    if req["fee_waiver_granted"]:
        req["fee_payment_status"] = "WAIVED"
        toll = False
    else:
        req["fee_payment_status"] = "DUE"
        toll = requires_advance

    req["version"] = req["version"] + 1  # version always advances on fee-estimate
    services.append_audit(rid, "FEE_ASSESSED", f"fee assessed: {assessed} cents", "FoiaOfficer")

    if toll:
        req["status"] = "AWAITING_PAYMENT"
        req["deadline_status"] = "TOLLED"
        db.toll_windows[rid] = now()
        services.append_audit(rid, "TOLLED", "advance-payment tolling window opened", "FoiaOfficer")
    # else: stays PROCESSING, deadline_status unchanged

    req["updated_at"] = db.now_iso()
    services.recompute_outstanding_balance(req["requester_id"])
    return ok_object(serialize("FeeEstimate", fe), status=200)


@bp.get("/requests/<rid>/fee-estimate")
def get_fee_estimate(rid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    get_or_404(db.requests, rid)
    items = sort_by_creation([fe for fe in db.fee_estimates.values() if fe["request_id"] == rid])
    return ok_array([serialize("FeeEstimate", fe) for fe in items],
                    limit=10, offset=0, total_count=len(items), has_more=False)


# ---- Fee waiver ------------------------------------------------------------
@bp.post("/requests/<rid>/fee-waiver")
def fee_waiver(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    body = get_json_body()
    f_pu = require_bool(body, "f_public_understanding")
    f_nc = require_bool(body, "f_not_commercial_interest")
    f_mc = require_bool(body, "f_meaningful_contribution")
    f_ad = require_bool(body, "f_ability_to_disseminate")
    expected_version = require_int(body, "expected_request_version")

    if expected_version != req["version"]:
        raise api_error(ERR_STALE_REQUEST_VERSION, "expected_request_version does not match.")
    if req["fee_category"] == "COMMERCIAL":
        raise api_error(ERR_WAIVER_INELIGIBLE_COMMERCIAL, "Commercial requesters are ineligible for a waiver.")

    _score, granted = services.waiver_score(f_pu, f_nc, f_mc, f_ad)
    req["fee_waiver_granted"] = granted
    req["version"] = req["version"] + 1
    req["updated_at"] = db.now_iso()
    services.append_audit(rid, "FEE_ASSESSED", f"fee waiver adjudicated: granted={granted}", "FoiaOfficer")
    return ok_object(serialize("FoiaRequest", req), status=200)


# ---- Payment ---------------------------------------------------------------
@bp.post("/requests/<rid>/payment")
def payment(rid):
    require_roles("Requester")
    req = get_or_404(db.requests, rid)
    if req["requester_id"] != g.user_id:
        raise api_error(ERR_NOT_RESOURCE_OWNER, "Only the owning requester may pay.")
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")

    if req["status"] != "AWAITING_PAYMENT" or req["fee_payment_status"] != "DUE":
        raise api_error(ERR_INVALID_STATE, "Request must be AWAITING_PAYMENT with a DUE fee.")

    fe = services.current_fee_estimate(rid)
    assessed = fe["assessed_fee_cents"] if fe else 0
    if amount_cents != assessed:
        raise api_error(ERR_PAYMENT_AMOUNT_MISMATCH, "Payment must equal the assessed fee; no partial payments.")

    req["fee_payment_status"] = "PAID"
    req["status"] = "PROCESSING"
    req["deadline_status"] = "RUNNING"

    # Close the advance-payment tolling window: accrue elapsed working days.
    deadline = services.get_deadline(rid)
    open_at = db.toll_windows.pop(rid, None)
    if deadline is not None and open_at is not None:
        from clock import working_days_between
        elapsed = working_days_between(open_at, now())
        deadline["tolled_working_days"] = deadline["tolled_working_days"] + elapsed
        services.recompute_effective_due_at(deadline)
        db.touch(deadline)

    db.touch(req)
    services.recompute_outstanding_balance(req["requester_id"])
    services.append_audit(rid, "RESUMED", "advance payment received; clock resumed", "Requester")
    return ok_object(serialize("FoiaRequest", req), status=200)


# ---- Deadline (GET) --------------------------------------------------------
@bp.get("/requests/<rid>/deadline")
def get_deadline(rid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    get_or_404(db.requests, rid)
    items = sort_by_creation([d for d in db.deadlines.values() if d["request_id"] == rid])
    return ok_array([serialize("ProcessingDeadline", d) for d in items],
                    limit=10, offset=0, total_count=len(items), has_more=False)


# ---- Determination ---------------------------------------------------------
@bp.post("/requests/<rid>/determination")
def determination(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    body = get_json_body()
    expected_version = require_int(body, "expected_request_version")

    if req["status"] != "PROCESSING":
        raise api_error(ERR_INVALID_STATE, "Request must be PROCESSING to issue a determination.")
    if expected_version != req["version"]:
        raise api_error(ERR_STALE_REQUEST_VERSION, "expected_request_version does not match.")

    recs = services.records_for_request(rid)
    dispositions = [r["disposition"] for r in recs]

    # Reverse-FOIA gate: no submitter-info record may be RELEASABLE while its
    # objection is NOTICED or OBJECTED (applies across all branches).
    for r in recs:
        if r["disposition"] == "RELEASABLE" and r.get("contains_submitter_info"):
            obj = services.objection_for_record(r["id"])
            if obj is not None and obj["status"] in ("NOTICED", "OBJECTED"):
                raise api_error(ERR_REVERSE_FOIA_PENDING,
                                "Cannot release a submitter-info record with a pending objection.")

    # Exemption-citation gate: every REDACTED/WITHHELD record needs a record-level
    # exemption citing it.
    for r in recs:
        if r["disposition"] in ("REDACTED", "WITHHELD"):
            if not services.record_has_record_exemption(r["id"]):
                raise api_error(ERR_EXEMPTION_REQUIRED,
                                "A withheld/redacted record must be cited by an exemption.")

    # Outcome derivation (PRD §3.6).
    all_releasable = len(dispositions) > 0 and all(d == "RELEASABLE" for d in dispositions)
    all_withheld = len(dispositions) > 0 and all(d == "WITHHELD" for d in dispositions)
    has_disclosure = any(d in ("REDACTED", "RELEASABLE") for d in dispositions)
    has_withholding = any(d in ("REDACTED", "WITHHELD") for d in dispositions)
    is_partial = has_disclosure and has_withholding

    if all_releasable:
        new_status = "GRANTED"
        detail = "full grant"
    elif all_withheld:
        new_status = "DENIED"
        detail = "full denial"
    elif is_partial:
        new_status = "PARTIALLY_GRANTED"
        detail = "partial grant"
    else:
        # No coherent determination branch (e.g. no records, or only PENDING).
        raise api_error(ERR_INVALID_STATE, "Record dispositions do not support a determination.")

    req["status"] = new_status
    req["version"] = req["version"] + 1
    deadline = services.get_deadline(rid)
    if deadline is not None:
        req["deadline_status"] = services.deadline_outcome(deadline)
    else:
        req["deadline_status"] = "MET"
    req["_determination_at"] = now()  # internal: anchors the appeal window
    req["updated_at"] = db.now_iso()
    services.append_audit(rid, "DETERMINATION", detail, "FoiaOfficer")
    return ok_object(serialize("FoiaRequest", req), status=200)


# ---- Glomar ----------------------------------------------------------------
@bp.post("/requests/<rid>/glomar")
def glomar(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    body = get_json_body()
    expected_version = require_int(body, "expected_request_version")

    if req["status"] != "PROCESSING":
        raise api_error(ERR_INVALID_STATE, "Request must be PROCESSING to invoke Glomar.")
    if expected_version != req["version"]:
        raise api_error(ERR_STALE_REQUEST_VERSION, "expected_request_version does not match.")

    officer = db.officers.get(g.user_id)
    if officer is None or not officer.get("can_invoke_glomar"):
        raise api_error(ERR_GLOMAR_NOT_AUTHORIZED, "Acting officer is not cleared to invoke Glomar.")

    recs = services.records_for_request(rid)
    req_level = [e for e in services.exemptions_for_request(rid)
                 if e["applies_to_kind"] == "REQUEST" and e["exemption_code"] in ("B1", "B7")]
    if len(recs) != 0 or len(req_level) != 1:
        raise api_error(ERR_GLOMAR_PRECONDITION,
                        "Glomar requires zero records and exactly one REQUEST-level B1/B7 exemption.")

    req["status"] = "GLOMAR_INVOKED"
    req["glomar_exemption_basis"] = req_level[0]["exemption_code"]
    req["version"] = req["version"] + 1
    deadline = services.get_deadline(rid)
    if deadline is not None:
        req["deadline_status"] = services.deadline_outcome(deadline)
    else:
        req["deadline_status"] = "MET"
    req["_determination_at"] = now()
    req["updated_at"] = db.now_iso()
    services.append_audit(rid, "GLOMAR", "Glomar response invoked", "FoiaOfficer")
    return ok_object(serialize("FoiaRequest", req), status=200)
