"""Row lifecycle, derived counters and serialization."""

from datetime import date, timedelta

from db import clock, db, new_id
from util import D, dfloor, fmt_date, fmt_dt, jnum, rhu, rhu_int, utc_date

# --------------------------------------------------------------------------- #
# constants (SCAFFOLD §1.3)
# --------------------------------------------------------------------------- #

HOUR_ROUNDING_INCREMENT = D("0.25")
IN_HOME_HOURS_PER_DAY = D(8)
OVERAGE_TIER_1_CENTS = 100000
OVERAGE_TIER_2_CENTS = 500000
W_QUALITY = D("0.45")
W_CAPACITY = D("0.30")
W_MODE = D("0.15")
W_CONTINUITY = D("0.10")
PROBATION_FACTOR = D("0.5")
REQUIRED_CREDENTIAL_TYPES = ["LICENSE", "BACKGROUND_CHECK", "CPR", "INSURANCE"]
TRAVEL_BUFFER_MINUTES = 60
SEVERITY_WEIGHT = {"MINOR": D(4), "MODERATE": D(12), "SEVERE": D(30)}
BONUS_CAP = D(10)
BONUS_EVERY = D(5)
BONUS_STEP = D(2)
LATE_CANCEL_FACTOR = D("0.5")
NO_SHOW_STRIKE_LIMIT = 2
RISK_NO_SHOW_HIGH_PCT = D(25)
RISK_NO_SHOW_MEDIUM_PCT = D(10)
RISK_LIFETIME_FLOOR = D(70)
REINSTATE_MIN_LIFETIME_SCORE = D(60)
OFFER_TTL_HOURS = 48
CHECK_IN_LEAD_MINUTES = 60

CENTER = "CENTER_BASED"
IN_HOME = "IN_HOME"

RESERVATION_TERMINAL = ("COMPLETED", "CANCELLED", "NO_SHOW")


# --------------------------------------------------------------------------- #
# row lifecycle
# --------------------------------------------------------------------------- #

def new_row(fields):
    now = clock()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def new_plain_row(fields):
    """Append-only rows: only id + created_at (common_fields: false)."""
    row = {"id": new_id(), "created_at": clock(), "_seq": db.next_seq()}
    row.update(fields)
    return row


def touch(row):
    row["updated_at"] = clock()
    row["version"] = row["version"] + 1


def created_key(row):
    return (row["created_at"], row["_seq"])


def sort_created(rows):
    return sorted(rows, key=created_key)


