"""Grant routes — submission, approvals, agreement, acceleration, vesting."""

from flask import Blueprint, request, g as flask_g
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_CROSS_RESOURCE_MISMATCH,
    ERR_BATCH_NOT_OPEN, ERR_GRANT_NOT_IN_DRAFT, ERR_GRANT_NOT_BOARD_APPROVED,
    ERR_GRANT_NOT_SHAREHOLDER_APPROVED, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_GRANTEE_INELIGIBLE, ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_POOL_INSUFFICIENT, ERR_BLACKOUT_ACTIVE, ERR_INVALID_TIME_INTERVAL,
)
from services.common import (
    init_common, init_append_only, bump_version, check_occ, get_body, get_or_404,
    get_pagination, paginate_list, sort_by_created_at_asc,
    require_string, require_enum,
)
from services.time_util import format_iso, parse_iso
from services.serializers import (
    serialize_grant, serialize_vesting_record,
    compute_pool_reserved_options,
)
from services.calculations import compute_vested_quantity
from services.audit import append_audit


bp = Blueprint("grants", __name__)


def _verify_plan_batch_chain(plan_id, batch_id):
    plan = get_or_404("option_plans", plan_id)
    batch = get_or_404("grant_batches", batch_id)
    if batch["plan_id"] != plan_id:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Batch does not belong to plan")
    return plan, batch


def _active_blackouts(plan, clock):
    out = []
    for ev in DB["corporate_events"].values():
        if ev["plan_id"] != plan["id"]:
            continue
        if ev["event_type"] not in ("EARNINGS_BLACKOUT", "MATERIAL_EVENT_BLACKOUT"):
            continue
        start = parse_iso(ev["effective_ts"])
        end = parse_iso(ev["blackout_end_ts"])
        if start is None or end is None:
            continue
        if start <= clock < end:
            out.append(ev)
    return out


@bp.post("/option-plans/<plan_id>/grant-batches/<batch_id>/grants")
@auth_required(["PlanAdministrator"])
def submit_grant(plan_id, batch_id):
    plan, batch = _verify_plan_batch_chain(plan_id, batch_id)
    if batch["status"] != "OPEN_FOR_GRANTS":
        raise_error(ERR_BATCH_NOT_OPEN, "Batch must be OPEN_FOR_GRANTS")
    body = get_body()
    grantee_id = require_string(body, "grantee_id")
    grantee = DB["grantees"].get(grantee_id)
    if grantee is None or grantee["plan_id"] != plan_id:
        raise_error(ERR_INVALID_REQUEST, "grantee_id not found in this plan")
    quantity = body.get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise_error(ERR_INVALID_REQUEST, "quantity must be positive integer")
    fmv = body.get("grant_date_fair_value_cents")
    if not isinstance(fmv, int) or isinstance(fmv, bool) or fmv < 1:
        raise_error(ERR_INVALID_REQUEST, "grant_date_fair_value_cents must be >=1")
    gid = new_id()
    grant = {
        "id": gid,
        "plan_id": plan_id,
        "batch_id": batch_id,
        "grantee_id": grantee_id,
        "quantity": quantity,
        "grant_date": None,
        "grant_date_fair_value_cents": fmv,
        "pinned_price_version_id": None,
        "board_approval_actor_id": None,
        "shareholder_approval_actor_id": None,
        "submitted_by_actor_id": flask_g.user_id,
        "vested_quantity": 0,
        "exercised_quantity": 0,
        "forfeited_quantity": 0,
        "performance_attested_at": None,
        "status": "DRAFT",
    }
    init_common(grant)
    DB["grants"][gid] = grant
    append_audit(plan, "GRANT_CREATED", "Grant", gid,
                 {"grantee_id": grantee_id, "quantity": quantity, "fmv_cents": fmv})
    return success_response(serialize_grant(grant), http_status=201)


@bp.get("/option-plans/<plan_id>/grants")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "AuditViewer"])
def list_plan_grants(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    grantee_id = request.args.get("grantee_id")
    status = request.args.get("status")
    items = [g for g in DB["grants"].values() if g["plan_id"] == plan_id]
    if grantee_id:
        items = [g for g in items if g["grantee_id"] == grantee_id]
    if status:
        items = [g for g in items if g["status"] == status]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_grant(g) for g in sliced], total, limit, offset)


