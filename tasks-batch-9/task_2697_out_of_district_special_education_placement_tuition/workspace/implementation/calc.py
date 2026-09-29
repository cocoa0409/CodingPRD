"""Domain constants and the ten pinned calculations (PRD 2.5 / 2.6 / 3.x)."""
from decimal import Decimal, ROUND_HALF_UP

from store import db, ordered, parse_date

D = Decimal

# ---- pinned domain constants -------------------------------------------------
BILLING_CYCLE_DAYS = 28
ABSENCE_TOLERANCE_DAYS = 3
SERVICE_PERIOD_WEEKS = 4
SERVICE_TRAVEL_DIFFERENTIAL = D("1.075")
TRANSPORT_FUEL_INDEX = D("1.0325")
VOLUME_CREDIT_HIGH_FLOOR_CENTS = 1000000
VOLUME_CREDIT_LOW_FLOOR_CENTS = 700000
VOLUME_CREDIT_HIGH_RATE = D("0.03")
VOLUME_CREDIT_LOW_RATE = D("0.015")
ADMIN_FEE_RATE = D("0.0225")
VARIANCE_TOLERANCE_PCT = D("0.02")
TURNAROUND_BUFFER_MIN = 10
CONTRACT_ACTIVATION_GRACE_DAYS = 30
TRANSITION_SERVICES_RESERVE_CENTS = 250000
MIN_CONTINUUM_OPTIONS = 3
MIN_LRE_JUSTIFICATION_CHARS = 40
MIN_EQUITABLE_FINDINGS_CHARS = 30
MAX_REVISION_ROUNDS = 3
MAX_AMENDMENT_ROUNDS = 2
MAX_RESUBMISSION_ROUNDS = 2
MAX_REMAND_ROUNDS = 2
MIN_ACCEPTED_REPORTS = 2
RETURN_READINESS_MIN = D("62.50")
BILLING_PERIODS_PER_YEAR = 13
REGRESSION_PENALTY_POINTS = 4
DECAY_BASE = D("0.7")
STATUTORY_DAY_RATE_CEILING_CENTS = 28000
TRANSPORT_CLAIM_CAP_CENTS = 150000
LATE_NOTICE_DAYS = 10
LATE_NOTICE_REDUCTION = D("0.25")
NON_COOPERATION_REDUCTION = D("0.20")
PRIOR_OFFER_REDUCTION = D("0.15")
MAX_EQUITABLE_REDUCTION = D("0.50")
HIGH_COST_TRIGGER_CENTS = 4000000
HIGH_COST_MAX_PER_STUDENT_CENTS = 5000000
HIGH_COST_TIER_HIGH_EXCESS = 6000000
HIGH_COST_TIER_MID_EXCESS = 2000000
HIGH_COST_TIER_HIGH_RATE = D("0.90")
HIGH_COST_TIER_MID_RATE = D("0.75")
HIGH_COST_TIER_LOW_RATE = D("0.60")
MEDICAID_HOURLY_RATE_CENTS = 9000
MEDICAID_MATCH_RATE = D("0.5432")


# ---- rounding ---------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return D(str(value))


def rhu(value, places):
    return dec(value).quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(dec(value).quantize(D(1), rounding=ROUND_HALF_UP))


# ---- 2.6 placement rollup ---------------------------------------------------

def recompute_placement_encumbrance(placement):
    contract_component = placement["contract_encumbrance_cents"] - placement["paid_total_ytd_cents"]
    if contract_component < 0:
        contract_component = 0
    placement["encumbrance_cents"] = (
        contract_component
        + placement["addendum_encumbrance_cents"]
        + placement["transport_encumbrance_cents"]
        + placement["transition_reserve_cents"]
    )


# ---- calc 1: placement_encumbrance -----------------------------------------

def placement_encumbrance(placement, schedule):
    total = placement["contracted_instructional_days"] * schedule["day_rate_cents"]
    if placement["placement_type"] == "RESIDENTIAL":
        total += placement["contracted_residential_nights"] * schedule["residential_rate_cents"]
    return total


# ---- calc 2: service_addendum_encumbrance ----------------------------------

def service_addendum_encumbrance(addendum, hourly_rate_cents):
    return rhu_cents(
        dec(addendum["authorized_hours_per_week"])
        * dec(addendum["contract_weeks"])
        * dec(hourly_rate_cents)
    )


# ---- calc 3: transport_encumbrance -----------------------------------------

