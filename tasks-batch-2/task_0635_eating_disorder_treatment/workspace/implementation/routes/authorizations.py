"""Insurance authorizations, concurrent reviews, appeal, expire, billing
summary (PRD §3.11, §3.12)."""
from flask import Blueprint

import errors
from clock import parse_iso
from db import store
from errors import ApiError
from middleware import require_auth_and_roles
from response import success, list_response
from services import calc
from services.common import (
    base_record,
    check_fk,
    get_json_body,
    get_optional_json_body,
    get_or_404,
    list_collection,
    require_field,
    serialize,
    touch,
    validate_enum,
    validate_int,
    validate_non_empty_string,
    validate_number,
)
from services.domain import (
    approved_windows,
    cascade_auth_to_admission_discharge_pending,
    maybe_exhaust,
    recompute_auth_days,
)

bp = Blueprint("authorizations", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]


# --------------------------- create / read ---------------------------
@bp.route("/edt/authorizations", methods=["POST"])
@require_auth_and_roles(["UtilizationReviewer"])
def create_authorization():
    body = get_json_body()
    admission_id = require_field(body, "admission_id")
    facility_id = require_field(body, "facility_id")
    payer_name = validate_non_empty_string(require_field(body, "payer_name"), "payer_name")
    daily_rate_cents = validate_int(require_field(body, "daily_rate_cents"), "daily_rate_cents", minimum=1)
    coinsurance_pct = validate_number(require_field(body, "coinsurance_pct"), "coinsurance_pct", minimum=0, maximum=1)
    with store.lock:
        check_fk("admission_id", admission_id)
        check_fk("facility_id", facility_id)
        rec = base_record()
        rec.update({
            "admission_id": admission_id,
            "facility_id": facility_id,
            "payer_name": payer_name,
            "daily_rate_cents": daily_rate_cents,
            "coinsurance_pct": coinsurance_pct,
            "days_authorized": 0,
            "days_consumed": 0,
            "days_remaining": 0,
            "covered_through_iso": None,
            "status": "PENDING",
        })
        store.authorizations[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/authorizations", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_authorizations():
    with store.lock:
        for auth in store.authorizations.values():
            recompute_auth_days(auth)
    page, limit, offset, total = list_collection(
        "authorizations", filters={"admission_id": "admission_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/authorizations/<auth_id>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_authorization(auth_id):
    with store.lock:
        rec = get_or_404("authorizations", auth_id, errors.ERR_AUTHORIZATION_NOT_FOUND)
        recompute_auth_days(rec)
        return success(serialize(rec), status=200)


@bp.route("/edt/authorizations/<auth_id>/billing-summary", methods=["GET"])
@require_auth_and_roles(["Admin", "UtilizationReviewer"])
def billing_summary(auth_id):
    with store.lock:
        auth = get_or_404("authorizations", auth_id, errors.ERR_AUTHORIZATION_NOT_FOUND)
        recompute_auth_days(auth)
        pr = calc.patient_responsibility_cents(
            auth["daily_rate_cents"], auth["coinsurance_pct"], auth["days_consumed"]
        )
        data = {
            "authorization_id": auth["id"],
            "days_consumed": auth["days_consumed"],
            "days_remaining": auth["days_remaining"],
            "patient_responsibility_cents": pr,
        }
        return success(data, status=200)


# --------------------------- reviews ---------------------------
@bp.route("/edt/reviews", methods=["POST"])
@require_auth_and_roles(["UtilizationReviewer"])
def create_review():
    body = get_json_body()
    authorization_id = require_field(body, "authorization_id")
    facility_id = require_field(body, "facility_id")
    decision = validate_enum(require_field(body, "decision"), "decision", {"APPROVE", "DENY"})

    with store.lock:
        # Priority 4: FK existence.
        auth = check_fk("authorization_id", authorization_id)
        check_fk("facility_id", facility_id)

        if decision == "APPROVE":
            return _review_approve(auth, facility_id, body)
        return _review_deny(auth, facility_id)


def _make_review(auth, facility_id, decision, window_start_iso, window_end_iso, approved_days):
    rec = base_record(with_version=True)
    rec.update({
        "authorization_id": auth["id"],
        "facility_id": facility_id,
        "decision": decision,
        "window_start_iso": window_start_iso,
        "window_end_iso": window_end_iso,
        "approved_days": approved_days,
    })
    store.reviews[rec["id"]] = rec
    return rec


def _review_approve(auth, facility_id, body):
    # APPROVE requires window fields; missing/inverted -> ERR_INVALID_WINDOW (PRD §2.6).
    window_start_raw = body.get("window_start_iso")
    window_end_raw = body.get("window_end_iso")
    if window_start_raw is None or window_end_raw is None:
        raise ApiError(errors.ERR_INVALID_WINDOW, 400, "APPROVE requires window_start_iso and window_end_iso.")
    try:
        w_start = parse_iso(window_start_raw)
        w_end = parse_iso(window_end_raw)
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_INVALID_WINDOW, 400, "Window instants must be valid ISO 8601.")
    if not (w_end > w_start):
        raise ApiError(errors.ERR_INVALID_WINDOW, 400, "window_end_iso must be strictly after window_start_iso.")

    # Priority 6: legal state for APPROVE.
    if auth["status"] not in ("PENDING", "APPROVED", "APPEALED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Authorization not in an approvable state.")

    is_extension = auth["status"] == "APPROVED"
    if is_extension:
        # Extension contiguity + non-overlap (PRD §3.11).
        covered_through = auth.get("covered_through_iso")
        ct_dt = parse_iso(covered_through) if covered_through else None
        # Overlap check against prior approved windows.
        for (ps, pe) in approved_windows(auth):
            if w_start < pe and ps < w_end:
                raise ApiError(errors.ERR_AUTH_WINDOW_OVERLAP, 409, "Window overlaps a prior approved window.")
        # Contiguity: window_start must equal covered_through, gap = 0.
        if ct_dt is None or w_start != ct_dt:
            raise ApiError(errors.ERR_AUTH_WINDOW_NONCONTIGUOUS, 409, "Window not contiguous with prior coverage.")

    approved_days = calc.whole_days(w_start, w_end)

    rec = _make_review(
        auth, facility_id, "APPROVE",
        _iso(w_start), _iso(w_end), approved_days,
    )

    auth["days_authorized"] += approved_days
    auth["covered_through_iso"] = _iso(w_end)
    auth["status"] = "APPROVED"
    recompute_auth_days(auth)
    touch(auth)
    # An approval extends coverage; it does not by itself exhaust. (Exhaustion
    # happens as the clock consumes days.) Re-check at the boundary anyway.
    maybe_exhaust(auth)

    return success(serialize(rec), status=201)


def _review_deny(auth, facility_id):
    # Priority 6: legal state for DENY.
    if auth["status"] not in ("PENDING", "APPROVED", "APPEALED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Authorization not in a deniable state.")
    rec = _make_review(auth, facility_id, "DENY", None, None, 0)
    auth["status"] = "DENIED"
    touch(auth)
    return success(serialize(rec), status=201)


def _iso(dt):
    from clock import to_iso
    return to_iso(dt)


@bp.route("/edt/reviews", methods=["GET"])
@require_auth_and_roles(["Admin", "UtilizationReviewer", "Clinician"])
def list_reviews():
    page, limit, offset, total = list_collection(
        "reviews", filters={"authorization_id": "authorization_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/reviews/<rid>", methods=["GET"])
@require_auth_and_roles(["Admin", "UtilizationReviewer", "Clinician"])
def get_review(rid):
    rec = get_or_404("reviews", rid, errors.ERR_REVIEW_NOT_FOUND)
    return success(serialize(rec), status=200)


# --------------------------- appeal ---------------------------
@bp.route("/edt/authorizations/<auth_id>/appeal", methods=["POST"])
@require_auth_and_roles(["UtilizationReviewer"])
def appeal(auth_id):
    get_optional_json_body()
    with store.lock:
        auth = get_or_404("authorizations", auth_id, errors.ERR_AUTHORIZATION_NOT_FOUND)
        if auth["status"] != "DENIED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Authorization is not DENIED.")
        auth["status"] = "APPEALED"
        touch(auth)
        return success(serialize(auth), status=200)


# --------------------------- expire ---------------------------
@bp.route("/edt/authorizations/<auth_id>/expire", methods=["POST"])
@require_auth_and_roles(["UtilizationReviewer", "Admin"])
def expire(auth_id):
    get_optional_json_body()
    with store.lock:
        auth = get_or_404("authorizations", auth_id, errors.ERR_AUTHORIZATION_NOT_FOUND)
        # legal from PENDING, APPROVED, DENIED, APPEALED (PRD §3.11).
        if auth["status"] not in ("PENDING", "APPROVED", "DENIED", "APPEALED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Authorization not in an expirable state.")
        # requires clock >= covered_through_iso.
        ct = auth.get("covered_through_iso")
        if ct is None or store.clock.now < parse_iso(ct):
            raise ApiError(errors.ERR_AUTH_NOT_EXPIRABLE, 409, "Coverage window has not yet passed.")
        auth["status"] = "EXPIRED"
        recompute_auth_days(auth)
        touch(auth)
        cascade_auth_to_admission_discharge_pending(auth)
        return success(serialize(auth), status=200)
