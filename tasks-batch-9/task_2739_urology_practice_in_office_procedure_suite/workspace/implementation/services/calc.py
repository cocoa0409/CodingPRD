"""The six pinned calculations (PRD sections 3.2, 3.3, 3.4, 3.6, 3.7, 3.8, 3.9)."""

from decimal import Decimal

import constants
import db
import util
from db import store

OCCUPYING_STATUSES = ("SCHEDULED", "IN_ROOM", "COMPLETED")


# ------------------------------------------------------------ occupancy window
def compute_window(start_at, ptype, room, patient):
    """Reads exactly one procedure type, one room and one patient, at mutation time."""
    anticoag_extra = (
        constants.ANTICOAG_BIOPSY_EXTRA_MINUTES
        if (patient["anticoagulant_flag"] and ptype["code"] == "PROSTATE_BIOPSY")
        else 0
    )
    renal_extra = (
        constants.RENAL_ANTIBIOTIC_EXTRA_MINUTES
        if (patient["egfr"] < constants.RENAL_EGFR_THRESHOLD and ptype["requires_antibiotic"])
        else 0
    )
    procedure_minutes = ptype["base_minutes"] + anticoag_extra + renal_extra

    multiplier = 2 if ptype["cleanup_class"] == "HIGH" else 1
    product = room["turnover_minutes"] * multiplier
    # The floor applies to the multiplied product, not to the final figure.
    working = max(product, constants.TURNOVER_FLOOR_MINUTES)
    turnover_minutes = working + (
        constants.SCOPE_TURNOVER_EXTRA_MINUTES if ptype["requires_scope"] else 0
    )

    scheduled_end_at = util.add_minutes(start_at, procedure_minutes)
    block_end_at = util.add_minutes(scheduled_end_at, turnover_minutes)

    return {
        "scheduled_start_at": start_at,
        "procedure_minutes": procedure_minutes,
        "turnover_minutes": turnover_minutes,
        "scheduled_end_at": scheduled_end_at,
        "block_end_at": block_end_at,
    }


def apply_window(case, window):
    case.update(window)
    return case


# ----------------------------------------------------------- interval geometry
def _occupying_others(case_id):
    return [
        row
        for row in store.all_rows("cases")
        if row["id"] != case_id and row["schedule_status"] in OCCUPYING_STATUSES
    ]


def room_conflict(case_id, room_id, start_at, block_end_at):
    """Room occupancy is the half-open interval [scheduled_start_at, block_end_at)."""
    for other in _occupying_others(case_id):
        if other["room_id"] != room_id:
            continue
        if start_at < other["block_end_at"] and other["scheduled_start_at"] < block_end_at:
            return True
    return False


def provider_conflict(case_id, provider_id, start_at, end_at):
    """Provider occupancy is the closed interval [start - 10 min, end + 10 min]."""
    buffer_minutes = constants.PROVIDER_BUFFER_MINUTES
    lo = util.add_minutes(start_at, -buffer_minutes)
    hi = util.add_minutes(end_at, buffer_minutes)
    for other in _occupying_others(case_id):
        if other["primary_provider_id"] != provider_id:
            continue
        other_lo = util.add_minutes(other["scheduled_start_at"], -buffer_minutes)
        other_hi = util.add_minutes(other["scheduled_end_at"], buffer_minutes)
        if lo <= other_hi and other_lo <= hi:
            return True
    return False


# --------------------------------------------------------- antibiotic selection
def eligible_agents(ptype, patient):
    ranking = (
        constants.ANTIBIOTIC_PROTOCOL_RANK.get(ptype["code"], {})
        if ptype["requires_antibiotic"]
        else {}
    )
    eligible = {}
    for name, entry in constants.ANTIBIOTIC_CATALOG.items():
        if name not in ranking:
            continue
        if entry["drug_class"] == patient["antibiotic_allergy_class"]:
            continue
        if patient["egfr"] < entry["min_egfr"]:
            continue
        eligible[name] = ranking[name]
    return eligible


