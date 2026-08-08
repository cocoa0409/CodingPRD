"""Core infrastructure: in-memory store, logical clock, errors, helpers, calculations."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# ----------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.4 / PRD)
# ----------------------------------------------------------------------------
SELF_PAY_DISCOUNT_PCT = Decimal("0.35")
SELF_PAY_MULTIPLIER = Decimal("1") - SELF_PAY_DISCOUNT_PCT  # 0.65
CLEANUP_BUFFER_MINUTES = 15
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

VALID_ROLES = {"PatientUser", "ProviderStaff", "PayerAnalyst", "Admin"}

# ----------------------------------------------------------------------------
# Error catalog (SCAFFOLD §1.6)
# ----------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_PROCEDURE_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_RATE_NOT_FOUND": 404,
    "ERR_BENEFIT_PLAN_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_ESTIMATE_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_PRIOR_AUTH_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_STALE_PATIENT_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_ESTIMATE_NOT_ACCEPTED": 409,
    "ERR_ESTIMATE_NO_LINES": 422,
    "ERR_ESTIMATE_TYPE_CONTRACT_MISMATCH": 422,
    "ERR_INVALID_ADJUSTMENT": 422,
    "ERR_PRIOR_AUTH_NOT_APPROVED": 409,
    "ERR_PRIOR_AUTH_EXPIRED": 409,
    "ERR_NO_NEGOTIATED_RATE": 422,
    "ERR_PROVIDER_UNAVAILABLE": 409,
    "ERR_ROOM_UNAVAILABLE": 409,
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
# In-memory store + logical clock
# ----------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.procedures = {}
        self.contracts = {}
        self.rates = {}
        self.plans = {}
        self.patients = {}
        self.providers = {}
        self.rooms = {}
        self.estimates = {}
        self.lines = {}
        self.prior_auths = {}
        self.appointments = {}
        self.disputes = {}
        self._seq = 0
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq


def now_dt():
    return db.clock


# ----------------------------------------------------------------------------
# Time helpers
# ----------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 datetime (accepting trailing Z) into aware UTC datetime."""
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
    """Render aware datetime as ISO 8601 UTC with three fractional digits and Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    return datetime.now(timezone.utc)


db = Store()


# ----------------------------------------------------------------------------
# Rounding
# ----------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to a whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# Id / request-id generation
# ----------------------------------------------------------------------------
def new_uuid():
    return str(uuid.uuid4())


def request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


# ----------------------------------------------------------------------------
# Record helpers
# ----------------------------------------------------------------------------
def stamp_new(rec):
    """Attach common system fields to a freshly created record."""
    ts = render_dt(db.clock)
    rec["id"] = new_uuid()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def bump(rec):
    """Register a mutation: advance version and updated_at from the logical clock."""
    rec["version"] += 1
    rec["updated_at"] = render_dt(db.clock)


def serialize(rec):
    """Public view of a record: drop private (underscore-prefixed) keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ----------------------------------------------------------------------------
def self_pay_price(gross_charge_cents):
    return round_half_up(Decimal(gross_charge_cents) * SELF_PAY_MULTIPLIER)


def rate_allowed(rate, procedure):
    """Allowed amount for a negotiated rate applied to a procedure."""
    if rate["rate_type"] == "FLAT":
        return rate["flat_amount_cents"]
    return round_half_up(Decimal(procedure["gross_charge_cents"]) * Decimal(str(rate["percent_of_charge"])))


def find_live_rate(contract_id, procedure_id):
    """The single non-superseded NegotiatedRate for (contract, procedure), or None."""
    for r in db.rates.values():
        if r["contract_id"] == contract_id and r["procedure_id"] == procedure_id and not r["superseded"]:
            return r
    return None


def lines_of(estimate_id):
    rows = [l for l in db.lines.values() if l["estimate_id"] == estimate_id]
    rows.sort(key=lambda l: l["line_number"])
    return rows


def price_lines_at_issue(est):
    """Stage 1: set each line's allowed_amount_cents and pinned rate (issue only)."""
    for line in lines_of(est["id"]):
        procedure = db.procedures[line["procedure_id"]]
        if est["estimate_type"] == "GFE_SELFPAY":
            line["allowed_amount_cents"] = self_pay_price(procedure["gross_charge_cents"])
            line["pinned_rate_id"] = None
            line["pinned_rate_version"] = None
        else:
            rate = find_live_rate(est["contract_id"], line["procedure_id"])
            line["allowed_amount_cents"] = rate_allowed(rate, procedure)
            line["pinned_rate_id"] = rate["id"]
            line["pinned_rate_version"] = rate["version"]


def aggregate_and_responsibility(est, basis):
    """Stages 2 & 3: deductible/coinsurance aggregation + patient-responsibility roll-up.

    Uses the patient's accumulators as they stand *now* (the variant's clock):
    ESTIMATE at issue, FINAL at settlement.
    """
    patient = db.patients[est["patient_id"]]
    plan = db.plans[patient["benefit_plan_id"]]
    lines = lines_of(est["id"])

    running_dm = patient["deductible_met_cents"]
    total_allowed = 0
    total_ded = 0
    total_coins = 0
    coins_rate = Decimal(str(plan["coinsurance_rate"]))
    for line in lines:
        allowed = line["allowed_amount_cents"]
        remaining_ded = max(0, plan["individual_deductible_cents"] - running_dm)
        d = min(allowed, remaining_ded)
        coins = round_half_up(Decimal(allowed - d) * coins_rate)
        line["deductible_applied_cents"] = d
        line["coinsurance_cents"] = coins
        line["line_patient_responsibility_cents"] = d + coins
        bump(line)
        running_dm += d
        total_allowed += allowed
        total_ded += d
        total_coins += coins

    est["allowed_amount_cents"] = total_allowed
    est["deductible_applied_cents"] = total_ded
    est["coinsurance_cents"] = total_coins

    if est["estimate_type"] == "GFE_SELFPAY":
        est["copay_cents"] = 0
        est["patient_responsibility_cents"] = total_allowed
        est["plan_paid_cents"] = 0
    else:
        copay = plan["copay_cents"]
        est["copay_cents"] = copay
        pre_oop = total_ded + total_coins + copay
        remaining_oop = max(0, plan["individual_oop_max_cents"] - patient["oop_met_cents"])
        pr = min(pre_oop, remaining_oop)
        est["patient_responsibility_cents"] = pr
        est["plan_paid_cents"] = total_allowed - pr

    est["responsibility_basis"] = basis


def cascade_recompute(patient_id, exclude_id=None):
    """Set recompute_required=true on every non-VOID estimate of the patient."""
    for e in db.estimates.values():
        if e["patient_id"] != patient_id:
            continue
        if e["status"] == "VOID":
            continue
        if exclude_id is not None and e["id"] == exclude_id:
            continue
        e["recompute_required"] = True
        bump(e)
