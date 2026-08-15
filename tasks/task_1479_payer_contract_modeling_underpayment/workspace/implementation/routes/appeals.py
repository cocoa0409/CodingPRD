"""Appeal endpoints (PRD §3.7) — the densest guard set in the system."""

from datetime import timedelta

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_appeal_level_mismatch,
    err_appeal_window_closed,
    err_appeal_already_open,
    err_escalation_min_not_met,
    err_escalation_blocked,
    err_recovery_amount_invalid,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_appeal
from services.validation import body, reject_unknown, as_str, as_int
from services.cases import compute_case_ledger
from services.pricing import reevaluate_claim_after_change, touch

bp = Blueprint("appeals", __name__)

RESPONSE_DAYS = {1: 30, 2: 30, 3: 45, 4: 60}
CHANNELS = {1: "INTERNAL_REVIEW", 2: "FORMAL_APPEAL", 3: "MEDIATION", 4: "ARBITRATION"}
ARBITRATION_MIN_OUTSTANDING_CENTS = 100000
# Case status that holds an active appeal at each level
LEVEL_CASE_STATUS = {1: "APPEAL_L1", 2: "APPEAL_L2", 3: "MEDIATION", 4: "ARBITRATION"}
CASE_STATUS_LEVEL = {v: k for k, v in LEVEL_CASE_STATUS.items()}
CASE_TERMINAL = {"RECOVERED", "DENIED_FINAL", "WRITTEN_OFF", "WITHDRAWN"}


def _case_appeals(case_id):
    items = [a for a in _db.store.appeals.values() if a["case_id"] == case_id]
    items.sort(key=lambda a: a["seq"])
    return items


def _most_recent_appeal_at_level(case_id, level, exclude_withdrawn=False):
    cands = [a for a in _case_appeals(case_id) if a["level"] == level]
    if exclude_withdrawn:
        cands = [a for a in cands if a["status"] != "WITHDRAWN"]
    if not cands:
        return None
    return cands[-1]


