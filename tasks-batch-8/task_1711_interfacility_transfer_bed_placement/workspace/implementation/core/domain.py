"""Domain model: constants, computed fields, serializers, and the shared
business rules of PRD section 3 - occupancy accounting and the saturation
hysteresis (2.6), diversion roll-up (2.7), bed selector (3.4), hold expiry
(3.4), transport estimates (3.7), refusal risk (3.3) and review scoring (3.9).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from .clock import render_instant, floor_minutes_between
from .store import db, new_row, bump, find_by

# ---------------------------------------------------------------------------
# Enum constants
# ---------------------------------------------------------------------------

TRAUMA_LEVELS = ("LEVEL_1", "LEVEL_2", "LEVEL_3", "COMMUNITY", "CRITICAL_ACCESS")
UNIT_TYPES = ("ICU", "CVICU", "NICU", "PICU", "TELEMETRY", "MED_SURG", "BURN", "ED_HOLD")
SPECIALTIES = ("EMERGENCY", "CARDIOLOGY", "NEUROLOGY", "SURGERY", "INTENSIVIST",
               "PEDIATRICS", "GENERAL")
ACUITY_LEVELS = ("CRITICAL", "EMERGENT", "URGENT", "STABLE")
BED_STATUSES = ("AVAILABLE", "HELD", "OCCUPIED", "OUT_OF_SERVICE")
CONTACT_METHODS = ("PHONE", "SECURE_MESSAGE", "TELEMEDICINE")
TRANSPORT_MODES = ("GROUND_BLS", "GROUND_ALS", "AIR_ROTOR", "AIR_FIXED_WING")
CREW_CAPABILITIES = ("BLS", "ALS", "CCT", "CRITICAL_CARE")
PAYER_CHANNELS = ("PORTAL", "PHONE", "FAX")
DOCUMENT_CODES = ("H_AND_P", "LABS", "MED_RECONCILIATION", "CODE_STATUS",
                  "CONSENT", "TRANSFER_CERT")
REFUSAL_CATEGORIES = ("NO_BED_AVAILABLE", "CAPABILITY_UNAVAILABLE", "DIVERSION_ACTIVE",
                      "UNSTABLE_FOR_TRANSFER", "CAPACITY_EXCEEDED")
ARRIVAL_CONDITIONS = ("STABLE", "DETERIORATED", "CRITICAL_DECLINE")
REVIEW_OUTCOMES = ("CONCURRENCE", "MINOR_VARIANCE", "MAJOR_VARIANCE", "SENTINEL_EVENT")
DIVERSION_SCOPES = ("ALL_UNITS", "SPECIFIC_UNIT")
EXCEPTION_REASONS = ("UNSTABLE_EMC", "NO_PAYER_IDENTIFIABLE", "CLINICAL_URGENCY")

AUTO_DIVERSION_REASON = "AUTO_OCCUPANCY_SATURATION"

# ---------------------------------------------------------------------------
# Calculation constants (scaffold table 3)
# ---------------------------------------------------------------------------

HOLD_MINUTES = {"CRITICAL": 60, "EMERGENT": 120, "URGENT": 240, "STABLE": 480}

SPEED_MPH = {"GROUND_BLS": 40, "GROUND_ALS": 45, "AIR_ROTOR": 120, "AIR_FIXED_WING": 160}
MODE_OVERHEAD = {"GROUND_BLS": 10, "GROUND_ALS": 10, "AIR_ROTOR": 25, "AIR_FIXED_WING": 45}
CREW_BUFFER = {"BLS": 0, "ALS": 0, "CCT": 10, "CRITICAL_CARE": 15}

CREW_REQUIRED = {"CRITICAL": "CCT", "EMERGENT": "ALS", "URGENT": "BLS", "STABLE": "BLS"}
CREW_ORDER = {"BLS": 0, "ALS": 1, "CCT": 2, "CRITICAL_CARE": 3}
AIR_MINIMUM_MILES = {"AIR_ROTOR": 30, "AIR_FIXED_WING": 100}

SLA_MINUTES = {"EMTALA_APPLIES": 60, "EMERGENCY_EXCEPTION": 60, "EMTALA_NOT_APPLIES": 240}

CATEGORY_BASE = {"NO_BED_AVAILABLE": 30, "CAPABILITY_UNAVAILABLE": 25,
                 "DIVERSION_ACTIVE": 40, "UNSTABLE_FOR_TRANSFER": 10,
                 "CAPACITY_EXCEEDED": 20}
OBLIGATION_ADD = {"EMTALA_APPLIES": 50, "EMERGENCY_EXCEPTION": 20,
                  "EMTALA_NOT_APPLIES": 0, "UNDETERMINED": 0}

SATURATION_ENTER_PCT = Decimal("95.0")   # >= boundary: exactly 95.00 triggers
SATURATION_EXIT_PCT = Decimal("90.0")    # < boundary: exactly 90.00 does NOT lift
AUTO_DIVERSION_HOURS = 4

TIMELINESS_TARGET_MINUTES = 240
TIMELINESS_PENALTY_PER_MINUTE = Decimal("0.25")
W_TIMELINESS = Decimal("0.40")
W_DOCUMENTATION = Decimal("0.35")
W_PROTOCOL = Decimal("0.25")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_facility(fid):
    return db.facilities.get(fid)


def get_bed(bid):
    return db.beds.get(bid)


def get_physician(pid):
    return db.physicians.get(pid)


def get_case(cid):
    return db.transfer_cases.get(cid)


def screening_of(case_id):
    rows = find_by("emtala_screenings", transfer_case_id=case_id)
    return rows[0] if rows else None


def packet_of(case_id):
    rows = find_by("clinical_packets", transfer_case_id=case_id)
    return rows[0] if rows else None


def outcome_of(case_id):
    rows = find_by("transfer_outcomes", transfer_case_id=case_id)
    return rows[0] if rows else None


def refusal_count(case_id):
    return len(find_by("refusal_records", transfer_case_id=case_id))


def live_notification_of(case_id):
    """The case's at-most-one non-VOIDED InsuranceNotification, if any."""
    for row in find_by("insurance_notifications", transfer_case_id=case_id):
        if row["status"] != "VOIDED":
            return row
    return None


