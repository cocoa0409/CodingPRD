"""Business workflows: cascades, state transitions with side effects,
quote expiry against the logical clock."""
from datetime import datetime, timedelta, timezone

from db import store, touch, new_record, now_iso
from services import calcs
from services.calcs import D

TERMINAL_QUOTE_STATES = {"ACCEPTED", "REJECTED", "EXPIRED", "SUPERSEDED"}


def parse_dt(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def latest_validated_census(case_id):
    cands = [c for c in store.censuses.values()
             if c["case_id"] == case_id and c["status"] == "VALIDATED"]
    if not cands:
        return None
    return max(cands, key=lambda c: c["_seq"])


# ---------------------------------------------------------------- census ---
def on_census_validated(census):
    """Cascade when a census snapshot validates (PRD 3.2): parent case
    CENSUS_PENDING -> CENSUS_RECEIVED and compute credibility + manual rate."""
    case = store.cases.get(census["case_id"])
    if case is None or case["status"] != "CENSUS_PENDING":
        return
    case["status"] = "CENSUS_RECEIVED"
    case["credibility_factor"] = calcs.credibility_from_census(case["group_size"])
    case["manual_rate_cents"] = calcs.manual_rate(
        census.get("average_age"), census.get("gender_ratio"), case["sic_code"]
    )
    case["rate_cap_pct"] = calcs.DEFAULT_RATE_CAP_PCT
    touch(case)


# ---------------------------------------------------------------- claims ---
def on_claims_reviewed(claims):
    """Cascade when claims experience is reviewed (PRD 3.3): parent case
    CLAIMS_PENDING -> RATING_IN_PROGRESS and compute experience rate,
    blended credibility, and the blended rate with rate cap."""
    case = store.cases.get(claims["case_id"])
    if case is None or case["status"] != "CLAIMS_PENDING":
        return
    months = claims["months_of_experience"]
    z = calcs.credibility_blended(case["group_size"], months)
    case["credibility_factor"] = z
    case["experience_rate_cents"] = calcs.experience_rate(
        claims["experience_claim_cost_cents"],
        D(str(claims["completion_ratio"])),
        claims["total_enrollment_months"],
        z,
    )
    census = latest_validated_census(case["id"])
    enrolled = census["enrolled_employees"] if census else 0
    if enrolled > 0:
        blended, capped = calcs.blended_rate(
            z,
            case["experience_rate_cents"],
            case["manual_rate_cents"],
            case["current_premium_annual"],
            enrolled,
            case["rate_cap_pct"] or calcs.DEFAULT_RATE_CAP_PCT,
        )
        case["blended_rate_cents"] = blended
        case["is_rate_cap_applied"] = capped
    case["status"] = "RATING_IN_PROGRESS"
    touch(case)


# ----------------------------------------------------------------- quote ---
def _create_round(quote, proposed_by, pepm, contrib, deductible, justification):
    rec = new_record()
    rec.update({
        "quote_id": quote["id"],
        "case_id": quote["case_id"],
        "round_number": len([r for r in store.rounds.values()
                             if r["quote_id"] == quote["id"]]) + 1,
        "proposed_by": proposed_by,
        "proposed_pepm_cents": pepm,
        "proposed_contribution_pct": contrib,
        "proposed_deductible_individual": deductible,
        "justification": justification,
        "status": "PROPOSED",
    })
    store.rounds[rec["id"]] = rec
    return rec


def _resolve_rounds(quote_id, to_status):
    for r in store.rounds.values():
        if r["quote_id"] == quote_id and r["status"] == "PROPOSED":
            r["status"] = to_status
            touch(r)


def propose_quote(quote):
    """PRD 3.5: compute every rate on proposal, move quote to PROPOSED,
    supersede older PROPOSED quotes, advance case RATING_IN_PROGRESS ->
    QUOTED."""
    case = store.cases[quote["case_id"]]
    plan = store.plans.get(quote["plan_design_id"])
    census = latest_validated_census(case["id"])
    enrolled = census["enrolled_employees"] if census else 0

    relativity = plan.get("relativity_factor") if plan else None
    if relativity is None:
        relativity = 1.0
    pepm = calcs.quote_pepm(case["blended_rate_cents"], relativity)
    quote["pepm_rate_cents"] = pepm

    if quote["funding_type"] == "LEVEL_FUNDED":
        claims_fund, admin_fee, stop_loss = calcs.level_funded_split(pepm)
        quote["claims_fund_cents"] = claims_fund
        quote["admin_fee_cents"] = admin_fee
        quote["stop_loss_premium_cents"] = stop_loss
    else:
        quote["claims_fund_cents"] = 0
        quote["admin_fee_cents"] = 0
        quote["stop_loss_premium_cents"] = 0

    annual = calcs.annual_premium(pepm, enrolled)
    quote["annual_premium_cents"] = annual
    quote["renewal_increase_pct"] = calcs.renewal_increase_pct(
        annual, case["current_premium_annual"]
    )
    broker = store.brokers.get(case["broker_id"])
    commission_pct = broker["commission_pct"] if broker else 0
    commission = calcs.broker_commission(annual, commission_pct)
    quote["broker_commission_cents"] = commission
    quote["commission_disclosure_required"] = (
        calcs.commission_disclosure_required(commission, enrolled)
    )

    # Supersede any other PROPOSED quote on this case (their open rounds
    # resolve to REJECTED).
    for other in store.quotes.values():
        if (other["case_id"] == case["id"] and other["id"] != quote["id"]
                and other["status"] == "PROPOSED"):
            other["status"] = "SUPERSEDED"
            touch(other)
            _resolve_rounds(other["id"], "REJECTED")

    quote["status"] = "PROPOSED"
    touch(quote)

    if case["status"] == "RATING_IN_PROGRESS":
        case["status"] = "QUOTED"
        touch(case)
    return quote


def counter_quote(quote, pepm, contrib, deductible, justification):
    """PRD 3.6: broker counter. Quote PROPOSED -> COUNTERED, spawn round,
    case QUOTED -> NEGOTIATING."""
    case = store.cases[quote["case_id"]]
    quote["status"] = "COUNTERED"
    quote["negotiation_round"] += 1
    touch(quote)
    _create_round(quote, "BROKER", pepm, contrib, deductible, justification)
    if case["status"] == "QUOTED":
        case["status"] = "NEGOTIATING"
        touch(case)
    return quote


def respond_quote(quote, pepm, contrib, deductible, justification):
    """PRD 3.6: underwriter response. Quote COUNTERED -> PROPOSED, spawn
    UNDERWRITER round, case NEGOTIATING -> QUOTED."""
    case = store.cases[quote["case_id"]]
    quote["status"] = "PROPOSED"
    quote["negotiation_round"] += 1
    touch(quote)
    _create_round(quote, "UNDERWRITER", pepm, contrib, deductible, justification)
    if case["status"] == "NEGOTIATING":
        case["status"] = "QUOTED"
        touch(case)
    return quote


def accept_quote(quote):
    """PRD 3.6 acceptance cascade: quote ACCEPTED, plan SELECTED, other
    non-terminal quotes SUPERSEDED, open rounds resolved, case APPROVED,
    CommissionDisclosure minted."""
    case = store.cases[quote["case_id"]]

    quote["status"] = "ACCEPTED"
    touch(quote)
    _resolve_rounds(quote["id"], "ACCEPTED")

    plan = store.plans.get(quote["plan_design_id"])
    if plan is not None and plan["status"] == "MODELED":
        plan["status"] = "SELECTED"
        touch(plan)

    for other in store.quotes.values():
        if (other["case_id"] == case["id"] and other["id"] != quote["id"]
                and other["status"] not in TERMINAL_QUOTE_STATES):
            other["status"] = "SUPERSEDED"
            touch(other)
            _resolve_rounds(other["id"], "REJECTED")

    case["status"] = "APPROVED"
    touch(case)

    # Mint the commission disclosure (PRD 3.6/3.9)
    census = latest_validated_census(case["id"])
    enrolled = census["enrolled_employees"] if census else 0
    broker = store.brokers.get(case["broker_id"])
    commission_pct = broker["commission_pct"] if broker else 0
    total_commission = quote["broker_commission_cents"]
    per_enrollee = calcs.round_cents(D(total_commission) / D(enrolled)) if enrolled > 0 else 0
    disc = new_record()
    disc.update({
        "case_id": case["id"],
        "quote_id": quote["id"],
        "broker_id": case["broker_id"],
        "total_commission_cents": total_commission,
        "commission_pct": commission_pct,
        "per_enrollee_cents": per_enrollee,
        "disclosure_threshold_cents": calcs.DISCLOSURE_THRESHOLD_PER_ENROLLEE_CENTS,
        "requires_disclosure": per_enrollee >= calcs.DISCLOSURE_THRESHOLD_PER_ENROLLEE_CENTS,
        "disclosed_at": None,
        "status": "PENDING",
    })
    store.disclosures[disc["id"]] = disc
    return quote


def reject_quote(quote):
    """Quote PROPOSED/COUNTERED -> REJECTED; open rounds resolve REJECTED."""
    quote["status"] = "REJECTED"
    touch(quote)
    _resolve_rounds(quote["id"], "REJECTED")
    return quote


# ------------------------------------------------------------- quote expiry
def expire_quotes():
    """PRD 2.8/3.6: a quote still PROPOSED or COUNTERED once the logical
    clock passes effective_date - 30 days expires automatically."""
    now = store.logical_clock
    for quote in list(store.quotes.values()):
        if quote["status"] not in ("PROPOSED", "COUNTERED"):
            continue
        case = store.cases.get(quote["case_id"])
        if case is None:
            continue
        eff = parse_dt(case.get("effective_date"))
        if eff is None:
            continue
        if now > eff - timedelta(days=30):
            quote["status"] = "EXPIRED"
            touch(quote)
