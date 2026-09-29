"""Funding cycles and retrofit grant adjudication (PRD 3.5)."""

from flask import Blueprint

import calc
import envelope
import guards
import store
from errors import ApiError

bp = Blueprint("grants", __name__)

GRANT_NON_TERMINAL = ("SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO",
                      "APPROVED", "FUNDS_RESERVED")
PROJECT_OPEN_STATUSES = ("SCHEDULED", "IN_PROGRESS", "AWAITING_INSPECTION",
                         "REWORK_REQUIRED")
TOTAL_POOL_MIN_CENTS = 100000


# --- funding cycles -------------------------------------------------------

@bp.post("/grant-cycles")
def create_cycle():
    guards.auth(("ProgramAdmin",))
    body = guards.body()
    guards.required(body, ("program_track", "label", "opens_at", "closes_at",
                           "total_pool_cents"))
    if not isinstance(body["program_track"], str) or not isinstance(body["label"], str):
        raise ApiError("ERR_INVALID_REQUEST")
    pool = guards.integer(body, "total_pool_cents", minimum=TOTAL_POOL_MIN_CENTS)
    opens = guards.instant(body, "opens_at")
    closes = guards.instant(body, "closes_at")
    guards.window(opens, closes)
    # Rung 62: closed intervals on the same track, in ANY status; endpoints touch.
    for other in store.DB["cycles"].values():
        if other["program_track"] != body["program_track"]:
            continue
        other_opens = store.dt_of(other, "opens_at")
        other_closes = store.dt_of(other, "closes_at")
        if opens <= other_closes and other_opens <= closes:
            raise ApiError("ERR_GRANT_CYCLE_WINDOW_OVERLAP")
    row = store.insert("cycles", {
        "program_track": body["program_track"],
        "label": body["label"],
        "opens_at": store.iso(opens),
        "closes_at": store.iso(closes),
        "total_pool_cents": pool,
        "reserved_cents": 0,
        "disbursed_cents": 0,
        "uncommitted_cents": pool,
        "status": "OPEN",
    })
    return envelope.created(store.public(row))


@bp.post("/grant-cycles/<row_id>/close")
def close_cycle(row_id):
    guards.auth(("ProgramAdmin",))
    cycle = guards.path_row("cycles", row_id)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_GRANT_CYCLE_CLOSED")
    cycle["status"] = "CLOSED"
    store.touch(cycle)
    return envelope.object_response(store.public(cycle))


@bp.get("/grant-cycles/<row_id>")
def read_cycle(row_id):
    guards.auth(("ProgramAdmin", "GrantReviewer", "Policyholder"))
    cycle = guards.path_row("cycles", row_id)
    return envelope.object_response(store.public(cycle))


@bp.get("/grant-cycles")
def list_cycles():
    guards.auth(("ProgramAdmin", "GrantReviewer"))
    rows = guards.filtered(store.all_rows("cycles"),
                           (("program_track", "program_track"),
                            ("status", "status")))
    return envelope.list_response(rows)


# --- grant applications ---------------------------------------------------

def _open_grant_exists(dwelling_id):
    for grant in store.DB["grants"].values():
        if grant["dwelling_id"] == dwelling_id and grant["status"] in GRANT_NON_TERMINAL:
            return True
    return False


def _cycle_of(grant):
    return store.DB["cycles"][grant["grant_cycle_id"]]


def _policy_of(grant):
    if grant["policy_id"] is None:
        return None
    return store.DB["policies"].get(grant["policy_id"])


@bp.post("/retrofit-grants")
def create_grant():
    role = guards.auth(("Policyholder", "ProgramAdmin"))
    body = guards.body()
    fks = guards.body_fks(body, ("dwelling_id", "policy_id", "grant_cycle_id"))
    dwelling = fks.get("dwelling_id")
    if role == "Policyholder" and dwelling is not None:
        guards.owner_must_be(dwelling["policyholder_id"])
    guards.required(body, ("dwelling_id", "grant_cycle_id", "income_tier",
                           "project_cost_estimate_cents", "requested_scope"))
    income_tier = guards.enum(body, "income_tier", "income_tier")
    scope = guards.enum(body, "requested_scope", "scope")
    estimate = guards.integer(body, "project_cost_estimate_cents", exclusive_min=0)
    cycle = fks["grant_cycle_id"]
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_GRANT_CYCLE_CLOSED")
    policy = fks.get("policy_id")
    if policy is not None and policy["dwelling_id"] != dwelling["id"]:
        raise ApiError("ERR_DWELLING_OWNER_MISMATCH")
    if _open_grant_exists(dwelling["id"]):
        raise ApiError("ERR_DUPLICATE_OPEN_GRANT")
    row = store.insert("grants", {
        "dwelling_id": dwelling["id"],
        "policy_id": policy["id"] if policy is not None else None,
        "grant_cycle_id": cycle["id"],
        "income_tier": income_tier,
        "project_cost_estimate_cents": estimate,
        "requested_scope": scope,
        "approved_amount_cents": 0,
        "funded_from_bucket": "NONE",
        "status": "SUBMITTED",
        "review_round": 0,
        "approved_by_user_id": None,
        "reserved_by_user_id": None,
        "denial_reason": "",
    })
    return envelope.created(store.public(row))


