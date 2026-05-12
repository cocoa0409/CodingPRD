"""Billing periods, bills, payments, disputes."""
import re
from datetime import datetime, timezone, timedelta
from clock import now
from db import store, GLOBAL_LOCK
from errors import E, raise_error
from services.common import stamp_create, bump, write_audit, emit_event
from services.pricing import (
    handover_fee_amount, period_final_total, round_money,
    quality_factor_for,
)


YYYYMM_RE = re.compile(r"^\d{6}$")


def _parse_period(yyyymm):
    if not isinstance(yyyymm, str) or not YYYYMM_RE.match(yyyymm):
        raise_error(E.VALIDATION, "period_yyyymm must be YYYYMM")
    year = int(yyyymm[:4])
    month = int(yyyymm[4:])
    if month < 1 or month > 12:
        raise_error(E.VALIDATION, "month out of range")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def create_or_fetch_period(station_id: str, body: dict):
    from services.station import get_station
    get_station(station_id, allow_not_found=False)
    period_yyyymm = (body or {}).get("period_yyyymm")
    start, end = _parse_period(period_yyyymm)
    with GLOBAL_LOCK:
        key = (station_id, period_yyyymm)
        if key in store.billing_period_by_key:
            return store.billing_periods[store.billing_period_by_key[key]], False
        row = stamp_create({
            "station_id": station_id,
            "period_yyyymm": period_yyyymm,
            "period_start": start,
            "period_end": end,
            "status": "OPEN",
            "handover_fee_total": 0,
            "storage_fee_total": 0,
            "quality_adjustment_factor": 1.0,
            "final_total": 0,
        })
        store.billing_periods[row["id"]] = row
        store.billing_period_by_key[key] = row["id"]
        return row, True


def get_period_by_yyyymm(station_id, period_yyyymm):
    key = (station_id, period_yyyymm)
    pid = store.billing_period_by_key.get(key)
    if pid is None:
        raise_error(E.RESOURCE_NOT_FOUND, "BillingPeriod not found")
    return store.billing_periods[pid]


def get_period(period_id, allow_not_found=False):
    p = store.billing_periods.get(period_id)
    if p is None and not allow_not_found:
        raise_error(E.RESOURCE_NOT_FOUND, "BillingPeriod not found")
    return p


def get_bill(bill_id, allow_not_found=False):
    b = store.bills.get(bill_id)
    if b is None and not allow_not_found:
        raise_error(E.RESOURCE_NOT_FOUND, "Bill not found")
    return b


def _find_existing_bill(period_id, payer_kind, payer_ref):
    for b in store.bills.values():
        if (b["billing_period_id"] == period_id
                and b["payer_kind"] == payer_kind
                and b["payer_ref"] == payer_ref):
            return b
    return None


def _create_bill(period_id, payer_kind, payer_ref):
    row = stamp_create({
        "billing_period_id": period_id,
        "payer_kind": payer_kind,
        "payer_ref": payer_ref,
        "handover_fee_amount": 0,
        "storage_fee_amount": 0,
        "parcel_count": 0,
        "status": "DRAFT",
        "issued_at": None,
        "paid_at": None,
        "dispute_reason": None,
    })
    store.bills[row["id"]] = row
    return row


def _find_or_create_recipient_bill_for_parcel(parcel):
    """Find/Create the RECIPIENT bill for the parcel's pickup billing period."""
    station_id = parcel["station_id"]
    # The period the parcel rolls into is the one containing the *pickup* event
    t = parcel.get("picked_up_at") or now()
    yyyymm = t.strftime("%Y%m")
    period, _ = create_or_fetch_period(station_id, {"period_yyyymm": yyyymm})

    payer_ref = parcel["recipient_phone"]
    existing = _find_existing_bill(period["id"], "RECIPIENT", payer_ref)
    if existing is None:
        existing = _create_bill(period["id"], "RECIPIENT", payer_ref)
    return existing, period


def roll_storage_into_recipient_bill(parcel):
    """Roll a parcel's finalized storage fee into the recipient bill."""
    bill, period = _find_or_create_recipient_bill_for_parcel(parcel)
    bill["storage_fee_amount"] = round_money(
        bill.get("storage_fee_amount", 0) + parcel["storage_fee_total"])
    bill["parcel_count"] = bill.get("parcel_count", 0) + 1
    bump(bill)
    # Refresh period totals
    period["storage_fee_total"] = round_money(
        sum(b.get("storage_fee_amount", 0) for b in store.bills.values()
            if b["billing_period_id"] == period["id"])
    )
    bump(period)


