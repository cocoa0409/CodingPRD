"""Enums, constants, existence resolution and every computed-at-read field."""
from datetime import timedelta

import store
from errors import fail

# --------------------------------------------------------------- enum members
PERSON_TYPES = {"SALESPERSON", "BROKER"}
LICENSE_STATUSES = {"APPLICANT", "EXAM_PASSED", "ACTIVE", "INACTIVE", "SUSPENDED",
                    "EXPIRED", "REVOKED", "DENIED"}
DISCIPLINE_STATUSES = {"NONE", "UNDER_INVESTIGATION", "PENDING_HEARING",
                       "SANCTIONED", "CLEARED"}
BROKERAGE_STATUSES = {"PENDING", "ACTIVE", "SUSPENDED", "CLOSED"}
POSTURES = {"COMPLIANT", "WATCH", "RESTRICTED", "FROZEN"}
ACCOUNT_TYPES = {"ESCROW", "SECURITY_DEPOSIT"}
ACCOUNT_STATUSES = {"OPEN", "RESTRICTED", "CLOSED"}
ENTRY_TYPES = {"DEPOSIT", "DISBURSEMENT", "OBLIGATION_OPENED",
               "OBLIGATION_RELEASED", "CORRECTION"}
BASES = {"BOOK", "BANK"}
AUDIT_STATUSES = {"SCHEDULED", "FIELDWORK", "FINDINGS_ISSUED", "REMEDIATION_ORDERED",
                  "VERIFYING", "ESCALATED", "CLOSED"}
ALLEGATION_TYPES = {"MISREPRESENTATION", "AGENCY_DISCLOSURE", "COMMISSION_DISPUTE",
                    "TRUST_SHORTAGE", "ADVERTISING", "UNLICENSED_ACTIVITY"}
COMPLAINT_STATUSES = {"SUBMITTED", "INVESTIGATION", "AMENDMENT_REQUESTED",
                      "PROBABLE_CAUSE", "CONSENT_PENDING", "HEARING_SCHEDULED",
                      "ADJUDICATED", "DISMISSED", "CLOSED_NO_ACTION"}
OPEN_COMPLAINT_STATUSES = {"SUBMITTED", "INVESTIGATION", "AMENDMENT_REQUESTED",
                           "PROBABLE_CAUSE", "CONSENT_PENDING", "HEARING_SCHEDULED"}
SANCTION_TYPES = {"REPRIMAND", "FINE", "PROBATION", "SUSPENSION", "REVOCATION"}
CONSENT_STATUSES = {"OFFERED", "COUNTERED", "ACCEPTED", "REJECTED", "EXECUTED"}
HEARING_STATUSES = {"SCHEDULED", "CONVENED", "CONTINUED", "DECIDED"}
FINDINGS = {"VIOLATION_FOUND", "NO_VIOLATION"}
ORDER_STATUSES = {"ISSUED", "SATISFIED", "IN_DEFAULT", "VACATED"}
LIVE_ORDER_STATUSES = {"ISSUED", "IN_DEFAULT", "SATISFIED"}
CLAIM_STATUSES = {"FILED", "ELIGIBLE", "DENIED", "PARTIALLY_PAID", "PAID", "CLAWED_BACK"}
DENIAL_REASONS = {"WINDOW_CLOSED", "ORDER_NOT_DISCIPLINARY", "ORDER_VACATED"}
PROVIDER_STATUSES = {"PENDING", "APPROVED", "PROBATION", "SUSPENDED"}
CREDENTIAL_TYPES = {"ATTORNEY", "LICENSED_BROKER", "SUBJECT_EXPERT"}
INSTRUCTOR_STATUSES = {"PENDING", "APPROVED", "SUSPENDED"}
SUSPENDED_REASONS = {"LICENSE_REVOKED", "LICENSE_SUSPENDED"}
COURSE_TYPES = {"PRELICENSE", "POST_LICENSE", "CE_CORE", "CE_ELECTIVE"}
CREDIT_STATUSES = {"VALID", "INVALIDATED"}
AD_KINDS = {"TEAM", "DBA", "BRANCH"}
AD_STATUSES = {"SUBMITTED", "APPROVED", "REJECTED", "REVOKED"}
REJECTION_REASONS = {"PROHIBITED_TERM", "NAME_TAKEN", "TEAM_LEAD_INELIGIBLE",
                     "POSTURE_RESTRICTED", "IMPLIES_BROKERAGE"}