def transport_encumbrance(assignment, route):
    return rhu_cents(
        dec(assignment["days_per_week"])
        * dec(assignment["contract_weeks"])
        * dec(route["daily_rate_cents"])
        * TRANSPORT_FUEL_INDEX
    )


# ---- calc 5: invoice_net_payable -------------------------------------------

def invoice_net_payable(gross):
    if gross >= VOLUME_CREDIT_HIGH_FLOOR_CENTS:
        rate = VOLUME_CREDIT_HIGH_RATE
    elif gross >= VOLUME_CREDIT_LOW_FLOOR_CENTS:
        rate = VOLUME_CREDIT_LOW_RATE
    else:
        rate = D("0")
    credit = rhu_cents(dec(gross) * rate)
    subtotal = gross - credit
    fee = rhu_cents(dec(subtotal) * ADMIN_FEE_RATE)
    return subtotal + fee, credit, fee


# ---- calc 4: invoice_verified_amount ---------------------------------------

def billable_days(record, basis):
    if basis == "ENROLLMENT":
        return record["days_enrolled"]
    return record["days_attended"] + min(record["days_absent_unexcused"], ABSENCE_TOLERANCE_DAYS)


def active_transport_route(placement_id):
    """Ranked created_at ASC then pickup_window_start_min ASC; first taken."""
    candidates = [
        a for a in db.assignments.values()
        if a["placement_id"] == placement_id and a["status"] == "ACTIVE"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["created_at"], a["pickup_window_start_min"], a["_seq"]))
    return db.routes.get(candidates[0]["route_id"])


def service_lines_total(record):
    entries = []
    for line in record.get("service_delivery_lines") or []:
        addendum = db.addenda.get(line.get("service_addendum_id"))
        if addendum is None:
            continue
        entries.append((addendum, line))
    entries.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["_seq"]))
    total = 0
    for addendum, line in entries:
        cap = dec(addendum["authorized_hours_per_week"]) * SERVICE_PERIOD_WEEKS
        hours = dec(line.get("hours_delivered", 0))
        capped = hours if hours < cap else cap
        total += rhu_cents(capped * dec(addendum["hourly_rate_cents"]) * SERVICE_TRAVEL_DIFFERENTIAL)
    return total


def price_invoice(invoice, placement, schedule, record, basis, route):
    """Runs the whole waterfall on both bases; returns the field set to store."""
    residential_line = 0
    if placement["placement_type"] == "RESIDENTIAL":
        residential_line = record["residential_nights"] * schedule["residential_rate_cents"]
    service_total = service_lines_total(record)

    transport_line = 0
    if invoice["transport_days_billed"] != 0 and route is not None:
        transport_line = rhu_cents(
            dec(invoice["transport_days_billed"])
            * dec(route["daily_rate_cents"])
            * TRANSPORT_FUEL_INDEX
        )

    runs = {}
    for candidate_basis in ("ENROLLMENT", "ATTENDANCE"):
        days = billable_days(record, candidate_basis)
        tuition_line = days * schedule["day_rate_cents"]
        gross = tuition_line + residential_line + service_total + transport_line
        net, credit, fee = invoice_net_payable(gross)
        runs[candidate_basis] = {
            "tuition_line_cents": tuition_line,
            "gross_billable_cents": gross,
            "volume_credit_cents": credit,
            "admin_fee_cents": fee,
            "net": net,
        }

    provisional = runs["ENROLLMENT"]["net"]
    final = runs["ATTENDANCE"]["net"]
    chosen = runs[basis]
    verified = provisional if basis == "ENROLLMENT" else final

    submitted = invoice["submitted_amount_cents"]
    if verified == 0:
        variance = D("0") if submitted == 0 else D("1.0000")
    else:
        variance = rhu(dec(abs(submitted - verified)) / dec(verified), 4)

    return {
        "verification_basis": basis,
        "tuition_line_cents": chosen["tuition_line_cents"],
        "residential_line_cents": residential_line,
        "service_lines_total_cents": service_total,
        "transport_line_cents": transport_line,
        "gross_billable_cents": chosen["gross_billable_cents"],
        "volume_credit_cents": chosen["volume_credit_cents"],
        "admin_fee_cents": chosen["admin_fee_cents"],
        "provisional_amount_cents": provisional,
        "final_amount_cents": final,
        "verified_amount_cents": verified,
        "variance_pct": variance,
    }


# ---- calc 6: return_readiness_score ----------------------------------------

