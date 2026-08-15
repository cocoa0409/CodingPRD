"""Business logic: calculations of PRD 3.3-3.9, shared gates, and cascades."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from errors import ApiError
from timeutil import add_years, business_days_between, clock, parse_date, render_instant

# ------------------------------------------------------------------ constants
ROLES = ("FirmAdmin", "ClientUser", "Appraiser", "QCReviewer", "ComplianceOfficer")

CLIENT_TYPES = ("AMC", "DIRECT_LENDER", "PRIVATE")
LICENSE_LEVELS = ("TRAINEE", "LICENSED", "CERTIFIED_RESIDENTIAL")
PROPERTY_TYPES = ("SFR", "CONDO", "MULTI_2_4", "MANUFACTURED")
LOAN_TYPES = ("CONVENTIONAL", "FHA", "VA")
TIERS = ("STANDARD", "COMPLEX", "HIGH_VALUE")
REPORT_TYPES = ("FORM_1004", "FORM_1073", "FORM_1025")
CONDITION_RATINGS = ("C1", "C2", "C3", "C4", "C5", "C6")
REVISION_KINDS = ("CORRECTION", "RECONSIDERATION_OF_VALUE")
SNAPSHOT_TYPES = (
    "ORDER_FORM", "INSPECTION_NOTES", "COMP_DATA",
    "REPORT_PDF", "CERTIFICATION", "REVISION_CORRESPONDENCE",
)
ADJUSTMENT_KINDS = ("SURCHARGE", "WAIVER")
COMPLAINT_OUTCOMES = ("NO_ACTION", "SANCTIONED")

# Working states in which an appraiser "holds" an order (deactivation gate,
# selector load, sanction cascade).
WORKING_ORDER_STATES = (
    "ASSIGNED", "INSPECTION_SCHEDULED", "INSPECTED",
    "IN_ANALYSIS", "DRAFTING", "QC_REVIEW",
)
OPEN_COMPLAINT_STATES = ("RECEIVED", "RESPONSE_DRAFTED", "RESPONSE_SUBMITTED")

# fee_quote constants (SCAFFOLD 1.3).
FEE_FLOOR_CENTS = 35000
FEE_CAP_CENTS = 150000
RETAIL_RUSH_BPS = 1500
RETAIL_BASE_CENTS = {"STANDARD": 45000, "COMPLEX": 60000, "HIGH_VALUE": 85000}
RETAIL_REVISION_FEE_CENTS = 15000
HIGH_VALUE_THRESHOLD_CENTS = 100000000
MULTI_SURCHARGE_CENTS = 15000
MANUFACTURED_SURCHARGE_CENTS = 7500
GOVT_LOAN_SURCHARGE_CENTS = 5000

# comparable_adjustment / comp_eligibility constants.
ADJ_LINE_ROUND_CENTS = 10000
NET_ADJ_LIMIT_PCT = Decimal("15.00")
GROSS_ADJ_LIMIT_PCT = Decimal("25.00")
DISTANCE_LIMIT_MILES = Decimal("2.00")
SALE_RECENCY_DAYS = 365

# value_conclusion constants.
MIN_LOCKED_COMPS = 3
VALUE_ROUND_CENTS = 100000

# turn_time_scorecard constants.
MIN_COMPLETED_FOR_RATING = 4
PROBATION_THRESHOLD = Decimal("0.90")
SUSPENSION_THRESHOLD = Decimal("0.75")

# appointment buffer.
BUFFER_MINUTES = 30

ROV_WINDOW_DAYS = 90
RESPONSE_DUE_DAYS = 21
STANDARD_RETENTION_YEARS = 5
JUDICIAL_RETENTION_YEARS = 2


def _rhup(value):
    """Round a Decimal to an integer, halves away from zero."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _D(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ------------------------------------------------------------------ standing
def compute_standing(appraiser):
    """turn_time_scorecard's standing ladder (PRD 3.2)."""
    if appraiser["sanction_override"]:
        return "PANEL_SUSPENDED"
    completed = [
        o for o in store.orders.values()
        if o["assigned_appraiser_id"] == appraiser["id"]
        and o["first_delivered_at"] is not None
    ]
    completed_count = len(completed)
    if completed_count < MIN_COMPLETED_FOR_RATING:
        return "GOOD_STANDING"
    on_time = [o for o in completed if o["_first_delivered_dt"] <= o["_due_at_dt"]]
    rate = Decimal(_rhup(Decimal(len(on_time)) * 10000 / Decimal(completed_count))) / Decimal(10000)
    if rate < SUSPENSION_THRESHOLD:
        return "PANEL_SUSPENDED"
    if rate < PROBATION_THRESHOLD:
        return "PROBATION"
    return "GOOD_STANDING"


