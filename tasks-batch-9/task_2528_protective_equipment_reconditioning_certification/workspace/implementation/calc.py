"""Domain constants, enums and the nine calculation rules (PRD 3.4-3.9)."""
from decimal import Decimal

import db
from util import add_days, add_years, date_key, day_start, dec, rhu, rhu_int

# --- enums -----------------------------------------------------------------
ORG_TYPES = ("SCHOOL", "CLUB", "COLLEGE", "MUNICIPAL")
SPORTS = ("FOOTBALL", "LACROSSE", "HOCKEY", "BASEBALL")
ACCOUNT_STATUSES = ("ACTIVE", "BILLING_HOLD")
WAIVER_STATUSES = ("MISSING", "ON_FILE", "STALE")
SHELL_MATERIALS = ("POLYCARBONATE", "ABS")
COMPONENT_CODES = ("SHELL", "LINER", "FACEMASK", "CHINSTRAP", "HARDWARE")
METRIC_DIRECTIONS = ("LOWER_IS_WORSE", "HIGHER_IS_WORSE")
TEST_TYPES = ("DROP_IMPACT", "PNEUMATIC_RAM")
CONDITION_GRADES = ("A", "B", "C")
LOANER_STATUSES = ("AVAILABLE", "RESERVED", "OUT_ON_LOAN")
SERVICE_TIERS = ("STANDARD", "SEASONAL_CONTRACT", "PRIORITY_RUSH")
DISCREPANCY_RESOLUTIONS = ("MATCHED", "CUSTOMER_CONFIRMED", "WRITTEN_OFF")
SHIPMENT_STATUSES = ("DRAFT", "COUNTED", "QUARANTINED", "ACCEPTED",
                     "IN_PROCESS", "READY_FOR_RETURN", "CLOSED")
RECON_STATUSES = ("RECEIVED", "IDENTIFIED", "DISASSEMBLED", "INSPECTED", "TESTED",
                  "TEST_PASSED", "REPAIR_PENDING", "REPAIRED", "CERTIFIED",
                  "CONDEMNED")
CUSTODY_STATUSES = ("AT_PLANT", "STAGED_FOR_RETURN", "RETURNED",
                    "PENDING_DISPOSAL", "DISPOSED")
AGE_BASES = ("MANUFACTURE_DATE", "FIRST_SEASON")
VERDICTS = ("PASS", "REPLACE", "FAIL")
SUMMARY_VALUES = ("PENDING", "CLEAR", "REPLACE_REQUIRED", "FAIL")
WARRANTY_COVERAGES = ("PENDING", "IN_WARRANTY", "OUT_OF_WARRANTY")
CONDEMN_REASONS = ("SI_EXCEEDS_LIMIT", "COMPONENT_FAIL", "LIFE_EXPIRED",
                   "NOT_RECONDITIONABLE", "REPAIR_UNSUCCESSFUL")
CONDITIONINGS = ("AMBIENT", "HOT", "COLD")
SHELL_TEST_STATUSES = ("SCHEDULED", "COMPLETED", "DETERMINED")
DETERMINATIONS = ("PASS", "REPAIR", "CONDEMN")
REPAIR_ORDER_STATUSES = ("DRAFT", "PARTS_PENDING", "INSTALLED", "CLOSED",
                         "CANCELLED")
PART_LINE_STATUSES = ("DRAFT", "RESERVED", "INSTALLED")
VERIFY_OUTCOMES = ("PASSED", "FAILED")
LABEL_STATUSES = ("ACTIVE", "VOIDED")
DESTRUCTION_METHODS = ("SHELL_CRUSH", "BAND_SAW_CUT", "SHREDDING")
DESTRUCTION_STATUSES = ("PENDING", "WITNESSED", "VERIFIED")
ASSIGNMENT_STATUSES = ("RESERVED", "OUT_ON_LOAN", "RETURNED")
SELECTED_BY = ("EXPLICIT", "SERVER_SELECTED")

