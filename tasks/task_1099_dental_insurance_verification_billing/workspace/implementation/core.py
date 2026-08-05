"""Core: in-memory store, logical clock, envelope, errors, auth, serializers, calculations."""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
VERIFICATION_VALIDITY_DAYS = 30
FREQUENCY_WINDOW_DAYS = 365
COLLECTIONS_THRESHOLD_CENTS = 50000
APPEAL_LIMIT = 2
MEMBERSHIP_GRACE_DAYS = 15
MAX_PAST_DUE_PERIODS = 2

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

VALID_ROLES = {"FrontOffice", "Biller", "BillingManager", "Patient"}

# ----------------------------------------------------------------------------
# Error catalog
# ----------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ATTACHMENT_TARGET_REQUIRED": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PAYMENT_CLAIM_MISMATCH": 409,
    "ERR_PRIMARY_CLAIM_NOT_ADJUDICATED": 409,
    "ERR_COVERAGE_INACTIVE": 409,
    "ERR_VERIFICATION_REQUIRED": 409,
    "ERR_VERIFICATION_EXPIRED": 409,
    "ERR_FREQUENCY_LIMIT_EXCEEDED": 409,
    "ERR_MISSING_NARRATIVE": 422,
    "ERR_MISSING_ATTACHMENT": 422,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_MEMBERSHIP_OVERLAP": 409,
    "ERR_ANNUAL_MAXIMUM_EXCEEDED": 409,
    "ERR_OVERPAYMENT": 422,
    "ERR_APPEAL_NOT_ALLOWED": 409,
    "ERR_MEMBERSHIP_NOT_PAYABLE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ----------------------------------------------------------------------------
# In-memory store
# ----------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.patients = {}
        self.insurance_plans = {}
        self.procedures = {}
        self.coverages = {}
        self.verifications = {}
        self.preauthorizations = {}
        self.attachments = {}
        self.claims = {}
        self.payments = {}
        self.membership_plans = {}
        self.memberships = {}
        self._seq = 0
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = None


def get_clock():
    return db.clock


