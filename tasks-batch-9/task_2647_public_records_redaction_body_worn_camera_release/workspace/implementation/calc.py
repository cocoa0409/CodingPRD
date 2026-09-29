"""Constants, enumerations and every calculation rule of the specification."""
from decimal import Decimal, ROUND_HALF_UP

from db import add_days, store

# -- enumerations ---------------------------------------------------------
REQUESTER_TYPES = ("MEDIA", "INVOLVED_PARTY", "ATTORNEY", "GENERAL_PUBLIC", "COMMERCIAL")
STAFF_ROLE_TYPES = ("CLERK", "TECHNICIAN", "REVIEWER", "COUNSEL", "SUPERVISOR")
PROCESSING_STATUSES = ("INTAKE", "SCOPING", "EXEMPTION_REVIEW", "REDACTION",
                       "RELEASE_READY", "PARTIALLY_RELEASED", "RELEASED", "DENIED",
                       "CLOSED")
FEE_STATUSES = ("NOT_ASSESSED", "ESTIMATED", "DEPOSIT_DUE", "DEPOSIT_PAID",
                "INVOICED", "SETTLED", "WAIVED")
CLASSIFICATIONS = ("ROUTINE", "USE_OF_FORCE", "JUVENILE_CONTACT",
                   "OFFICER_INVOLVED_SHOOTING", "IN_CUSTODY_DEATH")
RETENTION_CATEGORIES = ("EVIDENTIARY_7Y", "INVESTIGATIVE_3Y", "NON_EVIDENTIARY_180D")
DISPOSITION_STATES = ("SCHEDULED", "SUSPENDED", "PURGED")
INCLUSION_STATUSES = ("CANDIDATE", "RESPONSIVE", "WITHHELD_IN_FULL", "RELEASED",
                      "EXCLUDED")
RELEASE_POSTURES = ("OPEN", "RESTRICTED", "BLOCKED")
EXEMPTION_CODES = ("ONGOING_INVESTIGATION", "PERSONAL_PRIVACY", "MEDICAL",
                   "VICTIM_PROTECTION", "JUVENILE", "CONFIDENTIAL_INFORMANT")
ASSERTED_SCOPES = ("FULL_WITHHOLD", "PARTIAL_REDACT")
CLAIM_SOURCES = ("STAFF_ANALYSIS", "DEPICTED_OBJECTION")
CLAIM_STATUSES = ("ASSERTED", "SUSTAINED", "OVERRULED", "WITHDRAWN")
DISPOSITIONS = ("SUSTAINED", "OVERRULED", "WITHDRAWN")
TARGET_TYPES = ("FACE", "LICENSE_PLATE", "AUDIO_IDENTIFIER", "PROTECTED_CONTENT")
TASK_STATUSES = ("DRAFT", "QA_PENDING", "QA_REJECTED", "APPROVED", "CANCELLED")
QA_OUTCOMES = ("PASS", "FAIL")
RELATIONSHIPS = ("VICTIM", "JUVENILE", "WITNESS", "OFFICER", "BYSTANDER", "SUSPECT")
NOTIFICATION_STATUSES = ("NOT_REQUIRED", "PENDING", "NOTIFIED", "OBJECTED",
                         "OBJECTION_SUSTAINED", "OBJECTION_OVERRULED", "WAIVED")
NOTICE_METHODS = ("FIRST_CLASS_MAIL", "EMAIL", "PERSONAL_SERVICE")
OBJECTION_BASES = ("PRIVACY", "VICTIM_STATUS", "JUVENILE_STATUS", "MEDICAL_STATUS")
ESTIMATE_BASES = ("PRESUMPTIVE", "ADJUDICATED")
MEDIA_TYPES = ("DIGITAL_DOWNLOAD", "DVD", "USB")
ESTIMATE_STATUSES = ("ACTIVE", "SUPERSEDED", "STALE")
ENTRY_TYPES = ("DEPOSIT_PAYMENT", "LABOR_CHARGE", "MEDIA_CHARGE", "WAIVER_CREDIT",
               "REVERSAL", "REFUND")
