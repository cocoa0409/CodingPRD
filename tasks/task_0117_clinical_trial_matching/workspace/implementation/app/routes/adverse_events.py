"""Adverse Event endpoints — report, start-review, escalate, resolve, list."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, request

from ..auth import ROLE_COORD, ROLE_PI, require_roles
from ..clock import now
from ..errors import (
    err_cross_participant_reference,
    err_invalid_state,
)
from ..helpers import (
    assert_enum,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import (
    adverse_events_for_participant,
    get_adverse_event,
    get_participant,
    get_trial,
    get_visit,
)
from ..services.serialize import serialize_adverse_event
from ..store import store

bp = Blueprint("adverse_events", __name__)


ALLOWED_SEVERITIES = ["MILD", "MODERATE", "SEVERE", "LIFE_THREATENING"]


def _bump(ae: dict[str, Any]) -> None:
    ae["updated_at"] = now()
    ae["version"] = ae["version"] + 1


def _bump_participant(p: dict[str, Any]) -> None:
    p["updated_at"] = now()
    p["version"] = p["version"] + 1


# =====================================================================
# POST /participants/<id>/adverse-events
# =====================================================================

@bp.post("/participants/<participant_id>/adverse-events")
@require_roles(ROLE_PI, ROLE_COORD)
def report_adverse_event(participant_id: str, **_caller):
    body = require_json_object()
    severity = assert_enum(body.get("severity"), "severity", ALLOWED_SEVERITIES, required=True)
    narrative = assert_string(body.get("narrative"), "narrative", required=True, min_len=1, max_len=2000)
    caused_visit_id = body.get("caused_visit_id")
    if caused_visit_id is not None and not isinstance(caused_visit_id, str):
        from ..errors import err_invalid_input
        raise err_invalid_input("caused_visit_id must be a string")

    with store().lock:
        p = get_participant(participant_id)

        if caused_visit_id:
            v = get_visit(caused_visit_id)  # ERR_NOT_FOUND if missing
            if v["participant_id"] != participant_id:
                raise err_cross_participant_reference()

        ts = now()
        ae_id = new_uuid()
        ae = {
            "id": ae_id,
            "participant_id": participant_id,
            "severity": severity,
            "status": "OPEN",
            "reported_at": ts,
            "narrative": narrative,
            "caused_visit_id": caused_visit_id,
            "resolution_note": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        store().adverse_events[ae_id] = ae
        # Increment the participant's open_ae_count.
        p["open_ae_count"] = p["open_ae_count"] + 1
        _bump_participant(p)

        # Auto-escalation on SEVERE / LIFE_THREATENING.
        if severity in {"SEVERE", "LIFE_THREATENING"}:
            ae["status"] = "ESCALATED_HOLD"
            _bump(ae)
            _cascade_escalation(p, severity, ts)

    return created(serialize_adverse_event(ae))


# =====================================================================
# POST /participants/<id>/adverse-events/<ae_id>/start-review
# =====================================================================

@bp.post("/participants/<participant_id>/adverse-events/<adverse_event_id>/start-review")
@require_roles(ROLE_PI)
def start_review(participant_id: str, adverse_event_id: str, **_caller):
    with store().lock:
        p = get_participant(participant_id)
        ae = get_adverse_event(adverse_event_id)
        if ae["participant_id"] != participant_id:
            from ..errors import err_not_found
            raise err_not_found(f"Adverse event '{adverse_event_id}' not found")
        if ae["status"] != "OPEN":
            raise err_invalid_state("Adverse event is not OPEN")
        ae["status"] = "UNDER_REVIEW"
        _bump(ae)
        # open_ae_count unchanged — UNDER_REVIEW still counts as open.
        return ok(serialize_adverse_event(ae))


# =====================================================================
# POST /participants/<id>/adverse-events/<ae_id>/escalate
# =====================================================================

@bp.post("/participants/<participant_id>/adverse-events/<adverse_event_id>/escalate")
@require_roles(ROLE_PI)
def escalate(participant_id: str, adverse_event_id: str, **_caller):
    with store().lock:
        p = get_participant(participant_id)
        ae = get_adverse_event(adverse_event_id)
        if ae["participant_id"] != participant_id:
            from ..errors import err_not_found
            raise err_not_found(f"Adverse event '{adverse_event_id}' not found")
        if ae["status"] != "UNDER_REVIEW":
            raise err_invalid_state("Adverse event is not UNDER_REVIEW")
        ae["status"] = "ESCALATED_HOLD"
        _bump(ae)
        _cascade_escalation(p, ae["severity"], now())
        return ok(serialize_adverse_event(ae))


# =====================================================================
# POST /participants/<id>/adverse-events/<ae_id>/resolve
# =====================================================================

@bp.post("/participants/<participant_id>/adverse-events/<adverse_event_id>/resolve")
@require_roles(ROLE_PI)
def resolve(participant_id: str, adverse_event_id: str, **_caller):
    body = require_json_object()
    resolution_note = assert_string(
        body.get("resolution_note"), "resolution_note", required=True, min_len=1, max_len=1000
    )
    with store().lock:
        p = get_participant(participant_id)
        ae = get_adverse_event(adverse_event_id)
        if ae["participant_id"] != participant_id:
            from ..errors import err_not_found
            raise err_not_found(f"Adverse event '{adverse_event_id}' not found")
        if ae["status"] not in {"UNDER_REVIEW", "ESCALATED_HOLD"}:
            raise err_invalid_state("Adverse event is not in a resolvable state")
        ae["status"] = "RESOLVED"
        ae["resolution_note"] = resolution_note
        _bump(ae)
        # The scaffold's open_ae_count is defined as "events in OPEN or UNDER_REVIEW";
        # the AE state-machine side effect for both UNDER_REVIEW→RESOLVED and
        # ESCALATED_HOLD→RESOLVED says "open_ae_count--". We always recompute from the
        # authoritative AE table after the resolve, which keeps the counter consistent.
        from ..services.lookups import open_ae_count_for as _oac
        new_count = _oac(participant_id)
        if new_count != p["open_ae_count"]:
            p["open_ae_count"] = new_count
            _bump_participant(p)
        return ok(serialize_adverse_event(ae))


# =====================================================================
# GET /participants/<id>/adverse-events
# =====================================================================

@bp.get("/participants/<participant_id>/adverse-events")
@require_roles(ROLE_PI, ROLE_COORD)
def list_adverse_events(participant_id: str, **_caller):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    with store().lock:
        get_participant(participant_id)
        rows = adverse_events_for_participant(participant_id)
        if status_filter:
            rows = [r for r in rows if r["status"] == status_filter]
        total = len(rows)
        page = paginate(rows, limit, offset)
        items = [serialize_adverse_event(ae) for ae in page]
    return listing(items, total, limit, offset)


# =====================================================================
# Cascade chain for AE escalation (auto or manual)
# =====================================================================

def _cascade_escalation(participant: dict[str, Any], severity: str, ts: Any) -> None:
    """When an AE escalates to ESCALATED_HOLD:
    1) All SCHEDULED visits on that participant → CANCELLED.
    2) For each visit that was holding a PROVISIONAL payment (net positive), write REVERSAL.
    3) If severity == LIFE_THREATENING and parent trial is OPEN_FOR_ENROLLMENT → CLOSED_TO_ENROLLMENT.
    """
    s = store()
    # Compute net PROVISIONAL-minus-REVERSAL per visit so we don't double-reverse.
    net_by_visit: dict[str, int] = {}
    for pmt in s.payments.values():
        if pmt["participant_id"] != participant["id"]:
            continue
        if pmt["kind"] == "PROVISIONAL":
            net_by_visit[pmt["visit_id"]] = net_by_visit.get(pmt["visit_id"], 0) + pmt["amount_cents"]
        elif pmt["kind"] == "REVERSAL":
            net_by_visit[pmt["visit_id"]] = net_by_visit.get(pmt["visit_id"], 0) + pmt["amount_cents"]

    # Cancel SCHEDULED visits.
    for v in s.visits.values():
        if v["participant_id"] != participant["id"]:
            continue
        if v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            v["updated_at"] = ts
            v["version"] = v["version"] + 1

    # Reverse any COMPLETED visit's outstanding PROVISIONAL accrual.
    for v in s.visits.values():
        if v["participant_id"] != participant["id"]:
            continue
        if v["status"] != "COMPLETED":
            continue
        net = net_by_visit.get(v["id"], 0)
        if net > 0:
            rev_id = new_uuid()
            s.payments[rev_id] = {
                "id": rev_id,
                "participant_id": participant["id"],
                "visit_id": v["id"],
                "kind": "REVERSAL",
                "amount_cents": -net,
                "paid_at": None,
                "created_at": ts,
            }

    # LIFE_THREATENING parent-trial cascade.
    if severity == "LIFE_THREATENING":
        trial = s.trials.get(participant["trial_id"])
        if trial is not None and trial["status"] == "OPEN_FOR_ENROLLMENT":
            trial["status"] = "CLOSED_TO_ENROLLMENT"
            trial["updated_at"] = ts
            trial["version"] = trial["version"] + 1