def report_score(report):
    goal_pct = dec(report["goals_met"]) / dec(report["goals_total"]) * D(100)
    raw = (
        D("0.5") * goal_pct
        + D("0.3") * dec(report["benchmark_scaled_score"])
        + D("0.2") * dec(report["attendance_rate_pct"])
        - D(REGRESSION_PENALTY_POINTS) * dec(report["goals_regressed"])
    )
    return rhu(raw, 2)


READINESS_VARIANTS = ("trailing_two_quarter", "cumulative_recency_weighted")


def accepted_reports(placement_id):
    rows = [
        r for r in db.progress.values()
        if r["placement_id"] == placement_id and r["status"] == "ACCEPTED"
    ]
    rows.sort(key=lambda r: (r["fiscal_year"], r["quarter"], r["created_at"], r["_seq"]),
              reverse=True)
    return rows


def return_readiness(placement_id, variant):
    rows = accepted_reports(placement_id)
    scores = [dec(r["report_score"]) for r in rows]
    count = len(rows)
    if count == 0:
        return D("0.00"), 0, []
    if variant == "cumulative_recency_weighted":
        weight_sum = D(0)
        weighted = D(0)
        for index, score in enumerate(scores):
            weight = DECAY_BASE ** index
            weighted += weight * score
            weight_sum += weight
        score = rhu(weighted / weight_sum, 2)
    else:
        window = scores[:2]
        score = rhu(sum(window) / dec(len(window)), 2)
    return score, count, scores


# ---- calc 7: reimbursement_award -------------------------------------------

def reimbursement_award(claim, award_basis):
    statutory_cap = STATUTORY_DAY_RATE_CEILING_CENTS * claim["claimed_instructional_days"]
    claimed_tuition = claim["claimed_tuition_cents"]
    if award_basis == "strict_statutory":
        eligible_tuition = min(claimed_tuition, statutory_cap)
    else:
        eligible_tuition = claimed_tuition
    eligible_transport = min(claim["claimed_transport_cents"], TRANSPORT_CLAIM_CAP_CENTS)
    eligible_amount = eligible_tuition + eligible_transport

    pct = D("0")
    notice_date = parse_date(claim["notice_date"])
    start_date = parse_date(claim["unilateral_start_date"])
    notice_days = (start_date - notice_date).days
    if notice_days < LATE_NOTICE_DAYS:
        pct += LATE_NOTICE_REDUCTION
    if claim["parent_cooperation"] is False:
        pct += NON_COOPERATION_REDUCTION
    offer_date = parse_date(claim.get("prior_district_offer_date"))
    if offer_date is not None and offer_date <= notice_date:
        pct += PRIOR_OFFER_REDUCTION
    if pct > MAX_EQUITABLE_REDUCTION:
        pct = MAX_EQUITABLE_REDUCTION

    keep = D(1) - pct
    awarded_tuition = rhu_cents(dec(eligible_tuition) * keep)
    awarded_transport = rhu_cents(dec(eligible_transport) * keep)
    awarded_amount = awarded_tuition + awarded_transport

    if awarded_amount == 0 or pct >= MAX_EQUITABLE_REDUCTION:
        status = "DENIED"
    elif awarded_amount == claimed_tuition + claim["claimed_transport_cents"]:
        status = "AWARDED_FULL"
    else:
        status = "AWARDED_PARTIAL"

    return {
        "award_basis": award_basis,
        "equitable_reduction_pct": pct,
        "eligible_amount_cents": eligible_amount,
        "awarded_tuition_cents": awarded_tuition,
        "awarded_transport_cents": awarded_transport,
        "awarded_amount_cents": awarded_amount,
        "status": status,
    }


# ---- calc 8: funding_claim_reimbursable ------------------------------------

def placement_fiscal_year(placement):
    schedule = db.rate_schedules.get(placement.get("rate_schedule_id"))
    return schedule["fiscal_year"] if schedule else None


def high_cost_prior_awarded(student_id, fiscal_year, exclude_id=None):
    total = 0
    for claim in db.funding.values():
        if claim["id"] == exclude_id:
            continue
        if claim["claim_type"] != "HIGH_COST_FUND":
            continue
        if claim["fiscal_year"] != fiscal_year:
            continue
        if claim["status"] not in ("ELIGIBLE", "SUBMITTED"):
            continue
        parent = db.placements.get(claim["placement_id"])
        if parent is None or parent["student_id"] != student_id:
            continue
        total += claim["reimbursable_amount_cents"]
    return total


