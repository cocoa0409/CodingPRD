"""Deposit accounts, funding movements, coverage reports and runoff forecasts."""

from flask import Blueprint

import db
import middleware as mw
from constants import (
    COLLATERAL_STATUSES,
    DEPOSIT_CLASSES,
    FORECAST_BASES,
    FORECAST_CYCLE_LABELS,
    FORECAST_STATUSES,
    FUNDING_STATUSES,
    PLEDGING_MODES,
    POOL_PRIORITY_RANK_BY_UNIT_TYPE,
    POOL_PRIORITY_RANK_DEFAULT,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_STATE_REGULATOR,
    ROLE_SYSTEM_OPERATOR,
)
from errors import fail
from response import list_response, object_response, record_response
from services import calc, state

bp = Blueprint("accounts", __name__)

ACCOUNT_READ_ROLES = (
    ROLE_STATE_REGULATOR,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_SYSTEM_OPERATOR,
)


def _next_group_sequence(public_unit_id, depository_id, deposit_class):
    highest = 0
    for account in db.rows("deposit_accounts"):
        if account["public_unit_id"] != public_unit_id:
            continue
        if account["depository_id"] != depository_id:
            continue
        if account["deposit_class"] != deposit_class:
            continue
        highest = max(highest, account["group_sequence"])
    return highest + 1


