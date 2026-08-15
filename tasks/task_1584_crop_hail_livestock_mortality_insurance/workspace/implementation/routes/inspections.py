"""Field inspection endpoints (PRD 3.7): submission moves the claim
INSPECTION_SCHEDULED → INSPECTED and writes the provisional indemnity."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_CLAIM_NOT_IN_INSPECTION_SCHEDULED,
    ERR_NOT_ASSIGNED_ADJUSTER, ERR_NECROPSY_REQUIRED,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy, resolve_claim
from serializers import field_inspection_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_string, require_datetime,
    require_int, parse_pagination, paginate, sort_created, dt,
)

bp = Blueprint("inspections", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")

CREATE_FIELDS = {
    "adjuster_id", "scheduled_for", "observed_percent_damage_pct",
    "observed_appraisal_cents", "observed_deceased_count", "notes",
}


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/field-inspections",
          methods=["POST"])
@require_roles("Adjuster")
def create_field_inspection(carrierId: str, policyId: str, claimId: str,
                            _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    adjuster_id = require_string(body, "adjuster_id")
    scheduled_for = require_datetime(body, "scheduled_for")
    notes = body.get("notes")
    if notes is None or not isinstance(notes, str):
        raise_err(ERR_INVALID_REQUEST, "notes is required and must be a string")

    if claim["claim_kind"] == "HAIL_DAMAGE":
        observed_percent = require_int(
            body, "observed_percent_damage_pct", minimum=0, maximum=100)
        observed_appraisal = None
        observed_deceased = None
    else:
        observed_percent = None
        observed_appraisal = require_int(body, "observed_appraisal_cents", minimum=0)
        observed_deceased = require_int(body, "observed_deceased_count", minimum=0)

    # State guard, then caller identity (PRD 3.7 fixed order).
    if claim["claim_state"] != "INSPECTION_SCHEDULED":
        raise_err(ERR_CLAIM_NOT_IN_INSPECTION_SCHEDULED,
                  "field-inspection submission requires claim_state INSPECTION_SCHEDULED")
    if _user_id != claim["adjuster_id"] or adjuster_id != claim["adjuster_id"]:
        raise_err(ERR_NOT_ASSIGNED_ADJUSTER,
                  "Caller is not the claim's assigned adjuster")

    # Livestock safety gate: claims appraised above $5,000 need a necropsy
    # report with necropsy_performed=true on file before inspection.
    if (claim["claim_kind"] == "LIVESTOCK_MORTALITY"
            and claim["appraisal_value_cents"] > core.NECROPSY_THRESHOLD_CENTS):
        has_necropsy = any(
            r["necropsy_performed"] for r in core.vet_reports_of_claim(claim["id"])
        )
        if not has_necropsy:
            raise_err(ERR_NECROPSY_REQUIRED,
                      "Livestock claim above $5,000 requires a veterinary report "
                      "with necropsy_performed=true before inspection")

    now = carrier["current_utc"]
    now_dt = dt(now)
    unit = db.coverage_units.get(claim["coverage_unit_id"])

    observed = {
        "observed_percent_damage_pct": observed_percent,
        "observed_appraisal_cents": observed_appraisal,
        "observed_deceased_count": observed_deceased,
    }
    provisional = core.compute_provisional_indemnity(claim, unit, observed)

    inspection = db.stamp_new({
        "claim_id": claim["id"],
        "adjuster_id": claim["adjuster_id"],
        "scheduled_for": scheduled_for,
        "inspected_at": now,
        "within_inspection_window": now_dt <= dt(claim["reported_at"]) + timedelta(days=7),
        "observed_percent_damage_pct": observed_percent,
        "observed_appraisal_cents": observed_appraisal,
        "observed_deceased_count": observed_deceased,
        "provisional_indemnity_cents": provisional,
        "notes": notes,
    }, now)
    db.field_inspections[inspection["id"]] = inspection

    claim["provisional_indemnity_cents"] = provisional
    claim["claim_state"] = "INSPECTED"
    db.touch(claim, now)
    return success_object(field_inspection_view(inspection), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/field-inspections",
          methods=["GET"])
@require_roles(*ALL_ROLES)
def list_field_inspections(carrierId: str, policyId: str, claimId: str,
                           _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    items = [i for i in db.field_inspections.values() if i["claim_id"] == claim["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([field_inspection_view(i) for i in page], limit, offset, total)