def select_auto_agent(eligible):
    """Lowest protocol rank; ties broken by agent name ascending."""
    return sorted(eligible.items(), key=lambda kv: (kv[1], kv[0]))[0][0]


def dose_for(agent, patient):
    """Renal adjustment first, then snapped to the 25 mg dispensing increment."""
    base = Decimal(constants.ANTIBIOTIC_CATALOG[agent]["base_dose_mg"])
    factor = Decimal("1") if patient["egfr"] >= constants.RENAL_EGFR_THRESHOLD else Decimal("0.5")
    raw = base * factor
    increment = Decimal(constants.DOSE_INCREMENT_MG)
    return util.round_half_up(raw / increment) * constants.DOSE_INCREMENT_MG


# ------------------------------------------------------- notification clock
def escalation_due_at(anchor_at, grade, attempt_count):
    """Four pinned steps; the weekend test reads the provisional instant only, once."""
    window_hours = constants.GRADE_WINDOW_HOURS[grade or "INSUFFICIENT"]
    provisional = util.add_hours(anchor_at, window_hours)
    weekend_extension = constants.WEEKEND_EXTENSION_HOURS if util.is_weekend(provisional) else 0
    backoff = constants.NOTIFICATION_BACKOFF_HOURS * max(0, attempt_count - 1)
    return util.add_hours(provisional, weekend_extension + backoff)


def recompute_escalation(specimen):
    anchor = specimen["result_at"] or specimen["_notification_anchor_at"]
    if anchor is None:
        return
    specimen["escalation_due_at"] = escalation_due_at(
        anchor, specimen["pathology_result"], specimen["notification_attempt_count"]
    )


# ------------------------------------------------------------- recall due dates
def interval_months(protocol, risk_tier):
    return constants.RECALL_INTERVAL_MONTHS[protocol][risk_tier]


def protocol_anchored_due_on(recall):
    return util.add_months(recall["anchor_date"], recall["interval_months"])


def event_anchored_due_on(recall):
    """Returns (due_on, due_basis) under the EVENT_ANCHORED variant."""
    codes = constants.PROTOCOL_SURVEILLANCE_TYPES[recall["protocol"]]
    candidates = []
    for case in store.all_rows("cases"):
        if case["patient_id"] != recall["patient_id"]:
            continue
        if case["schedule_status"] != "COMPLETED":
            continue
        ptype = store.get("procedure_types", case["procedure_type_id"])
        if ptype is None or ptype["code"] not in codes:
            continue
        candidates.append(case)
    if not candidates:
        return util.add_months(recall["anchor_date"], recall["interval_months"]), "PROTOCOL_ANCHORED"
    anchor_case = max(candidates, key=lambda c: (c["scheduled_start_at"], c["created_at"], c["_seq"]))
    anchor_date = anchor_case["scheduled_start_at"].date()
    return util.add_months(anchor_date, recall["interval_months"]), "EVENT_ANCHORED"


def lapse_days_for(due_on, clock_date):
    return max(0, util.whole_days_between(due_on, clock_date))


# --------------------------------------------------------- consignment billing
def _lines_for(lot, states):
    return [
        case
        for case in store.all_rows("cases")
        if case["device_lot_id"] == lot["id"] and case["device_state"] in states
    ]


def rebill(lot, basis):
    """Per-line rounding first, then summation. Rounding once at the end is not the rule."""
    markup = Decimal(constants.CONSIGNMENT_MARKUP)
    if basis == "PROVISIONAL":
        factor = markup
        states = ("RESERVED",)
    else:
        rebate = (
            Decimal(constants.CONSIGNMENT_VOLUME_REBATE)
            if lot["quantity_consumed"] >= constants.CONSIGNMENT_REBATE_THRESHOLD
            else Decimal("0")
        )
        factor = markup - rebate
        states = ("CONSUMED", "WASTED")

    unit_price = Decimal(lot["unit_price_cents"])
    total = 0
    for case in _lines_for(lot, states):
        line = unit_price * factor * Decimal(case["device_quantity"])
        total += util.round_half_up(line)
    lot["billed_amount_cents"] = total
    lot["billing_basis"] = basis
    derive_billing_status(lot)
    return lot


