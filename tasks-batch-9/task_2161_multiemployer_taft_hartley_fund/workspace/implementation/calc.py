"""Calculation rules (PRD sections 2.6, 3.2 - 3.10)."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

from store import (
    db,
    month_add,
    month_index,
    plan_year_end_date,
    plan_year_of,
    sorted_rows,
    touch,
    values,
)

getcontext().prec = 60

# ----- constants pinned by the scaffold -------------------------------
CLASS_MULTIPLIER_BPS = {"JOURNEYMAN": 10000, "APPRENTICE": 5000, "FOREMAN": 12500}
MILLICENT_DIVISOR = Decimal(10000000)
AUDIT_CLASS_MULTIPLIER_BPS = 10000
DAYS_PER_YEAR = Decimal(365)
LD_TIER_SMALL_BPS = 500
LD_TIER_MID_BPS = 1000
LD_TIER_LARGE_BPS = 2000
QUARTER_CREDIT_HOURS = Decimal(250)
VESTING_HOURS_THRESHOLD = Decimal(870)
BREAK_HOURS = Decimal(375)
BREAK_YEARS_LIMIT = 5
VESTING_YEARS_REQUIRED = 5
DE_MINIMIS_CAP_CENTS = 750000
DE_MINIMIS_FRACTION_BPS = 75
PHASEOUT_START_CENTS = 10000000
FRACTION_DECIMALS = 10
MAX_SCHEDULE_YEARS = 20
INSTALLMENT_FIRST_OFFSET_DAYS = 60
INSTALLMENT_INTERVAL_DAYS = 365
CURE_DAYS = 60
DELINQUENCY_STRIKE_LIMIT = 3
MAX_AUDIT_ROUNDS = 3
MIN_TRUSTEES_PER_PARTY = 2
QUORUM_PER_PARTY = 2

ALLOCATING_STATUSES = (
    "CERTIFIED",
    "DEMANDED",
    "REVIEW_REQUESTED",
    "PAYMENT_ACTIVE",
    "ACCELERATED",
    "SATISFIED",
)


def rhu(value, places=0):
    """round half up to `places` decimals."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def d2(value):
    return rhu(value, 2)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------
# governance posture
# ---------------------------------------------------------------------
def recompute_governance(fund):
    u = 0
    e = 0
    for t in db.trustees.values():
        if t["fund_id"] != fund["id"] or t["seat_status"] != "ACTIVE":
            continue
        if t["appointing_party"] == "UNION":
            u += 1
        else:
            e += 1
    fund["active_union_trustees"] = u
    fund["active_employer_trustees"] = e
    if u == 0 or e == 0:
        fund["governance_posture"] = "FROZEN"
    elif u != e or min(u, e) < MIN_TRUSTEES_PER_PARTY:
        fund["governance_posture"] = "RESTRICTED"
    else:
        fund["governance_posture"] = "OPEN"
    return fund


def recompute_fund_derived(fund):
    recompute_governance(fund)
    fund["unallocated_uvb_cents"] = fund["total_uvb_cents"] - fund["allocated_uvb_cents"]
    return fund


def recompute_suspended_employer_count(fund):
    fund["suspended_employer_count"] = sum(
        1
        for e in db.employers.values()
        if e["fund_id"] == fund["id"] and e["status"] == "SUSPENDED"
    )
    return fund


def recompute_reciprocal_receipts(fund):
    total = 0
    for t in db.transfers.values():
        if t["status"] != "ACCEPTED":
            continue
        p = db.participants.get(t["participant_id"])
        if p is not None and p["fund_id"] == fund["id"]:
            total += t["amount_cents"]
    fund["reciprocal_receipts_cents"] = total
    return fund


# ---------------------------------------------------------------------
# contribution pricing
# ---------------------------------------------------------------------
def line_contribution_cents(hours, rate_millicents, work_classification):
    mult = CLASS_MULTIPLIER_BPS[work_classification]
    exact = dec(hours) * Decimal(rate_millicents) * Decimal(mult) / MILLICENT_DIVISOR
    return rhu_int(exact)


def report_lines(report_id):
    rows = [l for l in db.lines.values() if l["report_id"] == report_id]
    return sorted_rows(rows)


def recompute_report_totals(report):
    emp = db.employers[report["employer_id"]]
    total = 0
    hours_sum = Decimal("0")
    for line in report_lines(report["id"]):
        cents = line_contribution_cents(
            line["hours"], emp["contribution_rate_millicents_per_hour"], line["work_classification"]
        )
        line["contribution_cents"] = cents
        total += cents
        hours_sum += dec(line["hours"])
    report["total_contributions_due_cents"] = total
    report["total_hours_reported"] = d2(hours_sum)
    return report


