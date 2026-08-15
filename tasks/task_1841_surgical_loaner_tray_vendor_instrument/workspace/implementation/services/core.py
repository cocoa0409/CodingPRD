"""Shared business logic: serializers, readiness, sterilization projections,
escalation auto-creation, vendor exposure rollups, and cascade helpers.

Calculation constants (PRD §3 / scaffold §1.3):
  LEAD_HOURS: STANDARD 48, URGENT 24, EMERGENT 12
  ESCALATION_WINDOW_MINUTES: 1440
  PREP_BUFFER_MINUTES: 60
  DECON_MIN_MINUTES: 30
  MAX_REWORKS: 2
  ACCESS_LEAD_MINUTES: 120
  ACCESS_TRAIL_MINUTES: 30
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

LEAD_HOURS = {"STANDARD": 48, "URGENT": 24, "EMERGENT": 12}
ESCALATION_WINDOW_MINUTES = 1440
PREP_BUFFER_MINUTES = 60
DECON_MIN_MINUTES = 30
MAX_REWORKS = 2
ACCESS_LEAD_MINUTES = 120
ACCESS_TRAIL_MINUTES = 30

VENDOR_CAUSES = {"VENDOR_LATE_DELIVERY", "STERILIZATION_TURNAROUND", "REP_ACCESS_ISSUE"}

# Non-terminal tray states cancelled by request/case cancellation.
CANCELLABLE_TRAY_STATES = {
    "EXPECTED",
    "DELIVERY_PENDING",
    "CHECKED_IN",
    "PROCESSING",
    "QUARANTINED",
    "MISSING",
}

# Tray states that count as terminal for the request bubble-up closure check.
TERMINAL_TRAY_STATES = {"RECONCILED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

def round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_div(numerator_cents: int, denominator) -> int:
    """Integer-cents division rounding half up."""
    return round_half_up_cents(Decimal(numerator_cents) / Decimal(denominator))


# ---------------------------------------------------------------------------
# Generic system-field stamping
# ---------------------------------------------------------------------------

def stamp_new(entity: dict, with_version: bool = True) -> dict:
    entity["id"] = db.new_id()
    ts = db.fmt_ts(db.now_dt())
    entity["created_at"] = ts
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    entity["_seq"] = db.next_creation_seq()
    return entity


def touch(entity: dict) -> None:
    """updated_at refresh + version increment for versioned resources."""
    entity["updated_at"] = db.fmt_ts(db.now_dt())
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serializers (strip internal keys, datetimes already stored as strings)
# ---------------------------------------------------------------------------

def serialize(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Sterilization projection (calc_sterilization_turnaround)
# ---------------------------------------------------------------------------

def min_cycle_cooldown():
    """min(cycle_minutes + cooldown_minutes) over all SterilizerUnits, or None
    when no unit exists."""
    if not db.sterilizer_units:
        return None
    return min(
        u["cycle_minutes"] + u["cooldown_minutes"] for u in db.sterilizer_units.values()
    )


def active_turn_for_tray(tray_id: str):
    """The tray's latest non-terminal turn (DECONTAMINATING/STERILIZING/COOLDOWN)."""
    candidates = [
        t
        for t in db.turns.values()
        if t["tray_id"] == tray_id and t["status"] in {"DECONTAMINATING", "STERILIZING", "COOLDOWN"}
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda t: t["_seq"])
    return candidates[-1]


