"""Domain vocabulary, collection helpers, and the nine calculations of PRD 3."""

from datetime import timedelta
from decimal import Decimal

from db import dec, round2, round4, sorted_by_created, store

# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------

CONTROL_KEYS = ("MFA_PRIVILEGED", "OFFLINE_BACKUPS", "EDR_COVERAGE",
                "EMAIL_FILTERING", "INCIDENT_RESPONSE_PLAN")
LEVELS = ("NONE", "PARTIAL", "FULL")
LEVEL_ORDER = {"NONE": 0, "PARTIAL": 1, "FULL": 2}
LEVEL_FACTOR = {"NONE": Decimal("0.0"), "PARTIAL": Decimal("0.5"), "FULL": Decimal("1.0")}

INDUSTRY_CODES = ("HEALTHCARE", "FINANCIAL", "RETAIL", "MANUFACTURING",
                  "PUBLIC_SECTOR", "TECHNOLOGY")
DEPENDENCY_KEYS = ("CSP_ALPHA", "CSP_BETA", "MSSP_DELTA", "NONE")
NAMED_DEPENDENCY_KEYS = ("CSP_ALPHA", "CSP_BETA", "MSSP_DELTA")
DEPENDENT_BI_DEFINITIONS = ("NAMED_ONLY", "NAMED_PLUS_SUPPLY_CHAIN", "BROAD_SYSTEM_FAILURE")

APPLICATION_STATES = ("DRAFT", "SUBMITTED", "UNDERWRITING", "REMEDIATION_REQUIRED",
                      "QUOTED", "BOUND", "DECLINED", "EXPIRED")
SCAN_STATES = ("PENDING", "COMPLETED", "FAILED")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

SECTION_KEYS = ("FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION", "DEPENDENT_BI",
                "THIRD_PARTY_LIABILITY", "CYBER_EXTORTION")
INTERRUPTION_SECTION_KEYS = ("BUSINESS_INTERRUPTION", "DEPENDENT_BI")
BASELINE_METHODS = ("TRAILING_12M", "SAME_PERIOD_PRIOR_YEAR")
LIFECYCLE_STATES = ("INFORCE", "CANCELLED", "EXPIRED", "NON_RENEWED")
LIMIT_STATES = ("INTACT", "PARTIALLY_ERODED", "EXHAUSTED")
WARRANTY_STATES = ("COMPLIANT", "LAPSED")

VENDOR_TYPES = ("FORENSICS", "LEGAL_COUNSEL", "NOTIFICATION", "PR_CRISIS", "RANSOM_NEGOTIATION")
VENDOR_STATES = ("ACTIVE", "SUSPENDED", "RETIRED")
SELECTION_MODES = ("DIRECTED", "PANEL_SELECTED")

INCIDENT_TYPES = ("RANSOMWARE", "SYSTEM_FAILURE", "DEPENDENT_OUTAGE", "BEC", "DATA_THEFT")
OUTAGE_REQUIRED_TYPES = ("RANSOMWARE", "SYSTEM_FAILURE", "DEPENDENT_OUTAGE")
CLAIM_STATES = ("NOTIFIED", "TRIAGE", "COVERAGE_CONFIRMED", "RESPONSE_ACTIVE", "PROOF_REVIEW",
                "INFO_REQUESTED", "APPROVED_FOR_PAYMENT", "SETTLED", "DENIED",
                "CLOSED_NO_COVERAGE")
ENGAGEMENT_STATES = ("AUTHORIZED", "ACTIVE", "COMPLETED", "TERMINATED")
LIVE_ENGAGEMENT_STATES = ("AUTHORIZED", "ACTIVE")
PROOF_STATES = ("UNDER_REVIEW", "INFO_REQUESTED", "ACCEPTED", "SUPERSEDED")
PAYMENT_STATES = ("POSTED", "REVERSED")
LOSS_SOURCES = ("PROOF_OF_LOSS", "VENDOR_ENGAGEMENT")
ASSESSMENT_STATES = ("CONDITIONS_ISSUED", "REMEDIATION_SUBMITTED", "CONDITIONS_MET",
                     "RENEWAL_QUOTED", "NON_RENEWED")