def audit_underpayment(findings, rate_millicents):
    total = 0
    hours_sum = Decimal("0")
    for f in findings:
        exact = (
            dec(f["unreported_hours"])
            * Decimal(rate_millicents)
            * Decimal(AUDIT_CLASS_MULTIPLIER_BPS)
            / MILLICENT_DIVISOR
        )
        total += rhu_int(exact)
        hours_sum += dec(f["unreported_hours"])
    return d2(hours_sum), total


# ---------------------------------------------------------------------
# employer delinquency ledger
# ---------------------------------------------------------------------
def recompute_employer_ledger(emp):
    unpaid = 0
    report_ids = set()
    for r in db.reports.values():
        if r["employer_id"] != emp["id"]:
            continue
        report_ids.add(r["id"])
        if r["filing_status"] == "SUPERSEDED":
            continue
        if r["payment_status"] in ("UNPAID", "PARTIAL", "DELINQUENT"):
            unpaid += r["total_contributions_due_cents"] - r["amount_remitted_cents"]
    open_assessments = 0
    for a in db.assessments.values():
        if a["status"] == "ASSESSED" and a["report_id"] in report_ids:
            open_assessments += a["total_cents"]
    emp["cumulative_delinquent_cents"] = unpaid + open_assessments
    return emp


def restore_if_cleared(emp):
    """A ledger back at 0 lifts a suspension (PRD 3.6)."""
    if emp["cumulative_delinquent_cents"] == 0 and emp["status"] == "SUSPENDED":
        emp["status"] = "ACTIVE"
        emp["delinquency_strikes"] = 0
        fund = db.funds.get(emp["fund_id"])
        if fund is not None:
            recompute_suspended_employer_count(fund)
            touch(fund)
        return True
    return False


def ledger_cascade(emp):
    """Recompute the ledger, lift a suspension when it clears, and touch the row."""
    before = (
        emp["cumulative_delinquent_cents"],
        emp["status"],
        emp["delinquency_strikes"],
    )
    recompute_employer_ledger(emp)
    restore_if_cleared(emp)
    after = (
        emp["cumulative_delinquent_cents"],
        emp["status"],
        emp["delinquency_strikes"],
    )
    if before != after:
        touch(emp)
    return emp


# ---------------------------------------------------------------------
# delinquency charges
# ---------------------------------------------------------------------
def ld_tier_bps(days_late):
    if days_late <= 30:
        return LD_TIER_SMALL_BPS
    if days_late <= 60:
        return LD_TIER_MID_BPS
    return LD_TIER_LARGE_BPS


def delinquency_charges(basis, principal, days_late, fund):
    p = Decimal(principal)
    if basis == "STATUTORY":
        interest = rhu_int(
            p * Decimal(fund["interest_rate_annual_bps"]) * Decimal(days_late)
            / (Decimal(10000) * DAYS_PER_YEAR)
        )
        flat = rhu_int(p * Decimal(fund["ld_rate_bps"]) / Decimal(10000))
        ld = max(interest, flat)
    else:
        effective_days = max(0, days_late - fund["grace_days"])
        interest = rhu_int(
            p * Decimal(fund["interest_rate_annual_bps"]) * Decimal(effective_days)
            / (Decimal(10000) * DAYS_PER_YEAR)
        )
        tier = ld_tier_bps(days_late)
        tiered = rhu_int(p * Decimal(tier) / Decimal(10000))
        ld = max(tiered, fund["ld_floor_cents"])
    return interest, ld


# ---------------------------------------------------------------------
# withdrawal liability allocation + payment schedule
# ---------------------------------------------------------------------
def best_window_start(arr):
    best_i = 0
    best_sum = None
    for i in (0, 1, 2):
        s = sum(arr[i:i + 3])
        if best_sum is None or s > best_sum:
            best_sum = s
            best_i = i
    return best_i, best_sum


def employer_share_fraction(method, employer, fund):
    if method == "PRESUMPTIVE":
        num = sum(employer["prior_year_contributions_cents"])
        den = sum(fund["pool_prior_year_contributions_cents"])
    else:
        i, num = best_window_start(employer["prior_year_contributions_cents"])
        den = sum(fund["pool_prior_year_contributions_cents"][i:i + 3])
    if den == 0:
        return Decimal(0).quantize(Decimal(1).scaleb(-FRACTION_DECIMALS))
    return rhu(Decimal(num) / Decimal(den), FRACTION_DECIMALS)