def compute_projection(tray: dict):
    """projected_sterile_ready_at per calc_sterilization_turnaround.
    Returns a datetime or None."""
    status = tray["status"]
    # Once a tray reaches STERILE_READY or any later state, the projection is
    # null and the actual release governs.
    if status in {
        "STERILE_READY",
        "STAGED",
        "IN_USE",
        "USED",
        "AWAITING_PICKUP",
        "PICKED_UP",
        "RECONCILED",
        "CANCELLED",
    }:
        return None
    turn = active_turn_for_tray(tray["id"])
    if turn is not None:
        if turn["status"] == "DECONTAMINATING":
            mcc = min_cycle_cooldown()
            if mcc is None:
                return None
            return db.parse_dt(turn["decon_started_at"]) + timedelta(
                minutes=DECON_MIN_MINUTES + mcc
            )
        if turn["status"] == "STERILIZING":
            unit = db.sterilizer_units.get(turn["sterilizer_unit_id"])
            if unit is None:
                return None
            return db.parse_dt(turn["cycle_started_at"]) + timedelta(
                minutes=unit["cycle_minutes"] + unit["cooldown_minutes"]
            )
        if turn["status"] == "COOLDOWN":
            unit = db.sterilizer_units.get(turn["sterilizer_unit_id"])
            if unit is None:
                return None
            return db.parse_dt(turn["cycle_completed_at"]) + timedelta(
                minutes=unit["cooldown_minutes"]
            )
    # Tray CHECKED_IN with no active turn (or any pre-sterile state that
    # still projects): now + decon minimum + fleet-minimum cycle+cooldown.
    if status in {"CHECKED_IN", "PROCESSING"}:
        mcc = min_cycle_cooldown()
        if mcc is None:
            return None
        return db.now_dt() + timedelta(minutes=DECON_MIN_MINUTES + mcc)
    # EXPECTED / MISSING / DELIVERY_PENDING / QUARANTINED: no projection.
    return None


def recompute_tray_projection(tray: dict) -> None:
    tray["projected_sterile_ready_at"] = db.fmt_ts(compute_projection(tray))


# ---------------------------------------------------------------------------
# Readiness (calc_request_readiness) + flip escalation
# ---------------------------------------------------------------------------

def compute_readiness(request: dict) -> str:
    trays = [
        t for t in db.trays.values() if t["request_id"] == request["id"] and t["status"] != "CANCELLED"
    ]
    if len(trays) == 0:
        return "NOT_READY"
    if all(t["status"] in {"STERILE_READY", "STAGED", "IN_USE"} for t in trays):
        return "READY"
    if all(t["status"] in {"DELIVERY_PENDING", "CHECKED_IN", "PROCESSING"} for t in trays):
        on_time = True
        for t in trays:
            if t["status"] in {"CHECKED_IN", "PROCESSING"}:
                proj = db.parse_dt(t.get("projected_sterile_ready_at"))
                req = db.parse_dt(t.get("required_sterile_ready_by"))
                if proj is None or req is None or proj > req:
                    on_time = False
                    break
        if on_time:
            return "AT_RISK"
    return "NOT_READY"


def _readiness_flip_escalation_type(request: dict) -> str:
    """Type by cause for a readiness-flip escalation: tray EXPECTED/MISSING ->
    MISSING_TRAY; QUARANTINED -> DOCUMENTATION; else STERILIZATION_DELAY."""
    trays = [
        t for t in db.trays.values() if t["request_id"] == request["id"] and t["status"] != "CANCELLED"
    ]
    for t in trays:
        if t["status"] in {"EXPECTED", "MISSING"}:
            return "MISSING_TRAY"
    for t in trays:
        if t["status"] == "QUARANTINED":
            return "DOCUMENTATION"
    return "STERILIZATION_DELAY"


def recompute_readiness(request: dict) -> None:
    """Recompute the request's readiness. When an APPROVED request flips INTO
    AT_RISK or NOT_READY and the case's scheduled start is within the
    escalation window, auto-create an OPEN escalation typed by cause."""
    old = request.get("readiness", "NOT_READY")
    new = compute_readiness(request)
    request["readiness"] = new
    if request["status"] == "APPROVED" and new in {"AT_RISK", "NOT_READY"} and new != old:
        case = db.cases.get(request["case_id"])
        if case is not None:
            start = db.parse_dt(case["scheduled_start_at"])
            if start is not None:
                delta_min = (start - db.now_dt()).total_seconds() / 60.0
                if delta_min <= ESCALATION_WINDOW_MINUTES:
                    create_escalation(
                        request["id"],
                        _readiness_flip_escalation_type(request),
                        linked_tray_id=None,
                    )


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------

