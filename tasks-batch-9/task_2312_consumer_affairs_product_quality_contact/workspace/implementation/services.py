"""Shared business operations and the cross-entity cascades of PRD §2.8 / §3."""

from decimal import Decimal

import calc
import serializers as ser
from common import (
    base_record,
    dec,
    err,
    now,
    round_half_up,
    sort_records,
    store,
    touch,
)

LIVE_REMEDY_STATES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED")


# ---------------------------------------------------------------------------
# topology helpers
# ---------------------------------------------------------------------------
def line_of_lot(lot):
    return store.production_lines.get(lot.get("production_line_id"))


def plant_of_lot(lot):
    line = line_of_lot(lot)
    if line is None:
        return None
    return store.plants.get(line.get("plant_id"))


def plant_of_line(line):
    if line is None:
        return None
    return store.plants.get(line.get("plant_id"))


def lots_of_line(line_id):
    return [l for l in store.production_lots.values() if l.get("production_line_id") == line_id]


def lots_of_plant(plant_id):
    line_ids = {
        l["id"] for l in store.production_lines.values() if l.get("plant_id") == plant_id
    }
    return [
        l for l in store.production_lots.values() if l.get("production_line_id") in line_ids
    ]


def lots_in_signal_scope(signal):
    level = signal["scope_level"]
    if level == "LOT":
        lot = store.production_lots.get(signal.get("lot_id"))
        return [lot] if lot is not None else []
    if level == "LINE":
        return lots_of_line(signal.get("production_line_id"))
    return lots_of_plant(signal.get("plant_id"))


def complaints_of_contact(contact_id):
    return [c for c in store.complaints.values() if c.get("contact_id") == contact_id]


def kits_of_complaint(complaint_id):
    return sort_records(
        [k for k in store.sample_kits.values() if k.get("complaint_id") == complaint_id]
    )


def remedies_of_complaint(complaint_id):
    return sort_records(
        [r for r in store.remedies.values() if r.get("complaint_id") == complaint_id]
    )


def reports_of_complaint(complaint_id):
    return sort_records(
        [r for r in store.regulatory_reports.values() if r.get("complaint_id") == complaint_id]
    )


def active_report_of_complaint(complaint_id):
    for report in reports_of_complaint(complaint_id):
        if report["status"] != "WITHDRAWN":
            return report
    return None


def memberships_of_signal(signal_id):
    return sort_records(
        [m for m in store.signal_memberships.values() if m.get("trend_signal_id") == signal_id]
    )


def memberships_of_complaint(complaint_id):
    return sort_records(
        [m for m in store.signal_memberships.values() if m.get("complaint_id") == complaint_id]
    )


def member_complaints(signal_id):
    out = []
    for membership in memberships_of_signal(signal_id):
        complaint = store.complaints.get(membership["complaint_id"])
        if complaint is not None:
            out.append(complaint)
    return out


def signals_containing_complaint(complaint_id):
    signal_ids = {m["trend_signal_id"] for m in memberships_of_complaint(complaint_id)}
    return [store.trend_signals[s] for s in signal_ids if s in store.trend_signals]


def signals_covering_lot(lot):
    """Signals whose scope contains this lot, at any scope level."""
    line = line_of_lot(lot)
    plant_id = line.get("plant_id") if line is not None else None
    out = []
    for signal in store.trend_signals.values():
        level = signal["scope_level"]
        if level == "LOT" and signal.get("lot_id") == lot["id"]:
            out.append(signal)
        elif level == "LINE" and line is not None and signal.get("production_line_id") == line["id"]:
            out.append(signal)
        elif level == "PLANT" and plant_id is not None and signal.get("plant_id") == plant_id:
            out.append(signal)
    return out


# ---------------------------------------------------------------------------
# lot hold provenance
# ---------------------------------------------------------------------------
def hold_lot(lot, source):
    """Move a RELEASED lot to HOLD, recording which authority imposed it."""
    sources = lot.setdefault("_hold_sources", set())
    sources.add(source)
    if lot["release_status"] == "RELEASED":
        lot["release_status"] = "HOLD"
        touch(lot)


def release_lot(lot, clear_all=True):
    if clear_all:
        lot["_hold_sources"] = set()
    if lot["release_status"] == "HOLD":
        lot["release_status"] = "RELEASED"
        touch(lot)


