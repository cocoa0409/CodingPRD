"""CueSheet endpoints (PRD §3.7)."""

from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import fail
from middleware import (
    body,
    is_role,
    opt_string,
    req_datetime,
    req_enum,
    req_string,
    require_role,
    user_id,
)
from response import object_response, page_response, pagination
from routes.common import (
    MARKET_TIERS,
    PREFIX,
    USAGE_TYPES,
    guard_licensee,
    require_state,
    set_dt,
)
from services import calc
from services.cascade import accept_cue_sheet, register_cue_sheet, reject_cue_sheet
from services.derive import lookup, rows, serialize_cue_sheet

bp = Blueprint("cue_sheets", __name__)


def _parse_cues(data):
    """Schema pass over cues[]; elements are validated in array order."""
    value = data.get("cues")
    if value is None:
        fail("ERR_VALIDATION", "Field 'cues' is required.")
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "Field 'cues' must be an array.")
    if len(value) < 1 or len(value) > 20:
        fail("ERR_VALIDATION", "Field 'cues' must hold between 1 and 20 members.")
    parsed = []
    for element in value:
        if not isinstance(element, dict):
            fail("ERR_VALIDATION", "every cues[] member must be an object.")
        composition_id = element.get("composition_id")
        if not isinstance(composition_id, str) or composition_id.strip() == "":
            fail("ERR_VALIDATION", "cues[].composition_id must be a string.")
        usage_type = element.get("usage_type")
        if not isinstance(usage_type, str) or usage_type not in USAGE_TYPES:
            fail("ERR_VALIDATION", "cues[].usage_type must be one of %s." % (
                ", ".join(USAGE_TYPES),
            ))
        duration = element.get("duration_sec")
        if isinstance(duration, bool) or not isinstance(duration, int):
            fail("ERR_VALIDATION", "cues[].duration_sec must be an integer.")
        if duration < 1 or duration > 3600:
            fail("ERR_VALIDATION", "cues[].duration_sec must be between 1 and 3600.")
        parsed.append(
            {
                "composition_id": composition_id,
                "usage_type": usage_type,
                "duration_sec": duration,
            }
        )
    return parsed


@bp.post(PREFIX + "/cue-sheets")
def create_cue_sheet():
    data = body()
    production_title = req_string(data, "production_title", allow_empty=False)
    raw_date, broadcast = req_datetime(data, "broadcast_date")
    market_tier = req_enum(data, "market_tier", MARKET_TIERS)
    cues = _parse_cues(data)
    license_id = opt_string(data, "license_id")
    usage_report_id = opt_string(data, "usage_report_id")

    if (license_id is None) == (usage_report_id is None):              # 24
        fail("ERR_CUE_SHEET_PARENT_INVALID", "supply exactly one of license_id / usage_report_id.")

    license_row = None
    report = None
    if license_id is not None:                                        # 3, declared order
        license_row = lookup("licenses", license_id)
    if usage_report_id is not None:
        report = lookup("usage_reports", usage_report_id)
    for cue in cues:
        lookup("compositions", cue["composition_id"])

    require_role("Licensee", "LicensingAgent")                        # 4
    if license_row is not None:                                      # 5
        guard_licensee(license_row["licensee_id"])
    else:
        blanket = DB.blankets.get(report["blanket_agreement_id"])
        if blanket is not None:
            guard_licensee(blanket["licensee_id"])

    for cue in cues:                                                 # 25, array order
        composition = DB.compositions[cue["composition_id"]]
        if license_row is not None:
            if composition["id"] != license_row["composition_id"]:
                fail(
                    "ERR_CUE_COMPOSITION_NOT_COVERED",
                    "the cue cites a work this licence does not cover.",
                )
        else:
            agreement = DB.agreements.get(composition["agreement_id"])
            if composition["availability_status"] == "WITHDRAWN" or (
                agreement is not None and not agreement["blanket_opt_in"]
            ):
                fail(
                    "ERR_CUE_COMPOSITION_NOT_COVERED",
                    "the cue cites a work not covered by blanket reporting.",
                )

    breakdown = []
    total_credits = Decimal("0")
    total_seconds = 0
    by_composition = {}
    for cue in cues:
        credits = calc.cue_credits(cue["duration_sec"], cue["usage_type"], market_tier)
        breakdown.append(
            {
                "composition_id": cue["composition_id"],
                "usage_type": cue["usage_type"],
                "duration_sec": cue["duration_sec"],
                "credits": calc.num(credits),
            }
        )
        total_credits += credits
        total_seconds += cue["duration_sec"]
        by_composition[cue["composition_id"]] = (
            by_composition.get(cue["composition_id"], Decimal("0")) + credits
        )

    row = DB.new_row()
    row.update(
        {
            "license_id": license_row["id"] if license_row is not None else None,
            "usage_report_id": report["id"] if report is not None else None,
            "production_title": production_title,
            "market_tier": market_tier,
            "cues": cues,
            "status": "COLLECTED",
            "cue_credit_breakdown": breakdown,
            "_total_credits": calc.dp2(total_credits),
            "total_seconds": total_seconds,
            "_credits_by_composition": by_composition,
            "society_reference": None,
            "registration_round": 0,
            "registered_at": None,
            "rejection_reason": None,
        }
    )
    set_dt(row, "broadcast_date", raw_date, broadcast)
    DB.cue_sheets[row["id"]] = row
    return object_response(serialize_cue_sheet(row), 201)


