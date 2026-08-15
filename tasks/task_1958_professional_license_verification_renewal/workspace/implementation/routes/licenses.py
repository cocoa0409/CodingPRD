"""License inventory and primary-source verification endpoints (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, current_date, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import license_view, verification_event_view
from services import (
    compute_screening_posture,
    invalidate_sealed_packages,
    refresh_employee_derived,
    refresh_license_derived,
    touch,
)
from util import as_date, as_enum, as_str, body, pagination_args, parse_ymd, required

bp = Blueprint("licenses", __name__, url_prefix="/licensing")

VERIFICATION_SOURCES = ("STATE_BOARD_API", "MANUAL_UPLOAD", "NURSYS")
VERIFICATION_OUTCOMES = ("VERIFIED", "MISMATCH", "UNREACHABLE")


@bp.post("/licenses")
def create_license():
    user_id, role = auth(["ComplianceOfficer"])
    data = body()
    # Pull raw FK fields first: body-FK existence precedes field-domain checks
    # (PRD 2.8 steps 4-5), but the values must at least be strings to look up.
    employee_id = required(data, "employee_id")
    license_type_id = required(data, "license_type_id")
    if not isinstance(employee_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "employee_id must be a string")
    if not isinstance(license_type_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "license_type_id must be a string")
    if employee_id not in DB["employees"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced employee does not exist")
    if license_type_id not in DB["license_types"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced license type does not exist")

    state_code = as_str(required(data, "state_code"), "state_code")
    license_number = as_str(required(data, "license_number"), "license_number")
    issued = as_date(required(data, "issued_on"), "issued_on")
    expires = as_date(required(data, "expires_on"), "expires_on")

    # Safety gate: a CONFIRMED_MATCH screening bars new license registration.
    if compute_screening_posture(employee_id) == "FLAGGED":
        raise ApiError(
            "ERR_EMPLOYEE_SCREENING_FLAGGED", 403,
            "Employee has a confirmed exclusion-list match",
        )

    # Uniqueness: per-holder (employee_id, license_type_id, state_code).
    for lic in DB["licenses"].values():
        if (
            lic["employee_id"] == employee_id
            and lic["license_type_id"] == license_type_id
            and lic["state_code"] == state_code
        ):
            raise ApiError(
                "ERR_DUPLICATE_LICENSE", 409,
                "A license already exists for this (employee, license type, state)",
            )

    # Validity dates: order matters — expires strictly after issued first,
    # then the 730-day window.
    if expires <= issued:
        raise ApiError(
            "ERR_INVALID_DATES", 422, "expires_on must be after issued_on"
        )
    if (expires - issued).days > 730:
        raise ApiError(
            "ERR_VALIDITY_WINDOW_EXCEEDED", 422,
            "expires_on exceeds issued_on + 730 days",
        )

    ts = now_iso()
    lic = {
        "id": new_id(),
        "employee_id": employee_id,
        "license_type_id": license_type_id,
        "state_code": state_code,
        "license_number": license_number,
        "issued_on": issued.isoformat(),
        "expires_on": expires.isoformat(),
        "status": "PENDING_VERIFICATION",
        "last_verified_on": None,
        "next_verification_due_on": None,
        "verification_posture": "NEVER_VERIFIED",
        "alert_tier": "NONE",
        "ce_cycle_anchor_on": issued.isoformat(),
        "cycle_ce_hours_validated": 0,
        "rolling_ce_hours_validated": 0,
        "ce_progress_reported_pct": None,
        "ce_progress_required_pct": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["licenses"][lic["id"]] = lic
    refresh_license_derived(lic)
    # Registration re-derives the holder's authorization; a PENDING_VERIFICATION
    # row does not satisfy a mandatory matrix row, so MISSING_LICENSE persists.
    emp = DB["employees"][employee_id]
    refresh_employee_derived(emp, bump=True)
    return ok(license_view(lic), status=201)


@bp.get("/licenses")
def list_licenses():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted(DB["licenses"].values(), key=lambda x: x["created_at"])
    views = [license_view(x) for x in items]  # refresh before filtering
    employee_id = request.args.get("employee_id")
    license_type_id = request.args.get("license_type_id")
    state_code = request.args.get("state_code")
    status = request.args.get("status")
    posture = request.args.get("verification_posture")
    tier = request.args.get("alert_tier")
    if employee_id is not None:
        views = [v for v in views if v["employee_id"] == employee_id]
    if license_type_id is not None:
        views = [v for v in views if v["license_type_id"] == license_type_id]
    if state_code is not None:
        views = [v for v in views if v["state_code"] == state_code]
    if status is not None:
        views = [v for v in views if v["status"] == status]
    if posture is not None:
        views = [v for v in views if v["verification_posture"] == posture]
    if tier is not None:
        views = [v for v in views if v["alert_tier"] == tier]
    total = len(views)
    page = views[offset:offset + limit]
    return ok_list(page, total, limit, offset)


@bp.get("/licenses/<lid>")
def get_license(lid):
    auth(ALL_ROLES)
    lic = DB["licenses"].get(lid)
    if lic is None:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    return ok(license_view(lic))


@bp.post("/licenses/<lid>/verify")
def verify_license(lid):
    user_id, role = auth(["ComplianceOfficer"])
    lic = DB["licenses"].get(lid)
    if lic is None:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    data = body()
    verified_on = as_date(required(data, "verified_on"), "verified_on")
    source = as_enum(required(data, "source"), "source", VERIFICATION_SOURCES)
    outcome = as_enum(required(data, "outcome"), "outcome", VERIFICATION_OUTCOMES)
    pinned_due = None
    if "next_verification_due_on" in data and data["next_verification_due_on"] is not None:
        pinned_due = as_date(data["next_verification_due_on"], "next_verification_due_on")

    # State gate: SUSPENDED / REVOKED licenses accept no verification at all.
    if lic["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"License in {lic['status']} accepts no verification",
        )

    # Chronology checks (PRD 2.8 step 12).
    if verified_on > current_date() + timedelta(days=1):
        raise ApiError(
            "ERR_INVALID_VERIFICATION_DATE", 422,
            "verified_on is more than one day ahead of the logical clock",
        )
    events = [
        ev for ev in DB["verification_events"].values() if ev["license_id"] == lid
    ]
    if any(ev["verified_on"] == verified_on.isoformat() for ev in events):
        raise ApiError(
            "ERR_DUPLICATE_VERIFICATION", 409,
            "A verification event already exists for this license on that date",
        )
    if lic["status"] == "PENDING_VERIFICATION":
        if parse_ymd(lic["expires_on"]) < verified_on:
            raise ApiError(
                "ERR_INVALID_VERIFICATION_DATE", 422,
                "Cannot verify an already-expired pending license",
            )
    else:
        # Non-pending licenses: strictly after last_verified_on.
        if lic["last_verified_on"] is not None and verified_on <= parse_ymd(
            lic["last_verified_on"]
        ):
            raise ApiError(
                "ERR_VERIFICATION_OUT_OF_ORDER", 422,
                "verified_on must be strictly after last_verified_on",
            )

    lt = DB["license_types"][lic["license_type_id"]]
    status_before = lic["status"]

    if outcome == "VERIFIED":
        if status_before == "PENDING_VERIFICATION":
            lic["status"] = "ACTIVE"
            lic["last_verified_on"] = verified_on.isoformat()
            expires = parse_ymd(lic["expires_on"])
        elif status_before == "ACTIVE":
            lic["last_verified_on"] = verified_on.isoformat()
            expires = max(
                parse_ymd(lic["expires_on"]), verified_on + timedelta(days=365)
            )
            lic["expires_on"] = expires.isoformat()
        else:  # EXPIRED or LAPSED reinstatement — CE gate applies (step 15).
            ce_required = lt["ce_hours_required_per_cycle"]
            if ce_required > 0:
                refresh_license_derived(lic)
                if lic["cycle_ce_hours_validated"] < ce_required:
                    raise ApiError(
                        "ERR_CE_HOURS_INSUFFICIENT", 409,
                        "Validated cycle CE hours are below the license type requirement",
                    )
            lic["status"] = "ACTIVE"
            lic["last_verified_on"] = verified_on.isoformat()
            expires = verified_on + timedelta(days=365)
            lic["expires_on"] = expires.isoformat()
            lic["ce_cycle_anchor_on"] = verified_on.isoformat()

        if pinned_due is not None:
            lic["next_verification_due_on"] = pinned_due.isoformat()
        else:
            lic["next_verification_due_on"] = min(
                verified_on + timedelta(days=lt["verification_frequency_days"]),
                expires,
            ).isoformat()
    else:
        # MISMATCH / UNREACHABLE on a pending license changes nothing but the
        # log; on an ACTIVE license there is likewise no status mutation.
        pass

    refresh_license_derived(lic)
    touch(lic)  # recording a verification increments License.version by 1

    ev_ts = now_iso()
    ev = {
        "id": new_id(),
        "license_id": lid,
        "verified_on": verified_on.isoformat(),
        "source": source,
        "outcome": outcome,
        "verifier_user_id": user_id,
        "next_verification_due_on": lic["next_verification_due_on"],
        "created_at": ev_ts,
    }
    DB["verification_events"][ev["id"]] = ev

    emp = DB["employees"][lic["employee_id"]]
    refresh_employee_derived(emp, bump=True)
    # New evidence invalidates sealed packages covering verified_on.
    invalidate_sealed_packages(lic["employee_id"], verified_on)
    return ok(license_view(lic))


@bp.get("/licenses/<lid>/verification-events")
def list_verification_events(lid):
    auth(ALL_ROLES)
    if lid not in DB["licenses"]:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    limit, offset = pagination_args()
    items = sorted(
        (e for e in DB["verification_events"].values() if e["license_id"] == lid),
        key=lambda x: x["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([verification_event_view(x) for x in page], total, limit, offset)