SOURCE_KINDS = ("DEPOSIT", "INVOICE", "ADJUSTMENT", "WAIVER")
HOLD_TYPES = ("LITIGATION", "SUBPOENA", "INTERNAL_AFFAIRS")
HOLD_STATUSES = ("ACTIVE", "RELEASED")
DENIAL_TYPES = ("FULL", "PARTIAL")
APPEAL_AUTHORITIES = ("SUPERIOR_COURT", "DISTRICT_ATTORNEY")
LETTER_STATUSES = ("ISSUED", "APPEALED", "UPHELD", "REVERSED")
DECISIONS = ("UPHELD", "REVERSED")
PACKAGE_KINDS = ("INTERIM", "FINAL")

# -- constants ------------------------------------------------------------
REVIEW_MULTIPLIER = {
    "ROUTINE": Decimal("1.0"),
    "USE_OF_FORCE": Decimal("2.0"),
    "JUVENILE_CONTACT": Decimal("2.5"),
    "OFFICER_INVOLVED_SHOOTING": Decimal("3.0"),
    "IN_CUSTODY_DEATH": Decimal("3.0"),
}
EXEMPTION_WEIGHT = {
    "ONGOING_INVESTIGATION": Decimal("0.30"),
    "PERSONAL_PRIVACY": Decimal("0.40"),
    "MEDICAL": Decimal("0.50"),
    "VICTIM_PROTECTION": Decimal("0.60"),
    "JUVENILE": Decimal("0.80"),
    "CONFIDENTIAL_INFORMANT": Decimal("0.90"),
}
FULL_WITHHOLD_WEIGHT = Decimal("1.00")
BASELINE_OBSCURATION_RATIO = Decimal("0.25")

STANDARD_RESPONSE_DAYS = 20
CRITICAL_INCIDENT_RELEASE_DAYS = 45
MAX_EXTENSION_DAYS = 10
DEPOSIT_DUE_DAYS = 30
APPEAL_WINDOW_DAYS = 30
OBJECTION_WINDOW_DAYS = 10
JUVENILE_OBJECTION_WINDOW_DAYS = 15

HOURLY_RATE_CENTS = 4200
FREE_ALLOWANCE_MINUTES = 60
DEPOSIT_THRESHOLD_CENTS = 3500
DEPOSIT_PCT = Decimal("0.50")
STATUTORY_COST_RECOVERY_CAP_CENTS = 50000
PUBLIC_INTEREST_TIER_T1_MAX_CENTS = 5000
PUBLIC_INTEREST_TIER_T2_MAX_CENTS = 25000
PUBLIC_INTEREST_TIER_T1_PCT = Decimal("0.00")
PUBLIC_INTEREST_TIER_T2_PCT = Decimal("0.10")
PUBLIC_INTEREST_TIER_T3_PCT = Decimal("0.20")

DIGITAL_DOWNLOAD_CENTS = 0
DVD_MINUTES_PER_DISC = 120
DVD_CENTS_PER_DISC = 500
USB_MINUTES_PER_UNIT = 240
USB_CENTS_PER_UNIT = 1500

TARGET_COMPLEXITY_FACTOR = {
    "FACE": Decimal("1.00"),
    "LICENSE_PLATE": Decimal("0.85"),
    "AUDIO_IDENTIFIER": Decimal("1.15"),
    "PROTECTED_CONTENT": Decimal("1.30"),
}

MIN_REVIEWER_LEVEL = 2
QA_BUFFER_MINUTES = 30
MAX_CONCURRENT_QA_PER_REVIEWER = 3
COMMERCIAL_OPEN_REQUEST_LIMIT = 3
MAX_SCOPE_CLARIFICATIONS = 2

CITATION_MAP = {
    "ONGOING_INVESTIGATION": "119.071(2)(c)",
    "PERSONAL_PRIVACY": "119.071(4)(d)",
    "JUVENILE": "985.04(1)",
    "VICTIM_PROTECTION": "119.071(2)(j)",
    "MEDICAL": "456.057(7)",
    "CONFIDENTIAL_INFORMANT": "119.071(2)(f)",
}
OBJECTION_BASIS_TO_CODE = {
    "PRIVACY": "PERSONAL_PRIVACY",
    "VICTIM_STATUS": "VICTIM_PROTECTION",
    "JUVENILE_STATUS": "JUVENILE",
    "MEDICAL_STATUS": "MEDICAL",
}

NOTIFICATION_REQUIRED_RELATIONSHIPS = ("VICTIM", "JUVENILE", "WITNESS")
OPEN_PROCESSING_EXCLUDED = ("RELEASED", "DENIED", "CLOSED")
LIVE_TASK_STATUSES = ("DRAFT", "QA_PENDING", "QA_REJECTED")
TERMINAL_TASK_STATUSES = ("APPROVED", "CANCELLED")