SCENARIO_STATES = ("DRAFT", "MODELED")

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

MIN_AGGREGATE_LIMIT_USD = Decimal("250000")
LIMIT_INCREMENT_USD = Decimal("250000")
MIN_SCORE_FOR_COVERAGE = Decimal("70")
QUOTE_VALID_DAYS = 30
NOTIFICATION_DEADLINE_DAYS = 30
RENEWAL_WINDOW_DAYS = 90
MAX_PROOF_REVIEW_ROUNDS = 2
MAX_VERIFICATION_ROUNDS = 2
PREMIUM_FLOOR_USD = Decimal("7500.00")
HOURS_PER_YEAR = Decimal("8760")
EXTRA_EXPENSE_CAP_PCT = Decimal("0.25")
CHANGEOVER_BUFFER_HOURS = 24
MODELED_MARGIN_PCT = Decimal("0.60")
CONTROL_CREDIT_PER_KEY = Decimal("750")
CONTROL_CREDIT_CAP_PCT = Decimal("0.12")
AGGREGATION_LOAD_PCT = Decimal("0.10")

BASE_RATE_PER_MILLION = {
    "HEALTHCARE": Decimal("9000"),
    "FINANCIAL": Decimal("8000"),
    "RETAIL": Decimal("7000"),
    "MANUFACTURING": Decimal("6000"),
    "PUBLIC_SECTOR": Decimal("7500"),
    "TECHNOLOGY": Decimal("5500"),
}

SECTIONS_FOR_VENDOR_TYPE = {
    "FORENSICS": ("FIRST_PARTY_RESPONSE",),
    "NOTIFICATION": ("FIRST_PARTY_RESPONSE",),
    "PR_CRISIS": ("FIRST_PARTY_RESPONSE",),
    "LEGAL_COUNSEL": ("FIRST_PARTY_RESPONSE", "THIRD_PARTY_LIABILITY"),
    "RANSOM_NEGOTIATION": ("CYBER_EXTORTION",),
}

SECTION_FOR_INCIDENT_TYPE = {
    "RANSOMWARE": "BUSINESS_INTERRUPTION",
    "SYSTEM_FAILURE": "BUSINESS_INTERRUPTION",
    "DEPENDENT_OUTAGE": "DEPENDENT_BI",
    "BEC": None,
    "DATA_THEFT": None,
}

CLOSED_CLAIM_STATES = ("SETTLED", "DENIED", "CLOSED_NO_COVERAGE")


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------

def catalog_rows():
    return list(store.control_requirements.values())


def catalog_ordered():
    return sorted(catalog_rows(), key=lambda row: (-row["weight"], row["control_key"]))


def catalog_by_key():
    return dict((row["control_key"], row) for row in store.control_requirements.values())


def mandatory_catalog_keys():
    return sorted(row["control_key"] for row in store.control_requirements.values()
                  if row["is_mandatory"])


def attestations_of(application_id):
    return [row for row in store.control_attestations.values()
            if row["application_id"] == application_id]


def scans_of(application_id):
    return [row for row in store.external_scans.values()
            if row["application_id"] == application_id]


def sections_of(policy_id):
    return [row for row in store.coverage_sections.values() if row["policy_id"] == policy_id]


def section_by_key(policy_id, section_key):
    for row in sections_of(policy_id):
        if row["section_key"] == section_key:
            return row
    return None


def claims_of(policy_id):
    return [row for row in store.incident_claims.values() if row["policy_id"] == policy_id]


def engagements_of_claim(claim_id):
    return [row for row in store.vendor_engagements.values()
            if row["incident_claim_id"] == claim_id]


def engagements_of_vendor(vendor_id):
    return [row for row in store.vendor_engagements.values()
            if row["panel_vendor_id"] == vendor_id]


def proofs_of_claim(claim_id):
    return [row for row in store.proofs_of_loss.values()
            if row["incident_claim_id"] == claim_id]


def payments_of_claim(claim_id):
    return [row for row in store.claim_payments.values()
            if row["incident_claim_id"] == claim_id]


def assessments_of_policy(policy_id):
    return [row for row in store.renewal_assessments.values() if row["policy_id"] == policy_id]


