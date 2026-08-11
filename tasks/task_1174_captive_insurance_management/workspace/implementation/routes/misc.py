"""AuditLog nested routes, flat GET endpoints, filtered-list endpoints, and the
clock test-driving endpoint."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import set_current
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services.core import (
    body,
    flat_allocation,
    flat_audit_log,
    flat_claim,
    flat_collateral,
    flat_filing,
    flat_fronting,
    flat_meeting,
    flat_program,
    flat_reserve,
    flat_statement,
    flat_tax_position,
    flat_tpa,
    flat_unit,
    get_audit_log,
    get_captive,
)

bp = Blueprint("misc", __name__)

AUDIT_ROLES = ("CaptiveManager", "DomicileRegulator")


# ---------------------------------------------------------------------------
# Nested audit-log routes
# ---------------------------------------------------------------------------

@bp.get("/api/captives/<captiveId>/audit-logs")
def list_audit_logs(captiveId):
    require_roles(*AUDIT_ROLES)
    get_captive(captiveId)
    items = [a for a in db.audit_logs.values() if a["captive_id"] == captiveId]
    et = request.args.get("entity_type")
    if et:
        items = [a for a in items if a["entity_type"] == et]
    at = request.args.get("action_type")
    if at:
        items = [a for a in items if a["action_type"] == at]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/audit-logs/<logId>")
def get_audit_log_route(captiveId, logId):
    require_roles(*AUDIT_ROLES)
    captive = get_captive(captiveId)
    return ok(get_audit_log(captive, logId), 200)


# ---------------------------------------------------------------------------
# Flat GET endpoints (single resource by id)
# ---------------------------------------------------------------------------

@bp.get("/api/domicile-filings/<filingId>")
def flat_get_filing(filingId):
    require_roles("CaptiveManager", "DomicileRegulator")
    return ok(flat_filing(filingId), 200)


@bp.get("/api/programs/<programId>")
def flat_get_program(programId):
    require_roles("CaptiveManager", "Underwriter", "Actuary", "ClaimsAdjuster")
    return ok(flat_program(programId), 200)


@bp.get("/api/fronting-arrangements/<frontingId>")
def flat_get_fronting(frontingId):
    require_roles("CaptiveManager", "Underwriter")
    return ok(flat_fronting(frontingId), 200)


@bp.get("/api/collateral-postings/<collateralId>")
def flat_get_collateral(collateralId):
    require_roles("CaptiveManager", "Underwriter")
    return ok(flat_collateral(collateralId), 200)


@bp.get("/api/operating-units/<unitId>")
def flat_get_unit(unitId):
    require_roles("CaptiveManager", "Underwriter", "Actuary")
    return ok(flat_unit(unitId), 200)


@bp.get("/api/premium-allocations/<allocId>")
def flat_get_allocation(allocId):
    require_roles("CaptiveManager", "Underwriter", "Actuary")
    return ok(flat_allocation(allocId), 200)


@bp.get("/api/claims/<claimId>")
def flat_get_claim(claimId):
    require_roles("CaptiveManager", "Underwriter", "Actuary", "ClaimsAdjuster")
    return ok(flat_claim(claimId), 200)


@bp.get("/api/tpa-assignments/<tpaId>")
def flat_get_tpa(tpaId):
    require_roles("CaptiveManager", "ClaimsAdjuster")
    return ok(flat_tpa(tpaId), 200)


@bp.get("/api/actuarial-reserves/<reserveId>")
def flat_get_reserve(reserveId):
    require_roles("CaptiveManager", "Underwriter", "Actuary")
    return ok(flat_reserve(reserveId), 200)


@bp.get("/api/annual-statements/<statementId>")
def flat_get_statement(statementId):
    require_roles("CaptiveManager", "Actuary", "BoardDirector")
    return ok(flat_statement(statementId), 200)


@bp.get("/api/board-meetings/<meetingId>")
def flat_get_meeting(meetingId):
    require_roles("CaptiveManager", "BoardDirector")
    return ok(flat_meeting(meetingId), 200)


@bp.get("/api/tax-positions/<positionId>")
def flat_get_tax_position(positionId):
    require_roles("CaptiveManager", "TaxAdvisor")
    return ok(flat_tax_position(positionId), 200)


@bp.get("/api/audit-logs/<logId>")
def flat_get_audit_log(logId):
    require_roles(*AUDIT_ROLES)
    return ok(flat_audit_log(logId), 200)


# ---------------------------------------------------------------------------
# Filtered-list endpoints
# ---------------------------------------------------------------------------

def _list(store_values, filters, roles):
    require_roles(*roles)
    items = list(store_values)
    for param, field in filters:
        val = request.args.get(param)
        if val:
            items = [i for i in items if str(i.get(field)) == val]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/domicile-filings")
def flat_list_filings():
    return _list(db.filings.values(), [("captive_id", "captive_id")],
                 ("CaptiveManager", "DomicileRegulator"))


@bp.get("/api/programs")
def flat_list_programs():
    return _list(db.programs.values(), [("captive_id", "captive_id")],
                 ("CaptiveManager", "Underwriter", "Actuary", "ClaimsAdjuster"))


@bp.get("/api/fronting-arrangements")
def flat_list_frontings():
    return _list(db.frontings.values(),
                 [("program_id", "program_id"), ("captive_id", "captive_id")],
                 ("CaptiveManager", "Underwriter"))


@bp.get("/api/collateral-postings")
def flat_list_collaterals():
    return _list(db.collaterals.values(),
                 [("fronting_arrangement_id", "fronting_arrangement_id")],
                 ("CaptiveManager", "Underwriter"))


@bp.get("/api/operating-units")
def flat_list_units():
    return _list(db.units.values(), [("captive_id", "captive_id")],
                 ("CaptiveManager", "Underwriter", "Actuary"))


@bp.get("/api/premium-allocations")
def flat_list_allocations():
    return _list(db.allocations.values(),
                 [("program_id", "program_id"),
                  ("operating_unit_id", "operating_unit_id"),
                  ("captive_id", "captive_id")],
                 ("CaptiveManager", "Underwriter", "Actuary"))


@bp.get("/api/claims")
def flat_list_claims():
    return _list(db.claims.values(),
                 [("program_id", "program_id"),
                  ("operating_unit_id", "operating_unit_id"),
                  ("captive_id", "captive_id"),
                  ("tpa_assigned_id", "tpa_assigned_id")],
                 ("CaptiveManager", "Underwriter", "Actuary", "ClaimsAdjuster"))


@bp.get("/api/tpa-assignments")
def flat_list_tpas():
    return _list(db.tpas.values(), [("claim_id", "claim_id")],
                 ("CaptiveManager", "ClaimsAdjuster"))


@bp.get("/api/actuarial-reserves")
def flat_list_reserves():
    return _list(db.reserves.values(),
                 [("program_id", "program_id"), ("captive_id", "captive_id")],
                 ("CaptiveManager", "Underwriter", "Actuary"))


@bp.get("/api/annual-statements")
def flat_list_statements():
    return _list(db.statements.values(), [("captive_id", "captive_id")],
                 ("CaptiveManager", "Actuary", "BoardDirector"))


@bp.get("/api/board-meetings")
def flat_list_meetings():
    return _list(db.meetings.values(), [("captive_id", "captive_id")],
                 ("CaptiveManager", "BoardDirector"))


@bp.get("/api/tax-positions")
def flat_list_tax_positions():
    return _list(db.tax_positions.values(), [("captive_id", "captive_id")],
                 ("CaptiveManager", "TaxAdvisor"))


@bp.get("/api/audit-logs")
def flat_list_audit_logs():
    return _list(db.audit_logs.values(),
                 [("captive_id", "captive_id"),
                  ("entity_type", "entity_type"),
                  ("action_type", "action_type")],
                 ("CaptiveManager", "DomicileRegulator"))


# ---------------------------------------------------------------------------
# Clock test-driving endpoint
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("CaptiveManager")
    data = body()
    target = data.get("to_iso8601")
    if target is None or not isinstance(target, str) or not set_current(target):
        raise ApiError("ERR_INVALID_REQUEST",
                       "to_iso8601 must be a valid ISO 8601 timestamp")
    return ok({}, 200)