def current_round_communication(case):
    """The PhysicianCommunication of the case's current negotiation round."""
    for row in db.ordered("communications"):
        if (row["transfer_case_id"] == case["id"]
                and row["round"] == case["negotiation_round"]):
            return row
    return None


def latest_dispatch(case_id):
    rows = find_by("transport_dispatches", transfer_case_id=case_id)
    if not rows:
        return None
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))[-1]


def open_review_exists(case_id):
    for row in find_by("quality_reviews", transfer_case_id=case_id):
        if row["status"] in ("OPEN", "UNDER_REVIEW"):
            return True
    return False


# ---------------------------------------------------------------------------
# Derived fields: diversions, occupancy, packet statuses, notification lateness
# ---------------------------------------------------------------------------

def diversion_effective_status(event):
    """PRD 2.7: derived from the logical clock on every read, never stored."""
    if event["lifted_at"] is not None:
        return "LIFTED"
    if db.now >= event["ends_at"]:
        return "EXPIRED"
    if db.now >= event["starts_at"]:
        return "ACTIVE"
    return "SCHEDULED"


def facility_diversion_status(facility_id):
    """PRD 2.7 roll-up: HARD over ALL_UNITS, SOFT over SPECIFIC_UNIT, else OPEN."""
    events = find_by("diversion_events", facility_id=facility_id)
    active_all = any(diversion_effective_status(e) == "ACTIVE" and e["scope"] == "ALL_UNITS"
                     for e in events)
    if active_all:
        return "HARD_DIVERSION"
    active_unit = any(diversion_effective_status(e) == "ACTIVE" and e["scope"] == "SPECIFIC_UNIT"
                      for e in events)
    if active_unit:
        return "SOFT_DIVERSION"
    return "OPEN"


