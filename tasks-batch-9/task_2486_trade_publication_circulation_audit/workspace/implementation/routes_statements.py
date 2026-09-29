"""Circulation statements: drafting, recompute, certification, settlement."""
from flask import Blueprint

import calc
import validation as V
from auth import (OPERATOR_ROLES, ROLE_CIRCULATION_MANAGER,
                  ROLE_PUBLISHER_EXECUTIVE, current_user, endpoint)
from envelope import created, ok, ok_array, paginate
from errors import ApiError
from lookups import get_publication, get_statement
from store import (base_record, collection_sorted, db, now, serialize, touch)

statements_bp = Blueprint("statements", __name__)

STATEMENT_TERMINAL = ("AUDIT_CLEARED", "SUPERSEDED")
OVERLAP_CANDIDATE_STATUSES = ("DRAFT", "FILED", "UNDER_AUDIT", "FINDINGS_OPEN",
                              "AUDIT_CLEARED", "RESTATEMENT_REQUIRED")


def _require_draft(stmt):
    if stmt["status"] in STATEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This statement has already reached %s." % stmt["status"])
    if stmt["status"] != "DRAFT":
        raise ApiError("ERR_STATEMENT_NOT_DRAFT",
                       "This statement is %s, not DRAFT." % stmt["status"])