def on_time_rate(appraiser):
    completed = [
        o for o in store.orders.values()
        if o["assigned_appraiser_id"] == appraiser["id"]
        and o["first_delivered_at"] is not None
    ]
    if not completed:
        return None
    on_time = [o for o in completed if o["_first_delivered_dt"] <= o["_due_at_dt"]]
    return Decimal(_rhup(Decimal(len(on_time)) * 10000 / Decimal(len(completed)))) / Decimal(10000)


def inflight_count(appraiser_id):
    return sum(
        1 for o in store.orders.values()
        if o["assigned_appraiser_id"] == appraiser_id and o["status"] in WORKING_ORDER_STATES
    )


# ------------------------------------------------------------------ fee quote
def schedule_for(client_id, tier, as_of):
    """The (client, tier) window containing as_of: effective_from <= as_of and
    (effective_to IS NULL or as_of < effective_to)."""
    for sched in store.ordered(store.fee_schedules.values()):
        if sched["client_id"] != client_id or sched["complexity_tier"] != tier:
            continue
        if sched["_effective_from_dt"] <= as_of and (
            sched["_effective_to_dt"] is None or as_of < sched["_effective_to_dt"]
        ):
            return sched
    return None


def fee_quote(order, client, tier, as_of):
    """PRD 3.3: tiered pricing with rush premium, surcharges, floor and cap."""
    sched = schedule_for(client["id"], tier, as_of)
    base = sched["base_fee_cents"] if sched else RETAIL_BASE_CENTS[tier]
    rush_bps = sched["rush_multiplier_bps"] if sched else RETAIL_RUSH_BPS
    raw = base
    if order["requested_turn_days"] < client["default_turn_time_days"]:
        raw += _rhup(Decimal(base) * Decimal(rush_bps) / Decimal(10000))
    if order["property_type"] == "MULTI_2_4":
        raw += MULTI_SURCHARGE_CENTS
    elif order["property_type"] == "MANUFACTURED":
        raw += MANUFACTURED_SURCHARGE_CENTS
    if order["loan_type"] in ("FHA", "VA"):
        raw += GOVT_LOAN_SURCHARGE_CENTS
    return min(max(raw, FEE_FLOOR_CENTS), FEE_CAP_CENTS)


def revision_fee_for(order, client):
    """Revision fee from the (client, tier) schedule effective as-of the
    order's first_delivered_at; retail fallback 15000."""
    sched = schedule_for(client["id"], order["complexity_tier"], order["_first_delivered_dt"])
    return sched["revision_fee_cents"] if sched else RETAIL_REVISION_FEE_CENTS


# ------------------------------------------------------------------ tiers
def computed_tier(order):
    if order["estimated_value_cents"] >= HIGH_VALUE_THRESHOLD_CENTS:
        return "HIGH_VALUE"
    if order["property_type"] in ("MULTI_2_4", "MANUFACTURED"):
        return "COMPLEX"
    return "STANDARD"


_TIER_LEVEL = {"STANDARD": 0, "COMPLEX": 1, "HIGH_VALUE": 2}


def resolve_tier_override(order, override):
    """PRD 3.3: override must equal the computed tier or one level above it;
    HIGH_VALUE admits no override."""
    tier = computed_tier(order)
    if override is None:
        return tier
    if override == tier:
        return tier
    if _TIER_LEVEL[override] == _TIER_LEVEL[tier] + 1:
        return override
    raise ApiError("ERR_INVALID_TIER_OVERRIDE")