def drop_hold_source(lot, source):
    sources = lot.setdefault("_hold_sources", set())
    sources.discard(source)
    if not sources and lot["release_status"] == "HOLD":
        lot["release_status"] = "RELEASED"
        touch(lot)


# ---------------------------------------------------------------------------
# batch-code resolution (PRD §3.2)
# ---------------------------------------------------------------------------
def resolve_batch_code(complaint, reported_batch_code, pack_code_date):
    """Applies resolution to the complaint in place and returns the previous lot id."""
    previous_lot_id = complaint.get("lot_id")

    complaint["reported_batch_code"] = reported_batch_code
    if pack_code_date is not None:
        complaint["pack_code_date"] = pack_code_date

    if not reported_batch_code:
        complaint["product_identification_status"] = "UNRESOLVED"
        complaint["lot_id"] = None
        return previous_lot_id

    normalized = calc.normalize_batch_code(reported_batch_code)
    candidates = [
        l for l in store.production_lots.values() if l["normalized_batch_code"] == normalized
    ]
    if not candidates:
        complaint["product_identification_status"] = "UNRESOLVED"
        complaint["lot_id"] = None
        return previous_lot_id

    if len(candidates) > 1:
        effective_date = pack_code_date if pack_code_date is not None else complaint.get(
            "pack_code_date"
        )
        narrowed = []
        if effective_date is not None:
            narrowed = [l for l in candidates if l["code_date"] == effective_date]
        if len(narrowed) != 1:
            raise err(
                "ERR_BATCH_CODE_AMBIGUOUS",
                "the reported batch code matches more than one production lot",
            )
        chosen = narrowed[0]
    else:
        chosen = candidates[0]

    complaint["product_identification_status"] = "RESOLVED"
    complaint["lot_id"] = chosen["id"]
    complaint["product_id"] = chosen["product_id"]
    return previous_lot_id


# ---------------------------------------------------------------------------
# custody projection
# ---------------------------------------------------------------------------
def refresh_custody_projection(kit):
    status, transit_hours = calc.custody_projection(kit)
    changed = False
    if kit.get("chain_integrity_status") != status:
        kit["chain_integrity_status"] = status
        changed = True
    if transit_hours is not None and kit.get("transit_hours") != transit_hours:
        kit["transit_hours"] = transit_hours
        changed = True
    return changed


def append_custody_event(kit, event_type, occurred_at, actor_label, seal_id_observed, notes):
    event = base_record(with_version=False)
    event.update(
        {
            "sample_kit_id": kit["id"],
            "sequence_no": kit.get("custody_event_count", 0) + 1,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "actor_label": actor_label,
            "seal_id_observed": seal_id_observed,
            "notes": notes,
        }
    )
    store.custody_events[event["id"]] = event
    return event


# ---------------------------------------------------------------------------
# goodwill ledger
# ---------------------------------------------------------------------------
def price_remedy(remedy, complaint):
    figures = calc.goodwill_authorization(remedy, complaint)
    remedy.update(figures)
    return figures


def void_live_remedies_by_hold(complaint):
    """PRD §3.6: a quality hold voids every live remedy; only APPROVED ones move money."""
    for remedy in remedies_of_complaint(complaint["id"]):
        if remedy["status"] not in LIVE_REMEDY_STATES:
            continue
        was_approved = remedy["status"] == "APPROVED"
        remedy["status"] = "VOIDED_BY_HOLD"
        touch(remedy)
        if was_approved:
            consumer = store.consumers.get(remedy["consumer_id"])
            if consumer is not None:
                payout = remedy["payout_cents"]
                consumer["goodwill_outstanding_cents"] -= payout
                consumer["goodwill_voided_cents"] += payout
                touch(consumer)


def impose_quality_hold(complaint):
    complaint["pre_hold_handling_status"] = complaint["handling_status"]
    complaint["handling_status"] = "ON_QUALITY_HOLD"
    touch(complaint)
    void_live_remedies_by_hold(complaint)


# ---------------------------------------------------------------------------
# regulatory report creation
# ---------------------------------------------------------------------------
def open_regulatory_report(complaint, report_kind):
    escalated_at = now()
    report = base_record()
    report.update(
        {
            "complaint_id": complaint["id"],
            "report_kind": report_kind,
            "status": "OPEN",
            "escalated_at": escalated_at,
            "due_at": calc.regulatory_due_at(escalated_at, calc.effective_band(complaint)),
            "determination_note": None,
            "determined_by_ref": None,
            "submitted_by_ref": None,
            "submitted_at": None,
            "submitted_late": None,
            "agency_reference": None,
        }
    )
    store.regulatory_reports[report["id"]] = report
    complaint["regulatory_status"] = "ESCALATED"
    touch(complaint)
    return report