# ----------------------------------------------------------------- constants
CE_BASE_HOURS = 12
CE_INCREMENT_HOURS = 3
CE_HOUR_CAP = 36
INACTIVE_MONTH_DAYS = 30
BASE_REINSTATEMENT_FEE_CENTS = 15000
HOURLY_MAKEUP_FEE_CENTS = 2500
LATE_MONTHLY_RATE = "0.0175"
LATE_PERIOD_DAYS = 30
LATE_PERIOD_CAP = 24
SUPERVISION_RATIO_MAX = 25
PRELICENSE_HOURS_SALESPERSON = 90
PRELICENSE_HOURS_BROKER = 180
EXAM_PASS_SCORE = 75
EXAM_MAX_ATTEMPTS = 3
LICENSE_TERM_DAYS = 730
SHORTAGE_RESTRICT_THRESHOLD_CENTS = 100000
WATCH_COMPLAINT_THRESHOLD = 3
STATUTE_DAYS = 180
FINE_DUE_DAYS = 30
DEFAULT_SUSPENSION_DAYS = 90
CLAIM_WINDOW_DAYS = 365
PER_CLAIM_CAP_CENTS = 2000000
PER_LICENSEE_CAP_CENTS = 5000000
FUND_RESERVE_FLOOR_CENTS = 500000
ASSESSMENT_RATE = "0.02"
PROBABLE_CAUSE_MIN_SCORE = 40
MAX_AMENDMENTS = 2
MAX_CONSENT_ROUNDS = 3
MAX_CONTINUANCES = 2
AUDITOR_WINDOW_CAPACITY = 2
ACTIVE_AUDIT_STATUSES = {"SCHEDULED", "FIELDWORK", "FINDINGS_ISSUED",
                         "REMEDIATION_ORDERED", "VERIFYING"}
LIVE_HEARING_STATUSES = {"SCHEDULED", "CONVENED", "CONTINUED"}
HEARING_ROOM_BUFFER_SECONDS = 30 * 60
DEFAULT_REMEDIATION_DAYS = 3
PROVIDER_SUSPEND_HOURS = 60
DEFAULT_APPROVAL_YEARS = 2
BOOK_SENTINEL = "9999-12-31"
ALLEGATION_WEIGHT = {"MISREPRESENTATION": 40, "AGENCY_DISCLOSURE": 35,
                     "COMMISSION_DISPUTE": 20, "TRUST_SHORTAGE": 50,
                     "ADVERTISING": 15, "UNLICENSED_ACTIVITY": 60}
PROHIBITED_TERMS = ["REALTOR", "MLS", "COMMISSION", "STATEOF", "GUARANTEED", "OFFICIAL"]
TEAM_FORBIDDEN_WORDS = ["REALTY", "REALESTATE", "BROKERAGE", "COMPANY", "AGENCY"]

NOT_FOUND = {
    "licensee": "ERR_LICENSEE_NOT_FOUND",
    "brokerage": "ERR_BROKERAGE_NOT_FOUND",
    "trust_account": "ERR_TRUST_ACCOUNT_NOT_FOUND",
    "trust_audit": "ERR_TRUST_AUDIT_NOT_FOUND",
    "complaint": "ERR_COMPLAINT_NOT_FOUND",
    "consent_agreement": "ERR_CONSENT_AGREEMENT_NOT_FOUND",
    "hearing": "ERR_HEARING_NOT_FOUND",
    "sanction_order": "ERR_SANCTION_ORDER_NOT_FOUND",
    "education_provider": "ERR_EDUCATION_PROVIDER_NOT_FOUND",
    "instructor": "ERR_INSTRUCTOR_NOT_FOUND",
    "course_completion": "ERR_COURSE_COMPLETION_NOT_FOUND",
    "advertising_name": "ERR_ADVERTISING_NAME_NOT_FOUND",
    "recovery_claim": "ERR_SANCTION_ORDER_NOT_FOUND",
}


def must(kind, row_id):
    row = store.get(kind, row_id)
    if row is None:
        fail(NOT_FOUND[kind], "%s '%s' was not found." % (kind, row_id))
    return row