def facility_occupancy(facility_id):
    """PRD 2.6: operational excludes OUT_OF_SERVICE; unavailable is HELD+OCCUPIED;
    occupancy_pct is rounded half-up to 2dp and defined as 100.0 with no beds."""
    beds = find_by("beds", facility_id=facility_id)
    operational = sum(1 for b in beds if b["status"] != "OUT_OF_SERVICE")
    unavailable = sum(1 for b in beds if b["status"] in ("HELD", "OCCUPIED"))
    if operational == 0:
        pct = Decimal("100.00")
    else:
        pct = (Decimal(unavailable) * Decimal(100) / Decimal(operational)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    return operational, unavailable, pct


def evaluate_saturation(facility_id):
    """PRD 2.6 hysteresis, evaluated immediately after every occupancy recompute.

    >= 95.0 with no ACTIVE ALL_UNITS event: auto-create one (4h window).
    < 90.0: lift every auto-created ACTIVE ALL_UNITS event.
    [90.0, 95.0): no automatic change in either direction.
    """
    _, _, pct = facility_occupancy(facility_id)
    events = find_by("diversion_events", facility_id=facility_id)
    if pct >= SATURATION_ENTER_PCT:
        active_all = any(diversion_effective_status(e) == "ACTIVE" and e["scope"] == "ALL_UNITS"
                         for e in events)
        if not active_all:
            new_row("diversion_events", {
                "facility_id": facility_id,
                "scope": "ALL_UNITS",
                "unit_type": None,
                "starts_at": db.now,
                "ends_at": db.now + timedelta(hours=AUTO_DIVERSION_HOURS),
                "reason": AUTO_DIVERSION_REASON,
                "auto_created": True,
                "lifted_at": None,
            })
    elif pct < SATURATION_EXIT_PCT:
        for event in events:
            if (event["auto_created"] and event["scope"] == "ALL_UNITS"
                    and diversion_effective_status(event) == "ACTIVE"):
                event["lifted_at"] = db.now
                bump(event)


def document_status(packet):
    received = set(packet["received_documents"])
    required = set(packet["required_documents"])
    return "DOCUMENTS_COMPLETE" if required.issubset(received) else "INCOMPLETE"


def imaging_status(packet):
    exchanged = set(packet["exchanged_study_refs"])
    needed = set(s["study_ref"] for s in packet["imaging_studies"])
    return "IMAGING_COMPLETE" if needed.issubset(exchanged) else "IMAGING_PENDING"


def overall_status(packet):
    if document_status(packet) == "DOCUMENTS_COMPLETE" and imaging_status(packet) == "IMAGING_COMPLETE":
        return "READY"
    return "INCOMPLETE"


def notification_is_late(notification):
    """PRD 3.6: strictly greater than sla_due_at; exactly on time is on time;
    false for every status other than NOTIFIED."""
    return (notification["status"] == "NOTIFIED"
            and notification["notified_at"] is not None
            and notification["notified_at"] > notification["sla_due_at"])


def screening_determination(has_emc, is_stabilized):
    if not has_emc:
        return "EMTALA_NOT_APPLIES"
    if is_stabilized:
        return "EMTALA_APPLIES"
    return "EMERGENCY_EXCEPTION"


# ---------------------------------------------------------------------------
# Bed selector (PRD 3.4)
# ---------------------------------------------------------------------------

def select_bed(case):
    """Eligibility filter + ranking + tie-break; None when the pool is empty."""
    beds = []
    for bed in find_by("beds", facility_id=case["receiving_facility_id"]):
        if bed["status"] != "AVAILABLE":
            continue
        if bed["unit_type"] != case["required_unit_type"]:
            continue
        if case["requires_isolation"] and not bed["isolation_capable"]:
            continue
        beds.append(bed)
    if not beds:
        return None

    def rank(bed):
        # Isolation preservation: only when the case does not require isolation,
        # non-isolation beds rank ahead of isolation-capable ones.
        if case["requires_isolation"]:
            iso_rank = 0
        else:
            iso_rank = 0 if not bed["isolation_capable"] else 1
        return (iso_rank, bed["created_at"], bed["bed_code"], bed["_seq"])

    beds.sort(key=rank)
    return beds[0]


# ---------------------------------------------------------------------------
# Lazy bed-hold expiry (PRD 3.4)
# ---------------------------------------------------------------------------

def _expire_hold(hold):
    """ACTIVE -> EXPIRED with the full side-effect chain of PRD 3.4."""
    case = get_case(hold["transfer_case_id"])
    hold["status"] = "EXPIRED"
    hold["release_reason"] = "EXPIRED"
    bump(hold)
    bed = get_bed(hold["bed_id"])
    if bed is not None and bed["status"] == "HELD":
        bed["status"] = "AVAILABLE"
        bump(bed)
    if case is not None and case["active_bed_hold_id"] == hold["id"]:
        case["active_bed_hold_id"] = None
        bump(case)
    evaluate_saturation(hold_facility_id(hold))


def hold_facility_id(hold):
    bed = get_bed(hold["bed_id"])
    return bed["facility_id"] if bed is not None else None


def sweep_hold_expiries():
    """Half-open occupation: at clock >= hold_expires_at an ACTIVE hold of a
    case still in ACCEPTED flips to EXPIRED.  Holds of cases that have left
    ACCEPTED never expire.  Applied lazily on any read or write that touches
    holds; the clock endpoint itself is exempt (moving the clock rewrites
    nothing eagerly)."""
    for hold in db.ordered("bed_holds"):
        if hold["status"] != "ACTIVE":
            continue
        if db.now < hold["hold_expires_at"]:
            continue
        case = get_case(hold["transfer_case_id"])
        if case is None or case["status"] != "ACCEPTED":
            continue
        _expire_hold(hold)


# ---------------------------------------------------------------------------
# Transport estimates (PRD 3.7) - integer minutes, ceil exactly where stated
# ---------------------------------------------------------------------------

def _ceil_fraction(value):
    return -(-value.numerator // value.denominator)


def transport_estimates(mode, crew_capability, distance_miles, acuity_level):
    distance = Fraction(str(distance_miles))
    base = _ceil_fraction(distance * 60 / SPEED_MPH[mode])
    optimistic = base + MODE_OVERHEAD[mode]
    conservative = (_ceil_fraction(Fraction(base * 5, 4))
                    + MODE_OVERHEAD[mode]
                    + CREW_BUFFER[crew_capability]
                    + (10 if acuity_level == "CRITICAL" else 0))
    return optimistic, conservative


# ---------------------------------------------------------------------------
# Refusal EMTALA risk (PRD 3.3)
# ---------------------------------------------------------------------------

def refusal_risk(refusal_category, emtala_obligation, prior_refusals):
    score = (CATEGORY_BASE[refusal_category]
             + OBLIGATION_ADD[emtala_obligation]
             + 10 * min(prior_refusals, 3))
    if score >= 70:
        flag = "HIGH"
    elif score >= 40:
        flag = "ELEVATED"
    else:
        flag = "LOW"
    return score, flag


# ---------------------------------------------------------------------------
# Quality review scoring (PRD 3.9) - pinned nested rounding order
# ---------------------------------------------------------------------------

def _round0(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_review_scores(case):
    outcome = outcome_of(case["id"])
    if outcome is None:
        timeliness = 0
    else:
        over = max(0, outcome["door_to_arrival_minutes"] - TIMELINESS_TARGET_MINUTES)
        timeliness = _round0(max(Decimal(0), Decimal(100) - Decimal(over) * TIMELINESS_PENALTY_PER_MINUTE))

    packet = packet_of(case["id"])
    if packet is None:
        documentation = 0
    else:
        required = set(packet["required_documents"])
        if not required:
            documentation = 100
        else:
            inter = len(required & set(packet["received_documents"]))
            documentation = _round0(Decimal(100 * inter) / Decimal(len(required)))

    refusals = refusal_count(case["id"])
    any_late = any(notification_is_late(n)
                   for n in find_by("insurance_notifications", transfer_case_id=case["id"]))
    any_expired = any(h["status"] == "EXPIRED"
                      for h in find_by("bed_holds", transfer_case_id=case["id"]))
    protocol = _round0(max(0, 100
                           - 20 * refusals
                           - 30 * (1 if any_late else 0)
                           - 40 * (1 if any_expired else 0)))

    composite = (W_TIMELINESS * timeliness
                 + W_DOCUMENTATION * documentation
                 + W_PROTOCOL * protocol).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return timeliness, documentation, protocol, float(composite)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(row):
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
        "updated_at": render_instant(row["updated_at"]),
        "version": row["version"],
    }


def _append_only(row):
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
    }


def serialize_facility(row):
    operational, unavailable, pct = facility_occupancy(row["id"])
    data = _common(row)
    data.update({
        "name": row["name"],
        "facility_code": row["facility_code"],
        "trauma_level": row["trauma_level"],
        "capabilities": list(row["capabilities"]),
        "diversion_status": facility_diversion_status(row["id"]),
        "operational_bed_count": operational,
        "unavailable_bed_count": unavailable,
        "occupancy_pct": float(pct),
    })
    return data


def serialize_bed(row):
    data = _common(row)
    data.update({
        "facility_id": row["facility_id"],
        "bed_code": row["bed_code"],
        "unit_type": row["unit_type"],
        "isolation_capable": row["isolation_capable"],
        "status": row["status"],
    })
    return data


def serialize_physician(row):
    data = _common(row)
    data.update({
        "full_name": row["full_name"],
        "facility_id": row["facility_id"],
        "specialty": row["specialty"],
        "is_on_call": row["is_on_call"],
    })
    return data


def serialize_case(row):
    data = _common(row)
    data.update({
        "patient_ref": row["patient_ref"],
        "sending_facility_id": row["sending_facility_id"],
        "sending_physician_id": row["sending_physician_id"],
        "receiving_facility_id": row["receiving_facility_id"],
        "receiving_physician_id": row["receiving_physician_id"],
        "acuity_level": row["acuity_level"],
        "required_unit_type": row["required_unit_type"],
        "requires_isolation": row["requires_isolation"],
        "required_capability": row["required_capability"],
        "status": row["status"],
        "emtala_obligation": row["emtala_obligation"],
        "emtala_determined_at": render_instant(row["emtala_determined_at"]),
        "active_bed_hold_id": row["active_bed_hold_id"],
        "negotiation_round": row["negotiation_round"],
        "refusal_count": refusal_count(row["id"]),
    })
    return data


def serialize_screening(row):
    data = _common(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "has_emergency_medical_condition": row["has_emergency_medical_condition"],
        "is_stabilized": row["is_stabilized"],
        "benefits_outweigh_risks": row["benefits_outweigh_risks"],
        "physician_certification": row["physician_certification"],
        "determination": screening_determination(
            row["has_emergency_medical_condition"], row["is_stabilized"]),
        "status": row["status"],
        "certified_at": render_instant(row["certified_at"]),
        "amendment_count": row["amendment_count"],
    })
    return data


