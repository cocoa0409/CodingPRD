"""Domain core: constants, calculations (PRD section 3 / calculation rules),
cascade helpers and serialisation."""

import calendar
import copy
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db, new_id, next_seq
from errors import err
from response import iso_ms

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

FAITH_TRADITIONS = ("CATHOLIC", "ORTHODOX", "PROTESTANT", "JEWISH", "MUSLIM", "INTERFAITH")
DEPARTURE_STATUSES = ("PLANNING", "OPEN_FOR_SALE", "SALES_CLOSED", "OPERATED", "CANCELLED")
RISK_POSTURES = ("OPEN", "WATCH", "RESTRICTED", "SUSPENDED")
COMMISSION_MODES = ("PER_PAX_CASH", "FREE_SEAT_CREDIT", "HYBRID")
ACCRUAL_BASES = ("RECRUITED", "TRAVELED")
AGREEMENT_STATUSES = ("PENDING_COUNTERSIGN", "ACTIVE", "TERMINATED", "SETTLED")
ROOM_TYPES = ("SINGLE", "DOUBLE", "TWIN")
MOBILITY_CODES = ("NONE", "CANE", "WALKER", "WHEELCHAIR")
DIETARY_CODES = ("NONE", "VEGETARIAN", "GLUTEN_FREE", "KOSHER", "HALAL", "DIABETIC", "LOW_SODIUM")
BOOKING_STATUSES = ("INQUIRY", "DEPOSITED", "CONFIRMED", "CANCELLED")
PAYMENT_STATUSES = ("UNPAID", "DEPOSIT_PAID", "PLAN_ACTIVE", "PAID_IN_FULL", "IN_DEFAULT", "REFUNDED")
PROTECTION_STATUSES = ("NONE", "QUOTED", "MEDICAL_REVIEWED", "WAIVER_APPROVED",
                       "WAIVER_DECLINED", "PURCHASED", "VOIDED")
DEVIATION_TYPES = ("NONE", "ORIGIN_CHANGE", "DATE_DEVIATION", "CLASS_UPGRADE")
PLAN_TYPES = ("SINGLE_BALANCE", "MONTHLY_3", "MONTHLY_6")
PLAN_STATUSES = ("ACTIVE", "COMPLETED", "DEFAULTED", "SUPERSEDED")
INSTALLMENT_STATUSES = ("SCHEDULED", "PARTIALLY_PAID", "PAID", "PAST_DUE", "WAIVED")
PAYMENT_METHODS = ("CARD", "ACH", "CHECK", "PARISH_TRANSFER")
PAYMENT_ROW_STATUSES = ("APPLIED", "REVERSED")
AIR_BLOCK_STATUSES = ("DRAFT", "OFFERED", "COUNTERED", "CONFIRMED", "RELEASED", "EXPIRED")
NEGOTIATION_PARTIES = ("CARRIER_OFFER", "OPERATOR_COUNTER")
ACCESS_REGIMES = ("OPEN_ACCESS", "PERMIT_REQUIRED", "TICKETED_SLOT")
SERVICE_TYPES = ("MASS", "LITURGY", "PRAYER_SERVICE", "GUIDED_VISIT")
SERVICE_BOOKING_STATUSES = ("SITE_HELD", "CLERGY_CONFIRMED", "CONFIRMED", "CANCELLED")
RESOURCE_TYPES = ("HOTEL_ROOM_BLOCK", "MOTORCOACH", "GUIDE")
LAND_ASSIGNMENT_STATUSES = ("DRAFT", "COUNTERSIGNED", "TERMINATED")
PROTECTION_PLAN_CODES = ("BASIC", "STANDARD", "PREMIER")
PROTECTION_ROW_STATUSES = ("QUOTED", "MEDICAL_REVIEWED", "WAIVER_APPROVED", "WAIVER_DECLINED",
                           "PURCHASED", "VOIDED")
AGE_BANDS = ("A", "B", "C", "D")
ADVISORY_LEVELS = ("NORMAL", "EXERCISE_CAUTION", "RECONSIDER", "DO_NOT_TRAVEL")
ADVISORY_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")
WAIVER_DECISIONS = ("APPROVE", "DECLINE")

# ---------------------------------------------------------------------------
# Named constants (PRD section 2.6 / section 6)
# ---------------------------------------------------------------------------

