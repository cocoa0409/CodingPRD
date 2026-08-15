"""Business logic: calculations, suppression sweep, cascades per SCAFFOLD §3."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_RULE_WINDOW_OVERLAP,
    ERR_NO_PUBLISHED_CRITERIA,
    ERR_PORTABLE_REPORT_INVALID,
    ERR_PORTABLE_REPORT_NOT_ACCEPTED,
    ERR_PORTABLE_REPORT_EXPIRED,
)
from util import clock, touch

# Calculation constants (scaffold Table 3)
BASE_FEE_CENTS = 2500
SURCHARGE_RATE = Decimal("0.125")
PORTABLE_FLAT_FEE_CENTS = 1000
CRIMINAL_LOOKBACK_DEFAULT = 7
EVICTION_LOOKBACK_DEFAULT = 7
DISPUTE_WINDOW_DAYS = 30
REINVESTIGATION_SLA_DAYS = 30
PORTABLE_VALIDITY_DAYS = 30
IDENTITY_PASS_THRESHOLD = 70
MAX_IDENTITY_ATTEMPTS = 3


def round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Jurisdiction rules
# ---------------------------------------------------------------------------

def covering_rule(state_code, at):
    """Return the JurisdictionRule whose half-open window contains `at`, or None."""
    for rule in store.jurisdiction_rules.values():
        if rule["state_code"] != state_code:
            continue
        if rule["effective_from"] <= at and (rule["effective_to"] is None or at < rule["effective_to"]):
            return rule
    return None


def check_rule_window_overlap(state_code, effective_from, effective_to):
    """Half-open [effective_from, effective_to) windows per state must not overlap.

    Adjacency (one rule's effective_to == another's effective_from) is legal.
    """
    for rule in store.jurisdiction_rules.values():
        if rule["state_code"] != state_code:
            continue
        r_from = rule["effective_from"]
        r_to = rule["effective_to"]
        # Half-open overlap: a_from < b_to AND b_from < a_to (None end = +inf)
        a_to = effective_to
        b_to = r_to
        cond1 = True if b_to is None else effective_from < b_to
        cond2 = True if a_to is None else r_from < a_to
        if cond1 and cond2:
            raise ApiError(
                ERR_RULE_WINDOW_OVERLAP,
                "Half-open effective window overlaps another rule for the same state_code",
                409,
            )


# ---------------------------------------------------------------------------
# Criteria pinning
# ---------------------------------------------------------------------------

def covering_published_criteria(landlord_id, at):
    """PUBLISHED criteria of this landlord whose CLOSED window contains `at`.

    Closed window: effective_from <= at <= effective_to (None end = open-ended).
    Returns the list of matches (must be exactly one at submit).
    """
    matches = []
    for c in store.criteria.values():
        if c["landlord_id"] != landlord_id or c["status"] != "PUBLISHED":
            continue
        if c["effective_from"] <= at and (c["effective_to"] is None or at <= c["effective_to"]):
            matches.append(c)
    return matches


# ---------------------------------------------------------------------------
# Suppression sweep (record_suppression_sweep)
# ---------------------------------------------------------------------------

def _cutoff_date(at, years):
    """Calendar date of clock minus lookback years (handles Feb 29)."""
    d = at.date()
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap year
        return d.replace(year=d.year - years, day=28)


def suppression_sweep(records, state_code, at):
    """Classify each record INCLUDED/SUPPRESSED per the covering rule.

    STRICTLY-OLDER-THAN boundary: a record dated exactly on the cutoff stays INCLUDED.
    """
    rule = covering_rule(state_code, at)
    if rule is None:
        criminal_lookback = CRIMINAL_LOOKBACK_DEFAULT
        eviction_lookback = EVICTION_LOOKBACK_DEFAULT
    else:
        criminal_lookback = rule["criminal_lookback_years"]
        eviction_lookback = rule["eviction_lookback_years"]

    criminal_cutoff = _cutoff_date(at, criminal_lookback)
    eviction_cutoff = _cutoff_date(at, eviction_lookback)

    for rec in records:
        if rec["record_type"] == "CRIMINAL" and criminal_lookback == 0:
            rec["status"] = "SUPPRESSED"
            rec["suppression_reason"] = "SEARCH_PROHIBITED"
        else:
            cutoff = criminal_cutoff if rec["record_type"] == "CRIMINAL" else eviction_cutoff
            if rec["record_date"].date() < cutoff:
                rec["status"] = "SUPPRESSED"
                rec["suppression_reason"] = "LOOKBACK_EXPIRED"
            else:
                rec["status"] = "INCLUDED"
                rec["suppression_reason"] = None
        touch(rec)


def recompute_included_count(report):
    count = sum(
        1 for r in store.records.values()
        if r["report_id"] == report["id"] and r["status"] == "INCLUDED"
    )
    report["included_record_count"] = count


def report_records(report_id):
    """Records of a report in creation order (insertion order == input array order)."""
    return [r for r in store.records.values() if r["report_id"] == report_id]


# ---------------------------------------------------------------------------
# Screening fee (screening_fee)
# ---------------------------------------------------------------------------

def screening_fee(state_code, at):
    """Fee for a full bureau search. Pinned rounding order: round each surcharge
    component to integer cents FIRST, then sum, then cap (cap binds inclusively)."""
    rule = covering_rule(state_code, at)
    criminal_executed = True
    if rule is not None and rule["criminal_lookback_years"] == 0:
        criminal_executed = False

    surcharge = round_half_up_cents(SURCHARGE_RATE * BASE_FEE_CENTS)  # 313
    executed_types = 3 if criminal_executed else 2
    computed = BASE_FEE_CENTS + executed_types * surcharge

    if rule is not None and rule.get("max_screening_fee_cents") is not None:
        return min(rule["max_screening_fee_cents"], computed)
    return computed


# ---------------------------------------------------------------------------
# Rent-to-income ratio (rent_to_income_ratio)
# ---------------------------------------------------------------------------

def affordability(app, criteria, at):
    """Compute affordability_passes for an application at score time."""
    rule = covering_rule(app["unit_state_code"], at)
    applicable_rent = app["monthly_rent_cents"]
    soi_variant = (
        rule is not None
        and rule["source_of_income_protected"]
        and app.get("voucher_monthly_amount_cents", 0) > 0
        and criteria["accepts_voucher_income"]
    )
    if soi_variant:
        applicable_rent = app["monthly_rent_cents"] - app["voucher_monthly_amount_cents"]
        if applicable_rent <= 0:
            return True

    threshold = round_half_up_cents(
        Decimal(str(criteria["income_multiplier"])) * applicable_rent
    )
    verified = app.get("verified_income_cents")
    if verified is None:
        return False
    return verified >= threshold


# ---------------------------------------------------------------------------
# Recommendation decision table (screening_recommendation)
# ---------------------------------------------------------------------------

def compute_recommendation(app, criteria):
    """Decision table — evaluate in pinned order, first matching branch wins."""
    if app.get("credit_score") is not None and app["credit_score"] < criteria["min_credit_score"]:
        return "RECOMMEND_DENY"
    if (app.get("eviction_included_count") or 0) > 0:
        return "RECOMMEND_DENY"
    if (app.get("criminal_included_count") or 0) > 0:
        return "RECOMMEND_DENY"
    if app.get("affordability_passes") is True:
        return "RECOMMEND_APPROVE"
    has_approved_guarantor = any(
        g for g in store.guarantors.values()
        if g["application_id"] == app["id"] and g["status"] == "APPROVED"
    )
    if has_approved_guarantor:
        return "RECOMMEND_CONDITIONAL"
    return "RECOMMEND_DENY"


# ---------------------------------------------------------------------------
# Withdrawal / suspension cleanup (shared cascade)
# ---------------------------------------------------------------------------

def withdraw_cleanup(app, landlord):
    """Void DRAFT report and refund undelivered fee. Mutates in place."""
    report = application_report(app["id"])
    if report is not None and report["status"] == "DRAFT":
        report["status"] = "VOIDED"
        touch(report)
    if app.get("fee_charged_cents", 0) > 0:
        delivered = report is not None and report.get("delivered_at") is not None
        if not delivered:
            landlord["fee_balance_cents"] -= app["fee_charged_cents"]
            touch(landlord)


def application_report(application_id):
    """The application's report (at most one)."""
    for r in store.reports.values():
        if r["application_id"] == application_id:
            return r
    return None


