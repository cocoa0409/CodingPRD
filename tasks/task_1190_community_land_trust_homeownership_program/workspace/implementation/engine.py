"""Business-logic engine: calculations (SCAFFOLD Table 3), cascade helpers,
and the scheduled system pass driven by the logical clock (PRD section 2.9).

All monetary math uses Decimal with ROUND_HALF_UP to integer cents; ratios
(ami_pct, computed_ltv) are rounded half-up to 4 decimal places.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import db
from util import add_months, bump, new_entity

D = Decimal


# ---------------------------------------------------------------------------
# ami_pct_calc
# ---------------------------------------------------------------------------

_SIZE_ADJ = {
    1: D("0.70"),
    2: D("0.80"),
    3: D("0.90"),
    4: D("1.00"),
    5: D("1.08"),
    6: D("1.16"),
    7: D("1.24"),
}
_SIZE_ADJ_8PLUS = D("1.32")


def size_adjustment(household_size):
    if household_size >= 8:
        return _SIZE_ADJ_8PLUS
    return _SIZE_ADJ.get(household_size, _SIZE_ADJ_8PLUS)


def compute_ami_pct(verified_income_cents, area_median_income_cents, household_size):
    denom = D(area_median_income_cents) * size_adjustment(household_size)
    if denom == 0:
        return 0.0
    ratio = (D(verified_income_cents) / denom).quantize(D("0.0001"), rounding=ROUND_HALF_UP)
    return float(ratio)


# ---------------------------------------------------------------------------
# lease_fee_tier
# ---------------------------------------------------------------------------

def compute_monthly_fee(program, ami_pct):
    base = D(program["ground_lease_base_fee_cents"])
    if ami_pct is None:
        return int(base)
    a = D(str(ami_pct))
    reduction = D(str(program["low_income_fee_reduction_pct"]))
    if a <= D("0.50"):
        fee = base * (D(1) - reduction)
    elif a <= D("0.80"):
        fee = base * (D(1) - reduction * (D("0.80") - a) / D("0.30"))
    else:
        fee = base
    return int(fee.quantize(D("1"), rounding=ROUND_HALF_UP))


def reamount_pending_fees(lease, now):
    """Re-amount PENDING LeaseFee rows whose due_date is in the future."""
    for fee in db.store.fees.values():
        if (fee["lease_id"] == lease["id"] and fee["status"] == "PENDING"
                and fee["due_date"] > now):
            fee["amount_cents"] = lease["monthly_fee_cents"]


def recompute_lease_fee(program, lease, now):
    household = db.store.households.get(lease["household_id"])
    ami = household["ami_pct"] if household else None
    new_fee = compute_monthly_fee(program, ami)
    if lease["monthly_fee_cents"] != new_fee:
        lease["monthly_fee_cents"] = new_fee
        bump(lease)
    reamount_pending_fees(lease, now)


def recompute_program_fees(program, now):
    for lease in db.store.leases.values():
        unit = db.store.units.get(lease["unit_id"])
        if not unit or unit["program_id"] != program["id"]:
            continue
        if lease["status"] in ("ACTIVE", "IN_DEFAULT", "CURE_PERIOD"):
            recompute_lease_fee(program, lease, now)


# ---------------------------------------------------------------------------
# resale_formula / subsidy_retention / affordability_preservation_check
# ---------------------------------------------------------------------------

def compute_resale_values(program, unit, seller_lease, appraisal_at_listing_cents, listed_at):
    P0 = D(seller_lease["purchase_price_cents"])
    S0 = unit["original_subsidy_cents"]
    A0 = seller_lease.get("_purchase_appraisal_cents", 0)
    A1 = appraisal_at_listing_cents
    days = (listed_at - seller_lease["start_date"]).days
    Y = int(D(days) / D("365.25"))  # floor for non-negative values
    if Y < 0:
        Y = 0

    if program["resale_formula_kind"] == "APPRAISAL_BASED":
        appreciation = max(0, A1 - A0)
        seller_share = int((D(appreciation) * D(str(program["appraisal_seller_share_pct"])))
                           .quantize(D("1"), rounding=ROUND_HALF_UP))
        asking = int(P0) + seller_share
        subsidy_retained = S0 + (appreciation - seller_share)
        seller_proceeds = asking - int(P0)
    else:  # INDEXED
        pct = D(str(program["indexed_annual_appreciation_pct"]))
        indexed_value = int((P0 * (D(1) + pct * Y)).quantize(D("1"), rounding=ROUND_HALF_UP))
        asking = min(indexed_value, A1)
        subsidy_retained = S0 + max(0, A1 - asking)
        seller_proceeds = asking - int(P0)

    return {
        "asking_price_cents": asking,
        "seller_proceeds_cents": seller_proceeds,
        "subsidy_retained_cents": subsidy_retained,
    }


def compute_affordability_preserved(program, asking_price_cents):
    eligible_annual = D(program["area_median_income_cents"]) * D(str(program["max_eligibility_ami_pct"]))
    monthly_budget = (eligible_annual * D("0.30") / D(12)).quantize(D("1"), rounding=ROUND_HALF_UP)
    price_ceiling = int(monthly_budget) * 12 * 30
    return asking_price_cents <= price_ceiling


# ---------------------------------------------------------------------------
# priority_score_calc
# ---------------------------------------------------------------------------

SIZE_MATCH_BONUS = 50
AGE_CAP_DAYS = 365


def need_score(ami_pct):
    if ami_pct is None:
        return 0
    return int(((D(1) - D(str(ami_pct))) * D(1000)).quantize(D("1"), rounding=ROUND_HALF_UP))


def age_score(entry, now):
    days = (now - entry["created_at"]).days
    if days < 0:
        days = 0
    return min(days, AGE_CAP_DAYS)


def refresh_priority_score(entry, now):
    household = db.store.households.get(entry["household_id"])
    ami = household["ami_pct"] if household else None
    entry["priority_score"] = need_score(ami) + age_score(entry, now)


def refresh_program_waitlist_scores(program_id, now):
    for entry in db.store.waitlist.values():
        household = db.store.households.get(entry["household_id"])
        if household and household["program_id"] == program_id and entry["status"] == "ACTIVE":
            refresh_priority_score(entry, now)
            bump(entry)


def effective_score(entry, unit):
    household = db.store.households.get(entry["household_id"])
    bonus = 0
    if household and abs(unit["bedrooms"] - household["household_size"]) <= 1:
        bonus = SIZE_MATCH_BONUS
    return entry["priority_score"] + bonus


# ---------------------------------------------------------------------------
# refi_ltv_calc
# ---------------------------------------------------------------------------

def compute_refi(program, requested_loan_cents, appraised_value_cents):
    ltv = (D(requested_loan_cents) / D(appraised_value_cents)).quantize(
        D("0.0001"), rounding=ROUND_HALF_UP)
    max_loan = int((D(appraised_value_cents) * D(str(program["max_refi_ltv_pct"])))
                   .quantize(D("1"), rounding=ROUND_FLOOR))
    return float(ltv), max_loan


# ---------------------------------------------------------------------------
# Households: education, certification, eligibility
# ---------------------------------------------------------------------------

PASSING_SCORE = D("0.7")


def program_of_household(household):
    return db.store.programs.get(household["program_id"])


def program_of_unit(unit):
    return db.store.programs.get(unit["program_id"])


def program_of_lease(lease):
    unit = db.store.units.get(lease["unit_id"])
    return program_of_unit(unit) if unit else None


def required_courses_satisfied(program_id, household_id, now):
    """True iff every required, still-OFFERED course has an unexpired passing
    completion. Retired courses are waived going forward (PRD 3.2)."""
    for course in db.store.courses.values():
        if (course["program_id"] == program_id and course["is_required"]
                and course["status"] == "OFFERED"):
            ok = any(
                c for c in db.store.completions.values()
                if c["household_id"] == household_id
                and c["course_id"] == course["id"]
                and D(str(c["score_pct"])) >= PASSING_SCORE
                and c["expires_at"] > now
            )
            if not ok:
                return False
    return True


def refresh_education_completed_at(household, now):
    """After a completion is recorded: when every required course has an
    unexpired passing completion, education_completed_at = max(completed_at)
    across the required courses."""
    if not required_courses_satisfied(household["program_id"], household["id"], now):
        return
    latest = []
    for course in db.store.courses.values():
        if (course["program_id"] == household["program_id"] and course["is_required"]
                and course["status"] == "OFFERED"):
            completions = [
                c for c in db.store.completions.values()
                if c["household_id"] == household["id"]
                and c["course_id"] == course["id"]
                and D(str(c["score_pct"])) >= PASSING_SCORE
                and c["expires_at"] > now
            ]
            latest.append(max(c["completed_at"] for c in completions))
    if latest:
        value = max(latest)
        if household["education_completed_at"] != value:
            household["education_completed_at"] = value
            bump(household)


def latest_approved_cert(household_id):
    approved = [c for c in db.store.certs.values()
                if c["household_id"] == household_id and c["status"] == "APPROVED"]
    if not approved:
        return None
    return max(approved, key=lambda c: (c["decided_at"], c["created_at"], c["id"]))


def cert_is_fresh(cert, now):
    return cert is not None and cert["decided_at"] is not None \
        and add_months(cert["decided_at"], 24) > now


def reevaluate_eligibility_on_approval(program, household, cert, now):
    """Cascade executed when an IncomeCertification is approved (PRD 3.2)."""
    # A newer approved cert supersedes any older APPROVED rows.
    for other in db.store.certs.values():
        if (other["household_id"] == household["id"] and other["id"] != cert["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "EXPIRED"
            bump(other)

    household["ami_pct"] = cert["ami_pct_at_cert"]
    status = household["eligibility_status"]

    if cert["ami_pct_at_cert"] > program["max_eligibility_ami_pct"]:
        # AMI above the ceiling -> INELIGIBLE (boundary-inclusive eligibility).
        if status in ("PENDING", "ELIGIBLE", "EXPIRED"):
            if status == "ELIGIBLE":
                household["_eligibility_lost_at"] = now
            household["eligibility_status"] = "INELIGIBLE"
            household["eligibility_expires_at"] = None
    else:
        edu_ok = required_courses_satisfied(program["id"], household["id"], now)
        if edu_ok and cert_is_fresh(cert, now) and status in ("PENDING", "ELIGIBLE", "EXPIRED"):
            household["eligibility_status"] = "ELIGIBLE"
            household["eligibility_expires_at"] = add_months(cert["decided_at"], 24)
            household["_eligibility_lost_at"] = None
    bump(household)

    # Resident fee recalculation.
    if household["active_lease_id"]:
        lease = db.store.leases.get(household["active_lease_id"])
        if lease and lease["status"] in ("ACTIVE", "IN_DEFAULT", "CURE_PERIOD"):
            recompute_lease_fee(program, lease, now)

    # Priority scores depend on ami_pct.
    for entry in db.store.waitlist.values():
        if entry["household_id"] == household["id"] and entry["status"] == "ACTIVE":
            refresh_priority_score(entry, now)
            bump(entry)


# ---------------------------------------------------------------------------
# Default notices (shared by manual issue, auto FEE_ARREARS, FAILED inspection)
# ---------------------------------------------------------------------------

NOTICE_KINDS = {"FEE_ARREARS", "MAINTENANCE", "UNAUTHORIZED_REFINANCE", "OCCUPANCY_VIOLATION"}


def issue_default_notice(program, unit, lease, notice_kind, amount_due_cents, issued_by, now,
                         cure_evidence=""):
    notice = new_entity()
    notice.update({
        "lease_id": lease["id"],
        "notice_kind": notice_kind,
        "issued_at": now,
        "cure_deadline_at": now + timedelta(days=program["default_cure_window_days"]),
        "amount_due_cents": amount_due_cents,
        "status": "OPEN",
        "issued_by": issued_by,
        "cured_at": None,
        "cure_evidence": cure_evidence,
    })
    db.store.notices[notice["id"]] = notice
    # Cascade: lease -> IN_DEFAULT, unit -> IN_DEFAULT.
    if lease["status"] in ("ACTIVE", "CURE_PERIOD"):
        lease["status"] = "IN_DEFAULT"
        bump(lease)
    if unit["occupancy_status"] in ("OCCUPIED",):
        unit["occupancy_status"] = "IN_DEFAULT"
        bump(unit)
    return notice


def close_out_lease_if_no_open_notices(lease, now):
    """After a cure/dismiss: when no OPEN notices remain, lease returns to
    ACTIVE and the unit to OCCUPIED. CURE_PERIOD recovery clears arrears."""
    open_notices = [n for n in db.store.notices.values()
                    if n["lease_id"] == lease["id"] and n["status"] == "OPEN"]
    if open_notices:
        return
    if lease["status"] in ("IN_DEFAULT", "CURE_PERIOD"):
        was_cure_period = lease["status"] == "CURE_PERIOD"
        lease["status"] = "ACTIVE"
        if was_cure_period:
            lease["fee_arrears_cents"] = 0
        bump(lease)
        unit = db.store.units.get(lease["unit_id"])
        if unit and unit["occupancy_status"] == "IN_DEFAULT":
            unit["occupancy_status"] = "OCCUPIED"
            bump(unit)


# ---------------------------------------------------------------------------
# Lease fee charging
# ---------------------------------------------------------------------------

def create_lease_fee(lease, now, period_year, period_month):
    from datetime import datetime
    fee = new_entity(with_version=False)
    fee.update({
        "lease_id": lease["id"],
        "period_year": period_year,
        "period_month": period_month,
        "amount_cents": lease["monthly_fee_cents"],
        "due_date": datetime(period_year, period_month, 1, 0, 0, 0, tzinfo=db.UTC),
        "status": "PENDING",
        "paid_at": None,
        "paid_amount_cents": 0,
    })
    db.store.fees[fee["id"]] = fee
    lease["last_fee_charged_at"] = now
    return fee


# ---------------------------------------------------------------------------
# Scheduled system pass (logical clock, PRD 2.9)
# ---------------------------------------------------------------------------

def run_time_pass(now):
    store = db.store

    # 1. Approved certifications expire 24 months after decision.
    for cert in list(store.certs.values()):
        if (cert["status"] == "APPROVED" and cert["decided_at"] is not None
                and add_months(cert["decided_at"], 24) <= now):
            cert["status"] = "EXPIRED"
            bump(cert)

    # 2. Households whose eligibility lapses move ELIGIBLE -> EXPIRED; their
    #    ACTIVE waitlist entries expire at the same time.
    for h in list(store.households.values()):
        if (h["eligibility_status"] == "ELIGIBLE"
                and h["eligibility_expires_at"] is not None
                and now >= h["eligibility_expires_at"]):
            h["eligibility_status"] = "EXPIRED"
            h["_eligibility_lost_at"] = now
            bump(h)
            for entry in store.waitlist.values():
                if entry["household_id"] == h["id"] and entry["status"] == "ACTIVE":
                    entry["status"] = "EXPIRED"
                    bump(entry)
                    if h["waitlist_entry_id"] == entry["id"]:
                        h["waitlist_entry_id"] = None

    # 3. Waitlist entries expire when the household has been out of ELIGIBLE
    #    for more than 30 days.
    for entry in list(store.waitlist.values()):
        if entry["status"] != "ACTIVE":
            continue
        h = store.households.get(entry["household_id"])
        if not h or h["eligibility_status"] == "ELIGIBLE":
            continue
        lost_at = h.get("_eligibility_lost_at")
        if lost_at is not None and now > lost_at + timedelta(days=30):
            entry["status"] = "EXPIRED"
            bump(entry)
            if h["waitlist_entry_id"] == entry["id"]:
                h["waitlist_entry_id"] = None

    # 4. Lease fees go LATE at due_date + 5 days grace; arrears accumulate and
    #    may trigger an automatic FEE_ARREARS default notice.
    for fee in list(store.fees.values()):
        if fee["status"] == "PENDING" and now >= fee["due_date"] + timedelta(days=5):
            fee["status"] = "LATE"
            lease = store.leases.get(fee["lease_id"])
            if not lease:
                continue
            lease["fee_arrears_cents"] += fee["amount_cents"]
            bump(lease)
            monthly = lease["monthly_fee_cents"] or 0
            if monthly > 0 and lease["fee_arrears_cents"] >= 3 * monthly:
                already_open = any(
                    n for n in store.notices.values()
                    if n["lease_id"] == lease["id"]
                    and n["notice_kind"] == "FEE_ARREARS"
                    and n["status"] == "OPEN"
                )
                if not already_open:
                    unit = store.units.get(lease["unit_id"])
                    program = program_of_lease(lease)
                    if unit and program:
                        issue_default_notice(program, unit, lease, "FEE_ARREARS",
                                             lease["fee_arrears_cents"], "system", now)

    # 5. OPEN default notices past their cure deadline escalate, processed in
    #    chronological issued_at order with created_at tie-breaks.
    due_notices = [n for n in store.notices.values()
                   if n["status"] == "OPEN" and now > n["cure_deadline_at"]]
    due_notices.sort(key=lambda n: (n["issued_at"], n["created_at"], n["id"]))
    for notice in due_notices:
        notice["status"] = "ESCALATED"
        bump(notice)

    # 6. Ground leases reaching end_date expire.
    for lease in list(store.leases.values()):
        if lease["status"] == "ACTIVE" and now >= lease["end_date"]:
            lease["status"] = "EXPIRED"
            bump(lease)
            unit = store.units.get(lease["unit_id"])
            if unit and unit["current_lease_id"] == lease["id"]:
                unit["current_lease_id"] = None
                if unit["occupancy_status"] in ("OCCUPIED", "IN_DEFAULT"):
                    unit["occupancy_status"] = "VACANT"
                bump(unit)
            h = store.households.get(lease["household_id"])
            if h and h["active_lease_id"] == lease["id"]:
                h["active_lease_id"] = None
                bump(h)

    # 7. IN_DEFAULT leases enter CURE_PERIOD when a monetary notice is within
    #    7 days of its deadline and a partial payment has been received.
    for lease in list(store.leases.values()):
        if lease["status"] != "IN_DEFAULT":
            continue
        for notice in store.notices.values():
            if (notice["lease_id"] == lease["id"] and notice["status"] == "OPEN"
                    and notice["amount_due_cents"] > 0
                    and timedelta(0) <= (notice["cure_deadline_at"] - now) <= timedelta(days=7)):
                partial = any(
                    f for f in store.fees.values()
                    if f["lease_id"] == lease["id"]
                    and f["status"] in ("PENDING", "LATE")
                    and 0 < f["paid_amount_cents"] < f["amount_cents"]
                )
                if partial:
                    lease["status"] = "CURE_PERIOD"
                    bump(lease)
                break

    # 8. Inspection auto-scheduling.
    for unit in list(store.units.values()):
        due = unit["next_inspection_due_at"]
        if due is None or due >= now:
            continue
        has_pending = any(
            i for i in store.inspections.values()
            if i["unit_id"] == unit["id"] and i["result"] == "PENDING"
        )
        if has_pending:
            continue
        record = new_entity()
        record.update({
            "unit_id": unit["id"],
            "scheduled_for": now,
            "completed_at": None,
            "inspector_user_id": "system",
            "result": "PENDING",
            "findings": "",
            "follow_up_due_at": None,
            "linked_notice_id": None,
        })
        store.inspections[record["id"]] = record

    # 9. Daily refresh of ACTIVE waitlist priority scores.
    for entry in list(store.waitlist.values()):
        if entry["status"] == "ACTIVE":
            refresh_priority_score(entry, now)
            bump(entry)