@bp.post("/api/appeals")
def create_appeal():
    require_roles(["RevenueIntegrityAnalyst", "RecoveryManager"])
    data = body()
    reject_unknown(data, {"case_id", "level"})
    case_id = as_str(data, "case_id")
    level = as_int(data, "level", required=True)
    if level not in {1, 2, 3, 4}:
        raise err_invalid_request("level must be one of 1, 2, 3, 4")

    case = _db.store.cases.get(case_id)
    if case is None:
        raise err_not_found("UnderpaymentCase not found")

    # State (rung 6): valid from-state per level.
    # Level 1: UNDER_REVIEW (or current level == 1 refile when most recent L1 is WITHDRAWN).
    # Level n>1: case sits at LEVEL_CASE_STATUS[n-1] (progression) or at LEVEL_CASE_STATUS[n] (refile).
    status = case["status"]
    esc = case["escalation_level"]
    is_refile = False
    if level == 1:
        if status == "UNDER_REVIEW":
            pass
        elif status == "APPEAL_L1":
            is_refile = True
        else:
            raise err_invalid_state("Case is not in a valid state to open a level-1 appeal")
    else:
        if status == LEVEL_CASE_STATUS[level - 1]:
            pass
        elif status == LEVEL_CASE_STATUS[level]:
            is_refile = True
        else:
            raise err_invalid_state(f"Case is not in a valid state to open a level-{level} appeal")

    # Level match (rung 8): progression => level == esc + 1; refile => level == esc AND
    # most recent appeal at that level is WITHDRAWN.
    if is_refile:
        if level != esc:
            raise err_appeal_level_mismatch()
        recent = _most_recent_appeal_at_level(case_id, level)
        if recent is None or recent["status"] != "WITHDRAWN":
            raise err_appeal_level_mismatch(
                "Same-level refile is allowed only when the most recent appeal at that level is WITHDRAWN"
            )
    else:
        if level != esc + 1:
            raise err_appeal_level_mismatch()

    # Filing window (rung 9)
    payer = _db.store.payers.get(case["payer_id"])
    days = payer["appeal_deadline_days"] if payer else 45
    today = _db.today()
    if level == 1:
        deadline = parse_date(case["queued_date"]) + timedelta(days=days)
        if today > deadline:
            raise err_appeal_window_closed()
    else:
        prior = _most_recent_appeal_at_level(case_id, level - 1, exclude_withdrawn=True)
        if prior is not None and prior.get("outcome_recorded_date") is not None:
            deadline = parse_date(prior["outcome_recorded_date"]) + timedelta(days=days)
            if today > deadline:
                raise err_appeal_window_closed()
        # When no prior-level appeal has a recorded outcome the window check is vacuous.

    # Already-open guard (rung 10)
    for a in _db.store.appeals.values():
        if a["case_id"] == case_id and a["status"] in {"DRAFT", "FILED"}:
            raise err_appeal_already_open()

    # Money guard (rung 11): arbitration minimum
    ledger = compute_case_ledger(case)
    if level == 4 and ledger["current_outstanding_cents"] < ARBITRATION_MIN_OUTSTANDING_CENTS:
        raise err_escalation_min_not_met()

    # Escalation evidence (rung 12): level n > 1 requires the most recent non-WITHDRAWN
    # level-(n-1) appeal outcome IN {DENIED, EXPIRED, PARTIAL_PAYMENT}
    if level > 1 and not is_refile:
        prior = _most_recent_appeal_at_level(case_id, level - 1, exclude_withdrawn=True)
        if prior is None or prior["outcome"] not in {"DENIED", "EXPIRED", "PARTIAL_PAYMENT"}:
            raise err_escalation_blocked()
    elif level > 1 and is_refile:
        # Refiling at the current level after a WITHDRAWN appeal: the evidence rule still
        # references the prior level for n > 1 — but the case already demonstrated it when
        # it first reached this level. Re-check against the prior level to stay faithful to
        # "progression requires the most recent non-WITHDRAWN prior-level appeal outcome".
        prior = _most_recent_appeal_at_level(case_id, level - 1, exclude_withdrawn=True)
        if prior is None or prior["outcome"] not in {"DENIED", "EXPIRED", "PARTIAL_PAYMENT"}:
            raise err_escalation_blocked()

    now = _db.now_iso()
    appeal = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "case_id": case_id,
        "level": level,
        "channel": CHANNELS[level],
        "status": "DRAFT",
        "outcome": "PENDING",
        "filed_date": None,
        "response_due_date": None,
        "outcome_recorded_date": None,
        "recovered_amount_cents": 0,
    }
    _db.store.appeals[appeal["id"]] = appeal

    # Case escalation side effects
    if not is_refile:
        case["escalation_level"] = level
    case["status"] = LEVEL_CASE_STATUS[level]
    touch(case)

    return success_object(serialize_appeal(appeal), status=201)


@bp.get("/api/appeals/<aid>")
def get_appeal(aid):
    require_roles(ALL_ROLES)
    a = _db.store.appeals.get(aid)
    if a is None:
        raise err_not_found("Appeal not found")
    return success_object(serialize_appeal(a))


