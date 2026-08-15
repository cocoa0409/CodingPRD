"""Master waybill lifecycle: open, consolidate, deconsolidate, tender, void,
close, and milestone intake (PRD §3.4-§3.6)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import services as svc
from db import Rec, store
from errors import (
    ApiError,
    ERR_BOOKING_NOT_OPEN,
    ERR_CAPACITY_EXCEEDED,
    ERR_DUPLICATE_WAYBILL_NUMBER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LANE_MISMATCH,
    ERR_MEASURED_VOLUME_MISSING,
    ERR_MAWB_NOT_OPEN_FOR_CONSOLIDATION,
    ERR_NO_ACTIVE_RATE_AGREEMENT,
    ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS,
    ERR_OPEN_CLAIMS_EXIST,
    ERR_HWB_NOT_CLEARED,
    ERR_SHIPPER_NOT_KNOWN,
    ERR_STALE_VERSION,
    ERR_TENDER_WINDOW_CONFLICT,
)
from middleware import (
    ALL_ROLES,
    get_body,
    opt_str,
    opt_version,
    pagination_params,
    req_datetime,
    req_enum,
    req_nonempty_str,
    require_roles,
)
from money import chargeable_weight, dec
from response import ok, ok_list

bp = Blueprint("master_waybills", __name__)

TENDER_BUFFER = timedelta(minutes=30)
# Milestone rank rule (PRD §3.6): DEPARTED=1 requires rank 0 (TENDERED), etc.
MAWB_RANK = {"TENDERED": 0, "IN_TRANSIT": 1, "ARRIVED": 2, "DELIVERED": 3}
EVENT_RANK = {"DEPARTED": 1, "ARRIVED": 2, "DELIVERED": 3}
EVENT_CODES = ("DEPARTED", "ARRIVED", "DELIVERED", "EXCEPTION")
EXCEPTION_CODES = ("NONE", "DAMAGE", "SHORTAGE", "DELAY", "CUSTOMS_HOLD")


@bp.post("/master-waybills")
@require_roles("CapacityPlanner")
def create_mawb():
    body = get_body()
    # Existence (priority 3): body booking reference resolves.
    if isinstance(body.get("booking_id"), str):
        svc.get_booking(body["booking_id"])
    booking_id = req_nonempty_str(body, "booking_id")
    mawb_number = req_nonempty_str(body, "mawb_number")
    # Structural uniqueness guard (priority 8).
    if mawb_number in store.mawb_by_number:
        raise ApiError(
            ERR_DUPLICATE_WAYBILL_NUMBER,
            f"Master waybill number '{mawb_number}' already exists.",
            409,
        )
    m = svc.fresh_rec(
        booking_id=booking_id,
        mawb_number=mawb_number,
        total_chargeable_weight_kg=Decimal(0),
        total_volume_m3=Decimal(0),
        total_freight_amount=Decimal(0),
        tender_window_start_utc=None,
        tender_window_end_utc=None,
        status="DRAFT",
    )
    store.mawbs[m.id] = m
    store.mawb_by_number[mawb_number] = m
    return ok(svc.mawb_json(m), 201)


@bp.get("/master-waybills/<mid>")
@require_roles(*ALL_ROLES)
def get_mawb(mid):
    return ok(svc.mawb_json(svc.get_mawb(mid)), 200)


@bp.post("/master-waybills/<mid>/open")
@require_roles("CapacityPlanner")
def open_mawb(mid):
    m = svc.get_mawb(mid)
    if m.status != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Master waybill status is {m.status}; only DRAFT can be opened.",
            409,
        )
    booking = svc.get_booking(m.booking_id)
    svc.refresh_booking_cutoff(booking)
    if booking.status != "OPEN":
        raise ApiError(
            ERR_BOOKING_NOT_OPEN,
            f"Booking status is {booking.status}; opening requires OPEN.",
            409,
        )
    m.status = "OPEN_FOR_CONSOLIDATION"
    svc.touch(m)
    return ok(svc.mawb_json(m), 200)


@bp.post("/master-waybills/<mid>/house-waybills")
@require_roles("ForwarderOps")
def consolidate(mid):
    m = svc.get_mawb(mid)
    body = get_body()
    # Existence (priority 3): body hwb reference resolves.
    if isinstance(body.get("hwb_id"), str):
        svc.get_hwb(body["hwb_id"])
    hwb_id = req_nonempty_str(body, "hwb_id")
    h = store.hwbs[hwb_id]
    # OCC (priority 4, PRD §2.5): non-optional expected_master_waybill_version,
    # evaluated before any state-gate / compliance / lane / rate / capacity check.
    expected = opt_version(body, "expected_master_waybill_version")
    if expected is None:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'expected_master_waybill_version' is required.",
            400,
        )
    if expected != m.version:
        raise ApiError(
            ERR_STALE_VERSION,
            f"Master waybill version is {m.version}, not {expected}.",
            412,
        )
    # State gates (priority 5), in the PRD §3.4 order.
    if h.status != "CLEARED":
        raise ApiError(
            ERR_HWB_NOT_CLEARED,
            f"House waybill status is {h.status}; consolidation requires CLEARED.",
            409,
        )
    if m.status != "OPEN_FOR_CONSOLIDATION":
        raise ApiError(
            ERR_MAWB_NOT_OPEN_FOR_CONSOLIDATION,
            f"Master waybill status is {m.status}; consolidation requires OPEN_FOR_CONSOLIDATION.",
            409,
        )
    booking = svc.get_booking(m.booking_id)
    svc.refresh_booking_cutoff(booking)
    if booking.status != "OPEN":
        raise ApiError(
            ERR_BOOKING_NOT_OPEN,
            f"Booking status is {booking.status}; consolidation requires OPEN.",
            409,
        )
    # Dangerous-goods re-check (priority 6): standing verified twice.
    shipper = svc.get_shipper(h.shipper_id)
    if h.dg_flag and shipper.known_shipper_status != "KNOWN":
        raise ApiError(
            ERR_SHIPPER_NOT_KNOWN,
            "Dangerous-goods waybill requires the shipper to be KNOWN at consolidation.",
            403,
        )
    # Lane consistency (priority 9).
    if h.origin_code != booking.origin_code or h.destination_code != booking.destination_code:
        raise ApiError(
            ERR_LANE_MISMATCH,
            "House waybill origin/destination do not equal the booking's lane.",
            422,
        )
    # Active rate agreement at the logical clock (priority 10).
    agreement = svc.active_agreement(h.shipper_id, h.origin_code, h.destination_code)
    if agreement is None:
        raise ApiError(
            ERR_NO_ACTIVE_RATE_AGREEMENT,
            "No active rate agreement for this shipper and lane.",
            422,
        )
    # Capacity (priority 11): QUOTED candidate weight against the allotment.
    candidate_cw = chargeable_weight(dec(h.gross_weight_kg), dec(h.declared_volume_m3))
    candidate_vol = dec(h.effective_volume_m3)
    if (dec(booking.consumed_weight_kg) + candidate_cw > dec(booking.booked_weight_kg)
            or dec(booking.consumed_volume_m3) + candidate_vol > dec(booking.booked_volume_m3)):
        raise ApiError(
            ERR_CAPACITY_EXCEEDED,
            "Booking consumed plus candidate would exceed the booked allotment.",
            422,
        )
    # Commit: spot flag decided from the candidate-EXCLUDED pre-assignment
    # snapshot and locked; only then attach and recompute (pinned order §3.5).
    spot = svc.spot_surcharge_applied(booking, h.id)
    h.spot_surcharge_applied = spot
    svc.apply_rating(h, agreement, dec(h.declared_volume_m3), spot)
    h.weight_basis = "QUOTED"
    h.rate_agreement_id = agreement.id
    h.mawb_id = m.id
    h.status = "CONSOLIDATED"
    svc.touch(h)
    svc.recompute_mawb_totals(m)
    svc.touch(m)  # consolidation increments the MAWB version by exactly 1
    svc.recompute_booking(booking)
    return ok(svc.hwb_json(h), 200)


@bp.delete("/master-waybills/<mid>/house-waybills/<hwb_id>")
@require_roles("ForwarderOps")
def deconsolidate(mid, hwb_id):
    # Existence, path ids left to right.
    m = svc.get_mawb(mid)
    h = svc.get_hwb(hwb_id)
    if h.status != "CONSOLIDATED" or h.mawb_id != m.id:
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a waybill CONSOLIDATED under this master waybill can be removed.",
            409,
        )
    booking = svc.get_booking(m.booking_id)
    svc.detach_hwb(h)
    svc.recompute_mawb_totals(m)
    svc.touch(m)  # deconsolidation increments the MAWB version by exactly 1
    svc.recompute_booking(booking)
    return ok(svc.hwb_json(h), 200)


@bp.post("/master-waybills/<mid>/tender")
@require_roles("CapacityPlanner")
def tender(mid):
    m = svc.get_mawb(mid)
    body = get_body()
    # State gates (priority 5) in scaffold precondition order.
    if m.status != "OPEN_FOR_CONSOLIDATION":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Master waybill status is {m.status}; tender requires OPEN_FOR_CONSOLIDATION.",
            409,
        )
    booking = svc.get_booking(m.booking_id)
    svc.refresh_booking_cutoff(booking)
    if booking.status not in ("OPEN", "CUTOFF_CLOSED"):
        raise ApiError(
            ERR_BOOKING_NOT_OPEN,
            f"Booking status is {booking.status}; tender requires OPEN or CUTOFF_CLOSED.",
            409,
        )
    attached = [h for h in svc._attached_hwbs(m) if h.status == "CONSOLIDATED"]
    if not attached:
        raise ApiError(
            ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS,
            "Tender requires at least one attached CONSOLIDATED house waybill.",
            409,
        )
    if any(h.measured_volume_m3 is None for h in attached):
        raise ApiError(
            ERR_MEASURED_VOLUME_MISSING,
            "Every attached CONSOLIDATED waybill must have measured_volume_m3 recorded.",
            409,
        )
    # Malformed input (priority 8): window fields and end > start.
    start = req_datetime(body, "tender_window_start_utc")
    end = req_datetime(body, "tender_window_end_utc")
    if not end > start:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "tender_window_end_utc must be strictly after tender_window_start_utc.",
            400,
        )
    # 30-minute buffered window conflict vs other TENDERED MAWBs on this booking.
    for other in svc.booking_mawbs(booking):
        if other.id == m.id or other.status != "TENDERED":
            continue
        if (start < other.tender_window_end_utc + TENDER_BUFFER
                and end > other.tender_window_start_utc - TENDER_BUFFER):
            raise ApiError(
                ERR_TENDER_WINDOW_CONFLICT,
                "Tender window violates the 30-minute buffer against another TENDERED master waybill.",
                409,
            )
    # FINAL re-rate and capacity re-check (priority 11) before committing.
    final = []
    for h in attached:
        cw = chargeable_weight(dec(h.gross_weight_kg), dec(h.measured_volume_m3))
        final.append((h, cw))
    # Recomputed booking consumption with this MAWB's waybills at FINAL values.
    w = Decimal(0)
    v = Decimal(0)
    final_by_id = {h.id: (cw, dec(h.measured_volume_m3)) for h, cw in final}
    for om in svc.booking_mawbs(booking):
        if om.status == "VOID":
            continue
        for h in svc._attached_hwbs(om):
            if h.status not in svc.CONSUMPTION_STATES:
                continue
            if h.id in final_by_id:
                w += final_by_id[h.id][0]
                v += final_by_id[h.id][1]
            else:
                w += dec(h.chargeable_weight_kg)
                v += dec(h.effective_volume_m3)
    if w > dec(booking.booked_weight_kg) or v > dec(booking.booked_volume_m3):
        raise ApiError(
            ERR_CAPACITY_EXCEEDED,
            "FINAL re-rate would exceed the booked allotment.",
            422,
        )
    # Commit: FINAL re-rate (spot flag stays locked), attach window, transition.
    for h, _cw in final:
        agreement = store.rate_agreements[h.rate_agreement_id]
        svc.apply_rating(h, agreement, dec(h.measured_volume_m3), h.spot_surcharge_applied)
        h.weight_basis = "FINAL"
        h.status = "TENDERED"
        svc.touch(h)
    m.tender_window_start_utc = start
    m.tender_window_end_utc = end
    m.status = "TENDERED"
    svc.recompute_mawb_totals(m)
    svc.touch(m)
    svc.recompute_booking(booking)
    return ok(svc.mawb_json(m), 200)


@bp.post("/master-waybills/<mid>/void")
@require_roles("CapacityPlanner")
def void_mawb(mid):
    m = svc.get_mawb(mid)
    if m.status not in ("DRAFT", "OPEN_FOR_CONSOLIDATION"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"Master waybill status is {m.status}; only DRAFT or OPEN_FOR_CONSOLIDATION can be voided.",
            409,
        )
    booking = svc.get_booking(m.booking_id)
    svc.void_mawb(m)
    svc.recompute_booking(booking)
    svc.maybe_auto_depart(booking)
    return ok(svc.mawb_json(m), 200)


@bp.post("/master-waybills/<mid>/close")
@require_roles("CapacityPlanner")
def close_mawb(mid):
    m = svc.get_mawb(mid)
    if m.status != "DELIVERED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Master waybill status is {m.status}; close requires DELIVERED.",
            409,
        )
    attached_ids = {h.id for h in svc._attached_hwbs(m)}
    for c in store.claims.values():
        if c.hwb_id in attached_ids and c.status in svc.OPEN_CLAIM_STATES:
            raise ApiError(
                ERR_OPEN_CLAIMS_EXIST,
                "An open claim on an attached waybill blocks closing.",
                409,
            )
    m.status = "CLOSED"
    svc.touch(m)
    svc.maybe_auto_depart(svc.get_booking(m.booking_id))
    return ok(svc.mawb_json(m), 200)


@bp.post("/master-waybills/<mid>/milestone-events")
@require_roles("ForwarderOps")
def record_milestone(mid):
    m = svc.get_mawb(mid)
    # Terminal lockdown is a state gate (priority 5).
    if m.status in ("CLOSED", "VOID"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"Master waybill status is {m.status}; milestones cannot be recorded.",
            409,
        )
    body = get_body()
    event_code = req_enum(body, "event_code", EVENT_CODES)
    event_time_utc = req_datetime(body, "event_time_utc")
    exception_code = req_enum(body, "exception_code", EXCEPTION_CODES) if "exception_code" in body and body["exception_code"] is not None else "NONE"
    note = opt_str(body, "note", None)
    # exception_code is required non-NONE iff event_code == EXCEPTION.
    if event_code == "EXCEPTION" and exception_code == "NONE":
        raise ApiError(
            ERR_INVALID_REQUEST,
            "EXCEPTION events require a non-NONE exception_code.",
            400,
        )
    if event_code != "EXCEPTION" and exception_code != "NONE":
        raise ApiError(
            ERR_INVALID_REQUEST,
            "exception_code must be NONE for non-EXCEPTION events.",
            400,
        )
    out_of_order = False
    if event_code in EVENT_RANK:
        current_rank = MAWB_RANK.get(m.status)
        out_of_order = not (current_rank is not None and EVENT_RANK[event_code] == current_rank + 1)
    e = Rec(
        id=svc.new_id(),
        created_at=store.issue_ts(),
        seq=store.next_seq(),
        mawb_id=m.id,
        event_code=event_code,
        event_time_utc=event_time_utc,
        exception_code=exception_code,
        note=note,
        out_of_order=out_of_order,
    )
    store.milestones[e.id] = e
    if not out_of_order and event_code in EVENT_RANK:
        _apply_milestone_transition(m, event_code, event_time_utc)
    return ok(svc.milestone_json(e), 201)


def _apply_milestone_transition(m, event_code, event_time_utc):
    booking = svc.get_booking(m.booking_id)
    if event_code == "DEPARTED":
        m.status = "IN_TRANSIT"
        for h in svc._attached_hwbs(m):
            if h.status == "TENDERED":
                h.status = "IN_TRANSIT"
                svc.touch(h)
        # IN_TRANSIT waybills leave the MAWB totals set (CONSOLIDATED/TENDERED).
        svc.recompute_mawb_totals(m)
        svc.touch(m)
        svc.maybe_auto_depart(booking)
    elif event_code == "ARRIVED":
        m.status = "ARRIVED"
        svc.touch(m)
        svc.maybe_auto_depart(booking)
    elif event_code == "DELIVERED":
        m.status = "DELIVERED"
        for h in svc._attached_hwbs(m):
            if h.status == "IN_TRANSIT":
                h.status = "DELIVERED"
                h.delivered_at_utc = event_time_utc
                svc.touch(h)
        svc.touch(m)
        # DELIVERED waybills leave the booking consumption set (PRD §2.7).
        svc.recompute_booking(booking)
        svc.maybe_auto_depart(booking)


@bp.get("/master-waybills/<mid>/milestone-events")
@require_roles(*ALL_ROLES)
def list_milestones(mid):
    svc.get_mawb(mid)
    limit, offset = pagination_params()
    items = svc.sorted_by_created(
        [e for e in store.milestones.values() if e.mawb_id == mid]
    )
    page, total = svc.paginate(items, limit, offset)
    return ok_list([svc.milestone_json(e) for e in page], total, limit, offset)
