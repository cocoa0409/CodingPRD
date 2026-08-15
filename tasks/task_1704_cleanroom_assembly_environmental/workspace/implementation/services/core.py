"""Shared business logic: lazy expiry, posture derivation, classification,
severity scoring, cascades, and common field validators (PRD sections 2.5-2.8,
3.1-3.4; scaffold calculations table)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import (
    store,
    now,
    parse_iso,
    iso_ms,
    trunc_second,
    mutate,
    next_seq,
)
from errors import ApiError, ERR_INVALID_REQUEST

# ---------------------------------------------------------------------------
# Field validators (priority 9 structural checks)
# ---------------------------------------------------------------------------


def req_string(payload, field):
    v = payload.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s is required and must be a non-empty string" % field)
    return v


def opt_string(payload, field):
    v = payload.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be a non-empty string when provided" % field)
    return v


def req_int(payload, field, minimum=None):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be >= %d" % (field, minimum))
    return v


def opt_int(payload, field, minimum=None):
    v = payload.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be >= %d" % (field, minimum))
    return v


def req_enum(payload, field, allowed):
    v = payload.get(field)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return v


def req_bool(payload, field):
    v = payload.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s is required and must be a boolean" % field)
    return v


def req_iso(payload, field):
    v = payload.get(field)
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s is required and must be an ISO-8601 timestamp" % field)


def opt_iso(payload, field):
    v = payload.get(field)
    if v is None:
        return None
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be an ISO-8601 timestamp" % field)


# ---------------------------------------------------------------------------
# Lazy expiry (PRD 2.5; calculations certification_expiry / gowning expiry)
# ---------------------------------------------------------------------------


def recompute_posture(room):
    """Derived environment_posture per calculations.environment_posture_derivation.

    Fixed top-to-bottom evaluation order, first match wins. Returns True when
    the posture changed.
    """
    old = room["environment_posture"]

    # Rule 1: SHUTDOWN — an APPROVED investigation with product_impact
    # CONFIRMED on any excursion of this room, whose approval has not been
    # superseded by a fresh PASS certification recorded after that approval.
    confirmed_approvals = []
    for inv in store.investigations.values():
        if inv.get("_cleanroom_id") != room["id"]:
            continue
        if inv["status"] == "APPROVED" and inv["product_impact"] == "CONFIRMED":
            confirmed_approvals.append(inv["_approved_seq"])
    shutdown = False
    if confirmed_approvals:
        pass_seqs = [
            c["_created_seq"]
            for c in store.certifications.values()
            if c["cleanroom_id"] == room["id"] and c["result"] == "PASS"
        ]
        latest_pass_seq = max(pass_seqs) if pass_seqs else -1
        for appr_seq in confirmed_approvals:
            if appr_seq > latest_pass_seq:
                shutdown = True
                break

    if shutdown:
        new = "SHUTDOWN"
    else:
        open_exc = [
            e for e in store.excursions.values()
            if e["cleanroom_id"] == room["id"]
            and e["status"] in ("OPEN", "UNDER_INVESTIGATION")
        ]
        if any(e["severity"] == "ACTION" for e in open_exc):
            new = "ACTION"
        elif any(e["severity"] == "ALERT" for e in open_exc):
            new = "ALERT"
        elif room["certification_status"] != "CERTIFIED":
            new = "ALERT"  # floor
        else:
            new = "IN_CONTROL"

    if new != old:
        room["environment_posture"] = new
        return True
    return False


def touch_room(room):
    """Lazy certification expiry on any room read/write (PRD 2.5).

    CERTIFIED -> CERTIFICATION_EXPIRED when now >= certified_at +
    recert_interval_days (boundary inclusive, second precision). One version
    increment for the whole lazy evaluation.
    """
    if room["certification_status"] != "CERTIFIED":
        return room
    certified_at = parse_iso(room["certified_at"])
    expiry = certified_at + timedelta(days=room["recert_interval_days"])
    if trunc_second(now()) >= trunc_second(expiry):
        room["certification_status"] = "CERTIFICATION_EXPIRED"
        recompute_posture(room)
        mutate(room)
    return room


def touch_qualification(qual):
    """Lazy gowning-qualification expiry: QUALIFIED -> EXPIRED at boundary."""
    if qual["status"] != "QUALIFIED":
        return qual
    expires = parse_iso(qual["qualification_expires_at"])
    if trunc_second(now()) >= trunc_second(expires):
        qual["status"] = "EXPIRED"
        mutate(qual)
    return qual


# ---------------------------------------------------------------------------
# Sampling / excursions (PRD 3.3; calculations sample_classification,
# excursion_severity_score)
# ---------------------------------------------------------------------------

ZONE_MULTIPLIER = {
    "ISO_5": Decimal("3"),
    "ISO_6": Decimal("2.5"),
    "ISO_7": Decimal("2"),
    "ISO_8": Decimal("1"),
}


def classify_sample(room, metric, result_value):
    if metric == "PARTICLE":
        alert = room["particle_alert_limit"]
        action = room["particle_action_limit"]
    else:
        alert = room["viable_alert_limit"]
        action = room["viable_action_limit"]
    if result_value >= action:
        return "ACTION_EXCEEDED"
    if result_value >= alert:
        return "ALERT_EXCEEDED"
    return "IN_CONTROL"


def compute_severity_score(point, sample_dt):
    """base * zone * (1 + 0.25 * recurrence_count), round-half-up to 2dp.

    recurrence_count: CLOSED excursions at the same sampling point whose
    triggering sample's sampled_at falls in [sampled_at - 30d, sampled_at).
    """
    base = Decimal(10) if point["metric"] == "VIABLE" else Decimal(4)
    zone = ZONE_MULTIPLIER[point["zone_iso_class"]]
    upper = trunc_second(sample_dt)
    lower = trunc_second(sample_dt - timedelta(days=30))
    recurrence = 0
    for exc in store.excursions.values():
        if exc["sampling_point_id"] != point["id"]:
            continue
        if exc["status"] != "CLOSED":
            continue
        trig = store.samples.get(exc["sample_id"])
        if trig is None:
            continue
        ts = trunc_second(parse_iso(trig["sampled_at"]))
        if lower <= ts < upper:
            recurrence += 1
    score = base * zone * (Decimal(1) + Decimal("0.25") * recurrence)
    return float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Cascades (PRD 3.4 SHUTDOWN cascade)
# ---------------------------------------------------------------------------


def shutdown_cascade(room):
    """CONFIRMED-impact approval: batches OPEN/IN_PROGRESS -> ON_HOLD,
    STAGED transfers -> REJECTED, atomically within the request."""
    for batch in store.batches.values():
        if batch["cleanroom_id"] == room["id"] and batch["status"] in ("OPEN", "IN_PROGRESS"):
            batch["status"] = "ON_HOLD"
            batch["hold_reason"] = "EXCURSION_PRODUCT_IMPACT"
            mutate(batch)
    for transfer in store.transfers.values():
        if transfer["cleanroom_id"] == room["id"] and transfer["status"] == "STAGED":
            transfer["status"] = "REJECTED"
            mutate(transfer)


def open_excursions_for_room(room_id):
    return [
        e for e in store.excursions.values()
        if e["cleanroom_id"] == room_id
        and e["status"] in ("OPEN", "UNDER_INVESTIGATION")
    ]


def has_validated_cleaning_program(room_id):
    return any(
        p["cleanroom_id"] == room_id and p["status"] == "VALIDATED"
        for p in store.cleaning_programs.values()
    )


def latest_pass_certification(room_id):
    """Latest PASS cert: executed_at DESC, tie-break created_at DESC."""
    passes = [
        c for c in store.certifications.values()
        if c["cleanroom_id"] == room_id and c["result"] == "PASS"
    ]
    if not passes:
        return None
    return max(
        passes,
        key=lambda c: (parse_iso(c["executed_at"]), c["_created_seq"]),
    )


def qualified_unexpired_qualification(personnel_id, cleanroom_id):
    """A QUALIFIED, non-expired qualification for the (personnel, room) pair."""
    for q in store.qualifications.values():
        if q["personnel_id"] != personnel_id or q["cleanroom_id"] != cleanroom_id:
            continue
        touch_qualification(q)
        if q["status"] == "QUALIFIED":
            return q
    return None


def grade_check(room, location_mean_values):
    """mean(values) < particle_alert_limit, strictly, at full precision."""
    total = Decimal(0)
    for v in location_mean_values:
        total += Decimal(str(v))
    mean = total / Decimal(len(location_mean_values))
    return mean < Decimal(room["particle_alert_limit"])


def audit_scope_count(audit):
    """Samples of the audited room with sampled_at in [window_start, window_end)."""
    ws = trunc_second(parse_iso(audit["window_start"]))
    we = trunc_second(parse_iso(audit["window_end"]))
    count = 0
    for sample in store.samples.values():
        point = store.sampling_points.get(sample["sampling_point_id"])
        if point is None or point["cleanroom_id"] != audit["cleanroom_id"]:
            continue
        ts = trunc_second(parse_iso(sample["sampled_at"]))
        if ws <= ts < we:
            count += 1
    return count
