"""Retention rules and retention conflicts."""
from flask import Blueprint, request

from db import db, new_id, touch, bump
from errors import err, not_found
from middleware import authenticate, body_json, ALL_ROLES
from response import success_object, success_list, paginate
from serializers import rule_view, conflict_view
from services.core import (
    windows_overlap, recompute_records_for_pair)
from utils import (check_str, check_int, check_enum, check_datetime)

bp = Blueprint("rules", __name__)

TRIGGER_BASES = {"EVENT_DATE", "FISCAL_YEAR_END"}
STRATEGIES = {"APPLY_LONGEST", "APPLY_SHORTEST"}


def _overlapping_active_rules(rule, exclude_ids=()):
    """ACTIVE rules of the same (class, jurisdiction) whose half-open windows
    overlap the given rule's window."""
    out = []
    for r in db.retention_rules.values():
        if r["id"] == rule["id"] or r["id"] in exclude_ids:
            continue
        if r["status"] != "ACTIVE":
            continue
        if (r["record_class_id"] != rule["record_class_id"]
                or r["jurisdiction_id"] != rule["jurisdiction_id"]):
            continue
        if windows_overlap(rule["effective_from"], rule["effective_to"],
                           r["effective_from"], r["effective_to"]):
            out.append(r)
    return out


def _select_incumbent(overlapping):
    """Earliest created_at; tie-break rule_code ASC."""
    return sorted(overlapping,
                  key=lambda r: (r["created_at"], r["rule_code"]))[0]


def _spawn_conflict(challenger, incumbent):
    c = {
        "id": new_id(),
        "program_id": challenger["program_id"],
        "record_class_id": challenger["record_class_id"],
        "jurisdiction_id": challenger["jurisdiction_id"],
        "incumbent_rule_id": incumbent["id"],
        "challenger_rule_id": challenger["id"],
        "governing_rule_id": None,
        "resolution_strategy": None,
        "resolution_justification": None,
        "resolved_by_user_id": None,
        "status": "OPEN",
    }
    touch(c)
    db.retention_conflicts[c["id"]] = c
    return c


def _check_rule_body(body):
    rule_code = check_str(body, "rule_code")
    retention_months = check_int(body, "retention_months", minimum=0,
                                 min_exclusive=True)
    trigger_basis = check_enum(body, "trigger_basis", TRIGGER_BASES)
    effective_from = check_datetime(body, "effective_from")
    effective_to = check_datetime(body, "effective_to", required=False)
    if effective_to is not None and not effective_to > effective_from:
        raise err("ERR_INVALID_DATE_RANGE", 400,
                  "effective_to must be strictly after effective_from")
    return rule_code, retention_months, trigger_basis, effective_from, effective_to


def _rule_code_in_use(program_id, rule_code):
    return any(r["program_id"] == program_id and r["rule_code"] == rule_code
               for r in db.retention_rules.values())


# ---------------------------------------------------------------------------
# Retention Rules
# ---------------------------------------------------------------------------
@bp.route("/ig/retention-rules", methods=["POST"])
def create_rule():
    authenticate(["RecordsManager"])
    body = body_json()
    program_id = check_str(body, "program_id")
    record_class_id = check_str(body, "record_class_id")
    jurisdiction_id = check_str(body, "jurisdiction_id")
    rule_code, retention_months, trigger_basis, effective_from, effective_to = \
        _check_rule_body(body)
    # Body-referenced entity existence
    program = db.programs.get(program_id)
    if program is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    rclass = db.record_classes.get(record_class_id)
    if rclass is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced record class does not exist")
    jur = db.jurisdictions.get(jurisdiction_id)
    if jur is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced jurisdiction does not exist")
    # Same-program integrity
    if rclass["program_id"] != program_id or jur["program_id"] != program_id:
        raise err("ERR_CROSS_PROGRAM_REFERENCE", 409,
                  "Referenced entity belongs to a different program")
    # Uniqueness
    if _rule_code_in_use(program_id, rule_code):
        raise err("ERR_DUPLICATE_CODE", 409,
                  "Rule code already exists in the program")
    r = {
        "id": new_id(),
        "program_id": program_id,
        "record_class_id": record_class_id,
        "jurisdiction_id": jurisdiction_id,
        "rule_code": rule_code,
        "retention_months": retention_months,
        "trigger_basis": trigger_basis,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "supersedes_rule_id": None,
        "superseded_by_id": None,
        "status": "DRAFT",
    }
    touch(r)
    db.retention_rules[r["id"]] = r
    return success_object(rule_view(r), 201)