# --- constants -------------------------------------------------------------
REQUIRED_WAIVER_VERSION = "2026.1"
LOANER_RECALL_GRACE_DAYS = 14
DAYS_PER_SERVICE_YEAR = 365

SITE_WEIGHT_FRONT = Decimal("0.5")
SITE_WEIGHT_SIDE = Decimal("0.3")
SITE_WEIGHT_CROWN = Decimal("0.2")
SITE_CONTRIBUTION_CAP = Decimal("150.0")
CONDITION_MULTIPLIER = {
    "AMBIENT": Decimal("1.00"),
    "HOT": Decimal("1.15"),
    "COLD": Decimal("1.08"),
}
MATERIAL_OFFSET = {"POLYCARBONATE": Decimal("0"), "ABS": Decimal("25")}

BASE_SERVICE_CENTS = Decimal(8996)
TIER_MULTIPLIER = {
    "STANDARD": Decimal("1.00"),
    "SEASONAL_CONTRACT": Decimal("1.00"),
    "PRIORITY_RUSH": Decimal("1.35"),
}
CONDEMN_HANDLING_CENTS = Decimal(2500)
REPAIR_LABOR_CENTS = 4500
DISCOUNT_TIER_1_FLOOR = 10000
DISCOUNT_TIER_2_FLOOR = 100000
DISCOUNT_RATE_TIER_0 = Decimal("0.000")
DISCOUNT_RATE_TIER_1 = Decimal("0.125")
DISCOUNT_RATE_TIER_2 = Decimal("0.150")
COMPLIANCE_SURCHARGE_RATE = Decimal("0.02")

TIER_BASE_DAYS = {"STANDARD": 30, "SEASONAL_CONTRACT": 30, "PRIORITY_RUSH": 10}
UNITS_PER_BATCH_DAY = 25
SEASON_BUFFER_DAYS = 7

LABEL_PREFIX = "RCP"
SEQUENCE_PAD_WIDTH = 3
LABEL_ISSUE_WINDOW_DAYS = 14

MAX_VERIFICATION_ATTEMPTS = 2

DETERMINATION_SEVERITY = {"PASS": 0, "REPAIR": 1, "CONDEMN": 2}


# --- C: liability waiver posture (PRD 3.1) ---------------------------------
def waiver_status(account):
    version = account.get("liability_waiver_version")
    if version is None:
        return "MISSING"
    if version == REQUIRED_WAIVER_VERSION:
        return "ON_FILE"
    return "STALE"


