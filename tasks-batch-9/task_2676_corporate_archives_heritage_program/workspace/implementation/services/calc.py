"""The declared calculations (PRD 2.7 / section 3).  Decimal only for money."""

from decimal import ROUND_HALF_UP, Decimal

from core import add_days, clock, store

PAGES_PER_UNIT = 11

# --- generic helpers -------------------------------------------------------


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-int(places))
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def dec(value):
    return Decimal(str(value))


def clamp(value, low, high):
    return max(low, min(high, value))


# --- 1. appraisal scoring ---------------------------------------------------


def appraisal_score(appraisal, series, variant, brand_admitted_value):
    """variant is 'SCREENING' or 'FINAL'.

    SCREENING admits brand heritage unconditionally with multiplier 1.00.
    FINAL admits brand heritage only against a CERTIFIED evidence package and
    applies the 0.80 provenance haircut when provenance is unverified.
    """
    span_years = series["latest_record_year"] - series["earliest_record_year"] + 1
    age_bonus = min(10, span_years // 5)
    linear_feet = dec(series["annual_volume_linear_feet"])
    if linear_feet <= Decimal("50"):
        volume_penalty = 0
    else:
        volume_penalty = max(0, min(15, int((linear_feet - Decimal("50")) // Decimal("10"))))
    core = (
        appraisal["informational_value"] * 3
        + appraisal["evidential_value"] * 3
        + brand_admitted_value * 2
        + appraisal["uniqueness_factor"] * 2
    )
    raw = clamp(core + age_bonus - volume_penalty, 0, 100)
    if variant == "SCREENING":
        multiplier = Decimal("1.00")
    else:
        multiplier = Decimal("1.00") if appraisal["provenance_verified"] else Decimal("0.80")
    return round_half_up(Decimal(raw) * multiplier, 2)


def series_has_certified_package(series_id):
    for package in store.evidence_packages.values():
        if package["record_series_id"] == series_id and package["status"] == "CERTIFIED":
            return True
    return False


# --- 2. confidentiality risk scoring ---------------------------------------

CLASS_WEIGHT = {"INTERNAL_BUSINESS": 10, "EXTERNAL_RESEARCHER": 30, "MEDIA": 45}
SENSITIVITY_WEIGHT = {"PUBLIC": 0, "INTERNAL": 15, "CONFIDENTIAL": 35, "RESTRICTED": 60}
NDA_CREDIT = 12
HOLD_CHARGE = 25
REDACTION_CREDIT = 10


def prelim_risk_score(requester, series):
    total = (
        CLASS_WEIGHT[requester["requester_class"]]
        + SENSITIVITY_WEIGHT[series["sensitivity_ceiling"]]
        - (NDA_CREDIT if requester["nda_on_file"] else 0)
    )
    return clamp(total, 0, 100)


def max_item_sensitivity(item_ids):
    highest = None
    highest_weight = -1
    for item_id in item_ids:
        item = store.archival_items.get(item_id)
        if item is None:
            continue
        weight = SENSITIVITY_WEIGHT[item["sensitivity_level"]]
        if weight > highest_weight:
            highest_weight = weight
            highest = item["sensitivity_level"]
    return highest


def post_screen_risk_score(requester, series, item_ids, redaction_required):
    peak = max_item_sensitivity(item_ids)
    total = CLASS_WEIGHT[requester["requester_class"]]
    total += SENSITIVITY_WEIGHT[peak] if peak is not None else 0
    if series["legal_hold_active"]:
        total += HOLD_CHARGE
    if requester["nda_on_file"]:
        total -= NDA_CREDIT
    if redaction_required:
        total -= REDACTION_CREDIT
    return clamp(total, 0, 100)


# --- 3. access service fee -------------------------------------------------

PER_PAGE_CENTS = {"INTERNAL_BUSINESS": 0, "EXTERNAL_RESEARCHER": 35, "MEDIA": 90}
BASE_ADMIN_FEE_CENTS = 2500
MEDIA_SURCHARGE_CENTS = 15000


def requested_page_count(item_ids):
    total = 0
    for item_id in item_ids:
        item = store.archival_items.get(item_id)
        if item is not None:
            total += item["unit_count"]
    return PAGES_PER_UNIT * total


def _volume_tier(total_pages):
    if total_pages <= 100:
        return Decimal("0.000")
    if total_pages <= 500:
        return Decimal("0.075")
    return Decimal("0.125")


def access_service_fee(requester, item_ids):
    """Per-line rounding happens before the lines are summed (PRD 3.7)."""
    items = [store.archival_items[i] for i in item_ids if i in store.archival_items]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    pages = [item["unit_count"] * PAGES_PER_UNIT for item in items]
    total_pages = sum(pages)
    tier = _volume_tier(total_pages)
    rate = Decimal(PER_PAGE_CENTS[requester["requester_class"]])
    subtotal = 0
    for page_count in pages:
        gross = Decimal(page_count) * rate
        subtotal += int(round_half_up(gross * (Decimal("1") - tier), 0))
    fee = subtotal + BASE_ADMIN_FEE_CENTS
    if requester["requester_class"] == "MEDIA":
        fee += MEDIA_SURCHARGE_CENTS
    return fee


# --- 4. migration job cost waterfall --------------------------------------

FORMAT_RATE_CENTS = {
    "PAPER": 900,
    "PHOTO": 1800,
    "FILM": 3600,
    "MAGNETIC_TAPE": 4200,
    "BORN_DIGITAL": 600,
}
CONDITION_SURCHARGE_PCT = {
    "GOOD": Decimal("0.00"),
    "FAIR": Decimal("0.05"),
    "POOR": Decimal("0.12"),
    "UNSTABLE": Decimal("0.20"),
}


def migration_job_cost(item, units):
    subtotal = FORMAT_RATE_CENTS[item["original_format"]] * int(units)
    if subtotal <= 50000:
        discount = Decimal("0.00")
    elif subtotal <= 200000:
        discount = Decimal("0.06")
    else:
        discount = Decimal("0.11")
    discounted = int(round_half_up(Decimal(subtotal) * (Decimal("1") - discount), 0))
    if discounted <= 25000:
        handling = 1500
    elif discounted <= 100000:
        handling = 4000
    else:
        handling = 9000
    surcharge = int(
        round_half_up(
            Decimal(discounted + handling) * CONDITION_SURCHARGE_PCT[item["condition_grade"]], 0
        )
    )
    return {
        "subtotal_cents": subtotal,
        "volume_discount_pct": float(discount),
        "discounted_cents": discounted,
        "handling_fee_cents": handling,
        "condition_surcharge_cents": surcharge,
        "committed_cost_cents": discounted + handling + surcharge,
    }


# --- 5. trademark continuous use coverage --------------------------------


def continuous_use_coverage(package):
    span_start = package["claimed_first_use_year"]
    span_end = clock.now().year
    span_years = span_end - span_start + 1
    years = set()
    qualifying = 0
    for item_id in package["evidence_item_ids"]:
        item = store.archival_items.get(item_id)
        if item is None:
            continue
        year = item.get("brand_use_year")
        if year is None:
            continue
        if item["status"] == "DEACCESSIONED":
            continue
        if year < span_start or year > span_end:
            continue
        qualifying += 1
        years.add(year)
    if qualifying == 0:
        return {"qualifying_evidence_count": 0}
    ordered = sorted(years)
    gaps = [ordered[0] - span_start]
    for index in range(len(ordered) - 1):
        gaps.append(ordered[index + 1] - ordered[index] - 1)
    gaps.append(span_end - ordered[-1])
    max_gap = max(gaps)
    coverage = round_half_up(Decimal(100) * Decimal(len(ordered)) / Decimal(span_years), 2)
    return {
        "qualifying_evidence_count": qualifying,
        "covered_year_count": len(ordered),
        "max_gap_years": max_gap,
        "continuous_use_coverage_pct": float(coverage),
        "span_years": span_years,
    }


# --- 6. storage zone environmental classification -------------------------

LOAN_BUFFER_DAYS = 45
AT_RISK_ITEM_STATUSES = ("UNPROCESSED", "ACCESSIONED", "IN_TREATMENT")
AT_RISK_FORMATS = ("MAGNETIC_TAPE", "FILM")


def zone_environmental_status(temperature_c, relative_humidity_pct):
    temperature = dec(temperature_c)
    humidity = dec(relative_humidity_pct)
    if temperature <= Decimal("18.0") and Decimal("30.0") <= humidity <= Decimal("50.0"):
        return "COMPLIANT"
    if temperature <= Decimal("21.0") and Decimal("30.0") <= humidity <= Decimal("55.0"):
        return "MARGINAL"
    return "NON_COMPLIANT"


# --- 7. at-risk unit census ------------------------------------------------


def at_risk_unit_count(storage_zone_id):
    total = 0
    for item in store.archival_items.values():
        if item["storage_zone_id"] != storage_zone_id:
            continue
        if item["status"] not in AT_RISK_ITEM_STATUSES:
            continue
        if item["original_format"] not in AT_RISK_FORMATS:
            continue
        if item["digital_surrogate_available"]:
            continue
        total += item["unit_count"]
    return total


# --- 8. exhibit loan window occupation (HALF-OPEN + trailing buffer) -------

LOAN_OCCUPYING_STATUSES = ("REQUESTED", "CONFIRMED", "OUT")
LOAN_HISTORY_STATUSES = ("REQUESTED", "CONFIRMED", "OUT", "RETURNED")


def exhibit_loan_window_conflict(archival_item_id, window_start, window_end, exclude_id=None):
    """Conflict iff new.start < (existing.end + 45d) AND existing.start < new.end."""
    for loan in store.exhibit_loans.values():
        if loan["archival_item_id"] != archival_item_id:
            continue
        if exclude_id is not None and loan["id"] == exclude_id:
            continue
        if loan["status"] not in LOAN_OCCUPYING_STATUSES:
            continue
        buffered_end = add_days(loan["window_end"], LOAN_BUFFER_DAYS)
        if window_start < buffered_end and loan["window_start"] < window_end:
            return loan
    return None


def latest_loan_window_end(archival_item_id):
    newest = None
    for loan in store.exhibit_loans.values():
        if loan["archival_item_id"] != archival_item_id:
            continue
        if loan["status"] not in LOAN_HISTORY_STATUSES:
            continue
        if newest is None or (loan["created_at"], loan["_seq"]) > (
            newest["created_at"],
            newest["_seq"],
        ):
            newest = loan
    return newest["window_end"] if newest is not None else None


def item_has_occupying_loan(archival_item_id):
    for loan in store.exhibit_loans.values():
        if loan["archival_item_id"] != archival_item_id:
            continue
        if loan["status"] in LOAN_OCCUPYING_STATUSES:
            return loan
    return None


# --- 9. zone migration capacity (CLOSED both ends + aggregate peak) -------

CAPACITY_JOB_STATUSES = ("APPROVED", "IN_PROGRESS")


def zone_migration_peak(job, storage_zone_id):
    overlaps = []
    for other in store.migration_jobs.values():
        if other["id"] == job["id"]:
            continue
        if other["status"] not in CAPACITY_JOB_STATUSES:
            continue
        other_item = store.archival_items.get(other["archival_item_id"])
        if other_item is None or other_item["storage_zone_id"] != storage_zone_id:
            continue
        if other["window_start"] <= job["window_end"] and job["window_start"] <= other["window_end"]:
            overlaps.append(other)
    instants = [job["window_start"]] + [other["window_start"] for other in overlaps]
    peak = 1
    for instant in instants:
        covering = 0
        for other in overlaps:
            if other["window_start"] <= instant <= other["window_end"]:
                covering += 1
        peak = max(peak, 1 + covering)
    return peak


# --- 10. oral history derived release state -------------------------------

TRANSCRIPTION_READABLE = ("REVIEWED", "APPROVED")


def interview_release_state(interview):
    consent = interview["consent_status"]
    transcription = interview["transcription_status"]
    if consent in ("WITHDRAWN", "PENDING"):
        return "WITHHELD"
    embargo = interview.get("embargo_until")
    embargo_elapsed = embargo is None or clock.now() >= embargo
    if consent == "RESTRICTED":
        if transcription in TRANSCRIPTION_READABLE:
            return "RESEARCH_ROOM_ONLY"
        return "WITHHELD"
    # consent == SIGNED
    if transcription == "APPROVED" and embargo_elapsed:
        return "PUBLIC"
    if transcription in TRANSCRIPTION_READABLE:
        return "RESEARCH_ROOM_ONLY"
    return "WITHHELD"