BP_DENOMINATOR = 10000
FX_DENOMINATOR = 10000

GRANT_TIER_2_FLOOR_CENTS = 500000
GRANT_TIER_2_BP = 500
GRANT_TIER_1_FLOOR_CENTS = 300000
GRANT_TIER_1_BP = 300
SERVICE_FEE_BP = 350

AGE_BAND_BP = {"A": 400, "B": 620, "C": 910, "D": 1280}
MEDICAL_UPLIFT_THRESHOLD_CENTS = 5000000
MEDICAL_UPLIFT_BP = 1500
WAIVER_SURCHARGE_BP = 2200
WAIVER_SURCHARGE_CAP_CENTS = 45000
WAIVER_STABLE_PERIOD_MIN_DAYS = 60
WAIVER_PURCHASE_WINDOW_DAYS = 21

DEVIATION_ORIGIN_CHANGE_FEE_CENTS = 12500
DEVIATION_DATE_FEE_CENTS = 9000
DEVIATION_UPGRADE_BP = 4500
DEVIATION_LATE_WINDOW_DAYS = 30
DEVIATION_LATE_MULTIPLIER_BP = 15000
DEVIATION_NORMAL_MULTIPLIER_BP = 10000

SENIOR_PROTECTION_AGE = 70
DIETARY_LEAD_TIME_MIN_DAYS = 21
PLAN_DEFAULT_PAST_DUE_COUNT = 2

ROOM_CAPACITY = {"SINGLE": 1, "DOUBLE": 2, "TWIN": 2}
INSTALLMENT_COUNT = {"SINGLE_BALANCE": 1, "MONTHLY_3": 3, "MONTHLY_6": 6}

ADVISORY_LEVEL_RANK = {"NORMAL": 0, "EXERCISE_CAUTION": 1, "RECONSIDER": 2, "DO_NOT_TRAVEL": 3}
ADVISORY_LEVEL_POSTURE = {
    "NORMAL": "OPEN",
    "EXERCISE_CAUTION": "WATCH",
    "RECONSIDER": "RESTRICTED",
    "DO_NOT_TRAVEL": "SUSPENDED",
}

DIETARY_LEAD_TIME_CODES = ("KOSHER", "HALAL")
GROUND_FLOOR_MOBILITY_CODES = ("WHEELCHAIR", "WALKER")

# ---------------------------------------------------------------------------
# Clock, time and money primitives
# ---------------------------------------------------------------------------


def clock_now():
    return db.clock


def clock_date():
    return db.clock.date()


def real_now_iso():
    return iso_ms(datetime.now(timezone.utc))


def as_date(value):
    if value is None:
        return None
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def as_dt(value):
    if value is None:
        return None
    return datetime(
        int(value[0:4]), int(value[5:7]), int(value[8:10]),
        int(value[11:13]), int(value[14:16]), int(value[17:19]),
        int(value[20:23]) * 1000 if len(value) > 20 and value[19] == "." else 0,
        tzinfo=timezone.utc,
    )


def date_str(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def whole_days(later, earlier):
    """Whole days between two UTC calendar dates."""
    return (later - earlier).days


def round_half_up(numerator, denominator=1):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bp(amount_cents, bp):
    return round_half_up(amount_cents * bp, BP_DENOMINATOR)


def add_months(base, months):
    """Same day-of-month, clamped to the shorter month's last day."""
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(base.day, last_day))


