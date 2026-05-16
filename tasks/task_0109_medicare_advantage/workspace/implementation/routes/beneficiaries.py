"""Beneficiary CRUD and mark-deceased endpoints."""
from flask import Blueprint, g, request

from auth import require_roles
from errors import err
from response import ok_array, ok_object
from serializers import serialize_beneficiary
from services.eligibility import compute_eligibility
from store import store
from utils import (
    MBI_RE,
    STATE_RE,
    check_version,
    iso_string,
    optional_field,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_bool,
    require_field,
    require_str,
    stamp_create,
    stamp_update,
)

bp = Blueprint("beneficiaries", __name__)


@bp.route("/beneficiaries", methods=["POST"])
@require_roles("PlanAdmin")
def create_beneficiary():
    body = request.get_json(silent=True) or {}
    full_name = require_str(require_field(body, "full_name"), field="full_name", max_len=100)
    medicare_id = require_field(body, "medicare_id")
    if not isinstance(medicare_id, str) or not MBI_RE.match(medicare_id):
        raise err("ERR_VALIDATION", "medicare_id must be 11 uppercase-alphanumeric chars")
    if medicare_id in store.medicare_ids:
        raise err("ERR_VALIDATION", "medicare_id must be unique")

    state_code = require_field(body, "state_code")
    if not isinstance(state_code, str) or not STATE_RE.match(state_code):
        raise err("ERR_VALIDATION", "state_code must be 2 uppercase letters")

    dob = parse_iso_datetime(require_field(body, "date_of_birth"), field="date_of_birth")
    has_esrd = optional_field(body, "has_esrd", default=False)
    if not isinstance(has_esrd, bool):
        raise err("ERR_VALIDATION", "has_esrd must be boolean")
    has_disability = optional_field(body, "has_disability", default=False)
    if not isinstance(has_disability, bool):
        raise err("ERR_VALIDATION", "has_disability must be boolean")
    raw_ssdi = optional_field(body, "ssdi_start_date", default=None)
    ssdi_dt = parse_iso_datetime(raw_ssdi, field="ssdi_start_date") if raw_ssdi else None

    now_iso = store.now_iso()
    bid = store.new_id()

    beneficiary = {
        "id": bid,
        "full_name": full_name,
        "medicare_id": medicare_id,
        "state_code": state_code,
        "has_esrd": has_esrd,
        "has_disability": has_disability,
        "lifecycle_status": "PRE_ELIGIBLE",
        "_dob_dt": dob,
        "_ssdi_dt": ssdi_dt,
        "_deceased_dt": None,
    }
    stamp_create(beneficiary, store_now_iso=now_iso)

    elig = compute_eligibility(beneficiary)
    beneficiary["_elig_dt"] = elig["medicare_eligibility_date"]
    beneficiary["_iep_start_dt"] = elig["iep_start_date"]
    beneficiary["_iep_end_dt"] = elig["iep_end_date"]

    store.beneficiaries[bid] = beneficiary
    store.medicare_ids.add(medicare_id)

    # Create the companion IEP EnrollmentPeriod. PRD §3.1: "This period
    # begins in SCHEDULED status." PRD §3.2: "the lifecycle of every
    # enrollment period is driven by the test clock" — at intake, the
    # current clock determines whether the IEP period is SCHEDULED, OPEN,
    # or CLOSED, and the beneficiary's lifecycle_status is set
    # accordingly (PRE_ELIGIBLE / IEP_OPEN / IEP_CLOSED).
    now_dt = store.clock
    iep_start = elig["iep_start_date"]
    iep_end = elig["iep_end_date"]
    if now_dt < iep_start:
        period_status = "SCHEDULED"
    elif iep_start <= now_dt <= iep_end:
        period_status = "OPEN"
    else:
        period_status = "CLOSED"

    period_id = store.new_id()
    period = {
        "id": period_id,
        "beneficiary_id": bid,
        "period_type": "IEP",
        "status": period_status,
        "consumed_by_enrollment_id": None,
        "_window_start_dt": iep_start,
        "_window_end_dt": iep_end,
    }
    stamp_create(period, store_now_iso=now_iso)
    store.enrollment_periods[period_id] = period

    # Mirror the period status onto beneficiary lifecycle_status.
    if period_status == "OPEN":
        beneficiary["lifecycle_status"] = "IEP_OPEN"
        stamp_update(beneficiary, store_now_iso=now_iso)
    elif period_status == "CLOSED":
        beneficiary["lifecycle_status"] = "IEP_CLOSED"
        stamp_update(beneficiary, store_now_iso=now_iso)

    return ok_object(serialize_beneficiary(beneficiary), status=201)


@bp.route("/beneficiaries/<bid>", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_beneficiary(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    if g.role == "Beneficiary" and g.user_id != bid:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own record")
    return ok_object(serialize_beneficiary(b))


@bp.route("/beneficiaries", methods=["GET"])
@require_roles("PlanAdmin", "Auditor")
def list_beneficiaries():
    limit, offset = parse_pagination(request.args)
    lifecycle = request.args.get("lifecycle_status")
    state_filter = request.args.get("state_code")

    items = sorted(store.beneficiaries.values(), key=lambda b: b["created_at"])
    if lifecycle:
        items = [b for b in items if b["lifecycle_status"] == lifecycle]
    if state_filter:
        items = [b for b in items if b["state_code"] == state_filter]

    page, pagination = paginate(items, limit, offset)
    return ok_array([serialize_beneficiary(b) for b in page], pagination)


@bp.route("/beneficiaries/<bid>/mark-deceased", methods=["POST"])
@require_roles("PlanAdmin")
def mark_deceased(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    body = request.get_json(silent=True) or {}
    if b["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is already deceased")
    check_version(body, b["version"])

    now_iso = store.now_iso()
    now = store.clock

    # Lifecycle transition
    b["lifecycle_status"] = "DECEASED"
    b["_deceased_dt"] = now
    stamp_update(b, store_now_iso=now_iso)

    # Cascade: terminate ACTIVE enrollments
    for e in store.enrollments.values():
        if e["beneficiary_id"] == bid and e["status"] == "ACTIVE":
            e["status"] = "TERMINATED"
            e["_termination_dt"] = now
            stamp_update(e, store_now_iso=now_iso)

    # Cancel APPLIED/UNDERWRITING/ISSUED MedigapPolicy
    for m in store.medigap_policies.values():
        if m["beneficiary_id"] == bid and m["status"] in ("APPLIED", "UNDERWRITING", "ISSUED"):
            m["status"] = "CANCELLED"
            stamp_update(m, store_now_iso=now_iso)

    # Reverse SUBMITTED drug claims
    for c in store.drug_claims.values():
        if c["beneficiary_id"] == bid and c["status"] == "SUBMITTED":
            c["status"] = "REVERSED"
            # DrugClaim only carries id/created_at; no updated_at/version updates

    return ok_object(serialize_beneficiary(b))
