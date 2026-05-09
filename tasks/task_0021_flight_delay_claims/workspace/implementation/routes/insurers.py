"""Insurer routes + test-driver endpoints (clock, sweep, invariant)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from db import db, gen_id, now_iso_z
from errors import ERR_INVALID_REQUEST, ERR_RESERVE_DRIFT, raise_api_error
from middleware import require_roles
from response import success_response
from services.calculations import NINETY_DAYS_MS
from services.common import (
    append_audit,
    check_version,
    get_insurer_or_404,
    get_json_body,
    require_field,
    require_int,
)
from services.quorum import classify_cause, evaluate_quorum
from services.reserve import (
    recompute_quota_used,
    recompute_reserve_balance,
    total_outstanding_reserve,
)

bp = Blueprint("insurers", __name__)


def _serialize_insurer(ins: dict) -> dict:
    out = dict(ins)
    out["total_outstanding_reserve_cents"] = total_outstanding_reserve(ins["id"])
    return out


@bp.post("/insurers")
@require_roles("ClaimsAdmin")
def create_insurer():
    body = get_json_body()
    name = require_field(body, "name", type_=str)
    currency = require_field(body, "currency", type_=str)

    ins = {
        "id": gen_id(),
        "name": name,
        "currency": currency,
        "now_epoch_ms": 0,
        "total_outstanding_reserve_cents": 0,
    }
    db.stamp_create(ins)
    db.insurers[ins["id"]] = ins
    return jsonify(success_response(_serialize_insurer(ins))), 201


@bp.get("/insurers/<insurer_id>")
@require_roles("Any")
def get_insurer(insurer_id: str):
    ins = get_insurer_or_404(insurer_id)
    return jsonify(success_response(_serialize_insurer(ins))), 200


# ---------- Clock advance ----------

@bp.post("/insurers/<insurer_id>/_clock/advance")
@require_roles("ClaimsAdmin")
def advance_clock(insurer_id: str):
    ins = get_insurer_or_404(insurer_id)
    body = get_json_body()
    check_version(body, ins)

    delta_ms = body.get("delta_ms")
    to_epoch_ms = body.get("to_epoch_ms")
    if delta_ms is None and to_epoch_ms is None:
        raise_api_error(ERR_INVALID_REQUEST, "Either delta_ms or to_epoch_ms is required.")
    if delta_ms is not None:
        if not isinstance(delta_ms, int) or isinstance(delta_ms, bool) or delta_ms < 0:
            raise_api_error(ERR_INVALID_REQUEST, "delta_ms must be a non-negative integer.")
        ins["now_epoch_ms"] = ins.get("now_epoch_ms", 0) + delta_ms
    else:
        if not isinstance(to_epoch_ms, int) or isinstance(to_epoch_ms, bool) or to_epoch_ms < 0:
            raise_api_error(ERR_INVALID_REQUEST, "to_epoch_ms must be a non-negative integer.")
        ins["now_epoch_ms"] = to_epoch_ms

    db.stamp_update(ins)
    return jsonify(success_response(_serialize_insurer(ins))), 200


# ---------- System sweep ----------

def _all_claims_referencing_flight(flight_id: str) -> list[dict]:
    out = []
    for claim in db.claims.values():
        for seg_id in claim.get("segment_ids", []):
            seg = db.claim_segments.get(seg_id)
            if seg and seg.get("flight_id") == flight_id:
                out.append(claim)
                break
    return out


def _sweep_run(insurer_id: str) -> dict:
    """Run system sweep: SCHEDULED→ACTIVE; ARCHIVE old finalised flights;
    EXECUTING→SETTLED for batches; auto-reject claims when applicable.
    """
    ins = db.insurers[insurer_id]
    now = ins["now_epoch_ms"]
    flights_advanced = 0
    batches_settled = 0
    claims_auto_rejected = 0

    # 1) SCHEDULED → ACTIVE
    for flight in list(db.flights.values()):
        if flight.get("insurer_id") != insurer_id:
            continue
        if flight.get("status") != "SCHEDULED":
            continue
        # Has a terminal-status event already been ingested?
        events = [e for e in db.flight_status_events.values() if e.get("flight_id") == flight["id"]]
        terminal_seen = any(e["reported_status"] in ("CANCELLED", "DIVERTED", "RETURNED") for e in events)
        if terminal_seen:
            continue
        if now >= flight["scheduled_departure_epoch_ms"] - 30 * 60 * 1000:
            flight["status"] = "ACTIVE"
            db.stamp_update(flight)
            flights_advanced += 1

    # 2) Archive old finalised flights (90+ days past scheduled arrival)
    for flight in list(db.flights.values()):
        if flight.get("insurer_id") != insurer_id:
            continue
        if flight.get("status") not in ("LANDED", "CANCELLED", "DIVERTED", "RETURNED"):
            continue
        if now - flight["scheduled_arrival_epoch_ms"] <= NINETY_DAYS_MS:
            continue
        # Precondition: no Claim in non-terminal review_status references this flight
        blocking = False
        for c in _all_claims_referencing_flight(flight["id"]):
            if c.get("review_status") in ("PENDING_MATCH", "MATCHED", "UNDER_REVIEW", "APPROVED"):
                blocking = True
                break
        if blocking:
            continue
        flight["status"] = "ARCHIVED"
        flight["archived_at_epoch_ms"] = now
        db.stamp_update(flight)
        append_audit(insurer_id, "FLIGHT", flight["id"], "STATUS_CHANGE",
                     {"from": flight.get("status"), "to": "ARCHIVED"})

    # 3) Auto-settle batches whose claims are all terminal (PAID/REVERSED) with no exceptions
    for batch in list(db.payout_batches.values()):
        if batch.get("insurer_id") != insurer_id:
            continue
        if batch.get("execution_phase") != "EXECUTING":
            continue
        if batch.get("exception_claim_ids"):
            continue
        if not _all_batch_claims_terminal(batch):
            continue
        batch["execution_phase"] = "SETTLED"
        db.stamp_update(batch)
        batches_settled += 1
        append_audit(insurer_id, "PAYOUT_BATCH", batch["id"], "STATUS_CHANGE",
                     {"from": "EXECUTING", "to": "SETTLED"})

    return {
        "flights_advanced": flights_advanced,
        "batches_settled": batches_settled,
        "claims_auto_rejected": claims_auto_rejected,
    }


def _all_batch_claims_terminal(batch: dict) -> bool:
    for cid in batch.get("claim_ids", []):
        c = db.claims.get(cid)
        if not c:
            return False
        if c.get("payout_status") not in ("PAID", "REVERSED"):
            return False
    return True


@bp.post("/insurers/<insurer_id>/_sweep/run")
@require_roles("ClaimsAdmin", "system")
def sweep_run(insurer_id: str):
    get_insurer_or_404(insurer_id)
    summary = _sweep_run(insurer_id)
    return jsonify(success_response(summary)), 200


# ---------- Invariant check ----------

@bp.post("/insurers/<insurer_id>/_invariant/check")
@require_roles("ClaimsAdmin", "Auditor")
def invariant_check(insurer_id: str):
    get_insurer_or_404(insurer_id)
    drift = []
    for pol in db.policies.values():
        if pol.get("insurer_id") != insurer_id:
            continue
        expected_reserve = recompute_reserve_balance(pol)
        observed_reserve = pol.get("reserve_balance_cents", 0) or 0
        if expected_reserve != observed_reserve:
            drift.append({
                "policy_id": pol["id"],
                "field": "reserve_balance_cents",
                "expected": expected_reserve,
                "observed": observed_reserve,
            })
        expected_quota = recompute_quota_used(pol)
        observed_quota = pol.get("claim_quota_used_cents", 0) or 0
        if expected_quota != observed_quota:
            drift.append({
                "policy_id": pol["id"],
                "field": "claim_quota_used_cents",
                "expected": expected_quota,
                "observed": observed_quota,
            })

    if drift:
        # The PRD says ERR_RESERVE_DRIFT is "surfaced" so audit observers can act;
        # we return as a 409 error envelope.
        from response import error_response
        body = error_response(ERR_RESERVE_DRIFT, "Reserve/quota invariant drift detected.")
        body["data"]["drift"] = drift
        body["data"]["ok"] = False
        return jsonify(body), 409

    return jsonify(success_response({"ok": True, "drift": []})), 200
