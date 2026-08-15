"""Core shared services: record lifecycle, derived ledger fields, cascades,
verified financials, presumptive scoring, ECA window, report aggregation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db import db
from util import CLOCK, fmt_dt, new_id, now_ts, parse_dt, round_half_up, to_decimal


# ---------------------------------------------------------------------------
# Record lifecycle (PRD 2.5)
# ---------------------------------------------------------------------------

def new_record(collection, fields, versioned=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and increment version (PRD 2.5; cascades included)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def active_policy():
    for p in db["policies"].values():
        if p["status"] == "ACTIVE":
            return p
    return None


def pinned_policy(application):
    pid = application.get("policy_id")
    if pid:
        return db["policies"].get(pid)
    return None


def members_of(application_id):
    return [m for m in db["members"].values() if m["application_id"] == application_id]


def household_size(application_id):
    return len(members_of(application_id))


def get_screening(application_id):
    for s in db["screenings"].values():
        if s["application_id"] == application_id:
            return s
    return None


def documents_of(application_id):
    return [d for d in db["documents"].values() if d["application_id"] == application_id]


def payments_of(account_id):
    return [p for p in db["payments"].values() if p["account_id"] == account_id]


def adjustments_of_account(account_id):
    return [a for a in db["adjustments"].values() if a["account_id"] == account_id]


def open_application_for_patient(patient_id):
    """An application in SUBMITTED/UNDER_REVIEW/PENDING_DOCUMENTS (PRD 2.9 freeze)."""
    for a in db["applications"].values():
        if a["patient_id"] == patient_id and a["status"] in (
            "SUBMITTED", "UNDER_REVIEW", "PENDING_DOCUMENTS"
        ):
            return a
    return None


# ---------------------------------------------------------------------------
# Derived ledger fields (PRD 2.12 — evaluation order is pinned)
# ---------------------------------------------------------------------------

def adjusted_balance_cents(account) -> int:
    write_offs = sum(
        a["amount_cents"]
        for a in db["adjustments"].values()
        if a["account_id"] == account["id"]
        and a["adjustment_type"] == "WRITE_OFF"
        and a["status"] == "POSTED"
    )
    return account["patient_responsibility_cents"] - write_offs


def effective_payments_cents(account) -> int:
    return sum(
        p["amount_cents"] - p["refunded_cents"] for p in payments_of(account["id"])
    )


def amount_outstanding_cents(account) -> int:
    return max(0, adjusted_balance_cents(account) - effective_payments_cents(account))


def overpayment_cents(account) -> int:
    return max(0, effective_payments_cents(account) - adjusted_balance_cents(account))


def account_view(account):
    out = public(account)
    ab = adjusted_balance_cents(account)
    ep = effective_payments_cents(account)
    out["adjusted_balance_cents"] = ab
    out["effective_payments_cents"] = ep
    out["amount_outstanding_cents"] = max(0, ab - ep)
    out["overpayment_cents"] = max(0, ep - ab)
    return out


def application_view(app):
    out = public(app)
    out["household_size"] = household_size(app["id"])
    income, assets = verified_financials(app["id"])
    out["annualized_verified_income_cents"] = income
    out["verified_liquid_assets_cents"] = assets
    return out


# ---------------------------------------------------------------------------
# Verified household financials (calc: verified_household_financials)
# ---------------------------------------------------------------------------

ANNUALIZATION = {"PAY_STUB": 26, "BENEFIT_LETTER": 12, "TAX_RETURN": 1}
INCOME_DOC_TYPES = {"PAY_STUB", "BENEFIT_LETTER", "TAX_RETURN"}


def verified_financials(application_id):
    income = 0
    assets = 0
    for d in documents_of(application_id):
        if d["status"] != "VERIFIED":
            continue
        if d["doc_type"] in INCOME_DOC_TYPES:
            income += d["amount_cents"] * ANNUALIZATION[d["doc_type"]]
        elif d["doc_type"] == "BANK_STATEMENT":
            assets += d["amount_cents"]
    return income, assets


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def create_notice(account_id, application_id, notice_type,
                  delivery_channel="MAIL", is_plain_language=True):
    return new_record("notices", {
        "account_id": account_id,
        "application_id": application_id,
        "notice_type": notice_type,
        "delivery_channel": delivery_channel,
        "is_plain_language": is_plain_language,
        "issued_at": CLOCK.now_iso(),
    }, versioned=False)


# ---------------------------------------------------------------------------
# Account posture cascades
# ---------------------------------------------------------------------------

def halt_initiated_actions(account, reason):
    for ca in db["collection_actions"].values():
        if ca["account_id"] == account["id"] and ca["status"] == "INITIATED":
            ca["status"] = "HALTED"
            ca["halted_at"] = CLOCK.now_iso()
            ca["halt_reason"] = reason
            touch(ca)


def resolve_account_if_zero(account):
    """If amount_outstanding hits 0 the account holds RESOLVED (PRD 2.12);
    INITIATED collection actions halt with ACCOUNT_RESOLVED (PRD 3.9/3.10)."""
    if amount_outstanding_cents(account) == 0 and account["collection_posture"] != "RESOLVED":
        account["collection_posture"] = "RESOLVED"
        halt_initiated_actions(account, "ACCOUNT_RESOLVED")
        return True
    return False


def freeze_accounts_for_application(patient_id):
    """Submit freeze: NOTICE_PERIOD / ECA_ELIGIBLE / ECA_ACTIVE -> ASSISTANCE_HOLD."""
    for acct in db["accounts"].values():
        if acct["patient_id"] != patient_id:
            continue
        if acct["collection_posture"] in ("NOTICE_PERIOD", "ECA_ELIGIBLE", "ECA_ACTIVE"):
            acct["collection_posture"] = "ASSISTANCE_HOLD"
            touch(acct)


def release_holds_for_patient(patient_id):
    """Terminal-application release: ASSISTANCE_HOLD -> NOTICE_PERIOD."""
    for acct in db["accounts"].values():
        if acct["patient_id"] != patient_id:
            continue
        if acct["collection_posture"] == "ASSISTANCE_HOLD":
            acct["collection_posture"] = "NOTICE_PERIOD"
            touch(acct)


# ---------------------------------------------------------------------------
# 501(r) ECA clearance window (calc: eca_clearance_window; PRD 2.9)
# ---------------------------------------------------------------------------

def eca_window_met(account) -> bool:
    """Both gates inclusive, read from the policy ACTIVE at evaluation time."""
    policy = active_policy()
    if policy is None:
        return False
    fsa = account.get("first_statement_at")
    if fsa is None:
        return False
    now = CLOCK.now()
    notification_met = now >= parse_dt(fsa) + timedelta(days=policy["notification_period_days"])
    if not notification_met:
        return False
    threshold = now - timedelta(days=policy["eca_notice_days"])
    for n in db["notices"].values():
        if (
            n.get("account_id") == account["id"]
            and n["notice_type"] == "ECA_WARNING"
            and parse_dt(n["issued_at"]) <= threshold
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Presumptive eligibility score (calc: presumptive_eligibility_score)
# ---------------------------------------------------------------------------

FACTOR_WEIGHTS = {
    "income_band": Decimal("0.35"),
    "payment_history": Decimal("0.25"),
    "utilization": Decimal("0.15"),
    "public_benefit": Decimal("0.15"),
    "housing_stability": Decimal("0.10"),
}

# request field name -> weight key
FACTOR_FIELDS = {
    "income_band_score": "income_band",
    "payment_history_score": "payment_history",
    "utilization_score": "utilization",
    "public_benefit_score": "public_benefit",
    "housing_stability_score": "housing_stability",
}


def score_screening(scores: dict, policy):
    """scores: {factor_key: int|None}. Returns (present_count, thin_file, score_float, outcome)."""
    present = {f: s for f, s in scores.items() if s is not None}
    count = len(present)
    thin_file = count < 5
    raw = sum(FACTOR_WEIGHTS[f] * Decimal(s) for f, s in present.items())
    if thin_file:
        denom = sum(FACTOR_WEIGHTS[f] for f in present)
        score = round_half_up(raw / denom, 2)
    else:
        score = round_half_up(raw, 2)
    full_th = to_decimal(policy["presumptive_full_score_threshold"])
    partial_th = to_decimal(policy["presumptive_partial_score_threshold"])
    if score >= full_th:
        outcome = "ELIGIBLE_FULL"
    elif score >= partial_th:
        outcome = "ELIGIBLE_PARTIAL"
    else:
        outcome = "NOT_ELIGIBLE"
    return count, thin_file, float(score), outcome


# ---------------------------------------------------------------------------
# Discount tier assignment (calc: discount_tier_assignment + fpl_percentage)
# ---------------------------------------------------------------------------

def compute_fpl_pct(income_cents: int, hh_size: int, policy) -> Decimal:
    fpl_amount = policy["fpl_base_cents"] + (hh_size - 1) * policy["fpl_increment_cents"]
    return round_half_up(Decimal(income_cents) * Decimal(100) / Decimal(fpl_amount), 4)


def assign_tier_verified(application, policy):
    """Returns (fpl_pct Decimal, tier, discount_pct Decimal)."""
    income, assets = verified_financials(application["id"])
    hh = household_size(application["id"])
    fpl_pct = compute_fpl_pct(income, hh, policy)
    if assets > policy["asset_limit_cents"]:
        return fpl_pct, "INELIGIBLE", Decimal("0.00")
    full_max = to_decimal(policy["full_discount_max_fpl_pct"])
    partial_max = to_decimal(policy["partial_discount_max_fpl_pct"])
    if fpl_pct <= full_max:
        return fpl_pct, "TIER_FULL", Decimal("100.00")
    if fpl_pct <= partial_max:
        floor = to_decimal(policy["partial_discount_floor_pct"])
        disc = floor + (partial_max - fpl_pct) * (Decimal(100) - floor) / (partial_max - full_max)
        return fpl_pct, "TIER_PARTIAL", round_half_up(disc, 2)
    return fpl_pct, "INELIGIBLE", Decimal("0.00")


def assign_tier_presumptive(screening):
    """Flat discounts; income/assets/household not consulted."""
    if screening["outcome"] == "ELIGIBLE_FULL":
        return None, "TIER_FULL", Decimal("100.00")
    if screening["outcome"] == "ELIGIBLE_PARTIAL":
        return None, "TIER_PARTIAL", Decimal("50.00")
    return None, "INELIGIBLE", Decimal("0.00")


# ---------------------------------------------------------------------------
# Community benefit aggregation (calc: community_benefit_aggregation)
# ---------------------------------------------------------------------------

def compute_report_totals(year: int):
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    total_wo = 0
    total_std = 0
    total_pre = 0
    total_ref = 0
    assisted = set()
    for adj in db["adjustments"].values():
        if adj["status"] != "POSTED":
            continue
        det = db["determinations"].get(adj["determination_id"])
        if det is None or not det.get("finalized_at"):
            continue
        fa = parse_dt(det["finalized_at"])
        if not (start <= fa < end):
            continue
        if adj["adjustment_type"] == "WRITE_OFF":
            total_wo += adj["amount_cents"]
            if det["basis"] == "VERIFIED_APPLICATION":
                total_std += adj["amount_cents"]
            elif det["basis"] == "PRESUMPTIVE_SCORE":
                total_pre += adj["amount_cents"]
            assisted.add(adj["account_id"])
        elif adj["adjustment_type"] == "REFUND":
            total_ref += adj["amount_cents"]
    return {
        "total_write_offs_cents": total_wo,
        "total_standard_write_offs_cents": total_std,
        "total_presumptive_write_offs_cents": total_pre,
        "total_refunds_cents": total_ref,
        "accounts_assisted_count": len(assisted),
    }
