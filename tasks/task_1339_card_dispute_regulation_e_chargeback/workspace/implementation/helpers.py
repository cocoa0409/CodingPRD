"""Shared helpers: body validation, pagination, entity serializers, business rules."""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors
from clock import (
    add_business_days,
    business_days_between,
    end_of_day,
    iso_z,
    iso_z_millis,
)

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

TIER1_MAX_DELAY_DAYS = 2
TIER2_MAX_DELAY_DAYS = 60
TIER1_CAP_CENTS = 5000
TIER2_CAP_CENTS = 50000

WINDOW_STANDARD_DAYS = 45
WINDOW_EXTENDED_DAYS = 90
NEW_ACCOUNT_MAX_AGE_DAYS = 30

BD_STANDARD = 10
BD_NEW_ACCOUNT = 20

NETWORK_FILING_DAYS = {"VISA": 120, "MASTERCARD": 90}
MERCHANT_RESPONSE_DAYS = 30

FILING_FEE_CENTS = 2500
PRE_COMP_BASE_CENTS = 10000
PRE_COMP_PCT = Decimal("0.008")
ARB_BASE_CENTS = 25000
ARB_PCT = Decimal("0.015")

FRAUD_REASON_CODES = {"VISA": {"V10_4", "V10_5"}, "MASTERCARD": {"M4837", "M4870"}}
NONFRAUD_REASON_CODES = {"VISA": {"V13_1", "V13_3"}, "MASTERCARD": {"M4853", "M4855"}}

TRANSACTION_TYPES = {"POS_PIN", "POS_SIGNATURE", "ATM_WITHDRAWAL", "ECOMMERCE", "RECURRING"}
NETWORKS = {"VISA", "MASTERCARD"}
ERROR_TYPES = {
    "UNAUTHORIZED",
    "INCORRECT_AMOUNT",
    "DUPLICATE_CHARGE",
    "SERVICE_NOT_RECEIVED",
    "CANCELLED_RECURRING",
}
REASON_CODES = {"V10_4", "V10_5", "V13_1", "V13_3", "M4837", "M4870", "M4853", "M4855"}
NOTIFICATION_TYPES = {"PROVISIONAL_CREDIT_ADVICE", "REVERSAL_NOTICE", "RESOLUTION_LETTER"}
LOSS_TYPES = {"LOSS_RECOGNIZED", "RECOVERY_RECEIVED"}

NON_TERMINAL_CASE_STATUSES = {
    "RECEIVED",
    "CLASSIFIED",
    "CHARGEBACK_FILED",
    "REPRESENTMENT_REVIEW",
    "REVERSAL_PENDING",
}
OPEN_CREDIT_STATUSES = {"GRANTED", "REINSTATED"}
RESOLVED_CASE_STATUSES = {"RESOLVED_CARDHOLDER_FAVOR", "RESOLVED_MERCHANT_FAVOR"}


# ---------------------------------------------------------------------------
# Request body validation (tier 3, ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def validate_body(body, spec):
    """Validate body against a field spec.

    spec: list of (name, kind, required, allowed_values).
    kind: "string" | "int" | "bool" | "iso" | "evidence"
    Unknown fields are rejected. Missing required fields are rejected.
    Integer amount fields must be strictly greater than zero.
    """
    allowed_names = {name for name, _, _, _ in spec}
    for key in body:
        if key not in allowed_names:
            raise errors.invalid_request(f"Unknown body field: {key}")
    out = {}
    for name, kind, required, allowed_values in spec:
        if name not in body or body[name] is None:
            if required:
                raise errors.invalid_request(f"Missing required field: {name}")
            out[name] = None
            continue
        value = body[name]
        if kind == "string":
            if not isinstance(value, str) or value == "":
                raise errors.invalid_request(f"Field {name} must be a non-empty string")
        elif kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise errors.invalid_request(f"Field {name} must be an integer")
            if value <= 0:
                raise errors.invalid_request(f"Field {name} must be strictly greater than zero")
        elif kind == "int_nonneg":
            if isinstance(value, bool) or not isinstance(value, int):
                raise errors.invalid_request(f"Field {name} must be an integer")
            if value < 0:
                raise errors.invalid_request(f"Field {name} must be >= 0")
        elif kind == "bool":
            if not isinstance(value, bool):
                raise errors.invalid_request(f"Field {name} must be a boolean")
        elif kind == "iso":
            if not isinstance(value, str):
                raise errors.invalid_request(f"Field {name} must be an ISO 8601 string")
        elif kind == "evidence":
            if not isinstance(value, list):
                raise errors.invalid_request(f"Field {name} must be an array")
            for item in value:
                if not isinstance(item, dict):
                    raise errors.invalid_request(f"Field {name} entries must be objects")
                extra = set(item.keys()) - {"doc_type", "reference"}
                if extra:
                    raise errors.invalid_request(
                        f"Field {name} entries carry unknown keys: {sorted(extra)}"
                    )
                if not isinstance(item.get("doc_type"), str) or not item.get("doc_type"):
                    raise errors.invalid_request(f"Field {name} entries need a doc_type")
                if not isinstance(item.get("reference"), str) or not item.get("reference"):
                    raise errors.invalid_request(f"Field {name} entries need a reference")
        if allowed_values is not None and value not in allowed_values:
            raise errors.invalid_request(f"Field {name} has an invalid value: {value}")
        out[name] = value
    return out


