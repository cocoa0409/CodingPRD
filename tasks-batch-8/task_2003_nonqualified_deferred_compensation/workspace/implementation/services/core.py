"""Shared machinery: input validation, serialization, computed fields,
cascades, and the clock sweep."""
from datetime import date, timedelta

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATE_RANGE,
    ERR_NOT_FOUND,
    raise_err,
)
from util import CLOCK, parse_date, parse_ts, add_months


# ---------------------------------------------------------------------------
# Input validation helpers (pipeline stage 1: well-formedness)
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body as a dict; missing/invalid -> 400."""
    from flask import request

    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise_err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _is_bool(v):
    return isinstance(v, bool)


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return v


def req_int(data, field, lo=None, hi=None):
    v = data.get(field)
    if _is_bool(v) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an integer")
    if lo is not None and v < lo:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is below its minimum")
    if hi is not None and v > hi:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' exceeds its maximum")
    return v


def opt_int(data, field, lo=None, hi=None):
    v = data.get(field)
    if v is None:
        return None
    return req_int(data, field, lo, hi)


def req_bool(data, field):
    v = data.get(field)
    if not _is_bool(v):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a boolean")
    return v


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_bool(v):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean")
    return v


def req_date(data, field):
    v = data.get(field)
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO date string YYYY-MM-DD")


def opt_date(data, field):
    v = data.get(field)
    if v is None:
        return None
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO date string YYYY-MM-DD")


def req_enum(data, field, members):
    v = data.get(field)
    if not isinstance(v, str) or v not in members:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(members)}")
    return v


def opt_enum(data, field, members, default=None):
    v = data.get(field)
    if v is None:
        return default
    return req_enum(data, field, members)


def req_string_list(data, field, members=None, non_empty=False):
    v = data.get(field)
    if not isinstance(v, list):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an array")
    if non_empty and not v:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a non-empty array")
    for item in v:
        if not isinstance(item, str):
            raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must contain only strings")
        if members is not None and item not in members:
            raise_err(ERR_INVALID_REQUEST, f"Field '{field}' contains an invalid member '{item}'")
    return list(v)


# ---------------------------------------------------------------------------
# Existence helpers (pipeline stage 5)
# ---------------------------------------------------------------------------

def get_or_404(table, rid, label="Resource"):
    rec = table.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, f"{label} '{rid}' not found")
    return rec


# ---------------------------------------------------------------------------
# Common field handling
# ---------------------------------------------------------------------------

def stamp_new(rec):
    ts = CLOCK.stamp()
    rec["id"] = db.new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = CLOCK.stamp()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Computed fields: balances, vesting, posture
# ---------------------------------------------------------------------------

def account_entries(account_id):
    entries = [e for e in db.ledger_entries.values() if e["account_id"] == account_id]
    entries.sort(key=lambda e: e["created_at"])
    return entries


def recompute_account_balances(account):
    """Replay the account's ledger (created_at ASC) and refresh the three
    balance variants in place. Vesting is evaluated against the clock."""
    entries = account_entries(account["id"])
    settled = sum(e["amount_cents"] for e in entries if e["entry_status"] == "POSTED")
    provisional = sum(e["amount_cents"] for e in entries if e["entry_status"] in ("POSTED", "PENDING"))
    account["settled_balance_cents"] = settled
    account["provisional_balance_cents"] = provisional
    account["vested_balance_cents"] = vested_balance(account)


def vested_bp_for(participant, plan):
    service_days = (CLOCK.date() - parse_date(participant["hire_date"])).days
    service_thousandths = (service_days * 1000) // 365
    if service_thousandths >= plan["vesting_cliff_years"] * 1000:
        return 10000
    return 0


def vested_balance(account):
    participant = db.participants.get(account["participant_id"])
    plan = db.plans.get(account["plan_id"])
    if participant is None or plan is None:
        return 0
    bp = vested_bp_for(participant, plan)
    return (account["settled_balance_cents"] * bp) // 10000


def recompute_plan_posture(plan):
    findings = [f for f in db.document_findings.values() if f["plan_id"] == plan["id"]]
    has_lapsed = any(f["status"] == "LAPSED" for f in findings)
    open_count = sum(1 for f in findings if f["status"] in ("REPORTED", "CORRECTION_FILED"))
    plan["open_findings_count"] = open_count
    if has_lapsed:
        plan["document_posture"] = "LAPSED_FAILURE"
    elif open_count > 0:
        plan["document_posture"] = "FAILURE_OPEN"
    else:
        plan["document_posture"] = "COMPLIANT"


def recompute_trust(trust):
    from util import ceil_div_nonnegative

    trust["assets_cents"] = sum(ev["amount_cents"] for ev in trust["funding_events"])
    total_vested = 0
    for acct in db.accounts.values():
        if acct["plan_id"] == trust["plan_id"] and acct["status"] in ("ACTIVE", "FLAGGED_FOR_INCLUSION"):
            total_vested += acct["vested_balance_cents"]
    effective_bp = 12500 if trust["cic_funding_required"] else trust["funding_target_bp"]
    target_cents = ceil_div_nonnegative(total_vested * effective_bp, 10000)
    trust["required_funding_cents"] = max(0, target_cents - trust["assets_cents"])
    assets = trust["assets_cents"]
    if assets == 0:
        trust["posture"] = "UNFUNDED"
    elif target_cents > 0 and assets >= target_cents:
        trust["posture"] = "FUNDED"
    elif target_cents == 0 and assets > 0:
        trust["posture"] = "FUNDED"
    else:
        trust["posture"] = "UNDERFUNDED"


def recompute_trusts_for_plan(plan_id):
    for trust in db.rabbi_trusts.values():
        if trust["plan_id"] == plan_id:
            recompute_trust(trust)


def recompute_avg_fraction(case):
    records = case["service_records"]
    if not records:
        case["computed_avg_fraction_bp"] = None
        return
    total_weighted = 0
    total_days = 0
    for r in records:
        days = (parse_date(r["period_end"]) - parse_date(r["period_start"])).days
        total_weighted += r["service_fraction_bp"] * days
        total_days += days
    case["computed_avg_fraction_bp"] = total_weighted // total_days if total_days > 0 else None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def void_open_elections_for_participant(participant_id):
    for el in db.deferral_elections.values():
        if el["participant_id"] == participant_id and el["status"] in ("DRAFT", "SUBMITTED"):
            el["status"] = "VOIDED"
            touch(el)


def void_open_elections_for_plan(plan_id):
    for el in db.deferral_elections.values():
        if el["plan_id"] == plan_id and el["status"] in ("DRAFT", "SUBMITTED"):
            el["status"] = "VOIDED"
            touch(el)


def account_close_cascade(account):
    """Account -> CLOSED; sibling distribution requests in pre-terminal states
    -> CANCELLED."""
    account["status"] = "CLOSED"
    touch(account)
    for req in db.distribution_requests.values():
        if req["account_id"] == account["id"] and req["status"] in (
            "REQUESTED",
            "EVENT_VERIFIED",
            "SCHEDULED",
            "PAYABLE",
            "ON_HOLD",
        ):
            req["status"] = "CANCELLED"
            touch(req)


# ---------------------------------------------------------------------------
# scheduled_payment_date calculation (PRD section 3.5)
# ---------------------------------------------------------------------------

def compute_scheduled_payment_date(req):
    account = db.accounts[req["account_id"]]
    plan = db.plans[account["plan_id"]]
    participant = db.participants[account["participant_id"]]
    lag = plan["processing_lag_days"]
    et = req["event_type"]

    if et == "SEPARATION":
        case = db.separation_cases[req["separation_case_id"]]
        sep_date = parse_date(case["alleged_separation_date"])
        base = sep_date + timedelta(days=lag)
        if plan["six_month_delay_enabled"] and participant["is_specified_employee"]:
            # separation_date comes from the participant record (set at determination);
            # fall back to the case's alleged date when the participant record
            # was reset (e.g., reopen recompute happens after re-separation).
            sep = participant.get("separation_date") or case["alleged_separation_date"]
            delay_floor = add_months(parse_date(sep), 6)
            return max(base, delay_floor)
        return base
    if et == "FIXED_TIME":
        return parse_date(req["fixed_date"])
    if et == "CHANGE_IN_CONTROL":
        cic = db.change_in_control_events[req["change_in_control_event_id"]]
        return parse_date(cic["effective_date"]) + timedelta(days=lag)
    # DEATH | DISABILITY | UNFORESEEABLE_EMERGENCY
    return parse_date(req["verified_at"]) + timedelta(days=lag)


# ---------------------------------------------------------------------------
# Clock sweep (PRD section 2.6) — pinned order (1)-(4)
# ---------------------------------------------------------------------------

def run_sweep():
    # (1) Election windows open/close with election lock/expire effects
    today = CLOCK.date()
    for window in sorted(db.election_windows.values(), key=lambda w: w["created_at"]):
        if window["status"] == "SCHEDULED" and today >= parse_date(window["general_open_date"]):
            window["status"] = "OPEN"
            touch(window)
        if window["status"] == "OPEN" and today > parse_date(window["general_close_date"]):
            window["status"] = "CLOSED"
            touch(window)
            for el in db.deferral_elections.values():
                if el["election_window_id"] == window["id"] and el["election_type"] == "GENERAL":
                    if el["status"] == "DRAFT":
                        el["status"] = "EXPIRED"
                        touch(el)
                    elif el["status"] == "SUBMITTED":
                        el["status"] = "LOCKED"
                        el["locked_at"] = CLOCK.stamp()
                        touch(el)

    # Type-specific lock/expire for NEWLY_ELIGIBLE and PERFORMANCE elections
    for el in sorted(db.deferral_elections.values(), key=lambda e: e["created_at"]):
        if el["status"] not in ("DRAFT", "SUBMITTED"):
            continue
        participant = db.participants.get(el["participant_id"])
        window = db.election_windows.get(el["election_window_id"])
        deadline = None
        if el["election_type"] == "NEWLY_ELIGIBLE" and participant is not None:
            deadline = parse_date(participant["initial_eligibility_date"]) + timedelta(days=30)
        elif el["election_type"] == "PERFORMANCE" and window is not None and window.get("performance_period_end"):
            deadline = add_months(parse_date(window["performance_period_end"]), -6)
        if deadline is not None and today > deadline:
            if el["status"] == "DRAFT":
                el["status"] = "EXPIRED"
                touch(el)
            elif el["status"] == "SUBMITTED":
                el["status"] = "LOCKED"
                el["locked_at"] = CLOCK.stamp()
                touch(el)

    # (2) Document findings lapse
    for finding in sorted(db.document_findings.values(), key=lambda f: f["created_at"]):
        if finding["status"] in ("REPORTED", "CORRECTION_FILED") and today > parse_date(finding["correction_deadline"]):
            finding["status"] = "LAPSED"
            touch(finding)
            plan = db.plans.get(finding["plan_id"])
            if plan is not None:
                recompute_plan_posture(plan)

    # (3) Plans finalize termination
    for plan in sorted(db.plans.values(), key=lambda p: p["created_at"]):
        if plan["status"] == "TERMINATION_PENDING" and plan.get("termination_effective_date"):
            if today >= parse_date(plan["termination_effective_date"]):
                plan["status"] = "TERMINATED"
                touch(plan)

    # (4) Scheduled distributions become payable
    for req in sorted(db.distribution_requests.values(), key=lambda r: r["created_at"]):
        if req["status"] == "SCHEDULED" and req.get("scheduled_payment_date"):
            if today >= parse_date(req["scheduled_payment_date"]):
                req["status"] = "PAYABLE"
                touch(req)