# ----------------------------------------------------------------------------
# Time / date helpers
# ----------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO8601 datetime (accepting trailing Z) into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_dt(dt):
    """Render an aware datetime as ISO8601 UTC with 3 fractional digits and Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    return datetime.now(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD ISO date string into a date."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return date.fromisoformat(value.strip())


def add_months(d, n):
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to last valid day of month
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def advance_period(d, billing_period):
    if billing_period == "ANNUAL":
        return add_months(d, 12)
    return add_months(d, 1)


def round_half_up(numerator, denominator=1):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# Record creation helpers
# ----------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_record(common_fields=True):
    now = render_dt(wall_now())
    rec = {"id": new_id(), "_seq": db.next_seq(), "created_at": now}
    if common_fields:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = render_dt(wall_now())
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ----------------------------------------------------------------------------
# Validation helpers
# ----------------------------------------------------------------------------
def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def require_nonneg_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        err("ERR_INVALID_REQUEST", f"Field {field} must be a non-negative integer")
    return v


def optional_nonneg_int(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    return require_nonneg_int(body, field)


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    return require_enum(body, field, allowed)


# ----------------------------------------------------------------------------
# Serializers
# ----------------------------------------------------------------------------
COMMON_OUT = ("id", "created_at", "updated_at", "version")


def _pick_common(rec):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def serialize_patient(rec):
    out = _pick_common(rec)
    out["full_name"] = rec["full_name"]
    out["date_of_birth"] = rec["date_of_birth"]
    out["email"] = rec["email"]
    bal = patient_balance(rec["id"])
    out["balance_cents"] = bal
    out["status"] = "COLLECTIONS" if bal > COLLECTIONS_THRESHOLD_CENTS else "ACTIVE"
    return out


def serialize_insurance_plan(rec):
    out = _pick_common(rec)
    for f in ("payer_name", "plan_name", "annual_maximum_cents", "deductible_cents",
              "deductible_applies_to", "preventive_coinsurance_pct", "basic_coinsurance_pct",
              "major_coinsurance_pct", "cob_method"):
        out[f] = rec[f]
    return out


def serialize_procedure(rec):
    out = _pick_common(rec)
    for f in ("cdt_code", "description", "category", "ucr_fee_cents",
              "frequency_limit_per_year", "requires_narrative", "requires_attachment"):
        out[f] = rec[f]
    return out


def coverage_status(rec):
    clock_date = get_clock().date()
    eff = parse_date(rec["effective_date"])
    term = parse_date(rec["term_date"])
    return "ACTIVE" if eff <= clock_date <= term else "TERMINATED"


def serialize_coverage(rec):
    out = _pick_common(rec)
    for f in ("patient_id", "insurance_plan_id", "priority", "subscriber_id",
              "relationship", "effective_date", "term_date",
              "benefits_used_cents", "deductible_met_cents"):
        out[f] = rec[f]
    out["status"] = coverage_status(rec)
    return out


def verification_expires_at(rec):
    return parse_iso(rec["verified_at"]) + timedelta(days=VERIFICATION_VALIDITY_DAYS)


def verification_status(rec):
    return "VERIFIED" if get_clock() <= verification_expires_at(rec) else "EXPIRED"


def serialize_verification(rec):
    out = _pick_common(rec)
    for f in ("coverage_id", "verified_annual_maximum_cents", "verified_deductible_cents",
              "verified_preventive_pct", "verified_basic_pct", "verified_major_pct",
              "verified_at"):
        out[f] = rec[f]
    out["expires_at"] = render_dt(verification_expires_at(rec))
    out["status"] = verification_status(rec)
    return out


def preauth_attachment_count(preauth_id):
    return sum(1 for a in db.attachments.values() if a.get("preauth_id") == preauth_id)


def serialize_preauth(rec):
    out = _pick_common(rec)
    for f in ("patient_id", "coverage_id", "procedures", "narrative", "status",
              "estimated_benefit_cents", "approved_amount_cents", "submitted_at"):
        out[f] = rec[f]
    out["attachment_count"] = preauth_attachment_count(rec["id"])
    return out


def serialize_attachment(rec):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    for f in ("claim_id", "preauth_id", "kind", "filename", "note"):
        out[f] = rec[f]
    return out


def claim_total_billed(rec):
    return sum(int(line.get("billed_fee_cents", 0)) for line in rec["procedures"])


def claim_patient_paid(claim_id):
    return sum(p["amount_cents"] for p in db.payments.values()
               if p.get("claim_id") == claim_id and p["payer_type"] == "PATIENT"
               and p["status"] == "POSTED")


def claim_aging_days(rec):
    if rec["status"] == "CLOSED" or not rec.get("submitted_at"):
        return 0
    delta = get_clock() - parse_iso(rec["submitted_at"])
    days = int(delta.total_seconds() // 86400)
    return max(0, days)


def aging_bucket(days):
    if days <= 30:
        return "CURRENT"
    if days <= 60:
        return "DAYS_31_60"
    if days <= 90:
        return "DAYS_61_90"
    return "DAYS_90_PLUS"


def serialize_claim(rec):
    out = _pick_common(rec)
    for f in ("patient_id", "coverage_id", "preauth_id", "primary_claim_id", "procedures",
              "narrative", "service_date", "status", "estimated_insurance_cents",
              "estimated_patient_portion_cents", "paid_insurance_cents",
              "final_patient_portion_cents", "submitted_by_user_id", "submitted_at",
              "adjudicated_at", "appeal_count"):
        out[f] = rec[f]
    out["total_billed_cents"] = claim_total_billed(rec)
    out["patient_paid_cents"] = claim_patient_paid(rec["id"])
    days = claim_aging_days(rec)
    out["aging_days"] = days
    out["aging_bucket"] = aging_bucket(days)
    return out


def serialize_payment(rec):
    out = _pick_common(rec)
    for f in ("claim_id", "patient_id", "payer_type", "amount_cents", "eob_lines",
              "is_denial", "status", "posted_at"):
        out[f] = rec[f]
    return out


def serialize_membership_plan(rec):
    out = _pick_common(rec)
    for f in ("name", "annual_fee_cents", "billing_period", "discount_pct", "included_cdt_codes"):
        out[f] = rec[f]
    return out


def serialize_membership(rec):
    out = _pick_common(rec)
    for f in ("patient_id", "membership_plan_id", "status", "enrolled_at",
              "period_start", "period_end", "paid_through_date", "balance_cents",
              "past_due_periods"):
        out[f] = rec[f]
    out["next_billing_date"] = advance_period(
        parse_date(rec["paid_through_date"]),
        db.membership_plans[rec["membership_plan_id"]]["billing_period"],
    ).isoformat()
    return out


# ----------------------------------------------------------------------------
# Calculations
# ----------------------------------------------------------------------------
def patient_balance(patient_id):
    total = 0
    for c in db.claims.values():
        if c["patient_id"] == patient_id and c["status"] in ("ADJUDICATED", "DENIED"):
            open_portion = c["final_patient_portion_cents"] - claim_patient_paid(c["id"])
            if open_portion > 0:
                total += open_portion
    for m in db.memberships.values():
        if m["patient_id"] == patient_id:
            total += m["balance_cents"]
    return total


def latest_verification(coverage_id):
    vers = [v for v in db.verifications.values() if v["coverage_id"] == coverage_id]
    if not vers:
        return None
    return max(vers, key=lambda v: v["_seq"])


def snapshot_for_coverage(coverage):
    """Benefit snapshot: latest verification if present, else the plan's configured values."""
    ver = latest_verification(coverage["id"])
    if ver is not None:
        return {
            "max": ver["verified_annual_maximum_cents"],
            "ded": ver["verified_deductible_cents"],
            "prev": ver["verified_preventive_pct"],
            "basic": ver["verified_basic_pct"],
            "major": ver["verified_major_pct"],
        }
    plan = db.insurance_plans[coverage["insurance_plan_id"]]
    return {
        "max": plan["annual_maximum_cents"],
        "ded": plan["deductible_cents"],
        "prev": plan["preventive_coinsurance_pct"],
        "basic": plan["basic_coinsurance_pct"],
        "major": plan["major_coinsurance_pct"],
    }