def close_billing_period(station_id, period_yyyymm, actor_role, actor_id):
    from services.station import get_station
    get_station(station_id, allow_not_found=False)
    period = get_period_by_yyyymm(station_id, period_yyyymm)
    with GLOBAL_LOCK:
        if period["status"] != "OPEN":
            raise_error(E.INVALID_BILL_STATE, "Period not OPEN")
        t = now()
        if t < period["period_end"]:
            raise_error(E.PERIOD_NOT_ENDED, "Period not ended yet")

        qa_key = (station_id, period_yyyymm)
        qa_id = store.quality_assessment_by_key.get(qa_key)
        qa = store.quality_assessments.get(qa_id) if qa_id else None
        if qa is None or qa["status"] != "CLOSED":
            raise_error(E.QUALITY_ASSESSMENT_NOT_CLOSED, "Quality assessment not closed")

        # Snapshot quality adjustment factor
        factor = quality_factor_for(qa["composite_score"])
        period["quality_adjustment_factor"] = factor

        # ---- Generate handover-fee courier-company bills for the period window ----
        # Collect parcels in [period_start, period_end) with status != REJECTED
        # at this station, grouped by courier_company_id.
        courier_counts = {}
        for p in store.parcels.values():
            if p["station_id"] != station_id:
                continue
            if p.get("shelved_at") is None:
                continue
            sa = p["shelved_at"]
            if not (period["period_start"] <= sa < period["period_end"]):
                continue
            if p["status"] == "REJECTED":
                continue
            cid = p["courier_company_id"]
            courier_counts[cid] = courier_counts.get(cid, 0) + 1

        for cid, count in courier_counts.items():
            bill = _find_existing_bill(period["id"], "COURIER_COMPANY", cid)
            if bill is None:
                bill = _create_bill(period["id"], "COURIER_COMPANY", cid)
            bill["handover_fee_amount"] = handover_fee_amount(count)
            bill["parcel_count"] = count
            bump(bill)

        # ---- Recompute period rollups ----
        handover_total = round_money(
            sum(b.get("handover_fee_amount", 0) for b in store.bills.values()
                if b["billing_period_id"] == period["id"])
        )
        storage_total = round_money(
            sum(b.get("storage_fee_amount", 0) for b in store.bills.values()
                if b["billing_period_id"] == period["id"])
        )
        period["handover_fee_total"] = handover_total
        period["storage_fee_total"] = storage_total
        period["final_total"] = period_final_total(handover_total, factor, storage_total)
        period["status"] = "CLOSED"
        bump(period)

        # Issue all DRAFT bills
        issued = []
        for b in list(store.bills.values()):
            if b["billing_period_id"] != period["id"]:
                continue
            if b["status"] == "DRAFT":
                from_state = b["status"]
                b["status"] = "ISSUED"
                b["issued_at"] = t
                bump(b)
                emit_event("PAYMENT", "BILL_ISSUED", "Bill", b["id"],
                           payload={"period_id": period["id"]})
                write_audit("Bill", b["id"], "BILL_ISSUED", actor_role, actor_id,
                            from_state=from_state, to_state="ISSUED",
                            payload={"period_id": period["id"]})
                issued.append(b["id"])

        return period


def pay_bill(bill_id, body, actor_role, actor_id):
    bill = get_bill(bill_id, allow_not_found=False)
    if not isinstance(body, dict):
        body = {}
    idem = body.get("idempotency_key")
    amount = body.get("amount")
    if not idem:
        raise_error(E.IDEMPOTENCY_KEY_REQUIRED, "idempotency_key required")

    with GLOBAL_LOCK:
        replay_key = (bill_id, idem)
        if replay_key in store.payment_idempotency:
            # Return the prior outcome with synthetic replay marker.
            prior = store.payment_idempotency[replay_key]
            return ("replay", prior)

        # Validate bill state
        if bill["status"] == "PAID":
            raise_error(E.BILL_ALREADY_PAID, "Bill already paid")
        if bill["status"] != "ISSUED":
            raise_error(E.BILL_NOT_ISSUED, "Bill is not ISSUED")
        period = get_period(bill["billing_period_id"])
        if period["status"] not in ("CLOSED", "DISPUTED"):
            raise_error(E.INVALID_BILL_STATE, "Parent period not CLOSED/DISPUTED")

        t = now()
        from_state = bill["status"]
        bill["status"] = "PAID"
        bill["paid_at"] = t
        bump(bill)
        write_audit("Bill", bill_id, "BILL_PAID", actor_role, actor_id,
                    from_state=from_state, to_state="PAID",
                    payload={"amount": amount, "idempotency_key": idem})

        # Record idempotency snapshot AFTER state transition
        store.payment_idempotency[replay_key] = dict(bill)

        # Maybe auto-settle period
        _maybe_settle_period(period, actor_role, actor_id)

        return ("paid", bill)