def serialize_communication(row):
    data = _append_only(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "from_physician_id": row["from_physician_id"],
        "to_physician_id": row["to_physician_id"],
        "round": row["round"],
        "contact_method": row["contact_method"],
        "notes": row["notes"],
        "outcome": row["outcome"],
        "responded_at": render_instant(row["responded_at"]),
    })
    return data


def serialize_bed_hold(row):
    data = _common(row)
    data.update({
        "bed_id": row["bed_id"],
        "transfer_case_id": row["transfer_case_id"],
        "status": row["status"],
        "hold_started_at": render_instant(row["hold_started_at"]),
        "hold_expires_at": render_instant(row["hold_expires_at"]),
        "release_reason": row["release_reason"],
    })
    return data


def serialize_dispatch(row):
    data = _common(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "mode": row["mode"],
        "crew_capability": row["crew_capability"],
        "distance_miles": row["distance_miles"],
        "estimated_minutes_optimistic": row["estimated_minutes_optimistic"],
        "estimated_minutes_conservative": row["estimated_minutes_conservative"],
        "actual_duration_minutes": row["actual_duration_minutes"],
        "status": row["status"],
        "dispatched_at": render_instant(row["dispatched_at"]),
        "departed_at": render_instant(row["departed_at"]),
        "arrived_at": render_instant(row["arrived_at"]),
    })
    return data


