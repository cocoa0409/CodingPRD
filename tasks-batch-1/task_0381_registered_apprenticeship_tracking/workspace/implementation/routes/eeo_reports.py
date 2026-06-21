"""EEO report endpoints (PRD §3.8). Reports are immutable snapshots (id + created_at)."""
from flask import Blueprint, request

import db
from common import (
    get_json_body,
    parse_pagination,
    require_enum,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from lookups import get_eeo_report, get_program
from middleware import require_roles
from response import success_array, success_object
from services.calc import compute_completion_rate, compute_distributions

bp = Blueprint("eeo_reports", __name__)

COHORT_BASES = {"REGISTERED_COHORT", "ACTIVE_COHORT"}


@bp.route("/apprenticeship/eeo-reports", methods=["POST"])
@require_roles("RegistrationAgency", "Sponsor")
def create_eeo_report():
    body = get_json_body()
    program_id = require_str(body, "program_id")
    cohort_basis = require_enum(body, "cohort_basis", COHORT_BASES)

    get_program(program_id)

    total, completed, rate = compute_completion_rate(program_id, cohort_basis)
    gender_dist, race_dist, veteran_count, disability_count = compute_distributions(
        program_id, cohort_basis
    )

    rec = db.base_record(common_fields=False)
    rec.update(
        {
            "program_id": program_id,
            "cohort_basis": cohort_basis,
            "total_apprentices": total,
            "completed_count": completed,
            "completion_rate_pct": rate,
            "gender_distribution_pct": gender_dist,
            "race_distribution_pct": race_dist,
            "veteran_count": veteran_count,
            "disability_count": disability_count,
        }
    )
    db.eeo_reports[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/eeo-reports", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator")
def list_eeo_reports():
    limit, offset = parse_pagination()
    items = list(db.eeo_reports.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/eeo-reports/<rid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator")
def get_eeo_report_route(rid):
    rec = get_eeo_report(rid)
    return success_object(serialize(rec))