def policies_of_account(account_id):
    return [row for row in store.policies.values() if row["insured_account_id"] == account_id]


def latest_scan(application_id):
    """Latest scan attempt by created_at DESC -- the newest attempt governs."""
    rows = scans_of(application_id)
    if not rows:
        return None
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))[-1]


def latest_completed_scan(application_id):
    rows = [row for row in scans_of(application_id) if row["status"] == "COMPLETED"]
    if not rows:
        return None
    rows.sort(key=lambda row: (row["completed_at"], row["created_at"], row["_seq"]))
    return rows[-1]


# --------------------------------------------------------------------------
# 1. control_posture_score
# --------------------------------------------------------------------------

def _observed_levels(scan):
    observed = {}
    for finding in (scan.get("findings") or []):
        key = finding["control_key"]
        level = finding["observed_level"]
        current = observed.get(key)
        if current is None or LEVEL_ORDER[level] < LEVEL_ORDER[current]:
            observed[key] = level
    return observed


def effective_levels(application, basis):
    attestations = dict((row["control_key"], row) for row in attestations_of(application["id"]))
    observed = {}
    if basis == "verified":
        scan = latest_completed_scan(application["id"])
        if scan is not None:
            observed = _observed_levels(scan)
    levels = {}
    for requirement in catalog_rows():
        key = requirement["control_key"]
        attestation = attestations.get(key)
        level = attestation["attested_level"] if attestation else "NONE"
        if basis == "verified":
            seen = observed.get(key, "FULL")
            if LEVEL_ORDER[seen] < LEVEL_ORDER[level]:
                level = seen
        levels[key] = level
    return levels


def control_posture_score(application, basis):
    """Returns (score, mandatory_gap_control_keys) for 'attested' or 'verified' basis."""
    levels = effective_levels(application, basis)
    numerator = Decimal("0")
    denominator = Decimal("0")
    gaps = []
    for requirement in catalog_rows():
        weight = dec(requirement["weight"])
        level = levels[requirement["control_key"]]
        numerator += weight * LEVEL_FACTOR[level]
        denominator += weight
        if requirement["is_mandatory"]:
            if LEVEL_FACTOR[level] < LEVEL_FACTOR[requirement["min_level_required"]]:
                gaps.append(requirement)
    if denominator == 0:
        score = round2(0)
    else:
        score = round2(Decimal("100") * numerator / denominator)
    gaps.sort(key=lambda row: (-row["weight"], row["control_key"]))
    return score, [row["control_key"] for row in gaps]


# --------------------------------------------------------------------------
# 2. premium_quote
# --------------------------------------------------------------------------

def _revenue_tier_factor(annual_revenue_usd):
    revenue = dec(annual_revenue_usd)
    if revenue <= Decimal("50000000"):
        return Decimal("1.00")
    if revenue <= Decimal("250000000"):
        return Decimal("1.15")
    return Decimal("1.35")


def _control_adjustment(score):
    value = dec(score)
    if value >= Decimal("90"):
        return Decimal("-0.15")
    if value >= Decimal("75"):
        return Decimal("-0.05")
    if value >= Decimal("70"):
        return Decimal("0.10")
    return Decimal("0.30")


def _retention_adjustment(retention_usd):
    retention = dec(retention_usd)
    if retention >= Decimal("250000"):
        return Decimal("-0.10")
    if retention >= Decimal("100000"):
        return Decimal("-0.05")
    return Decimal("0.00")


def premium_quote(account, application, score):
    base_rate = BASE_RATE_PER_MILLION[account["industry_code"]]
    revenue_factor = _revenue_tier_factor(account["annual_revenue_usd"])
    millions = dec(application["requested_aggregate_limit_usd"]) / Decimal("1000000")
    layer_units = (min(millions, Decimal("1")) * Decimal("1.00")
                   + max(Decimal("0"), min(millions, Decimal("5")) - Decimal("1")) * Decimal("0.60")
                   + max(Decimal("0"), millions - Decimal("5")) * Decimal("0.35"))
    gross = round2(base_rate * revenue_factor * layer_units)
    multiplier = (Decimal("1")
                  + _control_adjustment(score if score is not None else Decimal("0"))
                  + _retention_adjustment(application["requested_retention_usd"])
                  + (Decimal("0.08") if account["primary_dependency_key"] != "NONE" else Decimal("0.00")))
    premium = round2(gross * multiplier)
    if premium < PREMIUM_FLOOR_USD:
        premium = PREMIUM_FLOOR_USD
    return premium