@bp.get("/api/appeals")
def list_appeals():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    case_id = request.args.get("case_id")
    level = request.args.get("level")
    outcome = request.args.get("outcome")
    if level is not None:
        try:
            level = int(level)
        except (TypeError, ValueError):
            raise err_invalid_request("level filter must be an integer")
    if outcome is not None and outcome not in {"PENDING", "PAID_IN_FULL", "PARTIAL_PAYMENT", "DENIED", "EXPIRED"}:
        raise err_invalid_request("outcome filter invalid")
    items = list(_db.store.appeals.values())
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    if level is not None:
        items = [a for a in items if a["level"] == level]
    if outcome is not None:
        items = [a for a in items if a["outcome"] == outcome]
    items.sort(key=lambda a: a["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_appeal(a) for a in page], limit, offset, total)


def _get_appeal_or_404(aid):
    a = _db.store.appeals.get(aid)
    if a is None:
        raise err_not_found("Appeal not found")
    return a


@bp.post("/api/appeals/<aid>/file")
def file_appeal(aid):
    require_roles(["RevenueIntegrityAnalyst", "RecoveryManager"])
    a = _get_appeal_or_404(aid)
    if a["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT appeal may be filed")
    filed = _db.today()
    a["status"] = "FILED"
    a["filed_date"] = filed.isoformat()
    a["response_due_date"] = (filed + timedelta(days=RESPONSE_DAYS[a["level"]])).isoformat()
    touch(a)
    return success_object(serialize_appeal(a))


@bp.post("/api/appeals/<aid>/record_outcome")
def record_outcome(aid):
    require_roles(["RecoveryManager"])
    a = _get_appeal_or_404(aid)
    data = body()
    reject_unknown(data, {"outcome", "recovered_amount_cents"})
    outcome = as_str(data, "outcome")
    if outcome not in {"PAID_IN_FULL", "PARTIAL_PAYMENT", "DENIED"}:
        raise err_invalid_request("outcome must be PAID_IN_FULL, PARTIAL_PAYMENT, or DENIED")
    recovered_amount_cents = as_int(data, "recovered_amount_cents", required=False, min_value=0)

    if a["status"] != "FILED":
        raise err_invalid_state("Only a FILED appeal may record an outcome")

    case = _db.store.cases.get(a["case_id"])
    ledger = compute_case_ledger(case) if case else {"current_outstanding_cents": 0}

    # Rung 10: recovery amount coherence
    if outcome == "PAID_IN_FULL":
        if recovered_amount_cents is not None:
            raise err_recovery_amount_invalid(
                "PAID_IN_FULL must not carry recovered_amount_cents"
            )
        recovered_amount_cents = ledger["current_outstanding_cents"]
    elif outcome == "PARTIAL_PAYMENT":
        if (
            recovered_amount_cents is None
            or recovered_amount_cents <= 0
            or recovered_amount_cents >= ledger["current_outstanding_cents"]
        ):
            raise err_recovery_amount_invalid(
                "PARTIAL_PAYMENT recovered_amount_cents must be > 0 and < current_outstanding_cents"
            )

    a["status"] = "CLOSED"
    a["outcome"] = outcome
    a["outcome_recorded_date"] = _db.today().isoformat()
    touch(a)

    if outcome in {"PAID_IN_FULL", "PARTIAL_PAYMENT"} and case is not None:
        a["recovered_amount_cents"] = recovered_amount_cents
        # Create APPEAL_RECOVERY remittance on the claim
        claim = _db.store.claims.get(case["claim_id"])
        now = _db.now_iso()
        remit = {
            "id": _db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "seq": _db.store.next_seq(),
            "claim_id": case["claim_id"],
            "appeal_id": a["id"],
            "paid_amount_cents": recovered_amount_cents,
            "remittance_date": _db.today().isoformat(),
            "adjustment_reason_code": "APPEAL_RECOVERY",
            "source": "APPEAL_RECOVERY",
            "status": "POSTED",
        }
        _db.store.remittances[remit["id"]] = remit
        if claim is not None:
            # A recovery payment: restate_original stays False (the recovery is
            # tracked in recovered_to_date_cents; restating original would
            # double-count it against the §3.7 money-ledger invariant), but it
            # is payment-driven so the §3.7 auto-RECOVERED transition may fire.
            reevaluate_claim_after_change(claim, payment_driven=True)
        # Ensure case restatement reflects the recovery even when no auto-transition fires
        touch(case)
    elif outcome == "DENIED" and case is not None:
        if a["level"] == 4 and case["status"] not in CASE_TERMINAL:
            case["status"] = "DENIED_FINAL"
        touch(case)

    return success_object(serialize_appeal(a))


@bp.post("/api/appeals/<aid>/withdraw")
def withdraw_appeal(aid):
    require_roles(["RevenueIntegrityAnalyst", "RecoveryManager"])
    a = _get_appeal_or_404(aid)
    if a["status"] not in {"DRAFT", "FILED"}:
        raise err_invalid_state("Only a DRAFT or FILED appeal may be withdrawn")
    a["status"] = "WITHDRAWN"
    touch(a)
    return success_object(serialize_appeal(a))
