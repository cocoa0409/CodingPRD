"""Account endpoints: create, read, list, contract lifecycle, change-plan."""
from flask import Blueprint, request

import clock
from db import db, new_id, new_common, touch
from errors import (
    err,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_ACCOUNT_OWNER,
    ERR_STALE_VERSION,
    ERR_OPEN_DISPATCH,
)
from middleware import authenticate, require_role
from response import success, list_response
from services import validate, common
from services import calc
from services.derive import serialize_account

bp = Blueprint("accounts", __name__)

PREMISES_TYPES = {"RESIDENTIAL", "COMMERCIAL"}


def _ownership_check(caller, account):
    """Subscriber may only act on their own account (X-User-ID == account.id)."""
    if caller.role == "Subscriber" and caller.user_id != account["id"]:
        raise err(ERR_NOT_ACCOUNT_OWNER, "Subscriber is not the owner of this account")


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------
@bp.route("/accounts", methods=["POST"])
def create_account():
    caller = authenticate()
    require_role(caller, {"Administrator"})
    body = validate.get_body()

    # FK presence + resolution before other body validation (priority 4 < 17)
    plan_id = validate.require_str(body, "plan_id")
    if plan_id not in db.monitoring_plans:
        raise err(ERR_REFERENCE_NOT_FOUND, "plan_id does not resolve: %s" % plan_id)

    premises_type = validate.require_enum(body, "premises_type", PREMISES_TYPES)
    contract_term_months = validate.require_int(body, "contract_term_months", minimum=1)

    aid = new_id()
    account = {"id": aid}
    account.update(new_common())
    account.update({
        "premises_type": premises_type,
        "plan_id": plan_id,
        "contract_status": "PENDING",
        "contract_start_utc": None,
        "contract_term_months": contract_term_months,
        "cycle_anchor_utc": None,
        "current_tier": None,
        "_anchor_tier": None,
        "early_termination_fee_cents": 0,
    })
    db.accounts[aid] = account
    db.plan_change_segments[aid] = []
    return success(serialize_account(account), http_status=201)


@bp.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    account = common.lookup(db.accounts, aid)
    return success(serialize_account(account))


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator"})
    limit, offset = common.parse_pagination()
    plan_id = request.args.get("plan_id")
    contract_status = request.args.get("contract_status")
    items = list(db.accounts.values())
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if contract_status is not None:
        items = [a for a in items if a["contract_status"] == contract_status]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_account(a) for a in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
@bp.route("/accounts/<aid>/activate", methods=["POST"])
def activate_account(aid):
    caller = authenticate()
    require_role(caller, {"Administrator"})
    account = common.lookup(db.accounts, aid)

    if account["contract_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Account is not PENDING")

    # at least one system with sensor_count >= 1
    from services.derive import systems_for_account, system_sensor_count
    has_ready_system = any(
        system_sensor_count(s["id"]) >= 1 for s in systems_for_account(aid)
    )
    if not has_ready_system:
        raise err(ERR_INVALID_STATE, "Account has no system with at least one sensor")

    plan = db.monitoring_plans.get(account["plan_id"])
    if plan is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Account plan no longer exists")

    now = clock.now()
    account["contract_status"] = "ACTIVE"
    account["contract_start_utc"] = now
    account["cycle_anchor_utc"] = now
    account["current_tier"] = plan["tier"]
    account["_anchor_tier"] = plan["tier"]
    db.plan_change_segments[aid] = []
    touch(account)
    return success(serialize_account(account))


