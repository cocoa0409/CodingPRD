"""Closing statement, proration, and true-up adjustment routes (PRD §3.11).

Rounding order is pinned: each proration line rounds half-up first, then the
rounded lines sum into total_prorations_cents; cash_to_close composes in the
pinned layered order (price -> less loan -> plus prorations -> plus
assumption fee -> less earnest money).
"""

from flask import Blueprint, g, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, ref_not_found, req_dt, req_enum, req_int, req_str
from services import domain

bp = Blueprint("closing", __name__)

# DueDiligenceOfficer is excluded from the closing read surface.
STMT_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "EscrowOfficer",
              "AssetManager", "CapitalMarketsOfficer", "PlatformAdmin")
# True-up read surface additionally excludes CapitalMarketsOfficer.
TRUEUP_READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "EscrowOfficer",
                     "AssetManager", "PlatformAdmin")
PRORATION_LINE_TYPES = {"BASE_RENT", "CAM", "TAX", "INSURANCE", "UTILITY"}
TRUEUP_LINE_TYPES = PRORATION_LINE_TYPES | {"REPAIR_CREDIT", "OTHER"}


def _parse_proration_inputs(deal, data):
    """Validate and return the proration_inputs array (each entry becomes one
    immutable Proration line at issue)."""
    inputs = data.get("proration_inputs")
    if inputs is None:
        # A reissued statement carries its prior inputs for re-issue.
        inputs = []
    if not isinstance(inputs, list):
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "proration_inputs must be an array", 400)
    parsed = []
    for i, entry in enumerate(inputs):
        if not isinstance(entry, dict):
            raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                           f"proration_inputs[{i}] must be an object", 400)
        line_type = req_enum(entry, "line_type", PRORATION_LINE_TYPES)
        lease_id = req_str(entry, "lease_id")
        lease = db.stores["leases"].get(lease_id)
        if lease is None:
            ref_not_found(f"proration_inputs[{i}].lease_id references a non-existent lease")
        prop = db.stores["properties"].get(lease["property_id"])
        if prop is None or prop["deal_id"] != deal["id"]:
            ref_not_found(f"proration_inputs[{i}].lease_id references a lease outside this deal")
        amount = req_int(entry, "annual_amount_cents")
        period_start = req_dt(entry, "period_start")
        period_end = req_dt(entry, "period_end")
        parsed.append({
            "line_type": line_type,
            "lease_id": lease_id,
            "annual_amount_cents": amount,
            "period_start": period_start,
            "period_end": period_end,
        })
    return parsed


def _issue_computations(deal, stmt, closing_date, proration_inputs):
    """Create the immutable proration lines and compute statement totals."""
    lines = []
    for entry in proration_inputs:
        prorated, direction = domain.compute_proration_line(
            entry["line_type"], entry["annual_amount_cents"],
            entry["period_start"], entry["period_end"], closing_date)
        line = db.make_line({
            "closing_statement_id": stmt["id"],
            "line_type": entry["line_type"],
            "lease_id": entry["lease_id"],
            "annual_amount_cents": entry["annual_amount_cents"],
            "period_start": entry["period_start"],
            "period_end": entry["period_end"],
            "prorated_cents": prorated,
            "direction": direction,
        })
        db.stores["prorations"][line["id"]] = line
        lines.append(line)
    total = domain.compute_total_prorations(lines)
    psa = domain.active_psa(deal["id"])
    stmt["closing_date"] = closing_date
    stmt["total_prorations_cents"] = total
    stmt["cash_to_close_cents"] = domain.compute_cash_to_close(deal, psa, total)


