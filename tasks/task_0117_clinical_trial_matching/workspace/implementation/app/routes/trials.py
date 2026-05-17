"""Trial CRUD and lifecycle transitions."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Blueprint, request

from ..auth import (
    ROLE_COORD,
    ROLE_IRB,
    ROLE_PI,
    require_roles,
)
from ..clock import clock, now
from ..errors import (
    err_duplicate_protocol_code,
    err_invalid_input,
    err_invalid_state,
    err_irb_expired,
    err_randomization_misconfigured,
)
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..services.lookups import (
    arms_for_trial,
    consent_versions_for_trial,
    get_trial,
    participants_for_trial,
    visits_for_participant,
)
from ..services.serialize import serialize_trial
from ..responses import created, listing, ok
from ..store import store

bp = Blueprint("trials", __name__)


# ---------- Trial validators ----------

PROTOCOL_CODE_PATTERN = r"^[A-Z]{2,4}-[0-9]{3,5}$"
ALLOWED_OPS = {"GTE", "LTE", "EQ", "IN", "BETWEEN"}
ALLOWED_SCHEMES = ["SIMPLE_BERNOULLI", "PERMUTED_BLOCK", "STRATIFIED_BLOCK"]
ALLOWED_BLOCK_SIZES = {2, 4, 6, 8}


def _validate_criteria(items: Any, field: str) -> list[dict[str, Any]]:
    if items is None:
        raise err_invalid_input(f"{field} is required")
    if not isinstance(items, list):
        raise err_invalid_input(f"{field} must be an array")
    if len(items) > 20:
        raise err_invalid_input(f"{field} may contain at most 20 entries")
    cleaned: list[dict[str, Any]] = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            raise err_invalid_input(f"{field}[{idx}] must be an object")
        code = it.get("code")
        op = it.get("op")
        f = it.get("field")
        v = it.get("value")
        if not isinstance(code, str) or not code:
            raise err_invalid_input(f"{field}[{idx}].code must be a non-empty string")
        if not isinstance(op, str) or op not in ALLOWED_OPS:
            raise err_invalid_input(
                f"{field}[{idx}].op must be one of {sorted(ALLOWED_OPS)}"
            )
        if not isinstance(f, str) or not f:
            raise err_invalid_input(f"{field}[{idx}].field must be a non-empty string")
        cleaned.append({"code": code, "op": op, "field": f, "value": v})
    return cleaned


def _validate_scheme_inputs(
    scheme: str, block_size: Any, stratification_field: Any
) -> tuple[int | None, str | None]:
    if scheme == "SIMPLE_BERNOULLI":
        if block_size is not None:
            raise err_invalid_input("block_size must be null for SIMPLE_BERNOULLI")
        sf = None
        if stratification_field not in (None, ""):
            sf = assert_string(
                stratification_field, "stratification_field", required=False, max_len=100
            )
        return None, sf
    if scheme in {"PERMUTED_BLOCK", "STRATIFIED_BLOCK"}:
        bs = assert_integer(block_size, "block_size", required=True)
        if bs not in ALLOWED_BLOCK_SIZES:
            raise err_invalid_input(
                f"block_size must be one of {sorted(ALLOWED_BLOCK_SIZES)}"
            )
        sf = stratification_field
        if scheme == "STRATIFIED_BLOCK":
            sf = assert_string(sf, "stratification_field", required=True, max_len=100)
        elif sf:
            sf = assert_string(sf, "stratification_field", required=False, max_len=100)
        else:
            sf = None
        return bs, sf
    raise err_invalid_input(f"Unknown randomization_scheme {scheme}")


def _check_protocol_code_unique(code: str, exclude_trial_id: str | None = None) -> None:
    s = store()
    existing = s.protocol_code_index.get(code)
    if existing is not None and existing != exclude_trial_id:
        raise err_duplicate_protocol_code()


# ---------- POST /trials ----------

@bp.post("/trials")
@require_roles(ROLE_PI)
def create_trial(**caller):
    body = require_json_object()

    protocol_code = assert_string(
        body.get("protocol_code"),
        "protocol_code",
        required=True,
        min_len=1,
        max_len=20,
        trim=True,
        pattern=PROTOCOL_CODE_PATTERN,
    )
    assert protocol_code is not None
    title = assert_string(body.get("title"), "title", required=True, min_len=1, max_len=200, trim=True)
    sponsor_org = assert_string(body.get("sponsor_org"), "sponsor_org", required=True, min_len=1, max_len=200, trim=True)
    inclusion_criteria = _validate_criteria(body.get("inclusion_criteria"), "inclusion_criteria")
    exclusion_criteria = _validate_criteria(body.get("exclusion_criteria"), "exclusion_criteria")
    scheme = assert_enum(body.get("randomization_scheme"), "randomization_scheme", ALLOWED_SCHEMES, required=True)
    assert scheme is not None
    block_size, stratification_field = _validate_scheme_inputs(
        scheme, body.get("block_size"), body.get("stratification_field")
    )
    target_enrollment = assert_integer(
        body.get("target_enrollment"), "target_enrollment", required=True, minimum=1, maximum=10000
    )
    window_days = assert_integer(
        body.get("blood_draw_window_days"), "blood_draw_window_days", required=True, minimum=0, maximum=14
    )

    with store().lock:
        _check_protocol_code_unique(protocol_code)
        ts = now()
        trial_id = new_uuid()
        trial = {
            "id": trial_id,
            "protocol_code": protocol_code,
            "title": title,
            "sponsor_org": sponsor_org,
            "status": "DRAFT",
            "inclusion_criteria": inclusion_criteria,
            "exclusion_criteria": exclusion_criteria,
            "active_consent_version": None,
            "randomization_scheme": scheme,
            "block_size": block_size,
            "stratification_field": stratification_field,
            "target_enrollment": target_enrollment,
            "enrolled_count": 0,
            "irb_decision_note": None,
            "irb_approval_expires_at": None,
            "blood_draw_window_days": window_days,
            "created_by_user_id": caller["_caller_id"],
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            # Snapshot of criteria at create-time for chronological eligibility replay.
            "_inclusion_snapshot_at_create": list(inclusion_criteria),
            "_exclusion_snapshot_at_create": list(exclusion_criteria),
            # Per-stratum running counters for STRATIFIED_BLOCK randomization.
            "_stratum_counters": {},
        }
        store().trials[trial_id] = trial
        store().protocol_code_index[protocol_code] = trial_id

    return created(serialize_trial(trial))


# ---------- GET /trials ----------

@bp.get("/trials")
@require_roles(ROLE_PI, ROLE_IRB, ROLE_COORD)
def list_trials(**_caller):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    with store().lock:
        rows = list(store().trials.values())
        if status_filter:
            rows = [r for r in rows if r["status"] == status_filter]
        rows.sort(key=lambda r: r["created_at"])
        total = len(rows)
        page = paginate(rows, limit, offset)
        items = [serialize_trial(r) for r in page]
    return listing(items, total, limit, offset)


# ---------- GET /trials/<id> ----------

@bp.get("/trials/<trial_id>")
@require_roles(ROLE_PI, ROLE_IRB, ROLE_COORD)
def read_trial(trial_id: str, **_caller):
    with store().lock:
        t = get_trial(trial_id)
        return ok(serialize_trial(t))


# ---------- PATCH /trials/<id> ----------

@bp.patch("/trials/<trial_id>")
@require_roles(ROLE_PI)
def update_trial(trial_id: str, **_caller):
    body = require_json_object()
    with store().lock:
        t = get_trial(trial_id)
        if t["status"] != "DRAFT":
            raise err_invalid_state("Trial may only be edited in DRAFT")
        # OCC after state check (per validation ordering: state has higher priority than OCC).
        occ_check(body.get("version"), t["version"])

        if "title" in body:
            t["title"] = assert_string(body["title"], "title", required=True, min_len=1, max_len=200, trim=True)
        if "sponsor_org" in body:
            t["sponsor_org"] = assert_string(
                body["sponsor_org"], "sponsor_org", required=True, min_len=1, max_len=200, trim=True
            )
        if "inclusion_criteria" in body:
            t["inclusion_criteria"] = _validate_criteria(body["inclusion_criteria"], "inclusion_criteria")
        if "exclusion_criteria" in body:
            t["exclusion_criteria"] = _validate_criteria(body["exclusion_criteria"], "exclusion_criteria")
        if "target_enrollment" in body:
            t["target_enrollment"] = assert_integer(
                body["target_enrollment"], "target_enrollment", required=True, minimum=1, maximum=10000
            )

        _bump(t)
        return ok(serialize_trial(t))


def _bump(t: dict[str, Any]) -> None:
    t["updated_at"] = now()
    t["version"] = t["version"] + 1


# ---------- POST /trials/<id>/submit-for-irb ----------

@bp.post("/trials/<trial_id>/submit-for-irb")
@require_roles(ROLE_PI)
def submit_for_irb(trial_id: str, **_caller):
    with store().lock:
        t = get_trial(trial_id)
        if t["status"] != "DRAFT":
            raise err_invalid_state("Trial is not in DRAFT")
        arms = arms_for_trial(trial_id)
        if len(arms) < 2:
            raise err_randomization_misconfigured(
                "Trial requires at least 2 arms before IRB submission"
            )
        scheme = t["randomization_scheme"]
        if scheme in {"PERMUTED_BLOCK", "STRATIFIED_BLOCK"}:
            if t["block_size"] is None or t["block_size"] % len(arms) != 0:
                raise err_randomization_misconfigured(
                    "block_size must be divisible by arm count"
                )
            weights = {a["weight"] for a in arms}
            if len(weights) > 1:
                raise err_randomization_misconfigured(
                    "All arms must share the same weight for block schemes"
                )
            if scheme == "STRATIFIED_BLOCK" and not t["stratification_field"]:
                raise err_randomization_misconfigured(
                    "stratification_field is required for STRATIFIED_BLOCK"
                )
        if t["active_consent_version"] is None:
            raise err_randomization_misconfigured(
                "Trial must have at least one published ConsentVersion before IRB submission"
            )
        t["status"] = "IRB_PENDING"
        _bump(t)
        return ok(serialize_trial(t))


# ---------- POST /trials/<id>/open-enrollment ----------

@bp.post("/trials/<trial_id>/open-enrollment")
@require_roles(ROLE_PI)
def open_enrollment(trial_id: str, **_caller):
    with store().lock:
        t = get_trial(trial_id)
        if t["status"] != "APPROVED":
            raise err_invalid_state("Trial is not APPROVED")
        if t["active_consent_version"] is None:
            raise err_invalid_state("Trial has no active consent version")
        if t["irb_approval_expires_at"] is None or now() >= t["irb_approval_expires_at"]:
            raise err_irb_expired()
        t["status"] = "OPEN_FOR_ENROLLMENT"
        _bump(t)
        return ok(serialize_trial(t))


# ---------- POST /trials/<id>/close-enrollment ----------

@bp.post("/trials/<trial_id>/close-enrollment")
@require_roles(ROLE_PI)
def close_enrollment(trial_id: str, **_caller):
    with store().lock:
        t = get_trial(trial_id)
        if t["status"] != "OPEN_FOR_ENROLLMENT":
            raise err_invalid_state("Trial is not OPEN_FOR_ENROLLMENT")
        t["status"] = "CLOSED_TO_ENROLLMENT"
        _bump(t)
        return ok(serialize_trial(t))


# ---------- POST /trials/<id>/complete ----------

@bp.post("/trials/<trial_id>/complete")
@require_roles(ROLE_PI)
def complete_trial(trial_id: str, **_caller):
    with store().lock:
        t = get_trial(trial_id)
        if t["status"] != "CLOSED_TO_ENROLLMENT":
            raise err_invalid_state("Trial is not CLOSED_TO_ENROLLMENT")
        active_states = {"SCREENING", "ELIGIBLE", "CONSENT_PENDING", "ENROLLED"}
        for p in participants_for_trial(trial_id):
            if p["status"] in active_states:
                raise err_invalid_state(
                    "All participants must be in COMPLETED, WITHDRAWN, or INELIGIBLE"
                )
        t["status"] = "COMPLETED"
        _bump(t)
        return ok(serialize_trial(t))


# ---------- POST /trials/<id>/terminate ----------

@bp.post("/trials/<trial_id>/terminate")
@require_roles(ROLE_PI)
def terminate_trial(trial_id: str, **_caller):
    body = require_json_object()
    # `reason` is accepted but not stored separately; recorded as irb_decision_note.
    reason = body.get("reason")
    if reason is not None:
        reason = assert_string(reason, "reason", required=False, min_len=1, max_len=1000)
    with store().lock:
        t = get_trial(trial_id)
        if t["status"] != "OPEN_FOR_ENROLLMENT":
            raise err_invalid_state("Trial may only be terminated from OPEN_FOR_ENROLLMENT")
        # Cascade: every participant in {SCREENING, ELIGIBLE, CONSENT_PENDING, ENROLLED} → WITHDRAWN.
        active = {"SCREENING", "ELIGIBLE", "CONSENT_PENDING", "ENROLLED"}
        from .participants import cascade_withdraw_for_trial_termination
        for p in participants_for_trial(trial_id):
            if p["status"] in active:
                cascade_withdraw_for_trial_termination(p, t)
        t["status"] = "TERMINATED"
        if reason:
            t["irb_decision_note"] = reason
        _bump(t)
        return ok(serialize_trial(t))
