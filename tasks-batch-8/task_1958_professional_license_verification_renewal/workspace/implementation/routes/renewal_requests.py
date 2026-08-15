"""Renewal reimbursement pipeline endpoints (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, current_date, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import renewal_request_view
from services import (
    EMPLOYER_COMMITTED_CAP_CENTS,
    EMPLOYER_PAID_CAP_CENTS,
    invalidate_sealed_packages,
    refresh_employee_derived,
    touch,
)
from util import as_int, as_str, body, pagination_args, required, round_half_up_int

bp = Blueprint("renewal_requests", __name__, url_prefix="/licensing")


def _compute_estimate(lt, claimed):
    """reimbursement_estimate calculation (PRD 3.6): mode-dependent variants."""
    if lt["reimbursement_mode"] == "FLAT_SCHEDULE":
        return min(lt["flat_schedule_amount_cents"], claimed)
    # RECEIPT_BASED: 100% band up to the full ceiling, then a half band up to
    # the half ceiling (half band rounds half up to a whole cent when odd).
    full_cap = lt["reimburse_full_up_to_cents"]
    half_cap = lt["reimburse_half_up_to_cents"]
    half_band = max(0, min(claimed, half_cap) - full_cap)
    half_value = round_half_up_int(Decimal(half_band) * Decimal("0.5"))
    tiered_total = full_cap + half_value
    return min(claimed, tiered_total)


def _get_license_of(req):
    return DB["licenses"][req["license_id"]]


def _get_employee_of(req):
    return DB["employees"][_get_license_of(req)["employee_id"]]


@bp.post("/licenses/<lid>/renewal-requests")
def create_renewal_request(lid):
    user_id, role = auth(["Employee", "ComplianceOfficer"])
    lic = DB["licenses"].get(lid)
    if lic is None:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    # Employee actors act only on their own licenses.
    if role == "Employee" and lic["employee_id"] != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Employee does not own the target license"
        )
    data = body()
    claimed = as_int(required(data, "claimed_amount_cents"), "claimed_amount_cents")
    if claimed < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "claimed_amount_cents must be >= 0"
        )
    expected_version = as_int(
        required(data, "expected_license_version"), "expected_license_version"
    )

    # OCC guard (PRD 2.7): the only version-guarded operation in the API.
    if expected_version != lic["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_license_version does not match the license's current version",
        )

    lt = DB["license_types"][lic["license_type_id"]]
    if claimed > lt["hard_claim_cap_cents"]:
        raise ApiError(
            "ERR_CLAIM_EXCEEDS_HARD_CAP", 422,
            "claimed_amount_cents exceeds the license type's hard claim cap",
        )

    ts = now_iso()
    req = {
        "id": new_id(),
        "license_id": lid,
        "claimed_amount_cents": claimed,
        "estimated_reimbursable_cents": _compute_estimate(lt, claimed),
        "expires_on_at_create": lic["expires_on"],
        "approved_amount_cents": None,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "paid_by_user_id": None,
        "paid_on": None,
        "info_note": None,
        "decision_note": None,
        "payment_ref": None,
        "void_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["renewal_requests"][req["id"]] = req
    # The license now carries a dependent draft: its version advances (PRD 3.6).
    touch(lic)
    return ok(renewal_request_view(req), status=201)


@bp.get("/licenses/<lid>/renewal-requests")
def list_renewal_requests(lid):
    auth(ALL_ROLES)
    if lid not in DB["licenses"]:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    limit, offset = pagination_args()
    items = sorted(
        (r for r in DB["renewal_requests"].values() if r["license_id"] == lid),
        key=lambda x: x["created_at"],
    )
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([renewal_request_view(x) for x in page], total, limit, offset)


@bp.get("/renewal-requests/<rid>")
def get_renewal_request(rid):
    auth(ALL_ROLES)
    req = DB["renewal_requests"].get(rid)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Renewal request not found")
    return ok(renewal_request_view(req))


@bp.post("/renewal-requests/<rid>/submit")
def submit_renewal_request(rid):
    user_id, role = auth(["Employee", "ComplianceOfficer"])
    req = DB["renewal_requests"].get(rid)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Renewal request not found")
    lic = _get_license_of(req)
    if role == "Employee" and lic["employee_id"] != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Employee does not own the target license"
        )
    if req["status"] not in ("DRAFT", "MORE_INFO"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Renewal request in {req['status']} cannot be submitted",
        )
    # License-state gates, in order: SUSPENDED first, then renewability.
    if lic["status"] == "SUSPENDED":
        raise ApiError(
            "ERR_LICENSE_SUSPENDED", 403,
            "Renewal submission blocked while the license is SUSPENDED",
        )
    if lic["status"] not in ("ACTIVE", "EXPIRED", "LAPSED"):
        raise ApiError(
            "ERR_LICENSE_NOT_RENEWABLE", 409,
            f"License in {lic['status']} is not renewable",
        )
    # Fiscal gate: first submission commits the claim; resubmission from
    # MORE_INFO re-checks but adds nothing (committed + 0 cannot newly fail).
    emp = _get_employee_of(req)
    refresh_employee_derived(emp)
    newly_committed = req["claimed_amount_cents"] if req["status"] == "DRAFT" else 0
    if (
        emp["reimbursement_committed_cents"] + newly_committed
        > EMPLOYER_COMMITTED_CAP_CENTS
    ):
        raise ApiError(
            "ERR_COMMITTED_CAP_EXCEEDED", 402,
            "Submit would exceed the employer committed-reimbursement cap",
        )
    req["status"] = "SUBMITTED"
    req["submitted_by_user_id"] = user_id
    touch(req)
    refresh_employee_derived(emp, bump=True)
    return ok(renewal_request_view(req))


@bp.post("/renewal-requests/<rid>/request-info")
def request_info(rid):
    user_id, role = auth(["ComplianceOfficer"])
    req = DB["renewal_requests"].get(rid)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Renewal request not found")
    data = body()
    info_note = as_str(required(data, "info_note"), "info_note")
    if req["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Renewal request in {req['status']} cannot be sent back for info",
        )
    req["status"] = "MORE_INFO"
    req["info_note"] = info_note
    touch(req)
    # Committed balance is unchanged by MORE_INFO (claim stays committed).
    return ok(renewal_request_view(req))


@bp.post("/renewal-requests/<rid>/approve")
def approve_renewal_request(rid):
    user_id, role = auth(["ComplianceOfficer"])
    req = DB["renewal_requests"].get(rid)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Renewal request not found")
    if req["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Renewal request in {req['status']} cannot be approved",
        )
    if user_id == req["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SOD_SAME_USER", 403,
            "Approver must differ from the request's submitter",
        )
    emp = _get_employee_of(req)
    refresh_employee_derived(emp)
    approved = min(
        req["estimated_reimbursable_cents"],
        EMPLOYER_PAID_CAP_CENTS - emp["reimbursement_paid_cents"],
    )
    req["approved_amount_cents"] = approved
    req["status"] = "APPROVED"
    req["decided_by_user_id"] = user_id
    touch(req)
    # Committed drops by the disallowed delta (claim minus approved); the
    # counters are recomputed from source state, which applies this exactly.
    refresh_employee_derived(emp, bump=True)
    return ok(renewal_request_view(req))


@bp.post("/renewal-requests/<rid>/reject")
def reject_renewal_request(rid):
    user_id, role = auth(["ComplianceOfficer"])
    req = DB["renewal_requests"].get(rid)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Renewal request not found")
    data = body()
    decision_note = as_str(required(data, "decision_note"), "decision_note")
    if req["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Renewal request in {req['status']} cannot be rejected",
        )
    if user_id == req["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SOD_SAME_USER", 403,
            "Rejecter must differ from the request's submitter",
        )
    req["status"] = "REJECTED"
    req["decided_by_user_id"] = user_id
    req["decision_note"] = decision_note
    touch(req)
    emp = _get_employee_of(req)
    refresh_employee_derived(emp, bump=True)
    return ok(renewal_request_view(req))


@bp.post("/renewal-requests/<rid>/mark-paid")
def mark_paid(rid):
    user_id, role = auth(["HRPartner"])
    req = DB["renewal_requests"].get(rid)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Renewal request not found")
    data = body()
    payment_ref = as_str(required(data, "payment_ref"), "payment_ref")
    if req["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Renewal request in {req['status']} cannot be marked paid",
        )
    req["status"] = "PAID"
    req["paid_by_user_id"] = user_id
    req["paid_on"] = current_date().isoformat()
    req["payment_ref"] = payment_ref
    touch(req)
    emp = _get_employee_of(req)
    refresh_employee_derived(emp, bump=True)
    # A payment is audit-relevant evidence: invalidate sealed packages whose
    # period contains paid_on.
    invalidate_sealed_packages(emp["id"], req["paid_on"])
    return ok(renewal_request_view(req))


@bp.post("/renewal-requests/<rid>/void")
def void_renewal_request(rid):
    user_id, role = auth(["ComplianceAdmin"])
    req = DB["renewal_requests"].get(rid)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Renewal request not found")
    data = body()
    void_reason = as_str(required(data, "void_reason"), "void_reason")
    if req["status"] not in ("DRAFT", "SUBMITTED", "MORE_INFO", "APPROVED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Renewal request in {req['status']} cannot be voided",
        )
    req["status"] = "VOIDED"
    req["void_reason"] = void_reason
    touch(req)
    emp = _get_employee_of(req)
    refresh_employee_derived(emp, bump=True)
    return ok(renewal_request_view(req))
