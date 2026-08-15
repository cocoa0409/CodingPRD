"""AssumptionSet endpoints (PRD 3.2): draft, edit, submit, approve (with
supersession cascade), reject."""

import store
from envelope import list_response, object_response
from errors import ApiError
from serializers import assumption_set_json
from services import stamp_new, touch
from timeutil import clock
from validate import req_enum, req_object, req_str

from routes.common import READ_ROLES, endpoint, get_or_404

DOMAINS = ("PREPAYMENT", "DEPOSIT_DECAY", "DEPOSIT_BETA")

# Exact params key sets per domain (scaffold 1.1 / 1.3).
PARAM_SCHEMA = {
    "PREPAYMENT": frozenset(("base_cpr_pct", "prepay_sensitivity_per_100bps")),
    "DEPOSIT_DECAY": frozenset(("base_annual_decay_pct", "surge_decay_per_100bps")),
    "DEPOSIT_BETA": frozenset(("up_beta_pct", "down_beta_pct", "lag_months")),
}


@endpoint("POST", "/books/<book_id>/assumption-sets", roles=["TreasuryAnalyst"])
def create_assumption_set(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    body = ctx.body
    domain = req_enum(body, "domain", DOMAINS)
    params = req_object(body, "params")
    aset = {
        "book_id": book["id"],
        "domain": domain,  # immutable after create
        "params": params,
        "status": "DRAFT",
        "created_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "approved_at": None,
        "governance_flag": "NONE",
    }
    stamp_new(aset)
    store.assumption_sets[aset["id"]] = aset
    return object_response(assumption_set_json(aset), 201)


@endpoint("GET", "/books/<book_id>/assumption-sets", roles=READ_ROLES)
def list_assumption_sets(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    rows = [a for a in store.assumption_sets.values() if a["book_id"] == book["id"]]
    domain = ctx.args.get("domain")
    if domain is not None:
        rows = [a for a in rows if a["domain"] == domain]
    status = ctx.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return list_response(rows, ctx.args, assumption_set_json)


@endpoint("GET", "/assumption-sets/<set_id>", roles=READ_ROLES)
def get_assumption_set(ctx):
    aset = get_or_404(store.assumption_sets, ctx.param("set_id"))
    return object_response(assumption_set_json(aset))


@endpoint("PATCH", "/assumption-sets/<set_id>", roles=["TreasuryAnalyst"])
def patch_assumption_set(ctx):
    aset = get_or_404(store.assumption_sets, ctx.param("set_id"))
    params = req_object(ctx.body, "params")  # rung 4
    if aset["status"] != "DRAFT":  # rung 6: params editable only while DRAFT
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    aset["params"] = params
    touch(aset)
    return object_response(assumption_set_json(aset))


@endpoint("POST", "/assumption-sets/<set_id>/submit", roles=["TreasuryAnalyst"])
def submit_assumption_set(ctx):
    aset = get_or_404(store.assumption_sets, ctx.param("set_id"))
    # Rung 4 (priority 4 outranks rung 6 state): params keys must exactly
    # match the set's domain schema.
    if not isinstance(aset["params"], dict) or (
        frozenset(aset["params"].keys()) != PARAM_SCHEMA[aset["domain"]]
    ):
        raise ApiError("ERR_ASSUMPTION_PARAMS_MISMATCH")
    if aset["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    aset["status"] = "SUBMITTED"
    touch(aset)
    return object_response(assumption_set_json(aset))


@endpoint("POST", "/assumption-sets/<set_id>/approve", roles=["ALCOChair"])
def approve_assumption_set(ctx):
    aset = get_or_404(store.assumption_sets, ctx.param("set_id"))
    if aset["status"] != "SUBMITTED":  # rung 6
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 7: segregation of duties - approver must differ from creator.
    if ctx.user_id == aset["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Cascade: any other APPROVED set in the same (book, domain) -> SUPERSEDED;
    # runs pinning a superseded set read assumption_stale = true on demand.
    for other in store.assumption_sets.values():
        if (
            other["id"] != aset["id"]
            and other["book_id"] == aset["book_id"]
            and other["domain"] == aset["domain"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    aset["status"] = "APPROVED"
    aset["approved_by_user_id"] = ctx.user_id
    aset["approved_at"] = clock.now_string()
    touch(aset)
    return object_response(assumption_set_json(aset))


@endpoint("POST", "/assumption-sets/<set_id>/reject", roles=["ALCOChair"])
def reject_assumption_set(ctx):
    aset = get_or_404(store.assumption_sets, ctx.param("set_id"))
    req_str(ctx.body, "reason")  # rung 4: rejection is accompanied by a reason
    if aset["status"] != "SUBMITTED":  # rung 6
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    aset["status"] = "DRAFT"  # back for revision; the cycle may repeat
    touch(aset)
    return object_response(assumption_set_json(aset))
