from flask import Blueprint, request, g

import db
import errors
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup, calc, cascade

bp = Blueprint("cases", __name__)


# --------------------------------------------------------------------------
# Case CRUD
# --------------------------------------------------------------------------
@bp.post("/cases")
@require("Arranger")
def create_case():
    body = validate.get_json()
    funeral_home_id = validate.require_string(body, "funeral_home_id")
    decedent_name = validate.require_string(body, "decedent_name")
    case_mode = validate.require_enum(body, "case_mode", {"AT_NEED", "PRENEED"})
    date_of_death = body.get("date_of_death")

    # case-mode / date-of-death coupling (PRD §3.2): AT_NEED requires it,
    # PRENEED forbids it. -> ERR_INVALID_REQUEST.
    if case_mode == "AT_NEED":
        if date_of_death is None:
            raise errors.invalid_request("AT_NEED case requires date_of_death")
        if not isinstance(date_of_death, str) or date_of_death == "":
            raise errors.invalid_request("date_of_death must be a non-empty ISO 8601 string")
    else:  # PRENEED
        if date_of_death is not None:
            raise errors.invalid_request("PRENEED case must not supply date_of_death")

    lookup.funeral_home(funeral_home_id)

    case = {
        "id": db.new_id(),
        "funeral_home_id": funeral_home_id,
        "decedent_name": decedent_name,
        "case_mode": case_mode,
        "date_of_death": date_of_death if case_mode == "AT_NEED" else None,
        "arrangement_status": "INTAKE",
        "interment_status": "NOT_READY",
        "disclosure_acknowledged": False,
        "disclosure_officer_id": None,
        "statement_total_final_cents": 0,
        "gfs_issued": False,
    }
    db.stamp_create(case)
    db.cases[case["id"]] = case
    return ok_object(serialize.case(case), 201)


@bp.get("/cases/<case_id>")
@require("Admin", "Arranger", "TrustOfficer", "CemeteryClerk", "Registrar")
def get_case(case_id):
    case = lookup.case(case_id)
    return ok_object(serialize.case(case), 200)


@bp.get("/cases")
@require("Admin", "Arranger", "TrustOfficer", "CemeteryClerk", "Registrar")
def list_cases():
    limit, offset = validate.pagination()
    fh = request.args.get("funeral_home_id")
    items = list(db.cases.values())
    if fh is not None:
        items = [c for c in items if c["funeral_home_id"] == fh]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.case(c) for c in window], limit, offset, total)


# --------------------------------------------------------------------------
# Arrangement-axis transitions
# --------------------------------------------------------------------------
@bp.post("/cases/<case_id>/acknowledge-disclosure")
@require("Arranger")
def acknowledge_disclosure(case_id):
    case = lookup.case(case_id)
    if case["arrangement_status"] != "INTAKE":
        raise errors.invalid_state("Disclosure can only be acknowledged from INTAKE")
    case["disclosure_acknowledged"] = True
    case["disclosure_officer_id"] = g.user_id
    case["arrangement_status"] = "DISCLOSED"
    db.touch(case)
    return ok_object(serialize.case(case), 200)


@bp.post("/cases/<case_id>/issue-gfs")
@require("Arranger")
def issue_gfs(case_id):
    case = lookup.case(case_id)
    # priority 7 (disclosure safety) before priority 6 state? Per PRD §2.9 the
    # state check (6) precedes business-safety (7). But the disclosure gate
    # (priority 7) applies specifically to issue-gfs and the difficulty case
    # "disclosure_safety_beats_referential_on_issue_gfs" shows an INTAKE case
    # (state != DISCLOSED) yielding ERR_DISCLOSURE_REQUIRED, so the disclosure
    # gate is evaluated before the DISCLOSED-state check here.
    if not case["disclosure_acknowledged"]:
        raise errors.conflict(errors.ERR_DISCLOSURE_REQUIRED,
                              "FTC disclosure must be acknowledged before issuing the GFS")
    if case["arrangement_status"] != "DISCLOSED":
        raise errors.invalid_state("GFS can only be issued from DISCLOSED")

    # empty-statement guard (priority 11) and contract-required (priority 9).
    # PRD §3.3 lists: zero selected -> ERR_EMPTY_STATEMENT; no contract ->
    # ERR_CONTRACT_REQUIRED. Referential (contract) is priority 9 < empty (11),
    # so contract-required is checked first.
    contract = lookup.contract_for_case(case_id)
    if contract is None:
        raise errors.conflict(errors.ERR_CONTRACT_REQUIRED,
                              "A contract must exist before issuing the GFS")

    selected = [
        l for l in db.statement_lines.values()
        if l["case_id"] == case_id and l["line_status"] == "SELECTED"
    ]
    if len(selected) == 0:
        raise errors.conflict(errors.ERR_EMPTY_STATEMENT,
                              "At least one SELECTED statement line is required")

    # recompute + lock final total
    _prov, final = calc.case_statement_totals(case)
    case["statement_total_final_cents"] = final
    case["gfs_issued"] = True
    case["arrangement_status"] = "ARRANGED"
    db.touch(case)

    # recompute the contract's contract_amount / trust_required (figures are
    # computed lazily at read, but bump the contract version to reflect change).
    db.touch(contract)

    return ok_object(serialize.case(case), 200)