# -- rounding primitives --------------------------------------------------
def rhu(value):
    """Round half up, away from zero, to a whole unit."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    return -((-int(numerator)) // int(denominator))


def ceil_dec(value):
    value = Decimal(value)
    whole = int(value)
    if Decimal(whole) < value:
        whole += 1
    return whole


# -- collection helpers ---------------------------------------------------
def records_of_request(request_id):
    return [row for row in store.all("responsive_records")
            if row["request_id"] == request_id]


def claims_of_record(record_id):
    return [row for row in store.all("exemption_claims")
            if row["responsive_record_id"] == record_id]


def claims_of_request(request_id):
    ids = set(row["id"] for row in records_of_request(request_id))
    return [row for row in store.all("exemption_claims")
            if row["responsive_record_id"] in ids]


def tasks_of_record(record_id):
    return [row for row in store.all("redaction_tasks")
            if row["responsive_record_id"] == record_id]


def tasks_of_request(request_id):
    ids = set(row["id"] for row in records_of_request(request_id))
    return [row for row in store.all("redaction_tasks")
            if row["responsive_record_id"] in ids]


def individuals_of_asset(asset_id):
    return [row for row in store.all("depicted_individuals")
            if row["video_asset_id"] == asset_id]


def entries_of_request(request_id):
    return [row for row in store.all("fee_ledger_entries")
            if row["request_id"] == request_id]


def estimates_of_request(request_id):
    return [row for row in store.all("fee_estimates")
            if row["request_id"] == request_id]


def packages_of_request(request_id):
    return [row for row in store.all("release_packages")
            if row["request_id"] == request_id]


def letters_of_request(request_id):
    return [row for row in store.all("denial_letters")
            if row["request_id"] == request_id]


def asset_of_record(record):
    return store.get("video_assets", record["video_asset_id"])


def active_holds_for_incident(incident_number):
    return [row for row in store.all("litigation_holds")
            if row["status"] == "ACTIVE"
            and row["scope_incident_number"] == incident_number]


# -- record_review_minutes ------------------------------------------------
def asset_minutes(asset):
    """Whole minutes of footage: ceil(duration_ms / 60000)."""
    return ceil_div(asset["duration_ms"], 60000)


def record_review_minutes(asset):
    minutes = asset_minutes(asset)
    return ceil_dec(Decimal(minutes) * REVIEW_MULTIPLIER[asset["classification"]])


# -- claim_redaction_minutes ---------------------------------------------
def claim_redaction_minutes(asset, exemption_code, asserted_scope):
    minutes = asset_minutes(asset)
    weight = (FULL_WITHHOLD_WEIGHT if asserted_scope == "FULL_WITHHOLD"
              else EXEMPTION_WEIGHT[exemption_code])
    return ceil_dec(Decimal(minutes) * weight)


# -- record_redaction_burden ---------------------------------------------
def baseline_obscuration_minutes(asset):
    return ceil_dec(Decimal(asset_minutes(asset)) * BASELINE_OBSCURATION_RATIO)


def record_burdens(record):
    asset = asset_of_record(record)
    baseline = baseline_obscuration_minutes(asset) if asset else 0
    claims = claims_of_record(record["id"])
    presumptive = baseline + sum(claim["estimated_redaction_minutes"] for claim in claims
                                if claim["status"] in ("ASSERTED", "SUSTAINED"))
    adjudicated = baseline + sum(claim["estimated_redaction_minutes"] for claim in claims
                                 if claim["status"] == "SUSTAINED")
    return presumptive, adjudicated


# -- record_release_posture ----------------------------------------------
def record_release_posture(record):
    claims = claims_of_record(record["id"])
    # Pinned evaluation order: the FULL_WITHHOLD test runs first.
    for claim in claims:
        if claim["status"] == "SUSTAINED" and claim["asserted_scope"] == "FULL_WITHHOLD":
            return "BLOCKED"
    for claim in claims:
        if claim["status"] in ("ASSERTED", "SUSTAINED"):
            return "RESTRICTED"
    return "OPEN"


# -- certification_requirement -------------------------------------------
def certification_requirement(target_type, claim):
    base_level = 1 if target_type in ("FACE", "LICENSE_PLATE") else 2
    if claim is not None and claim.get("exemption_code") == "JUVENILE":
        required_level = 3
    else:
        required_level = base_level
    return required_level, max(required_level, MIN_REVIEWER_LEVEL)


# -- statutory_deadline ---------------------------------------------------
CRITICAL_SET_STATUSES = ("RESPONSIVE", "WITHHELD_IN_FULL", "RELEASED")


def request_is_critical_incident(request):
    for record in records_of_request(request["id"]):
        if record["inclusion_status"] not in CRITICAL_SET_STATUSES:
            continue
        asset = asset_of_record(record)
        if asset is not None and asset["is_critical_incident"]:
            return True
    return False


def statutory_deadline(request):
    from db import parse_dt
    received_at = parse_dt(request["received_at"])
    critical_starts = []
    for record in records_of_request(request["id"]):
        if record["inclusion_status"] not in CRITICAL_SET_STATUSES:
            continue
        asset = asset_of_record(record)
        if asset is not None and asset["is_critical_incident"]:
            started = parse_dt(asset["recorded_start_at"])
            if started is not None:
                critical_starts.append(started)
    if request["is_critical_incident"] and critical_starts:
        anchor = min(critical_starts)
    else:
        anchor = received_at
    base_days = (CRITICAL_INCIDENT_RELEASE_DAYS if request["is_critical_incident"]
                 else STANDARD_RESPONSE_DAYS)
    granted = min(request["extension_days_granted"], MAX_EXTENSION_DAYS)
    budget = base_days + granted + request["tolled_days"]
    floor_guard = add_days(received_at, STANDARD_RESPONSE_DAYS)
    candidate = add_days(anchor, budget)
    return max(candidate, floor_guard)


def tolled_days_for_payment(deposit_due_at, payment_clock):
    if deposit_due_at is None:
        return 0
    elapsed = (payment_clock - deposit_due_at).total_seconds()
    return max(0, int(elapsed // 86400))


# -- objection_deadline ---------------------------------------------------
def objection_deadline(individual, notified_at):
    window = (JUVENILE_OBJECTION_WINDOW_DAYS
              if individual["relationship"] == "JUVENILE" else OBJECTION_WINDOW_DAYS)
    return add_days(notified_at, window)


# -- media_production_cost -----------------------------------------------
def media_production_cost(records, media_type):
    total_ms = 0
    for record in records:
        asset = asset_of_record(record)
        if asset is not None:
            total_ms += asset["duration_ms"]
    produced_minutes = ceil_div(total_ms, 60000) if total_ms else 0
    if media_type == "DIGITAL_DOWNLOAD":
        disc_count = 0
        cost = DIGITAL_DOWNLOAD_CENTS
    elif media_type == "DVD":
        disc_count = ceil_div(produced_minutes, DVD_MINUTES_PER_DISC) if produced_minutes else 0
        cost = disc_count * DVD_CENTS_PER_DISC
    else:
        disc_count = ceil_div(produced_minutes, USB_MINUTES_PER_UNIT) if produced_minutes else 0
        cost = disc_count * USB_CENTS_PER_UNIT
    return produced_minutes, disc_count, cost


# -- public interest tier -------------------------------------------------
def public_interest_pct(subtotal_cents):
    if subtotal_cents <= PUBLIC_INTEREST_TIER_T1_MAX_CENTS:
        return PUBLIC_INTEREST_TIER_T1_PCT
    if subtotal_cents <= PUBLIC_INTEREST_TIER_T2_MAX_CENTS:
        return PUBLIC_INTEREST_TIER_T2_PCT
    return PUBLIC_INTEREST_TIER_T3_PCT


def labor_cents(minutes):
    return rhu(Decimal(int(minutes)) * Decimal(HOURLY_RATE_CENTS) / Decimal(60))


def task_labor_cents(task):
    factor = TARGET_COMPLEXITY_FACTOR[task["target_type"]]
    exact = (Decimal(int(task["approved_labor_minutes"])) * Decimal(HOURLY_RATE_CENTS)
             * factor / Decimal(60))
    return rhu(exact)


# -- fee_estimate_total ---------------------------------------------------
def fee_estimate_total(request, requester, basis, media_type):
    records = records_of_request(request["id"])
    labor_set = [r for r in records
                 if r["inclusion_status"] in ("RESPONSIVE", "WITHHELD_IN_FULL")]
    projected_review_minutes = sum(r["estimated_review_minutes"] for r in labor_set)
    if basis == "PRESUMPTIVE":
        projected_burden_minutes = sum(r["presumptive_burden_minutes"] for r in labor_set)
    else:
        projected_burden_minutes = sum(r["adjudicated_burden_minutes"] for r in labor_set)
    billable_minutes = max(0, projected_review_minutes + projected_burden_minutes
                           - FREE_ALLOWANCE_MINUTES)
    estimated_labor_cents = labor_cents(billable_minutes)
    media_set = [r for r in records if r["inclusion_status"] == "RESPONSIVE"]
    _, _, media_production_cents = media_production_cost(media_set, media_type)
    subtotal_cents = estimated_labor_cents + media_production_cents
    tier_pct = public_interest_pct(subtotal_cents)
    base_pct = Decimal(str(requester["fee_waiver_pct"]))
    effective_waiver_pct = min(Decimal("1.00"), base_pct + tier_pct)
    waiver_credit_cents = rhu(Decimal(subtotal_cents) * effective_waiver_pct)
    estimated_total_cents = min(subtotal_cents - waiver_credit_cents,
                                STATUTORY_COST_RECOVERY_CAP_CENTS)
    if estimated_total_cents > DEPOSIT_THRESHOLD_CENTS:
        deposit_required_cents = rhu(Decimal(estimated_total_cents) * DEPOSIT_PCT)
    else:
        deposit_required_cents = 0
    return {
        "projected_review_minutes": projected_review_minutes,
        "projected_burden_minutes": projected_burden_minutes,
        "billable_minutes": billable_minutes,
        "estimated_labor_cents": estimated_labor_cents,
        "media_production_cents": media_production_cents,
        "subtotal_cents": subtotal_cents,
        "effective_waiver_pct": effective_waiver_pct,
        "waiver_credit_cents": waiver_credit_cents,
        "estimated_total_cents": estimated_total_cents,
        "deposit_required_cents": deposit_required_cents,
    }


# -- fee_invoice_total ----------------------------------------------------
def fee_invoice_total(request, requester):
    approved = [task for task in tasks_of_request(request["id"])
                if task["status"] == "APPROVED"]
    labor = sum(task_labor_cents(task) for task in approved)
    released = [r for r in records_of_request(request["id"])
                if r["inclusion_status"] == "RELEASED"]
    review_minutes = max(0, sum(r["estimated_review_minutes"] for r in released)
                         - FREE_ALLOWANCE_MINUTES)
    review = labor_cents(review_minutes)
    media = sum(pkg["production_cost_cents"] for pkg in packages_of_request(request["id"]))
    subtotal_cents = labor + review + media
    tier_pct = public_interest_pct(subtotal_cents)
    base_pct = Decimal(str(requester["fee_waiver_pct"]))
    effective_waiver_pct = min(Decimal("1.00"), base_pct + tier_pct)
    waiver_credit_cents = rhu(Decimal(subtotal_cents) * effective_waiver_pct)
    invoiced_total_cents = min(subtotal_cents - waiver_credit_cents,
                               STATUTORY_COST_RECOVERY_CAP_CENTS)
    return {
        "labor_cents": labor,
        "review_cents": review,
        "media_cents": media,
        "subtotal_cents": subtotal_cents,
        "effective_waiver_pct": effective_waiver_pct,
        "waiver_credit_cents": waiver_credit_cents,
        "invoiced_total_cents": invoiced_total_cents,
    }


# -- ledger_conservation --------------------------------------------------
def _target_type_of(entry):
    if entry["entry_type"] != "REVERSAL":
        return entry["entry_type"]
    target = store.get("fee_ledger_entries", entry.get("reverses_entry_id"))
    return target["entry_type"] if target else None


def ledger_figures(request_id):
    entries = entries_of_request(request_id)
    deposit_balance = sum(entry["amount_cents"] for entry in entries)
    deposit_paid = 0
    recognized = 0
    waiver_total = 0
    for entry in entries:
        kind = _target_type_of(entry)
        if kind == "DEPOSIT_PAYMENT":
            deposit_paid += entry["amount_cents"]
        elif kind in ("LABOR_CHARGE", "MEDIA_CHARGE"):
            recognized += entry["amount_cents"]
        elif kind == "WAIVER_CREDIT":
            waiver_total += entry["amount_cents"]
    return {
        "deposit_balance_cents": deposit_balance,
        "deposit_paid_cents": deposit_paid,
        "fee_recognized_cents": abs(recognized),
        "waiver_credit_total_cents": waiver_total,
    }


# -- clip_overlap ---------------------------------------------------------
CLIP_LIVE_STATUSES = ("DRAFT", "QA_PENDING", "QA_REJECTED", "APPROVED")


def clip_overlaps(record_id, target_type, start_ms, end_ms):
    for task in tasks_of_record(record_id):
        if task["target_type"] != target_type:
            continue
        if task["status"] not in CLIP_LIVE_STATUSES:
            continue
        # half-open [start, end) with no buffer
        if start_ms < task["clip_end_ms"] and task["clip_start_ms"] < end_ms:
            return True
    return False


# -- qa_window_conflict ---------------------------------------------------
def qa_window_conflicts(reviewer_id, start_at, end_at, exclude_task_id=None):
    from datetime import timedelta
    buffer_delta = timedelta(minutes=QA_BUFFER_MINUTES)
    for task in store.all("redaction_tasks"):
        if task["id"] == exclude_task_id:
            continue
        if task["status"] != "QA_PENDING" or task["qa_reviewer_id"] != reviewer_id:
            continue
        from db import parse_dt
        existing_start = parse_dt(task["qa_window_start_at"])
        existing_end = parse_dt(task["qa_window_end_at"])
        if existing_start is None or existing_end is None:
            continue
        # closed endpoints, symmetric 30-minute buffer
        if (start_at - buffer_delta) <= existing_end and \
           (existing_start - buffer_delta) <= end_at:
            return True
    return False


def qa_pending_count(reviewer_id, exclude_task_id=None):
    total = 0
    for task in store.all("redaction_tasks"):
        if task["id"] == exclude_task_id:
            continue
        if task["status"] == "QA_PENDING" and task["qa_reviewer_id"] == reviewer_id:
            total += 1
    return total


# -- notification posture -------------------------------------------------
ALLOWED_NOTIFICATION_STATUSES = ("WAIVED", "NOT_REQUIRED", "OBJECTION_OVERRULED")


def notification_satisfied(individual, clock):
    """Condition 6 of release_eligible_set for one depicted individual."""
    if not individual["notification_required"]:
        return True
    status = individual["notification_status"]
    if status in ALLOWED_NOTIFICATION_STATUSES:
        return True
    if status == "NOTIFIED":
        from db import parse_dt
        deadline = parse_dt(individual["objection_deadline_at"])
        return deadline is not None and clock >= deadline
    return False


def notification_blocks(individual, clock):
    """The narrower set that raises ERR_OBJECTION_UNRESOLVED (PRD 3.9)."""
    if not individual["notification_required"]:
        return False
    status = individual["notification_status"]
    if status == "OBJECTED":
        return True
    if status == "NOTIFIED":
        from db import parse_dt
        deadline = parse_dt(individual["objection_deadline_at"])
        return deadline is None or clock < deadline
    return False


def open_notification_count(request_id):
    total = 0
    for record in records_of_request(request_id):
        if record["inclusion_status"] != "RESPONSIVE":
            continue
        for individual in individuals_of_asset(record["video_asset_id"]):
            if individual["notification_status"] in ("PENDING", "NOTIFIED", "OBJECTED"):
                total += 1
    return total


# -- release_eligible_set -------------------------------------------------
def record_is_releasable(record, clock):
    if record["inclusion_status"] != "RESPONSIVE":
        return False
    if record["release_posture"] == "BLOCKED":
        return False
    if record["unadjudicated_claim_count"] != 0:
        return False
    tasks = tasks_of_record(record["id"])
    if not tasks:
        return False
    if any(task["status"] not in TERMINAL_TASK_STATUSES for task in tasks):
        return False
    if not any(task["status"] == "APPROVED" for task in tasks):
        return False
    asset = asset_of_record(record)
    if asset is None or asset["disposition_state"] == "PURGED":
        return False
    for individual in individuals_of_asset(record["video_asset_id"]):
        if not notification_satisfied(individual, clock):
            return False
    if active_holds_for_incident(asset["incident_number"]):
        return False
    return True


def release_eligible_set(request_id, clock):
    records = [r for r in records_of_request(request_id)
               if record_is_releasable(r, clock)]
    return sorted(records, key=lambda row: row["_seq"])