# ---------------------------------------------------------------------------
# trend signals
# ---------------------------------------------------------------------------
def scope_key(signal):
    return (
        signal["scope_level"],
        signal.get("plant_id"),
        signal.get("production_line_id"),
        signal.get("lot_id"),
    )


def windows_overlap(a_start, a_end, b_start, b_end):
    """Strict overlap: the first starts before the second ends and vice versa."""
    return a_start < b_end and b_start < a_end


def evaluate_scope(complaints, lots, scope_level):
    weighted = Decimal(0)
    for complaint in complaints:
        weighted += calc.weight_of(complaint)
    weighted = round_half_up(weighted, 2)
    units = sum(int(l.get("units_produced") or 0) for l in lots)
    rate = calc.observed_rate(weighted, units)
    return {
        "weighted_complaint_count": weighted,
        "units_in_scope": units,
        "observed_rate_ppm": rate,
        "threshold_ppm": calc.THRESHOLD_PPM[scope_level],
        "fires": calc.fires(weighted, rate, scope_level),
    }


def create_signal(
    scope_level,
    plant_id,
    production_line_id,
    lot_id,
    window_start,
    window_end,
    figures,
    detection_source,
):
    signal = base_record()
    signal.update(
        {
            "scope_level": scope_level,
            "plant_id": plant_id,
            "production_line_id": production_line_id,
            "lot_id": lot_id,
            "window_start": window_start,
            "window_end": window_end,
            "weighted_complaint_count": figures["weighted_complaint_count"],
            "units_in_scope": figures["units_in_scope"],
            "observed_rate_ppm": figures["observed_rate_ppm"],
            "threshold_ppm": figures["threshold_ppm"],
            "status": "DETECTED",
            "detection_source": detection_source,
            "membership_count": 0,
            "opened_by_ref": None,
        }
    )
    store.trend_signals[signal["id"]] = signal
    return signal


def add_membership(signal, complaint):
    membership = base_record(with_version=False)
    membership.update(
        {
            "trend_signal_id": signal["id"],
            "complaint_id": complaint["id"],
            "severity_weight": round_half_up(calc.weight_of(complaint), 2),
            "included_variant": calc.included_variant(complaint),
        }
    )
    store.signal_memberships[membership["id"]] = membership
    return membership


def find_refreshable_signal(scope_level, plant_id, line_id, lot_id, window_start, window_end):
    for signal in sort_records(list(store.trend_signals.values())):
        if signal["status"] != "DETECTED":
            continue
        if scope_key(signal) != (scope_level, plant_id, line_id, lot_id):
            continue
        if signal["window_start"] != window_start or signal["window_end"] != window_end:
            continue
        return signal
    return None


def emit_or_refresh(
    scope_level, plant_id, line_id, lot_id, window_start, window_end, figures, members
):
    """Returns (created, refreshed, memberships_created)."""
    existing = find_refreshable_signal(
        scope_level, plant_id, line_id, lot_id, window_start, window_end
    )
    created = 0
    refreshed = 0
    inserted = 0
    if existing is not None:
        signal = existing
        for key in (
            "weighted_complaint_count",
            "units_in_scope",
            "observed_rate_ppm",
            "threshold_ppm",
        ):
            signal[key] = figures[key]
        touch(signal)
        refreshed = 1
        already = {m["complaint_id"] for m in memberships_of_signal(signal["id"])}
    else:
        signal = create_signal(
            scope_level,
            plant_id,
            line_id,
            lot_id,
            window_start,
            window_end,
            figures,
            "OPS_RUN",
        )
        created = 1
        already = set()

    for complaint in members:
        if complaint["id"] in already:
            continue
        add_membership(signal, complaint)
        inserted += 1
        ser.sync_complaint_signal_count(complaint)
    ser.sync_signal(signal)
    return created, refreshed, inserted, signal


