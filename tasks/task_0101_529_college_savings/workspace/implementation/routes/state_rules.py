"""State-rule endpoints."""

from flask import Blueprint, request
from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, lock
from core.validation import (
    require_body, require_state_code, require_field, require_enum,
    parse_pagination,
)
from core.models import state_rule_create, state_rule_replace, state_rule_view


bp = Blueprint("state_rules", __name__)


@bp.post("/state-rules")
@require_roles("PlanAdministrator")
def upsert_state_rule():
    body = require_body(request)
    state_code = require_state_code(body, "state_code")
    deduction_cap = require_field(body, "deduction_cap_cents", kind="non_neg_int")
    parity = require_enum(body, "parity", {"IN_STATE_ONLY", "PARITY"})
    lifetime_cap = require_field(body, "lifetime_aggregate_cap_cents", kind="positive_int")
    k12_qualified = require_field(body, "k12_qualified", kind="bool")

    with lock():
        existing = STORE.state_rules.get(state_code)
        if existing:
            rule = state_rule_replace(existing, deduction_cap, parity, lifetime_cap, k12_qualified)
            return success_object(state_rule_view(rule), 201)
        rule = state_rule_create(state_code, deduction_cap, parity, lifetime_cap, k12_qualified)
    return success_object(state_rule_view(rule), 201)


@bp.get("/state-rules/<state_code>")
@require_roles("PlanAdministrator", "Donor")
def get_state_rule(state_code):
    r = STORE.state_rules.get(state_code)
    if not r:
        raise_error("ERR_NOT_FOUND", f"StateRule {state_code} not found")
    return success_object(state_rule_view(r))


@bp.get("/state-rules")
@require_roles("PlanAdministrator", "Donor")
def list_state_rules():
    limit, offset = parse_pagination(request)
    rules = sorted(STORE.state_rules.values(),
                   key=lambda r: (r["_created_seq"], r["id"]))
    total = len(rules)
    page = [state_rule_view(r) for r in rules[offset:offset + limit]]
    return success_array(page, limit, offset, total)
