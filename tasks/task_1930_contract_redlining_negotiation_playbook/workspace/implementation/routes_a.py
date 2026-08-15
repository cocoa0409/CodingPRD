"""Routes: clock, playbooks, clauses, contract types, counterparties, users, intake."""
from flask import Blueprint

from core import (
    db, now, parse_iso, fmt, ok, err, ApiError, authenticate, body, get_or_404,
    require_fields, stamp_new, stamp_audit, touch, pub, paginate, apply_filters,
    new_id, ALL_ROLES,
)
from domain import (
    compute_value_tier, compute_routing_bucket, OVERRIDE_UP, expire_packets,
)

bp = Blueprint("routes_a", __name__)

CLAUSE_CATEGORIES = {"RISK", "COMMERCIAL", "OPERATIONAL", "REGULATORY"}
APPROVER_ROLES = {"LEGAL_COUNSEL", "FINANCE_CONTROLLER", "BUSINESS_OWNER", "CHIEF_COUNSEL"}
SEVERITY_CAPS = {"LOW", "MEDIUM", "HIGH"}
RISK_TIERS = {"LOW", "STANDARD", "HIGH_RISK", "SANCTIONED"}
PRIMARY_ROLES = {
    "CONTRACT_ANALYST", "BUSINESS_OWNER", "LEGAL_COUNSEL",
    "FINANCE_CONTROLLER", "CHIEF_COUNSEL", "SIGNATORY", "OPS_ADMIN",
}
ROUTING_BUCKETS = {"SELF_SERVE", "STANDARD", "ELEVATED", "EXECUTIVE"}


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["OpsAdmin"])
    b = body()
    to = b.get("to_iso8601")
    if to is None:
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 is required.")
    try:
        dt = parse_iso(to)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 is not a valid ISO-8601 timestamp.")
    from core import set_now
    set_now(dt)
    expire_packets()
    return ok({"now_iso8601": fmt(dt)})


# --------------------------------------------------------------------------
# Playbooks
# --------------------------------------------------------------------------


@bp.route("/playbooks", methods=["POST"])
def create_playbook():
    authenticate(["ChiefCounsel", "OpsAdmin"])
    b = body()
    name = b.get("name")
    if not isinstance(name, str) or not name:
        err("ERR_INVALID_REQUEST", 400, "name is required.")
    pb = {
        "id": new_id(),
        "name": name,
        "status": "DRAFT",
        "published_at": None,
        "clause_count": 0,
        "active_negotiation_count": 0,
    }
    stamp_new(pb)
    db.playbooks[pb["id"]] = pb
    return ok(pub(pb), 201)


@bp.route("/playbooks", methods=["GET"])
def list_playbooks():
    authenticate(ALL_ROLES)
    items = apply_filters(list(db.playbooks.values()), [("status", "status")])
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/playbooks/<playbookId>", methods=["GET"])
def get_playbook(playbookId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.playbooks, playbookId)))


@bp.route("/playbooks/<playbookId>/publish", methods=["POST"])
def publish_playbook(playbookId):
    authenticate(["ChiefCounsel"])
    pb = get_or_404(db.playbooks, playbookId)
    if pb["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a DRAFT playbook can be published.")
    if pb["clause_count"] < 1:
        err("ERR_PLAYBOOK_EMPTY", 409, "Cannot publish a playbook with zero clause templates.")
    has_active = any(
        c for c in db.clauses.values()
        if c["playbook_id"] == pb["id"] and c["status"] == "ACTIVE"
    )
    if not has_active:
        err("ERR_PLAYBOOK_NO_ACTIVE_CLAUSES", 409, "At least one clause must be ACTIVE.")
    pb["status"] = "ACTIVE"
    pb["published_at"] = fmt(now())
    touch(pb)
    return ok(pub(pb))


