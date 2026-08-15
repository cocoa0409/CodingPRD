"""Business logic: lookups, serializers, calculations, cascades, audit events.

Implements PRD section 3 (workflows) and the scaffold's calculation table.
All time-sensitive behaviour evaluates against the server logical clock
(DB CLOCK), never wall-clock.
"""
import hashlib
import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db import DB, CLOCK, new_id, logical_now_iso, parse_iso, to_iso_ms
from errors import ApiError
from util import round_half_up

# ---------------------------------------------------------------------------
# Constants (scaffold calculations / PRD 2.7)
# ---------------------------------------------------------------------------

BP_DENOMINATOR = 10000
RUSH_CUTOFF_LOCAL = "14:00"
RUSH_GRACE_HOURS = 4
RETRIEVAL_SLA_HOURS = 48
FINANCIAL_HOLD_EXPIRY_DAYS = 365

VERIFICATION_BASE_CENTS = 500
VERIFICATION_SCOPE_SURCHARGE = {
    "ENROLLMENT_ONLY": 0,
    "DEGREE_ONLY": 300,
    "FULL_RECORD": 700,
}
VERIFICATION_ARCHIVE_SURCHARGE_CENTS = 1500

STUDENT_STATUSES = ("ACTIVE", "INACTIVE", "GRADUATED", "WITHDRAWN", "DECEASED")
RECIPIENT_KINDS = ("ELECTRONIC_NETWORK", "EMAIL_PDF", "PAPER_MAIL", "PICKUP")
DELIVERY_KINDS = ("ELECTRONIC_NETWORK", "EMAIL_PDF", "PAPER_MAIL", "PICKUP")
HOLD_TYPES = ("FINANCIAL", "LIBRARY", "REGISTRAR", "DISCIPLINARY")
HOLD_STATUSES = ("ACTIVE", "RELEASED", "EXPIRED")
BLOCKING_SCOPES = ("OFFICIAL", "ALL", "NONE")
IDV_METHODS = ("SSN_DOB", "GOVERNMENT_ID", "IN_PERSON", "NOTARIZED")
IDV_STATUSES = ("PENDING", "VERIFIED", "REJECTED", "EXPIRED")
ORDER_KINDS = ("OFFICIAL", "UNOFFICIAL")
FULFILLMENT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "IDENTITY_PENDING",
    "HOLD_CHECK",
    "READY_TO_FULFILL",
    "IN_TRANSIT",
    "DELIVERED",
    "REISSUE_PENDING",
    "CANCELLED",
    "FAILED",
)
PAYMENT_STATUSES = (
    "UNPAID",
    "AUTHORIZED",
    "CAPTURED",
    "PARTIALLY_REFUNDED",
    "REFUNDED",
    "WAIVED",
)
LINE_STATUSES = ("PENDING", "QUEUED", "SENT", "DELIVERED", "BOUNCED", "CANCELLED")
LINE_TERMINAL = ("DELIVERED", "BOUNCED", "CANCELLED")
RETRIEVAL_STATUSES = ("REQUESTED", "PULLED", "DIGITIZED", "ATTACHED", "FAILED")
CONSENT_SCOPES = ("ENROLLMENT_ONLY", "DEGREE_ONLY", "FULL_RECORD")
CONSENT_STATUSES = ("ACTIVE", "REVOKED", "EXPIRED")
VR_STATUSES = ("RECEIVED", "CONSENT_CHECK", "APPROVED", "DENIED", "REPORTED", "CANCELLED")
PAYMENT_LIFECYCLE = ("AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "VOIDED", "FAILED")
REISSUE_REASONS = (
    "NAME_CORRECTION",
    "RECORD_CORRECTION",
    "DAMAGED_IN_MAIL",
    "NEVER_RECEIVED",
    "WRONG_RECIPIENT",
)
REISSUE_STATUSES = ("REQUESTED", "APPROVED", "REJECTED", "FULFILLED")
BATCH_STATUSES = ("OPEN", "LOCKED", "TRANSMITTED", "ACKED", "FAILED")

# Registrar holiday calendar (logical-clock date strings, YYYY-MM-DD).
REGISTRAR_HOLIDAYS = set()

# Scope ordering: ENROLLMENT_ONLY < DEGREE_ONLY < FULL_RECORD (grant scope must
# cover the requested scope).
_SCOPE_RANK = {"ENROLLMENT_ONLY": 1, "DEGREE_ONLY": 2, "FULL_RECORD": 3}


# ---------------------------------------------------------------------------
# Common field helpers (PRD 2.4)
# ---------------------------------------------------------------------------

def stamp(rec):
    """Set created_at/updated_at/version=1 on a common-fields entity."""
    t = logical_now_iso()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1


def touch(rec):
    """Refresh updated_at and increment version on a common-fields entity."""
    rec["updated_at"] = logical_now_iso()
    rec["version"] += 1


def logical_now():
    return parse_iso(CLOCK["current_utc"])


# ---------------------------------------------------------------------------
# Audit events (PRD 2.8)
# ---------------------------------------------------------------------------

def emit_audit(aggregate_type, aggregate_id, actor_role, actor_id, action, payload=None):
    canonical = json.dumps(
        {
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "action": action,
            "payload": payload if payload is not None else {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    ev = {
        "id": new_id(),
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "payload_hash": digest,
        "recorded_at": logical_now_iso(),
        "created_at": logical_now_iso(),
    }
    DB["audit_events"][ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Lookups (existence checks, left-to-right)
# ---------------------------------------------------------------------------

def _lookup(store, rid, label):
    rec = DB[store].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return rec


def get_student(rid):
    return _lookup("students", rid, "Student")


def get_record(rid):
    return _lookup("student_records", rid, "StudentRecord")


def get_recipient(rid):
    return _lookup("recipients", rid, "Recipient")


def get_hold(rid):
    return _lookup("holds", rid, "Hold")


def get_idv(rid):
    return _lookup("identity_verifications", rid, "IdentityVerification")


def get_order(rid):
    return _lookup("orders", rid, "TranscriptOrder")


def get_line_item(rid):
    return _lookup("order_line_items", rid, "OrderLineItem")


def get_retrieval(rid):
    return _lookup("archived_retrievals", rid, "ArchivedRecordRetrieval")


def get_consent_grant(rid):
    return _lookup("consent_grants", rid, "ConsentGrant")


def get_verification_request(rid):
    return _lookup("verification_requests", rid, "VerificationRequest")


def get_fee_schedule(rid):
    return _lookup("fee_schedules", rid, "FeeSchedule")


def get_payment(rid):
    return _lookup("payments", rid, "Payment")


def get_reissue_request(rid):
    return _lookup("reissue_requests", rid, "ReissueRequest")


def get_batch(rid):
    return _lookup("clearinghouse_batches", rid, "ClearinghouseReportBatch")


def ref_lookup(store, rid, label):
    """Body-supplied FK lookup: ERR_REFERENCED_NOT_FOUND when absent."""
    if rid is None:
        return None
    rec = DB[store].get(rid)
    if rec is None:
        raise ApiError("ERR_REFERENCED_NOT_FOUND", 404, f"{label} not found")
    return rec


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def sorted_created(records):
    return sorted(
        records,
        key=lambda r: (r.get("created_at") or "", r["id"]),
    )


def lines_of_order(order_id):
    return [l for l in DB["order_line_items"].values() if l["order_id"] == order_id]


def payments_of_order(order_id):
    return [p for p in DB["payments"].values() if p["order_id"] == order_id]


def holds_of_student(student_id):
    return [h for h in DB["holds"].values() if h["student_id"] == student_id]


def idvs_of_order(order_id):
    return [
        v for v in DB["identity_verifications"].values() if v["order_id"] == order_id
    ]


def records_of_student(student_id):
    return [
        r for r in DB["student_records"].values() if r["student_id"] == student_id
    ]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_student(r):
    d = {
        "id": r["id"],
        "student_number": r["student_number"],
        "full_name": r["full_name"],
        "date_of_birth": r["date_of_birth"],
        "email": r["email"],
        "status": r["status"],
        "ferpa_restricted": r["ferpa_restricted"],
        "archived_record_flag": r["archived_record_flag"],
    }
    d.update(_common(r))
    return d


def ser_record(r):
    d = {
        "id": r["id"],
        "student_id": r["student_id"],
        "effective_term": r["effective_term"],
        "gpa_cents": r["gpa_cents"],
        "earned_credits": r["earned_credits"],
        "degree_awarded": r["degree_awarded"],
        "record_version": r["record_version"],
        "is_current": r["is_current"],
    }
    d.update(_common(r))
    return d


def ser_recipient(r):
    d = {
        "id": r["id"],
        "kind": r["kind"],
        "display_name": r["display_name"],
        "network_code": r["network_code"],
        "email_address": r["email_address"],
        "postal_address": r["postal_address"],
        "active": r["active"],
    }
    d.update(_common(r))
    return d


def ser_hold(r):
    d = {
        "id": r["id"],
        "student_id": r["student_id"],
        "hold_type": r["hold_type"],
        "status": r["status"],
        "blocking_scope": r["blocking_scope"],
        "amount_cents": r["amount_cents"],
        "placed_at": r["placed_at"],
        "released_at": r["released_at"],
    }
    d.update(_common(r))
    return d


def ser_idv(r):
    # IdentityVerification carries only id + created_at (PRD 2.4).
    return {
        "id": r["id"],
        "student_id": r["student_id"],
        "order_id": r["order_id"],
        "method": r["method"],
        "status": r["status"],
        "verification_token": r["verification_token"],
        "expires_at": r["expires_at"],
        "created_at": r["created_at"],
    }


def ser_order(r):
    d = {
        "id": r["id"],
        "student_id": r["student_id"],
        "order_kind": r["order_kind"],
        "fulfillment_status": r["fulfillment_status"],
        "payment_status": r["payment_status"],
        "rush_requested": r["rush_requested"],
        "rush_qualified": r["rush_qualified"],
        "quoted_fee_cents": r["quoted_fee_cents"],
        "final_fee_cents": r["final_fee_cents"],
        "submitted_at": r["submitted_at"],
        "cancelled_reason": r["cancelled_reason"],
        "reissue_of_order_id": r["reissue_of_order_id"],
    }
    d.update(_common(r))
    return d


def ser_line_item(r):
    d = {
        "id": r["id"],
        "order_id": r["order_id"],
        "recipient_id": r["recipient_id"],
        "delivery_kind": r["delivery_kind"],
        "quantity": r["quantity"],
        "unit_price_cents": r["unit_price_cents"],
        "line_status": r["line_status"],
        "tracking_ref": r["tracking_ref"],
        "archived_retrieval_id": r["archived_retrieval_id"],
    }
    d.update(_common(r))
    return d


def ser_retrieval(r):
    d = {
        "id": r["id"],
        "student_id": r["student_id"],
        "requested_by_order_id": r["requested_by_order_id"],
        "retrieval_status": r["retrieval_status"],
        "sla_due_at": r["sla_due_at"],
        "digitized_record_id": r["digitized_record_id"],
    }
    d.update(_common(r))
    return d


def ser_consent_grant(r):
    d = {
        "id": r["id"],
        "student_id": r["student_id"],
        "grantee_name": r["grantee_name"],
        "scope": r["scope"],
        "status": r["status"],
        "expires_at": r["expires_at"],
    }
    d.update(_common(r))
    return d


def ser_verification_request(r):
    d = {
        "id": r["id"],
        "requester_name": r["requester_name"],
        "subject_student_id": r["subject_student_id"],
        "consent_grant_id": r["consent_grant_id"],
        "scope": r["scope"],
        "status": r["status"],
        "fee_cents": r["fee_cents"],
        "denial_reason": r["denial_reason"],
    }
    d.update(_common(r))
    return d


def ser_fee_schedule(r):
    d = {
        "id": r["id"],
        "code": r["code"],
        "official_base_cents": r["official_base_cents"],
        "unofficial_base_cents": r["unofficial_base_cents"],
        "paper_surcharge_cents": r["paper_surcharge_cents"],
        "pickup_surcharge_cents": r["pickup_surcharge_cents"],
        "rush_flat_cents": r["rush_flat_cents"],
        "rush_multiplier_bp": r["rush_multiplier_bp"],
        "volume_tiers": r["volume_tiers"],
        "effective_from": r["effective_from"],
        "effective_to": r["effective_to"],
        "active": r["active"],
    }
    d.update(_common(r))
    return d


def ser_payment(r):
    d = {
        "id": r["id"],
        "order_id": r["order_id"],
        "amount_cents": r["amount_cents"],
        "captured_cents": r["captured_cents"],
        "refunded_cents": r["refunded_cents"],
        "status": r["status"],
        "idempotency_key": r["idempotency_key"],
        "gateway_ref": r["gateway_ref"],
    }
    d.update(_common(r))
    return d


def ser_reissue_request(r):
    d = {
        "id": r["id"],
        "original_order_id": r["original_order_id"],
        "reason": r["reason"],
        "status": r["status"],
        "replacement_order_id": r["replacement_order_id"],
        "reviewed_by": r["reviewed_by"],
        "fee_waived": r["fee_waived"],
    }
    d.update(_common(r))
    return d


def ser_batch(r):
    d = {
        "id": r["id"],
        "report_period_start": r["report_period_start"],
        "report_period_end": r["report_period_end"],
        "status": r["status"],
        "order_count": r["order_count"],
        "verification_count": r["verification_count"],
        "transmitted_at": r["transmitted_at"],
    }
    d.update(_common(r))
    return d


def ser_audit_event(r):
    return {
        "id": r["id"],
        "aggregate_type": r["aggregate_type"],
        "aggregate_id": r["aggregate_id"],
        "actor_role": r["actor_role"],
        "actor_id": r["actor_id"],
        "action": r["action"],
        "payload_hash": r["payload_hash"],
        "recorded_at": r["recorded_at"],
        "created_at": r["created_at"],
    }


# ---------------------------------------------------------------------------
# Hold blocking evaluation
# ---------------------------------------------------------------------------

def blocking_hold_exists(student_id):
    """True iff the student has an ACTIVE hold with blocking_scope ALL or OFFICIAL."""
    for h in DB["holds"].values():
        if (
            h["student_id"] == student_id
            and h["status"] == "ACTIVE"
            and h["blocking_scope"] in ("ALL", "OFFICIAL")
        ):
            return True
    return False


def verification_block_hold_exists(student_id):
    """True iff the student has an ACTIVE hold with blocking_scope ALL."""
    for h in DB["holds"].values():
        if (
            h["student_id"] == student_id
            and h["status"] == "ACTIVE"
            and h["blocking_scope"] == "ALL"
        ):
            return True
    return False


def order_blocks_on_hold(order):
    """HOLD_CHECK applies only to OFFICIAL orders with an ACTIVE blocking hold."""
    return order["order_kind"] == "OFFICIAL" and blocking_hold_exists(order["student_id"])


# ---------------------------------------------------------------------------
# Rush qualification + fee quoting (scaffold calculations)
# ---------------------------------------------------------------------------

def _local_dt(dt):
    """Registrar-local interpretation of an instant.

    The PRD does not pin a named timezone for 'local registrar time'; the
    logical clock is UTC and all test inputs are expressed in UTC, so local
    time is the UTC wall reading of the instant.
    """
    return dt.astimezone(timezone.utc)


def is_rush_qualified(order, at_dt):
    """rush_qualification: conjunction of five conditions (PRD 3.3)."""
    if not order["rush_requested"]:
        return False
    local = _local_dt(at_dt)
    cutoff_h, cutoff_m = (int(x) for x in RUSH_CUTOFF_LOCAL.split(":"))
    cutoff = local.replace(hour=cutoff_h, minute=cutoff_m, second=0, microsecond=0)
    if not (local < cutoff):  # STRICT < — exactly 14:00:00 is not qualified
        return False
    if local.weekday() > 4:  # Mon=0 .. Fri=4
        return False
    if local.date().isoformat() in REGISTRAR_HOLIDAYS:
        return False
    for line in lines_of_order(order["id"]):
        if line["delivery_kind"] not in ("ELECTRONIC_NETWORK", "EMAIL_PDF", "PICKUP"):
            return False
    return True


def active_schedule_at(at_dt):
    """The active FeeSchedule whose window contains at_dt (from inclusive, to exclusive)."""
    candidates = []
    for s in DB["fee_schedules"].values():
        if not s["active"]:
            continue
        ef = parse_iso(s["effective_from"])
        et = parse_iso(s["effective_to"]) if s["effective_to"] else None
        if ef <= at_dt and (et is None or at_dt < et):
            candidates.append(s)
    if not candidates:
        return None
    # Newest effective_from wins among overlapping actives (defensive; creation
    # normally deactivates overlapping schedules).
    candidates.sort(key=lambda s: (s["effective_from"], s["created_at"]), reverse=True)
    return candidates[0]


def _pick_volume_discount_bp(schedule, total_copies):
    """Highest-min_copies tier satisfied wins; tie on min_copies -> first listed."""
    best = None
    for tier in schedule.get("volume_tiers") or []:
        if total_copies >= tier["min_copies"]:
            if best is None or tier["min_copies"] > best["min_copies"]:
                best = tier
    return best["discount_bp"] if best else 0


def compute_quote(order, at_dt, rush_qualified=None, persist_unit_prices=False):
    """Tiered-pricing pipeline shared by provisional and final quotes.

    Returns (total_cents, schedule) or (None, None) when no active schedule
    covers at_dt. When persist_unit_prices is True, each line's computed
    unit_price_cents is stored on the line record.
    """
    schedule = active_schedule_at(at_dt)
    if schedule is None:
        return None, None
    if order["order_kind"] == "OFFICIAL":
        base_per_copy = schedule["official_base_cents"]
    else:
        base_per_copy = schedule["unofficial_base_cents"]

    lines = lines_of_order(order["id"])
    subtotal = 0
    total_copies = 0
    for line in lines:
        line_base = base_per_copy
        if line["delivery_kind"] == "PAPER_MAIL":
            line_base += schedule["paper_surcharge_cents"]
        if line["delivery_kind"] == "PICKUP":
            line_base += schedule["pickup_surcharge_cents"]
        unit = round_half_up(Decimal(line_base))
        if persist_unit_prices:
            line["unit_price_cents"] = unit
        subtotal += unit * line["quantity"]
        total_copies += line["quantity"]

    discount_bp = _pick_volume_discount_bp(schedule, total_copies)
    discounted = round_half_up(
        Decimal(subtotal) * Decimal(BP_DENOMINATOR - discount_bp) / Decimal(BP_DENOMINATOR)
    )

    if rush_qualified is None:
        rush_qualified = order["rush_qualified"]
    if rush_qualified:
        after_mult = round_half_up(
            Decimal(discounted) * Decimal(schedule["rush_multiplier_bp"]) / Decimal(BP_DENOMINATOR)
        )
        total = after_mult + schedule["rush_flat_cents"]
    else:
        total = discounted
    return total, schedule


def compute_final_fee(order, at_dt):
    """fee_quote_final: same pipeline at capture clock, with two adjustments.

    - reissue orders with fee_waived=true short-circuit to 0
    - if rush_qualified at submit but capture clock is past the same-day rush
      cutoff + 4h grace, drop the rush components.
    """
    # fee_waived short-circuit: the replacement order of a fee-waived reissue.
    if order.get("reissue_of_order_id"):
        for rr in DB["reissue_requests"].values():
            if rr.get("replacement_order_id") == order["id"] and rr.get("fee_waived"):
                return 0

    rush = order["rush_qualified"]
    if rush and order.get("submitted_at"):
        sub_dt = parse_iso(order["submitted_at"])
        local = _local_dt(sub_dt)
        cutoff_h, cutoff_m = (int(x) for x in RUSH_CUTOFF_LOCAL.split(":"))
        cutoff = local.replace(hour=cutoff_h, minute=cutoff_m, second=0, microsecond=0)
        grace_end = cutoff + timedelta(hours=RUSH_GRACE_HOURS)
        if _local_dt(at_dt) > grace_end:
            rush = False

    total, _schedule = compute_quote(order, at_dt, rush_qualified=rush)
    return total if total is not None else order["quoted_fee_cents"]


# ---------------------------------------------------------------------------
# Order cascades
# ---------------------------------------------------------------------------

def fan_out_pending_lines(order):
    """READY_TO_FULFILL fan-out: every PENDING line item -> QUEUED."""
    for line in lines_of_order(order["id"]):
        if line["line_status"] == "PENDING":
            line["line_status"] = "QUEUED"
            touch(line)


def advance_order_ready(order, actor_role=None, actor_id=None):
    """Move an order into READY_TO_FULFILL and fan out its line items."""
    order["fulfillment_status"] = "READY_TO_FULFILL"
    touch(order)
    fan_out_pending_lines(order)
    if order["order_kind"] == "OFFICIAL":
        emit_audit(
            "TranscriptOrder",
            order["id"],
            actor_role,
            actor_id,
            "HOLD_CLEARED",
        )


def reevaluate_hold_check_orders(student_id):
    """After a hold leaves ACTIVE, advance HOLD_CHECK orders when unblocked."""
    for order in DB["orders"].values():
        if order["student_id"] != student_id:
            continue
        if order["fulfillment_status"] != "HOLD_CHECK":
            continue
        if blocking_hold_exists(student_id):
            continue
        advance_order_ready(order)


def evaluate_order_bubble_up(order):
    """After a line reaches a terminal state, evaluate IN_TRANSIT resolution."""
    if order["fulfillment_status"] != "IN_TRANSIT":
        return
    lines = lines_of_order(order["id"])
    if not lines:
        return
    if not all(l["line_status"] in LINE_TERMINAL for l in lines):
        return
    delivered = sum(1 for l in lines if l["line_status"] == "DELIVERED")
    if delivered >= 1:
        order["fulfillment_status"] = "DELIVERED"
        touch(order)
        emit_audit("TranscriptOrder", order["id"], None, None, "ORDER_DELIVERED")
        # ReissueRequest auto-fulfil: APPROVED reissue whose replacement is delivered.
        for rr in DB["reissue_requests"].values():
            if (
                rr["status"] == "APPROVED"
                and rr.get("replacement_order_id") == order["id"]
            ):
                rr["status"] = "FULFILLED"
                touch(rr)
    else:
        order["fulfillment_status"] = "FAILED"
        touch(order)
        # Auto-refund captured payment in full (order_refund_on_failure).
        for p in payments_of_order(order["id"]):
            if p["status"] in ("CAPTURED", "PARTIALLY_REFUNDED"):
                refundable = p["captured_cents"] - p["refunded_cents"]
                if refundable > 0:
                    p["refunded_cents"] += refundable
                p["status"] = "REFUNDED"
                touch(p)
                order["payment_status"] = "REFUNDED"
        emit_audit("TranscriptOrder", order["id"], None, None, "ORDER_FAILED")


# ---------------------------------------------------------------------------
# Clock-driven re-evaluation (POST /registrar/_clock/set_current_utc)
# ---------------------------------------------------------------------------

def reevaluate_clock_driven():
    """Sweep clock-driven transitions after the logical clock advances."""
    now = logical_now()

    # ConsentGrant: ACTIVE -> EXPIRED at expires_at.
    for g in list(DB["consent_grants"].values()):
        if g["status"] == "ACTIVE" and parse_iso(g["expires_at"]) <= now:
            g["status"] = "EXPIRED"
            touch(g)
            # Cascade: VerificationRequests referencing this grant in
            # CONSENT_CHECK -> DENIED (CONSENT_EXPIRED).
            for vr in DB["verification_requests"].values():
                if (
                    vr.get("consent_grant_id") == g["id"]
                    and vr["status"] == "CONSENT_CHECK"
                ):
                    vr["status"] = "DENIED"
                    vr["denial_reason"] = "CONSENT_EXPIRED"
                    touch(vr)

    # IdentityVerification: PENDING -> EXPIRED at expires_at; bound orders in
    # IDENTITY_PENDING are cancelled.
    for v in list(DB["identity_verifications"].values()):
        if v["status"] == "PENDING" and parse_iso(v["expires_at"]) <= now:
            v["status"] = "EXPIRED"
            for order in DB["orders"].values():
                if (
                    order["id"] == v["order_id"]
                    and order["fulfillment_status"] == "IDENTITY_PENDING"
                ):
                    _cancel_order_internal(order)

    # Hold: FINANCIAL zero-amount ACTIVE holds expire 365 days after placed_at.
    for h in list(DB["holds"].values()):
        if (
            h["status"] == "ACTIVE"
            and h["hold_type"] == "FINANCIAL"
            and h["amount_cents"] == 0
            and now > parse_iso(h["placed_at"]) + timedelta(days=FINANCIAL_HOLD_EXPIRY_DAYS)
        ):
            h["status"] = "EXPIRED"
            touch(h)
            reevaluate_hold_check_orders(h["student_id"])


def _cancel_order_internal(order):
    """Cancel an order: lines to CANCELLED, AUTHORIZED payment voided."""
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    for line in lines_of_order(order["id"]):
        if line["line_status"] not in LINE_TERMINAL:
            line["line_status"] = "CANCELLED"
            touch(line)
    for p in payments_of_order(order["id"]):
        if p["status"] == "AUTHORIZED":
            p["status"] = "VOIDED"
            touch(p)
            order["payment_status"] = "UNPAID"


# ---------------------------------------------------------------------------
# Clearinghouse sweep (scaffold: clearinghouse_sweep)
# ---------------------------------------------------------------------------

def batch_membership():
    """Return {batch_id: {"orders": [...], "verifications": [...]}}."""
    membership = {}
    for b in DB["clearinghouse_batches"].values():
        membership[b["id"]] = {
            "orders": list(b.get("_swept_order_ids", [])),
            "verifications": list(b.get("_swept_verification_ids", [])),
        }
    return membership


def ids_in_active_batches(exclude_batch_id=None):
    """IDs already swept into any non-FAILED batch (optionally excluding one batch)."""
    orders = set()
    verifications = set()
    for b in DB["clearinghouse_batches"].values():
        if exclude_batch_id is not None and b["id"] == exclude_batch_id:
            continue
        if b["status"] in ("OPEN", "LOCKED", "TRANSMITTED", "ACKED"):
            orders.update(b.get("_swept_order_ids", []))
            verifications.update(b.get("_swept_verification_ids", []))
    return orders, verifications


def sweep_batch(batch):
    """Compute the inclusion set for a batch and record counts + membership.

    The batch's own current membership is not an exclusion (a re-sweep at lock
    must not drop the items this batch already holds).
    """
    start = parse_iso(batch["report_period_start"])
    end = parse_iso(batch["report_period_end"])
    swept_orders, swept_vrs = ids_in_active_batches(exclude_batch_id=batch["id"])

    orders = []
    for o in DB["orders"].values():
        if o["fulfillment_status"] != "DELIVERED":
            continue
        if o["id"] in swept_orders:
            continue
        if not o.get("submitted_at"):
            continue
        sub = parse_iso(o["submitted_at"])
        if start <= sub < end:
            orders.append(o)
    # Tie-break on shared submitted_at: created_at ASC, never id.
    orders.sort(key=lambda o: (o["submitted_at"], o["created_at"]))

    vrs = []
    for v in DB["verification_requests"].values():
        if v["status"] != "APPROVED":
            continue
        if v["id"] in swept_vrs:
            continue
        upd = parse_iso(v["updated_at"])
        if start <= upd < end:
            vrs.append(v)
    vrs.sort(key=lambda v: (v["updated_at"], v["created_at"]))

    batch["_swept_order_ids"] = [o["id"] for o in orders]
    batch["_swept_verification_ids"] = [v["id"] for v in vrs]
    batch["order_count"] = len(orders)
    batch["verification_count"] = len(vrs)
