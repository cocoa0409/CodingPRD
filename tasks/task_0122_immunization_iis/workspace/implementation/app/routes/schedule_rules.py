"""AntigenScheduleRule routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import store
from ..auth import require_roles
from ..errors import APIError
from ..helpers import (
    ensure_enum,
    is_bool,
    is_int,
    is_nonneg_int,
    optional_field,
    paginate,
    parse_json_body,
    parse_pagination,
    require_field,
)
from ..responses import build_envelope


bp = Blueprint("schedule_rules", __name__)


ANTIGEN_VALUES = {
    "DTAP_DIPHTHERIA",
    "DTAP_TETANUS",
    "DTAP_PERTUSSIS",
    "MMR_MEASLES",
    "MMR_MUMPS",
    "MMR_RUBELLA",
    "HEPB",
    "HPV",
    "POLIO",
    "VARICELLA",
}


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "antigen": r["antigen"],
        "dose_sequence_number": r["dose_sequence_number"],
        "routine_min_age_days": r["routine_min_age_days"],
        "routine_recommended_age_days": r["routine_recommended_age_days"],
        "routine_max_age_days": r["routine_max_age_days"],
        "catchup_min_interval_days": r["catchup_min_interval_days"],
        "prerequisite_rule_id": r.get("prerequisite_rule_id"),
        "school_enrollment_required": r["school_enrollment_required"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.post("/antigen-schedule-rules")
@require_roles(["PublicHealthOfficer"])
def create_rule():
    body = parse_json_body()
    antigen = ensure_enum(require_field(body, "antigen"), ANTIGEN_VALUES, "antigen")
    seq = require_field(body, "dose_sequence_number", type_check=lambda v: is_int(v) and v >= 1)
    # Uniqueness: (antigen, dose_sequence_number) unique.
    for existing in store.antigen_schedule_rules.values():
        if existing["antigen"] == antigen and existing["dose_sequence_number"] == seq:
            raise APIError("ERR_VALIDATION", "(antigen, dose_sequence_number) must be unique.")
    rmin = require_field(body, "routine_min_age_days", type_check=is_nonneg_int)
    rrec = require_field(body, "routine_recommended_age_days", type_check=is_nonneg_int)
    rmax = require_field(body, "routine_max_age_days", type_check=is_nonneg_int)
    cmin = require_field(body, "catchup_min_interval_days", type_check=is_nonneg_int)
    prereq = optional_field(body, "prerequisite_rule_id", default=None)
    if prereq is not None and prereq not in store.antigen_schedule_rules:
        raise APIError("ERR_VALIDATION", "prerequisite_rule_id must reference an existing rule.")
    school_required = require_field(body, "school_enrollment_required", type_check=is_bool)

    with store.lock:
        rec = {
            "antigen": antigen,
            "dose_sequence_number": seq,
            "routine_min_age_days": rmin,
            "routine_recommended_age_days": rrec,
            "routine_max_age_days": rmax,
            "catchup_min_interval_days": cmin,
            "prerequisite_rule_id": prereq,
            "school_enrollment_required": school_required,
        }
        store.stamp_create(rec)
        store.antigen_schedule_rules[rec["id"]] = rec
    return jsonify(build_envelope(_serialize(rec), "object")), 201


@bp.get("/antigen-schedule-rules")
@require_roles(["PublicHealthOfficer", "SchoolRegistrar", "ProviderClinician", "ReviewingClinician"])
def list_rules():
    limit, offset = parse_pagination()
    antigen_q = request.args.get("antigen")
    if antigen_q is not None and antigen_q not in ANTIGEN_VALUES:
        raise APIError("ERR_VALIDATION", "antigen filter invalid.")
    rows = list(store.antigen_schedule_rules.values())
    if antigen_q is not None:
        rows = [r for r in rows if r["antigen"] == antigen_q]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows, limit, offset)
    return jsonify(build_envelope([_serialize(r) for r in page], "array", meta)), 200