@bp.route("/playbooks/<playbookId>/deprecate", methods=["POST"])
def deprecate_playbook(playbookId):
    authenticate(["ChiefCounsel"])
    pb = get_or_404(db.playbooks, playbookId)
    if pb["status"] == "ACTIVE":
        if pb["active_negotiation_count"] != 0:
            err("ERR_PLAYBOOK_IN_USE", 409, "Playbook is referenced by active negotiations.")
    elif pb["status"] == "DRAFT":
        pass
    else:
        err("ERR_INVALID_STATE_TRANSITION", 409, "Playbook is already DEPRECATED.")
    pb["status"] = "DEPRECATED"
    touch(pb)
    return ok(pub(pb))


# --------------------------------------------------------------------------
# Clause templates (nested + flat)
# --------------------------------------------------------------------------


def _validate_clause_body(b):
    require_fields(b, [
        "clause_key", "category", "standard_text",
        "fallback_positions", "approver_role_required", "deviation_severity_cap",
    ])
    if not isinstance(b["clause_key"], str) or not b["clause_key"]:
        err("ERR_INVALID_REQUEST", 400, "clause_key must be a non-empty string.")
    if b["category"] not in CLAUSE_CATEGORIES:
        err("ERR_INVALID_REQUEST", 400, "category must be RISK | COMMERCIAL | OPERATIONAL | REGULATORY.")
    if not isinstance(b["standard_text"], str):
        err("ERR_INVALID_REQUEST", 400, "standard_text must be a string.")
    fp = b["fallback_positions"]
    if not isinstance(fp, list) or len(fp) > 3 or not all(isinstance(x, str) for x in fp):
        err("ERR_INVALID_REQUEST", 400, "fallback_positions must be an array of up to 3 strings.")
    if b["approver_role_required"] not in APPROVER_ROLES:
        err("ERR_INVALID_REQUEST", 400, "approver_role_required is not a valid approver role.")
    if b["deviation_severity_cap"] not in SEVERITY_CAPS:
        err("ERR_INVALID_REQUEST", 400, "deviation_severity_cap must be LOW | MEDIUM | HIGH.")


@bp.route("/playbooks/<playbookId>/clauses", methods=["POST"])
def create_clause(playbookId):
    authenticate(["ChiefCounsel"])
    pb = get_or_404(db.playbooks, playbookId)
    b = body()
    _validate_clause_body(b)
    clause = {
        "id": new_id(),
        "playbook_id": pb["id"],
        "clause_key": b["clause_key"],
        "category": b["category"],
        "standard_text": b["standard_text"],
        "fallback_positions": list(b["fallback_positions"]),
        "approver_role_required": b["approver_role_required"],
        "deviation_severity_cap": b["deviation_severity_cap"],
        "status": "ACTIVE",
    }
    stamp_new(clause)
    db.clauses[clause["id"]] = clause
    pb["clause_count"] += 1
    touch(pb)
    return ok(pub(clause), 201)


@bp.route("/playbooks/<playbookId>/clauses", methods=["GET"])
def list_clauses_nested(playbookId):
    authenticate(ALL_ROLES)
    pb = get_or_404(db.playbooks, playbookId)
    items = [c for c in db.clauses.values() if c["playbook_id"] == pb["id"]]
    items = apply_filters(items, [("status", "status"), ("category", "category")])
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/playbooks/<playbookId>/clauses/<clauseId>", methods=["GET"])
def get_clause_nested(playbookId, clauseId):
    authenticate(ALL_ROLES)
    get_or_404(db.playbooks, playbookId)
    clause = get_or_404(db.clauses, clauseId)
    if clause["playbook_id"] != playbookId:
        err("ERR_NOT_FOUND", 404, "Clause %s not found under playbook %s." % (clauseId, playbookId))
    return ok(pub(clause))