def run_trend_waterfall(window_start, window_end):
    """Narrowest-scope-wins waterfall (PRD §3.9). Returns aggregate counts."""
    eligible = calc.eligible_complaints(window_start, window_end)
    by_lot = {}
    for complaint in eligible:
        by_lot.setdefault(complaint["lot_id"], []).append(complaint)

    signals_created = 0
    signals_refreshed = 0
    memberships_created = 0
    touched_plants = set()
    consumed_lot_ids = set()

    all_lots = sorted(
        store.production_lots.values(), key=lambda l: (l["code_date"], l["created_at"], l["_seq"])
    )

    # --- LOT pass ---------------------------------------------------------
    for lot in all_lots:
        members = by_lot.get(lot["id"], [])
        figures = evaluate_scope(members, [lot], "LOT")
        if not figures["fires"]:
            continue
        line = line_of_lot(lot)
        plant = plant_of_line(line)
        if plant is None:
            continue
        created, refreshed, inserted, _ = emit_or_refresh(
            "LOT",
            plant["id"],
            line["id"],
            lot["id"],
            window_start,
            window_end,
            figures,
            members,
        )
        signals_created += created
        signals_refreshed += refreshed
        memberships_created += inserted
        touched_plants.add(plant["id"])
        consumed_lot_ids.add(lot["id"])

    # --- LINE pass --------------------------------------------------------
    all_lines = sorted(
        store.production_lines.values(),
        key=lambda l: (l["line_code"], l["created_at"], l["_seq"]),
    )
    for line in all_lines:
        lots = [
            l
            for l in all_lots
            if l.get("production_line_id") == line["id"] and l["id"] not in consumed_lot_ids
        ]
        members = []
        for lot in lots:
            members.extend(by_lot.get(lot["id"], []))
        members = sort_records(members)
        figures = evaluate_scope(members, lots, "LINE")
        if not figures["fires"]:
            continue
        plant = plant_of_line(line)
        if plant is None:
            continue
        created, refreshed, inserted, _ = emit_or_refresh(
            "LINE", plant["id"], line["id"], None, window_start, window_end, figures, members
        )
        signals_created += created
        signals_refreshed += refreshed
        memberships_created += inserted
        touched_plants.add(plant["id"])
        for lot in lots:
            consumed_lot_ids.add(lot["id"])

    # --- PLANT pass -------------------------------------------------------
    all_plants = sorted(
        store.plants.values(), key=lambda p: (p["plant_code"], p["created_at"], p["_seq"])
    )
    for plant in all_plants:
        lots = [l for l in lots_of_plant(plant["id"]) if l["id"] not in consumed_lot_ids]
        lots = sorted(lots, key=lambda l: (l["code_date"], l["created_at"], l["_seq"]))
        members = []
        for lot in lots:
            members.extend(by_lot.get(lot["id"], []))
        members = sort_records(members)
        figures = evaluate_scope(members, lots, "PLANT")
        if not figures["fires"]:
            continue
        created, refreshed, inserted, _ = emit_or_refresh(
            "PLANT", plant["id"], None, None, window_start, window_end, figures, members
        )
        signals_created += created
        signals_refreshed += refreshed
        memberships_created += inserted
        touched_plants.add(plant["id"])
        for lot in lots:
            consumed_lot_ids.add(lot["id"])

    return {
        "signals_created_count": signals_created,
        "signals_refreshed_count": signals_refreshed,
        "memberships_created_count": memberships_created,
        "plants_reposted_count": len(touched_plants),
    }


# ---------------------------------------------------------------------------
# operations checkpoint (PRD §3.9)
# ---------------------------------------------------------------------------
def run_quality_ops():
    run_at = now()
    kits_expired = 0
    complaints_advanced = 0

    kits = sort_records([k for k in store.sample_kits.values() if k["status"] == "SHIPPED"])
    for kit in kits:
        expected = kit.get("expected_return_by")
        if expected is None or not run_at > expected:
            continue
        kit["status"] = "EXPIRED"
        kit["disposition"] = "UNUSABLE"
        kit["chain_integrity_status"] = "BROKEN"
        touch(kit)
        kits_expired += 1
        complaint = store.complaints.get(kit["complaint_id"])
        if complaint is not None and complaint["handling_status"] == "AWAITING_SAMPLE":
            complaint["handling_status"] = "IN_RESOLUTION"
            touch(complaint)
            complaints_advanced += 1
        ser.sync_consumer(store.consumers.get(kit["consumer_id"]))

    window_start = run_at - calc.days(calc.TREND_WINDOW_DAYS)
    counts = run_trend_waterfall(window_start, run_at)
    ser.sync_all_plants()

    result = {"run_at": run_at, "kits_expired_count": kits_expired,
              "complaints_advanced_count": complaints_advanced}
    result.update(counts)
    return result
