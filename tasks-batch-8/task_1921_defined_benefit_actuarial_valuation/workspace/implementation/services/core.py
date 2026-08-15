"""Shared entity helpers, actuarial calculations, and cascade logic.

All monetary amounts and percentages use Decimal with ROUND_HALF_UP at the
pinned precision: 2dp for money/percent, 4dp for annuity factors (rounded
BEFORE benefit multiplication), per-participant cent rounding BEFORE
aggregation.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, fmt_ts, new_id, parse_iso
from errors import not_found

# ---------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------

CENT = Decimal("0.01")
FACTOR_Q = Decimal("0.0001")


def D(value):
    """Coerce a JSON number / stored value to Decimal exactly."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not numeric")


def r2(value):
    """Round Decimal to 2dp half-up; return float for JSON."""
    return float(D(value).quantize(CENT, rounding=ROUND_HALF_UP))


def r2d(value):
    """Round Decimal to 2dp half-up; keep Decimal."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def r4d(value):
    """Round Decimal to 4dp half-up; keep Decimal."""
    return D(value).quantize(FACTOR_Q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# generic record factory / touch
# ---------------------------------------------------------------------------

def base_record():
    ts = store.now_str()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = store.now_str()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip private keys (underscore-prefixed)."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# getters with 404
# ---------------------------------------------------------------------------

def _get(mapping, rid, label):
    rec = mapping.get(rid)
    if rec is None:
        raise not_found(f"{label} not found")
    return rec


def get_plan(pid):
    return _get(store.plans, pid, "Plan")


def get_actuary(aid):
    return _get(store.actuaries, aid, "Actuary")


def get_batch(bid):
    return _get(store.census_batches, bid, "CensusBatch")


def get_participant(pid):
    return _get(store.participants, pid, "Participant")


def get_aset(sid):
    return _get(store.assumption_sets, sid, "AssumptionSet")


def get_asset_valuation(aid):
    return _get(store.asset_valuations, aid, "AssetValuation")


def get_run(rid):
    return _get(store.valuation_runs, rid, "ValuationRun")


def get_election(eid):
    return _get(store.credit_balance_elections, eid, "CreditBalanceElection")


def get_demand(did):
    return _get(store.contribution_demands, did, "ContributionDemand")


def get_filing(fid):
    return _get(store.pbgc_filings, fid, "PBGCFiling")


def get_report(rid):
    return _get(store.disclosure_reports, rid, "DisclosureReport")


# ---------------------------------------------------------------------------
# calendar anchors (all midnight UTC, pinned to the plan year)
# ---------------------------------------------------------------------------

def year_dt(plan_year, month, day):
    return datetime(plan_year, month, day, 0, 0, 0, tzinfo=timezone.utc)


def due_date_for(plan_year):
    return year_dt(plan_year, 9, 15)


def filing_deadline_for(plan_year):
    return year_dt(plan_year, 10, 15)


def april_cutoff_for(plan_year):
    return year_dt(plan_year, 4, 1)


def october_deemed_for(plan_year):
    return year_dt(plan_year, 10, 1)


# ---------------------------------------------------------------------------
# annuity factors — pinned mortality table TEST_TABLE_4AGE
# ---------------------------------------------------------------------------

Q_TABLE = {
    60: Decimal("0.20"),
    61: Decimal("0.25"),
    62: Decimal("0.50"),
    63: Decimal("1.00"),
}
OMEGA_AGE = 63


def _survival(age, t):
    """Product over k=0..t-1 of (1 - q[age+k]); survival(age, 0) == 1."""
    p = Decimal(1)
    for k in range(t):
        q = Q_TABLE.get(age + k, Decimal(1))
        p *= (Decimal(1) - q)
    return p


def _af_immediate(age, rate):
    """Immediate annuity factor: sum t=0..(omega-age) of v^t * survival(age, t)."""
    age = max(60, min(OMEGA_AGE, age))
    v = Decimal(1) / (Decimal(1) + rate)
    total = Decimal(0)
    for t in range(0, OMEGA_AGE - age + 1):
        total += (v ** t) * _survival(age, t)
    return total


def annuity_factor(age, nra, rate):
    """AF(age, nra) rounded half-up to 4dp. Deferred when age < nra."""
    if age >= nra:
        af = _af_immediate(age, rate)
    else:
        v = Decimal(1) / (Decimal(1) + rate)
        af = (v ** (nra - age)) * _survival(age, nra - age) * _af_immediate(nra, rate)
    return r4d(af)


def annuity_factor_immediate(age, rate):
    """Immediate-only factor (RETIREE basis), 4dp half-up."""
    return r4d(_af_immediate(age, rate))


def attained_age(plan_year, date_of_birth):
    """Attained age = plan_year - birth year (month/day ignored)."""
    dob = parse_iso(date_of_birth) if "T" in str(date_of_birth) else datetime.fromisoformat(str(date_of_birth)).replace(tzinfo=timezone.utc)
    return plan_year - dob.year


# ---------------------------------------------------------------------------
# participant screening (business-level row rules, adjudicated at screening)
# ---------------------------------------------------------------------------

def screen_participant_row(participant, plan_year):
    """Return a list of error strings for a stored participant row."""
    errs = []
    try:
        age = attained_age(plan_year, participant.get("date_of_birth"))
        if age < 60 or age > 63:
            errs.append("attained age outside pinned mortality domain [60, 63]")
    except Exception:
        errs.append("date_of_birth is not a valid ISO date")
    status = participant.get("status")
    if status not in ("ACTIVE", "TERMINATED_VESTED", "RETIREE"):
        errs.append("status is not a recognized participant status")
        return errs

    def _nonneg(field):
        v = participant.get(field)
        if v is None:
            return
        try:
            if D(v) < 0:
                errs.append(f"{field} must be non-negative")
        except Exception:
            errs.append(f"{field} must be a number")

    if status == "ACTIVE":
        if participant.get("years_of_service") is None:
            errs.append("years_of_service is required for ACTIVE participants")
        if participant.get("annual_compensation") is None:
            errs.append("annual_compensation is required for ACTIVE participants")
        _nonneg("years_of_service")
        _nonneg("annual_compensation")
    elif status == "TERMINATED_VESTED":
        if participant.get("deferred_benefit_annual") is None:
            errs.append("deferred_benefit_annual is required for TERMINATED_VESTED participants")
        _nonneg("deferred_benefit_annual")
    elif status == "RETIREE":
        if participant.get("current_annual_benefit") is None:
            errs.append("current_annual_benefit is required for RETIREE participants")
        _nonneg("current_annual_benefit")
    return errs


def batch_participants(batch_id):
    rows = [p for p in store.participants.values() if p["census_batch_id"] == batch_id]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return rows


def recompute_batch_counts(batch):
    batch["participant_count"] = len(batch_participants(batch["id"]))


# ---------------------------------------------------------------------------
# AFTAP / posture
# ---------------------------------------------------------------------------

def certified_run_for_plan(plan_id):
    """The plan's currently CERTIFIED ValuationRun, or None."""
    current = None
    for r in store.valuation_runs.values():
        if r["plan_id"] == plan_id and r["status"] == "CERTIFIED":
            if current is None or (r["created_at"], r["_seq"]) > (current["created_at"], current["_seq"]):
                current = r
    return current


