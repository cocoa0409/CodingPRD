"""Every derived figure in the domain (SCAFFOLD 1.3 calculations)."""

import calendar
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

from arith import F, dec, floor_int, rhu, rhu_int
from db import (apply_changes, centers_of, completed_run, db, entries_of, interim_requests_of,
                occ_of, ordered, reports_of, residents_of, rotations_of_resident, runs_of,
                settlements_of, submissions_of, tb_lines_of, touch, ucc_of)

# ------------------------------------------------------------------ constants
NATIONAL_TARGET_PCT = {
    "RN": Fraction("0.5600"),
    "LPN": Fraction("0.1000"),
    "NURSE_AIDE": Fraction("0.2000"),
    "MEDICAL_ASSISTANT": Fraction("0.0400"),
    "NURSE_PRACTITIONER": Fraction("0.1000"),
}
WAGE_RELATED_COST_CAP_PCT = Fraction(1, 4)
WITHIN_IRP_WEIGHT = Fraction(1)
BEYOND_IRP_WEIGHT = Fraction(1, 2)
RESIDENT_DAILY_FTE_CAP = Fraction(1)
DSH_ELIGIBILITY_THRESHOLD = Decimal("0.1500")
BAD_DEBT_ALLOWABLE_FACTOR = Fraction(65, 100)
UCC_POOL_CENTS = 800000000000
NATIONAL_UCC_COST_CENTS = 4000000000000
TENTATIVE_PAYMENT_PCT = Fraction(3, 4)
INTERIM_VARIANCE_THRESHOLD = Decimal("0.1000")
INTERIM_RATE_CAP_MULTIPLIER = Fraction(11, 10)
FILING_MONTHS_AFTER_FYE = 5
REOPENING_WINDOW_YEARS = 3
PRRB_APPEAL_WINDOW_DAYS = 180
PRRB_MINIMUM_AMOUNT_CENTS = 1000000
INTERIM_PERIOD_BUFFER_DAYS = 30
OCC_MIX_MIN_CATEGORIES = 3

BASIS_KEYS = ("SQUARE_FEET", "MEALS_SERVED", "POUNDS_LAUNDRY", "NURSING_HOURS")
STALE_SUPERSEDED = "SUPERSEDED_BY_NEWER_RUN"
STALE_COST_CENTER = "COST_CENTER_INPUT_CHANGED"
STALE_WORKPAPER = "WORKPAPER_ENTRY_CHANGED"


# ------------------------------------------------------------------ calendar
def as_date(text):
    return date.fromisoformat(text)


def add_months(source, months):
    index = source.month - 1 + months
    year = source.year + index // 12
    month = index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(source.day, last_day))


def add_years(source, years):
    try:
        return source.replace(year=source.year + years)
    except ValueError:  # 29 February
        return source.replace(year=source.year + years, day=28)


def filing_deadline(fiscal_year_end):
    return add_months(fiscal_year_end, FILING_MONTHS_AFTER_FYE)


def clock_date():
    return db.clock.astimezone(db.clock.tzinfo).date()


# --------------------------------------------------- trial balance roll-up
def rollup(report):
    """trial_balance_mapping_rollup — pure aggregation over integer cents."""
    lines = tb_lines_of(report["id"])
    direct = {}
    unmapped_total = 0
    for line in lines:
        if line["status"] == "MAPPED" and line["mapped_cost_center_id"]:
            key = line["mapped_cost_center_id"]
            direct[key] = direct.get(key, 0) + line["amount_cents"]
        else:
            unmapped_total += line["amount_cents"]

    reclass = {}
    adjust = {}
    for entry in entries_of(report["id"]):
        if entry["status"] != "ACTIVE":
            continue
        bucket = reclass if entry["entry_type"] == "RECLASSIFICATION" else adjust
        for leg in entry["legs"]:
            key = leg["cost_center_id"]
            bucket[key] = bucket.get(key, 0) + leg["amount_cents"]

    total_direct = 0
    for center in centers_of(report["id"]):
        direct_cost = direct.get(center["id"], 0)
        reclassified = reclass.get(center["id"], 0)
        adjustment = adjust.get(center["id"], 0)
        post_reclass = direct_cost + reclassified
        post_adjustment = post_reclass + adjustment
        apply_changes(center, {
            "direct_cost_cents": direct_cost,
            "reclassified_amount_cents": reclassified,
            "adjustment_amount_cents": adjustment,
            "post_reclass_direct_cost_cents": post_reclass,
            "post_adjustment_cost_cents": post_adjustment,
            "allocated_total_cost_cents": (post_adjustment + center["allocated_in_cents"]
                                           - center["allocated_out_cents"]),
        })
        total_direct += direct_cost

    report["total_direct_cost_cents"] = total_direct
    report["unmapped_tb_total_cents"] = unmapped_total


