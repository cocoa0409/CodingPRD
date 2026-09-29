"""Conserved derived quantities and cross-aggregate reconciliation (PRD §2.12)."""

import db
from services import calculations as calc


def recompute_evidence_sample_total(plan):
    """ServicePlan.evidence_sample_total — sum over INCLUDED runs."""
    total = 0
    for run in db.store.test_runs.values():
        if run["plan_id"] == plan["id"] and run["status"] == "INCLUDED":
            total += run["sample_count"]
    plan["evidence_sample_total"] = total
    return total


def recompute_upheld_complaint_count(plan):
    """ServicePlan.upheld_complaint_count — complaints of the plan's accounts."""
    count = 0
    for complaint in db.store.complaints.values():
        if complaint["state"] != "UPHELD":
            continue
        account = db.store.subscriber_accounts.get(complaint["account_id"])
        if account is not None and account["plan_id"] == plan["id"]:
            count += 1
    plan["upheld_complaint_count"] = count
    return count


def recompute_account_credit_totals(account):
    """credit_balance_cents / remediation_count / audit_flag (PRD §2.12)."""
    balance = 0
    count = 0
    for credit in db.store.remediation_credits.values():
        if credit["account_id"] == account["id"] and credit["status"] == "ISSUED":
            balance += credit["amount_cents"]
            count += 1
    account["credit_balance_cents"] = balance
    account["remediation_count"] = count
    account["audit_flag"] = count >= calc.REMEDIATION_AUDIT_THRESHOLD
    db.touch(account)


def recompute_verified_locale_count(label):
    count = 0
    for translation in db.store.label_translations.values():
        if (translation["label_version_id"] == label["id"]
                and translation["status"] == "VERIFIED"):
            count += 1
    label["verified_locale_count"] = count
    return count


def recompute_last_disclosed_label(account):
    latest = None
    for disclosure in db.store.label_disclosures.values():
        if disclosure["account_id"] != account["id"]:
            continue
        if latest is None or disclosure["_seq"] > latest["_seq"]:
            latest = disclosure
    account["last_disclosed_label_version_id"] = (
        latest["label_version_id"] if latest is not None else None)


LABEL_FIGURE_FIELDS = (
    "fee_itemization",
    "monthly_total_intro_cents",
    "monthly_total_post_promo_cents",
    "discount_program_benefit_intro_cents",
    "discount_program_benefit_post_promo_cents",
    "net_monthly_intro_cents",
    "net_monthly_post_promo_cents",
    "one_time_fee_total_cents",
    "first_year_total_promo_weighted_cents",
    "first_year_total_post_promo_cents",
    "etf_disclosure_cents",
    "data_allowance_gb_snapshot",
    "overage_rate_cents_per_gb_snapshot",
)


def apply_label_figures(plan, label):
    """(Re)compute the priced face of a label; returns True when it changed."""
    figures = calc.compute_label_figures(plan, label["discount_program_applied"])
    changed = any(label.get(key) != value for key, value in figures.items())
    label.update(figures)
    return changed


def recompute_draft_labels(plan):
    """Every DRAFT label of the plan is recomputed; pinned labels are not."""
    for label in db.ordered(db.store.label_versions.values()):
        if label["plan_id"] != plan["id"]:
            continue
        if label["publication_state"] != "DRAFT":
            continue
        if apply_label_figures(plan, label):
            db.touch(label)
