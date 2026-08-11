"""FaultAllocation endpoints: create (OCC + supersede), propose, contest, revise, finalize."""

from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db
from errors import (err_authority_cap, err_contest_window, err_invalid_request,
                    err_invalid_state, err_no_evidence, err_not_found,
                    err_ownership, err_segregation, err_shares_sum,
                    err_stale_version)
from middleware import require_roles
from serializers import allocation_out
from services.core import (DEFAULT_SHARES, POINTS, allocate_shares,
                           compute_standard_line_total, evaluate_program,
                           recompute_case_totals, recompute_offender_points,
                           touch)
from util import (get_pagination, new_id, paginate, parse_body, require_enum,
                  require_int, require_string, success_envelope)

bp = Blueprint("fault_allocations", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")

PARTY_TYPES = ("EXCAVATOR", "LOCATOR", "FACILITY_OWNER")
ROOT_CAUSES = ("NO_TICKET", "EXPIRED_TICKET", "MISMARK", "LOCATE_LATE", "OWNER_ABANDONED")


def _validate_shares(shares):
    """Validate the shares array structurally; returns normalized list."""
    if not isinstance(shares, list) or len(shares) == 0:
        raise err_invalid_request("shares must be a non-empty array")
    out = []
    for entry in shares:
        if not isinstance(entry, dict):
            raise err_invalid_request("share entry must be an object")
        party_type = entry.get("party_type")
        require_enum(party_type, PARTY_TYPES, "party_type")
        party_id = entry.get("party_id")
        if party_id is not None and not isinstance(party_id, str):
            raise err_invalid_request("party_id must be a string or null")
        share_bp = entry.get("share_bp")
        require_int(share_bp, "share_bp")
        out.append({"party_type": party_type, "party_id": party_id, "share_bp": share_bp})
    total = sum(s["share_bp"] for s in out)
    if total != 10000:
        raise err_shares_sum()
    return out


def _default_shares_for(case, root_cause_code):
    """Rule-default shares; locator party_id is the earliest-created response's locator."""
    locator_id = None
    if case["locate_ticket_id"]:
        responses = [r for r in db.locate_responses.values()
                     if r["locate_ticket_id"] == case["locate_ticket_id"]]
        if responses:
            responses.sort(key=lambda r: (r["created_at"], r["_seq"]))
            locator_id = responses[0]["locator_id"]
    shares = []
    for party_type, bp in DEFAULT_SHARES[root_cause_code]:
        if party_type == "EXCAVATOR":
            pid = case["excavator_id"]
        elif party_type == "LOCATOR":
            pid = locator_id
        else:
            pid = None
        shares.append({"party_type": party_type, "party_id": pid, "share_bp": bp})
    return shares


def _check_share_party_ids_exist(shares):
    for s in shares:
        if s["party_type"] == "EXCAVATOR" and s["party_id"] is not None:
            if s["party_id"] not in db.excavators:
                raise err_not_found("share party_id (excavator) not found")
        if s["party_type"] == "LOCATOR" and s["party_id"] is not None:
            if s["party_id"] not in db.locators:
                raise err_not_found("share party_id (locator) not found")


@bp.route("/damage-recovery/fault-allocations", methods=["POST"])
def create_allocation():
    require_roles("DamageInvestigator")
    body = parse_body(required_fields=["damage_case_id", "root_cause_code", "expected_damage_case_version"])
    case = db.damage_cases.get(body["damage_case_id"])
    if case is None:
        raise err_not_found("damage case not found")
    root_cause = require_enum(body["root_cause_code"], ROOT_CAUSES, "root_cause_code")
    expected = body["expected_damage_case_version"]
    require_int(expected, "expected_damage_case_version")
    shares_supplied = body.get("shares")
    if shares_supplied is not None:
        shares = _validate_shares(shares_supplied)
        basis = "ADJUDICATED"
        _check_share_party_ids_exist(shares)
    else:
        shares = _default_shares_for(case, root_cause)
        basis = "RULE_DEFAULT"
    # state check
    if case["investigation_status"] != "INVESTIGATING":
        raise err_invalid_state("case is not INVESTIGATING")
    # OCC
    if expected != case["version"]:
        raise err_stale_version()

    # supersede prior non-FINAL allocation of this case
    prior = None
    for a in db.fault_allocations.values():
        if a["damage_case_id"] == case["id"] and a["status"] != "FINAL" and a["status"] != "SUPERSEDED":
            prior = a
            break
    now = clock.get_current_utc()
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        prior["updated_at"] = now
        prior["version"] += 1

    aid = new_id()
    alloc = {
        "id": aid,
        "damage_case_id": case["id"],
        "supersedes_allocation_id": prior["id"] if prior else None,
        "root_cause_code": root_cause,
        "basis": basis,
        "shares": shares,
        "status": "DRAFT",
        "revision_no": 0,
        "proposed_at": None,
        "contest_deadline_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.fault_allocations[aid] = alloc
    touch(case)
    return success_envelope(allocation_out(alloc), "object", 201)


@bp.route("/damage-recovery/fault-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    require_roles(*ALL_ROLES)
    a = db.fault_allocations.get(aid)
    if a is None:
        raise err_not_found("fault allocation not found")
    return success_envelope(allocation_out(a), "object", 200)


@bp.route("/damage-recovery/fault-allocations", methods=["GET"])
def list_allocations():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.fault_allocations.values())
    case_id = request.args.get("damage_case_id")
    supersedes = request.args.get("supersedes_allocation_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [a for a in items if a["damage_case_id"] == case_id]
    if supersedes is not None:
        items = [a for a in items if a["supersedes_allocation_id"] == supersedes]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([allocation_out(a) for a in page], "array", 200, meta)


@bp.route("/damage-recovery/fault-allocations/<aid>/propose", methods=["POST"])
def propose_allocation(aid):
    require_roles("DamageInvestigator")
    a = db.fault_allocations.get(aid)
    if a is None:
        raise err_not_found("fault allocation not found")
    case = db.damage_cases.get(a["damage_case_id"])
    if a["status"] != "DRAFT":
        raise err_invalid_state("allocation is not DRAFT")
    if case is None or case["investigation_status"] != "INVESTIGATING":
        raise err_invalid_state("case is not INVESTIGATING")
    now = clock.get_current_utc()
    a["status"] = "PROPOSED"
    a["proposed_at"] = now
    a["contest_deadline_at"] = now + timedelta(days=10)
    a["updated_at"] = now
    a["version"] += 1
    case["investigation_status"] = "FAULT_PROPOSED"
    touch(case)
    return success_envelope(allocation_out(a), "object", 200)


@bp.route("/damage-recovery/fault-allocations/<aid>/contest", methods=["POST"])
def contest_allocation(aid):
    user_id, role = require_roles("Excavator", "Locator", "RecoveryManager")
    a = db.fault_allocations.get(aid)
    if a is None:
        raise err_not_found("fault allocation not found")
    # state check before temporal check (per PRD)
    if a["status"] != "PROPOSED":
        raise err_invalid_state("allocation is not PROPOSED")
    now = clock.get_current_utc()
    if a["contest_deadline_at"] is not None and now > a["contest_deadline_at"]:
        raise err_contest_window()
    if role != "RecoveryManager":
        party_ids = [s["party_id"] for s in a["shares"]]
        if user_id not in party_ids:
            raise err_ownership("caller is not a named party on this allocation")
    a["status"] = "CONTESTED"
    a["updated_at"] = now
    a["version"] += 1
    return success_envelope(allocation_out(a), "object", 200)


@bp.route("/damage-recovery/fault-allocations/<aid>/revise", methods=["POST"])
def revise_allocation(aid):
    require_roles("DamageInvestigator")
    a = db.fault_allocations.get(aid)
    if a is None:
        raise err_not_found("fault allocation not found")
    if a["status"] != "CONTESTED":
        raise err_invalid_state("allocation is not CONTESTED")
    body = parse_body()
    case = db.damage_cases.get(a["damage_case_id"])
    if "root_cause_code" in body and body["root_cause_code"] is not None:
        a["root_cause_code"] = require_enum(body["root_cause_code"], ROOT_CAUSES, "root_cause_code")
    if "shares" in body and body["shares"] is not None:
        shares = _validate_shares(body["shares"])
        _check_share_party_ids_exist(shares)
        a["shares"] = shares
        a["basis"] = "ADJUDICATED"
    a["status"] = "DRAFT"
    a["revision_no"] += 1
    a["proposed_at"] = None
    a["contest_deadline_at"] = None
    a["updated_at"] = clock.get_current_utc()
    a["version"] += 1
    if case is not None:
        case["investigation_status"] = "INVESTIGATING"
        touch(case)
    return success_envelope(allocation_out(a), "object", 200)


@bp.route("/damage-recovery/fault-allocations/<aid>/finalize", methods=["POST"])
def finalize_allocation(aid):
    user_id, _ = require_roles("RecoveryManager")
    a = db.fault_allocations.get(aid)
    if a is None:
        raise err_not_found("fault allocation not found")
    if a["status"] != "PROPOSED":
        raise err_invalid_state("allocation is not PROPOSED")
    case = db.damage_cases.get(a["damage_case_id"])
    if case is None:
        raise err_not_found("damage case not found")
    body = parse_body()
    override = body.get("override_authority_cap", False)
    if not isinstance(override, bool):
        raise err_invalid_request("override_authority_cap must be a boolean")
    if user_id == case["investigator_user_id"]:
        raise err_segregation()
    if case["evidence_count"] < 1:
        raise err_no_evidence()
    from services.core import INVOICE_AUTHORITY_CAP_CENTS
    if case["subtotal_cents"] > INVOICE_AUTHORITY_CAP_CENTS and not override:
        raise err_authority_cap()

    now = clock.get_current_utc()

    # standard basis: reprice lines at standard rates, then allocate by shares
    lines = [c for c in db.cost_line_items.values() if c["damage_case_id"] == case["id"]]
    standard_subtotal = 0
    for line in lines:
        standard_subtotal += compute_standard_line_total(line["category"], line["quantity"], case["severity"])

    shares = a["shares"]
    actual_amounts = allocate_shares(case["subtotal_cents"], shares)
    standard_amounts = allocate_shares(standard_subtotal, shares)

    a["status"] = "FINAL"
    a["updated_at"] = now
    a["version"] += 1

    for share, amt, std_amt in zip(shares, actual_amounts, standard_amounts):
        if share["share_bp"] <= 0:
            continue
        debtor_type = share["party_type"]
        debtor_id = "FACILITY_OWNER" if debtor_type == "FACILITY_OWNER" else share["party_id"]
        iid = new_id()
        inv = {
            "id": iid,
            "damage_case_id": case["id"],
            "fault_allocation_id": a["id"],
            "debtor_type": debtor_type,
            "debtor_id": debtor_id,
            "status": "DRAFT",
            "invoiced_cents": amt,
            "standard_basis_cents": std_amt,
            "amount_paid_cents": 0,
            "amount_due_cents": amt,
            "issued_at": None,
            "due_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_insert_seq(),
        }
        db.claim_invoices[iid] = inv

    case["investigation_status"] = "FAULT_FINAL"
    case["recovery_status"] = "INVOICED"
    recompute_case_totals(case)
    touch(case)

    # violation cascade: excavator share >= 5000 bp
    exc_share = next((s for s in shares if s["party_type"] == "EXCAVATOR"), None)
    if exc_share is not None and exc_share["share_bp"] >= 5000:
        excavator = db.excavators.get(case["excavator_id"])
        if excavator is not None:
            vid = new_id()
            points = POINTS[case["severity"]]
            violation = {
                "id": vid,
                "excavator_id": excavator["id"],
                "damage_case_id": case["id"],
                "points": points,
                "effective_points": points,
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "_seq": db.next_insert_seq(),
            }
            db.violation_records[vid] = violation
            evaluate_program(excavator)

    return success_envelope(allocation_out(a), "object", 200)
