"""Mark-to-market runs, margin calls, the logical clock and the daily sweep."""

from flask import Blueprint

import db
import middleware as mw
from constants import (
    ESCALATION_GRACE_HOURS,
    INTERNAL_TRAILING_RUNS,
    MARGIN_CALL_STATUSES,
    MTM_BASES,
    MTM_MIN_GAP_HOURS,
    MTM_OUTCOMES,
    OPEN_MARGIN_CALL_STATUSES,
    PRICE_STALE_HOURS,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_STATE_REGULATOR,
    ROLE_SYSTEM_OPERATOR,
)
from errors import fail
from response import list_response, object_response, record_response
from routes.collateral import pledgeable
from services import calc, state

bp = Blueprint("margin", __name__)

RUN_READ_ROLES = (
    ROLE_STATE_REGULATOR,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_SYSTEM_OPERATOR,
)


def _runs_of_depository(depository_id):
    return [r for r in db.rows("mtm_runs") if r["depository_id"] == depository_id]


def _check_window(depository, window_start, window_end):
    """Rung 22 — every window failure is reported as ERR_MTM_WINDOW_OVERLAP."""
    if window_start.dt > window_end.dt:
        fail("ERR_MTM_WINDOW_OVERLAP")
    if window_end.dt > db.clock():
        fail("ERR_MTM_WINDOW_OVERLAP")
    prior_runs = _runs_of_depository(depository["id"])
    for prior in prior_runs:
        if window_start.dt <= prior["window_end"].dt and prior["window_start"].dt <= window_end.dt:
            fail("ERR_MTM_WINDOW_OVERLAP")
    if prior_runs:
        previous = max(prior_runs, key=lambda r: r["run_index"])
        gap = db.hours_between(previous["window_end"].dt, window_start.dt)
        if gap < MTM_MIN_GAP_HOURS:
            fail("ERR_MTM_WINDOW_OVERLAP")


def _documentation_counts(depository):
    denominator = 0
    numerator = 0
    pool_documented = False
    pool_id = depository["pooled_program_id"]
    if pool_id is not None:
        for agreement in db.rows("pledge_agreements"):
            if agreement["status"] != "EXECUTED":
                continue
            if agreement["beneficiary_type"] != "POOLED_PROGRAM":
                continue
            if agreement["pooled_program_id"] == pool_id:
                pool_documented = True
                break
    for account in state.accounts_of_depository(depository["id"]):
        if account["funding_status"] not in ("FUNDED", "RESTRICTED"):
            continue
        denominator += 1
        if account["pledging_mode"] == "POOLED":
            if pool_documented:
                numerator += 1
            continue
        for agreement in state.agreements_of_depository(depository["id"]):
            if agreement["status"] != "EXECUTED":
                continue
            if agreement["beneficiary_type"] != "DEPOSIT_ACCOUNT":
                continue
            if agreement["deposit_account_id"] == account["id"]:
                numerator += 1
                break
    return numerator, denominator