def parse_pagination():
    """limit/offset per SCAFFOLD §1.0 pagination_defaults (10 / min 1 / max 100 / 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list; returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Entity construction / mutation
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def stamp_new(clock):
    """Common system fields for primary resources (PRD §2.5)."""
    return {
        "id": new_id(),
        "created_at": clock.now_iso_millis(),
        "updated_at": clock.now_iso_millis(),
        "version": 1,
        "_seq": db.next_sequence(),
    }


def touch(entity, clock):
    """Refresh updated_at and bump version on every mutation (including cascades)."""
    entity["updated_at"] = clock.now_iso_millis()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Business rules (SCAFFOLD §1.3 calculations)
# ---------------------------------------------------------------------------


def account_is_new(account, transaction):
    """New-account rule: transaction posted within 30 days of account opening."""
    from clock import parse_iso

    opened = parse_iso(account["opened_at"])
    posted = parse_iso(transaction["posted_at"])
    return (posted - opened) <= timedelta(days=NEW_ACCOUNT_MAX_AGE_DAYS)


def holdback_for(is_fraud, delay_days, claim_amount_cents):
    """Consumer liability holdback tier (integer cents, no rounding)."""
    if not is_fraud:
        return 0
    if delay_days <= TIER1_MAX_DELAY_DAYS:
        cap = TIER1_CAP_CENTS
    elif delay_days <= TIER2_MAX_DELAY_DAYS:
        cap = TIER2_CAP_CENTS
    else:
        cap = claim_amount_cents
    return min(cap, claim_amount_cents)


def provisional_due_at(clock_received_at, is_new):
    """received_at + 10 business days (20 when new account), end-of-day inclusive."""
    n_bd = BD_NEW_ACCOUNT if is_new else BD_STANDARD
    return end_of_day(add_business_days(clock_received_at, n_bd))


def investigation_window(is_fraud, transaction_type, is_new):
    if is_fraud or transaction_type in ("POS_PIN", "POS_SIGNATURE") or is_new:
        return WINDOW_EXTENDED_DAYS
    return WINDOW_STANDARD_DAYS


def network_filing_deadline(transaction):
    from clock import parse_iso

    posted = parse_iso(transaction["posted_at"])
    days = NETWORK_FILING_DAYS[transaction["network"]]
    return end_of_day(posted + timedelta(days=days))


def stage_fee(stage, amount_cents):
    """Per-stage fee rounded half-up to whole cents BEFORE summing (PRD §2.6)."""
    if stage == "PRE_COMPLIANCE":
        raw = Decimal(PRE_COMP_BASE_CENTS) + PRE_COMP_PCT * Decimal(amount_cents)
    else:  # ARBITRATION
        raw = Decimal(ARB_BASE_CENTS) + ARB_PCT * Decimal(amount_cents)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Cross-entity lookups and cascades
# ---------------------------------------------------------------------------


def case_non_terminal_for_transaction(transaction_id):
    for case in db.dispute_cases.values():
        if (
            case["card_transaction_id"] == transaction_id
            and case["status"] in NON_TERMINAL_CASE_STATUSES
        ):
            return case
    return None


def open_credit_for_case(case_id):
    for credit in db.provisional_credits.values():
        if credit["dispute_case_id"] == case_id and credit["status"] in OPEN_CREDIT_STATUSES:
            return credit
    return None


def any_credit_ever_for_case(case_id):
    """True when any credit reached GRANTED / REINSTATED / FINALIZED for the case."""
    for credit in db.provisional_credits.values():
        if credit["dispute_case_id"] == case_id and credit["status"] in (
            "GRANTED",
            "REINSTATED",
            "FINALIZED",
            "REVERSED",
        ):
            # A credit record only ever exists after a grant (or a direct
            # FINALIZED creation), so any record implies a grant happened.
            return True
    return False


def provisional_outstanding(account_id):
    """Sum of amount_cents over credits in GRANTED or REINSTATED for the account."""
    total = 0
    for credit in db.provisional_credits.values():
        if credit["status"] not in OPEN_CREDIT_STATUSES:
            continue
        case = db.dispute_cases.get(credit["dispute_case_id"])
        if case is not None and case["card_account_id"] == account_id:
            total += credit["amount_cents"]
    return total


def outstanding_loss(case_id):
    total = 0
    for entry in db.loss_recoveries.values():
        if entry["dispute_case_id"] != case_id:
            continue
        if entry["type"] == "LOSS_RECOGNIZED":
            total += entry["amount_cents"]
        else:
            total -= entry["amount_cents"]
    return total


def count_open_fraud_cases(account_id, exclude_case_id=None):
    count = 0
    for case in db.dispute_cases.values():
        if exclude_case_id is not None and case["id"] == exclude_case_id:
            continue
        if (
            case["card_account_id"] == account_id
            and case["is_fraud_claim"] is True
            and case["status"] in NON_TERMINAL_CASE_STATUSES
        ):
            count += 1
    return count


def maybe_restore_account(account, clock):
    """RESTRICTED -> ACTIVE when no non-terminal fraud case references it."""
    if account["status"] != "RESTRICTED":
        return
    if count_open_fraud_cases(account["id"]) == 0:
        account["status"] = "ACTIVE"
        touch(account, clock)


def add_notification(case_id, notif_type, detail, clock):
    notif = {
        "id": new_id(),
        "created_at": clock.now_iso_millis(),
        "_seq": db.next_sequence(),
        "dispute_case_id": case_id,
        "type": notif_type,
        "sent_at": clock.now_iso(),
        "detail": detail,
    }
    db.notifications[notif["id"]] = notif
    return notif


def record_loss_entry(case_id, entry_type, amount_cents, source, clock, memo=None):
    entry = {
        "id": new_id(),
        "created_at": clock.now_iso_millis(),
        "_seq": db.next_sequence(),
        "dispute_case_id": case_id,
        "type": entry_type,
        "amount_cents": amount_cents,
        "source": source,
        "memo": memo,
    }
    db.loss_recoveries[entry["id"]] = entry
    case = db.dispute_cases.get(case_id)
    if case is not None:
        case["outstanding_loss_cents"] = outstanding_loss(case_id)
    return entry


def settle_transaction(case, clock):
    txn = db.card_transactions.get(case["card_transaction_id"])
    if txn is not None and txn["status"] != "SETTLED":
        txn["status"] = "SETTLED"
        touch(txn, clock)


def reversal_notice_cooled(case_id, clock):
    """A REVERSAL_NOTICE exists with >= 3 business days between sent_at and now."""
    for notif in db.notifications.values():
        if notif["dispute_case_id"] == case_id and notif["type"] == "REVERSAL_NOTICE":
            from clock import parse_iso

            sent = parse_iso(notif["sent_at"])
            if business_days_between(sent, clock.now()) >= 3:
                return True
    return False


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_account(account):
    out = _public(account)
    out["provisional_outstanding_cents"] = provisional_outstanding(account["id"])
    return out


def serialize_transaction(txn):
    return _public(txn)


def serialize_case(case):
    return _public(case)


def serialize_credit(credit):
    return _public(credit)


def serialize_chargeback(cb):
    return _public(cb)


def serialize_representment(rep):
    return _public(rep)


def serialize_notification(notif):
    return _public(notif)


def serialize_loss_entry(entry):
    return _public(entry)


def sorted_by_creation(items):
    return sorted(items, key=lambda item: item["_seq"])