def rows_where(kind, **filters):
    out = []
    for row in store.all_rows(kind):
        keep = True
        for key, value in filters.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


# ------------------------------------------------------------ ledger / shortage
def shortage_figures(account_id, basis="BOOK", as_of=None, cleared_through=None):
    """Two-basis reconciliation (calculations.trust_account_shortage)."""
    as_of_text = as_of if as_of is not None else BOOK_SENTINEL
    obligation = 0
    available = 0
    for entry in rows_where("ledger_entry", trust_account_id=account_id):
        etype = entry["entry_type"]
        amount = entry["amount_cents"]
        if etype in ("OBLIGATION_OPENED", "OBLIGATION_RELEASED"):
            if entry["effective_date"] <= as_of_text:
                obligation += amount if etype == "OBLIGATION_OPENED" else -amount
            continue
        if basis == "BANK":
            cleared = entry.get("cleared_date")
            if cleared is None:
                continue
            limit = as_of_text
            if cleared_through is not None and cleared_through < limit:
                limit = cleared_through
            if cleared > limit:
                continue
        else:
            if entry["effective_date"] > as_of_text:
                continue
        if etype == "DEPOSIT":
            available += amount
        elif etype == "DISBURSEMENT":
            available -= amount
        elif etype == "CORRECTION":
            available += amount
    return obligation, available, max(0, obligation - available)


def account_triple(account):
    return shortage_figures(account["id"], "BOOK", None, None)


def audit_shortage(audit):
    account_id = audit["trust_account_id"]
    if audit["basis"] == "BANK":
        return shortage_figures(account_id, "BANK", audit["as_of_date"],
                                audit.get("cleared_through_date"))[2]
    return shortage_figures(account_id, "BOOK", audit["as_of_date"], None)[2]


# ------------------------------------------------------------------ brokerage
def affiliated_licensee_count(brokerage_id):
    return len([r for r in store.all_rows("licensee")
                if r.get("sponsoring_brokerage_id") == brokerage_id
                and r.get("license_status") == "ACTIVE"])


def open_shortage_cents(brokerage_id):
    total = 0
    for account in rows_where("trust_account", brokerage_id=brokerage_id):
        if account["status"] in ("OPEN", "RESTRICTED"):
            total += account_triple(account)[2]
    return total


def open_complaint_count(brokerage_id):
    return len([c for c in store.all_rows("complaint")
                if c.get("respondent_brokerage_id") == brokerage_id
                and c.get("status") in OPEN_COMPLAINT_STATUSES])


def overdue_remediation_count(brokerage_id):
    moment = store.now()
    count = 0
    account_ids = {a["id"] for a in rows_where("trust_account", brokerage_id=brokerage_id)}
    for audit in store.all_rows("trust_audit"):
        if audit["trust_account_id"] not in account_ids:
            continue
        if audit["status"] != "REMEDIATION_ORDERED":
            continue
        due = audit.get("remediation_due_at")
        if due is not None and store.dt_of(due) < moment:
            count += 1
    return count


def supervision_posture(brokerage):
    if brokerage is None:
        return None
    designated = store.get("licensee", brokerage.get("designated_broker_id"))
    d_license = designated.get("license_status") if designated else None
    d_discipline = designated.get("discipline_status") if designated else None
    shortage = open_shortage_cents(brokerage["id"])
    if (overdue_remediation_count(brokerage["id"]) >= 1
            or d_license in ("SUSPENDED", "REVOKED", "EXPIRED")
            or brokerage["status"] == "SUSPENDED"):
        return "FROZEN"
    if (shortage >= SHORTAGE_RESTRICT_THRESHOLD_CENTS
            or d_discipline in ("UNDER_INVESTIGATION", "PENDING_HEARING", "SANCTIONED")
            or d_license == "INACTIVE"):
        return "RESTRICTED"
    if shortage > 0 or open_complaint_count(brokerage["id"]) >= WATCH_COMPLAINT_THRESHOLD:
        return "WATCH"
    return "COMPLIANT"


def posture_of(brokerage_id):
    return supervision_posture(store.get("brokerage", brokerage_id))