@bp.get("/grants/<grant_id>")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "Grantee", "AuditViewer"])
def get_grant(grant_id):
    grant = get_or_404("grants", grant_id)
    # Grantee can only see own
    if flask_g.user_role == "Grantee":
        grantee = DB["grantees"].get(grant["grantee_id"])
        if not grantee or grantee["hr_employee_id"] != flask_g.user_id:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "Grantee may only read own grants")
    return success_response(serialize_grant(grant))


@bp.post("/grants/<grant_id>/board-approve")
@auth_required(["BoardSecretary"])
def board_approve(grant_id):
    grant = get_or_404("grants", grant_id)
    body = get_body()
    check_occ(grant, body)
    # SoD must run before state-check per state machine table (SoD is priority 6, but
    # state-machine preconditions in the SCAFFOLD lists SoD as the first precondition
    # of the board-approve transition: it should fire before NotIn-DRAFT).
    # Per PRD §3.4: 'Four checks fire in order: SoD ... DRAFT ... batch OPEN ... pool'.
    if flask_g.user_id == grant.get("submitted_by_actor_id"):
        raise_error(ERR_SEGREGATION_OF_DUTIES_VIOLATION, "Cannot approve own draft")
    if grant["status"] != "DRAFT":
        raise_error(ERR_GRANT_NOT_IN_DRAFT, "Grant not in DRAFT")
    batch = DB["grant_batches"].get(grant["batch_id"])
    if batch is None or batch["status"] != "OPEN_FOR_GRANTS":
        raise_error(ERR_BATCH_NOT_OPEN, "Batch not OPEN_FOR_GRANTS")
    plan = DB["option_plans"].get(grant["plan_id"])
    # pool check
    reserved = compute_pool_reserved_options(plan)
    remaining = int(plan["pool_total_options"]) - reserved
    if int(grant["quantity"]) > remaining:
        raise_error(ERR_POOL_INSUFFICIENT, "Pool insufficient")
    grant["board_approval_actor_id"] = flask_g.user_id
    grant["status"] = "BOARD_APPROVED"
    bump_version(grant)
    bump_version(plan)  # pool_reserved_options is recomputed; plan version reflects state change
    append_audit(plan, "GRANT_BOARD_APPROVED", "Grant", grant_id,
                 {"actor_id": flask_g.user_id, "quantity": grant["quantity"]})
    return success_response(serialize_grant(grant))


@bp.post("/grants/<grant_id>/shareholder-approve")
@auth_required(["ShareholderRegistrar"])
def shareholder_approve(grant_id):
    grant = get_or_404("grants", grant_id)
    body = get_body()
    check_occ(grant, body)
    if flask_g.user_id in {grant.get("submitted_by_actor_id"), grant.get("board_approval_actor_id")}:
        raise_error(ERR_SEGREGATION_OF_DUTIES_VIOLATION, "Cannot approve own or board-approved grant")
    if grant["status"] != "BOARD_APPROVED":
        raise_error(ERR_GRANT_NOT_BOARD_APPROVED, "Grant not BOARD_APPROVED")
    plan = DB["option_plans"].get(grant["plan_id"])
    grant["shareholder_approval_actor_id"] = flask_g.user_id
    grant["grant_date"] = plan.get("current_clock_ts")
    grant["status"] = "SHAREHOLDER_APPROVED"
    bump_version(grant)
    # Append GRANT TaxEventRecord
    grantee = DB["grantees"].get(grant["grantee_id"])
    from services.calculations import compute_tax_for_event
    taxable, withheld, deferred = compute_tax_for_event(plan, grant, grantee, "GRANT")
    teid = new_id()
    te = {
        "id": teid,
        "grant_id": grant["id"],
        "exercise_application_id": None,
        "event_type": "GRANT",
        "taxable_amount_cents": taxable,
        "withheld_amount_cents": withheld,
        "deferred": deferred,
        "jurisdiction_code": plan["jurisdiction_code"],
        "document_id": None,
        "event_ts": plan.get("current_clock_ts"),
        "payload_summary": {},
    }
    init_append_only(te)
    DB["tax_events"][teid] = te
    append_audit(plan, "GRANT_SHAREHOLDER_APPROVED", "Grant", grant_id,
                 {"actor_id": flask_g.user_id, "grant_date": grant["grant_date"]})
    return success_response(serialize_grant(grant))