def benefit_estimate(procedures, snapshot, coverage, plan):
    remaining_max = snapshot["max"] - coverage["benefits_used_cents"]
    remaining_deductible = max(0, snapshot["ded"] - coverage["deductible_met_cents"])
    pct_map = {"PREVENTIVE": snapshot["prev"], "BASIC": snapshot["basic"], "MAJOR": snapshot["major"]}
    applies = plan["deductible_applies_to"]
    estimated = 0
    for line in procedures:
        proc = proc_by_code(line["cdt_code"])
        allowed = min(int(line["billed_fee_cents"]), proc["ucr_fee_cents"])
        pct = pct_map[proc["category"]]
        if proc["category"] in applies:
            d = min(remaining_deductible, allowed)
            remaining_deductible -= d
        else:
            d = 0
        line_benefit = round_half_up((allowed - d) * pct, 100)
        line_benefit = min(line_benefit, remaining_max)
        remaining_max -= line_benefit
        estimated += line_benefit
    return estimated


def proc_by_code(cdt_code):
    for p in db.procedures.values():
        if p["cdt_code"] == cdt_code:
            return p
    return None


def allowed_basis(procedures):
    total = 0
    for line in procedures:
        proc = proc_by_code(line["cdt_code"])
        total += min(int(line["billed_fee_cents"]), proc["ucr_fee_cents"])
    return total


def cob_secondary_benefit(claim, coverage, plan, normal_benefit):
    primary = db.claims[claim["primary_claim_id"]]
    primary_paid = primary["paid_insurance_cents"]
    basis = allowed_basis(claim["procedures"])
    patient_remaining = basis - primary_paid
    if plan["cob_method"] == "NON_DUPLICATION":
        return max(0, normal_benefit - primary_paid)
    return min(normal_benefit, patient_remaining)


# Instantiate the store now that all helpers (parse_iso, etc.) are defined.
db = Store()
