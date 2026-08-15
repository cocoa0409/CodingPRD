"""Drop-test validation and customer sign-off support (PRD §3.4).

Laboratory bookings are closed intervals: both endpoints inclusive, with a
>= 30 minute buffer applying on both sides of every booking (PRD §2.8).
"""
from datetime import timedelta

from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object
from services.common import (
    body, get_or_404, get_single, list_many, owner_of_drop_test,
    parse_iso_datetime, pub, req_datetime, req_enum, req_int, req_str,
    stamp_new, touch,
)

bp = Blueprint("drop_tests", __name__)

ORIENTATIONS = ("FLAT", "EDGE", "CORNER")
LAB_GAP = timedelta(minutes=30)


def _lab_conflict(new_start, new_end):
    """A booking violates the buffer unless it leaves >= 30 minutes to every
    other booking on both sides (closed intervals, buffer both sides)."""
    for other in db.drop_tests.values():
        os_ = parse_iso_datetime(other["scheduled_start"], "scheduled_start")
        oe = parse_iso_datetime(other["scheduled_end"], "scheduled_end")
        if new_end + LAB_GAP <= os_ or oe + LAB_GAP <= new_start:
            continue  # enough separation from this booking
        return True
    return False


@bp.route("/drop-tests", methods=["POST"])
def create_drop_test():
    user_id, role = get_auth_context()
    require_role(role, ("QualityEngineer",))
    data = body()
    package_spec_id = req_str(data, "package_spec_id")
    scheduled_start = req_datetime(data, "scheduled_start")
    scheduled_end = req_datetime(data, "scheduled_end")
    drop_height_in = req_int(data, "drop_height_in", minimum=0)
    orientation = req_enum(data, "orientation", ORIENTATIONS)

    spec = get_or_404(db.package_specs, package_spec_id, "PackageSpec")
    if spec["status"] != "IN_VALIDATION":
        raise ApiError(
            errors.ERR_INVALID_STATE,
            "Drop tests may be scheduled only while the spec is IN_VALIDATION",
            409,
        )
    start_dt = parse_iso_datetime(scheduled_start, "scheduled_start")
    end_dt = parse_iso_datetime(scheduled_end, "scheduled_end")
    if not start_dt < end_dt:
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            "scheduled_start must be before scheduled_end",
            400,
        )
    if _lab_conflict(start_dt, end_dt):
        raise ApiError(
            errors.ERR_LAB_WINDOW_CONFLICT,
            "Lab booking violates the >= 30 minute gap rule against another booking",
            409,
        )
    rec = stamp_new({
        "package_spec_id": package_spec_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "drop_height_in": drop_height_in,
        "orientation": orientation,
        # Pinned at schedule time; later spec edits never move these (PRD §3.4).
        "pass_limit_g": spec["max_fragility_g"],
        "spec_revision_no": spec["revision_no"],
        "measured_peak_g": None,
        "result": None,
        "status": "SCHEDULED",
    })
    db.drop_tests[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/drop-tests", methods=["GET"])
def list_drop_tests():
    return list_many(db.drop_tests, owner_of_drop_test, ("package_spec_id", "result"))


@bp.route("/drop-tests/<rid>", methods=["GET"])
def get_drop_test(rid):
    return get_single(db.drop_tests, rid, owner_of_drop_test, "DropTest")


@bp.route("/drop-tests/<rid>/record", methods=["POST"])
def record_drop_test(rid):
    user_id, role = get_auth_context()
    require_role(role, ("QualityEngineer",))
    data = body()
    measured = req_int(data, "measured_peak_g", minimum=0)
    rec = get_or_404(db.drop_tests, rid, "DropTest")
    if rec["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot record a drop test in {rec['status']}", 409)
    rec["measured_peak_g"] = measured
    rec["result"] = "PASS" if measured <= rec["pass_limit_g"] else "FAIL"
    rec["status"] = "RECORDED"
    touch(rec)
    # Auto-validation (PRD §3.4): a recorded PASS pinned to the spec's current
    # revision, with no recorded FAIL at that same revision, advances an
    # IN_VALIDATION spec to VALIDATED. Tests pinned to older revisions are
    # invisible to this check.
    spec = db.package_specs.get(rec["package_spec_id"])
    if rec["result"] == "PASS" and spec is not None and spec["status"] == "IN_VALIDATION":
        current_rev = spec["revision_no"]
        has_pass_at_rev = any(
            t["status"] == "RECORDED" and t["result"] == "PASS" and t["spec_revision_no"] == current_rev
            for t in db.drop_tests.values()
            if t["package_spec_id"] == spec["id"]
        )
        has_fail_at_rev = any(
            t["status"] == "RECORDED" and t["result"] == "FAIL" and t["spec_revision_no"] == current_rev
            for t in db.drop_tests.values()
            if t["package_spec_id"] == spec["id"]
        )
        if has_pass_at_rev and not has_fail_at_rev:
            spec["status"] = "VALIDATED"
            touch(spec)
    return success_object(pub(rec))
