"""Domain constants, enumerations and pure calculations."""
import re
from datetime import timedelta
from decimal import Decimal

from core import DB, ceil_div, half_up, minutes_between, now

# --------------------------------------------------------------------------- enumerations
CLIENT_STATUSES = ("ACTIVE", "SUSPENDED")
TEMPLATE_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
MAIL_CLASS_PREFERENCES = ("FIRST_CLASS", "MARKETING")
PIECE_MAIL_CLASSES = ("FIRST_CLASS", "MARKETING", "NONE_ELECTRONIC")
INSERT_STATUSES = ("ACTIVE", "WITHDRAWN")
FORMAT_SPEC_CODES = ("FIXED_WIDTH", "DELIMITED", "XML")
FILE_STATUSES = ("RECEIVED", "FORMAT_VALIDATED", "HELD_VARIANCE", "ACCEPTED", "CONSUMED")
HYGIENE_STATUSES = ("PENDING", "DELIVERABLE", "CORRECTED", "UNDELIVERABLE_AS_ADDRESSED", "STALE")
DELIVERY_CHANNELS = ("PENDING", "PRINT", "ELECTRONIC")
ENROLLMENT_CHANNELS = ("EMAIL", "PORTAL")
ENROLLMENT_STATUSES = ("PENDING", "ENROLLED", "REVOKED")
JOB_STATUSES = (
    "COMPOSED", "PRESORTED", "SCHEDULED", "PRINTING", "PRINTED",
    "INTEGRITY_HELD", "VERIFIED", "MANIFESTED", "CLOSED",
)
JOB_INTEGRITY_STATUSES = ("PENDING", "MATCHED", "BREACHED")
PIECE_STATUSES = ("COMPOSED", "PRINTED", "INSERTED", "INDUCTED", "SUPPRESSED", "VOID")
PIECE_INTEGRITY_STATUSES = ("UNVERIFIED", "SCAN_MATCHED", "SCAN_MISSING", "DUPLICATE_SCAN", "RECONCILED")
PRESORT_BUCKETS = ("PENDING", "FIVE_DIGIT", "THREE_DIGIT", "AADC", "MIXED_AADC", "NONMACHINABLE")
BATCH_BUCKETS = ("FIVE_DIGIT", "THREE_DIGIT", "AADC", "MIXED_AADC", "NONMACHINABLE")
SCAN_STAGES = ("PRINT", "INSERT", "INDUCT")
LAST_SCAN_STAGES = ("NONE", "PRINT", "INSERT", "INDUCT")
REJECTION_REASONS = ("NONE", "UNKNOWN_BARCODE", "DUPLICATE_STAGE", "OUT_OF_SEQUENCE")
PRESS_CAPABILITIES = ("DUPLEX", "COLOR", "INSERT")
PRESS_LINE_STATUSES = ("AVAILABLE", "MAINTENANCE")
RUN_STATUSES = ("PLANNED", "RUNNING", "COMPLETED", "ABORTED")
ABORT_REASONS = ("NONE", "EQUIPMENT_FAULT", "INTEGRITY_BREACH", "DR_FAILOVER")
SELECTION_MODES = ("EXPLICIT", "SELECTED")
FACILITY_TYPES = ("SCF", "NDC", "DDU")
FACILITY_STATUSES = ("OPEN", "CLOSED")
BATCH_STATUSES = ("OPEN", "SEALED", "MANIFESTED")
RETURN_REASON_CODES = ("MOVED_NO_FORWARD", "INSUFFICIENT_ADDRESS", "VACANT", "REFUSED", "DECEASED")
RETURN_DISPOSITIONS = ("SCANNED", "ADDRESS_UPDATED", "UNRESOLVED", "FEEDBACK_SENT")
DRILL_RESULTS = ("PASS", "FAIL")
DRILL_RESULT_STATES = ("NONE", "PASS", "FAIL")
READINESS_STATUSES = ("UNTESTED", "READY", "STALE", "FAILED")

# --------------------------------------------------------------------------- constants
W_ADDRESS_LINE1 = 2500
W_CITY = 1000
W_REGION = 1500
W_POSTAL5 = 2200
W_PLUS4 = 2800
DELIVERABLE_THRESHOLD = Decimal("0.90")
CORRECTED_THRESHOLD = Decimal("0.65")

SIDES_PER_SHEET = 2

MAX_MACHINABLE_SHEETS = 12
MIN_FIVE_DIGIT_PIECES = 3
MIN_THREE_DIGIT_PIECES = 2
MIN_AADC_PIECES = 2
TRAY_CAPACITY_PIECES = 4

FREE_SHEETS_PER_PIECE = 3
SHEET_SURCHARGE_CENTS = 3
BASE_RATE_TABLE = {
    "FIRST_CLASS": {"FIVE_DIGIT": 53, "THREE_DIGIT": 56, "AADC": 58, "MIXED_AADC": 62, "NONMACHINABLE": 88},
    "MARKETING": {"FIVE_DIGIT": 27, "THREE_DIGIT": 30, "AADC": 33, "MIXED_AADC": 37, "NONMACHINABLE": 55},
}