@bp.post("/depositories/<depository_id>/mtm-runs")
def execute_run(depository_id):
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER, ROLE_STATE_REGULATOR)
    depository = mw.resolve("depositories", depository_id)
    body = mw.body_json()
    window_start = mw.req_ts(body, "window_start")
    window_end = mw.req_ts(body, "window_end")
    basis = mw.req_enum(body, "basis", MTM_BASES)
    expected = mw.req_version(body, "expected_depository_version")
    if expected != depository["version"]:
        fail("ERR_STALE_DEPOSITORY_VERSION")
    if depository["approval_status"] == "DENIED":
        fail("ERR_INVALID_STATE")
    _check_window(depository, window_start, window_end)

    # Step one — snapshot, held for the whole run.
    snapshot = depository["consecutive_deficiency_runs"]
    as_of = db.now_ts()
    run_index = depository["mtm_run_index"] + 1
    surcharge = calc.deficiency_surcharge_bps(snapshot)

    # Step two — re-derive every account against the snapshot.
    state.recompute_all(counter_override={depository["id"]: snapshot})

    # Step three — totals.
    total_required = 0
    for account in state.accounts_of_depository(depository["id"]):
        if account["funding_status"] in ("FUNDED", "RESTRICTED"):
            total_required += account["required_collateral_cents"]
    total_value = 0
    for agreement in state.agreements_of_depository(depository["id"]):
        if agreement["status"] != "EXECUTED":
            continue
        for allocation in state.allocations_of_agreement(agreement["id"]):
            if allocation["status"] != "ACTIVE":
                continue
            if not calc.covers(allocation, as_of.dt):
                continue
            asset = db.get("collateral_assets", allocation["collateral_asset_id"])
            if asset is None or asset["eligibility_status"] != "ELIGIBLE":
                continue
            total_value += allocation["allocated_collateral_value_cents"]

    # Steps four and five.
    deficiency = max(0, total_required - total_value)
    deficiency_ratio = calc.deficiency_ratio_bps(deficiency, total_required)
    outcome = "DEFICIENT" if deficiency > 0 else "SUFFICIENT"

    run = db.new_record(
        {
            "depository_id": depository["id"],
            "run_index": run_index,
            "window_start": window_start,
            "window_end": window_end,
            "as_of": as_of,
            "basis": basis,
            "deficiency_surcharge_bps_applied": surcharge,
            "total_required_collateral_cents": total_required,
            "total_collateral_value_cents": total_value,
            "deficiency_cents": deficiency,
            "deficiency_ratio_bps": deficiency_ratio,
            "outcome": outcome,
            "coverage_component_bps": 0,
            "volatility_component_bps": 0,
            "documentation_component_bps": 0,
            "risk_score_bps": 0,
            "risk_grade_assigned": "A",
        },
        versioned=False,
    )

    # Step six — the only writes to the deficiency counter in the service.
    if outcome == "DEFICIENT":
        depository["consecutive_deficiency_runs"] = snapshot + 1
        cure_deadline = as_of.plus_hours(calc.cure_window_hours(deficiency_ratio))
        call = db.new_record(
            {
                "depository_id": depository["id"],
                "mtm_run_id": run["id"],
                "required_cure_cents": deficiency,
                "cured_cents": 0,
                "outstanding_cents": deficiency,
                "cure_deadline_at": cure_deadline,
                "escalated_at": None,
                "breach_deadline_at": cure_deadline.plus_hours(ESCALATION_GRACE_HOURS),
                "cured_at": None,
                "status": "ISSUED",
            }
        )
        db.insert("margin_calls", call)
    else:
        depository["consecutive_deficiency_runs"] = 0
    depository["mtm_run_index"] = run_index
    depository["last_mtm_window_end"] = window_end

    # Step seven — components and the weighted grade.
    coverage_component = calc.coverage_component_bps(total_value, total_required)
    volatility_component = calc.volatility_component_bps(
        depository["consecutive_deficiency_runs"]
    )
    numerator, denominator = _documentation_counts(depository)
    documentation_component = calc.documentation_component_bps(numerator, denominator)
    run["coverage_component_bps"] = coverage_component
    run["volatility_component_bps"] = volatility_component
    run["documentation_component_bps"] = documentation_component
    if basis == "INTERNAL":
        trailing = sorted(
            _runs_of_depository(depository["id"]), key=lambda r: r["run_index"], reverse=True
        )[: INTERNAL_TRAILING_RUNS - 1]
        coverage_input = calc.mean_bps(
            [coverage_component] + [r["coverage_component_bps"] for r in trailing]
        )
        volatility_input = calc.mean_bps(
            [volatility_component] + [r["volatility_component_bps"] for r in trailing]
        )
        documentation_input = calc.mean_bps(
            [documentation_component] + [r["documentation_component_bps"] for r in trailing]
        )
    else:
        coverage_input = coverage_component
        volatility_input = volatility_component
        documentation_input = documentation_component
    score = calc.risk_score_bps(coverage_input, volatility_input, documentation_input)
    run["risk_score_bps"] = score
    run["risk_grade_assigned"] = calc.risk_grade_for(score)
    depository["risk_score_bps"] = score
    depository["risk_grade"] = run["risk_grade_assigned"]

    depository["open_margin_call_count"] = sum(
        1
        for existing in state.margin_calls_of_depository(depository["id"])
        if existing["status"] in OPEN_MARGIN_CALL_STATUSES
    )
    depository["collateral_posture"] = state.derive_posture(depository)
    db.touch(depository)
    db.insert("mtm_runs", run)
    return record_response(run, 201)


@bp.get("/depositories/<depository_id>/mtm-runs")
def list_runs(depository_id):
    mw.authorize(*RUN_READ_ROLES)
    depository = mw.resolve("depositories", depository_id)
    limit, offset = mw.page_params()
    basis = mw.query_filter("basis", MTM_BASES)
    outcome = mw.query_filter("outcome", MTM_OUTCOMES)
    records = _runs_of_depository(depository["id"])
    if basis is not None:
        records = [r for r in records if r["basis"] == basis]
    if outcome is not None:
        records = [r for r in records if r["outcome"] == outcome]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.get("/mtm-runs/<run_id>")
def read_run(run_id):
    mw.authorize(*RUN_READ_ROLES)
    return record_response(mw.resolve("mtm_runs", run_id))


# ------------------------------------------------------------------ margin calls
@bp.get("/margin-calls/<call_id>")
def read_call(call_id):
    mw.authorize(*RUN_READ_ROLES)
    return record_response(mw.resolve("margin_calls", call_id))