def derive_billing_status(lot):
    """Ordered tests over the lot's own unit counters."""
    if (
        lot["quantity_returned"] == lot["quantity_received"]
        and lot["quantity_consumed"] == 0
        and lot["quantity_wasted"] == 0
    ):
        lot["billing_status"] = "RETURNED"
    elif (
        lot["quantity_available"] == 0
        and lot["quantity_reserved"] == 0
        and (lot["quantity_consumed"] + lot["quantity_wasted"]) >= 1
    ):
        lot["billing_status"] = "INVOICED"
    elif (lot["quantity_consumed"] + lot["quantity_wasted"]) >= 1:
        lot["billing_status"] = "PARTIALLY_INVOICED"
    else:
        lot["billing_status"] = "CONSIGNED"
    return lot["billing_status"]


# --------------------------------------------------------------- derived counts
def outstanding_recall_count(patient_id):
    return len(
        [
            r
            for r in store.table("recalls").values()
            if r["patient_id"] == patient_id and r["status"] in ("SCHEDULED_DUE", "OVERDUE")
        ]
    )


def open_notification_count(patient_id):
    case_ids = set(
        c["id"] for c in store.table("cases").values() if c["patient_id"] == patient_id
    )
    return len(
        [
            s
            for s in store.table("specimens").values()
            if s["case_id"] in case_ids
            and s["notification_status"] in ("PENDING", "ATTEMPTED", "ESCALATED")
        ]
    )


def occupied_block_count(room_id):
    return len(
        [
            c
            for c in store.table("cases").values()
            if c["room_id"] == room_id and c["schedule_status"] in OCCUPYING_STATUSES
        ]
    )


# ------------------------------------------------------------- readiness gates
def _accreditation_lapsed(expires_on, clock_date):
    return expires_on is None or expires_on < clock_date


def blocking_reason_codes(case):
    """The ordered subsequence of gates the case currently fails."""
    if case["schedule_status"] in ("IN_ROOM", "COMPLETED", "CANCELLED", "NO_SHOW"):
        return []

    ptype = store.get("procedure_types", case["procedure_type_id"])
    room = store.get("rooms", case["room_id"])
    provider = store.get("providers", case["primary_provider_id"])
    scope = store.get("scopes", case["scope_asset_id"]) if case["scope_asset_id"] else None
    clock = store.now()
    clock_date = clock.date()

    failures = set()

    if case["clearance_status"] not in ("CLEARED", "PREP_WAIVED"):
        failures.add("CLEARANCE_NOT_GRANTED")

    room_accredited_type = room is not None and room["room_type"] in constants.ACCREDITED_ROOM_TYPES
    if room_accredited_type and _accreditation_lapsed(room["accreditation_expires_on"], clock_date):
        failures.add("ROOM_ACCREDITATION_LAPSED")
    if room_accredited_type and (
        provider is None
        or _accreditation_lapsed(provider["ultrasound_accreditation_expires_on"], clock_date)
    ):
        failures.add("PROVIDER_ACCREDITATION_LAPSED")

    if ptype is not None and ptype["requires_antibiotic"]:
        administered = [
            o
            for o in store.table("antibiotic_orders").values()
            if o["case_id"] == case["id"] and o["status"] == "ADMINISTERED"
        ]
        if not administered:
            failures.add("ANTIBIOTIC_NOT_ADMINISTERED")

    if ptype is not None and ptype["requires_scope"]:
        if (
            scope is None
            or scope["status"] != "IN_USE"
            or scope["hld_pass_at"] is None
            or scope["reprocess_due_at"] is not None
        ):
            failures.add("SCOPE_NOT_READY")

    earliest = util.add_minutes(case["scheduled_start_at"], -constants.CHECKIN_EARLIEST_MINUTES)
    if clock < earliest:
        failures.add("CHECKIN_TOO_EARLY")

    if ptype is not None and ptype["consignment_required"] and case["device_state"] != "RESERVED":
        failures.add("DEVICE_NOT_RESERVED")

    return [code for code in constants.GATE_PRIORITY_ORDER if code in failures]
