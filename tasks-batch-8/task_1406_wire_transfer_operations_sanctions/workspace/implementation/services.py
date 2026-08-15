"""Shared business logic: audit trail, lazy expiry, screening / risk score,
fee assessment, reservation accounting (PRD §2.4-2.6, §3.3, §3.7)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, base_entity, iso, new_id, new_seq, now, parse_dt, pub, touch
from errors import ERR_NOT_FOUND, ApiError

NON_TERMINAL_WIRE = {"INITIATED", "CALLBACK_PENDING", "PENDING_APPROVAL", "APPROVED", "RELEASING", "REPAIR"}

CALLBACK_THRESHOLD_CENTS = 100000000  # $1,000,000.00, inclusive
RISK_REVIEW_THRESHOLD = 50
BASE_FEE = {"Fedwire": 2500, "SWIFT": 3500, "CHIPS": 1800}
PRIORITY_SURCHARGE_SAME_DAY = 1000
BENEPAY_SHARE = Decimal("0.40")
DEDUCTED_FACTOR = Decimal("0.50")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_or_404(mapping, entity_id, what="resource"):
    obj = mapping.get(entity_id)
    if obj is None:
        raise ApiError(*ERR_NOT_FOUND, f"The requested {what} does not exist.")
    return obj


def wires_of_account(account_id):
    return [w for w in STORE.wires.values() if w["ordering_account_id"] == account_id]


def wires_of_customer(customer_id):
    acct_ids = {a["id"] for a in STORE.accounts.values() if a["customer_id"] == customer_id}
    return [w for w in STORE.wires.values() if w["ordering_account_id"] in acct_ids]


def hits_of_wire(wire_id):
    return [h for h in STORE.sanctions_hits.values() if h["wire_id"] == wire_id]


def unresolved_hits(wire_id):
    return [h for h in hits_of_wire(wire_id) if h["status"] in ("OPEN", "ESCALATED")]


def find_business_date(date_str):
    for bd in STORE.business_dates.values():
        if bd["business_date"] == date_str:
            return bd
    return None


# ---------------------------------------------------------------------------
# Audit trail (append-only; id + created_at only, no updated_at/version)
# ---------------------------------------------------------------------------

def audit(action, entity_type, entity_id, wire_id, detail, actor_user_id="system", actor_role="system"):
    entry = {
        "id": new_id(),
        "created_at": iso(now()),
        "_seq": new_seq(),
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "wire_id": wire_id,
        "detail": detail,
    }
    STORE.audit_logs[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Lazy expiry (PRD §2.5): strict boundary — at or after the deadline the
# window is closed; applied before answering any access to the case or its
# parent wire.
# ---------------------------------------------------------------------------

def lazy_eval_callback(case):
    if case["status"] == "OPEN" and now() >= parse_dt(case["expires_at"]):
        case["status"] = "EXPIRED"
        case["resolved_at"] = iso(now())
        touch(case)
        wire = STORE.wires.get(case["wire_id"])
        if wire is not None and wire["status"] == "CALLBACK_PENDING":
            wire["status"] = "CANCELLED"
            wire["callback_status"] = "NONE"
            touch(wire)
        audit("callback.expired", "CallbackVerification", case["id"], case["wire_id"],
              "status: OPEN -> EXPIRED (verification window lapsed)")


def _freeze_customer_for_fraud(customer):
    if customer["status"] == "ACTIVE":
        customer["status"] = "FROZEN"
        customer["frozen_at"] = iso(now())
        touch(customer)
        audit("customer.frozen", "Customer", customer["id"], None,
              "status: ACTIVE -> FROZEN (confirmed fraud)")


def _cancel_wire_for_fraud(wire):
    before = wire["status"]
    wire["status"] = "CANCELLED"
    wire["hold_reason_code"] = None
    touch(wire)
    return before


def lazy_eval_hold(hold):
    if hold["status"] == "OPEN" and now() >= parse_dt(hold["expires_at"]):
        hold["status"] = "CONFIRMED_FRAUD"
        hold["resolution"] = "AUTO_LAPSED"
        touch(hold)
        wire = STORE.wires.get(hold["wire_id"])
        if wire is not None and wire["status"] == "APPROVED":
            _cancel_wire_for_fraud(wire)
            account = STORE.accounts.get(wire["ordering_account_id"])
            if account is not None:
                customer = STORE.customers.get(account["customer_id"])
                if customer is not None:
                    _freeze_customer_for_fraud(customer)
        audit("fraud.confirmed", "FraudHold", hold["id"], hold["wire_id"],
              "status: OPEN -> CONFIRMED_FRAUD (resolution AUTO_LAPSED)")


def lazy_eval_recall(rec):
    if rec["status"] == "SENT_TO_BENEFICIARY_BANK" and rec["response_due_at"] is not None \
            and now() >= parse_dt(rec["response_due_at"]):
        rec["status"] = "EXPIRED"
        touch(rec)
        # The wire's status is NOT affected — the recall dies, the payment stays EXECUTED.
        audit("recall.expired", "RecallRequest", rec["id"], rec["wire_id"],
              "status: SENT_TO_BENEFICIARY_BANK -> EXPIRED (response window lapsed)")


def lazy_eval_wire(wire):
    for case in list(STORE.callbacks.values()):
        if case["wire_id"] == wire["id"]:
            lazy_eval_callback(case)
    for hold in list(STORE.fraud_holds.values()):
        if hold["wire_id"] == wire["id"]:
            lazy_eval_hold(hold)
    for rec in list(STORE.recalls.values()):
        if rec["wire_id"] == wire["id"]:
            lazy_eval_recall(rec)


# ---------------------------------------------------------------------------
# Risk score + sanctions screening (PRD §3.3)
# ---------------------------------------------------------------------------

def compute_risk_score(wire):
    account = STORE.accounts[wire["ordering_account_id"]]
    customer = STORE.customers[account["customer_id"]]
    beneficiary = STORE.beneficiaries[wire["beneficiary_id"]]

    amt = wire["amount_cents"]
    if amt < 100000000:
        amount_band = 0
    elif amt < 500000000:
        amount_band = 25
    else:
        amount_band = 40

    geo = 20 if customer["high_risk_jurisdiction"] else 0

    watchlist = min(30, 15 * len(unresolved_hits(wire["id"])))

    window_start = now() - timedelta(days=30)
    vel_sum = 0
    for w in wires_of_account(account["id"]):
        if w["status"] in ("EXECUTED", "RECALLED") and w.get("_executed_dt") is not None:
            if window_start <= w["_executed_dt"] <= now():
                vel_sum += w["amount_cents"]
    velocity = 15 if vel_sum > 1000000000 else 0

    behavior = 10 if account["status"] == "DORMANT" else 0
    if wire["method"] == "SWIFT":
        # Cross-border convention: new-beneficiary term is rated per beneficiary
        # BANK (bank_name + country_code) never seen on a prior EXECUTED wire
        # of this account.
        bank_key = (beneficiary["bank_name"], beneficiary["country_code"])
        bank_seen = False
        for w in wires_of_account(account["id"]):
            if w["id"] == wire["id"]:
                continue
            if w["status"] in ("EXECUTED", "RECALLED") and w.get("_executed_dt") is not None:
                other = STORE.beneficiaries.get(w["beneficiary_id"])
                if other is not None and (other["bank_name"], other["country_code"]) == bank_key:
                    bank_seen = True
                    break
        behavior += 0 if bank_seen else 10
    else:
        behavior += 10 if beneficiary["first_used_at"] is None else 0

    raw = amount_band + geo + watchlist + velocity + behavior
    return max(0, min(100, raw))


def run_screening(wire):
    """screening_status NOT_SCREENED -> CLEAR or REVIEW; computes risk_score.
    A risk-driven REVIEW with no party match creates one synthetic
    RISK_THRESHOLD hit so the disposition path is uniform."""
    wire["risk_score"] = compute_risk_score(wire)
    unresolved = unresolved_hits(wire["id"])
    if not unresolved and wire["risk_score"] < RISK_REVIEW_THRESHOLD:
        wire["screening_status"] = "CLEAR"
    else:
        wire["screening_status"] = "REVIEW"
        if not unresolved and wire["risk_score"] >= RISK_REVIEW_THRESHOLD:
            hit = base_entity()
            hit.update({
                "wire_id": wire["id"],
                "matched_list": "INTERNAL_WATCH",
                "matched_party": "RISK_THRESHOLD",
                "match_score": wire["risk_score"],
                "status": "OPEN",
                "decided_by": None,
                "decided_at": None,
            })
            STORE.sanctions_hits[hit["id"]] = hit
        if wire["status"] == "APPROVED" and wire["hold_reason_code"] is None:
            wire["hold_reason_code"] = "SANCTIONS_HOLD"  # a FRAUD_HOLD is never overwritten


# ---------------------------------------------------------------------------
# Fee assessment (PRD §3.7): pinned evaluation order — each component computed
# independently (per-charge round-half-up), then summed; total NOT re-rounded.
# ---------------------------------------------------------------------------

def _round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_fee(wire, kind):
    base_fee = BASE_FEE[wire["method"]]
    priority_fee = PRIORITY_SURCHARGE_SAME_DAY if wire["priority"] == "SAME_DAY" else 0
    beneficiary_share = 0
    if wire["method"] == "SWIFT" and wire["charge_mode"] == "BENEFICIARY_REMUNERATION":
        beneficiary_share = _round_half_up_cents(Decimal(base_fee) * BENEPAY_SHARE)
    source = "PROVISIONAL_ESTIMATE" if kind == "PROVISIONAL" else "ACTUAL_ADVICE"
    correspondent_share = 0
    for c in STORE.charges.values():
        if c["wire_id"] != wire["id"] or c["status"] != "POSTED" or c["source"] != source:
            continue
        if c["charge_type"] == "DEDUCTED_FROM_PRINCIPAL":
            correspondent_share += _round_half_up_cents(Decimal(c["amount_cents"]) * DEDUCTED_FACTOR)
        elif c["charge_type"] == "OUR":
            correspondent_share += c["amount_cents"]
        # charge_type BENEFICIARY contributes 0
    total = base_fee + priority_fee + beneficiary_share + correspondent_share
    return {
        "base_fee_cents": base_fee,
        "priority_fee_cents": priority_fee,
        "beneficiary_share_cents": beneficiary_share,
        "correspondent_share_cents": correspondent_share,
        "total_fee_cents": total,
    }


def posted_deducted_from_principal_cents(wire_id):
    return sum(
        c["amount_cents"]
        for c in STORE.charges.values()
        if c["wire_id"] == wire_id and c["status"] == "POSTED"
        and c["charge_type"] == "DEDUCTED_FROM_PRINCIPAL"
    )


# ---------------------------------------------------------------------------
# Reservation helpers (PRD §2.6)
# ---------------------------------------------------------------------------

def release_reservation(wire):
    if wire["reservation_active"]:
        account = STORE.accounts[wire["ordering_account_id"]]
        account["daily_reserved_cents"] -= wire["amount_cents"]
        touch(account)
        wire["reservation_active"] = False