def create_escalation(request_id: str, esc_type: str, linked_tray_id=None) -> dict:
    esc = {
        "request_id": request_id,
        "type": esc_type,
        "linked_tray_id": linked_tray_id,
        "status": "OPEN",
        "resolution_type": None,
    }
    stamp_new(esc)
    db.escalations[esc["id"]] = esc
    return esc


# ---------------------------------------------------------------------------
# Vendor exposure rollups (calc_vendor_exposure_rollup)
# ---------------------------------------------------------------------------

def recompute_vendor_rollups(vendor_id: str) -> None:
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        return
    # Requests of this vendor
    vendor_request_ids = {r["id"] for r in db.requests.values() if r["vendor_id"] == vendor_id}
    outstanding_penalty = sum(
        p["outstanding_cents"]
        for p in db.penalties.values()
        if p["request_id"] in vendor_request_ids and p["status"] == "ASSESSED"
    )
    outstanding_liability = sum(
        c["final_vendor_share_cents"] or 0
        for c in db.claims.values()
        if c["request_id"] in vendor_request_ids and c["status"] == "APPORTIONED"
    )
    vendor["outstanding_penalty_cents"] = outstanding_penalty
    vendor["outstanding_liability_cents"] = outstanding_liability


def recompute_request_penalty_exposure(request_id: str) -> None:
    """penalty_exposure_cents = sum(time_charge + delay_surcharge) over
    penalties of the request in ACCRUING or ASSESSED."""
    request = db.requests.get(request_id)
    if request is None:
        return
    request["penalty_exposure_cents"] = sum(
        p["time_charge_cents"] + p["delay_surcharge_cents"]
        for p in db.penalties.values()
        if p["request_id"] == request_id and p["status"] in {"ACCRUING", "ASSESSED"}
    )


# ---------------------------------------------------------------------------
# Request cancellation cascade (shared by request cancel and case cancel)
# ---------------------------------------------------------------------------

def cancel_request_cascade(request: dict) -> None:
    """Cascade applied when a request is cancelled (directly or via case
    cancel). Assumes request status already validated. Mutates the request."""
    # Non-terminal trays -> CANCELLED
    for tray in db.trays.values():
        if tray["request_id"] == request["id"] and tray["status"] in CANCELLABLE_TRAY_STATES:
            tray["status"] = "CANCELLED"
            recompute_tray_projection(tray)
            touch(tray)
    # Penalties ACCRUING -> VOID
    for penalty in db.penalties.values():
        if penalty["request_id"] == request["id"] and penalty["status"] == "ACCRUING":
            penalty["status"] = "VOID"
            touch(penalty)
    recompute_request_penalty_exposure(request["id"])
    # Escalations OPEN/ACKNOWLEDGED -> RESOLVED with CASE_CANCELLED
    for esc in db.escalations.values():
        if esc["request_id"] == request["id"] and esc["status"] in {"OPEN", "ACKNOWLEDGED"}:
            esc["status"] = "RESOLVED"
            esc["resolution_type"] = "CASE_CANCELLED"
            touch(esc)
    request["status"] = "CANCELLED"
    recompute_readiness(request)
    touch(request)


def request_bubble_up_close(request: dict) -> None:
    """APPROVED -> CLOSED when every tray is terminal and the case is
    COMPLETED."""
    if request["status"] != "APPROVED":
        return
    case = db.cases.get(request["case_id"])
    if case is None or case["status"] != "COMPLETED":
        return
    trays = [t for t in db.trays.values() if t["request_id"] == request["id"]]
    if not trays:
        return
    if all(t["status"] in TERMINAL_TRAY_STATES for t in trays):
        request["status"] = "CLOSED"
        touch(request)


def trays_of_request(request_id: str):
    return sorted(
        (t for t in db.trays.values() if t["request_id"] == request_id),
        key=lambda t: t["_seq"],
    )


def requests_of_case(case_id: str):
    return sorted(
        (r for r in db.requests.values() if r["case_id"] == case_id),
        key=lambda r: r["_seq"],
    )