def serialize_notification(row):
    data = _common(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "payer_id": row["payer_id"],
        "channel": row["channel"],
        "sla_due_at": render_instant(row["sla_due_at"]),
        "notified_at": render_instant(row["notified_at"]),
        "status": row["status"],
        "is_late": notification_is_late(row),
        "exception_reason": row["exception_reason"],
    })
    return data


def serialize_packet(row):
    data = _common(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "required_documents": list(row["required_documents"]),
        "received_documents": list(row["received_documents"]),
        "imaging_studies": [dict(s) for s in row["imaging_studies"]],
        "exchanged_study_refs": list(row["exchanged_study_refs"]),
        "document_status": document_status(row),
        "imaging_status": imaging_status(row),
        "overall_status": overall_status(row),
    })
    return data


def serialize_refusal_record(row):
    data = _append_only(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "facility_id": row["facility_id"],
        "refusing_physician_id": row["refusing_physician_id"],
        "refusal_category": row["refusal_category"],
        "narrative": row["narrative"],
        "emtala_risk_score": row["emtala_risk_score"],
        "emtala_risk_flag": row["emtala_risk_flag"],
        "round": row["round"],
    })
    return data


def serialize_outcome(row):
    data = _append_only(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "arrival_condition": row["arrival_condition"],
        "deterioration_en_route": row["deterioration_en_route"],
        "receiving_physician_confirmed": row["receiving_physician_confirmed"],
        "door_to_arrival_minutes": row["door_to_arrival_minutes"],
        "recorded_at": render_instant(row["recorded_at"]),
    })
    return data


def serialize_review(row):
    data = _common(row)
    data.update({
        "transfer_case_id": row["transfer_case_id"],
        "trigger": row["trigger"],
        "status": row["status"],
        "reviewer_physician_id": row["reviewer_physician_id"],
        "timeliness_score": row["timeliness_score"],
        "documentation_score": row["documentation_score"],
        "protocol_score": row["protocol_score"],
        "composite_score": row["composite_score"],
        "outcome": row["outcome"],
        "findings": row["findings"],
    })
    return data


def serialize_diversion_event(row):
    data = _common(row)
    data.update({
        "facility_id": row["facility_id"],
        "scope": row["scope"],
        "unit_type": row["unit_type"],
        "starts_at": render_instant(row["starts_at"]),
        "ends_at": render_instant(row["ends_at"]),
        "reason": row["reason"],
        "auto_created": row["auto_created"],
        "lifted_at": render_instant(row["lifted_at"]),
        "effective_status": diversion_effective_status(row),
    })
    return data