# --- C1: unit_service_age (PRD 3.4) ----------------------------------------
def unit_service_age(manufacture_date, age_basis, clock):
    """Whole-year service age under the frozen ageing basis; never negative."""
    if age_basis == "FIRST_SEASON":
        years = clock.year - manufacture_date.year
    else:
        elapsed_days = (day_start(clock) - day_start(manufacture_date)).days
        years = elapsed_days // DAYS_PER_SERVICE_YEAR
        if elapsed_days < 0:
            # floor division would run past zero for a future manufacture date
            years = -((-elapsed_days) // DAYS_PER_SERVICE_YEAR)
    if years < 0:
        years = 0
    return int(years)


def warranty_coverage(service_age_years, warranty_years):
    if service_age_years is None:
        return "PENDING"
    return "IN_WARRANTY" if service_age_years <= warranty_years else "OUT_OF_WARRANTY"


# --- C2: shell_test_severity_index (PRD 3.5) -------------------------------
def severity_index(front, side, crown, conditioning, shell_material):
    site_front = min(SITE_WEIGHT_FRONT * dec(front), SITE_CONTRIBUTION_CAP)
    site_side = min(SITE_WEIGHT_SIDE * dec(side), SITE_CONTRIBUTION_CAP)
    site_crown = min(SITE_WEIGHT_CROWN * dec(crown), SITE_CONTRIBUTION_CAP)
    raw_index = site_front + site_side + site_crown
    adjusted = raw_index * CONDITION_MULTIPLIER[conditioning] + MATERIAL_OFFSET[shell_material]
    return rhu(adjusted, 1)


def computed_result(index, pass_si_max, repair_si_max):
    value = dec(index)
    if value <= dec(pass_si_max):
        return "PASS"
    if value <= dec(repair_si_max):
        return "REPAIR"
    return "CONDEMN"


# --- C5: component_inspection_verdict (PRD 3.4) ----------------------------
def criteria_for(model, component_code):
    for entry in model.get("component_criteria") or []:
        if isinstance(entry, dict) and entry.get("code") == component_code:
            return entry
    return None


def component_verdict(measurement_value, metric_direction, replace_threshold,
                      fail_threshold):
    value = dec(measurement_value)
    if metric_direction == "LOWER_IS_WORSE":
        if value <= dec(fail_threshold):
            return "FAIL"
        if value <= dec(replace_threshold):
            return "REPLACE"
        return "PASS"
    if value >= dec(fail_threshold):
        return "FAIL"
    if value >= dec(replace_threshold):
        return "REPLACE"
    return "PASS"


def inspection_verdict_summary(unit, model):
    """PENDING / FAIL / REPLACE_REQUIRED / CLEAR, in that order of precedence."""
    if model is None:
        return "PENDING"
    rows = [r for r in db.db.component_inspections.values()
            if r["equipment_unit_id"] == unit["id"]]
    covered = set(r["component_code"] for r in rows)
    for code in model.get("required_component_codes") or []:
        if code not in covered:
            return "PENDING"
    for row in rows:
        if row["component_code"] == "SHELL" and row["verdict"] == "FAIL":
            return "FAIL"
    for row in rows:
        if row["component_code"] != "SHELL" and row["verdict"] in ("REPLACE", "FAIL"):
            return "REPLACE_REQUIRED"
    return "CLEAR"


def condemn_required(unit, model):
    if unit.get("life_expired"):
        return True
    if unit.get("inspection_verdict_summary") == "FAIL":
        return True
    if model is not None and model.get("reconditionable") is False:
        return True
    return False


# --- C4: turnaround_commitment (PRD 3.9) -----------------------------------
def turnaround_commitment(service_tier, counted_unit_count, season_start_date,
                          accepted_at):
    count = counted_unit_count or 0
    batch_days = -(-count // UNITS_PER_BATCH_DAY)  # ceil
    raw_due_at = add_days(accepted_at, TIER_BASE_DAYS[service_tier] + batch_days)
    season_deadline = add_days(season_start_date, -SEASON_BUFFER_DAYS)
    committed_due_at = raw_due_at if raw_due_at <= season_deadline else season_deadline
    loaner_required = raw_due_at > committed_due_at
    return raw_due_at, committed_due_at, loaner_required


# --- C3: shipment_settlement_total (PRD 3.9) -------------------------------
def _discount_rate(gross_cents):
    if gross_cents < DISCOUNT_TIER_1_FLOOR:
        return DISCOUNT_RATE_TIER_0
    if gross_cents < DISCOUNT_TIER_2_FLOOR:
        return DISCOUNT_RATE_TIER_1
    return DISCOUNT_RATE_TIER_2


def _closed_repair_labor(unit_id):
    total = 0
    for order in db.db.repair_orders.values():
        if order["equipment_unit_id"] == unit_id and order["status"] == "CLOSED":
            total += order.get("labor_cents") or 0
    return total


def billable_units(shipment):
    """Units of the shipment in CERTIFIED or CONDEMNED, created_at ascending."""
    rows = [u for u in db.db.equipment_units.values()
            if u["intake_shipment_id"] == shipment["id"]
            and u["recon_status"] in ("CERTIFIED", "CONDEMNED")]
    return db.ordered(rows)


def shipment_settlement_total(shipment, variant):
    """PROVISIONAL sums exact lines then rounds once; FINAL rounds each line."""
    multiplier = TIER_MULTIPLIER[shipment["service_tier"]]
    line_exacts = []
    if variant == "PROVISIONAL":
        count = shipment.get("counted_unit_count") or 0
        base = BASE_SERVICE_CENTS * multiplier
        line_exacts = [base for _ in range(count)]
    else:
        for unit in billable_units(shipment):
            line_base = BASE_SERVICE_CENTS * multiplier
            if unit["recon_status"] == "CONDEMNED":
                extra = CONDEMN_HANDLING_CENTS
            else:
                extra = dec(_closed_repair_labor(unit["id"]))
            line_exacts.append(line_base + extra)

    if variant == "PROVISIONAL":
        gross_cents = rhu_int(sum(line_exacts, Decimal(0)))
    else:
        gross_cents = sum((rhu_int(line) for line in line_exacts), 0)

    discount_cents = rhu_int(dec(gross_cents) * _discount_rate(gross_cents))
    net_cents = gross_cents - discount_cents
    surcharge_cents = rhu_int(dec(net_cents) * COMPLIANCE_SURCHARGE_RATE)
    return net_cents + surcharge_cents


# --- C6: certification_label_code (PRD 3.7) --------------------------------
def certification_label_code(standard_code_snapshot, certified_on):
    """daily_sequence is plant-wide within the certification date."""
    same_day = [row for row in db.db.certification_labels.values()
                if date_key(row["certified_on"]) == date_key(certified_on)
                and row["status"] in ("ACTIVE", "VOIDED")]
    daily_sequence = 1 + len(same_day)
    stamp = "%04d%02d%02d" % date_key(certified_on)
    label_code = "%s-%s-%s-%s" % (
        LABEL_PREFIX,
        standard_code_snapshot,
        stamp,
        str(daily_sequence).zfill(SEQUENCE_PAD_WIDTH),
    )
    return label_code, daily_sequence


# --- C7: loaner_unit_selection (PRD 3.9) -----------------------------------
def windows_overlap_half_open(a_start, a_end, b_start, b_end):
    """[start, end) intersection; touching endpoints are not an overlap."""
    return a_start < b_end and b_start < a_end


def active_assignments_for_loaner(loaner_id):
    return [a for a in db.db.loaner_assignments.values()
            if a.get("loaner_unit_id") == loaner_id
            and a["status"] in ("RESERVED", "OUT_ON_LOAN")]


def loaner_double_booked(loaner_id, window_start, window_end):
    for assignment in active_assignments_for_loaner(loaner_id):
        if windows_overlap_half_open(assignment["window_start"],
                                     assignment["window_end"],
                                     window_start, window_end):
            return True
    return False


def derived_loaner_status(loaner_id):
    """AVAILABLE, or the status of the earliest-starting active assignment."""
    active = active_assignments_for_loaner(loaner_id)
    if not active:
        return "AVAILABLE"
    active.sort(key=lambda a: (a["window_start"], a["created_at"], a["_seq"]))
    return active[0]["status"]


def select_loaner_unit(model_spec_id, window_start, window_end):
    """Selector policy: eligibility predicates then the three ranking keys."""
    eligible = []
    for loaner in db.db.loaner_units.values():
        if loaner["model_spec_id"] != model_spec_id:
            continue
        if loaner["status"] != "AVAILABLE":
            continue
        if loaner["certification_valid_until"] < window_end:
            continue
        if loaner_double_booked(loaner["id"], window_start, window_end):
            continue
        eligible.append(loaner)
    if not eligible:
        return None
    eligible.sort(key=lambda l: (
        CONDITION_GRADES.index(l["condition_grade"]),
        l["assignment_count"],
        l["created_at"],
        l["_seq"],
    ))
    return eligible[0]


# --- retention (PRD 3.8) ---------------------------------------------------
def retention_until(anchor, record_retention_years):
    if anchor is None:
        return None
    return add_years(anchor, record_retention_years)