@bp.route("/ig/retention-rules/<ruleId>/supersede", methods=["POST"])
def supersede_rule(ruleId):
    authenticate(["RecordsManager"])
    target = db.retention_rules.get(ruleId)
    if target is None:
        not_found("Retention rule not found")
    body = body_json()
    rule_code, retention_months, trigger_basis, effective_from, effective_to = \
        _check_rule_body(body)
    expected = body.get("expected_retention_rule_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", 400,
                  "Missing required field: expected_retention_rule_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", 400,
                  "expected_retention_rule_version must be an integer")
    # OCC before domain state checks
    if expected != target["version"]:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_retention_rule_version does not match the "
                  "target rule's current version")
    if target["status"] != "ACTIVE":
        raise err("ERR_SUPERSEDE_TARGET_NOT_ACTIVE", 409,
                  "The supersede target rule is not currently ACTIVE")
    if _rule_code_in_use(target["program_id"], rule_code):
        raise err("ERR_DUPLICATE_CODE", 409,
                  "Rule code already exists in the program")
    r = {
        "id": new_id(),
        "program_id": target["program_id"],
        "record_class_id": target["record_class_id"],
        "jurisdiction_id": target["jurisdiction_id"],
        "rule_code": rule_code,
        "retention_months": retention_months,
        "trigger_basis": trigger_basis,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "supersedes_rule_id": target["id"],
        "superseded_by_id": None,
        "status": "DRAFT",
    }
    touch(r)
    db.retention_rules[r["id"]] = r
    # Claiming the succession head advances the target's version.
    bump(target)
    return success_object(rule_view(r), 201)


@bp.route("/ig/retention-rules", methods=["GET"])
def list_rules():
    authenticate(ALL_ROLES)
    items = list(db.retention_rules.values())
    a = request.args
    for f in ("program_id", "record_class_id", "jurisdiction_id", "status",
              "supersedes_rule_id", "superseded_by_id"):
        v = a.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([rule_view(r) for r in window], limit, offset, total)


@bp.route("/ig/retention-rules/<ruleId>", methods=["GET"])
def get_rule(ruleId):
    authenticate(ALL_ROLES)
    r = db.retention_rules.get(ruleId)
    if r is None:
        not_found("Retention rule not found")
    return success_object(rule_view(r))


@bp.route("/ig/retention-rules/<ruleId>/activate", methods=["POST"])
def activate_rule(ruleId):
    authenticate(["RecordsManager"])
    rule = db.retention_rules.get(ruleId)
    if rule is None:
        not_found("Retention rule not found")
    if rule["status"] != "DRAFT":
        raise err("ERR_RULE_INVALID_STATE", 409,
                  "Only a DRAFT rule can be activated")
    target = None
    if rule["supersedes_rule_id"]:
        target = db.retention_rules.get(rule["supersedes_rule_id"])
        if target is None or target["status"] != "ACTIVE":
            raise err("ERR_SUPERSEDE_TARGET_NOT_ACTIVE", 409,
                      "The supersede target rule is not currently ACTIVE")
    # Succession: supersede the declared target.
    if target is not None:
        target["status"] = "SUPERSEDED"
        target["superseded_by_id"] = rule["id"]
        bump(target)
        remaining = _overlapping_active_rules(rule, exclude_ids={target["id"]})
    else:
        remaining = _overlapping_active_rules(rule)
    if remaining:
        rule["status"] = "PENDING_CONFLICT"
        bump(rule)
        _spawn_conflict(rule, _select_incumbent(remaining))
    else:
        rule["status"] = "ACTIVE"
        bump(rule)
    recompute_records_for_pair(rule["record_class_id"], rule["jurisdiction_id"])
    return success_object(rule_view(rule))


@bp.route("/ig/retention-rules/<ruleId>/withdraw", methods=["POST"])
def withdraw_rule(ruleId):
    authenticate(["RecordsManager"])
    rule = db.retention_rules.get(ruleId)
    if rule is None:
        not_found("Retention rule not found")
    if rule["status"] != "PENDING_CONFLICT":
        raise err("ERR_RULE_INVALID_STATE", 409,
                  "Only a PENDING_CONFLICT rule can be withdrawn")
    rule["status"] = "DRAFT"
    bump(rule)
    for c in db.retention_conflicts.values():
        if c["challenger_rule_id"] == rule["id"] and c["status"] == "OPEN":
            c["status"] = "WITHDRAWN"
            bump(c)
    recompute_records_for_pair(rule["record_class_id"], rule["jurisdiction_id"])
    return success_object(rule_view(rule))