@bp.route("/playbooks/<playbookId>/clauses/<clauseId>/retire", methods=["POST"])
def retire_clause(playbookId, clauseId):
    authenticate(["ChiefCounsel"])
    pb = get_or_404(db.playbooks, playbookId)
    clause = get_or_404(db.clauses, clauseId)
    if clause["playbook_id"] != pb["id"]:
        err("ERR_NOT_FOUND", 404, "Clause %s not found under playbook %s." % (clauseId, playbookId))
    if clause["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an ACTIVE clause can be retired.")
    if pb["status"] != "ACTIVE":
        err("ERR_PLAYBOOK_NOT_ACTIVE", 409, "Parent playbook must be ACTIVE to retire a clause.")
    blocking = any(
        d for d in db.deviations.values()
        if d["clause_template_id"] == clause["id"]
        and d["status"] in ("OPEN", "IN_REVIEW", "ESCALATED")
    )
    if blocking:
        err("ERR_CLAUSE_HAS_OPEN_DEVIATIONS", 409, "Clause has open deviations referencing it.")
    clause["status"] = "RETIRED"
    touch(clause)
    pb["clause_count"] -= 1
    touch(pb)
    return ok(pub(clause))


@bp.route("/clauses", methods=["GET"])
def list_clauses_flat():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.clauses.values()),
        [("playbook_id", "playbook_id"), ("status", "status"), ("category", "category")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/clauses/<clauseId>", methods=["GET"])
def get_clause_flat(clauseId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.clauses, clauseId)))


# --------------------------------------------------------------------------
# Contract types
# --------------------------------------------------------------------------


@bp.route("/contract-types", methods=["POST"])
def create_contract_type():
    authenticate(["OpsAdmin"])
    b = body()
    for fk in ("default_business_owner_id", "default_legal_counsel_id"):
        if fk in b and b[fk] is not None and b[fk] not in db.users:
            err("ERR_FOREIGN_KEY_NOT_FOUND", 422, "%s does not resolve to a User." % fk)
    require_fields(b, [
        "code", "display_name",
        "low_value_threshold_cents", "mid_value_threshold_cents", "high_value_threshold_cents",
        "auto_approve_below_cents", "requires_chief_counsel_above_cents",
        "default_business_owner_id", "default_legal_counsel_id",
    ])
    for f in (
        "low_value_threshold_cents", "mid_value_threshold_cents", "high_value_threshold_cents",
        "auto_approve_below_cents", "requires_chief_counsel_above_cents",
    ):
        if not isinstance(b[f], int) or isinstance(b[f], bool):
            err("ERR_INVALID_REQUEST", 400, "%s must be an integer." % f)
    low = b["low_value_threshold_cents"]
    mid = b["mid_value_threshold_cents"]
    high = b["high_value_threshold_cents"]
    if not (mid > low and high > mid):
        err("ERR_THRESHOLDS_NOT_MONOTONIC", 422, "Thresholds must be strictly ascending (low < mid < high).")
    ct = {
        "id": new_id(),
        "code": b["code"],
        "display_name": b["display_name"],
        "low_value_threshold_cents": low,
        "mid_value_threshold_cents": mid,
        "high_value_threshold_cents": high,
        "auto_approve_below_cents": b["auto_approve_below_cents"],
        "requires_chief_counsel_above_cents": b["requires_chief_counsel_above_cents"],
        "default_business_owner_id": b["default_business_owner_id"],
        "default_legal_counsel_id": b["default_legal_counsel_id"],
        "status": "ACTIVE",
    }
    stamp_new(ct)
    db.contract_types[ct["id"]] = ct
    return ok(pub(ct), 201)


@bp.route("/contract-types", methods=["GET"])
def list_contract_types():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.contract_types.values()),
        [
            ("status", "status"),
            ("default_business_owner_id", "default_business_owner_id"),
            ("default_legal_counsel_id", "default_legal_counsel_id"),
        ],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/contract-types/<typeId>", methods=["GET"])
def get_contract_type(typeId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.contract_types, typeId)))