HEADROOM_WEIGHT_BP = 6000
SPEED_WEIGHT_BP = 4000
SURPLUS_PENALTY_POINTS = 500
MIN_RUN_MINUTES = 60

COMPOSITION_RATE_CENTS_PER_SHEET = 9
INSERT_RATE_CENTS_PER_SHEET = 4
RUSH_FEE_BP = 1500
DISCOUNT_TIERS = ((400, 1200), (230, 800), (200, 400))

FULFILMENT_LAG_MINUTES = 120
BASE_SEVERITY_BP = 10000
RUSH_SEVERITY_BP = 15000

DR_DRILL_VALIDITY_HOURS = 720
MAX_REPLICATION_LAG_MINUTES = 15

ACCOUNT_REF_PATTERN = re.compile(r"^[A-Z]{3}[0-9]{4}$")
POSTAL5_PATTERN = re.compile(r"^[0-9]{5}$")
PLUS4_PATTERN = re.compile(r"^[0-9]{4}$")
CLIENT_CODE_PATTERN = r"^[A-Z0-9]{3,10}$"

BUCKET_CREATION_ORDER = ("FIVE_DIGIT", "THREE_DIGIT", "AADC", "MIXED_AADC", "NONMACHINABLE")
MAIL_CLASS_CREATION_ORDER = ("FIRST_CLASS", "MARKETING")


# --------------------------------------------------------------------------- format validation
def record_format_valid(record, format_spec_code):
    account_ref = record.get("account_ref") or ""
    base_ok = (
        bool(ACCOUNT_REF_PATTERN.match(account_ref))
        and record.get("statement_amount_cents", 0) >= 0
        and bool(record.get("address_line1"))
    )
    if format_spec_code == "FIXED_WIDTH":
        return base_ok and len(account_ref) == 7 and len(record.get("postal_code") or "") == 5
    if format_spec_code == "DELIMITED":
        return base_ok and bool(POSTAL5_PATTERN.match(record.get("postal_code") or ""))
    if format_spec_code == "XML":
        return base_ok and bool(record.get("region_code"))
    return False


def control_total_variance_bp(variance_cents, declared_total):
    if declared_total == 0:
        return 0 if variance_cents == 0 else 10000
    return half_up(Decimal(abs(variance_cents)) * Decimal(10000) / Decimal(declared_total))


# --------------------------------------------------------------------------- hygiene
def hygiene_confidence(record):
    awarded = 0
    if len(record.get("address_line1") or "") >= 5:
        awarded += W_ADDRESS_LINE1
    if record.get("city"):
        awarded += W_CITY
    if len(record.get("region_code") or "") == 2:
        awarded += W_REGION
    if POSTAL5_PATTERN.match(record.get("postal_code") or ""):
        awarded += W_POSTAL5
    if PLUS4_PATTERN.match(record.get("postal_code_plus4") or ""):
        awarded += W_PLUS4
    return half_up(Decimal(awarded) / Decimal(10000), 2)


def hygiene_disposition(confidence):
    if confidence >= DELIVERABLE_THRESHOLD:
        return "DELIVERABLE"
    if confidence >= CORRECTED_THRESHOLD:
        return "CORRECTED"
    return "UNDELIVERABLE_AS_ADDRESSED"


# --------------------------------------------------------------------------- sheet composition
def compose_sheets(template, record, insert_by_code):
    insert_codes = list(template.get("required_insert_codes") or [])
    add_sheets = 0
    rules = sorted(template.get("variable_content_rules") or [], key=lambda r: r["rule_code"])
    for rule in rules:
        if record.get("statement_amount_cents", 0) >= rule["threshold_amount_cents"]:
            add_sheets += rule["add_sheets"]
            if rule.get("required_insert_code") is not None:
                insert_codes.append(rule["required_insert_code"])
    insert_codes = sorted(set(insert_codes))
    insert_sheet_count = 0
    for code in insert_codes:
        stock = insert_by_code.get(code)
        insert_sheet_count += stock["sheets_per_insert"] if stock else 0
    sheet_count = template["sheets_per_document"] + add_sheets + insert_sheet_count
    color_page_count = min(template["color_pages_per_document"], sheet_count * SIDES_PER_SHEET)
    return {
        "insert_codes": insert_codes,
        "insert_sheet_count": insert_sheet_count,
        "sheet_count": sheet_count,
        "color_page_count": color_page_count,
    }