@bp.route("/ig/retention-rules/<ruleId>/retire", methods=["POST"])
def retire_rule(ruleId):
    authenticate(["RecordsManager"])
    rule = db.retention_rules.get(ruleId)
    if rule is None:
        not_found("Retention rule not found")
    if rule["status"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_RULE_INVALID_STATE", 409,
                  "Only a DRAFT or ACTIVE rule can be retired")
    if rule["status"] == "ACTIVE":
        governed = [r for r in db.records.values()
                    if r["status"] == "ACTIVE"
                    and r.get("governing_rule_id") == rule["id"]]
        if governed:
            raise err("ERR_RULE_HAS_GOVERNED_RECORDS", 409,
                      "An ACTIVE rule governing live records cannot be retired")
    rule["status"] = "RETIRED"
    bump(rule)
    return success_object(rule_view(rule))


# ---------------------------------------------------------------------------
# Retention Conflicts
# ---------------------------------------------------------------------------
@bp.route("/ig/retention-conflicts", methods=["GET"])
def list_conflicts():
    authenticate(ALL_ROLES)
    items = list(db.retention_conflicts.values())
    a = request.args
    for f in ("program_id", "status", "record_class_id", "jurisdiction_id",
              "incumbent_rule_id", "challenger_rule_id", "governing_rule_id"):
        v = a.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([conflict_view(c) for c in window], limit, offset, total)


@bp.route("/ig/retention-conflicts/<conflictId>", methods=["GET"])
def get_conflict(conflictId):
    authenticate(ALL_ROLES)
    c = db.retention_conflicts.get(conflictId)
    if c is None:
        not_found("Retention conflict not found")
    return success_object(conflict_view(c))


@bp.route("/ig/retention-conflicts/<conflictId>/resolve", methods=["POST"])
def resolve_conflict(conflictId):
    uid, role = authenticate(["RecordsManager", "LegalCounsel"])
    conflict = db.retention_conflicts.get(conflictId)
    if conflict is None:
        not_found("Retention conflict not found")
    body = body_json()
    strategy = check_enum(body, "strategy", STRATEGIES)
    justification = body.get("justification")
    if justification is not None and not isinstance(justification, str):
        raise err("ERR_INVALID_REQUEST", 400, "justification must be a string")
    # Minimum-length text (APPLY_SHORTEST requires justification >= 20).
    if strategy == "APPLY_SHORTEST" and (justification is None
                                         or len(justification) < 20):
        raise err("ERR_JUSTIFICATION_TOO_SHORT", 400,
                  "APPLY_SHORTEST resolution requires a justification of at "
                  "least 20 characters")
    # Domain state
    if conflict["status"] != "OPEN":
        raise err("ERR_CONFLICT_NOT_OPEN", 409,
                  "Only an OPEN conflict can be resolved")
    # APPLY_SHORTEST regulatory downgrade requires LegalCounsel.
    if strategy == "APPLY_SHORTEST" and role != "LegalCounsel":
        raise err("ERR_SHORTEST_STRATEGY_REQUIRES_COUNSEL", 403,
                  "APPLY_SHORTEST resolution requires the LegalCounsel role")
    incumbent = db.retention_rules[conflict["incumbent_rule_id"]]
    challenger = db.retention_rules[conflict["challenger_rule_id"]]
    # Winner: max/min retention_months; tie-break created_at DESC (newer
    # wins), then rule_code ASC.
    pair = [incumbent, challenger]
    if strategy == "APPLY_LONGEST":
        pair.sort(key=lambda r: (-r["retention_months"],
                                 -r["created_at"].timestamp(),
                                 r["rule_code"]))
    else:
        pair.sort(key=lambda r: (r["retention_months"],
                                 -r["created_at"].timestamp(),
                                 r["rule_code"]))
    winner, loser = pair[0], pair[1]
    loser["status"] = "SUPERSEDED"
    loser["superseded_by_id"] = winner["id"]
    bump(loser)
    if winner["id"] == challenger["id"]:
        # If further overlapping ACTIVE rules remain, the challenger stays
        # PENDING_CONFLICT and a fresh OPEN conflict is spawned against the
        # next overlapping rule by the same selector.
        remaining = _overlapping_active_rules(
            challenger, exclude_ids={incumbent["id"], challenger["id"]})
        if remaining:
            _spawn_conflict(challenger, _select_incumbent(remaining))
        else:
            challenger["status"] = "ACTIVE"
            bump(challenger)
    conflict["status"] = "RESOLVED"
    conflict["governing_rule_id"] = winner["id"]
    conflict["resolution_strategy"] = strategy
    conflict["resolution_justification"] = justification
    conflict["resolved_by_user_id"] = uid
    bump(conflict)
    recompute_records_for_pair(conflict["record_class_id"],
                               conflict["jurisdiction_id"])
    return success_object(conflict_view(conflict))