@bp.get("/margin-calls")
def list_calls():
    mw.authorize(*RUN_READ_ROLES)
    limit, offset = mw.page_params()
    depository_id = mw.query_filter("depository_id")
    run_id = mw.query_filter("mtm_run_id")
    status_filter = mw.query_filter("status", MARGIN_CALL_STATUSES)
    records = db.rows("margin_calls")
    if depository_id is not None:
        records = [r for r in records if r["depository_id"] == depository_id]
    if run_id is not None:
        records = [r for r in records if r["mtm_run_id"] == run_id]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


def _credited_allocations(body):
    raw = body.get("credited_allocation_ids")
    # Rung 5 requires the field to be present and well shaped. The PRD singles
    # out only `projected_windows` as needing to be non-empty, so an empty
    # `credited_allocation_ids` array is shape-valid and simply credits zero.
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST")
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            fail("ERR_INVALID_REQUEST")
    return [mw.resolve("pledge_allocations", item) for item in raw]


@bp.post("/margin-calls/<call_id>/cure")
def cure_call(call_id):
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    call = mw.resolve("margin_calls", call_id)
    body = mw.body_json()
    offered = _credited_allocations(body)
    if call["status"] not in OPEN_MARGIN_CALL_STATUSES:
        fail("ERR_INVALID_STATE")
    for allocation in offered:
        asset = db.get("collateral_assets", allocation["collateral_asset_id"])
        if asset is None or not pledgeable(asset):
            fail("ERR_COLLATERAL_TYPE_INELIGIBLE")
    if db.clock() >= call["breach_deadline_at"].dt:
        fail("ERR_CURE_WINDOW_CLOSED")
    run = db.get("mtm_runs", call["mtm_run_id"])
    for allocation in offered:
        if allocation["status"] != "ACTIVE":
            fail("ERR_CURE_ALLOCATION_INELIGIBLE")
        agreement = db.get("pledge_agreements", allocation["pledge_agreement_id"])
        if agreement is None or agreement["status"] != "EXECUTED":
            fail("ERR_CURE_ALLOCATION_INELIGIBLE")
        if agreement["depository_id"] != call["depository_id"]:
            fail("ERR_CURE_ALLOCATION_INELIGIBLE")
        if run is not None and not allocation["created_at"].dt > run["as_of"].dt:
            fail("ERR_CURE_ALLOCATION_INELIGIBLE")
    credited = sum(a["allocated_collateral_value_cents"] for a in offered)
    if credited > call["outstanding_cents"]:
        fail("ERR_CURE_EXCEEDS_OUTSTANDING")
    call["cured_cents"] = call["cured_cents"] + credited
    call["outstanding_cents"] = max(0, call["required_cure_cents"] - call["cured_cents"])
    if call["outstanding_cents"] == 0:
        call["status"] = "CURED"
        call["cured_at"] = db.now_ts()
    elif call["status"] == "ISSUED":
        call["status"] = "PARTIALLY_CURED"
    db.touch(call)
    state.recompute_all(apply_status=True)
    return record_response(call)


# ------------------------------------------------------- operator-only endpoints
@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.authorize(ROLE_SYSTEM_OPERATOR)
    body = mw.body_json()
    stamp = mw.req_ts(body, "to_iso8601")
    db.set_clock(stamp.dt)
    state.recompute_all()
    return object_response({"current_utc": db.now_text()})


@bp.post("/_ops/run-daily-cycle")
def run_daily_cycle():
    mw.authorize(ROLE_SYSTEM_OPERATOR)
    moment = db.clock()
    escalated = 0
    breached = 0
    suspended = 0
    for call in db.rows("margin_calls"):
        if call["status"] in ("ISSUED", "PARTIALLY_CURED"):
            if moment >= call["cure_deadline_at"].dt and moment < call["breach_deadline_at"].dt:
                call["status"] = "ESCALATED"
                call["escalated_at"] = db.now_ts()
                call["breach_deadline_at"] = call["escalated_at"].plus_hours(
                    ESCALATION_GRACE_HOURS
                )
                db.touch(call)
                escalated += 1
                continue
        if call["status"] == "ESCALATED" and moment >= call["breach_deadline_at"].dt:
            call["status"] = "BREACHED"
            db.touch(call)
            breached += 1
            depository = db.get("depositories", call["depository_id"])
            if depository is not None:
                if depository["approval_status"] == "APPROVED":
                    state.suspend_depository_cascade(depository)
                    suspended += 1
                depository["_frozen_by_breach"] = True
                depository["collateral_posture"] = "FROZEN"
    stale_assets = 0
    for asset in db.rows("collateral_assets"):
        if calc.hours_stale(asset["priced_at"]) > PRICE_STALE_HOURS:
            stale_assets += 1
    state.recompute_all()
    return object_response(
        {
            "escalated_margin_call_count": escalated,
            "breached_margin_call_count": breached,
            "suspended_depository_count": suspended,
            "stale_priced_asset_count": stale_assets,
            "current_utc": db.now_text(),
        }
    )
