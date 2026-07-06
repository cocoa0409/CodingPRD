from flask import request

from db import db
from errors import (
    ERR_GRANT_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_OUTCOME_ALREADY_REVERSED,
    ERR_OUTCOME_REPORT_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    raise_error,
)
from middleware import require_roles
from response import paginate, success
from services import (
    _stamp_new,
    _touch,
    compute_service_cost_final,
    recompute_grant_remaining,
    serialise_outcome,
)
from validate import (
    OUTCOME_ENUM,
    parse_pagination,
    require_body,
    require_bool,
    require_enum,
    require_number,
)


def _referral_or_404(rid: str):
    r = db.referrals.get(rid)
    if not r:
        raise_error(ERR_REFERRAL_NOT_FOUND, f"referral {rid} not found")
    return r


def _outcome_or_404(oid: str):
    o = db.outcome_reports.get(oid)
    if not o:
        raise_error(ERR_OUTCOME_REPORT_NOT_FOUND, f"outcome report {oid} not found")
    return o


def register(app):
    @app.post("/referrals/<rid>/outcome-reports")
    @require_roles("Caseworker", "ProviderStaff", "PlatformAdmin")
    def create_outcome(rid):
        r = _referral_or_404(rid)
        body = require_body(request.get_json(silent=True))
        outcome = require_enum(body, "outcome", OUTCOME_ENUM)
        service_hours = require_number(body, "service_hours")
        if service_hours < 0:
            raise_error(ERR_INVALID_REQUEST, "service_hours must be >= 0")
        follow_up = require_bool(body, "follow_up_needed")

        program = db.programs.get(r["program_id"])
        if not program:
            raise_error(ERR_INVALID_REQUEST, "referral has dangling program_id")
        funder = db.funders.get(program["funder_id"])
        if not funder:
            raise_error(ERR_INVALID_REQUEST, "program has dangling funder_id")

        # Priority 29: computed service_cost_final_cents <= Funder.grant_cents_remaining
        cost = compute_service_cost_final(outcome, service_hours, program["unit_cost_cents"])
        if cost > funder["grant_cents_remaining"]:
            raise_error(ERR_GRANT_INSUFFICIENT,
                        "computed cost exceeds funder grant_cents_remaining")

        entity = {
            "referral_id": rid,
            "outcome": outcome,
            "service_hours": service_hours,
            "follow_up_needed": follow_up,
            "service_cost_final_cents": cost,
            "status": "ACTIVE",
        }
        _stamp_new(entity)
        db.outcome_reports[entity["id"]] = entity
        # Ledger recompute (also equivalent to funder["grant_cents_remaining"] -= cost).
        recompute_grant_remaining(funder)
        return success(serialise_outcome(entity), 201)

    @app.get("/referrals/<rid>/outcome-reports")
    @require_roles("Caseworker", "ProviderStaff", "PlatformAdmin", "FunderReporter")
    def list_outcomes(rid):
        _referral_or_404(rid)
        limit, offset = parse_pagination(request.args)
        items = [o for o in db.outcome_reports.values() if o["referral_id"] == rid]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_outcome(o) for o in window], 200, "array", pg)

    @app.post("/outcome-reports/<oid>/reverse")
    @require_roles("PlatformAdmin")
    def reverse_outcome(oid):
        o = _outcome_or_404(oid)
        # Priority 17: status must be ACTIVE and program's funder_reporting_posture != ARCHIVED.
        if o["status"] != "ACTIVE":
            raise_error(ERR_OUTCOME_ALREADY_REVERSED, "outcome is not ACTIVE")
        ref = db.referrals.get(o["referral_id"])
        prog = db.programs.get(ref["program_id"]) if ref else None
        if not prog:
            raise_error(ERR_INVALID_REQUEST, "outcome has dangling referral/program")
        if prog["funder_reporting_posture"] == "ARCHIVED":
            raise_error(ERR_OUTCOME_ALREADY_REVERSED,
                        "program funder_reporting_posture is ARCHIVED — outcomes are frozen")
        o["status"] = "REVERSED"
        _touch(o)
        funder = db.funders.get(prog["funder_id"])
        if funder:
            recompute_grant_remaining(funder)
        return success(serialise_outcome(o), 200)