# ------------------------------------------------------------------ comps
def recompute_comp(comp):
    """comparable_adjustment (SCAFFOLD 1.3): per-line rounding FIRST, then sum.

    Each line is divided by 10000, rounded half-up to a whole number, and
    multiplied back by 10000.  For negative halves Decimal ROUND_HALF_UP rounds
    away from zero (e.g. -5000/10000 = -0.5 -> -1 -> -10000).
    """
    lines = [
        comp["site_adjustment_cents"],
        comp["gla_adjustment_cents"],
        comp["condition_adjustment_cents"],
        comp["other_adjustment_cents"],
    ]
    rounded = [
        _rhup(Decimal(v) / Decimal(ADJ_LINE_ROUND_CENTS)) * ADJ_LINE_ROUND_CENTS
        for v in lines
    ]
    net_sum = sum(rounded)
    gross_sum = sum(abs(v) for v in rounded)
    comp["adjusted_price_cents"] = comp["sale_price_cents"] + net_sum
    price = Decimal(comp["sale_price_cents"])
    net_pct = Decimal(_rhup(Decimal(abs(net_sum)) * 10000 / price)) / Decimal(100)
    gross_pct = Decimal(_rhup(Decimal(gross_sum) * 10000 / price)) / Decimal(100)
    comp["net_adjustment_pct"] = float(net_pct)
    comp["gross_adjustment_pct"] = float(gross_pct)
    comp["_net_pct_dec"] = net_pct
    comp["_gross_pct_dec"] = gross_pct


def evaluate_eligibility(comp):
    """comp_eligibility against the logical clock date; all bounds inclusive."""
    reasons = []
    if comp["_net_pct_dec"] > NET_ADJ_LIMIT_PCT:
        reasons.append("NET_ADJ_EXCEEDED")
    if comp["_gross_pct_dec"] > GROSS_ADJ_LIMIT_PCT:
        reasons.append("GROSS_ADJ_EXCEEDED")
    if _D(comp["distance_miles"]) > DISTANCE_LIMIT_MILES:
        reasons.append("DISTANCE_EXCEEDED")
    sale = comp["_sale_date_obj"]
    if sale is not None and sale < clock.today - timedelta(days=SALE_RECENCY_DAYS):
        reasons.append("SALE_TOO_OLD")
    comp["is_eligible"] = not reasons
    comp["ineligible_reasons"] = reasons


def locked_eligible_comps(order_id):
    return store.ordered(
        c for c in store.comparables.values()
        if c["order_id"] == order_id and c["status"] == "LOCKED" and c["is_eligible"]
    )


def value_conclusion(order_id):
    """PRD 3.6: distance-weighted mean of LOCKED eligible comps, single final
    round half-up to the nearest 100000 cents."""
    comps = locked_eligible_comps(order_id)
    if len(comps) < MIN_LOCKED_COMPS:
        raise ApiError("ERR_INSUFFICIENT_LOCKED_COMPS")
    num = Decimal(0)
    den = 0
    for comp in comps:
        dist = _D(comp["distance_miles"])
        weight = 3 if dist <= Decimal("0.50") else (2 if dist <= Decimal("1.00") else 1)
        num += Decimal(weight) * Decimal(comp["adjusted_price_cents"])
        den += weight
    raw = num / Decimal(den)
    return _rhup(raw / Decimal(VALUE_ROUND_CENTS)) * VALUE_ROUND_CENTS


# ------------------------------------------------------------------ retention
def compute_retention(order):
    """retention_expiry: standard pin first_delivered_at + 5y; judicial variant
    takes the max with the latest CLOSED_SANCTIONED close + 2y."""
    first = order.get("_first_delivered_dt")
    if first is None:
        return None
    base = add_years(first, STANDARD_RETENTION_YEARS)
    judicial = None
    for complaint in store.complaints.values():
        if complaint["order_id"] == order["id"] and complaint["status"] == "CLOSED_SANCTIONED":
            closed = complaint.get("_closed_dt")
            if closed is not None and (judicial is None or closed > judicial):
                judicial = closed
    if judicial is not None:
        base = max(base, add_years(judicial, JUDICIAL_RETENTION_YEARS))
    return base


def pin_retention(order):
    """Pin retention_until on every non-PURGED workfile record of the order."""
    retention = compute_retention(order)
    if retention is None:
        return
    for record in store.workfile_records.values():
        if record["order_id"] == order["id"] and record["status"] != "PURGED":
            record["retention_until"] = render_instant(retention)
            record["_retention_dt"] = retention
            store.touch(record)


# ------------------------------------------------------------------ workfiles
def file_workfile(order, snapshot_type):
    """Create a workfile record; records created after the first delivery
    inherit the order's pinned retention_until (PRD 3.8)."""
    fields = {
        "order_id": order["id"],
        "snapshot_type": snapshot_type,
        "recorded_at": store.now_string(),
        "retention_until": None,
        "status": "ACTIVE",
        "purged_at": None,
        "_retention_dt": None,
    }
    retention = compute_retention(order)
    if retention is not None:
        fields["retention_until"] = render_instant(retention)
        fields["_retention_dt"] = retention
    return store.new_row(store.workfile_records, **fields)


