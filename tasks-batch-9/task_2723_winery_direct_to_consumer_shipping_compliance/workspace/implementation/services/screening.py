"""The screening ladder (PRD 2.9 / 3.6).

evaluate() returns the error_id of the FIRST -- that is, highest ranked --
failing rule, or None when every rule passes. Screening records what this
returns; label production raises the safety/permit/carrier band of it.
"""
import clock
from rounding import dec
from store import db, ordered
from services import permits, volume

OVERRIDABLE = (
    "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED",
    "ERR_WINERY_VOLUME_LIMIT_EXCEEDED",
    "ERR_ELEVATED_RISK_REVIEW_REQUIRED",
)

# the band label-time re-verification raises as genuine HTTP errors (PRD 3.7)
LABEL_BAND = (
    "ERR_STATE_DTC_PROHIBITED",
    "ERR_PROHIBITED_DESTINATION",
    "ERR_CONSUMER_UNDERAGE",
    "ERR_ID_VERIFICATION_REQUIRED",
    "ERR_PERMIT_MISSING_FOR_STATE",
    "ERR_PERMIT_NOT_ACTIVE",
    "ERR_PERMIT_EXPIRED",
    "ERR_CARRIER_NOT_ENROLLED",
    "ERR_ADULT_SIGNATURE_NOT_SUPPORTED",
)


def zip_blocked(state_rule, zip_value):
    """A block counts only once its effective_from has arrived (PRD 3.1)."""
    if state_rule is None:
        return False
    day = clock.today()
    for row in db.prohibited_zips.values():
        if row["state_rule_id"] != state_rule["id"]:
            continue
        if row["zip_code"] != zip_value:
            continue
        effective = clock.parse_date(row["effective_from"])
        if effective is None or effective <= day:
            return True
    return False


def approved_enrollments(winery_id, state_code):
    out = []
    for enrollment in ordered(list(db.carrier_enrollments.values())):
        if enrollment["winery_id"] != winery_id or enrollment["status"] != "APPROVED":
            continue
        program = db.carrier_programs.get(enrollment["carrier_program_id"])
        if program is None:
            continue
        if state_code not in (program.get("states_served") or []):
            continue
        out.append((enrollment, program))
    return out


def evaluate(order, band=None):
    """Walk the ladder in the fixed order of PRD 2.9. Returns error_id or None."""
    rule = volume.state_rule_for(order["ship_to_state_code"])
    consumer = db.consumers.get(order["consumer_id"])
    winery = db.wineries.get(order["winery_id"])

    def allowed(error_id):
        return band is None or error_id in band

    # 40
    if rule is not None and not rule["allows_dtc"] and allowed("ERR_STATE_DTC_PROHIBITED"):
        return "ERR_STATE_DTC_PROHIBITED"
    # 45
    if allowed("ERR_PROHIBITED_DESTINATION") and zip_blocked(rule, order["ship_to_zip"]):
        return "ERR_PROHIBITED_DESTINATION"
    # 50
    if allowed("ERR_CONSUMER_UNDERAGE") and consumer is not None and rule is not None:
        birth = clock.parse_date(consumer["birthdate"])
        if birth is not None:
            if clock.completed_years(birth, clock.today()) < rule["min_purchaser_age"]:
                return "ERR_CONSUMER_UNDERAGE"
    # 55
    if allowed("ERR_ID_VERIFICATION_REQUIRED") and consumer is not None:
        if not consumer.get("id_verified_at"):
            return "ERR_ID_VERIFICATION_REQUIRED"

    # 60 / 62 / 64 -- observing a lapse also performs ACTIVE -> EXPIRED
    permit = permits.select_permit(order["winery_id"], order["ship_to_state_code"])
    if permit is None:
        if allowed("ERR_PERMIT_MISSING_FOR_STATE"):
            return "ERR_PERMIT_MISSING_FOR_STATE"
    else:
        if permit["status"] not in ("ACTIVE", "EXPIRED") and allowed("ERR_PERMIT_NOT_ACTIVE"):
            return "ERR_PERMIT_NOT_ACTIVE"
        if not permits.covers_today(permit) and allowed("ERR_PERMIT_EXPIRED"):
            return "ERR_PERMIT_EXPIRED"

    # 70 / 72
    enrollments = approved_enrollments(order["winery_id"], order["ship_to_state_code"])
    if rule is not None and rule["requires_carrier_program"]:
        if not enrollments:
            if allowed("ERR_CARRIER_NOT_ENROLLED"):
                return "ERR_CARRIER_NOT_ENROLLED"
        elif order.get("adult_signature_required"):
            if not any(p.get("adult_signature_service_code") for _, p in enrollments):
                if allowed("ERR_ADULT_SIGNATURE_NOT_SUPPORTED"):
                    return "ERR_ADULT_SIGNATURE_NOT_SUPPORTED"

    # 80
    if allowed("ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED") and rule is not None:
        if not consumer_has_room(order, rule):
            return "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED"
    # 85
    if allowed("ERR_WINERY_VOLUME_LIMIT_EXCEEDED") and rule is not None:
        if not winery_has_room(order, rule):
            return "ERR_WINERY_VOLUME_LIMIT_EXCEEDED"
    # 95
    if allowed("ERR_ELEVATED_RISK_REVIEW_REQUIRED") and consumer is not None:
        if volume.consumer_derived(consumer)["screening_tier"] != "STANDARD":
            return "ERR_ELEVATED_RISK_REVIEW_REQUIRED"
    return None


def consumer_has_room(order, rule):
    """Rolling liters for the destination state, this order's own movements
    excluded, plus this order's total_liters, must be <= the state limit."""
    accumulated = volume.rolling_state_liters(
        order["consumer_id"], order["ship_to_state_code"], exclude_order_id=order["id"])
    projected = accumulated + dec(order["total_liters"])
    return projected <= dec(rule["per_consumer_limit_liters"])


def winery_has_room(order, rule):
    accumulated = volume.winery_annual_liters(
        order["winery_id"], order["ship_to_state_code"], exclude_order_id=order["id"])
    projected = accumulated + dec(order["total_liters"])
    return projected <= dec(rule["per_winery_annual_limit_liters"])