@bp.route("/accounts/<aid>/change-plan", methods=["POST"])
def change_plan(aid):
    caller = authenticate()
    require_role(caller, {"Administrator"})
    account = common.lookup(db.accounts, aid)
    body = validate.get_body()

    # FK presence + resolution
    new_plan_id = validate.require_str(body, "new_plan_id")
    if new_plan_id not in db.monitoring_plans:
        raise err(ERR_REFERENCE_NOT_FOUND, "new_plan_id does not resolve: %s" % new_plan_id)

    expected_version = validate.require_int(body, "expected_account_version")

    # State: change-plan defined only on ACTIVE / CANCELLATION_REQUESTED contracts
    # (must have an open cycle to re-anchor).
    if account["contract_status"] not in ("ACTIVE", "CANCELLATION_REQUESTED"):
        raise err(ERR_INVALID_STATE, "Account contract is not in a changeable state")

    # Business band: open-dispatch guard (priority 15) before OCC (priority 16)
    for ev in db.alarm_events.values():
        if ev.get("_account_id") == aid and ev["status"] == "DISPATCHED":
            raise err(ERR_OPEN_DISPATCH, "An alarm event under the account is DISPATCHED")

    # OCC (priority 16)
    if expected_version != account["version"]:
        raise err(ERR_STALE_VERSION, "expected_account_version does not match current version")

    new_plan = db.monitoring_plans[new_plan_id]
    now = clock.now()
    db.plan_change_segments.setdefault(aid, []).append({"at": now, "tier": new_plan["tier"]})
    account["plan_id"] = new_plan_id
    account["current_tier"] = new_plan["tier"]
    touch(account)
    return success(serialize_account(account))


@bp.route("/accounts/<aid>/request-cancellation", methods=["POST"])
def request_cancellation(aid):
    caller = authenticate()
    require_role(caller, {"Subscriber", "Administrator"})
    account = common.lookup(db.accounts, aid)
    _ownership_check(caller, account)

    if account["contract_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Account is not ACTIVE")

    fee = calc.early_termination_fee(
        account["contract_start_utc"],
        account["contract_term_months"],
        clock.now(),
    )
    account["contract_status"] = "CANCELLATION_REQUESTED"
    account["early_termination_fee_cents"] = fee
    touch(account)
    return success(serialize_account(account))


@bp.route("/accounts/<aid>/withdraw-cancellation", methods=["POST"])
def withdraw_cancellation(aid):
    caller = authenticate()
    require_role(caller, {"Subscriber", "Administrator"})
    account = common.lookup(db.accounts, aid)
    _ownership_check(caller, account)

    if account["contract_status"] != "CANCELLATION_REQUESTED":
        raise err(ERR_INVALID_STATE, "Account is not CANCELLATION_REQUESTED")

    account["contract_status"] = "ACTIVE"
    account["early_termination_fee_cents"] = 0
    touch(account)
    return success(serialize_account(account))


@bp.route("/accounts/<aid>/finalize-cancellation", methods=["POST"])
def finalize_cancellation(aid):
    caller = authenticate()
    require_role(caller, {"Administrator"})
    account = common.lookup(db.accounts, aid)
    body = validate.get_body()

    expected_version = validate.require_int(body, "expected_account_version")

    if account["contract_status"] != "CANCELLATION_REQUESTED":
        raise err(ERR_INVALID_STATE, "Account is not CANCELLATION_REQUESTED")

    # OCC (priority 16)
    if expected_version != account["version"]:
        raise err(ERR_STALE_VERSION, "expected_account_version does not match current version")

    from services.derive import systems_for_account

    account["contract_status"] = "CANCELLED"

    # CASCADE step 1: every system DISARMED + test_mode cleared
    for sys in systems_for_account(aid):
        sys_changed = False
        if sys["arming_state"] != "DISARMED":
            sys["arming_state"] = "DISARMED"
            sys_changed = True
        if sys["test_mode"] or sys.get("test_mode_expires_utc") is not None:
            sys["test_mode"] = False
            sys["test_mode_expires_utc"] = None
            sys_changed = True
        if sys_changed:
            touch(sys)

    # CASCADE step 2: open AlarmEvents (RECEIVED/ROUTED/DISPATCHED) -> SUPPRESSED
    for ev in db.alarm_events.values():
        if ev.get("_account_id") != aid:
            continue
        if ev["status"] in ("RECEIVED", "ROUTED", "DISPATCHED"):
            ev["status"] = "SUPPRESSED"
            touch(ev)
            # CASCADE step 3: ORDERED Dispatch on the event -> CANCELLED (fee reversal)
            for d in db.dispatches.values():
                if d["alarm_event_id"] == ev["id"] and d["status"] == "ORDERED":
                    d["status"] = "CANCELLED"
                    touch(d)

    touch(account)
    return success(serialize_account(account))