def high_cost_tier_rate(excess):
    if excess >= HIGH_COST_TIER_HIGH_EXCESS:
        return HIGH_COST_TIER_HIGH_RATE
    if excess >= HIGH_COST_TIER_MID_EXCESS:
        return HIGH_COST_TIER_MID_RATE
    return HIGH_COST_TIER_LOW_RATE


def high_cost_amounts(placement, fiscal_year, exclude_id=None):
    """Returns (eligible_base, tier_rate, reimbursable). Never raises."""
    eligible_base = placement["paid_total_ytd_cents"]
    excess = eligible_base - HIGH_COST_TRIGGER_CENTS
    if excess < 0:
        excess = 0
    tier_rate = high_cost_tier_rate(excess)
    prior = high_cost_prior_awarded(placement["student_id"], fiscal_year, exclude_id)
    headroom = HIGH_COST_MAX_PER_STUDENT_CENTS - prior
    tier_product = rhu_cents(dec(excess) * tier_rate)
    reimbursable = tier_product if tier_product < headroom else headroom
    if reimbursable < 0:
        reimbursable = 0
    return eligible_base, tier_rate, reimbursable


def medicaid_billable_hours(placement_id):
    total = D(0)
    for record in db.attendance.values():
        if record["placement_id"] != placement_id or record["status"] != "VERIFIED":
            continue
        for line in record.get("service_delivery_lines") or []:
            addendum = db.addenda.get(line.get("service_addendum_id"))
            if addendum is None or not addendum.get("medicaid_billable"):
                continue
            total += dec(line.get("hours_delivered", 0))
    return total


def medicaid_amounts(placement):
    hours = medicaid_billable_hours(placement["id"])
    eligible_base = rhu_cents(hours * dec(MEDICAID_HOURLY_RATE_CENTS))
    reimbursable = rhu_cents(dec(eligible_base) * MEDICAID_MATCH_RATE)
    return hours, eligible_base, MEDICAID_MATCH_RATE, reimbursable


# ---- calc 9: waitlist_promotion --------------------------------------------

def _buffered(assignment):
    return (
        assignment["pickup_window_start_min"],
        assignment["pickup_window_end_min"] + TURNAROUND_BUFFER_MIN,
    )


def window_collides(route_id, start, end, exclude_id=None):
    lo = start
    hi = end + TURNAROUND_BUFFER_MIN
    for other in db.assignments.values():
        if other["route_id"] != route_id or other["status"] != "ACTIVE":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        o_lo, o_hi = _buffered(other)
        if lo < o_hi and o_lo < hi:
            return True
    return False


def waitlist_candidate(route_id):
    candidates = []
    for assignment in db.assignments.values():
        if assignment["route_id"] != route_id or assignment["status"] != "WAITLISTED":
            continue
        parent = db.placements.get(assignment["placement_id"])
        if parent is None or parent["status"] not in ("CONTRACTED", "ACTIVE"):
            continue
        candidates.append(assignment)
    candidates.sort(key=lambda a: (a["created_at"], a["pickup_window_start_min"], a["id"]))
    for candidate in candidates:
        if window_collides(route_id, candidate["pickup_window_start_min"],
                           candidate["pickup_window_end_min"], candidate["id"]):
            continue
        return candidate
    return None


# ---- calc 10: placement_cost_projection ------------------------------------

PROJECTION_VARIANTS = ("CONTRACTED_ENCUMBRANCE", "ACTUAL_RUN_RATE")


def cost_projection(placement, variant):
    periods_paid = 0
    if variant == "ACTUAL_RUN_RATE":
        paid = [
            i for i in db.invoices.values()
            if i["placement_id"] == placement["id"] and i["payment_status"] == "PAID"
        ]
        periods_paid = len(paid)
        if periods_paid == 0:
            projected = 0
        else:
            settled = sum(i["verified_amount_cents"] for i in paid)
            projected = rhu_cents(
                dec(settled) / dec(periods_paid) * dec(BILLING_PERIODS_PER_YEAR)
            )
    else:
        projected = (
            placement["contract_encumbrance_cents"]
            + placement["addendum_encumbrance_cents"]
            + placement["transport_encumbrance_cents"]
        )
    remaining = placement["encumbrance_cents"]
    if remaining < 0:
        remaining = 0
    return {
        "placement_id": placement["id"],
        "variant": variant,
        "projected_annual_cents": projected,
        "remaining_commitment_cents": remaining,
        "variance_cents": projected - placement["contract_encumbrance_cents"],
        "periods_paid": periods_paid,
    }


def sorted_children(collection, placement_id):
    return ordered([r for r in collection.values() if r["placement_id"] == placement_id])