# ------------------------------------------------------------------- licensee
def ce_hours_valid(licensee):
    start = licensee.get("ce_period_start_on")
    if start is None:
        return 0
    total = 0
    for row in rows_where("course_completion", licensee_id=licensee["id"]):
        if row["credit_status"] != "VALID":
            continue
        if row["course_type"] not in ("CE_CORE", "CE_ELECTIVE"):
            continue
        if row["completed_on"] >= start:
            total += row["credit_hours"]
    return total


def inactive_full_months(licensee):
    since = licensee.get("inactive_since")
    if since is None:
        return 0
    elapsed = (store.now() - store.dt_of(since)).total_seconds()
    if elapsed < 0:
        return 0
    return int(elapsed // (INACTIVE_MONTH_DAYS * 86400))


def ce_hours_required(licensee):
    status = licensee.get("license_status")
    if status in ("INACTIVE", "EXPIRED") and licensee.get("inactive_since") is not None:
        months = inactive_full_months(licensee)
        return min(CE_HOUR_CAP, CE_BASE_HOURS + CE_INCREMENT_HOURS * (months // 6))
    return CE_BASE_HOURS


def ce_deficient(licensee):
    return ce_hours_valid(licensee) < ce_hours_required(licensee)


def reinstatement_fee_cents(licensee):
    late_periods = 0
    since = licensee.get("inactive_since")
    if since is not None:
        elapsed = (store.now() - store.dt_of(since)).total_seconds()
        if elapsed > 0:
            late_periods = int(elapsed // (LATE_PERIOD_DAYS * 86400))
    late_periods = min(LATE_PERIOD_CAP, late_periods)
    per_period = store.round_half_up(
        (store.Decimal(BASE_REINSTATEMENT_FEE_CENTS) * store.Decimal(LATE_MONTHLY_RATE)))
    excess = ce_hours_required(licensee) - CE_BASE_HOURS
    return (BASE_REINSTATEMENT_FEE_CENTS + HOURLY_MAKEUP_FEE_CENTS * excess
            + per_period * late_periods)


def prior_sanction_count(licensee_id):
    return len([o for o in store.all_rows("sanction_order")
                if o["respondent_licensee_id"] == licensee_id
                and o["status"] in LIVE_ORDER_STATUSES])


def recovery_paid_cents(licensee_id):
    order_ids = {o["id"] for o in store.all_rows("sanction_order")
                 if o["respondent_licensee_id"] == licensee_id
                 and o["status"] != "VACATED"}
    total = 0
    for claim in store.all_rows("recovery_claim"):
        if claim["sanction_order_id"] in order_ids and claim["status"] in ("PARTIALLY_PAID", "PAID"):
            total += claim["awarded_cents"]
    return total


# ------------------------------------------------------------------ complaint
def priority_score(complaint):
    base = ALLEGATION_WEIGHT.get(complaint["allegation_type"], 0)
    harm = min(30, complaint["alleged_loss_cents"] // 100000)
    if complaint["status"] == "SUBMITTED":
        return min(100, base + harm)
    prior = min(20, 5 * prior_sanction_count(complaint["respondent_licensee_id"]))
    posture = posture_of(complaint.get("respondent_brokerage_id"))
    if posture in ("RESTRICTED", "FROZEN"):
        bump = 15
    elif posture == "WATCH":
        bump = 5
    else:
        bump = 0
    return min(100, base + harm + prior + bump)


# ---------------------------------------------------------------- advertising
def normalize_name(text):
    return "".join(ch for ch in text.upper() if ch.isascii() and ch.isalnum())


def prohibited_term_hits(normalized):
    return len([t for t in PROHIBITED_TERMS if t in normalized])


def team_word_hits(normalized):
    return len([w for w in TEAM_FORBIDDEN_WORDS if w in normalized])


def name_taken(normalized, exclude_id=None):
    for row in store.all_rows("advertising_name"):
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row["normalized_name"] == normalized and row["status"] in ("SUBMITTED", "APPROVED"):
            return True
    return False


# ------------------------------------------------------------------ providers
def suspended_instructor_count(provider_id):
    return len([i for i in rows_where("instructor", education_provider_id=provider_id)
                if i["status"] == "SUSPENDED"])


def invalidated_credit_hours(provider_id):
    total = 0
    for row in rows_where("course_completion", education_provider_id=provider_id):
        if row["credit_status"] == "INVALIDATED":
            total += row["credit_hours"]
    return total