# ------------------------------------------------------------- freshness
def mark_allocation_stale(report):
    """NOT_RUN never becomes STALE; a STALE allocation stales the UCC data set."""
    if report["allocation_status"] != "CURRENT":
        return
    report["allocation_status"] = "STALE"
    for data_set in ucc_of(report["id"]):
        apply_changes(data_set, {"recompute_required": True})


def demote_completed_runs(report, reason):
    for run in runs_of(report["id"]):
        if run["status"] == "COMPLETED":
            run["status"] = "STALE"
            run["stale_reason"] = reason
            touch(run)


def invalidate_allocation(report, reason):
    """Demote every COMPLETED run and stale the report unless a newer run stands."""
    demote_completed_runs(report, reason)
    if completed_run(report["id"]) is None:
        mark_allocation_stale(report)


def stale_when_completed_run(report):
    """Cost-center creation and ledger mapping stale the allocation without
    demoting the run itself (PRD 3.2 / 3.3)."""
    if completed_run(report["id"]) is not None:
        mark_allocation_stale(report)


# ------------------------------------------------------------ stepdown
def _weight(receiver, basis):
    if not basis or basis == "NONE":
        return Fraction(0)
    raw = receiver.get("statistics", {}).get(basis)
    if raw is None:
        return Fraction(0)
    return F(raw)


def distribute(pool_cents, basis, receivers):
    """Pinned rounding order: exact share, floor per receiver, spread remainder."""
    eligible = []
    for receiver in receivers:
        weight = _weight(receiver, basis)
        if weight > 0:
            eligible.append([receiver, weight, None, 0])
    if not eligible:
        return [], pool_cents

    total_weight = sum(item[1] for item in eligible)
    for item in eligible:
        exact = Fraction(pool_cents) * item[1] / total_weight
        item[2] = exact
        item[3] = exact.numerator // exact.denominator

    remainder = pool_cents - sum(item[3] for item in eligible)
    order = sorted(
        range(len(eligible)),
        key=lambda i: (-(eligible[i][2] - eligible[i][3]),
                       eligible[i][0]["created_at"], eligible[i][0]["_seq"]))
    for index in order[:remainder]:
        eligible[index][3] += 1
    return [(item[0], item[3]) for item in eligible], 0


def general_service_centers(report_id):
    centers = [c for c in centers_of(report_id) if c["center_type"] == "GENERAL_SERVICE"]
    return sorted(centers, key=lambda c: (c["stepdown_order"], c["created_at"], c["_seq"]))


def has_duplicate_stepdown_order(report_id):
    seen = set()
    for center in general_service_centers(report_id):
        if center["stepdown_order"] in seen:
            return True
        seen.add(center["stepdown_order"])
    return False


def execute_stepdown(report, method):
    centers = centers_of(report["id"])
    gs_centers = general_service_centers(report["id"])
    others = [c for c in centers if c["center_type"] != "GENERAL_SERVICE"]
    lines = []
    residual_total = 0

    def record(pass_no, allocator, receiver, amount):
        lines.append({
            "pass": pass_no,
            "from_cost_center_id": allocator["id"],
            "to_cost_center_id": receiver["id"],
            "amount_cents": amount,
        })

    if method == "SINGLE_APPORTIONMENT":
        accumulator = {c["id"]: c["post_adjustment_cost_cents"] for c in centers}
        for index, allocator in enumerate(gs_centers):
            receivers = others + gs_centers[index + 1:]
            shares, residual = distribute(
                accumulator[allocator["id"]], allocator["allocation_basis"], receivers)
            for receiver, amount in shares:
                accumulator[receiver["id"]] += amount
                record(1, allocator, receiver, amount)
            accumulator[allocator["id"]] = residual
            residual_total += residual
    else:
        received = {c["id"]: 0 for c in centers}
        for allocator in gs_centers:
            receivers = [c for c in centers if c["id"] != allocator["id"]]
            shares, residual = distribute(
                allocator["post_adjustment_cost_cents"], allocator["allocation_basis"], receivers)
            for receiver, amount in shares:
                received[receiver["id"]] += amount
                record(1, allocator, receiver, amount)
            residual_total += residual
        for allocator in gs_centers:
            shares, residual = distribute(
                received[allocator["id"]], allocator["allocation_basis"], others)
            for receiver, amount in shares:
                record(2, allocator, receiver, amount)
            residual_total += residual

    return lines, residual_total