@bp.post("/deposit-accounts")
def open_account():
    user_id, _ = mw.authorize(ROLE_PUBLIC_UNIT_TREASURER)
    body = mw.body_json()
    claimed_unit = body.get("public_unit_id")
    if isinstance(claimed_unit, str) and claimed_unit.strip() and claimed_unit != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    depository = mw.resolve_fk("depositories", body.get("depository_id"))
    unit = mw.resolve_fk("public_units", claimed_unit)
    mw.req_id(body, "depository_id")
    mw.req_id(body, "public_unit_id")
    deposit_class = mw.req_enum(body, "deposit_class", DEPOSIT_CLASSES)
    pledging_mode = mw.req_enum(body, "pledging_mode", PLEDGING_MODES)
    if depository["approval_status"] != "APPROVED":
        fail("ERR_DEPOSITORY_NOT_APPROVED")
    if depository["collateral_posture"] == "FROZEN":
        fail("ERR_DEPOSITORY_POSTURE_FROZEN")
    if depository["risk_grade"] == "D":
        fail("ERR_DEPOSITORY_RISK_GRADE_BLOCKED")
    if pledging_mode != unit["collateral_program_preference"]:
        fail("ERR_PLEDGING_MODE_MISMATCH")
    if pledging_mode == "POOLED" and depository["pooled_program_id"] is None:
        fail("ERR_PLEDGING_MODE_MISMATCH")
    record = db.new_record(
        {
            "depository_id": depository["id"],
            "public_unit_id": unit["id"],
            "deposit_class": deposit_class,
            "pledging_mode": pledging_mode,
            "group_sequence": _next_group_sequence(unit["id"], depository["id"], deposit_class),
            "ledger_balance_cents": 0,
            "insured_amount_cents": 0,
            "uninsured_amount_cents": 0,
            "required_collateral_pct_bps": 0,
            "required_collateral_cents": 0,
            "assigned_collateral_value_cents": 0,
            "pooled_allocated_collateral_cents": 0,
            "coverage_ratio_bps": 10000,
            "pool_priority_rank": POOL_PRIORITY_RANK_BY_UNIT_TYPE.get(
                unit["unit_type"], POOL_PRIORITY_RANK_DEFAULT
            ),
            "funding_status": "PENDING_FUNDING",
            "collateral_status": "UNSECURED",
            "restricted_reason": None,
        }
    )
    db.insert("deposit_accounts", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/deposit-accounts/<account_id>")
def read_account(account_id):
    mw.authorize(*ACCOUNT_READ_ROLES)
    return record_response(mw.resolve("deposit_accounts", account_id))


@bp.get("/deposit-accounts")
def list_accounts():
    mw.authorize(*ACCOUNT_READ_ROLES)
    limit, offset = mw.page_params()
    depository_id = mw.query_filter("depository_id")
    public_unit_id = mw.query_filter("public_unit_id")
    deposit_class = mw.query_filter("deposit_class", DEPOSIT_CLASSES)
    funding_status = mw.query_filter("funding_status", FUNDING_STATUSES)
    collateral_status = mw.query_filter("collateral_status", COLLATERAL_STATUSES)
    records = db.rows("deposit_accounts")
    if depository_id is not None:
        records = [r for r in records if r["depository_id"] == depository_id]
    if public_unit_id is not None:
        records = [r for r in records if r["public_unit_id"] == public_unit_id]
    if deposit_class is not None:
        records = [r for r in records if r["deposit_class"] == deposit_class]
    if funding_status is not None:
        records = [r for r in records if r["funding_status"] == funding_status]
    if collateral_status is not None:
        records = [r for r in records if r["collateral_status"] == collateral_status]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/deposit-accounts/<account_id>/deposits")
def credit_deposit(account_id):
    user_id, _ = mw.authorize(ROLE_PUBLIC_UNIT_TREASURER)
    account = mw.resolve("deposit_accounts", account_id)
    if account["public_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    body = mw.body_json()
    amount = mw.req_int(body, "amount_cents")
    if account["funding_status"] not in ("PENDING_FUNDING", "FUNDED"):
        fail("ERR_INVALID_STATE")
    depository = db.get("depositories", account["depository_id"])
    if depository is None or depository["approval_status"] != "APPROVED":
        fail("ERR_DEPOSITORY_NOT_APPROVED")
    unit = db.get("public_units", account["public_unit_id"])
    if unit is not None:
        if unit["total_deposit_balance_cents"] + amount > unit["statutory_max_deposit_cents"]:
            fail("ERR_STATUTORY_DEPOSIT_LIMIT")
    before = state.snapshot_accounts()
    account["ledger_balance_cents"] = account["ledger_balance_cents"] + amount
    if account["funding_status"] == "PENDING_FUNDING":
        account["funding_status"] = "FUNDED"
    state.recompute_all(apply_status=True)
    db.touch(account)
    state.version_changed_accounts(before, skip_ids=(account["id"],))
    return record_response(account)


@bp.post("/deposit-accounts/<account_id>/withdrawals")
def debit_withdrawal(account_id):
    user_id, _ = mw.authorize(ROLE_PUBLIC_UNIT_TREASURER)
    account = mw.resolve("deposit_accounts", account_id)
    if account["public_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    body = mw.body_json()
    amount = mw.req_int(body, "amount_cents")
    if account["funding_status"] != "FUNDED":
        fail("ERR_INVALID_STATE")
    depository = db.get("depositories", account["depository_id"])
    if depository is None or depository["approval_status"] != "APPROVED":
        fail("ERR_DEPOSITORY_NOT_APPROVED")
    if amount > account["ledger_balance_cents"]:
        fail("ERR_INSUFFICIENT_LEDGER_BALANCE")
    before = state.snapshot_accounts()
    account["ledger_balance_cents"] = account["ledger_balance_cents"] - amount
    state.recompute_all(apply_status=True)
    db.touch(account)
    state.version_changed_accounts(before, skip_ids=(account["id"],))
    return record_response(account)


@bp.get("/deposit-accounts/<account_id>/coverage-report")
def coverage_report(account_id):
    user_id, role = mw.authorize(
        ROLE_STATE_REGULATOR, ROLE_PUBLIC_UNIT_TREASURER, ROLE_BANK_COMPLIANCE_OFFICER
    )
    account = mw.resolve("deposit_accounts", account_id)
    if role == ROLE_PUBLIC_UNIT_TREASURER and account["public_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    depository = db.get("depositories", account["depository_id"])
    basis = depository["insurance_determination_basis"] if depository else None
    return object_response(
        {
            "insured_amount_cents": account["insured_amount_cents"],
            "uninsured_amount_cents": account["uninsured_amount_cents"],
            "required_collateral_pct_bps": account["required_collateral_pct_bps"],
            "required_collateral_cents": account["required_collateral_cents"],
            "assigned_collateral_value_cents": account["assigned_collateral_value_cents"],
            "coverage_ratio_bps": account["coverage_ratio_bps"],
            "collateral_status": account["collateral_status"],
            "pledging_mode": account["pledging_mode"],
            "insurance_determination_basis": basis,
            "report_as_of": db.now_text(),
        }
    )


# ------------------------------------------------------------ runoff forecasts
@bp.get("/deposit-accounts/<account_id>/runoff-forecasts")
def list_account_forecasts(account_id):
    mw.authorize(ROLE_STATE_REGULATOR, ROLE_PUBLIC_UNIT_TREASURER, ROLE_BANK_COLLATERAL_OFFICER)
    account = mw.resolve("deposit_accounts", account_id)
    limit, offset = mw.page_params()
    status_filter = mw.query_filter("status", FORECAST_STATUSES)
    cycle_filter = mw.query_filter("cycle_label", FORECAST_CYCLE_LABELS)
    records = state.forecasts_of_account(account["id"])
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    if cycle_filter is not None:
        records = [r for r in records if r["cycle_label"] == cycle_filter]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.get("/runoff-forecasts/<forecast_id>")
def read_forecast(forecast_id):
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_SYSTEM_OPERATOR,
    )
    return record_response(mw.resolve("runoff_forecasts", forecast_id))


def _read_windows(body):
    """Rung 5 shape of projected_windows: a non-empty ordered array of objects."""
    raw = body.get("projected_windows")
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST")
    windows = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST")
        start = mw.req_ts(item, "window_start")
        end = mw.req_ts(item, "window_end")
        balance = mw.req_int(item, "projected_balance_cents")
        windows.append(
            {
                "window_start": start,
                "window_end": end,
                "projected_balance_cents": balance,
            }
        )
    return windows


def _check_window_chain(windows, horizon_start, horizon_end):
    """Rung 23: exactly contiguous and exactly coextensive with the horizon."""
    for window in windows:
        if not window["window_start"].dt < window["window_end"].dt:
            fail("ERR_FORECAST_WINDOW_DISCONTINUITY")
    for index in range(len(windows) - 1):
        if windows[index]["window_end"].dt != windows[index + 1]["window_start"].dt:
            fail("ERR_FORECAST_WINDOW_DISCONTINUITY")
    if windows[0]["window_start"].dt != horizon_start.dt:
        fail("ERR_FORECAST_WINDOW_DISCONTINUITY")
    if windows[-1]["window_end"].dt != horizon_end.dt:
        fail("ERR_FORECAST_WINDOW_DISCONTINUITY")


@bp.post("/runoff-forecasts")
def file_forecast():
    user_id, _ = mw.authorize(ROLE_PUBLIC_UNIT_TREASURER)
    body = mw.body_json()
    account = mw.resolve_fk("deposit_accounts", body.get("deposit_account_id"))
    if account is not None and account["public_unit_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    mw.req_id(body, "deposit_account_id")
    cycle_label = mw.req_enum(body, "cycle_label", FORECAST_CYCLE_LABELS)
    basis = mw.req_enum(body, "basis", FORECAST_BASES)
    horizon_start = mw.req_ts(body, "horizon_start")
    horizon_end = mw.req_ts(body, "horizon_end")
    windows = _read_windows(body)
    expected = mw.req_version(body, "expected_deposit_account_version")
    if expected != account["version"]:
        fail("ERR_STALE_DEPOSIT_ACCOUNT_VERSION")
    if horizon_start.dt >= horizon_end.dt:
        fail("ERR_INVALID_INTERVAL")
    _check_window_chain(windows, horizon_start, horizon_end)

    pct = account["required_collateral_pct_bps"]
    requirements = [
        calc.window_requirement_cents(w["projected_balance_cents"], pct) for w in windows
    ]
    peak_balance = max(w["projected_balance_cents"] for w in windows)
    if basis == "PEAK_WINDOW":
        projected_required = max(requirements)
    else:
        order = sorted(
            range(len(windows)),
            key=lambda i: (windows[i]["window_start"].dt, windows[i]["window_end"].dt),
        )
        projected_required = requirements[order[-1]]
    capacity = calc.unpledged_capacity_cents(state.assets_of_depository(account["depository_id"]))
    record = db.new_record(
        {
            "deposit_account_id": account["id"],
            "cycle_label": cycle_label,
            "basis": basis,
            "horizon_start": horizon_start,
            "horizon_end": horizon_end,
            "projected_windows": windows,
            "projected_peak_balance_cents": peak_balance,
            "projected_required_collateral_cents": projected_required,
            "unpledged_capacity_cents": capacity,
            "pledge_capacity_gap_cents": max(0, projected_required - capacity),
            "status": "OPEN",
            "requires_reforecast": False,
            "superseded_at": None,
        }
    )
    for prior in state.forecasts_of_account(account["id"]):
        if prior["cycle_label"] != cycle_label:
            continue
        if prior["status"] not in ("OPEN", "STALE"):
            continue
        prior["status"] = "SUPERSEDED"
        prior["superseded_at"] = db.now_ts()
        prior["requires_reforecast"] = False
        db.touch(prior)
    db.insert("runoff_forecasts", record)
    db.touch(account)
    state.recompute_all()
    return record_response(record, 201)