def dispute_bill(bill_id, body, actor_role, actor_id):
    bill = get_bill(bill_id, allow_not_found=False)
    reason = (body or {}).get("reason")
    if not reason or not isinstance(reason, str):
        raise_error(E.DISPUTE_REASON_REQUIRED, "reason required")
    with GLOBAL_LOCK:
        if bill["status"] != "ISSUED":
            raise_error(E.BILL_NOT_ISSUED, "Bill is not ISSUED")
        period = get_period(bill["billing_period_id"])
        if period["status"] not in ("CLOSED", "DISPUTED"):
            raise_error(E.INVALID_BILL_STATE, "Parent period not in correct state")
        from_state = bill["status"]
        bill["status"] = "DISPUTED"
        bill["dispute_reason"] = reason
        bump(bill)
        write_audit("Bill", bill_id, "BILL_DISPUTED", actor_role, actor_id,
                    from_state=from_state, to_state="DISPUTED",
                    payload={"reason": reason})
        # Bubble up period to DISPUTED
        if period["status"] != "DISPUTED":
            period["status"] = "DISPUTED"
            bump(period)
        return bill


def resolve_dispute(bill_id, body, actor_role, actor_id):
    bill = get_bill(bill_id, allow_not_found=False)
    body = body or {}
    adj = body.get("adjustment_amount")
    note = body.get("note")
    with GLOBAL_LOCK:
        if bill["status"] != "DISPUTED":
            raise_error(E.INVALID_BILL_STATE, "Bill not DISPUTED")
        if adj is not None:
            if bill["payer_kind"] == "COURIER_COMPANY":
                bill["handover_fee_amount"] = round_money(adj)
            else:
                bill["storage_fee_amount"] = round_money(adj)
        from_state = bill["status"]
        bill["status"] = "RESOLVED"
        bump(bill)
        write_audit("Bill", bill_id, "BILL_RESOLVED", actor_role, actor_id,
                    from_state=from_state, to_state="RESOLVED",
                    payload={"adjustment_amount": adj, "note": note})
        period = get_period(bill["billing_period_id"])
        _maybe_bubble_period_after_dispute_end(period)
        _maybe_settle_period(period, actor_role, actor_id)
        return bill


def write_off_bill(bill_id, body, actor_role, actor_id):
    bill = get_bill(bill_id, allow_not_found=False)
    note = (body or {}).get("note")
    with GLOBAL_LOCK:
        if bill["status"] != "DISPUTED":
            raise_error(E.INVALID_BILL_STATE, "Bill not DISPUTED")
        from_state = bill["status"]
        bill["status"] = "WRITTEN_OFF"
        bump(bill)
        write_audit("Bill", bill_id, "BILL_WRITTEN_OFF", actor_role, actor_id,
                    from_state=from_state, to_state="WRITTEN_OFF",
                    payload={"note": note})
        period = get_period(bill["billing_period_id"])
        _maybe_bubble_period_after_dispute_end(period)
        _maybe_settle_period(period, actor_role, actor_id)
        return bill


def _maybe_bubble_period_after_dispute_end(period):
    if period["status"] != "DISPUTED":
        return
    still_disputed = any(
        b["status"] == "DISPUTED"
        for b in store.bills.values()
        if b["billing_period_id"] == period["id"]
    )
    if not still_disputed:
        period["status"] = "CLOSED"
        bump(period)


def _maybe_settle_period(period, actor_role, actor_id):
    if period["status"] not in ("CLOSED",):
        # Only settle from CLOSED
        return
    children = [b for b in store.bills.values() if b["billing_period_id"] == period["id"]]
    if not children:
        return
    if all(b["status"] in ("PAID", "WRITTEN_OFF", "RESOLVED") for b in children):
        from_state = period["status"]
        period["status"] = "SETTLED"
        bump(period)
        # PERIOD_SETTLED audit: per PRD §2.10 subject_kind is one of
        # {Parcel, Bill, PickupCode, ReturnShipment}; we record this event
        # against the last terminal bill that triggered settlement so the
        # invariant on subject_kind holds.
        anchor = children[-1] if children else None
        if anchor is not None:
            write_audit("Bill", anchor["id"], "PERIOD_SETTLED",
                        actor_role, actor_id, from_state=from_state, to_state="SETTLED",
                        payload={"period_id": period["id"]})