def publish_allocation(report, lines):
    """Cascade links 1 to 4 of the completed-stepdown cascade."""
    allocated_in = {}
    allocated_out = {}
    for line in lines:
        allocated_in[line["to_cost_center_id"]] = (
            allocated_in.get(line["to_cost_center_id"], 0) + line["amount_cents"])
        allocated_out[line["from_cost_center_id"]] = (
            allocated_out.get(line["from_cost_center_id"], 0) + line["amount_cents"])

    total_allowable = 0
    for center in centers_of(report["id"]):
        received = allocated_in.get(center["id"], 0)
        distributed = allocated_out.get(center["id"], 0)
        total = center["post_adjustment_cost_cents"] + received - distributed
        apply_changes(center, {
            "allocated_in_cents": received,
            "allocated_out_cents": distributed,
            "allocated_total_cost_cents": total,
        })
        if center["center_type"] in ("ROUTINE", "ANCILLARY"):
            total_allowable += total

    report["total_allowable_cost_cents"] = total_allowable
    report["cost_to_charge_ratio"] = cost_to_charge(total_allowable, report["total_charges_cents"])
    report["allocation_status"] = "CURRENT"

    for data_set in ucc_of(report["id"]):
        compile_ucc(report, data_set)

    for settlement in settlements_of(report["id"]):
        if (settlement["status"] == "ISSUED"
                and settlement["basis_allowable_cost_cents"] != total_allowable):
            apply_changes(settlement, {"recompute_required": True})


def cost_to_charge(total_allowable_cents, total_charges_cents):
    if not total_charges_cents:
        return Decimal("0.000000")
    return rhu(Fraction(total_allowable_cents, total_charges_cents), 6)


# ------------------------------------------------------- average hourly wage
def recompute_ahw(submission):
    """average_hourly_wage: pooled variant plus the occ-mix weighted variant."""
    responses = occ_of(submission["id"])
    for response in responses:
        hours = F(response["reported_hours"])
        category_ahw = None
        if hours != 0:
            category_ahw = rhu_int(F(response["reported_salaries_cents"]) / hours)
        apply_changes(response, {"category_ahw_cents": category_ahw})

    reported_total = Fraction(0)
    for response in responses:
        reported_total += F(response["reported_hours"])
    active = [r for r in responses if F(r["reported_hours"]) > 0]
    count = len(active)

    allowed = min(
        submission["wage_related_costs_cents"],
        floor_int(F(submission["total_salaries_cents"]) * WAGE_RELATED_COST_CAP_PCT))

    if F(submission["contract_labor_hours"]) == 0:
        labor_cents = 0
        labor_hours = Fraction(0)
    else:
        labor_cents = submission["contract_labor_cents"]
        labor_hours = F(submission["contract_labor_hours"])

    numerator = (submission["total_salaries_cents"] + allowed + labor_cents
                 - submission["excluded_area_salaries_cents"])
    denominator = (F(submission["total_paid_hours"]) + labor_hours
                   - F(submission["excluded_area_hours"]))
    unadjusted = 0 if denominator == 0 else rhu_int(F(numerator) / denominator)

    adjusted = None
    if count >= OCC_MIX_MIN_CATEGORIES:
        base = sum(NATIONAL_TARGET_PCT[r["category"]] for r in active)
        weights = {}
        for response in active:
            weights[response["id"]] = rhu(NATIONAL_TARGET_PCT[response["category"]] / base, 6)
        drift = Decimal("1.000000")
        for value in weights.values():
            drift -= value
        anchor = sorted(
            active, key=lambda r: (-NATIONAL_TARGET_PCT[r["category"]], r["category"]))[0]
        weights[anchor["id"]] = weights[anchor["id"]] + drift
        weighted = Fraction(0)
        for response in active:
            weighted += F(weights[response["id"]]) * F(response["category_ahw_cents"])
        adjusted = rhu_int(weighted)

    effective = adjusted if count >= OCC_MIX_MIN_CATEGORIES else unadjusted
    apply_changes(submission, {
        "allowed_wage_related_costs_cents": allowed,
        "unadjusted_ahw_cents": unadjusted,
        "occ_mix_adjusted_ahw_cents": adjusted,
        "occ_mix_category_count": count,
        "effective_ahw_cents": effective,
        "reported_hours_total": dec(reported_total, 2),
    })