@bp.post("/cases/<case_id>/complete")
@require("Arranger")
def complete_case(case_id):
    case = lookup.case(case_id)
    if case["arrangement_status"] != "ARRANGED":
        raise errors.invalid_state("Case can only be completed from ARRANGED")
    # priority 9 referential gating: interment INTERRED and contract FUNDED.
    if case["interment_status"] != "INTERRED":
        raise errors.conflict(errors.ERR_INTERMENT_INCOMPLETE,
                              "Interment must be complete before completing the case")
    contract = lookup.contract_for_case(case_id)
    if contract is None or contract["status"] != "FUNDED":
        raise errors.conflict(errors.ERR_CONTRACT_NOT_FUNDED,
                              "Contract must be FUNDED before completing the case")

    case["arrangement_status"] = "COMPLETED"
    db.touch(case)
    # auto-settle the contract
    contract["status"] = "SETTLED"
    db.touch(contract)
    return ok_object(serialize.case(case), 200)


@bp.post("/cases/<case_id>/cancel")
@require("Arranger")
def cancel_case(case_id):
    case = lookup.case(case_id)
    if case["arrangement_status"] not in ("INTAKE", "DISCLOSED", "ARRANGED"):
        raise errors.invalid_state("Case cannot be cancelled from its current state")
    cascade.cancel_case(case)
    return ok_object(serialize.case(case), 200)


# --------------------------------------------------------------------------
# StatementLine sub-resource
# --------------------------------------------------------------------------
@bp.post("/cases/<case_id>/statement-lines")
@require("Arranger")
def add_statement_line(case_id):
    case = lookup.case(case_id)
    body = validate.get_json()
    gpl_item_id = validate.require_string(body, "gpl_item_id")
    quantity = validate.optional_int(body, "quantity", default=1, minimum=1)

    item = lookup.gpl_item(gpl_item_id)

    # FTC disclosure gate (priority 7)
    if not case["disclosure_acknowledged"]:
        raise errors.conflict(errors.ERR_DISCLOSURE_REQUIRED,
                              "FTC disclosure must be acknowledged before adding lines")

    non_declinable = bool(item.get("non_declinable"))
    line = {
        "id": db.new_id(),
        "case_id": case_id,
        "gpl_item_id": gpl_item_id,
        "description": item["name"],
        "category": item["category"],
        "taxable": bool(item.get("taxable")),
        "non_declinable": non_declinable,
        "preneed_trustable": bool(item.get("preneed_trustable")),
        "unit_price_cents": item["unit_price_cents"],
        "quantity": quantity,
        "line_status": "SELECTED" if non_declinable else "PROPOSED",
    }
    db.stamp_create(line)
    db.statement_lines[line["id"]] = line
    # provisional total recompute is reflected via the case's version bump
    db.touch(case)
    return ok_object(serialize.statement_line(line), 201)


@bp.get("/cases/<case_id>/statement-lines")
@require("Admin", "Arranger")
def list_case_statement_lines(case_id):
    lookup.case(case_id)
    limit, offset = validate.pagination()
    items = [l for l in db.statement_lines.values() if l["case_id"] == case_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.statement_line(l) for l in window], limit, offset, total)


@bp.post("/cases/<case_id>/statement-lines/<line_id>/select")
@require("Arranger")
def select_statement_line(case_id, line_id):
    case = lookup.case(case_id)
    line = lookup.statement_line(line_id)
    if line["case_id"] != case_id:
        raise errors.not_found("Statement line does not belong to this case")
    # PROPOSED -> SELECTED; from any other state it is an invalid transition.
    if line["line_status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED line can be selected")
    line["line_status"] = "SELECTED"
    db.touch(line)
    db.touch(case)
    return ok_object(serialize.statement_line(line), 200)


@bp.post("/cases/<case_id>/statement-lines/<line_id>/remove")
@require("Arranger")
def remove_statement_line(case_id, line_id):
    case = lookup.case(case_id)
    line = lookup.statement_line(line_id)
    if line["case_id"] != case_id:
        raise errors.not_found("Statement line does not belong to this case")
    if line.get("non_declinable"):
        raise errors.conflict(errors.ERR_NON_DECLINABLE_LINE,
                              "Non-declinable lines cannot be removed")
    if line["line_status"] == "REMOVED":
        raise errors.invalid_state("Line is already REMOVED")
    line["line_status"] = "REMOVED"
    db.touch(line)
    db.touch(case)
    return ok_object(serialize.statement_line(line), 200)
