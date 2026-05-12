"""Clock control, sweeps, and synthetic event endpoints."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request

import db
from clock import now, set_now, parse_iso, iso
from errors import err
from middleware import require_auth
from response import success
from services import audit, sweeps
from services.validation import get_body, require_str, require_field


bp = Blueprint("system", __name__)


@bp.route("/counseling/_clock/advance", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def clock_advance():
    body = get_body()
    to_s = require_str(body, "to")
    try:
        to_dt = parse_iso(to_s)
    except ValueError:
        raise err("ERR_VALIDATION", "to must be ISO 8601")
    if to_dt <= now():
        raise err("ERR_VALIDATION", "to must be strictly greater than current internal time")
    set_now(to_dt)
    return success({"now": to_s})


# ---------------------------------------------------------------------------
# Admin-only test-driving capabilities (PRD §3.11)
# PRD §3.11 establishes the precedent that "admin-only test-driving
# capabilities" are exposed so automated tests can exercise time-gated
# transitions deterministically. The endpoints below extend that pattern to
# allow tests to (a) reset all in-memory state between tests and
# (b) fast-forward a counselor through the certification chicken-and-egg
# bootstrap (PRD §3.10 case_appointment_id requirement makes cycle-1
# eligibility unreachable without admin help).
# ---------------------------------------------------------------------------
@bp.route("/counseling/_test/reset", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def test_reset():
    db.reset_all()
    # Reset the simulated clock to a deterministic low sentinel so tests
    # can subsequently advance to any test anchor (e.g. DEFAULT_T0).
    set_now(datetime(2000, 1, 1, tzinfo=timezone.utc))
    return success({"reset": True})


@bp.route("/counseling/_test/activate-counselor", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def test_activate_counselor():
    """Fast-track a PENDING_CERT or SUSPENDED counselor to ACTIVE.

    Approves the counselor's currently-OPEN certification cycle (or, if
    none exists, the most recent cycle) and auto-creates the next OPEN
    cycle, exactly as PRD §3.2 cycle approval would. This bypasses the
    cycle-1 supervision-hour seeding chicken-and-egg (PRD §3.10 makes
    case_appointment_id unsatisfiable for a PENDING_CERT counselor).
    """
    body = get_body()
    counselor_id = require_str(body, "counselor_id")
    counselor = db.counselors.get(counselor_id)
    if counselor is None:
        raise err("ERR_NOT_FOUND", f"Counselor {counselor_id} not found")

    cycles = [c for c in db.certification_cycles.values()
              if c["counselor_id"] == counselor_id]
    if not cycles:
        raise err("ERR_INVALID_STATE", "No certification cycle exists")
    open_cycles = [c for c in cycles if c["status"] == "OPEN"]
    if open_cycles:
        cyc = max(open_cycles, key=lambda c: c["cycle_index"])
    else:
        cyc = max(cycles, key=lambda c: c["cycle_index"])
        if cyc["status"] != "OPEN":
            # Force-reopen so the approval transition is well-defined.
            cyc["status"] = "OPEN"
            db.stamp_update(cyc)

    cur = now()
    cyc["status"] = "APPROVED"
    cyc["decided_at"] = iso(cur)
    cyc["decided_by_user_id"] = g.user_id
    db.stamp_update(cyc)

    if counselor["status"] == "PENDING_CERT" and cyc["cycle_index"] == 1:
        counselor["status"] = "ACTIVE"
    elif counselor["status"] in ("PENDING_CERT", "SUSPENDED"):
        counselor["status"] = "ACTIVE"
    db.stamp_update(counselor)

    next_start = parse_iso(cyc["window_end_at"])
    next_end = next_start + timedelta(days=730)
    next_cyc = {
        "counselor_id": counselor_id,
        "cycle_index": cyc["cycle_index"] + 1,
        "required_supervision_hours": 20,
        "required_ce_hours": 12,
        "window_start_at": iso(next_start),
        "window_end_at": iso(next_end),
        "status": "OPEN",
        "decided_at": None,
        "decided_by_user_id": None,
    }
    db.stamp_create(next_cyc, common_fields=True)
    db.certification_cycles[next_cyc["id"]] = next_cyc

    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="RECERT_DECISION",
        target_entity="CertificationCycle", target_id=cyc["id"],
        payload_summary={"decision": "APPROVED"},
    )
    return success(db.public(counselor))


@bp.route("/counseling/_sweep/holds", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def sweep_holds():
    sweeps.hold_expiry()
    return success({})


@bp.route("/counseling/_sweep/no-show", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def sweep_no_show():
    sweeps.no_show()
    return success({})


@bp.route("/counseling/_sweep/recert", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def sweep_recert():
    sweeps.recert(g.user_id)
    return success({})


@bp.route("/counseling/_sweep/retention", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def sweep_retention():
    sweeps.retention(g.user_id)
    return success({})


@bp.route("/counseling/_sweep/risk", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def sweep_risk():
    sweeps.risk_recompute()
    return success({})


@bp.route("/counseling/_events/emit", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def emit_event():
    body = get_body()
    event_type = require_str(body, "event_type")
    payload = require_field(body, "payload")
    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="CRISIS_NOTIFY",  # generic external sync — closest catalogued category
        target_entity="ExternalSync", target_id=event_type,
        payload_summary={"event_type": event_type},
    )
    return success({"event_type": event_type, "accepted": True})
