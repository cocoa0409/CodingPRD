"""Variance investigations: root cause, segregated approval, attribution (PRD 3.6)."""

from flask import Blueprint

import calc
from db import db
from errors import ApiError
from middleware import acting_user, require_read, require_roles, segregation_check
from response import ok, ok_list, paginate, read_pagination
from validate import S, body_json, filter_enum, filter_str, lookup, parse_body

bp = Blueprint("investigations", __name__)
PREFIX = "/inventory-integrity"

INVESTIGATION_STATUSES = ("OPEN", "IN_REVIEW", "CAUSE_PROPOSED", "CAUSE_APPROVED",
                          "CLOSED", "WAIVED")
ROOT_CAUSES = ("THEFT", "DAMAGE", "PROCESS_ERROR", "VENDOR_SHORTAGE")

NOTE_SPECS = [S("note", "str", required=False, max_len=2000)]


def _bad_state(message):
    raise ApiError("ERR_INVESTIGATION_INVALID_STATE", message)


@bp.get(PREFIX + "/variance-investigations/<investigation_id>")
def get_investigation(investigation_id):
    require_read()
    return ok(lookup("investigations", investigation_id))


@bp.get(PREFIX + "/variance-investigations")
def list_investigations():
    require_read()
    status = filter_enum("status", INVESTIGATION_STATUSES)
    approved_root_cause = filter_enum("approved_root_cause", ROOT_CAUSES)
    predicates = []
    for param in ("count_line_id", "store_id", "shrink_period_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    if status is not None:
        predicates.append(("status", status))
    if approved_root_cause is not None:
        predicates.append(("approved_root_cause", approved_root_cause))
    matched = [r for r in db.investigations.values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post(PREFIX + "/variance-investigations/<investigation_id>/assign")
def assign_investigation(investigation_id):
    require_roles("InventoryAnalyst", "InventorySupervisor")
    investigation = lookup("investigations", investigation_id)
    data = parse_body(body_json(), [S("assigned_investigator_id", "str", min_len=1,
                                      max_len=200)])
    if investigation["status"] != "OPEN":
        _bad_state("only an OPEN investigation may be assigned")
    investigation["assigned_investigator_id"] = data["assigned_investigator_id"]
    investigation["status"] = "IN_REVIEW"
    calc.touch(investigation)
    return ok(investigation)


PROPOSE_SPECS = [
    S("evidence_note", "str", min_len=1, max_len=2000),
    S("expected_investigation_version", "int"),
    S("proposed_root_cause", "enum", allowed=ROOT_CAUSES),
]


@bp.post(PREFIX + "/variance-investigations/<investigation_id>/propose-cause")
def propose_cause(investigation_id):
    require_roles("InventoryAnalyst", "InventorySupervisor")
    investigation = lookup("investigations", investigation_id)
    data = parse_body(body_json(), PROPOSE_SPECS)
    if data["expected_investigation_version"] != investigation["version"]:
        raise ApiError("ERR_STALE_INVESTIGATION_VERSION",
                       "expected_investigation_version does not match the stored version")
    if investigation["status"] not in ("IN_REVIEW", "CAUSE_PROPOSED"):
        _bad_state("a cause may only be proposed from IN_REVIEW or CAUSE_PROPOSED")
    investigation["proposed_root_cause"] = data["proposed_root_cause"]
    investigation["evidence_note"] = data["evidence_note"]
    investigation["proposed_by_user_id"] = acting_user()
    investigation["proposal_round"] += 1
    investigation["status"] = "CAUSE_PROPOSED"
    calc.touch(investigation)
    return ok(investigation)


@bp.post(PREFIX + "/variance-investigations/<investigation_id>/return")
def return_proposal(investigation_id):
    require_roles("InventorySupervisor", "ShrinkController")
    investigation = lookup("investigations", investigation_id)
    parse_body(body_json(), NOTE_SPECS)
    if investigation["status"] != "CAUSE_PROPOSED":
        _bad_state("only a CAUSE_PROPOSED investigation may be returned")
    segregation_check(investigation["proposed_by_user_id"])
    investigation["proposed_root_cause"] = None
    investigation["proposed_by_user_id"] = None
    investigation["status"] = "IN_REVIEW"
    calc.touch(investigation)
    return ok(investigation)


def _covering_period(investigation):
    period_id = investigation.get("shrink_period_id")
    if not period_id:
        return None
    return db.shrink_periods.get(period_id)


@bp.post(PREFIX + "/variance-investigations/<investigation_id>/approve-cause")
def approve_cause(investigation_id):
    require_roles("InventorySupervisor", "ShrinkController")
    investigation = lookup("investigations", investigation_id)
    parse_body(body_json(), [])
    if investigation["status"] != "CAUSE_PROPOSED":
        _bad_state("only a CAUSE_PROPOSED investigation may have its cause approved")
    period = _covering_period(investigation)
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_SHRINK_PERIOD_INVALID_STATE",
                       "the covering shrink period is not OPEN")
    segregation_check(investigation["proposed_by_user_id"])
    investigation["approved_root_cause"] = investigation["proposed_root_cause"]
    investigation["approved_by_user_id"] = acting_user()
    investigation["status"] = "CAUSE_APPROVED"
    calc.touch(investigation)
    return ok(investigation)


@bp.post(PREFIX + "/variance-investigations/<investigation_id>/close")
def close_investigation(investigation_id):
    require_roles("InventorySupervisor", "ShrinkController")
    investigation = lookup("investigations", investigation_id)
    parse_body(body_json(), [])
    if investigation["status"] != "CAUSE_APPROVED":
        _bad_state("only a CAUSE_APPROVED investigation may be closed")
    period = _covering_period(investigation)
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_SHRINK_PERIOD_INVALID_STATE",
                       "the covering shrink period is not OPEN")
    # hop one
    investigation["status"] = "CLOSED"
    calc.touch(investigation)
    # hop two — attribution moves out of unresolved into the named bucket
    calc.recompute_period(period)
    # hop three / four — vendor shortage reaches the vendor and its open batches
    if investigation.get("approved_root_cause") == "VENDOR_SHORTAGE":
        item = db.items.get(investigation.get("_item_id"))
        if item is not None:
            vendor = db.vendors.get(item["primary_vendor_id"])
            if vendor is not None:
                vendor["shortage_event_count"] += 1
                calc.apply_vendor_score(vendor, -calc.VENDOR_SHORTAGE_PENALTY_BPS)
                calc.touch(vendor)
                calc.refreeze_vendor_batches(vendor["id"])
    position_id = investigation.get("_stock_position_id")
    if position_id:
        calc.settle([position_id])
    return ok(investigation)