def base_fields(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


# --------------------------------------------------------------------------- #
# benefit year (SCAFFOLD §1.3 employee_entitlement_projection)
# --------------------------------------------------------------------------- #

def benefit_year_for(employer, moment=None):
    moment = moment or clock()
    month = employer["fiscal_year_start_month"]
    year = moment.year if moment.month >= month else moment.year - 1
    start = date(year, month, 1)
    end = date(year + 1, month, 1)
    return start, end


def employee_employer(employee):
    return db.employers.get(employee["employer_id"])


def employee_benefit_year(employee):
    employer = employee_employer(employee)
    if employer is None:
        return date(clock().year, 1, 1), date(clock().year + 1, 1, 1)
    return benefit_year_for(employer)


# --------------------------------------------------------------------------- #
# ledger
# --------------------------------------------------------------------------- #

def ledger_sorted(rows):
    return sorted(rows, key=lambda e: (e["effective_at"], e["_seq"]))


def employee_ledger(employee_id):
    return ledger_sorted(
        [e for e in db.ledger_entries.values() if e["employee_id"] == employee_id]
    )


def append_ledger(employee_id, reservation_id, entry_type, days_delta, cents_delta, memo):
    employee = db.employees.get(employee_id)
    by_start, _ = employee_benefit_year(employee)
    entry = new_plain_row(
        {
            "employee_id": employee_id,
            "reservation_id": reservation_id,
            "entry_type": entry_type,
            "days_delta": D(days_delta),
            "cents_delta": D(cents_delta),
            "benefit_year_start": by_start.isoformat(),
            "effective_at": clock(),
            "memo": memo,
        }
    )
    db.ledger_entries[entry["id"]] = entry
    return entry


# --------------------------------------------------------------------------- #
# derived counters
# --------------------------------------------------------------------------- #

def employee_counters(employee):
    by_start, _ = employee_benefit_year(employee)
    key = by_start.isoformat()
    days_used = D(0)
    days_reserved = D(0)
    strikes = 0
    for entry in db.ledger_entries.values():
        if entry["employee_id"] != employee["id"]:
            continue
        if entry["benefit_year_start"] != key:
            continue
        if entry["entry_type"] == "COMMIT":
            days_used += entry["days_delta"]
        elif entry["entry_type"] in ("RESERVE", "RELEASE"):
            days_reserved += entry["days_delta"]
        if entry["entry_type"] == "NO_SHOW_CHARGE":
            strikes += 1
    return rhu(days_used, 2), rhu(days_reserved, 2), strikes


def employee_eligibility(employee, strikes=None):
    employer = employee_employer(employee)
    if employee["employment_status"] != "ACTIVE":
        return "INELIGIBLE"
    if employer is None or employer["contract_status"] != "ACTIVE":
        return "INELIGIBLE"
    if strikes is None:
        _, _, strikes = employee_counters(employee)
    if strikes >= NO_SHOW_STRIKE_LIMIT:
        return "RESTRICTED"
    return "ELIGIBLE"


def employer_accrued_overage(employer):
    by_start, by_end = benefit_year_for(employer)
    total = 0
    employee_ids = set(
        e["id"] for e in db.employees.values() if e["employer_id"] == employer["id"]
    )
    for entry in db.ledger_entries.values():
        if entry["employee_id"] not in employee_ids:
            continue
        effective_date = utc_date(entry["effective_at"])
        if not (by_start <= effective_date < by_end):
            continue
        if entry["entry_type"] == "OVERAGE_ACCRUE":
            total += int(entry["cents_delta"])
        elif entry["entry_type"] == "OVERAGE_REVERSE":
            total -= int(entry["cents_delta"])
    return total


def employer_ytd_billed(employer):
    total = 0
    for invoice in db.employer_invoices.values():
        if invoice["employer_id"] != employer["id"]:
            continue
        if invoice["invoice_status"] in ("ISSUED", "PAID"):
            total += invoice["total_cents"]
    return total


def plan_enrolled_count(plan):
    count = 0
    for employee in db.employees.values():
        if employee["benefit_plan_id"] == plan["id"] and employee[
            "employment_status"
        ] in ("ACTIVE", "LEAVE"):
            count += 1
    return count


def block_occupancy(block):
    reserved = 0
    committed = 0
    for res in db.reservations.values():
        if res["matched_capacity_block_id"] != block["id"]:
            continue
        seats = res["required_seats"]
        if res["fulfillment_status"] in ("CONFIRMED", "IN_SERVICE"):
            reserved += seats
        elif res["fulfillment_status"] in ("COMPLETED", "NO_SHOW"):
            committed += seats
    return reserved, committed


def block_status(block, reserved=None, committed=None):
    if reserved is None or committed is None:
        reserved, committed = block_occupancy(block)
    if block.get("closed"):
        return "CLOSED"
    service_date = date.fromisoformat(block["service_date"])
    if service_date < utc_date(clock()):
        return "CLOSED"
    provider = db.providers.get(block["provider_id"])
    if provider is not None and provider["care_mode"] == CENTER:
        if reserved + committed >= block["total_slots"]:
            return "FULL"
    return "OPEN"


def provider_substantiated_incidents(provider_id):
    return [
        i
        for i in db.incident_reports.values()
        if i["provider_id"] == provider_id and i["incident_status"] == "SUBSTANTIATED"
    ]


def provider_completed_count(provider_id):
    return len(
        [
            r
            for r in db.reservations.values()
            if r["matched_provider_id"] == provider_id
            and r["fulfillment_status"] == "COMPLETED"
        ]
    )


def provider_quality(provider, variant="ROLLING_90D"):
    now = clock()
    deductions = D(0)
    for incident in provider_substantiated_incidents(provider["id"]):
        age_days = int(
            dfloor(D((now - incident["reported_at"]).total_seconds()) / D(86400))
        )
        if variant == "LIFETIME_UNDECAYED":
            decay = D(1)
        elif age_days <= 30:
            decay = D(1)
        elif age_days <= 60:
            decay = D("0.60")
        elif age_days <= 90:
            decay = D("0.30")
        else:
            decay = D(0)
        deductions += SEVERITY_WEIGHT[incident["severity"]] * decay
    completed = D(provider_completed_count(provider["id"]))
    bonus = min(BONUS_CAP, dfloor(completed / BONUS_EVERY) * BONUS_STEP)
    score = rhu(D(100) - deductions + bonus, 2)
    if score < 0:
        score = D(0)
    if score > 100:
        score = D(100)
    return score


def provider_scores(provider):
    return provider_quality(provider, "ROLLING_90D"), provider_quality(
        provider, "LIFETIME_UNDECAYED"
    )


def has_full_credentials(provider_id, against_date):
    """Every REQUIRED_CREDENTIAL_TYPES member VALID and not expiring before `against_date`."""
    for credential_type in REQUIRED_CREDENTIAL_TYPES:
        found = False
        for credential in db.credentials.values():
            if credential["provider_id"] != provider_id:
                continue
            if credential["credential_type"] != credential_type:
                continue
            if credential["status"] != "VALID":
                continue
            if date.fromisoformat(credential["expires_on"]) < against_date:
                continue
            found = True
            break
        if not found:
            return False
    return True


# --------------------------------------------------------------------------- #
# serializers
# --------------------------------------------------------------------------- #

def s_employer(row):
    out = base_fields(row)
    out.update(
        {
            "name": row["name"],
            "industry_code": row["industry_code"],
            "contract_status": row["contract_status"],
            "fiscal_year_start_month": row["fiscal_year_start_month"],
            "invoicing_cycle": row["invoicing_cycle"],
            "admin_fee_pct": jnum(row["admin_fee_pct"]),
            "overage_billing_enabled": row["overage_billing_enabled"],
            "adult_elder_extension_enabled": row["adult_elder_extension_enabled"],
            "accrued_overage_cents_current_period": employer_accrued_overage(row),
            "ytd_billed_cents": employer_ytd_billed(row),
        }
    )
    return out


def s_plan(row):
    out = base_fields(row)
    out.update(
        {
            "employer_id": row["employer_id"],
            "plan_code": row["plan_code"],
            "annual_use_limit_days": row["annual_use_limit_days"],
            "copay_center_cents_per_day": row["copay_center_cents_per_day"],
            "copay_in_home_cents_per_hour": row["copay_in_home_cents_per_hour"],
            "in_home_min_billable_hours": jnum(row["in_home_min_billable_hours"]),
            "eligible_dependent_types": list(row["eligible_dependent_types"]),
            "max_dependents_per_reservation": row["max_dependents_per_reservation"],
            "overage_rate_center_cents_per_day": row["overage_rate_center_cents_per_day"],
            "overage_rate_in_home_cents_per_hour": row[
                "overage_rate_in_home_cents_per_hour"
            ],
            "cancellation_window_hours": row["cancellation_window_hours"],
            "no_show_charge_cents": row["no_show_charge_cents"],
            "effective_from": fmt_dt(row["effective_from"]),
            "effective_to": fmt_dt(row["effective_to"]),
            "status": row["status"],
            "superseded_by_plan_id": row["superseded_by_plan_id"],
            "enrolled_employee_count": plan_enrolled_count(row),
        }
    )
    return out


def s_employee(row):
    days_used, days_reserved, strikes = employee_counters(row)
    out = base_fields(row)
    out.update(
        {
            "employer_id": row["employer_id"],
            "benefit_plan_id": row["benefit_plan_id"],
            "employee_external_id": row["employee_external_id"],
            "user_id": row["user_id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "employment_status": row["employment_status"],
            "entitlement_days_used": jnum(days_used),
            "entitlement_days_reserved": jnum(days_reserved),
            "no_show_strike_count": strikes,
            "eligibility_status": employee_eligibility(row, strikes),
        }
    )
    return out


def s_dependent(row):
    out = base_fields(row)
    out.update(
        {
            "employee_id": row["employee_id"],
            "full_name": row["full_name"],
            "dependent_type": row["dependent_type"],
            "date_of_birth": row["date_of_birth"],
            "relationship": row["relationship"],
            "care_notes": row["care_notes"],
            "status": row["status"],
        }
    )
    return out


def s_provider(row):
    quality, lifetime = provider_scores(row)
    out = base_fields(row)
    out.update(
        {
            "provider_name": row["provider_name"],
            "owner_user_id": row["owner_user_id"],
            "care_mode": row["care_mode"],
            "market_code": row["market_code"],
            "postal_code": row["postal_code"],
            "network_status": row["network_status"],
            "daily_capacity_slots": row["daily_capacity_slots"],
            "max_concurrent_assignments": row["max_concurrent_assignments"],
            "same_day_available": row["same_day_available"],
            "quality_score": jnum(quality),
            "lifetime_quality_score": jnum(lifetime),
            "substantiated_incident_count": len(
                provider_substantiated_incidents(row["id"])
            ),
            "completed_reservation_count": provider_completed_count(row["id"]),
            "last_status_reason_code": row["last_status_reason_code"],
        }
    )
    return out


def s_credential(row):
    out = base_fields(row)
    out.update(
        {
            "provider_id": row["provider_id"],
            "credential_type": row["credential_type"],
            "issued_on": row["issued_on"],
            "expires_on": row["expires_on"],
            "verified_by": row["verified_by"],
            "status": row["status"],
            "revoked_reason_code": row["revoked_reason_code"],
        }
    )
    return out


def s_block(row):
    reserved, committed = block_occupancy(row)
    out = base_fields(row)
    out.update(
        {
            "provider_id": row["provider_id"],
            "service_date": row["service_date"],
            "start_time_utc": fmt_dt(row["start_time_utc"]),
            "end_time_utc": fmt_dt(row["end_time_utc"]),
            "total_slots": row["total_slots"],
            "reserved_slots": reserved,
            "committed_slots": committed,
            "block_status": block_status(row, reserved, committed),
        }
    )
    return out


def s_reservation(row):
    out = base_fields(row)
    out.update(
        {
            "employee_id": row["employee_id"],
            "benefit_plan_id": row["benefit_plan_id"],
            "plan_version_pinned": row["plan_version_pinned"],
            "requested_care_mode": row["requested_care_mode"],
            "market_code": row["market_code"],
            "care_start_utc": fmt_dt(row["care_start_utc"]),
            "care_end_utc": fmt_dt(row["care_end_utc"]),
            "care_date": row["care_date"],
            "dependent_ids": list(row["dependent_ids"]),
            "dependent_count": row["dependent_count"],
            "dependent_type_mix": row["dependent_type_mix"],
            "required_seats": row["required_seats"],
            "fulfillment_status": row["fulfillment_status"],
            "billing_status": row["billing_status"],
            "matched_provider_id": row["matched_provider_id"],
            "matched_capacity_block_id": row["matched_capacity_block_id"],
            "excluded_provider_ids": list(row["excluded_provider_ids"]),
            "billable_hours_provisional": jnum(row["billable_hours_provisional"]),
            "billable_hours_final": jnum(row["billable_hours_final"]),
            "days_charged_provisional": jnum(row["days_charged_provisional"]),
            "days_charged_final": jnum(row["days_charged_final"]),
            "covered_days": jnum(row["covered_days"]),
            "overage_days": jnum(row["overage_days"]),
            "overage_tier_multiplier": jnum(row["overage_tier_multiplier"]),
            "copay_cents": row["copay_cents"],
            "overage_cents": row["overage_cents"],
            "penalty_cents": row["penalty_cents"],
            "cancellation_deadline_utc": fmt_dt(row["cancellation_deadline_utc"]),
            "actual_start_utc": fmt_dt(row["actual_start_utc"]),
            "actual_end_utc": fmt_dt(row["actual_end_utc"]),
            "confirmation_code": row["confirmation_code"],
            "unfulfilled_reason_code": row["unfulfilled_reason_code"],
            "cancel_reason_code": row["cancel_reason_code"],
        }
    )
    return out


def s_offer(row):
    out = base_fields(row)
    out.update(
        {
            "reservation_id": row["reservation_id"],
            "provider_id": row["provider_id"],
            "rank_score": jnum(row["rank_score"]),
            "rank_position": row["rank_position"],
            "quality_component": jnum(row["quality_component"]),
            "capacity_component": jnum(row["capacity_component"]),
            "mode_component": jnum(row["mode_component"]),
            "continuity_component": jnum(row["continuity_component"]),
            "probation_penalty_applied": row["probation_penalty_applied"],
            "remaining_slots_at_offer": row["remaining_slots_at_offer"],
            "offer_expires_at": fmt_dt(row["offer_expires_at"]),
            "offer_status": row["offer_status"],
            "reason_code": row["reason_code"],
        }
    )
    return out


def s_ledger(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "employee_id": row["employee_id"],
        "reservation_id": row["reservation_id"],
        "entry_type": row["entry_type"],
        "days_delta": jnum(row["days_delta"]),
        "cents_delta": jnum(row["cents_delta"]),
        "benefit_year_start": row["benefit_year_start"],
        "effective_at": fmt_dt(row["effective_at"]),
        "memo": row["memo"],
    }


def s_invoice(row):
    out = base_fields(row)
    out.update(
        {
            "employer_id": row["employer_id"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "copay_cents": row["copay_cents"],
            "overage_cents": row["overage_cents"],
            "penalty_cents": row["penalty_cents"],
            "subtotal_cents": row["subtotal_cents"],
            "admin_fee_cents": row["admin_fee_cents"],
            "total_cents": row["total_cents"],
            "line_count": row["line_count"],
            "reservation_count": row["reservation_count"],
            "invoice_status": row["invoice_status"],
            "issued_at": fmt_dt(row["issued_at"]),
            "paid_amount_cents": row["paid_amount_cents"],
            "void_reason_code": row["void_reason_code"],
        }
    )
    return out


def s_invoice_line(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "employer_invoice_id": row["employer_invoice_id"],
        "reservation_id": row["reservation_id"],
        "employee_id": row["employee_id"],
        "line_type": row["line_type"],
        "quantity": jnum(row["quantity"]),
        "unit_cents": row["unit_cents"],
        "amount_cents": row["amount_cents"],
    }


def s_incident(row):
    out = base_fields(row)
    out.update(
        {
            "provider_id": row["provider_id"],
            "reservation_id": row["reservation_id"],
            "severity": row["severity"],
            "category": row["category"],
            "narrative": row["narrative"],
            "reported_by_user_id": row["reported_by_user_id"],
            "reported_at": fmt_dt(row["reported_at"]),
            "incident_status": row["incident_status"],
            "qa_action": row["qa_action"],
            "reviewed_by": row["reviewed_by"],
            "resolution_reason_code": row["resolution_reason_code"],
        }
    )
    return out