def reported_hours_total(submission):
    total = Fraction(0)
    for response in occ_of(submission["id"]):
        total += F(response["reported_hours"])
    return total


# --------------------------------------------------------------------- GME
def recompute_gme(report):
    """gme_fte_rolling_average; returns (period_days, prior_period_count)."""
    provider = db.providers[report["provider_id"]]
    begin = as_date(report["fiscal_year_begin"])
    period_end = as_date(report["fiscal_year_end"]) + timedelta(days=1)
    period_days = (period_end - begin).days
    center_ids = set(c["id"] for c in centers_of(report["id"]))

    days_total = Fraction(0)
    for rotation in ordered(list(db.rotation_assignments.values())):
        if rotation["cost_center_id"] not in center_ids:
            continue
        if rotation["status"] != "ACTIVE":
            apply_changes(rotation, {"fte_days": Decimal("0.0000")})
            continue
        overlap = overlap_days(rotation, begin, period_end)
        fte_days = rhu(F(rotation["fte_fraction"]) * overlap, 4)
        apply_changes(rotation, {"overlap_days": overlap, "fte_days": fte_days})
        days_total += F(fte_days)
    report["unweighted_fte_days_total"] = dec(days_total, 4)

    residents = residents_of(provider["id"])
    resident_fte = {}
    for resident in residents:
        assigned = Fraction(0)
        for rotation in rotations_of_resident(resident["id"]):
            if rotation["status"] == "ACTIVE":
                assigned += F(rotation["fte_days"])
        apply_changes(resident, {"assigned_fte_days": dec(assigned, 4)})
        share = rhu(assigned / period_days, 4) if period_days else Decimal("0.0000")
        if share > Decimal("1.0000"):
            share = Decimal("1.0000")
        resident_fte[resident["id"]] = share

    unweighted_sum = Fraction(0)
    weighted_sum = Fraction(0)
    for resident in residents:
        share = F(resident_fte[resident["id"]])
        unweighted_sum += share
        weighted_sum += share * (
            WITHIN_IRP_WEIGHT if resident["irp_status"] == "WITHIN_IRP" else BEYOND_IRP_WEIGHT)

    unweighted_total = rhu(unweighted_sum, 2)
    capped = min(unweighted_total, dec(provider["fte_cap"], 2))
    weighted_total = rhu(weighted_sum, 2)

    priors = [r for r in reports_of(provider["id"])
              if r["status"] == "FINAL_SETTLED"
              and r["id"] != report["id"]
              and r["fiscal_year_end"] < report["fiscal_year_end"]]
    priors.sort(key=lambda r: r["fiscal_year_end"], reverse=True)
    priors = priors[:2]
    rolling_sum = F(capped)
    for prior in priors:
        rolling_sum += F(prior["capped_unweighted_fte"])
    rolling = rhu(rolling_sum / (1 + len(priors)), 2)

    report["unweighted_fte_total"] = unweighted_total
    report["capped_unweighted_fte"] = capped
    report["weighted_fte_total"] = weighted_total
    report["rolling_average_fte"] = rolling
    return period_days, len(priors)


def overlap_days(rotation, period_begin, period_end):
    start = as_date(rotation["start_date"])
    end = as_date(rotation["end_date"])
    low = max(start, period_begin)
    high = min(end, period_end)
    return (high - low).days if high > low else 0


def daily_fte_exceeded(resident_id, start, end, fraction, skip_id=None):
    """Event sweep over the half-open interval [start, end)."""
    events = {start: F(fraction), end: -F(fraction)}
    for rotation in rotations_of_resident(resident_id):
        if rotation["status"] != "ACTIVE" or rotation["id"] == skip_id:
            continue
        other_start = as_date(rotation["start_date"])
        other_end = as_date(rotation["end_date"])
        if other_end <= start or other_start >= end:
            continue
        weight = F(rotation["fte_fraction"])
        events[other_start] = events.get(other_start, Fraction(0)) + weight
        events[other_end] = events.get(other_end, Fraction(0)) - weight
    running = Fraction(0)
    for moment in sorted(events):
        if moment >= end:
            break
        running += events[moment]
        if moment >= start and running > RESIDENT_DAILY_FTE_CAP:
            return True
    return False