@bp.post("/retrofit-grants/<row_id>/begin-review")
def begin_review(row_id):
    guards.auth(("GrantReviewer", "ProgramAdmin"))
    grant = guards.path_row("grants", row_id)
    if grant["status"] != "SUBMITTED":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    if _cycle_of(grant)["status"] != "OPEN":
        raise ApiError("ERR_GRANT_CYCLE_CLOSED")
    grant["status"] = "UNDER_REVIEW"
    grant["review_round"] += 1
    store.touch(grant)
    return envelope.object_response(store.public(grant))


@bp.post("/retrofit-grants/<row_id>/review")
def review_grant(row_id):
    guards.auth(("GrantReviewer",), need_user_id=True)
    grant = guards.path_row("grants", row_id)
    body = guards.body()
    guards.required(body, ("decision",))
    decision = guards.enum(body, "decision", "decision")
    if grant["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    reason = guards.optional_string(body, "denial_reason")
    if decision == "APPROVE":
        policy = _policy_of(grant)
        if policy is not None and policy["lifecycle_status"] != "ACTIVE":
            raise ApiError("ERR_POLICY_NOT_ACTIVE")
        cycle = _cycle_of(grant)
        now = store.clock_now()
        if (cycle["status"] != "OPEN"
                or now < store.dt_of(cycle, "opens_at")
                or now > store.dt_of(cycle, "closes_at")):
            raise ApiError("ERR_GRANT_CYCLE_CLOSED")
        dwelling = store.DB["dwellings"][grant["dwelling_id"]]
        if not calc.structure_is_grant_eligible(dwelling):
            raise ApiError("ERR_STRUCTURE_NOT_GRANT_ELIGIBLE")
        grant["approved_amount_cents"] = calc.grant_award_amount(grant, dwelling)
        grant["approved_by_user_id"] = guards.acting_id()
        grant["status"] = "APPROVED"
    elif decision == "RETURN":
        if grant["review_round"] >= calc.MAX_REVIEW_ROUNDS:
            raise ApiError("ERR_GRANT_REVIEW_ROUNDS_EXHAUSTED")
        grant["denial_reason"] = reason
        grant["status"] = "RETURNED_FOR_INFO"
    else:
        grant["denial_reason"] = reason
        grant["status"] = "DENIED"
    store.touch(grant)
    return envelope.object_response(store.public(grant))


@bp.post("/retrofit-grants/<row_id>/resubmit")
def resubmit_grant(row_id):
    role = guards.auth(("Policyholder", "ProgramAdmin"))
    grant = guards.path_row("grants", row_id)
    dwelling = store.DB["dwellings"][grant["dwelling_id"]]
    if role == "Policyholder":
        guards.owner_must_be(dwelling["policyholder_id"])
    body = guards.body()
    estimate = None
    if body.get("project_cost_estimate_cents") is not None:
        estimate = guards.integer(body, "project_cost_estimate_cents", exclusive_min=0)
    scope = guards.enum(body, "requested_scope", "scope", optional=True)
    if grant["status"] != "RETURNED_FOR_INFO":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    if estimate is not None:
        grant["project_cost_estimate_cents"] = estimate
    if scope is not None:
        grant["requested_scope"] = scope
    grant["status"] = "SUBMITTED"
    store.touch(grant)
    return envelope.object_response(store.public(grant))


@bp.post("/retrofit-grants/<row_id>/reserve-funds")
def reserve_funds(row_id):
    guards.auth(("ProgramAdmin",), need_user_id=True)
    grant = guards.path_row("grants", row_id)
    guards.sod(grant["approved_by_user_id"], "ERR_SOD_GRANT_REVIEWER_CONFLICT")
    body = guards.body()
    guards.required(body, ("expected_grant_cycle_version",))
    cycle = _cycle_of(grant)
    guards.occ(body, "expected_grant_cycle_version", cycle["version"],
               "ERR_STALE_GRANT_CYCLE_VERSION")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_GRANT_CYCLE_CLOSED")
    if grant["status"] != "APPROVED":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    bucket = calc.resolve_bucket(cycle, grant)
    award = grant["approved_amount_cents"]
    if cycle["reserved_cents"] + cycle["disbursed_cents"] + award > cycle["total_pool_cents"]:
        raise ApiError("ERR_GRANT_CYCLE_POOL_EXHAUSTED")
    grant["funded_from_bucket"] = bucket
    grant["reserved_by_user_id"] = guards.acting_id()
    grant["status"] = "FUNDS_RESERVED"
    cycle["reserved_cents"] += award
    calc.recompute_uncommitted(cycle)
    store.touch(cycle)
    dwelling = store.DB["dwellings"][grant["dwelling_id"]]
    dwelling["grant_lifetime_count"] += 1
    store.touch(dwelling)
    policy = _policy_of(grant)
    if (policy is not None and policy["lifecycle_status"] == "ACTIVE"
            and policy["mitigation_status"] == "UNMITIGATED"):
        policy["mitigation_status"] = "RETROFIT_PENDING"
        store.touch(policy)
    store.touch(grant)
    return envelope.object_response(store.public(grant))


@bp.post("/retrofit-grants/<row_id>/withdraw")
def withdraw_grant(row_id):
    role = guards.auth(("ProgramAdmin", "Policyholder"))
    grant = guards.path_row("grants", row_id)
    dwelling = store.DB["dwellings"][grant["dwelling_id"]]
    if role == "Policyholder":
        guards.owner_must_be(dwelling["policyholder_id"])
    guards.body()
    if grant["status"] not in GRANT_NON_TERMINAL:
        raise ApiError("ERR_GRANT_INVALID_STATE")
    was_reserved = grant["status"] == "FUNDS_RESERVED"
    grant["status"] = "WITHDRAWN"
    if was_reserved:
        cycle = _cycle_of(grant)
        cycle["reserved_cents"] -= grant["approved_amount_cents"]
        calc.recompute_uncommitted(cycle)
        store.touch(cycle)
        grant["funded_from_bucket"] = "NONE"
        for project in store.all_rows("projects"):
            if project["grant_id"] != grant["id"]:
                continue
            if project["status"] not in PROJECT_OPEN_STATUSES:
                continue
            project["status"] = "ABANDONED"
            store.touch(project)
            contractor = store.DB["contractors"].get(project["contractor_id"])
            if contractor is not None:
                contractor["open_project_count"] = max(
                    0, contractor["open_project_count"] - 1)
                store.touch(contractor)
        policy = _policy_of(grant)
        if policy is not None and policy["mitigation_status"] == "RETROFIT_PENDING":
            policy["mitigation_status"] = "UNMITIGATED"
            store.touch(policy)
    store.touch(grant)
    return envelope.object_response(store.public(grant))


@bp.get("/retrofit-grants/<row_id>")
def read_grant(row_id):
    role = guards.auth(("ProgramAdmin", "GrantReviewer", "Policyholder", "FieldInspector"))
    grant = guards.path_row("grants", row_id)
    if role == "Policyholder":
        dwelling = store.DB["dwellings"][grant["dwelling_id"]]
        guards.owner_must_be(dwelling["policyholder_id"])
    return envelope.object_response(store.public(grant))


@bp.get("/retrofit-grants")
def list_grants():
    role = guards.auth(("ProgramAdmin", "GrantReviewer", "Policyholder"))
    rows = store.all_rows("grants")
    if role == "Policyholder":
        owner = guards.acting_id()
        rows = [row for row in rows
                if store.DB["dwellings"][row["dwelling_id"]]["policyholder_id"] == owner]
    rows = guards.filtered(rows, (("dwelling_id", "dwelling_id"),
                                  ("policy_id", "policy_id"),
                                  ("grant_cycle_id", "grant_cycle_id"),
                                  ("status", "status"),
                                  ("income_tier", "income_tier"),
                                  ("funded_from_bucket", "funded_from_bucket")))
    return envelope.list_response(rows)