# --------------------------------------------------------------------------
# POST /circulation/statements
# --------------------------------------------------------------------------
@statements_bp.route("/circulation/statements", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def create_statement():
    payload = V.body()
    pub = get_publication(payload.get("publication_id"))
    restates = None
    if isinstance(payload, dict) and payload.get("restates_statement_id") is not None:
        restates = get_statement(payload.get("restates_statement_id"))

    fields = V.parse(payload, [
        V.f_id("publication_id"),
        V.f_id("restates_statement_id", required=False, default=None),
        V.f_dt("period_start"),
        V.f_dt("period_end"),
        V.f_enum("basis", V.STATEMENT_BASES, required=False, default="AS_OF_PERIOD_END"),
        V.f_int("expected_publication_version", minimum=0),
    ])

    if fields["expected_publication_version"] != pub["version"]:
        raise ApiError("ERR_STALE_PUBLICATION_VERSION",
                       "expected_publication_version %s does not match the publication's "
                       "current version %s." % (fields["expected_publication_version"],
                                                pub["version"]))

    if restates is not None:
        if restates["publication_id"] != pub["id"] \
                or restates["status"] != "RESTATEMENT_REQUIRED":
            raise ApiError("ERR_RESTATEMENT_NOT_REQUIRED",
                           "The restated statement must belong to this publication and "
                           "stand in RESTATEMENT_REQUIRED.")

    if not fields["period_start"] < fields["period_end"]:
        raise ApiError("ERR_INVALID_PERIOD_RANGE",
                       "period_start must be strictly before period_end.")
    if fields["period_end"] > now():
        raise ApiError("ERR_PERIOD_NOT_ELAPSED",
                       "The reporting period has not closed yet.")

    stmt = base_record()
    stmt.update({
        "publication_id": pub["id"],
        "restates_statement_id": restates["id"] if restates else None,
        "period_start": fields["period_start"],
        "period_end": fields["period_end"],
        "statement_type": "PUBLISHER_STATEMENT",
        "basis": fields["basis"],
        "status": "DRAFT",
        "paid_copies": 0,
        "qualified_non_paid_copies": 0,
        "controlled_copies_included": 0,
        "controlled_copies_excess": 0,
        "total_qualified_copies": 0,
        "digital_reach_verified": 0,
        "undeliverable_pct_at_close": pub["undeliverable_pct"],
        "declared_total_copies": 0,
        "discrepancy_copies": None,
        "discrepancy_pct": None,
        "breakdown_stale": False,
        "prepared_by_user_id": current_user(),
        "certified_by_user_id": None,
        "filed_at": None,
        "guarantees_settled_at": None,
        "_samples": [],
    })
    db.statements[stmt["id"]] = stmt
    calc.compute_statement_breakdown(stmt, pub)
    touch(pub)
    return created(serialize(stmt))


@statements_bp.route("/circulation/statements/<stmt_id>", methods=["GET"])
@endpoint(*OPERATOR_ROLES)
def read_statement(stmt_id):
    return ok(serialize(get_statement(stmt_id)))


@statements_bp.route("/circulation/statements", methods=["GET"])
@endpoint(*OPERATOR_ROLES)
def list_statements():
    publication_id = V.filter_str("publication_id")
    status = V.filter_enum("status", V.STATEMENT_STATUSES)
    basis = V.filter_enum("basis", V.STATEMENT_BASES)
    restates_statement_id = V.filter_str("restates_statement_id")
    rows = list(db.statements.values())
    if publication_id:
        rows = [s for s in rows if s["publication_id"] == publication_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    if basis:
        rows = [s for s in rows if s["basis"] == basis]
    if restates_statement_id:
        rows = [s for s in rows if s["restates_statement_id"] == restates_statement_id]
    return paginate(collection_sorted(rows))


# --------------------------------------------------------------------------
# POST /circulation/statements/{id}/recompute
# --------------------------------------------------------------------------
@statements_bp.route("/circulation/statements/<stmt_id>/recompute", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def recompute_statement(stmt_id):
    stmt = get_statement(stmt_id)
    payload = V.body()
    fields = V.parse(payload, [
        V.f_enum("basis", V.STATEMENT_BASES, required=False, default=None),
    ])
    _require_draft(stmt)

    if fields["basis"] is not None:
        stmt["basis"] = fields["basis"]
    pub = db.publications.get(stmt["publication_id"])
    calc.compute_statement_breakdown(stmt, pub)
    touch(stmt)
    return ok(serialize(stmt))


# --------------------------------------------------------------------------
# POST /circulation/statements/{id}/certify
# --------------------------------------------------------------------------
@statements_bp.route("/circulation/statements/<stmt_id>/certify", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER, ROLE_PUBLISHER_EXECUTIVE)
def certify_statement(stmt_id):
    stmt = get_statement(stmt_id)
    payload = V.body()
    V.parse(payload, [V.f_str("certification_note", required=False, max_len=1000, default=None)])
    _require_draft(stmt)

    pub = db.publications.get(stmt["publication_id"])
    predecessor = None
    if stmt["restates_statement_id"] is not None:
        candidate = db.statements.get(stmt["restates_statement_id"])
        if candidate is not None and candidate["publication_id"] == stmt["publication_id"] \
                and candidate["status"] == "RESTATEMENT_REQUIRED":
            predecessor = candidate

    if current_user() == stmt["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The operator who prepared a statement may not certify it.")
    if pub is not None and pub["audit_posture"] == "FROZEN" and predecessor is None:
        raise ApiError("ERR_PUBLICATION_FROZEN",
                       "The publication is FROZEN; only a sanctioned restatement may be "
                       "certified.")
    if stmt["breakdown_stale"]:
        raise ApiError("ERR_BREAKDOWN_STALE",
                       "The breakdown is stale; recompute the statement first.")

    for other in db.statements.values():
        if other["id"] == stmt["id"]:
            continue
        if other["publication_id"] != stmt["publication_id"]:
            continue
        if other["status"] not in OVERLAP_CANDIDATE_STATUSES:
            continue
        if stmt["restates_statement_id"] is not None \
                and other["id"] == stmt["restates_statement_id"]:
            continue
        if other["period_start"] < stmt["period_end"] \
                and stmt["period_start"] < other["period_end"]:
            raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP",
                           "The reporting period intersects another statement of this "
                           "publication.")

    at = now()
    stmt["status"] = "FILED"
    stmt["filed_at"] = at
    stmt["certified_by_user_id"] = current_user()
    stmt["declared_total_copies"] = stmt["total_qualified_copies"]
    touch(stmt)

    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        touch(predecessor)
    if pub is not None:
        before, after, _ = calc.recompute_publication(pub)
        touch(pub)
        if predecessor is not None and before == "FROZEN" and after != "FROZEN":
            for contract in collection_sorted(calc.contracts_of(pub["id"])):
                if contract["guarantee_status"] == "SUSPENDED_PENDING_RESTATEMENT":
                    contract["guarantee_status"] = "ACTIVE"
                    touch(contract)
    return ok(serialize(stmt))


# --------------------------------------------------------------------------
# POST /circulation/statements/{id}/settle-guarantees
# --------------------------------------------------------------------------
@statements_bp.route("/circulation/statements/<stmt_id>/settle-guarantees", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def settle_guarantees(stmt_id):
    stmt = get_statement(stmt_id)
    payload = V.body()
    V.parse(payload, [V.f_str("settlement_note", required=False, max_len=1000, default=None)])

    if stmt["status"] in STATEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "This statement has already reached %s." % stmt["status"])
    if stmt["status"] == "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Guarantees are settled against a certified statement.")

    planned = []
    for contract in collection_sorted(calc.contracts_of(stmt["publication_id"])):
        if contract["guarantee_status"] != "ACTIVE":
            continue
        figures = calc.shortfall_makegood(contract, stmt["total_qualified_copies"])
        if figures is None:
            continue
        if figures["credit_cents"] > contract["makegood_credit_available_cents"]:
            raise ApiError("ERR_MAKEGOOD_POOL_EXCEEDED",
                           "The computed credit of %s cents exceeds the contract's "
                           "available pool of %s cents."
                           % (figures["credit_cents"],
                              contract["makegood_credit_available_cents"]))
        planned.append((contract, figures))

    if not planned:
        raise ApiError("ERR_NO_SHORTFALL_TO_SETTLE",
                       "No active contract of this publication is short of its "
                       "guaranteed rate base beyond its tolerance.")

    obligations = []
    for contract, figures in planned:
        obligation = base_record()
        obligation.update({
            "contract_id": contract["id"],
            "statement_id": stmt["id"],
            "shortfall_copies": figures["shortfall_copies"],
            "shortfall_pct": figures["shortfall_pct"],
            "tier_factor": figures["tier_factor"],
            "per_insertion_credit_cents": figures["per_insertion_credit_cents"],
            "credit_cents": figures["credit_cents"],
            "bonus_insertions": figures["bonus_insertions"],
            "status": "PENDING",
            "offered_at": None,
            "accepted_at": None,
            "closed_reason": None,
        })
        db.make_goods[obligation["id"]] = obligation
        calc.recompute_contract_ledger(contract)
        touch(contract)
        obligations.append(obligation)

    stmt["guarantees_settled_at"] = now()
    touch(stmt)
    return ok_array([serialize(o) for o in obligations], 201)