# ---------------------------------------------------------------------------
# ClosingStatement
# ---------------------------------------------------------------------------
@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements", methods=["GET"])
def list_statements(deal_id):
    require_role(*STMT_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.statements_of(deal["id"])
    v = request.args.get("status")
    if v is not None:
        items = [s for s in items if s["status"] == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>", methods=["GET"])
def get_statement(deal_id, stmt_id):
    require_role(*STMT_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_statement_scoped(deal, stmt_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/issue", methods=["POST"])
def issue_statement(deal_id, stmt_id):
    require_role("EscrowOfficer")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    if stmt["status"] != "DRAFT":
        raise ApiError("ERR_STATEMENT_INVALID_STATE",
                       "issue requires statement status DRAFT", 409)
    if deal.get("posture") != "CLEAR_TO_CLOSE":
        raise ApiError("ERR_NOT_CLEAR_TO_CLOSE",
                       "issue requires deal posture CLEAR_TO_CLOSE", 422)
    data = body()
    closing_date = req_dt(data, "closing_date")
    psa = domain.active_psa(deal["id"])
    if psa is not None and psa.get("executed_at"):
        if db.parse_dt(closing_date) < db.parse_dt(psa["executed_at"]):
            raise ApiError("ERR_CLOSING_DATE_BEFORE_EXECUTION",
                           "closing_date must not precede the PSA executed_at", 422)
    inputs = _parse_proration_inputs(deal, data)
    if not inputs and stmt.get("_proration_inputs"):
        inputs = stmt["_proration_inputs"]
    _issue_computations(deal, stmt, closing_date, inputs)
    stmt["status"] = "ISSUED"
    stmt["_issued_by"] = g.user_id
    bump(stmt)
    return ok(db.pub(stmt))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/acknowledge", methods=["POST"])
def acknowledge_statement(deal_id, stmt_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    if stmt["status"] != "ISSUED":
        raise ApiError("ERR_STATEMENT_INVALID_STATE",
                       "acknowledge requires statement status ISSUED", 409)
    # Segregation of duties: acknowledger != issuing EscrowOfficer.
    if stmt.get("_issued_by") is not None and g.user_id == stmt["_issued_by"]:
        raise ApiError("ERR_SOD_VIOLATION",
                       "Acknowledging analyst must differ from the issuing escrow officer", 403)
    stmt["status"] = "ACKNOWLEDGED"
    bump(stmt)
    return ok(db.pub(stmt))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/reissue", methods=["POST"])
def reissue_statement(deal_id, stmt_id):
    require_role("EscrowOfficer")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    if stmt["status"] != "ISSUED":
        raise ApiError("ERR_STATEMENT_INVALID_STATE",
                       "reissue requires statement status ISSUED", 409)
    data = body()
    expected = req_int(data, "expected_deal_version")
    if expected != deal["version"]:
        raise ApiError("ERR_STALE_DEAL_VERSION",
                       "expected_deal_version does not match the deal's current version", 412)
    closing_date = req_dt(data, "closing_date")
    psa = domain.active_psa(deal["id"])
    if psa is not None and psa.get("executed_at"):
        if db.parse_dt(closing_date) < db.parse_dt(psa["executed_at"]):
            raise ApiError("ERR_CLOSING_DATE_BEFORE_EXECUTION",
                           "closing_date must not precede the PSA executed_at", 422)
    inputs = _parse_proration_inputs(deal, data)
    stmt["status"] = "SUPERSEDED"
    bump(stmt)
    new_stmt = db.make_record({
        "deal_id": deal["id"],
        "statement_version": stmt["statement_version"] + 1,
        "closing_date": closing_date,
        "total_prorations_cents": 0,
        "cash_to_close_cents": 0,
        "provisional": True,
        "status": "DRAFT",
        "_issued_by": None,
        # The new draft carries the supplied proration inputs for re-issue.
        "_proration_inputs": inputs,
    })
    db.stores["statements"][new_stmt["id"]] = new_stmt
    deal["closing_statement_id"] = new_stmt["id"]
    bump(deal)
    return ok(db.pub(new_stmt))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/finalize-true-up", methods=["POST"])
def finalize_true_up(deal_id, stmt_id):
    require_role("EscrowOfficer")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    if stmt["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_STATEMENT_INVALID_STATE",
                       "finalize-true-up requires statement status ACKNOWLEDGED", 409)
    if deal["status"] != "CLOSED":
        raise ApiError("ERR_DEAL_NOT_CLOSED",
                       "finalize-true-up requires the deal to be CLOSED", 422)
    adjustments = domain.trueups_of(stmt["id"])
    for adj in adjustments:
        if adj["status"] not in ("FULLY_APPROVED", "REJECTED"):
            raise ApiError("ERR_TRUE_UP_PENDING",
                           "All true-up adjustments must be decided before finalize", 422)
    # Fold every fully-approved adjustment into the final-variant recompute.
    applied_total = 0
    for adj in adjustments:
        if adj["status"] == "FULLY_APPROVED":
            adj["status"] = "APPLIED"
            applied_total += adj["amount_cents"]
            bump(adj)
    stmt["total_prorations_cents"] = stmt["total_prorations_cents"] + applied_total
    psa = domain.active_psa(deal["id"])
    stmt["cash_to_close_cents"] = domain.compute_cash_to_close(
        deal, psa, stmt["total_prorations_cents"])
    stmt["provisional"] = False
    stmt["status"] = "TRUED_UP"
    bump(stmt)
    return ok(db.pub(stmt))


# ---------------------------------------------------------------------------
# Proration (read-only; lines are system-computed at issue)
# ---------------------------------------------------------------------------
@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/prorations", methods=["GET"])
def list_prorations(deal_id, stmt_id):
    require_role(*STMT_ROLES)
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    items = domain.prorations_of(stmt["id"])
    for param in ("line_type", "lease_id"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if str(p.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/prorations/<proration_id>", methods=["GET"])
def get_proration(deal_id, stmt_id, proration_id):
    require_role(*STMT_ROLES)
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    return ok(db.pub(domain.get_proration_scoped(stmt, proration_id)))


# ---------------------------------------------------------------------------
# TrueUpAdjustment
# ---------------------------------------------------------------------------
@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/true-ups", methods=["POST"])
def create_trueup(deal_id, stmt_id):
    require_role("AssetManager")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    data = body()
    adj = db.make_record({
        "closing_statement_id": stmt["id"],
        "line_type": req_enum(data, "line_type", TRUEUP_LINE_TYPES),
        "amount_cents": req_int(data, "amount_cents"),
        "reason": req_str(data, "reason"),
        "approved": False,
        "status": "PROPOSED",
        "_proposed_by": g.user_id,
    })
    db.stores["true_ups"][adj["id"]] = adj
    return created(db.pub(adj))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/true-ups", methods=["GET"])
def list_trueups(deal_id, stmt_id):
    require_role(*TRUEUP_READ_ROLES)
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    items = domain.trueups_of(stmt["id"])
    v = request.args.get("status")
    if v is not None:
        items = [a for a in items if a["status"] == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/true-ups/<adj_id>", methods=["GET"])
def get_trueup(deal_id, stmt_id, adj_id):
    require_role(*TRUEUP_READ_ROLES)
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    return ok(db.pub(domain.get_trueup_scoped(stmt, adj_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/true-ups/<adj_id>/escrow-approve", methods=["POST"])
def escrow_approve_trueup(deal_id, stmt_id, adj_id):
    require_role("EscrowOfficer")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    adj = domain.get_trueup_scoped(stmt, adj_id)
    if adj["status"] != "PROPOSED":
        raise ApiError("ERR_TRUE_UP_INVALID_STATE",
                       "escrow-approve requires status PROPOSED", 409)
    adj["status"] = "ESCROW_APPROVED"
    bump(adj)
    return ok(db.pub(adj))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/true-ups/<adj_id>/asset-manager-approve", methods=["POST"])
def asset_manager_approve_trueup(deal_id, stmt_id, adj_id):
    require_role("AssetManager")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    adj = domain.get_trueup_scoped(stmt, adj_id)
    if adj["status"] != "ESCROW_APPROVED":
        raise ApiError("ERR_TRUE_UP_INVALID_STATE",
                       "asset-manager-approve requires status ESCROW_APPROVED", 409)
    # Segregation of duties: approver != proposer.
    if adj.get("_proposed_by") is not None and g.user_id == adj["_proposed_by"]:
        raise ApiError("ERR_SOD_VIOLATION",
                       "Asset manager approver must differ from the adjustment proposer", 403)
    adj["status"] = "FULLY_APPROVED"
    adj["approved"] = True
    bump(adj)
    return ok(db.pub(adj))


@bp.route("/acquisition-deals/deals/<deal_id>/closing-statements/<stmt_id>/true-ups/<adj_id>/reject", methods=["POST"])
def reject_trueup(deal_id, stmt_id, adj_id):
    require_role("EscrowOfficer")
    deal = domain.get_deal(deal_id)
    stmt = domain.get_statement_scoped(deal, stmt_id)
    adj = domain.get_trueup_scoped(stmt, adj_id)
    if adj["status"] != "PROPOSED":
        raise ApiError("ERR_TRUE_UP_INVALID_STATE",
                       "reject requires status PROPOSED", 409)
    adj["status"] = "REJECTED"
    bump(adj)
    return ok(db.pub(adj))
