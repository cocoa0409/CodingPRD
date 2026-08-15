"""Domain services: record lifecycle, views, audit chain, cascades, clock evaluation."""
import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from db import STORE, AUDIT_EVENTS, next_seq, get_clock
from helpers import fmt_dt, new_uuid, rhu, add_years, parse_dt

DORMANCY_YEARS = {"CA": 3, "NY": 5, "TX": 3}
DORMANCY_DEFAULT = 5

BOND_MULTIPLIER = 2
PREMIUM_TIER1_CAP_CENTS = 10000000
PREMIUM_TIER1_RATE = Decimal("0.03")
PREMIUM_TIER2_RATE = Decimal("0.02")

MILLICENTS_PER_CENT = 1000
STALE_DAYS = 180
NOTICE_WINDOW_DAYS = 60
HOLDING_PERIOD_DAYS = 180

OPEN_CLAIM_STATUSES = {"FILED", "BOND_POSTED", "APPROVED"}
OPEN_CASE_STATUSES = {"IDENTIFIED", "NOTICE_SENT", "REPORTED"}


# ---------------------------------------------------------------- clock / ids

def now_dt():
    return get_clock()


def now_iso():
    return fmt_dt(get_clock())


def stamp_new(rec):
    rec["id"] = new_uuid()
    rec["created_at"] = now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def sorted_recs(kind):
    return sorted(STORE[kind].values(), key=lambda r: r["_seq"])


# ---------------------------------------------------------------- audit chain

