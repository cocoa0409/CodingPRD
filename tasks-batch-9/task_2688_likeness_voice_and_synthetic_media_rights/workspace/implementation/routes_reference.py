"""State law profiles, union minimum schedules, the logical clock and the sweep."""

from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, authorize, body_json, collection, db, fail, invalid, iso, new_id,
    now, parse_dt, public, respond, want_bool, want_code, want_dt, want_enum,
    want_int, want_str,
)

bp = Blueprint("reference", __name__)

READ_ALL = ALL_ROLES
READ_NO_LICENSEE = ("RightsAdministrator", "ComplianceOfficer",
                    "TalentRepresentative", "EstateRepresentative")


# ------------------------------------------------------------ state law profiles

@bp.post("/state-law-profiles")
def create_state_law_profile():
    authorize("RightsAdministrator")
    body = body_json()
    state_code = want_code(body, "state_code")
    postmortem_rights_years = want_int(body, "postmortem_rights_years", 0, 100)
    requires_registration = want_bool(body, "postmortem_requires_registration")
    retention_max_days = want_int(body, "biometric_retention_max_days", 1, 3650)
    deletion_grace_days = want_int(body, "deletion_grace_days", 0, 365)
    removal_window_days = want_int(body, "removal_window_days", 1, 90)
    disclosure_advertising = want_bool(body, "disclosure_required_advertising")
    disclosure_entertainment = want_bool(body, "disclosure_required_entertainment")
    min_rank_advertising = want_int(body, "min_disclosure_rank_advertising", 1, 4)
    min_rank_entertainment = want_int(body, "min_disclosure_rank_entertainment", 1, 4)
    if calc.profile_for(state_code) is not None:
        invalid("a state law profile for %s already exists" % state_code)
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "state_code": state_code,
        "postmortem_rights_years": postmortem_rights_years,
        "postmortem_requires_registration": requires_registration,
        "biometric_retention_max_days": retention_max_days,
        "deletion_grace_days": deletion_grace_days,
        "removal_window_days": removal_window_days,
        "disclosure_required_advertising": disclosure_advertising,
        "disclosure_required_entertainment": disclosure_entertainment,
        "min_disclosure_rank_advertising": min_rank_advertising,
        "min_disclosure_rank_entertainment": min_rank_entertainment,
        "_seq": db.next_seq(),
    }
    db.state_law_profiles[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/state-law-profiles/<row_id>")
def read_state_law_profile(row_id):
    authorize(*READ_ALL)
    row = db.state_law_profiles.get(row_id)
    if row is None:
        fail("ERR_STATE_LAW_PROFILE_MISSING", "no state law profile %s" % row_id)
    return respond(public(row))


@bp.get("/state-law-profiles")
def list_state_law_profiles():
    authorize(*READ_ALL)
    return collection(db.state_law_profiles.values(),
                      {"state_code": "state_code"}, "created_desc_id")


# ------------------------------------------------------- union minimum schedules

@bp.post("/union-minimum-schedules")
def create_union_minimum_schedule():
    authorize("RightsAdministrator")
    body = body_json()
    union_code = want_enum(body, "union_code", calc.UNION_CODES)
    media_type = want_enum(body, "media_type", calc.MEDIA_TYPES)
    effective_from = want_dt(body, "effective_from")
    minimum_initial_cents = want_int(body, "minimum_initial_cents", 0)
    minimum_per_use_cents = want_int(body, "minimum_per_use_cents", 0)
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "union_code": union_code,
        "media_type": media_type,
        "effective_from": effective_from,
        "minimum_initial_cents": minimum_initial_cents,
        "minimum_per_use_cents": minimum_per_use_cents,
        "_seq": db.next_seq(),
    }
    db.union_minimum_schedules[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/union-minimum-schedules/<row_id>")
def read_union_minimum_schedule(row_id):
    authorize(*READ_NO_LICENSEE)
    row = db.union_minimum_schedules.get(row_id)
    if row is None:
        fail("ERR_UNION_SCHEDULE_MISSING", "no union minimum schedule %s" % row_id)
    return respond(public(row))


@bp.get("/union-minimum-schedules")
def list_union_minimum_schedules():
    authorize(*READ_NO_LICENSEE)
    return collection(db.union_minimum_schedules.values(),
                      {"union_code": "union_code", "media_type": "media_type"},
                      "effective_from_asc")


# ------------------------------------------------------ ledger reads (read-only)

@bp.get("/compensation-entries/<row_id>")
def read_compensation_entry(row_id):
    authorize(*READ_NO_LICENSEE)
    row = db.compensation_entries.get(row_id)
    if row is None:
        fail("ERR_COMPENSATION_ENTRY_NOT_FOUND", "no compensation entry %s" % row_id)
    return respond(public(row))


@bp.get("/compensation-entries")
def list_compensation_entries():
    authorize(*READ_NO_LICENSEE)
    return collection(db.compensation_entries.values(), {
        "talent_id": "talent_id",
        "consent_grant_id": "consent_grant_id",
        "generated_performance_id": "generated_performance_id",
        "usage_license_id": "usage_license_id",
        "reverses_entry_id": "reverses_entry_id",
        "entry_type": "entry_type",
    }, "posted_at_asc")


# --------------------------------------------------------------- sweep and clock

@bp.post("/compliance-sweeps")
def compliance_sweep():
    authorize("RightsAdministrator", "ComplianceOfficer")
    body_json()
    return respond(services.run_compliance_sweep(), 200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize("RightsAdministrator", "ComplianceOfficer")
    body = body_json()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        invalid("to_iso8601 is required")
    parsed = parse_dt(body["to_iso8601"])
    if parsed is None:
        invalid("to_iso8601 must be a parseable ISO 8601 datetime")
    db.clock = parsed
    return respond({"current_utc": iso(parsed)}, 200)
