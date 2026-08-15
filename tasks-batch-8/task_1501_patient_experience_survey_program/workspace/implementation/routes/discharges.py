"""Discharge endpoints (PRD 3.2): intake, bulk import with auto-evaluation,
and re-evaluation with the exclusion cascade."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_DISCHARGE_LOCKED_BY_SAMPLE,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import discharge_view
from services.core import apply_discharge_evaluation, cascade_discharge_excluded
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    require_bool, require_enum, require_date, get_or_404,
    parse_pagination, paginate, sort_created, query_arg, parse_iso_date,
)

bp = Blueprint("discharges", __name__)

DISPOSITIONS = {"HOME", "SNF", "EXPIRED", "PSYCH_FACILITY", "REHAB", "HOSPICE"}
DX_GROUPS = {"MEDICAL", "SURGICAL", "PSYCHIATRIC", "MATERNITY"}
PAYERS = {"MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY"}
CUSTODY = {"NONE", "LAW_ENFORCEMENT"}

CREATE_FIELDS = {
    "program_id", "mrn", "unit_id", "provider_id", "admit_date", "discharge_date",
    "discharge_disposition", "primary_dx_group", "payer", "age_years",
    "address_country", "no_publicity_flag", "custody_status",
}
TEMPLATE_FIELDS = {
    "mrn_prefix", "unit_id", "provider_id", "admit_date", "discharge_date",
    "discharge_disposition", "primary_dx_group", "payer", "age_years",
    "address_country", "no_publicity_flag", "custody_status",
}
OVERRIDE_FIELDS = {
    "discharge_disposition", "primary_dx_group", "age_years", "address_country",
    "no_publicity_flag", "custody_status", "admit_date", "discharge_date",
}


def _validate_core_fields(src: dict, names: tuple[str, ...]) -> dict:
    """Validate and extract the clinical/administrative discharge fields."""
    out = {}
    if "admit_date" in names:
        out["admit_date"] = require_date(src, "admit_date")
    if "discharge_date" in names:
        out["discharge_date"] = require_date(src, "discharge_date")
    if "discharge_disposition" in names:
        out["discharge_disposition"] = require_enum(src, "discharge_disposition", DISPOSITIONS)
    if "primary_dx_group" in names:
        out["primary_dx_group"] = require_enum(src, "primary_dx_group", DX_GROUPS)
    if "payer" in names:
        out["payer"] = require_enum(src, "payer", PAYERS)
    if "age_years" in names:
        out["age_years"] = require_int(src, "age_years", minimum=0)
    if "address_country" in names:
        out["address_country"] = require_string(src, "address_country")
    if "no_publicity_flag" in names:
        out["no_publicity_flag"] = require_bool(src, "no_publicity_flag")
    if "custody_status" in names:
        out["custody_status"] = require_enum(src, "custody_status", CUSTODY)
    if "admit_date" in out and "discharge_date" in out:
        if parse_iso_date(out["discharge_date"], "discharge_date") < parse_iso_date(
            out["admit_date"], "admit_date"
        ):
            raise_err(ERR_INVALID_REQUEST,
                      "discharge_date must be on or after admit_date")
    return out


@bp.route("/api/discharges", methods=["POST"])
@require_roles("DataSteward")
def create_discharge(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    program_id = require_string(body, "program_id")
    mrn = require_string(body, "mrn")
    unit_id = require_string(body, "unit_id")
    provider_id = require_string(body, "provider_id")
    fields = _validate_core_fields(body, (
        "admit_date", "discharge_date", "discharge_disposition", "primary_dx_group",
        "payer", "age_years", "address_country", "no_publicity_flag", "custody_status",
    ))

    get_or_404(db.programs, program_id, "SurveyProgram")
    get_or_404(db.units, unit_id, "CareUnit")
    get_or_404(db.providers, provider_id, "Provider")

    discharge = db.stamp_new({
        "program_id": program_id,
        "mrn": mrn,
        "unit_id": unit_id,
        "provider_id": provider_id,
        **fields,
        "status": "ELIGIBILITY_PENDING",
        "exclusion_reasons": [],
    })
    db.discharges[discharge["id"]] = discharge
    return success_object(discharge_view(discharge), 201)


@bp.route("/api/discharges/import", methods=["POST"])
@require_roles("DataSteward")
def import_discharges(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, {"program_id", "count", "template"})
    program_id = require_string(body, "program_id")
    count = require_int(body, "count", minimum=1, maximum=500)
    template = body.get("template")
    if not isinstance(template, dict):
        raise_err(ERR_INVALID_REQUEST, "Field template must be an object")

    # Atomic: any malformed template field rejects the whole import.
    reject_unknown_fields(template, TEMPLATE_FIELDS)
    mrn_prefix = require_string(template, "mrn_prefix")
    unit_id = require_string(template, "unit_id")
    provider_id = require_string(template, "provider_id")
    fields = _validate_core_fields(template, (
        "admit_date", "discharge_date", "discharge_disposition", "primary_dx_group",
        "payer", "age_years", "address_country", "no_publicity_flag", "custody_status",
    ))

    get_or_404(db.programs, program_id, "SurveyProgram")
    get_or_404(db.units, unit_id, "CareUnit")
    get_or_404(db.providers, provider_id, "Provider")

    discharge_ids = []
    eligible_count = 0
    excluded_count = 0
    for i in range(1, count + 1):
        discharge = db.stamp_new({
            "program_id": program_id,
            "mrn": f"{mrn_prefix}-{i:03d}",
            "unit_id": unit_id,
            "provider_id": provider_id,
            **fields,
            "status": "ELIGIBILITY_PENDING",
            "exclusion_reasons": [],
        })
        # Every imported item is auto-evaluated (PRD 3.2).
        apply_discharge_evaluation(discharge)
        db.discharges[discharge["id"]] = discharge
        discharge_ids.append(discharge["id"])
        if discharge["status"] == "ELIGIBLE":
            eligible_count += 1
        else:
            excluded_count += 1

    return success_object({
        "created_count": count,
        "eligible_count": eligible_count,
        "excluded_count": excluded_count,
        "discharge_ids": discharge_ids,
    }, 201)


@bp.route("/api/discharges", methods=["GET"])
@require_roles("Any")
def list_discharges(_user_id: str, _role: str):
    items = list(db.discharges.values())
    program_id = query_arg("program_id")
    unit_id = query_arg("unit_id")
    provider_id = query_arg("provider_id")
    status = query_arg("status")
    if program_id is not None:
        items = [d for d in items if d["program_id"] == program_id]
    if unit_id is not None:
        items = [d for d in items if d["unit_id"] == unit_id]
    if provider_id is not None:
        items = [d for d in items if d["provider_id"] == provider_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([discharge_view(d) for d in page], limit, offset, total)


@bp.route("/api/discharges/<dischargeId>", methods=["GET"])
@require_roles("Any")
def get_discharge(dischargeId: str, _user_id: str, _role: str):
    discharge = get_or_404(db.discharges, dischargeId, "Discharge")
    return success_object(discharge_view(discharge))


@bp.route("/api/discharges/<dischargeId>/evaluate", methods=["POST"])
@require_roles("DataSteward")
def evaluate_discharge(dischargeId: str, _user_id: str, _role: str):
    discharge = get_or_404(db.discharges, dischargeId, "Discharge")

    body = get_json_body()
    reject_unknown_fields(body, OVERRIDE_FIELDS)

    # Shape-validate each supplied override before any state check.
    overrides: dict = {}
    if "discharge_disposition" in body:
        overrides["discharge_disposition"] = require_enum(
            body, "discharge_disposition", DISPOSITIONS)
    if "primary_dx_group" in body:
        overrides["primary_dx_group"] = require_enum(body, "primary_dx_group", DX_GROUPS)
    if "age_years" in body:
        overrides["age_years"] = require_int(body, "age_years", minimum=0)
    if "address_country" in body:
        overrides["address_country"] = require_string(body, "address_country")
    if "no_publicity_flag" in body:
        overrides["no_publicity_flag"] = require_bool(body, "no_publicity_flag")
    if "custody_status" in body:
        overrides["custody_status"] = require_enum(body, "custody_status", CUSTODY)
    if "admit_date" in body:
        overrides["admit_date"] = require_date(body, "admit_date")
    if "discharge_date" in body:
        overrides["discharge_date"] = require_date(body, "discharge_date")

    # The override path is locked while a linked case has reached RESPONDED
    # (PRD 3.2); re-evaluation without overrides is always permitted.
    if overrides:
        for case in db.sample_cases.values():
            if case["discharge_id"] == discharge["id"] and case["status"] == "RESPONDED":
                raise_err(
                    ERR_DISCHARGE_LOCKED_BY_SAMPLE,
                    "Discharge overrides are blocked while a linked sample case is RESPONDED",
                )

    merged = {**discharge, **overrides}
    if parse_iso_date(merged["discharge_date"], "discharge_date") < parse_iso_date(
        merged["admit_date"], "admit_date"
    ):
        raise_err(ERR_INVALID_REQUEST, "discharge_date must be on or after admit_date")

    discharge.update(overrides)
    apply_discharge_evaluation(discharge)
    db.touch(discharge)

    if discharge["status"] == "EXCLUDED":
        cascade_discharge_excluded(discharge)

    return success_object(discharge_view(discharge))
