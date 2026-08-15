"""Veterinary report endpoints (PRD 3.7): mortality claim documentation."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy, resolve_claim
from serializers import vet_report_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_string, require_enum,
    require_bool, require_datetime, parse_pagination, paginate, sort_created, dt,
)

bp = Blueprint("vet_reports", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")

CREATE_FIELDS = {
    "veterinarian_license", "report_kind", "cause_of_death",
    "necropsy_performed", "death_date",
}
REPORT_KINDS = {"VETERINARY_CERTIFICATE", "NECROPSY_REPORT", "THIRD_PARTY_AFFIDAVIT"}


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/veterinary-reports",
          methods=["POST"])
@require_roles("Policyholder")
def create_vet_report(carrierId: str, policyId: str, claimId: str,
                      _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)

    if claim["claim_kind"] != "LIVESTOCK_MORTALITY":
        raise_err(ERR_INVALID_REQUEST,
                  "Veterinary reports attach to livestock mortality claims only")

    veterinarian_license = require_string(body, "veterinarian_license")
    report_kind = require_enum(body, "report_kind", REPORT_KINDS)
    cause_of_death = body.get("cause_of_death")
    if report_kind in ("VETERINARY_CERTIFICATE", "NECROPSY_REPORT"):
        if not isinstance(cause_of_death, str) or cause_of_death == "":
            raise_err(ERR_INVALID_REQUEST,
                      "cause_of_death must be non-empty for certificates and necropsy reports")
    elif cause_of_death is not None and not isinstance(cause_of_death, str):
        raise_err(ERR_INVALID_REQUEST, "cause_of_death must be a string")
    necropsy_performed = require_bool(body, "necropsy_performed")
    death_date = require_datetime(body, "death_date")

    loss_dt = dt(claim["loss_date"])
    if abs(dt(death_date) - loss_dt) > timedelta(days=2):
        raise_err(ERR_INVALID_REQUEST,
                  "death_date must fall within two days of the claim's loss_date")

    now = carrier["current_utc"]
    report = db.stamp_new({
        "claim_id": claim["id"],
        "veterinarian_license": veterinarian_license,
        "report_kind": report_kind,
        "cause_of_death": cause_of_death,
        "necropsy_performed": necropsy_performed,
        "death_date": death_date,
        "submitted_at": now,
    }, now)
    db.vet_reports[report["id"]] = report

    core.recompute_doc_posture(claim, now)
    return success_object(vet_report_view(report), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/veterinary-reports",
          methods=["GET"])
@require_roles(*ALL_ROLES)
def list_vet_reports(carrierId: str, policyId: str, claimId: str,
                     _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    items = core.vet_reports_of_claim(claim["id"])
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([vet_report_view(r) for r in page], limit, offset, total)