# --------------------------------------------------------------- DSH / UCC
def compile_ucc(report, data_set):
    """dsh_and_ucc_compilation; each fraction is rounded before they are summed."""
    medicaid = rhu(Fraction(data_set["medicaid_non_medicare_days"],
                            data_set["total_inpatient_days"]), 4)
    ssi = rhu(Fraction(data_set["ssi_days"], data_set["medicare_part_a_days"]), 4)
    dsh = rhu(F(medicaid) + F(ssi), 4)
    eligible = dsh >= DSH_ELIGIBILITY_THRESHOLD
    ratio = dec(report["cost_to_charge_ratio"], 6)
    cost = (rhu_int(F(data_set["charity_care_charges_cents"]) * F(ratio))
            + rhu_int(F(data_set["non_medicare_bad_debt_cents"]) * BAD_DEBT_ALLOWABLE_FACTOR))
    payment = 0
    if eligible:
        payment = floor_int(Fraction(UCC_POOL_CENTS * cost, NATIONAL_UCC_COST_CENTS))
    apply_changes(data_set, {
        "medicaid_fraction": medicaid,
        "ssi_fraction": ssi,
        "dsh_patient_percentage": dsh,
        "dsh_eligible": eligible,
        "cost_to_charge_ratio": ratio,
        "uncompensated_care_cost_cents": cost,
        "ucc_payment_cents": payment,
        "recompute_required": False,
    })


# ------------------------------------------------------------- settlement
def compute_settlement(report, stage, basis_run):
    basis_allowable = report["total_allowable_cost_cents"]
    reimbursable = rhu_int(F(basis_allowable) * F(report["medicare_utilization_ratio"]))
    interim_paid = report["interim_payments_received_cents"]
    if stage == "TENTATIVE":
        ucc_payment = 0
        prior_paid = 0
        amount = rhu_int(TENTATIVE_PAYMENT_PCT * Fraction(reimbursable - interim_paid))
    else:
        data_sets = ucc_of(report["id"])
        ucc_payment = data_sets[0]["ucc_payment_cents"] if data_sets else 0
        prior_paid = 0
        for settlement in settlements_of(report["id"]):
            if settlement["stage"] == "TENTATIVE" and settlement["status"] != "SUPERSEDED":
                prior_paid += settlement["amount_due_provider_cents"]
        amount = (reimbursable - interim_paid) + ucc_payment - prior_paid
    return {
        "basis_method": basis_run["method"],
        "basis_allowable_cost_cents": basis_allowable,
        "reimbursable_cost_cents": reimbursable,
        "ucc_payment_cents": ucc_payment,
        "prior_tentative_paid_cents": prior_paid,
        "amount_due_provider_cents": amount,
    }


def allowable_cost_per_discharge(report):
    if not report["medicare_discharges"]:
        return 0
    return rhu_int(Fraction(report["total_allowable_cost_cents"], report["medicare_discharges"]))


# ---------------------------------------------------------- interim rates
def project_interim_rate(provider, basis_report, trend_factor, projected_discharges):
    """Returns (projection, variance_ratio, approved_rate, adjustment_amount)."""
    current = provider["current_interim_rate_cents"]
    projection = rhu_int(
        F(basis_report["allowable_cost_per_discharge_cents"]) * (Fraction(1) + F(trend_factor)))
    variance = rhu(Fraction(abs(projection - current), current), 4)
    cap = floor_int(Fraction(current) * INTERIM_RATE_CAP_MULTIPLIER)
    approved = min(projection, cap)
    adjustment = (approved - current) * projected_discharges
    return projection, variance, approved, adjustment


def interim_period_conflict(provider_id, effective_from, effective_to):
    buffer_days = timedelta(days=INTERIM_PERIOD_BUFFER_DAYS)
    for request in interim_requests_of(provider_id):
        if request["status"] in ("DENIED", "SUPERSEDED"):
            continue
        other_from = as_date(request["effective_from"])
        other_to = as_date(request["effective_to"])
        if effective_from <= other_to + buffer_days and effective_to >= other_from - buffer_days:
            return True
    return False


def active_submission(report_id):
    for submission in submissions_of(report_id):
        if submission["status"] != "REJECTED":
            return submission
    return None