def posture_for_pct(pct):
    """benefit_restriction_posture: 80.00 / 60.00 pinned boundaries."""
    p = D(pct)
    if p >= Decimal("80.00"):
        return "UNRESTRICTED"
    if p >= Decimal("60.00"):
        return "LUMP_SUM_RESTRICTED"
    return "ACCRUAL_FROZEN"


def presumed_aftap(plan):
    """Presumed AFTAP per ftap_calculation presumed variant.

    Returns (presumed_aftap_pct_or_None, posture). Only meaningful while no
    CERTIFIED run governs the plan.
    """
    now = store.now()
    py = plan["plan_year"]
    if now >= october_deemed_for(py):
        # deemed under 60; no numeric presumed percentage
        return None, "ACCRUAL_FROZEN"
    prior = r2(plan["prior_aftap_pct"])
    if now >= april_cutoff_for(py):
        presumed = r2(D(prior) - Decimal("10.00"))
        return presumed, posture_for_pct(presumed)
    # presumed adequate: prior governs, posture pinned UNRESTRICTED
    return prior, "UNRESTRICTED"


def serialize_plan(plan):
    out = public(plan)
    certified = certified_run_for_plan(plan["id"])
    if certified is not None:
        out["certified_aftap_pct"] = plan.get("certified_aftap_pct")
        out["presumed_aftap_pct"] = None
        out["current_posture"] = plan.get("current_posture", "UNRESTRICTED")
    else:
        presumed, posture = presumed_aftap(plan)
        out["certified_aftap_pct"] = None
        out["presumed_aftap_pct"] = presumed
        out["current_posture"] = posture
    return out