# --------------------------------------------------------------------------
# 3. bi_indemnity_quantification
# --------------------------------------------------------------------------

def outage_hours_of(claim):
    start = claim.get("_outage_start_at")
    end = claim.get("_outage_end_at")
    if start is None or end is None:
        return None
    seconds = dec((end - start).total_seconds())
    return round2(seconds / Decimal("3600"))


def compensable_hours_of(claim, section):
    hours = outage_hours_of(claim)
    if hours is None or section is None:
        return None
    waiting = dec(section["waiting_period_hours"] or 0)
    return max(Decimal("0"), hours - waiting)


def bi_indemnity_quantification(claim, proof, section, baseline_method):
    hours = outage_hours_of(claim)
    compensable = max(Decimal("0"), hours - dec(section["waiting_period_hours"] or 0))
    if baseline_method == "TRAILING_12M":
        hourly = dec(proof["trailing_12m_revenue_usd"]) / HOURS_PER_YEAR
    else:
        hourly = (dec(proof["prior_year_same_period_revenue_usd"])
                  / dec(proof["prior_year_same_period_hours"]))
    bi_component = round2(compensable * hourly * dec(proof["gross_profit_margin_pct"]))
    mitigation = round2(min(dec(proof["mitigation_savings_usd"]), bi_component))
    extra = round2(min(dec(proof["extra_expense_usd"]), bi_component * EXTRA_EXPENSE_CAP_PCT))
    assessed = round2(bi_component - mitigation + extra)
    return {
        "outage_hours": hours,
        "compensable_hours": compensable,
        "bi_component_usd": bi_component,
        "mitigation_component_usd": mitigation,
        "extra_expense_component_usd": extra,
        "assessed_indemnity_usd": assessed,
    }


# --------------------------------------------------------------------------
# 6. policy_loss_ratio
# --------------------------------------------------------------------------

def policy_loss_summary(policy):
    paid = Decimal("0.00")
    reserve = Decimal("0.00")
    for claim in claims_of(policy["id"]):
        for payment in payments_of_claim(claim["id"]):
            if payment["payment_status"] == "POSTED":
                paid += dec(payment["net_paid_usd"])
        if claim["status"] not in CLOSED_CLAIM_STATES:
            reserve += dec(claim["reserved_amount_usd"])
    paid = round2(paid)
    reserve = round2(reserve)
    incurred = round2(paid + reserve)
    premium = dec(policy["premium_usd"] or 0)
    loss_ratio = round4(incurred / premium) if premium != 0 else round4(0)
    return {
        "paid_total_usd": paid,
        "outstanding_reserve_usd": reserve,
        "incurred_usd": incurred,
        "loss_ratio": loss_ratio,
    }


# --------------------------------------------------------------------------
# 7. renewal_premium_adjustment
# --------------------------------------------------------------------------

def _loss_ratio_tier(loss_ratio):
    value = dec(loss_ratio)
    if value <= Decimal("0.30"):
        return Decimal("-0.05")
    if value <= Decimal("0.60"):
        return Decimal("0.05")
    if value <= Decimal("1.00"):
        return Decimal("0.20")
    return Decimal("0.45")


def renewal_premium_adjustment(policy, assessment):
    earned = dec(policy["premium_usd"])
    summary = policy_loss_summary(policy)
    loss_ratio = summary["loss_ratio"]
    tier = _loss_ratio_tier(loss_ratio)
    load = AGGREGATION_LOAD_PCT if policy["aggregation_flagged"] else Decimal("0.00")
    pre_credit = round2(earned * (Decimal("1") + tier + load))
    raw_credit = dec(len(assessment["verified_control_keys"] or [])) * CONTROL_CREDIT_PER_KEY
    credit = round2(min(raw_credit, pre_credit * CONTROL_CREDIT_CAP_PCT))
    renewal_premium = round2(pre_credit - credit)
    if renewal_premium < PREMIUM_FLOOR_USD:
        renewal_premium = PREMIUM_FLOOR_USD
    adjustment = round4((renewal_premium - earned) / earned)
    return {
        "loss_ratio": loss_ratio,
        "renewal_premium_usd": renewal_premium,
        "premium_adjustment_pct": adjustment,
    }