def audit(entity_type, entity_id, actor_role, actor_id, action, from_state, to_state, detail):
    prev_hash = AUDIT_EVENTS[-1]["entry_hash"] if AUDIT_EVENTS else "GENESIS"
    canonical = json.dumps(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "action": action,
            "from_state": from_state,
            "to_state": to_state,
            "detail": detail,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    entry_hash = hashlib.sha256((prev_hash + "|" + canonical).encode("utf-8")).hexdigest()
    event = {
        "id": new_uuid(),
        "created_at": now_iso(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "from_state": from_state,
        "to_state": to_state,
        "detail": detail,
        "prev_entry_hash": prev_hash,
        "entry_hash": entry_hash,
        "_seq": next_seq(),
    }
    AUDIT_EVENTS.append(event)
    return event


# ---------------------------------------------------------------- views

def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def issuer_view(issuer):
    d = pub(issuer)
    positions = [p for p in STORE["positions"].values() if p["issuer_id"] == issuer["id"]]
    d["total_book_entry_shares"] = sum(p["book_entry_shares"] for p in positions)
    d["total_certificated_shares"] = sum(p["certificated_shares"] for p in positions)
    return d


def account_view(account):
    d = pub(account)
    d["dormancy_years"] = DORMANCY_YEARS.get(account["state_code"], DORMANCY_DEFAULT)
    return d


def position_view(position):
    d = pub(position)
    d["total_shares"] = position["book_entry_shares"] + position["certificated_shares"]
    return d


def certificate_view(cert):
    return pub(cert)


def transfer_view(transfer):
    return pub(transfer)


def claim_view(claim):
    return pub(claim)


def declaration_view(decl):
    return pub(decl)


def payment_view(payment):
    return pub(payment)


def legend_view(req):
    return pub(req)


def case_view(case):
    return pub(case)


def inquiry_view(inquiry):
    return pub(inquiry)


def window_view(window):
    return pub(window)


def audit_event_view(event):
    return pub(event)


# ---------------------------------------------------------------- lookups

def find_position(account_id, issuer_id):
    for p in STORE["positions"].values():
        if p["account_id"] == account_id and p["issuer_id"] == issuer_id:
            return p
    return None


def positions_of_account(account_id):
    return sorted(
        [p for p in STORE["positions"].values() if p["account_id"] == account_id],
        key=lambda r: r["_seq"],
    )


def positions_of_issuer(issuer_id):
    return sorted(
        [p for p in STORE["positions"].values() if p["issuer_id"] == issuer_id],
        key=lambda r: r["_seq"],
    )


def payments_of_declaration(declaration_id):
    return sorted(
        [p for p in STORE["payments"].values() if p["declaration_id"] == declaration_id],
        key=lambda r: r["_seq"],
    )


def payments_of_account(account_id):
    return sorted(
        [p for p in STORE["payments"].values() if p["account_id"] == account_id],
        key=lambda r: r["_seq"],
    )


def cases_of_account(account_id):
    return sorted(
        [c for c in STORE["escheatment_cases"].values() if c["account_id"] == account_id],
        key=lambda r: r["_seq"],
    )


def open_case_for_account(account_id):
    for c in cases_of_account(account_id):
        if c["status"] in OPEN_CASE_STATUSES:
            return c
    return None


def reactivated_case_for_account(account_id):
    for c in cases_of_account(account_id):
        if c["status"] == "REACTIVATED":
            return c
    return None


def open_claim_for_certificate(certificate_id):
    for c in sorted_recs("claims"):
        if c["certificate_id"] == certificate_id and c["status"] in OPEN_CLAIM_STATUSES:
            return c
    return None


def new_certificate_number():
    return "CERT-" + new_uuid().replace("-", "")[:12].upper()


# ---------------------------------------------------------------- calculations

def withholding_rate(account):
    tin = account["tin_status"]
    if tin in ("MISSING", "UNCERTIFIED"):
        return Decimal("0.24")
    if account["residency"] == "US":
        return Decimal("0")
    return Decimal("0.15") if account["treaty_tier"] == "TREATY" else Decimal("0.30")


def withholding_for(gross_cents, account):
    return rhu(Decimal(gross_cents) * withholding_rate(account))


def gross_for(eligible_shares, amount_per_share_millicents):
    return rhu(Decimal(eligible_shares * amount_per_share_millicents) / Decimal(MILLICENTS_PER_CENT))


def bond_pricing(claim, certificate, issuer, bond_variant):
    if bond_variant == "OPEN_PENALTY":
        price = issuer["current_market_price_cents"]
    else:  # FIXED_PENALTY
        price = claim["loss_report_price_cents"]
    bond_amount = certificate["share_quantity"] * price * BOND_MULTIPLIER
    premium = rhu(
        Decimal(min(bond_amount, PREMIUM_TIER1_CAP_CENTS)) * PREMIUM_TIER1_RATE
        + Decimal(max(0, bond_amount - PREMIUM_TIER1_CAP_CENTS)) * PREMIUM_TIER2_RATE
    )
    return bond_amount, premium


# ---------------------------------------------------------------- cascades

def reactivate_account(account, actor_role, actor_id):
    """DORMANT -> ACTIVE plus escheatment-case reactivation cascade (PRD 3.7)."""
    if account["account_status"] == "DORMANT":
        account["account_status"] = "ACTIVE"
        account["last_qualifying_contact_date"] = now_iso()
        touch(account)
        audit("ShareholderAccount", account["id"], actor_role, actor_id,
              "account.reactivate", "DORMANT", "ACTIVE", "qualifying owner contact")
        for case in cases_of_account(account["id"]):
            if case["status"] in ("IDENTIFIED", "NOTICE_SENT"):
                frm = case["status"]
                case["status"] = "REACTIVATED"
                touch(case)
                audit("EscheatmentCase", case["id"], actor_role, actor_id,
                      "case.reactivate", frm, "REACTIVATED", "owner contact reactivation")
    else:
        account["last_qualifying_contact_date"] = now_iso()
        touch(account)


def create_or_rearm_case(account, actor_role, actor_id):
    """Open a fresh IDENTIFIED case or re-arm a REACTIVATED one. Returns 'created',
    'rearmed', or None when an open case already exists."""
    if open_case_for_account(account["id"]) is not None:
        return None
    existing = reactivated_case_for_account(account["id"])
    if existing is not None:
        existing["status"] = "IDENTIFIED"
        existing["dormancy_start_date"] = account["last_qualifying_contact_date"]
        touch(existing)
        audit("EscheatmentCase", existing["id"], actor_role, actor_id,
              "case.rearmed", "REACTIVATED", "IDENTIFIED", "dormancy case re-armed")
        return "rearmed"
    case = stamp_new({
        "account_id": account["id"],
        "status": "IDENTIFIED",
        "dormancy_start_date": account["last_qualifying_contact_date"],
        "notice_sent_at": None,
        "report_price_cents": None,
        "share_value_cents": None,
        "cash_value_cents": None,
        "total_remit_cents": None,
    })
    STORE["escheatment_cases"][case["id"]] = case
    audit("EscheatmentCase", case["id"], actor_role, actor_id,
          "case.create", "", "IDENTIFIED", "escheatment case identified")
    return "created"


def account_holds_property(account):
    for p in positions_of_account(account["id"]):
        if p["book_entry_shares"] + p["certificated_shares"] > 0:
            return True
    return account["stale_dividend_cents"] > 0


def maybe_close_declaration(declaration_id, actor_role, actor_id):
    decl = STORE["declarations"].get(declaration_id)
    if decl is None or decl["status"] != "PAYABLE":
        return
    payments = payments_of_declaration(declaration_id)
    if payments and all(p["status"] in ("RECONCILED", "ESCHEATED") for p in payments):
        decl["status"] = "CLOSED"
        touch(decl)
        audit("DividendDeclaration", decl["id"], actor_role, actor_id,
              "declaration.closed", "PAYABLE", "CLOSED",
              "all payments reached terminal states")


# ---------------------------------------------------------------- clock evaluation

def _accrue_declaration(decl, now, actor_role, actor_id):
    """DECLARED -> ACCRUED: generate one payment per eligible position."""
    issuer = STORE["issuers"].get(decl["issuer_id"])
    total_shares = 0
    total_cents = 0
    for position in positions_of_issuer(decl["issuer_id"]):
        if position["status"] != "ACTIVE":
            continue
        account = STORE["accounts"].get(position["account_id"])
        if account is None or account["account_status"] == "ESCHEATED":
            continue
        eligible = position["book_entry_shares"] + position["certificated_shares"]
        gross = gross_for(eligible, decl["amount_per_share_millicents"])
        provisional = withholding_for(gross, account)
        payment = stamp_new({
            "declaration_id": decl["id"],
            "account_id": position["account_id"],
            "eligible_shares": eligible,
            "gross_cents": gross,
            "provisional_withholding_cents": provisional,
            "withholding_cents": None,
            "net_cents": None,
            "status": "ACCRUED",
            "disbursed_at": None,
            "returned_at": None,
        })
        STORE["payments"][payment["id"]] = payment
        audit("DividendPayment", payment["id"], actor_role, actor_id,
              "payment.accrued", "", "ACCRUED", "dividend accrued at record lock")
        total_shares += eligible
        total_cents += gross
    decl["total_eligible_shares"] = total_shares
    decl["total_accrued_cents"] = total_cents
    decl["status"] = "ACCRUED"
    touch(decl)
    audit("DividendDeclaration", decl["id"], actor_role, actor_id,
          "declaration.accrued", "DECLARED", "ACCRUED", "record-date accrual")


def _disburse_declaration(decl, now, actor_role, actor_id):
    """ACCRUED -> PAYABLE: disburse every ACCRUED payment with final withholding."""
    for payment in payments_of_declaration(decl["id"]):
        if payment["status"] != "ACCRUED":
            continue
        account = STORE["accounts"].get(payment["account_id"])
        final_wh = withholding_for(payment["gross_cents"], account) if account else 0
        payment["withholding_cents"] = final_wh
        payment["net_cents"] = payment["gross_cents"] - final_wh
        payment["status"] = "DISBURSED"
        payment["disbursed_at"] = now_iso()
        touch(payment)
        audit("DividendPayment", payment["id"], actor_role, actor_id,
              "payment.disbursed", "ACCRUED", "DISBURSED", "dividend disbursed")
    decl["status"] = "PAYABLE"
    touch(decl)
    audit("DividendDeclaration", decl["id"], actor_role, actor_id,
          "declaration.payable", "ACCRUED", "PAYABLE", "declaration became payable")


def _stale_date_payment(payment, now, actor_role, actor_id):
    payment["status"] = "STALE_DATED"
    touch(payment)
    audit("DividendPayment", payment["id"], actor_role, actor_id,
          "payment.stale_dated", "DISBURSED", "STALE_DATED", "uncashed past 180 days")
    account = STORE["accounts"].get(payment["account_id"])
    if account is None:
        return
    account["stale_dividend_cents"] += payment["gross_cents"]
    touch(account)
    if account["account_status"] == "DORMANT" and open_case_for_account(account["id"]) is None:
        create_or_rearm_case(account, actor_role, actor_id)


def evaluate_clock(now, actor_role, actor_id):
    """Evaluate every time-gated system transition at the new instant (PRD 2.4)."""
    # 1. declarations reaching their record date accrue (issuer must be ACTIVE)
    for decl in sorted_recs("declarations"):
        if decl["status"] != "DECLARED":
            continue
        if parse_dt(decl["record_date"], "record_date") <= now:
            issuer = STORE["issuers"].get(decl["issuer_id"])
            if issuer is not None and issuer["status"] == "ACTIVE":
                _accrue_declaration(decl, now, actor_role, actor_id)
    # 2. accrued declarations reaching their payable date disburse
    for decl in sorted_recs("declarations"):
        if decl["status"] == "ACCRUED" and parse_dt(decl["payable_date"], "payable_date") <= now:
            _disburse_declaration(decl, now, actor_role, actor_id)
    # 3. disbursed payments sitting uncashed for 180 days go stale (inclusive)
    for payment in sorted_recs("payments"):
        if payment["status"] == "DISBURSED" and payment["disbursed_at"]:
            horizon = parse_dt(payment["disbursed_at"], "disbursed_at") + timedelta(days=STALE_DAYS)
            if now >= horizon:
                _stale_date_payment(payment, now, actor_role, actor_id)
    # 4. freeze windows activate at start_date and expire once past end_date
    for window in sorted_recs("freeze_windows"):
        if window["status"] == "SCHEDULED" and parse_dt(window["start_date"], "start_date") <= now:
            window["status"] = "ACTIVE"
            touch(window)
            audit("TransferFreezeWindow", window["id"], actor_role, actor_id,
                  "freeze.activated", "SCHEDULED", "ACTIVE", "freeze window start reached")
        if window["status"] == "ACTIVE" and parse_dt(window["end_date"], "end_date") < now:
            window["status"] = "EXPIRED"
            touch(window)
            audit("TransferFreezeWindow", window["id"], actor_role, actor_id,
                  "freeze.expired", "ACTIVE", "EXPIRED", "freeze window end passed")


def freeze_window_blocks(issuer_id, now):
    """True when the clock falls inside any live freeze window (closed interval)."""
    for window in STORE["freeze_windows"].values():
        if window["issuer_id"] != issuer_id:
            continue
        if window["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if parse_dt(window["start_date"], "start_date") <= now <= parse_dt(window["end_date"], "end_date"):
            return True
    return False