@bp.route("/contract-types/<typeId>/retire", methods=["POST"])
def retire_contract_type(typeId):
    authenticate(["OpsAdmin"])
    ct = get_or_404(db.contract_types, typeId)
    if ct["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an ACTIVE contract type can be retired.")
    in_use = any(
        n for n in db.negotiations.values()
        if n["contract_type_id"] == ct["id"]
        and n["draft_status"] not in ("EXECUTED", "ABORTED")
    )
    if in_use:
        err("ERR_CONTRACT_TYPE_IN_USE", 409, "Contract type is referenced by active negotiations.")
    ct["status"] = "RETIRED"
    touch(ct)
    return ok(pub(ct))


# --------------------------------------------------------------------------
# Counterparties
# --------------------------------------------------------------------------


@bp.route("/counterparties", methods=["POST"])
def create_counterparty():
    authenticate(["OpsAdmin", "ContractAnalyst"])
    b = body()
    require_fields(b, ["legal_name", "jurisdiction"])
    risk = b.get("risk_tier", "STANDARD")
    if risk not in RISK_TIERS:
        err("ERR_INVALID_REQUEST", 400, "risk_tier must be LOW | STANDARD | HIGH_RISK | SANCTIONED.")
    cp = {
        "id": new_id(),
        "legal_name": b["legal_name"],
        "jurisdiction": b["jurisdiction"],
        "risk_tier": risk,
        "active_negotiation_count": 0,
        "last_executed_at": None,
    }
    stamp_new(cp)
    db.counterparties[cp["id"]] = cp
    return ok(pub(cp), 201)


@bp.route("/counterparties", methods=["GET"])
def list_counterparties():
    authenticate(ALL_ROLES)
    items = apply_filters(list(db.counterparties.values()), [("risk_tier", "risk_tier")])
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/counterparties/<counterpartyId>", methods=["GET"])
def get_counterparty(counterpartyId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.counterparties, counterpartyId)))


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


@bp.route("/users", methods=["POST"])
def create_user():
    authenticate(["OpsAdmin"])
    b = body()
    require_fields(b, ["email", "display_name", "primary_role"])
    if b["primary_role"] not in PRIMARY_ROLES:
        err("ERR_INVALID_REQUEST", 400, "primary_role is not a recognized role.")
    cap = b.get("can_sign_above_cents", 0)
    if not isinstance(cap, int) or isinstance(cap, bool):
        err("ERR_INVALID_REQUEST", 400, "can_sign_above_cents must be an integer.")
    u = {
        "id": new_id(),
        "email": b["email"],
        "display_name": b["display_name"],
        "primary_role": b["primary_role"],
        "can_sign_above_cents": cap,
        "status": "ACTIVE",
    }
    stamp_new(u)
    db.users[u["id"]] = u
    return ok(pub(u), 201)


@bp.route("/users", methods=["GET"])
def list_users():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.users.values()),
        [("primary_role", "primary_role"), ("status", "status")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/users/<userId>", methods=["GET"])
def get_user(userId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.users, userId)))


# --------------------------------------------------------------------------
# Intake requests
# --------------------------------------------------------------------------


@bp.route("/intake-requests", methods=["POST"])
def create_intake():
    authenticate(["ContractAnalyst", "BusinessOwner"])
    b = body()
    for fk, coll in (
        ("submitted_by_user_id", db.users),
        ("contract_type_id", db.contract_types),
        ("counterparty_id", db.counterparties),
    ):
        if fk in b and b[fk] is not None and b[fk] not in coll:
            err("ERR_FOREIGN_KEY_NOT_FOUND", 422, "%s does not resolve." % fk)
    require_fields(b, [
        "submitted_by_user_id", "contract_type_id", "counterparty_id",
        "contract_value_cents", "effective_date",
    ])
    v = b["contract_value_cents"]
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        err("ERR_INVALID_REQUEST", 400, "contract_value_cents must be an integer greater than zero.")
    try:
        parse_iso(b["effective_date"])
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "effective_date must be an ISO-8601 timestamp.")
    intake = {
        "id": new_id(),
        "submitted_by_user_id": b["submitted_by_user_id"],
        "contract_type_id": b["contract_type_id"],
        "counterparty_id": b["counterparty_id"],
        "contract_value_cents": v,
        "effective_date": b["effective_date"],
        "routing_bucket": None,
        "assigned_owner_id": None,
        "assigned_legal_id": None,
        "triage_decision_id": None,
        "status": "PENDING_TRIAGE",
    }
    stamp_new(intake)
    db.intakes[intake["id"]] = intake
    return ok(pub(intake), 201)