def application_income_verification(application_id):
    for iv in store.income_verifications.values():
        if iv["application_id"] == application_id:
            return iv
    return None


# ---------------------------------------------------------------------------
# Portable submit helpers
# ---------------------------------------------------------------------------

def validate_portable(app, at):
    """Portable preconditions for submit (temporal gate then structural checks).

    Caller handles criteria pinning first. Raises on violation.
    """
    report = store.reports.get(app["portable_report_id"])
    if report is None:
        raise ApiError(ERR_NOT_FOUND, "Referenced portable_report_id does not exist", 404)
    return report


def check_portable_temporal(source_report, at):
    """clock <= last_delivered_at + PORTABLE_VALIDITY_DAYS (inclusive)."""
    last = source_report.get("last_delivered_at")
    if last is None:
        # An undelivered report has no validity window; treat as invalid rather
        # than expired — but PRD orders temporal before structural. A report
        # without last_delivered_at cannot be DELIVERED/RE_DELIVERED either;
        # the temporal comparison would be meaningless, so evaluate validity
        # structurally here by treating it as expired only when a timestamp
        # exists. Undelivered reports are caught by ERR_PORTABLE_REPORT_INVALID.
        return
    deadline = last + timedelta(days=PORTABLE_VALIDITY_DAYS)
    if at > deadline:
        raise ApiError(
            ERR_PORTABLE_REPORT_EXPIRED,
            "Portable report older than 30 days at submit",
            422,
        )


def check_portable_structural(app, source_report, criteria, at):
    """Same-applicant + DELIVERED/RE_DELIVERED, then acceptance."""
    source_app = store.applications.get(source_report["application_id"])
    same_applicant = source_app is not None and source_app["applicant_id"] == app["applicant_id"]
    if not same_applicant or source_report["status"] not in ("DELIVERED", "RE_DELIVERED"):
        raise ApiError(
            ERR_PORTABLE_REPORT_INVALID,
            "Portable report belongs to a different applicant or is not DELIVERED/RE_DELIVERED",
            422,
        )
    rule = covering_rule(app["unit_state_code"], at)
    mandated = rule is not None and rule["portable_report_acceptance_required"]
    if not mandated and not criteria["accepts_portable_reports"]:
        raise ApiError(
            ERR_PORTABLE_REPORT_NOT_ACCEPTED,
            "Neither the jurisdiction mandate nor the pinned criteria accepts portable reports",
            422,
        )