# ------------------------------------------------------------------ cascade
def cascade_unassign(order):
    """Sanction cascade link 2/3: order falls back to ACCEPTED, its PROPOSED
    and CONFIRMED appointments are cancelled."""
    order["assigned_appraiser_id"] = None
    order["requires_supervisor_cosign"] = False
    order["status"] = "ACCEPTED"
    store.touch(order)
    for appt in store.appointments.values():
        if appt["order_id"] == order["id"] and appt["status"] in ("PROPOSED", "CONFIRMED"):
            appt["status"] = "CANCELLED"
            store.touch(appt)


# ------------------------------------------------------------------ validation helpers
def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % name)


def optional_fields(body, names):
    for name in names:
        if name in body and body[name] is None:
            raise ApiError("ERR_VALIDATION", "Field %s may not be null." % name)


def require_string(body, name, allow_blank=False):
    value = body.get(name)
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string." % name)
    return value


def optional_string(body, name):
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string." % name)
    return value


def require_enum(body, name, choices):
    value = body.get(name)
    if value not in choices:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s." % (name, list(choices)))
    return value


def require_int(body, name, minimum=None, maximum=None, strictly_positive=False):
    value = body.get(name)
    if not _is_int(value):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer." % name)
    if strictly_positive and value <= 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be positive." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "Field %s is above its maximum." % name)
    return value


def require_number(body, name, minimum=None):
    value = body.get(name)
    if not _is_num(value):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number." % name)
    if minimum is not None and _D(value) < _D(minimum):
        raise ApiError("ERR_VALIDATION", "Field %s is below its minimum." % name)
    return value


def require_bool(body, name):
    value = body.get(name)
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", "Field %s must be a boolean." % name)
    return value


def require_instant(body, name):
    value = body.get(name)
    from timeutil import is_iso_instant
    if not is_iso_instant(value):
        raise ApiError("ERR_VALIDATION", "Field %s must be an ISO-8601 timestamp." % name)
    return value


def require_date(body, name):
    from timeutil import is_date_string
    value = body.get(name)
    if not is_date_string(value):
        raise ApiError("ERR_VALIDATION", "Field %s must be a YYYY-MM-DD date." % name)
    return value


# ------------------------------------------------------------------ 404 lookups
def get_client(client_id):
    row = store.clients.get(client_id)
    if row is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    return row


def get_appraiser(appraiser_id):
    row = store.appraisers.get(appraiser_id)
    if row is None:
        raise ApiError("ERR_APPRAISER_NOT_FOUND")
    return row


def get_order(order_id):
    row = store.orders.get(order_id)
    if row is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    return row


def get_appointment(appt_id):
    row = store.appointments.get(appt_id)
    if row is None:
        raise ApiError("ERR_APPOINTMENT_NOT_FOUND")
    return row


def get_comparable(comp_id):
    row = store.comparables.get(comp_id)
    if row is None:
        raise ApiError("ERR_COMPARABLE_NOT_FOUND")
    return row


def get_report(report_id):
    row = store.reports.get(report_id)
    if row is None:
        raise ApiError("ERR_REPORT_NOT_FOUND")
    return row


def get_revision_request(req_id):
    row = store.revision_requests.get(req_id)
    if row is None:
        raise ApiError("ERR_REVISION_REQUEST_NOT_FOUND")
    return row


def get_workfile(record_id):
    row = store.workfile_records.get(record_id)
    if row is None:
        raise ApiError("ERR_WORKFILE_NOT_FOUND")
    return row


def get_complaint(complaint_id):
    row = store.complaints.get(complaint_id)
    if row is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND")
    return row


def get_membership(membership_id):
    row = store.panel_memberships.get(membership_id)
    if row is None:
        raise ApiError("ERR_PANEL_MEMBERSHIP_NOT_FOUND")
    return row


def get_fee_schedule(schedule_id):
    row = store.fee_schedules.get(schedule_id)
    if row is None:
        raise ApiError("ERR_FEE_SCHEDULE_NOT_FOUND")
    return row


def report_for_order(order_id):
    for report in store.reports.values():
        if report["order_id"] == order_id:
            return report
    return None


def parse_date_field(value):
    return parse_date(value) if isinstance(value, str) else None