# --------------------------------------------------------------------------
# 8. panel_vendor_selection
# --------------------------------------------------------------------------

def colliding_count(vendor_id, window_start, window_end):
    count = 0
    for engagement in engagements_of_vendor(vendor_id):
        if engagement["status"] not in LIVE_ENGAGEMENT_STATES:
            continue
        start = engagement["_deployment_start_at"]
        end = engagement["_deployment_end_at"] + timedelta(hours=CHANGEOVER_BUFFER_HOURS)
        if start <= window_end and window_start <= end:
            count += 1
    return count


def panel_rank_key(vendor):
    return (vendor["tier"], dec(vendor["pre_approved_hourly_rate_usd"]),
            vendor["created_at"], vendor["_seq"])


def panel_vendor_selection(vendor_type, industry_code, window_start, window_end):
    candidates = []
    for vendor in store.panel_vendors.values():
        if vendor["vendor_type"] != vendor_type:
            continue
        if vendor["status"] != "ACTIVE":
            continue
        if industry_code not in (vendor["specialty_sectors"] or []):
            continue
        if colliding_count(vendor["id"], window_start, window_end) >= vendor["capacity_concurrent_engagements"]:
            continue
        candidates.append(vendor)
    if not candidates:
        return None
    candidates.sort(key=panel_rank_key)
    return candidates[0]


# --------------------------------------------------------------------------
# 9. engagement_incurred_amount
# --------------------------------------------------------------------------

def engagement_incurred_amount(engagement, hours, records):
    hours_term = round2(dec(hours) * dec(engagement["approved_rate_usd"]))
    records_term = round2(dec(records) * dec(engagement["approved_per_record_rate_usd"]))
    return round2(hours_term + records_term)


# --------------------------------------------------------------------------
# 10. systemic_aggregation_model
# --------------------------------------------------------------------------

def systemic_population(scenario):
    now = store.clock
    included = []
    for policy in store.policies.values():
        if policy["lifecycle_status"] != "INFORCE":
            continue
        if not (policy["_period_start"] <= now < policy["_period_end"]):
            continue
        account = store.insured_accounts.get(policy["insured_account_id"])
        if account is None or account["primary_dependency_key"] != scenario["dependency_key"]:
            continue
        if policy["dependent_bi_definition"] not in (scenario["qualifying_definitions"] or []):
            continue
        if section_by_key(policy["id"], "DEPENDENT_BI") is None:
            continue
        included.append(policy)
    return sorted_by_created(included)


def systemic_aggregation_model(scenario):
    included = systemic_population(scenario)
    total = Decimal("0.00")
    for policy in included:
        account = store.insured_accounts[policy["insured_account_id"]]
        section = section_by_key(policy["id"], "DEPENDENT_BI")
        hourly = dec(account["annual_revenue_usd"]) / HOURS_PER_YEAR
        compensable = max(Decimal("0"),
                          dec(scenario["assumed_outage_hours"]) - dec(section["waiting_period_hours"] or 0))
        modeled_loss = round2(compensable * hourly * MODELED_MARGIN_PCT)
        exposure = round2(min(modeled_loss, dec(section["sublimit_remaining_usd"])))
        after_retention = round2(max(Decimal("0"), exposure - dec(policy["retention_usd"])))
        after_coinsurance = round2(after_retention * (Decimal("1") - dec(section["coinsurance_pct"])))
        modeled_paid = round2(min(after_coinsurance, dec(policy["aggregate_limit_remaining_usd"])))
        total += modeled_paid
    gross = round2(total * dec(scenario["footprint_pct"]))
    return {
        "included_policies": included,
        "modeled_policy_count": len(included),
        "modeled_gross_exposure_usd": gross,
        "capacity_breached": gross > dec(scenario["portfolio_capacity_usd"]),
    }