@bp.route("/intake-requests", methods=["GET"])
def list_intakes():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.intakes.values()),
        [
            ("status", "status"),
            ("routing_bucket", "routing_bucket"),
            ("submitted_by_user_id", "submitted_by_user_id"),
            ("contract_type_id", "contract_type_id"),
            ("counterparty_id", "counterparty_id"),
            ("assigned_owner_id", "assigned_owner_id"),
            ("assigned_legal_id", "assigned_legal_id"),
            ("triage_decision_id", "triage_decision_id"),
        ],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/intake-requests/<intakeRequestId>", methods=["GET"])
def get_intake(intakeRequestId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.intakes, intakeRequestId)))


@bp.route("/intake-requests/<intakeRequestId>/triage", methods=["POST"])
def triage_intake(intakeRequestId):
    user, role = authenticate(["ContractAnalyst"])
    intake = get_or_404(db.intakes, intakeRequestId)
    ct = db.contract_types.get(intake["contract_type_id"])
    cp = db.counterparties.get(intake["counterparty_id"])
    if ct is not None and ct["status"] != "ACTIVE":
        err("ERR_CONTRACT_TYPE_INACTIVE", 409, "Referenced contract type is not ACTIVE.")
    if cp is not None and cp["risk_tier"] == "SANCTIONED":
        err("ERR_COUNTERPARTY_SANCTIONED", 409, "Sanctioned counterparties cannot be routed.")
    if intake["status"] != "PENDING_TRIAGE":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a PENDING_TRIAGE intake can be triaged.")
    v = intake["contract_value_cents"]
    tier = compute_value_tier(ct, v)
    bucket = compute_routing_bucket(tier, cp["risk_tier"], v, ct)
    decided_by = "SYSTEM"
    b = body()
    override = b.get("override_routing_bucket")
    if override is not None:
        if override not in ROUTING_BUCKETS or OVERRIDE_UP.get(bucket) != override:
            err("ERR_INVALID_REQUEST", 400, "override_routing_bucket may only shift the computed bucket up by exactly one level.")
        bucket = override
        decided_by = "ANALYST_OVERRIDE"
    rationale = (
        "value_tier=%s (contract_value_cents=%d against thresholds low=%d mid=%d high=%d); "
        "counterparty_risk=%s; routing_bucket=%s%s."
        % (
            tier, v,
            ct["low_value_threshold_cents"], ct["mid_value_threshold_cents"],
            ct["high_value_threshold_cents"],
            cp["risk_tier"], bucket,
            " (analyst override)" if decided_by == "ANALYST_OVERRIDE" else "",
        )
    )
    td = {
        "id": new_id(),
        "intake_request_id": intake["id"],
        "decided_at": fmt(now()),
        "routing_bucket": bucket,
        "value_tier": tier,
        "counterparty_risk": cp["risk_tier"],
        "rationale": rationale,
        "decided_by": decided_by,
    }
    stamp_audit(td)
    db.triage_decisions[td["id"]] = td
    intake["routing_bucket"] = bucket
    intake["assigned_owner_id"] = ct["default_business_owner_id"]
    intake["assigned_legal_id"] = ct["default_legal_counsel_id"]
    intake["triage_decision_id"] = td["id"]
    intake["status"] = "ROUTED"
    touch(intake)
    return ok(pub(intake))