@bp.post("/grants/<grant_id>/sign-agreement")
@auth_required(["Grantee"])
def sign_agreement(grant_id):
    grant = get_or_404("grants", grant_id)
    body = get_body()
    check_occ(grant, body)
    grantee = DB["grantees"].get(grant["grantee_id"])
    if not grantee or grantee["hr_employee_id"] != flask_g.user_id:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "Caller is not the grant's grantee")
    if grant["status"] != "SHAREHOLDER_APPROVED":
        raise_error(ERR_GRANT_NOT_SHAREHOLDER_APPROVED, "Grant not SHAREHOLDER_APPROVED")
    if grantee["eligibility_status"] != "ELIGIBLE":
        raise_error(ERR_GRANTEE_INELIGIBLE, "Grantee not ELIGIBLE")
    plan = DB["option_plans"].get(grant["plan_id"])
    clock = parse_iso(plan["current_clock_ts"]) if plan.get("current_clock_ts") else None
    active_blackouts = _active_blackouts(plan, clock) if clock else []
    require_live = bool(body.get("require_live", False))
    if active_blackouts and require_live:
        raise_error(ERR_BLACKOUT_ACTIVE, "Active blackout prevents LIVE routing")

    # Pin price version = current tip on batch
    tip = _latest_price_version_for_batch(grant["batch_id"])
    if tip is None:
        raise_error(ERR_INVALID_REQUEST, "No exercise price version for batch")
    grant["pinned_price_version_id"] = tip["id"]
    grant["status"] = "AGREEMENT_SIGNED"
    # Auto-route to LIVE or FROZEN
    if active_blackouts:
        grant["status"] = "FROZEN"
    else:
        grant["status"] = "LIVE"
    bump_version(grant)
    append_audit(plan, "GRANT_AGREEMENT_SIGNED", "Grant", grant_id,
                 {"pinned_price_version_id": tip["id"], "final_status": grant["status"]})
    return success_response(serialize_grant(grant))


def _latest_price_version_for_batch(batch_id):
    best = None
    for v in DB["exercise_price_versions"].values():
        if v["batch_id"] != batch_id:
            continue
        if best is None or v["version_index"] > best["version_index"]:
            best = v
    return best


@bp.post("/grants/<grant_id>/accelerate-vesting")
@auth_required(["PlanAdministrator"])
def accelerate_vesting(grant_id):
    grant = get_or_404("grants", grant_id)
    body = get_body()
    check_occ(grant, body)
    plan = DB["option_plans"].get(grant["plan_id"])
    batch = DB["grant_batches"].get(grant["batch_id"])
    ev_id = body.get("corporate_event_id")
    if not isinstance(ev_id, str) or not ev_id.strip():
        raise_error(ERR_INVALID_TIME_INTERVAL, "corporate_event_id required")
    event = DB["corporate_events"].get(ev_id)
    if event is None or event["event_type"] not in ("CHANGE_OF_CONTROL", "IPO"):
        raise_error(ERR_INVALID_TIME_INTERVAL, "Acceleration requires CHANGE_OF_CONTROL or IPO event")
    if event["plan_id"] != grant["plan_id"]:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Event does not belong to plan")
    # Compute remaining outstanding to accelerate
    current_vested = compute_vested_quantity(grant, plan, batch)
    remaining = int(grant["quantity"]) - int(grant.get("exercised_quantity", 0)) - int(grant.get("forfeited_quantity", 0)) - current_vested
    if remaining < 0:
        remaining = 0
    # Default: accelerate the full remaining outstanding (unvested portion)
    tranche = remaining
    cause = "ACCELERATION_CHANGE_OF_CONTROL" if event["event_type"] == "CHANGE_OF_CONTROL" else "ACCELERATION_IPO"
    next_idx = _next_tranche_index(grant_id)
    vrid = new_id()
    vr = {
        "id": vrid,
        "grant_id": grant_id,
        "tranche_index": next_idx,
        "vested_ts": plan.get("current_clock_ts"),
        "tranche_quantity": tranche,
        "cause": cause,
        "archived": False,
    }
    init_append_only(vr)
    DB["vesting_records"][vrid] = vr
    bump_version(grant)
    return success_response(serialize_grant(grant))


