"""Jurisdiction endpoints."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_DUPLICATE_JURISDICTION_STATE,
    ERR_INVALID_REQUEST,
)
from middleware import (
    require_roles, get_json_body, require_fields, reject_unknown_fields,
    require_enum, require_string, require_int, opt_int, opt_bool, opt_enum,
)
from response import success_object

bp = Blueprint("jurisdictions", __name__)

IBC_EDITIONS = ("IBC_2018", "IBC_2021", "IBC_2024")
ASCE7_EDITIONS = ("ASCE7_16", "ASCE7_22")
FEE_METHODS = ("VALUATION", "SQUARE_FOOTAGE")
SLA_MODES = ("BUSINESS", "CALENDAR")
READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")


def _get_or_404(jid):
    j = db.jurisdictions.get(jid)
    if j is None:
        raise ApiError(ERR_JURISDICTION_NOT_FOUND, 404, "No jurisdiction with the given id")
    return j


@bp.post("/plan-review/jurisdictions")
def create_jurisdiction():
    require_roles("PlatformAdmin")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {
        "state_code", "ibc_edition", "asce7_edition", "fee_method",
        "turnaround_days", "sla_mode", "free_resubmittal_cycles",
        "requires_se_seal", "allows_deferred_submittals",
    })
    require_fields(body, ["state_code", "ibc_edition", "asce7_edition", "fee_method",
                          "turnaround_days", "sla_mode"])
    state_code = require_string(body, "state_code")
    if len(state_code) != 2 or not state_code.isupper() or not state_code.isalpha():
        raise ApiError(ERR_INVALID_REQUEST, 400, "state_code must be uppercase 2 letters")
    ibc_edition = require_enum(body, "ibc_edition", IBC_EDITIONS)
    asce7_edition = require_enum(body, "asce7_edition", ASCE7_EDITIONS)
    fee_method = require_enum(body, "fee_method", FEE_METHODS)
    turnaround_days = require_int(body, "turnaround_days")
    sla_mode = require_enum(body, "sla_mode", SLA_MODES)
    free_resubmittal_cycles = opt_int(body, "free_resubmittal_cycles", 2)
    requires_se_seal = opt_bool(body, "requires_se_seal", False)
    allows_deferred_submittals = opt_bool(body, "allows_deferred_submittals", True)

    # business constraint: state_code unique
    for j in db.jurisdictions.values():
        if j["state_code"] == state_code:
            raise ApiError(ERR_DUPLICATE_JURISDICTION_STATE, 409,
                           "A jurisdiction with the same state_code already exists")

    entity = db.stamp_new({
        "state_code": state_code,
        "ibc_edition": ibc_edition,
        "asce7_edition": asce7_edition,
        "fee_method": fee_method,
        "turnaround_days": turnaround_days,
        "sla_mode": sla_mode,
        "free_resubmittal_cycles": free_resubmittal_cycles,
        "requires_se_seal": requires_se_seal,
        "allows_deferred_submittals": allows_deferred_submittals,
    })
    db.jurisdictions[entity["id"]] = entity
    return success_object(db.serialize(entity), status=201)


@bp.get("/plan-review/jurisdictions/<jid>")
def get_jurisdiction(jid):
    require_roles(*READ_ROLES)
    j = _get_or_404(jid)
    return success_object(db.serialize(j))


@bp.put("/plan-review/jurisdictions/<jid>")
def update_jurisdiction(jid):
    require_roles("PlatformAdmin")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {
        "ibc_edition", "asce7_edition", "fee_method", "turnaround_days",
        "sla_mode", "free_resubmittal_cycles", "requires_se_seal",
        "allows_deferred_submittals",
    })
    j = _get_or_404(jid)

    if "ibc_edition" in body and body["ibc_edition"] is not None:
        j["ibc_edition"] = require_enum(body, "ibc_edition", IBC_EDITIONS)
    if "asce7_edition" in body and body["asce7_edition"] is not None:
        j["asce7_edition"] = require_enum(body, "asce7_edition", ASCE7_EDITIONS)
    if "fee_method" in body and body["fee_method"] is not None:
        j["fee_method"] = require_enum(body, "fee_method", FEE_METHODS)
    if "turnaround_days" in body and body["turnaround_days"] is not None:
        j["turnaround_days"] = require_int(body, "turnaround_days")
    if "sla_mode" in body and body["sla_mode"] is not None:
        j["sla_mode"] = require_enum(body, "sla_mode", SLA_MODES)
    if "free_resubmittal_cycles" in body and body["free_resubmittal_cycles"] is not None:
        j["free_resubmittal_cycles"] = require_int(body, "free_resubmittal_cycles")
    if "requires_se_seal" in body and body["requires_se_seal"] is not None:
        j["requires_se_seal"] = opt_bool(body, "requires_se_seal")
    if "allows_deferred_submittals" in body and body["allows_deferred_submittals"] is not None:
        j["allows_deferred_submittals"] = opt_bool(body, "allows_deferred_submittals")

    db.touch(j)
    return success_object(db.serialize(j))
