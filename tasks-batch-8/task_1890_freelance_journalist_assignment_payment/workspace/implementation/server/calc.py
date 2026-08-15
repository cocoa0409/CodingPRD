"""Calculation rules per scaffold section 1.3 / PRD section 3.
All monetary math is integer cents with floor division (PRD section 2.6)."""

import uuid

from .store import STORE, now, next_seq, touch

DEFAULTS = {
    "kill_fee_post_delivery_pct_num": 50,
    "receipt_required_cents": 2500,
    "category_caps_cents": {"TRAVEL": 50000, "MEALS": 7500, "EQUIPMENT": 20000, "OTHER": 5000},
    "net_terms_days": 30,
    "late_fee_daily_bps": 50,
    "reporting_threshold_cents": 60000,
    "backup_withholding_rate_bps": 2400,
    "foreign_statutory_rate_bps": 3000,
    "treaty_rates_bps": {"GB": 0, "DE": 0, "JP": 1000, "IN": 1500, "BR": 1500},
    "flag_threshold_bps": 2000,
    "ai_flag_threshold_bps": 7000,
    "reuse_royalty_pct_num": 25,
    "all_rights_uplift_pct_num": 35,
}

PRE_DELIVERY_KILL_PCT = 25
DOC_VALIDITY_DAYS = 1095
CREDIT_KINDS = {"FEE_CREDIT", "EXPENSE_CREDIT", "LATE_FEE_CREDIT", "REUSE_ROYALTY_CREDIT"}


def cfg(key):
    dc = STORE.desk_config
    if dc is not None and key in dc and dc[key] is not None:
        return dc[key]
    return DEFAULTS[key]


def category_cap(category):
    caps = cfg("category_caps_cents")
    if isinstance(caps, dict) and category in caps:
        return caps[category]
    return DEFAULTS["category_caps_cents"][category]


def fee_kill(assignment):
    """Kill variant of assignment_fee_due."""
    base = assignment["agreed_fee_cents"]
    if assignment["kill_fee_tier"] == "PRE_DELIVERY":
        tier_pct = PRE_DELIVERY_KILL_PCT
    else:
        tier_pct = cfg("kill_fee_post_delivery_pct_num")
    fee = base * tier_pct // 100
    if assignment["late_flag"] and assignment["kill_fee_tier"] == "POST_DELIVERY":
        fee = fee // 2
    return fee


def fee_accepted(assignment, agreement):
    """Accepted variant of assignment_fee_due."""
    if agreement["pricing_mode"] == "PER_WORD":
        return assignment["final_word_count"] * agreement["per_word_rate_cents"]
    return agreement["flat_fee_cents"]


def latest_valid_tax_doc(contributor_id, at=None):
    """Most recent VERIFIED, unexpired TaxDocument: max submitted_at, tie -> max created_at."""
    at = at if at is not None else now()
    docs = [
        d for d in STORE.tax_documents.values()
        if d["contributor_id"] == contributor_id
        and d["status"] == "VERIFIED"
        and d["expires_at"] >= at
    ]
    if not docs:
        return None
    return max(docs, key=lambda d: (d["submitted_at"], d["created_at"], d["_seq"]))


def withholding_cents(fee_cents, contributor):
    """withholding_computation: fee portion only; pinned branch order."""
    doc = latest_valid_tax_doc(contributor["id"])
    if contributor["tax_residency"] == "DOMESTIC_US":
        if contributor["backup_withholding_flag"] or doc is None:
            rate_bps = cfg("backup_withholding_rate_bps")
        else:
            rate_bps = 0
    else:
        if doc is None:
            rate_bps = cfg("foreign_statutory_rate_bps")
        else:
            rate_bps = cfg("treaty_rates_bps").get(
                doc["treaty_country"], cfg("foreign_statutory_rate_bps")
            )
    return fee_cents * rate_bps // 10000


def reuse_royalty(final_fee_cents):
    return final_fee_cents * cfg("reuse_royalty_pct_num") // 100


def rights_uplift(final_fee_cents):
    return final_fee_cents * cfg("all_rights_uplift_pct_num") // 100


def late_fee_cents(invoice, scheduled_pay_date):
    delta_seconds = (scheduled_pay_date - invoice["due_date_utc"]).total_seconds()
    days_overdue = max(0, int(delta_seconds // 86400))
    return invoice["net_payable_cents"] * cfg("late_fee_daily_bps") * days_overdue // 10000


def has_valid_tax_doc(contributor_id):
    return latest_valid_tax_doc(contributor_id) is not None


def post_ledger(invoice_id, contributor_id, entry_kind, amount_cents):
    t = now()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "_seq": next_seq(),
        "invoice_id": invoice_id,
        "contributor_id": contributor_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "posted_at": t,
    }
    STORE.ledger_entries[e["id"]] = e
    return e


def sync_ytd(contributor):
    """contributor_ytd_gross: credit kinds only, calendar year of now (UTC, inclusive)."""
    n = now()
    total = sum(
        e["amount_cents"]
        for e in STORE.ledger_entries.values()
        if e["contributor_id"] == contributor["id"]
        and e["entry_kind"] in CREDIT_KINDS
        and e["posted_at"].year == n.year
    )
    flag = total >= cfg("reporting_threshold_cents")
    if contributor["ytd_gross_cents"] != total or contributor["reportable_threshold_crossed"] != flag:
        contributor["ytd_gross_cents"] = total
        contributor["reportable_threshold_crossed"] = flag
        touch(contributor)


def reports_of(assignment_id):
    return [
        r for r in STORE.verification_reports.values()
        if r["assignment_id"] == assignment_id
    ]


def sync_verification_cleared(assignment):
    """True iff the assignment has reports and every one is CLEARED or DISMISSED."""
    reports = reports_of(assignment["id"])
    cleared = bool(reports) and all(
        r["status"] in ("CLEARED", "DISMISSED") for r in reports
    )
    if assignment["verification_cleared"] != cleared:
        assignment["verification_cleared"] = cleared
        touch(assignment)


def verification_gate_open(assignment):
    """verification_cleared, or KILLED with no report in PENDING/FLAGGED."""
    if assignment["verification_cleared"]:
        return True
    if assignment["editorial_status"] == "KILLED":
        return not any(
            r["status"] in ("PENDING", "FLAGGED") for r in reports_of(assignment["id"])
        )
    return False