# --------------------------------------------------------------------------- barcode
def compact_instant(dt):
    return "%04d%02d%02d%02d%02d%02d" % (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def mint_barcode(client_code, received_at, piece_seq):
    return "%s-%s-%06d" % (client_code, compact_instant(received_at), piece_seq)


# --------------------------------------------------------------------------- postage
def piece_gross_postage(mail_class, presort_bucket, sheet_count):
    base = BASE_RATE_TABLE.get(mail_class, {}).get(presort_bucket, 0)
    surcharge = max(0, sheet_count - FREE_SHEETS_PER_PIECE) * SHEET_SURCHARGE_CENTS
    return base + surcharge


def piece_net_postage(gross, discount_bp):
    return half_up(Decimal(gross) * Decimal(10000 - discount_bp) / Decimal(10000))


# --------------------------------------------------------------------------- press line selection
def press_requirements(job, template):
    required = set()
    if template.get("duplex_required"):
        required.add("DUPLEX")
    if job.get("color_page_count", 0) > 0:
        required.add("COLOR")
    if job.get("insert_sheet_total", 0) > 0:
        required.add("INSERT")
    return required


def line_score(line, required):
    headroom = line["daily_sheet_capacity"] - line["committed_sheet_count"]
    surplus = len([cap for cap in line["capabilities"] if cap not in required])
    raw = (
        Decimal(headroom) * Decimal(HEADROOM_WEIGHT_BP) / Decimal(10000)
        + Decimal(line["sheets_per_hour"]) * Decimal(SPEED_WEIGHT_BP) / Decimal(10000)
        - Decimal(surplus) * Decimal(SURPLUS_PENALTY_POINTS)
    )
    return half_up(raw, 2)


def run_minutes_for(planned_sheet_count, sheets_per_hour):
    quotient = ceil_div(Decimal(planned_sheet_count) * Decimal(60), Decimal(sheets_per_hour))
    return max(MIN_RUN_MINUTES, quotient)


def window_conflicts(line, window_start, window_end, exclude_run_id=None):
    buffer_minutes = timedelta(minutes=line["changeover_buffer_minutes"])
    for run in DB.runs.values():
        if run["press_line_id"] != line["id"]:
            continue
        if run["status"] not in ("PLANNED", "RUNNING"):
            continue
        if exclude_run_id is not None and run["id"] == exclude_run_id:
            continue
        if window_start <= run["window_end"] + buffer_minutes and run["window_start"] <= window_end + buffer_minutes:
            return True
    return False


def utilization_bp(line):
    return half_up(Decimal(line["committed_sheet_count"]) * Decimal(10000) / Decimal(line["daily_sheet_capacity"]))


# --------------------------------------------------------------------------- sla and billing
def severity_bp(job):
    return RUSH_SEVERITY_BP if job.get("rush_requested") else BASE_SEVERITY_BP


def penalty_from_late_minutes(client, job, late_minutes):
    if late_minutes < 0:
        late_minutes = Decimal(0)
    late_hours = ceil_div(late_minutes, Decimal(60))
    raw = (
        Decimal(late_hours)
        * Decimal(client["sla_penalty_rate_cents_per_hour"])
        * Decimal(severity_bp(job))
        / Decimal(10000)
    )
    penalty = half_up(raw)
    return min(client["sla_penalty_cap_cents"], penalty)


def projected_penalty(client, job, projected_completion_at):
    late = minutes_between(job["sla_due_at"], projected_completion_at)
    if late < 0:
        late = Decimal(0)
    return penalty_from_late_minutes(client, job, late)


def assessed_penalty(client, job, completed_at):
    late = minutes_between(job["sla_due_at"], completed_at) - Decimal(job.get("sla_hold_minutes", 0))
    if late < 0:
        late = Decimal(0)
    return penalty_from_late_minutes(client, job, late)


def volume_discount_bp(pre_discount_subtotal_cents):
    for floor_cents, bp in DISCOUNT_TIERS:
        if pre_discount_subtotal_cents >= floor_cents:
            return bp
    return 0


def billing_figures(job):
    composition_charge = job.get("total_sheet_count", 0) * COMPOSITION_RATE_CENTS_PER_SHEET
    insert_charge = job.get("insert_sheet_total", 0) * INSERT_RATE_CENTS_PER_SHEET
    pre_discount = composition_charge + insert_charge
    discount_bp = volume_discount_bp(pre_discount)
    volume_discount = half_up(Decimal(pre_discount) * Decimal(discount_bp) / Decimal(10000))
    post_discount = pre_discount - volume_discount
    if job.get("rush_requested"):
        expedite = half_up(Decimal(post_discount) * Decimal(RUSH_FEE_BP) / Decimal(10000))
    else:
        expedite = 0
    return {
        "composition_charge_cents": composition_charge,
        "insert_charge_cents": insert_charge,
        "pre_discount_subtotal_cents": pre_discount,
        "volume_discount_cents": volume_discount,
        "expedite_fee_cents": expedite,
        "billing_total_cents": post_discount + expedite,
    }


# --------------------------------------------------------------------------- dr readiness
def dr_readiness(site):
    if site.get("last_drill_at") is None:
        return "UNTESTED", None
    valid_until = site["last_drill_at"] + timedelta(hours=DR_DRILL_VALIDITY_HOURS)
    if site.get("last_drill_result") == "FAIL":
        return "FAILED", valid_until
    if now() > valid_until:
        return "STALE", valid_until
    if site.get("replication_lag_minutes", 0) > MAX_REPLICATION_LAG_MINUTES:
        return "STALE", valid_until
    return "READY", valid_until