@bp.route("/intake-requests/<intakeRequestId>/triage-decisions", methods=["GET"])
def list_triage_decisions_nested(intakeRequestId):
    authenticate(ALL_ROLES)
    intake = get_or_404(db.intakes, intakeRequestId)
    items = [t for t in db.triage_decisions.values() if t["intake_request_id"] == intake["id"]]
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/intake-requests/<intakeRequestId>/reject", methods=["POST"])
def reject_intake(intakeRequestId):
    authenticate(["ContractAnalyst"])
    intake = get_or_404(db.intakes, intakeRequestId)
    if intake["status"] != "PENDING_TRIAGE":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a PENDING_TRIAGE intake can be rejected.")
    b = body()
    if not b.get("rejection_reason"):
        err("ERR_INVALID_REQUEST", 400, "rejection_reason is required.")
    intake["status"] = "REJECTED"
    touch(intake)
    return ok(pub(intake))


@bp.route("/intake-requests/<intakeRequestId>/cancel", methods=["POST"])
def cancel_intake(intakeRequestId):
    authenticate(["ContractAnalyst"])
    intake = get_or_404(db.intakes, intakeRequestId)
    if intake["status"] not in ("PENDING_TRIAGE", "ROUTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a PENDING_TRIAGE or ROUTED intake can be cancelled.")
    intake["status"] = "CANCELLED"
    touch(intake)
    return ok(pub(intake))


@bp.route("/intake-requests/<intakeRequestId>/open-negotiation", methods=["POST"])
def open_negotiation(intakeRequestId):
    user, role = authenticate(["ContractAnalyst"])
    intake = get_or_404(db.intakes, intakeRequestId)
    b = body()
    for fk, coll in (("playbook_id", db.playbooks), ("drafter_user_id", db.users)):
        if fk in b and b[fk] is not None and b[fk] not in coll:
            err("ERR_FOREIGN_KEY_NOT_FOUND", 422, "%s does not resolve." % fk)
    require_fields(b, ["playbook_id", "drafter_user_id"])
    pb = db.playbooks[b["playbook_id"]]
    if intake["status"] != "ROUTED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Intake request must be ROUTED to open a negotiation.")
    if pb["status"] != "ACTIVE":
        err("ERR_PLAYBOOK_NOT_ACTIVE", 409, "Referenced playbook is not ACTIVE.")
    expected = b.get("expected_intake_request_version")
    if expected is None:
        err("ERR_INVALID_REQUEST", 400, "expected_intake_request_version is required.")
    if expected != intake["version"]:
        err("ERR_STALE_VERSION", 412, "Intake request version has advanced; re-read before opening.")
    neg = {
        "id": new_id(),
        "intake_request_id": intake["id"],
        "playbook_id": pb["id"],
        "playbook_version_at_pin": None,  # set after counter bump below
        "contract_value_cents": intake["contract_value_cents"],
        "contract_type_id": intake["contract_type_id"],
        "counterparty_id": intake["counterparty_id"],
        "business_owner_id": intake["assigned_owner_id"],
        "legal_counsel_id": intake["assigned_legal_id"],
        "drafter_user_id": b["drafter_user_id"],
        "draft_status": "OPEN",
        "approval_status": "NO_DEVIATIONS",
        "signature_status": "NOT_STARTED",
        "current_round_index": 0,
        "open_deviation_count": 0,
        "blocking_deviation_count": 0,
        "cycle_time_seconds": 0,
        "total_rounds": 0,
        "_executed_at": None,
    }
    stamp_new(neg)
    db.negotiations[neg["id"]] = neg
    intake["status"] = "NEGOTIATION_OPENED"
    touch(intake)
    cp = db.counterparties.get(intake["counterparty_id"])
    if cp is not None:
        cp["active_negotiation_count"] += 1
        touch(cp)
    pb["active_negotiation_count"] += 1
    touch(pb)
    # Pin the playbook version as it stands once the opening cascade has run,
    # so the negotiation is not born stale against its own creation side effect.
    neg["playbook_version_at_pin"] = pb["version"]
    return ok(pub(neg), 201)