@bp.get(PREFIX + "/cue-sheets/<cue_sheet_id>")
def get_cue_sheet(cue_sheet_id):
    row = lookup("cue_sheets", cue_sheet_id)
    require_role(
        "LicensingAgent", "RightsManager", "RoyaltyAccountant", "Licensee", "Composer"
    )
    if is_role("Licensee"):
        if row["license_id"] is not None:
            license_row = DB.licenses.get(row["license_id"])
            if license_row is not None:
                guard_licensee(license_row["licensee_id"])
        else:
            report = DB.usage_reports.get(row["usage_report_id"])
            blanket = DB.blankets.get(report["blanket_agreement_id"]) if report else None
            if blanket is not None:
                guard_licensee(blanket["licensee_id"])
    if is_role("Composer"):
        owners = set()
        for composition_id in row["_credits_by_composition"]:
            composition = DB.compositions.get(composition_id)
            if composition is not None:
                owners.add(composition["composer_id"])
        if user_id() not in owners:
            fail("ERR_COMPOSER_IDENTITY_MISMATCH", "this sheet cites no work of yours.")
    return object_response(serialize_cue_sheet(row))


@bp.get(PREFIX + "/cue-sheets")
def list_cue_sheets():
    limit, offset = pagination(request.args)
    require_role("LicensingAgent", "RightsManager", "RoyaltyAccountant")
    result = rows("cue_sheets")
    for name in ("license_id", "usage_report_id", "status"):
        wanted = request.args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_cue_sheet)


@bp.post(PREFIX + "/cue-sheets/<cue_sheet_id>/register")
def register(cue_sheet_id):
    data = body()
    society_reference = req_string(data, "society_reference", allow_empty=False)
    row = lookup("cue_sheets", cue_sheet_id)
    require_role("RightsManager")
    require_state(row, "status", ("COLLECTED", "REJECTED_BY_SOCIETY"), "cue_sheet")
    if row["_total_credits"] == Decimal("0.00"):                       # 38
        fail("ERR_CUE_SHEET_HAS_NO_CREDITS", "the sheet carries no performance credits.")
    for composition_id in row["_credits_by_composition"]:              # 39
        composition = DB.compositions.get(composition_id)
        if composition is None:
            continue
        composer = DB.composers.get(composition["composer_id"])
        if composer is None or composer["pro_affiliation"] == "NONE":
            fail("ERR_COMPOSER_NOT_AFFILIATED", "a cited composer has no PRO affiliation.")
    register_cue_sheet(row, society_reference)
    return object_response(serialize_cue_sheet(row))


@bp.post(PREFIX + "/cue-sheets/<cue_sheet_id>/society-decision")
def society_decision(cue_sheet_id):
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    rejection_reason = opt_string(data, "rejection_reason")
    row = lookup("cue_sheets", cue_sheet_id)
    require_role("RightsManager")
    require_state(row, "status", ("REGISTERED",), "cue_sheet")
    if decision == "ACCEPT":
        accept_cue_sheet(row)
    else:
        reject_cue_sheet(row, rejection_reason)
    return object_response(serialize_cue_sheet(row))