def complete_years(born, on_day):
    years = on_day.year - born.year
    if (on_day.month, on_day.day) < (born.month, born.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Row bookkeeping
# ---------------------------------------------------------------------------


def base_row(with_version=True):
    row = {"id": new_id()}
    row["_seq"] = next_seq()
    row["created_at"] = real_now_iso()
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = real_now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1


def snap(row):
    return copy.deepcopy({k: v for k, v in row.items()
                          if not k.startswith("_") and k not in ("updated_at", "version")})


def touch_if_changed(row, before):
    if snap(row) != before:
        touch(row)


def order_rows(rows):
    """Default ordering: created_at ascending, insertion sequence as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def order_rows_desc(rows):
    return list(reversed(order_rows(rows)))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def program_of(departure):
    return db.programs[departure["program_id"]]


def departure_of(row):
    return db.departures[row["departure_id"]]


def pilgrims_of_departure(departure_id):
    return order_rows([p for p in db.pilgrims.values() if p["departure_id"] == departure_id])


def pilgrims_of_agreement(agreement_id):
    return order_rows([p for p in db.pilgrims.values()
                       if p["recruited_by_agreement_id"] == agreement_id])


def plans_of_pilgrim(pilgrim_id):
    return order_rows([pl for pl in db.payment_plans.values() if pl["pilgrim_id"] == pilgrim_id])


def active_plan_of(pilgrim_id):
    for plan in plans_of_pilgrim(pilgrim_id):
        if plan["status"] == "ACTIVE":
            return plan
    return None


def protections_of_pilgrim(pilgrim_id):
    return order_rows([tp for tp in db.protections.values() if tp["pilgrim_id"] == pilgrim_id])


def air_blocks_of_departure(departure_id):
    return order_rows([ab for ab in db.air_blocks.values() if ab["departure_id"] == departure_id])


def confirmed_air_block(departure_id):
    for block in air_blocks_of_departure(departure_id):
        if block["status"] == "CONFIRMED":
            return block
    return None


def service_bookings_of_departure(departure_id):
    return order_rows([sb for sb in db.service_bookings.values()
                       if sb["departure_id"] == departure_id])


def land_assignments_of_departure(departure_id):
    return order_rows([la for la in db.land_assignments.values()
                       if la["departure_id"] == departure_id])


def agreements_of_departure(departure_id):
    return order_rows([a for a in db.agreements.values() if a["departure_id"] == departure_id])


# ---------------------------------------------------------------------------
# Calculation: departure_group_size_tier
# ---------------------------------------------------------------------------


def select_tier(program, pax):
    for tier in program["price_tiers"]:
        if tier["min_pax"] <= pax <= tier["max_pax"]:
            return tier
    return None


def provisional_pax(departure):
    return len([p for p in db.pilgrims.values()
                if p["departure_id"] == departure["id"]
                and p["is_paying"]
                and p["booking_status"] in ("DEPOSITED", "CONFIRMED")])


def final_pax(departure):
    return len([p for p in db.pilgrims.values()
                if p["departure_id"] == departure["id"]
                and p["is_paying"]
                and p["booking_status"] == "CONFIRMED"
                and p["payment_status"] == "PAID_IN_FULL"])


def recompute_paying_pax_count(departure):
    departure["paying_pax_count"] = provisional_pax(departure)


def recompute_provisional_tier(departure):
    """Provisional variant: floors the head-count at one before tier selection."""
    program = program_of(departure)
    count = provisional_pax(departure)
    departure["paying_pax_count"] = count
    effective = max(1, count)
    tier = select_tier(program, effective)
    if tier is None:
        err("ERR_NO_APPLICABLE_PRICE_TIER",
            "No price tier covers a group size of %d." % effective)
    departure["provisional_tier_code"] = tier["tier_code"]
    departure["provisional_per_pax_price_cents"] = tier["per_pax_price_cents"]
    departure["provisional_single_supplement_cents"] = tier["single_supplement_cents"]
    departure["provisional_deposit_cents"] = tier["deposit_cents"]


def compute_final_tier(departure):
    """Final variant: no floor.  Returns (count, tier or None)."""
    program = program_of(departure)
    count = final_pax(departure)
    return count, select_tier(program, count)


# ---------------------------------------------------------------------------
# Calculation: leader_benefit_accrual
# ---------------------------------------------------------------------------


def free_seats_granted(agreement):
    return len([p for p in db.pilgrims.values()
                if p["recruited_by_agreement_id"] == agreement["id"]
                and not p["is_paying"]
                and p["booking_status"] != "CANCELLED"])


def _accrual_values(agreement, recruited, per_pax_price_cents):
    earned = recruited // agreement["free_travel_threshold"]
    free_seat_value = earned * per_pax_price_cents
    gross = recruited * agreement["commission_rate_cents_per_pax"]
    mode = agreement["commission_mode"]
    if mode == "PER_PAX_CASH":
        commission = gross
    elif mode == "FREE_SEAT_CREDIT":
        commission = 0
    else:  # HYBRID
        commission = max(0, gross - free_seat_value)
    return recruited, earned, commission


def recompute_accrual_snapshot(agreement):
    """Snapshot variant: DEPOSITED or CONFIRMED, at the provisional price."""
    departure = db.departures.get(agreement["departure_id"])
    per_pax = departure["provisional_per_pax_price_cents"] if departure else 0
    recruited = len([p for p in db.pilgrims.values()
                     if p["recruited_by_agreement_id"] == agreement["id"]
                     and p["is_paying"]
                     and p["booking_status"] in ("DEPOSITED", "CONFIRMED")])
    recruited, earned, commission = _accrual_values(agreement, recruited, per_pax)
    agreement["recruited_paying_count"] = recruited
    agreement["earned_free_seats"] = earned
    agreement["commission_payable_cents"] = commission
    agreement["free_seats_granted_count"] = free_seats_granted(agreement)


def recompute_accrual_settlement(agreement):
    """Settlement variant: CONFIRMED and PAID_IN_FULL, at the final price."""
    departure = db.departures.get(agreement["departure_id"])
    per_pax = departure["final_per_pax_price_cents"] if departure else 0
    recruited = len([p for p in db.pilgrims.values()
                     if p["recruited_by_agreement_id"] == agreement["id"]
                     and p["is_paying"]
                     and p["booking_status"] == "CONFIRMED"
                     and p["payment_status"] == "PAID_IN_FULL"])
    recruited, earned, commission = _accrual_values(agreement, recruited, per_pax)
    agreement["settled_recruited_count"] = recruited
    agreement["settled_earned_free_seats"] = earned
    agreement["settled_commission_cents"] = commission
    agreement["free_seats_granted_count"] = free_seats_granted(agreement)


def refresh_recruiting_agreement(pilgrim, variant="snapshot"):
    agreement_id = pilgrim.get("recruited_by_agreement_id")
    if not agreement_id:
        return None
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        return None
    before = snap(agreement)
    if variant == "snapshot":
        recompute_accrual_snapshot(agreement)
    else:
        recompute_accrual_settlement(agreement)
    touch_if_changed(agreement, before)
    return agreement


# ---------------------------------------------------------------------------
# Calculation: pilgrim_invoice_total
# ---------------------------------------------------------------------------


def recompute_invoice(pilgrim):
    departure = departure_of(pilgrim)
    locked = pilgrim["price_locked_cents"]
    effective = locked if locked is not None else departure["provisional_per_pax_price_cents"]
    gross = effective + pilgrim["single_supplement_applied_cents"] + pilgrim["deviation_fee_cents"]
    if gross >= GRANT_TIER_2_FLOOR_CENTS:
        grant_bp = GRANT_TIER_2_BP
    elif gross >= GRANT_TIER_1_FLOOR_CENTS:
        grant_bp = GRANT_TIER_1_BP
    else:
        grant_bp = 0
    grant = apply_bp(gross, grant_bp)
    net = gross - grant
    service_fee = apply_bp(net, SERVICE_FEE_BP)
    pilgrim["invoice_total_cents"] = net + service_fee
    return pilgrim["invoice_total_cents"]


# ---------------------------------------------------------------------------
# Calculation: departure_land_cost_rollup
# ---------------------------------------------------------------------------


def land_line_amounts(resource, date_from, date_to, units_requested):
    days = whole_days(date_to, date_from) + 1
    line_local = units_requested * days * resource["unit_rate_local_cents"]
    line_usd = round_half_up(line_local * resource["fx_rate_bp"], FX_DENOMINATOR)
    return days, line_local, line_usd


def recompute_land_rollup(departure, touch_departure=True):
    lines = [la for la in db.land_assignments.values()
             if la["departure_id"] == departure["id"] and la["status"] == "COUNTERSIGNED"]
    lines.sort(key=lambda la: (la["date_from"], la["created_at"], la["_seq"]))
    before = snap(departure)
    departure["land_cost_total_cents"] = sum(la["line_usd_cents"] for la in lines)
    if touch_departure:
        touch_if_changed(departure, before)


# ---------------------------------------------------------------------------
# Calculation: protection_premium / waiver_eligibility
# ---------------------------------------------------------------------------


def age_band_for(age):
    if age >= 75:
        return "D"
    if age >= 65:
        return "C"
    if age >= 40:
        return "B"
    return "A"


def recompute_waiver_eligibility(protection):
    if protection["deposit_reference_date"] is None:
        protection["waiver_eligible"] = False
        return False
    days = whole_days(clock_date(), as_date(protection["deposit_reference_date"]))
    protection["waiver_eligible"] = bool(
        protection["questionnaire_complete"]
        and protection["stable_period_days"] >= WAIVER_STABLE_PERIOD_MIN_DAYS
        and days <= WAIVER_PURCHASE_WINDOW_DAYS
    )
    return protection["waiver_eligible"]


def recompute_premium(protection):
    pilgrim = db.pilgrims[protection["pilgrim_id"]]
    cost = pilgrim["invoice_total_cents"]
    protection["insured_trip_cost_cents"] = cost
    band = age_band_for(pilgrim["age_at_departure"])
    protection["age_band"] = band
    base = apply_bp(cost, AGE_BAND_BP[band])
    protection["base_premium_cents"] = base
    if protection["medical_limit_cents"] > MEDICAL_UPLIFT_THRESHOLD_CENTS:
        uplift = apply_bp(base, MEDICAL_UPLIFT_BP)
    else:
        uplift = 0
    protection["medical_uplift_cents"] = uplift
    if (protection["pre_existing_waiver_requested"]
            and protection["waiver_eligible"]
            and pilgrim["protection_status"] != "WAIVER_DECLINED"):
        surcharge = min(apply_bp(base, WAIVER_SURCHARGE_BP), WAIVER_SURCHARGE_CAP_CENTS)
    else:
        surcharge = 0
    protection["waiver_surcharge_cents"] = surcharge
    protection["premium_cents"] = base + uplift + surcharge
    return protection["premium_cents"]


def requote_quoted_protections(pilgrim):
    for protection in protections_of_pilgrim(pilgrim["id"]):
        if protection["status"] != "QUOTED":
            continue
        before = snap(protection)
        recompute_waiver_eligibility(protection)
        recompute_premium(protection)
        touch_if_changed(protection, before)


# ---------------------------------------------------------------------------
# Calculation: air_deviation_fee
# ---------------------------------------------------------------------------


def deviation_fee(departure, block, deviation_type):
    if deviation_type == "ORIGIN_CHANGE":
        base = DEVIATION_ORIGIN_CHANGE_FEE_CENTS
    elif deviation_type == "DATE_DEVIATION":
        base = DEVIATION_DATE_FEE_CENTS
    elif deviation_type == "CLASS_UPGRADE":
        contracted = block["contracted_fare_cents"] or 0
        base = apply_bp(contracted, DEVIATION_UPGRADE_BP)
    else:
        return 0
    days_to_departure = whole_days(as_date(departure["departure_date"]), clock_date())
    multiplier = (DEVIATION_LATE_MULTIPLIER_BP
                  if days_to_departure <= DEVIATION_LATE_WINDOW_DAYS
                  else DEVIATION_NORMAL_MULTIPLIER_BP)
    return apply_bp(base, multiplier)


# ---------------------------------------------------------------------------
# Calculation: payment_plan_schedule
# ---------------------------------------------------------------------------


def build_installments(plan_type, first_due_date, total_cents):
    count = INSTALLMENT_COUNT[plan_type]
    base = total_cents // count
    remainder = total_cents - base * count
    installments = []
    for i in range(1, count + 1):
        amount = base + (1 if i <= remainder else 0)
        installments.append({
            "sequence_no": i,
            "due_date": date_str(add_months(first_due_date, i - 1)),
            "amount_due_cents": amount,
            "amount_paid_cents": 0,
            "status": "SCHEDULED",
        })
    return installments


# ---------------------------------------------------------------------------
# Calculation: payment_waterfall_allocation
# ---------------------------------------------------------------------------


def _derive_payment_status_without_plan(pilgrim):
    departure = departure_of(pilgrim)
    if pilgrim["cash_applied_cents"] >= pilgrim["invoice_total_cents"]:
        return "PAID_IN_FULL"
    if pilgrim["cash_applied_cents"] >= departure["provisional_deposit_cents"]:
        return "DEPOSIT_PAID"
    return "UNPAID"


def refresh_past_due_count(plan):
    plan["past_due_count"] = len([i for i in plan["installments"] if i["status"] == "PAST_DUE"])


def rederive_payment_status_after_reversal(pilgrim):
    """PRD section 3.7: PAID_IN_FULL only while every installment is PAID;
    otherwise PLAN_ACTIVE when an ACTIVE plan exists; otherwise DEPOSIT_PAID
    when the applied cash still reaches the provisional deposit; otherwise
    UNPAID."""
    plans = [pl for pl in plans_of_pilgrim(pilgrim["id"]) if pl["status"] != "SUPERSEDED"]
    for plan in plans:
        if plan["installments"] and all(i["status"] == "PAID" for i in plan["installments"]):
            pilgrim["payment_status"] = "PAID_IN_FULL"
            return
    if any(pl["status"] == "ACTIVE" for pl in plans):
        pilgrim["payment_status"] = "PLAN_ACTIVE"
        return
    departure = departure_of(pilgrim)
    if pilgrim["cash_applied_cents"] >= departure["provisional_deposit_cents"]:
        pilgrim["payment_status"] = "DEPOSIT_PAID"
        return
    pilgrim["payment_status"] = "UNPAID"


def allocate_cash(pilgrim, amount):
    """The waterfall.  Returns (allocation, plan_ids) where plan_ids parallels
    allocation and records which plan each installment entry belongs to."""
    allocation = []
    plan_ids = []
    plan = active_plan_of(pilgrim["id"])
    if plan is None:
        pilgrim["credit_balance_cents"] = pilgrim["credit_balance_cents"] + amount
        allocation.append({"target": "CREDIT", "sequence_no": None, "amount_cents": amount})
        plan_ids.append(None)
        pilgrim["payment_status"] = _derive_payment_status_without_plan(pilgrim)
        return allocation, plan_ids

    plan_before = snap(plan)
    remaining = amount
    fundable = [i for i in plan["installments"]
                if i["status"] in ("SCHEDULED", "PARTIALLY_PAID", "PAST_DUE")]
    fundable.sort(key=lambda i: (i["due_date"], i["sequence_no"]))
    for installment in fundable:
        if remaining <= 0:
            break
        need = installment["amount_due_cents"] - installment["amount_paid_cents"]
        if need <= 0:
            installment["status"] = "PAID"
            continue
        take = min(need, remaining)
        installment["amount_paid_cents"] += take
        remaining -= take
        if installment["amount_paid_cents"] >= installment["amount_due_cents"]:
            installment["status"] = "PAID"
        else:
            installment["status"] = "PARTIALLY_PAID"
        allocation.append({"target": "INSTALLMENT",
                           "sequence_no": installment["sequence_no"],
                           "amount_cents": take})
        plan_ids.append(plan["id"])
    if remaining > 0:
        pilgrim["credit_balance_cents"] = pilgrim["credit_balance_cents"] + remaining
        allocation.append({"target": "CREDIT", "sequence_no": None, "amount_cents": remaining})
        plan_ids.append(None)
    refresh_past_due_count(plan)
    if all(i["status"] == "PAID" for i in plan["installments"]):
        plan["status"] = "COMPLETED"
        pilgrim["payment_status"] = "PAID_IN_FULL"
    else:
        pilgrim["payment_status"] = "PLAN_ACTIVE"
    touch_if_changed(plan, plan_before)
    return allocation, plan_ids


# ---------------------------------------------------------------------------
# Calculation: departure_risk_posture
# ---------------------------------------------------------------------------


def governing_advisory_for_country(country):
    candidates = [a for a in db.advisories.values()
                  if a["country"] == country
                  and a["status"] == "PUBLISHED"
                  and as_dt(a["effective_from"]) <= clock_now()]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (ADVISORY_LEVEL_RANK[a["level"]],
                                   a["effective_from"],
                                   a["created_at"],
                                   a["_seq"]))
    return candidates[-1]


def refresh_posture(departure):
    """Re-read the governing advisory.  Silent: this is a projection, not a
    mutation, so it never bumps updated_at or version by itself."""
    program = program_of(departure)
    advisory = governing_advisory_for_country(program["destination_country"])
    if advisory is None:
        departure["risk_posture"] = "OPEN"
        departure["governing_advisory_id"] = None
        return
    departure["risk_posture"] = ADVISORY_LEVEL_POSTURE[advisory["level"]]
    departure["governing_advisory_id"] = None if advisory["level"] == "NORMAL" else advisory["id"]


# ---------------------------------------------------------------------------
# Calculation: site_capacity_conservation helpers
# ---------------------------------------------------------------------------

OCCUPYING_SERVICE_STATUSES = ("SITE_HELD", "CLERGY_CONFIRMED", "CONFIRMED")


def site_occupied_pax(site_id, day, exclude_id=None):
    total = 0
    for booking in db.service_bookings.values():
        if booking["sacred_site_id"] != site_id:
            continue
        if booking["status"] not in OCCUPYING_SERVICE_STATUSES:
            continue
        if exclude_id is not None and booking["id"] == exclude_id:
            continue
        if as_dt(booking["scheduled_start_utc"]).date() != day:
            continue
        total += booking["pax_count"]
    return total


def recompute_service_coverage(departure, touch_departure=True):
    bookings = service_bookings_of_departure(departure["id"])
    live = [b for b in bookings if b["status"] != "CANCELLED"]
    risk_cancelled = any(b["status"] == "CANCELLED" and b["cancelled_by_risk"] for b in bookings)
    before = snap(departure)
    departure["service_coverage_ok"] = bool(
        live and all(b["status"] == "CONFIRMED" for b in live) and not risk_cancelled)
    if touch_departure:
        touch_if_changed(departure, before)


# ---------------------------------------------------------------------------
# Derived air-block seat usage
# ---------------------------------------------------------------------------


def seats_assigned_for(departure_id):
    return len([p for p in db.pilgrims.values()
                if p["departure_id"] == departure_id
                and p["ticketed_name"] is not None
                and p["booking_status"] in ("DEPOSITED", "CONFIRMED")])


# ---------------------------------------------------------------------------
# Calculation: pilgrim_cancellation_settlement + cancellation cascade
# ---------------------------------------------------------------------------


def cancellation_penalty_bp(departure, program, force_zero=False):
    days_before = whole_days(as_date(departure["departure_date"]), clock_date())
    bucket = None
    for item in program["cancellation_grid"]:
        if days_before >= item["min_days_before"]:
            if bucket is None or item["min_days_before"] > bucket["min_days_before"]:
                bucket = item
    penalty_bp = bucket["penalty_bp"] if bucket is not None else 0
    if departure["risk_posture"] == "SUSPENDED":
        penalty_bp = 0
    if force_zero:
        penalty_bp = 0
    return penalty_bp


def unpair_roommate(pilgrim):
    partner_id = pilgrim.get("roommate_pilgrim_id")
    pilgrim["roommate_pilgrim_id"] = None
    if not partner_id:
        return
    partner = db.pilgrims.get(partner_id)
    if partner is None:
        return
    before = snap(partner)
    if partner.get("roommate_pilgrim_id") == pilgrim["id"]:
        partner["roommate_pilgrim_id"] = None
    departure = departure_of(partner)
    if partner["room_type_assigned"] == "SINGLE":
        partner["single_supplement_applied_cents"] = departure["provisional_single_supplement_cents"]
    else:
        partner["single_supplement_applied_cents"] = 0
    recompute_invoice(partner)
    touch_if_changed(partner, before)


def supersede_plans_on_cancel(pilgrim):
    for plan in plans_of_pilgrim(pilgrim["id"]):
        if plan["status"] != "ACTIVE":
            continue
        before = snap(plan)
        plan["status"] = "SUPERSEDED"
        for installment in plan["installments"]:
            if installment["status"] in ("SCHEDULED", "PARTIALLY_PAID", "PAST_DUE"):
                installment["status"] = "WAIVED"
        refresh_past_due_count(plan)
        touch_if_changed(plan, before)


def void_protections_on_cancel(pilgrim):
    voided = False
    for protection in protections_of_pilgrim(pilgrim["id"]):
        if protection["status"] in ("PURCHASED", "VOIDED"):
            continue
        before = snap(protection)
        protection["status"] = "VOIDED"
        protection["base_premium_cents"] = 0
        protection["medical_uplift_cents"] = 0
        protection["waiver_surcharge_cents"] = 0
        protection["premium_cents"] = 0
        protection["insured_trip_cost_cents"] = 0
        touch_if_changed(protection, before)
        voided = True
    if voided:
        pilgrim["protection_status"] = "VOIDED"
        pilgrim["protection_premium_cents"] = 0


def revoke_free_seats(agreement, departure):
    """Flip free-seat travellers back to paying, newest first, until the granted
    count no longer exceeds the recomputed entitlement."""
    guard = 0
    while guard < 1000:
        guard += 1
        granted = free_seats_granted(agreement)
        if granted <= agreement["earned_free_seats"]:
            break
        candidates = [p for p in db.pilgrims.values()
                      if p["recruited_by_agreement_id"] == agreement["id"]
                      and not p["is_paying"]
                      and p["booking_status"] != "CANCELLED"]
        if not candidates:
            break
        victim = order_rows_desc(candidates)[0]
        before = snap(victim)
        victim["is_paying"] = True
        victim["price_locked_cents"] = departure["provisional_per_pax_price_cents"]
        recompute_invoice(victim)
        touch_if_changed(victim, before)
        agreement_before = snap(agreement)
        recompute_accrual_snapshot(agreement)
        touch_if_changed(agreement, agreement_before)


def reprice_departure_roster(departure, previous_price):
    """When the provisional per-pax price moved, re-price every still-open
    traveller that has not already paid in full."""
    if departure["provisional_per_pax_price_cents"] == previous_price:
        return
    for pilgrim in pilgrims_of_departure(departure["id"]):
        if pilgrim["booking_status"] not in ("DEPOSITED", "CONFIRMED"):
            continue
        if pilgrim["payment_status"] == "PAID_IN_FULL":
            continue
        before = snap(pilgrim)
        pilgrim["price_locked_cents"] = departure["provisional_per_pax_price_cents"]
        if pilgrim["room_type_assigned"] == "SINGLE":
            pilgrim["single_supplement_applied_cents"] = \
                departure["provisional_single_supplement_cents"]
        recompute_invoice(pilgrim)
        touch_if_changed(pilgrim, before)


def cancel_pilgrim(pilgrim, force_zero_penalty=False, cascade_departure=True):
    """Traveller-cancellation unwind (PRD section 3.5).

    cascade_departure is False when this cancellation is a hop of a
    departure-wide cancellation: the departure-level unwind owns the departure
    row's own recomputation and its single version bump.
    """
    departure = departure_of(pilgrim)
    program = program_of(departure)

    penalty_bp = cancellation_penalty_bp(departure, program, force_zero=force_zero_penalty)
    penalty = min(pilgrim["cash_applied_cents"],
                  apply_bp(pilgrim["invoice_total_cents"], penalty_bp))
    pilgrim["penalty_retained_cents"] = penalty
    pilgrim["refund_cents"] = pilgrim["cash_applied_cents"] - penalty
    pilgrim["payment_status"] = "REFUNDED"
    pilgrim["booking_status"] = "CANCELLED"
    pilgrim["ticketed_name"] = None
    pilgrim["room_type_assigned"] = None
    pilgrim["room_label"] = None
    pilgrim["ground_floor"] = False
    unpair_roommate(pilgrim)
    touch(pilgrim)

    supersede_plans_on_cancel(pilgrim)
    void_protections_on_cancel(pilgrim)

    agreement = None
    agreement_id = pilgrim.get("recruited_by_agreement_id")
    if agreement_id:
        agreement = db.agreements.get(agreement_id)
    if agreement is not None:
        before = snap(agreement)
        recompute_accrual_snapshot(agreement)
        touch_if_changed(agreement, before)
        revoke_free_seats(agreement, departure)

    if cascade_departure:
        previous_price = departure["provisional_per_pax_price_cents"]
        departure_before = snap(departure)
        recompute_provisional_tier(departure)
        reprice_departure_roster(departure, previous_price)
        touch_if_changed(departure, departure_before)


# ---------------------------------------------------------------------------
# Air block expiry guard
# ---------------------------------------------------------------------------


def guard_air_block_deadline(block):
    """Any write against a live block after deposit_deadline_utc first moves the
    block to EXPIRED and then fails."""
    if block["status"] in ("DRAFT", "OFFERED", "COUNTERED") and \
            clock_now() > as_dt(block["deposit_deadline_utc"]):
        block["status"] = "EXPIRED"
        touch(block)
        err("ERR_AIR_BLOCK_INVALID_STATE", "The air block deposit deadline has passed.")


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialize(row):
    return copy.deepcopy({k: v for k, v in row.items() if not k.startswith("_")})


def serialize_air_block(row):
    # seats_assigned is a derived count, not a stored counter.
    out = serialize(row)
    out["seats_assigned"] = seats_assigned_for(row["departure_id"])
    return out


def serialize_program(row):
    return serialize(row)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