# ---------------------------------------------------------------------------
# asset smoothing corridor
# ---------------------------------------------------------------------------

def compute_asset_valuation_fields(stmt):
    """asset_smoothing_corridor: expected return 5%, 1/3 gain recognized,
    corridor 0.80/1.20 of market_value_end."""
    mv_begin = r2d(stmt["market_value_begin"])
    mv_end = r2d(stmt["market_value_end"])
    inv_return = r2d(stmt["investment_return"])
    expected_return = r2d(mv_begin * Decimal("0.05"))
    gain = inv_return - expected_return
    unrecognized_gain = r2d((gain * 2) / 3)
    pre_corridor = mv_end - unrecognized_gain
    corridor_floor = r2d(Decimal("0.80") * mv_end)
    corridor_ceiling = r2d(Decimal("1.20") * mv_end)
    if pre_corridor < corridor_floor:
        smoothed = corridor_floor
        applied = "FLOOR"
    elif pre_corridor > corridor_ceiling:
        smoothed = corridor_ceiling
        applied = "CEILING"
    else:
        smoothed = pre_corridor
        applied = "NONE"
    return {
        "market_value": float(mv_end),
        "smoothed_value": float(smoothed),
        "unrecognized_gain": float(unrecognized_gain),
        "corridor_floor": float(corridor_floor),
        "corridor_ceiling": float(corridor_ceiling),
        "corridor_applied": applied,
    }


# ---------------------------------------------------------------------------
# valuation run compute
# ---------------------------------------------------------------------------

def compute_run_accruals(run):
    """Create one ParticipantAccrual per participant of the referenced batch
    and aggregate funding_target / normal_cost (per-row cents, then exact sum)."""
    plan = store.plans[run["plan_id"]]
    aset = store.assumption_sets[run["assumption_set_id"]]
    rate = D(aset["funding_discount_rate"])
    nra = aset["retirement_age"]
    accrual_rate = D(plan["accrual_rate"])
    plan_year = run["plan_year"]

    ft_total = Decimal("0.00")
    nc_total = Decimal("0.00")
    for p in batch_participants(run["census_batch_id"]):
        age = attained_age(plan_year, p["date_of_birth"])
        status = p["status"]
        if status == "RETIREE":
            af = annuity_factor_immediate(age, rate)
            liability = r2d(D(p["current_annual_benefit"]) * af)
            nc_share = Decimal("0.00")
        else:
            af = annuity_factor(age, nra, rate)
            if status == "ACTIVE":
                liability = r2d(accrual_rate * D(p["years_of_service"]) * D(p["annual_compensation"]) * af)
                nc_share = r2d(accrual_rate * D(1) * D(p["annual_compensation"]) * af)
            else:  # TERMINATED_VESTED
                liability = r2d(D(p["deferred_benefit_annual"]) * af)
                nc_share = Decimal("0.00")
        row = base_record()
        row.update({
            "valuation_run_id": run["id"],
            "participant_id": p["id"],
            "age_at_valuation": age,
            "annuity_factor": float(af),
            "accrued_liability": float(liability),
            "normal_cost_share": float(nc_share),
            "frozen": False,
        })
        store.participant_accruals[row["id"]] = row
        ft_total += liability
        nc_total += nc_share
    run["funding_target"] = float(ft_total)
    run["normal_cost"] = float(nc_total)


def run_accruals(run_id):
    rows = [a for a in store.participant_accruals.values() if a["valuation_run_id"] == run_id]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return rows


# ---------------------------------------------------------------------------
# contribution demand: minimum_required_contribution + maximum_deductible
# ---------------------------------------------------------------------------

def demand_for_plan(plan_id):
    for d in store.contribution_demands.values():
        if d["plan_id"] == plan_id:
            return d
    return None


def demand_payments(demand_id):
    rows = [p for p in store.contribution_payments.values() if p["contribution_demand_id"] == demand_id]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return rows