def compute_allocation(assessment, employer, fund, pool):
    fraction = employer_share_fraction(assessment["method"], employer, fund)
    raw = rhu_int(Decimal(pool) * fraction)
    de_minimis = min(
        DE_MINIMIS_CAP_CENTS,
        rhu_int(Decimal(fund["total_uvb_cents"]) * Decimal(DE_MINIMIS_FRACTION_BPS) / Decimal(10000)),
    )
    excess = max(0, raw - PHASEOUT_START_CENTS)
    reduction = max(0, de_minimis - excess)
    net = raw - reduction
    assessment["employer_share_fraction"] = fraction
    assessment["raw_allocation_cents"] = raw
    assessment["de_minimis_reduction_cents"] = reduction
    assessment["net_liability_cents"] = net
    return assessment


def compute_schedule(assessment, employer):
    """Returns annual_payment_cents; 0 means ERR_NO_PAYMENT_BASE."""
    j, base_sum = best_window_start(employer["prior_year_base_units"])
    avg = rhu_int(Decimal(base_sum) / Decimal(3))
    annual = rhu_int(
        Decimal(avg) * Decimal(employer["contribution_rate_millicents_per_hour"]) / Decimal(1000)
    )
    assessment["annual_payment_cents"] = annual
    if annual == 0:
        assessment["schedule_years"] = 0
        assessment["twenty_year_cap_applied"] = False
        assessment["capped_liability_cents"] = 0
        return 0
    net = assessment["net_liability_cents"]
    uncapped = -((-net) // annual)  # ceil division
    if uncapped > MAX_SCHEDULE_YEARS:
        assessment["twenty_year_cap_applied"] = True
        assessment["schedule_years"] = MAX_SCHEDULE_YEARS
        assessment["capped_liability_cents"] = annual * MAX_SCHEDULE_YEARS
    else:
        assessment["twenty_year_cap_applied"] = False
        assessment["schedule_years"] = int(uncapped)
        assessment["capped_liability_cents"] = net
    return annual


def installment_amount(assessment, k):
    years = assessment["schedule_years"]
    annual = assessment["annual_payment_cents"]
    if k < years:
        return annual
    return assessment["capped_liability_cents"] - annual * (years - 1)


# ---------------------------------------------------------------------
# motion bloc tally
# ---------------------------------------------------------------------
def bloc_position(motion_id, party):
    for_n = 0
    agn_n = 0
    for v in db.votes.values():
        if v["motion_id"] != motion_id:
            continue
        t = db.trustees.get(v["trustee_id"])
        if t is None or t["appointing_party"] != party:
            continue
        if v["position"] == "FOR":
            for_n += 1
        elif v["position"] == "AGAINST":
            agn_n += 1
    counted = for_n + agn_n
    if for_n > agn_n:
        pos = "FOR"
    elif agn_n > for_n:
        pos = "AGAINST"
    else:
        pos = "TIED"
    return counted, pos


# ---------------------------------------------------------------------
# participant eligibility replay (PRD 3.4)
# ---------------------------------------------------------------------
def participant_coverage_months(participant_id):
    return sorted_rows([c for c in db.coverage_months.values() if c["participant_id"] == participant_id])


def outstanding_advance_months(participant_id):
    clock_month = db.clock_month
    return sum(
        1
        for c in db.coverage_months.values()
        if c["participant_id"] == participant_id
        and c["status"] == "GRANTED"
        and c["coverage_month"] > clock_month
    )


def eligibility_status(participant):
    ctm = participant.get("coverage_through_month")
    if ctm is not None and ctm >= db.clock_month:
        return "ELIGIBLE"
    return "NOT_ELIGIBLE"


def _mint_coverage_month(participant, month, granting_report_id, source, hours_applied):
    from store import new_row

    return new_row(
        db.coverage_months,
        {
            "participant_id": participant["id"],
            "coverage_month": month,
            "granting_report_id": granting_report_id,
            "source": source,
            "hours_applied": hours_applied,
            "status": "GRANTED",
        },
    )


def eligibility_replay(participant):
    """Full rebuild of the participant's welfare eligibility. Returns
    {transfer_id: months_granted_by_that_transfer_event}."""
    fund = db.funds[participant["fund_id"]]
    hpcm = Decimal(fund["hours_per_coverage_month"])
    bank_cap = dec(fund["bank_cap_hours"])
    lag = fund["eligibility_lag_months"]
    max_advance = fund["max_advance_coverage_months"]

    # STEP 0 - wipe
    for cm in participant_coverage_months(participant["id"]):
        if cm["status"] == "GRANTED":
            cm["status"] = "REVOKED"
            touch(cm)
    participant["hour_bank_hours"] = Decimal("0.00")
    participant["forfeited_hours_total"] = Decimal("0.00")
    participant["coverage_through_month"] = None

    # STEP 1 - credit events
    events = []
    for line in db.lines.values():
        if line["participant_id"] != participant["id"]:
            continue
        rep = db.reports.get(line["report_id"])
        if rep is None or rep["filing_status"] != "POSTED":
            continue
        events.append(
            {
                "month": rep["work_period"],
                "hours": dec(line["hours"]),
                "report_id": rep["id"],
                "kind": "CONTRIBUTION",
                "created_at": line["created_at"],
                "seq": line["_seq"],
                "transfer_id": None,
            }
        )
    for t in db.transfers.values():
        if t["participant_id"] != participant["id"] or t["status"] != "ACCEPTED":
            continue
        events.append(
            {
                "month": t["work_period"],
                "hours": dec(t["hours"]),
                "report_id": None,
                "kind": "RECIPROCAL",
                "created_at": t["created_at"],
                "seq": t["_seq"],
                "transfer_id": t["id"],
            }
        )

    # STEP 2 - sort by month ASC then the underlying row's created_at ASC
    events.sort(key=lambda e: (month_index(e["month"]), e["created_at"], e["seq"]))

    granted_per_transfer = {}
    contribution_hours = Decimal("0")
    reciprocal_hours = Decimal("0")

    # STEP 3 - replay
    for ev in events:
        if ev["kind"] == "CONTRIBUTION":
            contribution_hours += ev["hours"]
        else:
            reciprocal_hours += ev["hours"]
        available = dec(participant["hour_bank_hours"]) + ev["hours"]
        outstanding = outstanding_advance_months(participant["id"])
        allowance = max_advance - outstanding
        by_hours = int(available // hpcm) if hpcm > 0 else 0
        months = min(by_hours, max(0, allowance))
        consumed = Decimal(months) * hpcm
        leftover = available - consumed
        forfeited = leftover - bank_cap
        if forfeited < 0:
            forfeited = Decimal("0")
        participant["forfeited_hours_total"] = d2(dec(participant["forfeited_hours_total"]) + forfeited)
        participant["hour_bank_hours"] = d2(min(bank_cap, leftover))

        first_month = month_add(ev["month"], lag)
        ctm = participant["coverage_through_month"]
        if ctm is not None:
            nxt = month_add(ctm, 1)
            if month_index(nxt) > month_index(first_month):
                first_month = nxt
        if ev["kind"] == "RECIPROCAL":
            source = "RECIPROCAL"
        elif ev["hours"] >= hpcm:
            source = "CURRENT_HOURS"
        else:
            source = "BANK_DRAW"
        for k in range(months):
            _mint_coverage_month(
                participant,
                month_add(first_month, k),
                ev["report_id"],
                source,
                d2(hpcm),
            )
        if months > 0:
            participant["coverage_through_month"] = month_add(first_month, months - 1)
        if ev["transfer_id"] is not None:
            granted_per_transfer[ev["transfer_id"]] = months

    # STEP 4 - totals
    participant["credited_hours_total"] = d2(contribution_hours)
    participant["reciprocal_hours_total"] = d2(reciprocal_hours)
    return granted_per_transfer


# ---------------------------------------------------------------------
# pension accrual (PRD 3.5)
# ---------------------------------------------------------------------
def participant_accruals(participant_id):
    rows = [a for a in db.accruals.values() if a["participant_id"] == participant_id]
    return sorted(rows, key=lambda a: (a["plan_year"], a["_seq"]))


def _get_or_create_accrual(participant, plan_year):
    for a in db.accruals.values():
        if a["participant_id"] == participant["id"] and a["plan_year"] == plan_year:
            return a, False
    from store import new_row

    row = new_row(
        db.accruals,
        {
            "participant_id": participant["id"],
            "plan_year": plan_year,
            "hours_credited": Decimal("0.00"),
            "reciprocal_hours_credited": Decimal("0.00"),
            "pension_credit": Decimal("0.00"),
            "vesting_year_earned": False,
            "break_in_service": False,
            "accrual_status": "OPEN",
            "_erased": False,
        },
    )
    return row, True


def recompute_accruals(participant):
    fund = db.funds[participant["fund_id"]]
    pym = fund["plan_year_start_month"]
    method = fund["accrual_method"]

    posted_lines = []
    for line in db.lines.values():
        if line["participant_id"] != participant["id"]:
            continue
        rep = db.reports.get(line["report_id"])
        if rep is None or rep["filing_status"] != "POSTED":
            continue
        posted_lines.append((plan_year_of(rep["work_period"], pym), dec(line["hours"])))

    accepted_transfers = []
    for t in db.transfers.values():
        if t["participant_id"] != participant["id"] or t["status"] != "ACCEPTED":
            continue
        accepted_transfers.append(
            (plan_year_of(t["work_period"], pym), dec(t["hours"]), t["transfer_type"])
        )

    years = set(y for y, _ in posted_lines)
    years |= set(y for y, _, _ in accepted_transfers)
    years |= set(a["plan_year"] for a in participant_accruals(participant["id"]))

    granted_years = set()
    if method == "ELAPSED_TIME":
        for c in db.coverage_months.values():
            if c["participant_id"] == participant["id"] and c["status"] == "GRANTED":
                granted_years.add(plan_year_of(c["coverage_month"], pym))

    for year in sorted(years):
        row, is_new = _get_or_create_accrual(participant, year)
        before = (
            row["hours_credited"],
            row["reciprocal_hours_credited"],
            row["pension_credit"],
            row["vesting_year_earned"],
            row["break_in_service"],
        )
        hours_credited = sum((h for y, h in posted_lines if y == year), Decimal("0"))
        pro_rata = sum(
            (h for y, h, kind in accepted_transfers if y == year and kind == "PRO_RATA"),
            Decimal("0"),
        )
        any_transfer = sum(
            (h for y, h, kind in accepted_transfers if y == year), Decimal("0")
        )
        row["hours_credited"] = d2(hours_credited)
        row["reciprocal_hours_credited"] = d2(pro_rata)
        countable = dec(row["hours_credited"]) + dec(row["reciprocal_hours_credited"])
        if method == "HOURS_BASED":
            quarters = int(countable // QUARTER_CREDIT_HOURS)
            credit = min(Decimal("1.00"), Decimal(quarters) * Decimal("0.25"))
            vesting = countable >= VESTING_HOURS_THRESHOLD
        else:
            covered = year in granted_years
            credit = Decimal("1.00") if (countable > 0 and covered) else Decimal("0.00")
            vesting = countable > 0
        if row.get("_erased"):
            credit = Decimal("0.00")
            vesting = False
        row["pension_credit"] = d2(credit)
        row["vesting_year_earned"] = bool(vesting)
        row["break_in_service"] = (dec(row["hours_credited"]) + any_transfer) < BREAK_HOURS
        after = (
            row["hours_credited"],
            row["reciprocal_hours_credited"],
            row["pension_credit"],
            row["vesting_year_earned"],
            row["break_in_service"],
        )
        if not is_new and before != after:
            touch(row)

    recompute_participant_rollups(participant)
    return participant


def recompute_consecutive_break_years(participant):
    finalized = [a for a in participant_accruals(participant["id"]) if a["accrual_status"] == "FINALIZED"]
    run = 0
    for a in reversed(finalized):
        if a["break_in_service"]:
            run += 1
        else:
            break
    participant["consecutive_break_years"] = run
    return run


def recompute_participant_rollups(participant):
    rows = participant_accruals(participant["id"])
    participant["vesting_service_years"] = sum(1 for a in rows if a["vesting_year_earned"])
    participant["total_pension_credits"] = d2(
        sum((dec(a["pension_credit"]) for a in rows), Decimal("0"))
    )
    participant["vested"] = participant["vesting_service_years"] >= VESTING_YEARS_REQUIRED
    recompute_consecutive_break_years(participant)
    return participant


def erase_accrued_benefit(participant):
    for a in participant_accruals(participant["id"]):
        changed = a["pension_credit"] != Decimal("0.00") or a["vesting_year_earned"]
        a["pension_credit"] = Decimal("0.00")
        a["vesting_year_earned"] = False
        a["_erased"] = True
        if changed:
            touch(a)
    participant["vesting_service_years"] = 0
    participant["total_pension_credits"] = Decimal("0.00")
    participant["vested"] = False
    return participant


def cascade_participant(participant):
    """Full eligibility + accrual cascade for one participant."""
    eligibility_replay(participant)
    recompute_accruals(participant)
    touch(participant)
    return participant
