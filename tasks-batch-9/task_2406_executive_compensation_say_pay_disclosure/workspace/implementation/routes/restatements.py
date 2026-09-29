"""Restatements, clawback determinations and recovery (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
from db import apply_changes, insert, now, ordered, sec, store, touch
from errors import ApiError
from middleware import (
    ROLE_CHAIR,
    ROLE_COMP_CONSULTANT,
    ROLE_COUNSEL,
    ROLE_OFFICER,
    authenticate,
)
from response import object_response
from routes.common import fetch, paginated
from services import domain
from validation import Body, bad

bp = Blueprint("restatements", __name__)

LIVE_EVENT_STATUSES = ("DECLARED", "ANALYZED", "RECOVERY_ORDERED")
COLLISION_BUFFER = timedelta(days=1)
RECOVERABLE_VEHICLES = ("ANNUAL_INCENTIVE", "LONG_TERM_PSU")


# ---------------------------------------------------------------------------
# RestatementEvent
# ---------------------------------------------------------------------------
@bp.post("/exec-comp/companies/<cid>/restatement-events")
def declare_event(cid):
    authenticate([ROLE_COUNSEL])
    company = fetch("companies", cid)
    body = Body()
    restatement_date = body.instant("restatement_date", required=True)
    lookback_start = body.instant("lookback_start", required=True)
    lookback_end = body.instant("lookback_end", required=True)
    accounting_reason = body.string(
        "accounting_reason", required=True, min_len=1, max_len=500
    )
    if sec(lookback_end) <= sec(lookback_start):
        bad("lookback_end must be strictly after lookback_start")
    if sec(restatement_date) < sec(lookback_end):
        bad("restatement_date must fall at or after lookback_end")

    for rival in domain.company_events(company["id"]):
        if rival["status"] not in LIVE_EVENT_STATUSES:
            continue
        if sec(lookback_start) <= sec(rival["lookback_end"]) + COLLISION_BUFFER and sec(
            lookback_end
        ) >= sec(rival["lookback_start"]) - COLLISION_BUFFER:
            raise ApiError("ERR_LOOKBACK_PERIOD_COLLISION")

    event = insert(
        store.restatement_events,
        {
            "company_id": company["id"],
            "restatement_date": restatement_date,
            "lookback_start": lookback_start,
            "lookback_end": lookback_end,
            "accounting_reason": accounting_reason,
            "status": "DECLARED",
            "determination_count": 0,
            "recoverable_total_usd": calc.money(0),
            "recovered_total_usd": calc.money(0),
        },
    )
    return object_response(event, 201)


def _restated_results(body):
    """Validate the restated_metric_results array (ladder step 6)."""
    rows = body.array("restated_metric_results", required=True)
    parsed = []
    for entry in rows:
        if not isinstance(entry, dict):
            bad("restated_metric_results entries must be objects")
        metric_id = entry.get("incentive_metric_id")
        if not isinstance(metric_id, str) or not metric_id.strip():
            bad("incentive_metric_id is required on every restated result")
        value = entry.get("restated_achieved_value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad("restated_achieved_value must be a number")
        parsed.append((metric_id, calc.dec(value)))
    return parsed


@bp.post("/exec-comp/restatement-events/<eid>/analyze")
def analyze_event(eid):
    authenticate([ROLE_COUNSEL])
    event = fetch("restatement_events", eid)
    body = Body()
    results = _restated_results(body)

    if event["status"] != "DECLARED":
        raise ApiError("ERR_EVENT_STATE_INVALID")

    company_program_ids = {
        p["id"]
        for p in store.pay_programs.values()
        if p["issuer_company_id"] == event["company_id"]
    }
    targets = []
    for metric_id, restated_value in results:
        metric = store.incentive_metrics.get(metric_id)
        if metric is None or metric["pay_program_id"] not in company_program_ids:
            raise ApiError("ERR_METRIC_NOT_CERTIFIED")
        if metric["status"] != "CERTIFIED":
            raise ApiError("ERR_METRIC_NOT_CERTIFIED")
        targets.append((metric, restated_value))

    # L1 — restate the named metrics.
    for metric, restated_value in targets:
        factor = calc.metric_payout_factor(metric, restated_value)
        apply_changes(
            metric,
            {"restated_payout_factor_pct": factor, "status": "RESTATED"},
        )

    # L2 — one determination per over-paid in-scope award.
    scope = []
    for award in store.payout_awards.values():
        if award["pay_program_id"] not in company_program_ids:
            continue
        if award["vehicle"] not in RECOVERABLE_VEHICLES:
            continue
        if award["status"] != "VESTED":
            continue
        settled = award["settlement_date"]
        if settled is None:
            continue
        if sec(settled) < sec(event["lookback_start"]) or sec(settled) > sec(
            event["lookback_end"]
        ):
            continue
        scope.append(award)
    scope.sort(key=lambda a: (a["settlement_date"], a["created_at"], a["_seq"]))

    created = 0
    recoverable_total = calc.dec(0)
    for award in scope:
        program = store.pay_programs[award["pay_program_id"]]
        vehicle_metrics = domain.program_metrics(program["id"], award["vehicle"])
        original = award["certified_factor_pct"]
        restated = calc.restated_vehicle_factor(vehicle_metrics)
        if restated is None:
            restated = original
        if original is None:
            original = calc.money(0)
        restated_amount, recoverable = calc.clawback_amounts(
            award["realized_value_usd"], original, restated
        )
        if recoverable <= 0:
            continue
        insert(
            store.clawback_determinations,
            {
                "restatement_event_id": event["id"],
                "payout_award_id": award["id"],
                "original_factor_pct": calc.money(original),
                "restated_factor_pct": calc.money(restated),
                "restated_amount_usd": restated_amount,
                "recoverable_amount_usd": recoverable,
                "status": "CALCULATED",
                "noticed_at": None,
                "acknowledged_at": None,
                "acknowledged_by_user_id": None,
                "recovered_at": None,
            },
        )
        created += 1
        recoverable_total += calc.dec(recoverable)

    # L3 — roll the totals up onto the event.
    apply_changes(
        event,
        {
            "determination_count": created,
            "recoverable_total_usd": calc.money(recoverable_total),
            "status": "ANALYZED",
        },
    )
    touch(event)
    return object_response(event)


@bp.post("/exec-comp/restatement-events/<eid>/order-recovery")
def order_recovery(eid):
    authenticate([ROLE_CHAIR])
    event = fetch("restatement_events", eid)
    if event["status"] != "ANALYZED":
        raise ApiError("ERR_EVENT_STATE_INVALID")

    apply_changes(event, {"status": "RECOVERY_ORDERED"})
    touch(event)
    for determination in domain.event_determinations(event["id"]):
        if determination["status"] == "CALCULATED":
            apply_changes(
                determination, {"status": "NOTICED", "noticed_at": now()}
            )
            touch(determination)
    return object_response(event)


# ---------------------------------------------------------------------------
# ClawbackDetermination
# ---------------------------------------------------------------------------
def _owner_of(determination):
    award = store.payout_awards[determination["payout_award_id"]]
    return award["executive_id"]


@bp.get("/exec-comp/clawback-determinations")
def list_determinations():
    user_id, role = authenticate(
        [ROLE_COUNSEL, ROLE_CHAIR, ROLE_COMP_CONSULTANT, ROLE_OFFICER]
    )
    rows = ordered(list(store.clawback_determinations.values()))
    if role == ROLE_OFFICER:
        rows = [r for r in rows if _owner_of(r) == user_id]
    for field in ("restatement_event_id", "payout_award_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginated(rows)


@bp.get("/exec-comp/clawback-determinations/<did>")
def read_determination(did):
    user_id, role = authenticate(
        [ROLE_COUNSEL, ROLE_CHAIR, ROLE_COMP_CONSULTANT, ROLE_OFFICER]
    )
    determination = fetch("clawback_determinations", did)
    if role == ROLE_OFFICER and _owner_of(determination) != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return object_response(determination)


@bp.post("/exec-comp/clawback-determinations/<did>/acknowledge")
def acknowledge(did):
    user_id, _ = authenticate([ROLE_OFFICER])
    determination = fetch("clawback_determinations", did)
    if _owner_of(determination) != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if determination["status"] != "NOTICED":
        raise ApiError("ERR_DETERMINATION_STATE_INVALID")

    apply_changes(
        determination,
        {"acknowledged_at": now(), "acknowledged_by_user_id": user_id},
    )
    touch(determination)
    return object_response(determination)


def _recovered_total(event):
    total = calc.dec(0)
    for row in domain.event_determinations(event["id"]):
        if row["status"] == "RECOVERED":
            total += calc.dec(row["recoverable_amount_usd"])
    return calc.money(total)


@bp.post("/exec-comp/clawback-determinations/<did>/recover")
def recover(did):
    user_id, _ = authenticate([ROLE_CHAIR])
    determination = fetch("clawback_determinations", did)
    if determination["acknowledged_by_user_id"] is not None and (
        user_id == determination["acknowledged_by_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if determination["status"] != "NOTICED":
        raise ApiError("ERR_DETERMINATION_STATE_INVALID")
    if determination["acknowledged_at"] is None:
        raise ApiError("ERR_DETERMINATION_NOT_ACKNOWLEDGED")

    # L1
    apply_changes(determination, {"status": "RECOVERED", "recovered_at": now()})
    touch(determination)
    event = store.restatement_events[determination["restatement_event_id"]]
    siblings = domain.event_determinations(event["id"])
    changes = {"recovered_total_usd": _recovered_total(event)}
    if all(row["status"] == "RECOVERED" for row in siblings):
        if event["status"] == "RECOVERY_ORDERED":
            changes["status"] = "CLOSED"
    apply_changes(event, changes)

    # L2
    award = store.payout_awards[determination["payout_award_id"]]
    new_realized = calc.money(
        calc.dec(award["realized_value_usd"])
        - calc.dec(determination["recoverable_amount_usd"])
    )
    apply_changes(
        award,
        {
            "status": "CLAWED_BACK",
            "realized_value_usd": new_realized,
            "realizable_value_usd": new_realized,
        },
    )

    # L3 → L5
    program = store.pay_programs[award["pay_program_id"]]
    before = domain.watched(program)
    domain.recompute_program_alignment(program)
    domain.stale_if_watched_changed(program, before)
    return object_response(determination)


@bp.post("/exec-comp/clawback-determinations/<did>/reverse-recovery")
def reverse_recovery(did):
    authenticate([ROLE_CHAIR])
    determination = fetch("clawback_determinations", did)
    body = Body()
    body.string("reversal_reason", required=True, min_len=1, max_len=500)

    if determination["status"] != "RECOVERED":
        raise ApiError("ERR_DETERMINATION_STATE_INVALID")

    # L1
    apply_changes(determination, {"status": "NOTICED", "recovered_at": None})
    touch(determination)
    event = store.restatement_events[determination["restatement_event_id"]]
    changes = {"recovered_total_usd": _recovered_total(event)}
    if event["status"] == "CLOSED":
        changes["status"] = "RECOVERY_ORDERED"
    apply_changes(event, changes)

    # L2
    award = store.payout_awards[determination["payout_award_id"]]
    new_realized = calc.money(
        calc.dec(award["realized_value_usd"])
        + calc.dec(determination["recoverable_amount_usd"])
    )
    apply_changes(
        award,
        {
            "status": "VESTED",
            "realized_value_usd": new_realized,
            "realizable_value_usd": new_realized,
        },
    )

    # L3 → L5
    program = store.pay_programs[award["pay_program_id"]]
    before = domain.watched(program)
    domain.recompute_program_alignment(program)
    domain.stale_if_watched_changed(program, before)
    return object_response(determination)
