"""PovertyDataSnapshot endpoints, including the certification cascade."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from routes.grants import get_grant_or_404
from services import serializers, workflows

bp = Blueprint("snapshots", __name__)

ALL_ROLES = middleware.ROLES
MEASURES = {"CENSUS_SAIPE", "FREE_REDUCED_LUNCH", "MEDICAID_DIRECT_CERT", "COMPOSITE"}


def get_snapshot_or_404(snapshot_id):
    snap = db.snapshots.get(snapshot_id)
    if snap is None:
        errors.fail(errors.ERR_NOT_FOUND, "Snapshot %s does not exist." % snapshot_id)
    return snap


def _validate_entries(entries_raw):
    """Tier 3 (school FK existence, in array order) then tier 4 (entry schema)
    then tier 4.5 (duplicate school_id)."""
    # Tier 3: every entry's school_id must resolve.
    for entry in entries_raw:
        if isinstance(entry, dict) and isinstance(entry.get("school_id"), str):
            if entry["school_id"] not in db.schools:
                errors.fail(
                    errors.ERR_NOT_FOUND,
                    "School %s does not exist." % entry["school_id"],
                )
    # Tier 4: entry schema.
    entries = []
    for entry in entries_raw:
        if not isinstance(entry, dict):
            errors.fail(errors.ERR_INVALID_REQUEST, "Each snapshot entry must be an object.")
        V.check_unknown(entry, {"school_id", "low_income_student_count", "total_student_count"})
        school_id = V.req_str(entry, "school_id")
        li = V.req_int(entry, "low_income_student_count")
        total = V.req_int(entry, "total_student_count")
        if total <= 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "total_student_count must be > 0.")
        if li < 0 or li > total:
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "low_income_student_count must satisfy 0 <= low_income <= total.",
            )
        entries.append({
            "school_id": school_id,
            "low_income_student_count": li,
            "total_student_count": total,
        })
    # Tier 4.5: duplicate school_id inside the entries.
    seen = set()
    for e in entries:
        if e["school_id"] in seen:
            errors.fail(
                errors.ERR_DUPLICATE_SCHOOL_ENTRY,
                "Snapshot entries contain school_id %s twice." % e["school_id"],
            )
        seen.add(e["school_id"])
    return entries


def _check_coverage(entries):
    """Tier 9: entries must cover every active school exactly once."""
    active_ids = {s["id"] for s in db.schools.values() if s["is_active"]}
    entry_ids = {e["school_id"] for e in entries}
    if entry_ids != active_ids:
        errors.fail(
            errors.ERR_SNAPSHOT_INCOMPLETE_COVERAGE,
            "Snapshot entries must cover every active school exactly once.",
        )


@bp.post("/poverty-snapshots")
def create_snapshot():
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"ComplianceAnalyst"})
    data = V.json_body()
    # Tier 3: body FK existence in declared field order.
    grant_ref = data.get("grant_id")
    if grant_ref is not None and isinstance(grant_ref, str):
        get_grant_or_404(grant_ref)
    # Tier 4: schema.
    V.check_unknown(data, {"grant_id", "measure", "entries"})
    grant_id = V.req_str(data, "grant_id")
    grant = get_grant_or_404(grant_id)
    V.req_enum(data, "measure", MEASURES)
    entries = _validate_entries(V.req_array(data, "entries"))
    # Tier 9: coverage is enforced at creation as well as at certification.
    _check_coverage(entries)
    snap = db.init_common({
        "grant_id": grant["id"],
        "measure": data["measure"],
        "entries": entries,
        "status": "DRAFT",
        "certified_at": None,
    })
    db.snapshots[snap["id"]] = snap
    return response.success_object(serializers.snapshot_view(snap), 201)


@bp.get("/poverty-snapshots")
def list_snapshots():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    grant_id = V.query_filter("grant_id")
    status = V.query_filter("status")
    page, limit, offset, total = V.sorted_page(
        list(db.snapshots.values()), [("grant_id", grant_id), ("status", status)]
    )
    return response.success_list(
        [serializers.snapshot_view(s) for s in page], limit, offset, total
    )


@bp.get("/poverty-snapshots/<snapshot_id>")
def get_snapshot(snapshot_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.snapshot_view(get_snapshot_or_404(snapshot_id)))


@bp.post("/poverty-snapshots/<snapshot_id>/certify")
def certify_snapshot(snapshot_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    snap = get_snapshot_or_404(snapshot_id)
    data = V.json_body()
    # Tier 4: schema (expected_grant_version is mandatory per PRD 2.7).
    V.check_unknown(data, {"expected_grant_version"})
    expected_version = V.req_int(data, "expected_grant_version")
    grant = db.grants[snap["grant_id"]]
    # Tier 5: state gates.
    if snap["status"] != "DRAFT":
        errors.fail(errors.ERR_SNAPSHOT_NOT_CERTIFIABLE, "Snapshot is not in DRAFT.")
    if grant["status"] not in ("SETUP", "RANKING_LOCKED", "ALLOCATED"):
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "Grant status %s does not permit certification." % grant["status"],
        )
    # Tier 6: OCC on the grant baseline.
    if expected_version != grant["version"]:
        errors.fail(
            errors.ERR_STALE_GRANT_VERSION,
            "expected_grant_version does not match the grant's current version.",
        )
    # Tier 9: coverage re-validated against the current active roster.
    _check_coverage(snap["entries"])
    if snap["measure"] != grant["poverty_measure"]:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "Snapshot measure must equal the grant's poverty_measure.",
        )
    workflows.certify_snapshot_cascade(snap, grant)
    return response.success_object(serializers.snapshot_view(snap))