def effective_elections(demand_id):
    rows = [
        e for e in store.credit_balance_elections.values()
        if e["contribution_demand_id"] == demand_id and e["status"] == "EFFECTIVE"
    ]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return rows


def recompute_demand(demand):
    """Pinned evaluation order (minimum_required_contribution +
    maximum_deductible_contribution), then status auto-transition."""
    run = store.valuation_runs.get(demand["valuation_run_id"])
    plan = store.plans.get(demand["plan_id"])
    if run is None or plan is None:
        return
    ava = store.asset_valuations.get(run["asset_valuation_id"])
    smoothed = r2d(ava["smoothed_value"]) if ava else Decimal("0.00")
    funding_target = r2d(run["funding_target"] or 0)
    # freeze state zeroes the normal-cost component
    if plan.get("current_posture") == "ACCRUAL_FROZEN":
        nc_component = Decimal("0.00")
    else:
        nc_component = r2d(run["normal_cost"] or 0)
    shortfall = funding_target - smoothed
    if shortfall < 0:
        shortfall = Decimal("0.00")
    installment = r2d(shortfall / 7) if shortfall > 0 else Decimal("0.00")
    tentative_minimum = nc_component + installment

    drawn = Decimal("0.00")
    for e in effective_elections(demand["id"]):
        drawn += r2d(e["amount"])
    credit_applied = drawn if drawn <= tentative_minimum else tentative_minimum
    minimum_due = tentative_minimum - credit_applied

    paid = Decimal("0.00")
    for p in demand_payments(demand["id"]):
        paid += r2d(p["amount"])
    paid_to_date = paid
    outstanding = minimum_due - paid_to_date

    cushion_basis = r2d(Decimal("1.5") * funding_target) + nc_component
    maximum_deductible = cushion_basis - smoothed
    if tentative_minimum > maximum_deductible:
        maximum_deductible = tentative_minimum

    demand["tentative_minimum"] = float(r2d(tentative_minimum))
    demand["credit_applied"] = float(r2d(credit_applied))
    demand["minimum_due"] = float(r2d(minimum_due))
    demand["paid_to_date"] = float(r2d(paid_to_date))
    demand["outstanding_amount"] = float(r2d(outstanding))
    demand["maximum_deductible"] = float(r2d(maximum_deductible))
    _auto_transition_demand(demand)


def _auto_transition_demand(demand):
    outstanding = D(str(demand["outstanding_amount"]))
    if outstanding <= 0:
        demand["status"] = "SATISFIED"
    elif demand["status"] == "DELINQUENT":
        pass  # DELINQUENT is sticky while outstanding stays positive
    elif demand["status"] != "OPEN":
        # revocation / recertification restoring a positive outstanding amount
        # pulls the demand back to PARTIALLY_SATISFIED, never to OPEN
        demand["status"] = "PARTIALLY_SATISFIED"
    else:
        # birth state OPEN: a payment or election that leaves a positive
        # outstanding amount moves it to PARTIALLY_SATISFIED
        credit = D(str(demand["credit_applied"]))
        paid = D(str(demand["paid_to_date"]))
        if credit > 0 or paid > 0:
            demand["status"] = "PARTIALLY_SATISFIED"
        else:
            demand["status"] = "OPEN"


def evaluate_delinquency():
    """Clock-driven: OPEN/PARTIALLY_SATISFIED demands with outstanding > 0 and
    clock strictly past due_date transition to DELINQUENT with excise assessed once."""
    now = store.now()
    for d in store.contribution_demands.values():
        if d["status"] not in ("OPEN", "PARTIALLY_SATISFIED"):
            continue
        if D(str(d["outstanding_amount"])) <= 0:
            continue
        if now > parse_iso(d["due_date"]):
            d["status"] = "DELINQUENT"
            d["excise_accrued"] = float(r2d(Decimal("0.10") * D(str(d["outstanding_amount"]))))
            touch(d)


# ---------------------------------------------------------------------------
# PBGC premium
# ---------------------------------------------------------------------------

FLAT_RATE_PER_PARTICIPANT = Decimal("100")
VARIABLE_RATE_PER_1000 = Decimal("50")
PER_PARTICIPANT_CAP = Decimal("600")
ALTERNATIVE_TARGET_FACTOR = Decimal("1.05")