def _next_tranche_index(grant_id):
    idx = 0
    for vr in DB["vesting_records"].values():
        if vr["grant_id"] == grant_id:
            if vr["tranche_index"] > idx:
                idx = vr["tranche_index"]
    return idx + 1


@bp.post("/grants/<grant_id>/attest-performance")
@auth_required(["PlanAdministrator"])
def attest_performance(grant_id):
    grant = get_or_404("grants", grant_id)
    body = get_body()
    check_occ(grant, body)
    plan = DB["option_plans"].get(grant["plan_id"])
    grant["performance_attested_at"] = plan.get("current_clock_ts")
    bump_version(grant)
    return success_response(serialize_grant(grant))


@bp.post("/grants/<grant_id>/vesting/recompute")
@auth_required(["PlanAdministrator"])
def recompute_vesting(grant_id):
    grant = get_or_404("grants", grant_id)
    body = get_body()
    check_occ(grant, body)
    plan = DB["option_plans"].get(grant["plan_id"])
    batch = DB["grant_batches"].get(grant["batch_id"])
    # Compute current vested (unconditional + gated)
    new_vested = compute_vested_quantity(grant, plan, batch)
    old_vested = int(grant.get("vested_quantity", 0))
    delta = new_vested - old_vested
    if delta > 0:
        # Emit a single PERIODIC (or CLIFF if first crossing) VestingRecord with the delta
        cause = "CLIFF" if old_vested == 0 and int(batch["cliff_months"]) > 0 else "PERIODIC"
        next_idx = _next_tranche_index(grant_id)
        vrid = new_id()
        vr = {
            "id": vrid,
            "grant_id": grant_id,
            "tranche_index": next_idx,
            "vested_ts": plan.get("current_clock_ts"),
            "tranche_quantity": delta,
            "cause": cause,
            "archived": False,
        }
        init_append_only(vr)
        DB["vesting_records"][vrid] = vr
    grant["vested_quantity"] = new_vested
    bump_version(grant)
    return success_response(serialize_grant(grant))


@bp.get("/grants/<grant_id>/vesting-records")
@auth_required(["PlanAdministrator", "Grantee", "AuditViewer"])
def list_vesting_records(grant_id):
    grant = get_or_404("grants", grant_id)
    if flask_g.user_role == "Grantee":
        grantee = DB["grantees"].get(grant["grantee_id"])
        if not grantee or grantee["hr_employee_id"] != flask_g.user_id:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "Grantee may only read own")
    archived = request.args.get("archived")
    items = [v for v in DB["vesting_records"].values() if v["grant_id"] == grant_id]
    if archived is not None:
        want = archived.lower() in ("true", "1", "yes")
        items = [v for v in items if bool(v.get("archived")) is want]
    items.sort(key=lambda v: v["tranche_index"])
    limit, offset = get_pagination()
    total = len(items)
    sliced = items[offset:offset + limit]
    return list_response([serialize_vesting_record(v) for v in sliced], total, limit, offset)


@bp.post("/grants/<grant_id>/vesting-records/archive")
@auth_required(["PlanAdministrator"])
def archive_vesting_records(grant_id):
    get_or_404("grants", grant_id)
    items = [v for v in DB["vesting_records"].values() if v["grant_id"] == grant_id]
    for v in items:
        v["archived"] = True
    items.sort(key=lambda v: v["tranche_index"])
    # Return the archived rows as an array
    from response import list_response as _lr
    return _lr([serialize_vesting_record(v) for v in items], len(items), len(items) if len(items) > 0 else 10, 0)
