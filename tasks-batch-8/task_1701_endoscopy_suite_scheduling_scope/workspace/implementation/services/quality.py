"""Quality-metric snapshot and room-utilization computations (PRD 3.9)."""
from decimal import Decimal

from db import db
from services.booking_svc import BLOCK_HOLDING_STATUSES, patient_age_at_start
from util import mean_half_up_1dp, rate_half_up_1dp, round_half_up_1dp_decimal

ADR_MIN_AGE = 45
ROOM_OPEN_MINUTES_PER_DAY = 480


def _completed_in_period(provider_id, period_start, period_end):
    return [
        b for b in db["bookings"].values()
        if b["provider_id"] == provider_id
        and b["status"] == "COMPLETED"
        and b["actual_end"] is not None
        and period_start <= b["actual_end"] <= period_end
    ]


def compute_quality_report(provider_id, period_start, period_end, metric_variant):
    """Compute all metrics once, into the immutable snapshot."""
    completed = _completed_in_period(provider_id, period_start, period_end)

    # --- adenoma_detection_rate (variant-sensitive) ---
    candidates = []
    for b in completed:
        ptype = db["procedure_types"].get(b["procedure_type_id"])
        if ptype is not None and ptype["adr_relevant"]:
            candidates.append(b)
    if metric_variant == "STRICT":
        denominator_rows = []
        for b in candidates:
            patient = db["patients"].get(b["patient_id"])
            age = patient_age_at_start(patient, b["scheduled_start"]) if patient else 0
            if (
                b["indication"] == "SCREENING"
                and age >= ADR_MIN_AGE
                and b["cecum_intubated"] is True
                and b["prep_status"] == "PREP_ADEQUATE"
            ):
                denominator_rows.append(b)
    else:  # EXPANDED
        denominator_rows = list(candidates)
    adr_denominator = len(denominator_rows)
    adr_numerator = sum(
        1 for b in denominator_rows if (b["adenomas_detected"] or 0) >= 1
    )
    adenoma_detection_rate = rate_half_up_1dp(adr_numerator, adr_denominator)

    # --- withdrawal_time_average (variant-invariant) ---
    withdrawal_rows = []
    for b in completed:
        ptype = db["procedure_types"].get(b["procedure_type_id"])
        if ptype is None or not ptype["colonoscopy_family"]:
            continue
        if b["cecum_intubated"] is not True:
            continue
        if (b["adenomas_detected"] or 0) != 0:
            continue
        has_specimen = any(
            s["booking_id"] == b["id"] for s in db["specimens"].values()
        )
        if has_specimen:
            continue
        withdrawal_rows.append(b)
    withdrawal_sample_size = len(withdrawal_rows)
    withdrawal_time_avg_seconds = mean_half_up_1dp(
        [b["withdrawal_time_seconds"] for b in withdrawal_rows]
    )

    # --- cecal_intubation_rate ---
    cir_rows = [
        b for b in completed
        if (db["procedure_types"].get(b["procedure_type_id"]) or {}).get("colonoscopy_family")
    ]
    cecal_intubation_rate = rate_half_up_1dp(
        sum(1 for b in cir_rows if b["cecum_intubated"] is True),
        len(cir_rows),
    )

    # --- prep_adequacy_rate: any booking of the provider with actual_end in
    # period and an assessed prep axis (booking-axis status unrestricted) ---
    assessed = [
        b for b in db["bookings"].values()
        if b["provider_id"] == provider_id
        and b["actual_end"] is not None
        and period_start <= b["actual_end"] <= period_end
        and b["prep_status"] in ("PREP_ADEQUATE", "PREP_INADEQUATE")
    ]
    prep_adequacy_rate = rate_half_up_1dp(
        sum(1 for b in assessed if b["prep_status"] == "PREP_ADEQUATE"),
        len(assessed),
    )

    return {
        "adenoma_detection_rate": adenoma_detection_rate,
        "adr_numerator": adr_numerator,
        "adr_denominator": adr_denominator,
        "withdrawal_time_avg_seconds": withdrawal_time_avg_seconds,
        "withdrawal_sample_size": withdrawal_sample_size,
        "cecal_intubation_rate": cecal_intubation_rate,
        "prep_adequacy_rate": prep_adequacy_rate,
    }


def room_utilization_report(day):
    """room_utilization_report: per-room percentages rounded FIRST, then averaged.

    The rounding order is pinned (normative): round each room to 1 decimal,
    then average, then round once more.
    """
    rooms = sorted(db["rooms"].values(), key=lambda r: (r["created_at"], r.get("_seq", 0)))
    room_entries = []
    for room in rooms:
        occupied = 0
        for b in db["bookings"].values():
            if b["room_id"] != room["id"]:
                continue
            if b["status"] not in BLOCK_HOLDING_STATUSES:
                continue
            if b["scheduled_start"].date() != day:
                continue
            occupied += int((b["room_block_end"] - b["scheduled_start"]).total_seconds() // 60)
        pct = round_half_up_1dp_decimal(
            Decimal(100) * Decimal(occupied) / Decimal(ROOM_OPEN_MINUTES_PER_DAY)
        )
        room_entries.append({
            "room_id": room["id"],
            "occupied_minutes": occupied,
            "utilization_pct": float(pct),
        })
    if room_entries:
        unit = round_half_up_1dp_decimal(
            sum(Decimal(str(e["utilization_pct"])) for e in room_entries)
            / Decimal(len(room_entries))
        )
        unit_pct = float(unit)
    else:
        unit_pct = None
    return {
        "date": day.isoformat(),
        "open_minutes_per_room": ROOM_OPEN_MINUTES_PER_DAY,
        "unit_utilization_pct": unit_pct,
        "rooms": room_entries,
    }