def compute_premium_fields(run, premium_method):
    """pbgc_premium: UVB on MARKET assets; cap binds at equality."""
    batch = store.census_batches.get(run["census_batch_id"])
    participant_count = batch["participant_count"] if batch else 0
    funding_target = r2d(run["funding_target"] or 0)
    if premium_method == "ALTERNATIVE":
        premium_target = r2d(funding_target * ALTERNATIVE_TARGET_FACTOR)
    else:
        premium_target = funding_target
    ava = store.asset_valuations.get(run["asset_valuation_id"])
    market_assets = r2d(ava["market_value"]) if ava else Decimal("0.00")
    uvb = premium_target - market_assets
    if uvb < 0:
        uvb = Decimal("0.00")
    flat_rate_premium = r2d(participant_count * FLAT_RATE_PER_PARTICIPANT)
    uncapped_variable = r2d(uvb * VARIABLE_RATE_PER_1000 / 1000)
    cap = r2d(participant_count * PER_PARTICIPANT_CAP)
    cap_applied = uncapped_variable >= cap
    variable_rate_premium = uncapped_variable if uncapped_variable <= cap else cap
    total_premium = flat_rate_premium + variable_rate_premium
    return {
        "participant_count": participant_count,
        "premium_target": float(premium_target),
        "market_assets": float(market_assets),
        "uvb": float(uvb),
        "flat_rate_premium": float(flat_rate_premium),
        "variable_rate_premium": float(variable_rate_premium),
        "total_premium": float(r2d(total_premium)),
        "cap_applied": bool(cap_applied),
    }


# ---------------------------------------------------------------------------
# disclosure funded status
# ---------------------------------------------------------------------------

def compute_pbo(run):
    """disclosure_funded_status: census revalued at disclosure_discount_rate,
    same pinned rounding order (per-participant cents, then exact sum)."""
    plan = store.plans[run["plan_id"]]
    aset = store.assumption_sets[run["assumption_set_id"]]
    rate = D(aset["disclosure_discount_rate"])
    nra = aset["retirement_age"]
    accrual_rate = D(plan["accrual_rate"])
    plan_year = run["plan_year"]
    total = Decimal("0.00")
    for p in batch_participants(run["census_batch_id"]):
        age = attained_age(plan_year, p["date_of_birth"])
        status = p["status"]
        if status == "RETIREE":
            af = annuity_factor_immediate(age, rate)
            total += r2d(D(p["current_annual_benefit"]) * af)
        elif status == "ACTIVE":
            af = annuity_factor(age, nra, rate)
            total += r2d(accrual_rate * D(p["years_of_service"]) * D(p["annual_compensation"]) * af)
        else:
            af = annuity_factor(age, nra, rate)
            total += r2d(D(p["deferred_benefit_annual"]) * af)
    return total


# ---------------------------------------------------------------------------
# credit balance waterfall
# ---------------------------------------------------------------------------

def ledger_for_plan(plan_id):
    return store.credit_balance_ledgers.get(plan_id)


def waterfall_draw(ledger, amount):
    """Forward pass: carryover first, then prefunding. Returns (from_co, from_pf)."""
    amt = r2d(amount)
    carry = r2d(ledger["carryover_balance"])
    pre = r2d(ledger["prefunding_balance"])
    from_carryover = amt if amt <= carry else carry
    remainder = amt - from_carryover
    from_prefunding = remainder if remainder <= pre else pre
    ledger["carryover_balance"] = float(carry - from_carryover)
    ledger["prefunding_balance"] = float(pre - from_prefunding)
    ledger["total_applied_to_date"] = float(r2d(ledger["total_applied_to_date"]) + amt)
    touch(ledger)
    return from_carryover, from_prefunding


def waterfall_restore(ledger, from_carryover, from_prefunding, amount):
    """Reverse pass: restore pools in the proportions recorded at draw time."""
    ledger["carryover_balance"] = float(r2d(ledger["carryover_balance"]) + r2d(from_carryover))
    ledger["prefunding_balance"] = float(r2d(ledger["prefunding_balance"]) + r2d(from_prefunding))
    ledger["total_applied_to_date"] = float(r2d(ledger["total_applied_to_date"]) - r2d(amount))
    touch(ledger)
