"""Business logic: rate derivation, charge stamping, true-up waterfall,
MII tally, cascades, and the logical-clock automation sweep."""
from datetime import timedelta

import errors
from db import store
from util import (fmt_iso, new_id, parse_iso, rhu_div, ceil_pct_div, days_later)

# calculation constants (scaffold Table 3)
NON_SIGNATORY_MARKUP_PCT = 125
RATE_UNIT_KG = 1000
REMAINDER_ROUND_UP_KG = 500
PFC_PER_PAX_CENTS = 450
PFC_ANNUAL_CAP_PAX = 2_000_000
CONSULTATION_MIN_DAYS = 30
COUNTERSIGN_WINDOW_DAYS = 30
DISPUTE_WINDOW_DAYS = 45
PAYMENT_DUE_DAYS = 60
MII_WINDOW_DAYS = 365  # rolling twelve-month window


# ---------------------------------------------------------------------------
# common helpers
# ---------------------------------------------------------------------------
def now_dt():
    return store.clock_dt


def stamp():
    return fmt_iso(store.clock_dt)


def touch(ent):
    """Every modification refreshes updated_at and increments version (§2.5)."""
    ent["updated_at"] = stamp()
    ent["version"] = ent.get("version", 1) + 1


def base_fields(ent):
    return ent


# ---------------------------------------------------------------------------
# serializers (exact scaffold field sets; internal '_' keys never leak)
# ---------------------------------------------------------------------------
def ser_fiscal_year(fy):
    return {
        "id": fy["id"],
        "year_label": fy["year_label"],
        "methodology": fy["methodology"],
        "status": fy["status"],
        "airfield_opex_cents": fy["airfield_opex_cents"],
        "terminal_opex_cents": fy["terminal_opex_cents"],
        "nonairline_airfield_revenue_cents": fy["nonairline_airfield_revenue_cents"],
        "nonairline_terminal_revenue_cents": fy["nonairline_terminal_revenue_cents"],
        "terminal_total_space_sqft": fy["terminal_total_space_sqft"],
        "forecast_landed_weight_kg": fy["forecast_landed_weight_kg"],
        "prior_year_surplus_cents": fy["prior_year_surplus_cents"],
        "total_projected_landed_weight_kg": fy["total_projected_landed_weight_kg"],
        "total_signatory_landed_weight_kg": fy["total_signatory_landed_weight_kg"],
        "total_rented_space_sqft": fy["total_rented_space_sqft"],
        "settlement_id": fy["settlement_id"],
        "created_at": fy["created_at"],
        "updated_at": fy["updated_at"],
        "version": fy["version"],
    }


def ser_airline(a):
    return {
        "id": a["id"],
        "iata_code": a["iata_code"],
        "legal_name": a["legal_name"],
        "carrier_class": a["carrier_class"],
        "pfc_approved": a["pfc_approved"],
        "mii_eligible_weight_kg": a["mii_eligible_weight_kg"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_agreement(ag):
    return {
        "id": ag["id"],
        "airline_id": ag["airline_id"],
        "fiscal_year_id": ag["fiscal_year_id"],
        "signature_status": ag["signature_status"],
        "credit_standing": ag["credit_standing"],
        "rented_space_sqft": ag["rented_space_sqft"],
        "countersign_deadline": ag["countersign_deadline"],
        "superseded_by_id": ag["superseded_by_id"],
        "created_at": ag["created_at"],
        "updated_at": ag["updated_at"],
        "version": ag["version"],
    }


def ser_rates_setting(rs):
    return {
        "id": rs["id"],
        "fiscal_year_id": rs["fiscal_year_id"],
        "status": rs["status"],
        "airfield_requirement_cents": rs["airfield_requirement_cents"],
        "signatory_landing_fee_per_1000kg_cents": rs["signatory_landing_fee_per_1000kg_cents"],
        "non_signatory_landing_fee_per_1000kg_cents": rs["non_signatory_landing_fee_per_1000kg_cents"],
        "terminal_rental_rate_per_sqft_year_cents": rs["terminal_rental_rate_per_sqft_year_cents"],
        "adopted_at": rs["adopted_at"],
        "consultation_comment_count": rs["consultation_comment_count"],
        "created_at": rs["created_at"],
        "updated_at": rs["updated_at"],
        "version": rs["version"],
    }


def ser_comment(c):
    return {
        "id": c["id"],
        "rates_setting_id": c["rates_setting_id"],
        "airline_id": c["airline_id"],
        "body": c["body"],
        "submitted_at": c["submitted_at"],
        "created_at": c["created_at"],
    }


def ser_activity(r):
    return {
        "id": r["id"],
        "fiscal_year_id": r["fiscal_year_id"],
        "airline_id": r["airline_id"],
        "activity_date": r["activity_date"],
        "landed_weight_kg": r["landed_weight_kg"],
        "signature_status_at_activity": r["signature_status_at_activity"],
        "billed_landing_fee_cents": r["billed_landing_fee_cents"],
        "created_at": r["created_at"],
    }


def ser_capital_project(p):
    return {
        "id": p["id"],
        "fiscal_year_id": p["fiscal_year_id"],
        "project_name": p["project_name"],
        "cost_center": p["cost_center"],
        "budget_cents": p["budget_cents"],
        "mii_threshold_pct": p["mii_threshold_pct"],
        "status": p["status"],
        "votes_for_count": p["votes_for_count"],
        "votes_for_weight_kg": p["votes_for_weight_kg"],
        "votes_against_weight_kg": p["votes_against_weight_kg"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_mii_vote(v):
    return {
        "id": v["id"],
        "capital_project_id": v["capital_project_id"],
        "airline_id": v["airline_id"],
        "ballot": v["ballot"],
        "cast_at": v["cast_at"],
        "created_at": v["created_at"],
    }


def ser_settlement(s):
    return {
        "id": s["id"],
        "fiscal_year_id": s["fiscal_year_id"],
        "status": s["status"],
        "actual_airfield_requirement_cents": s["actual_airfield_requirement_cents"],
        "actual_terminal_requirement_cents": s["actual_terminal_requirement_cents"],
        "total_billed_landing_cents": s["total_billed_landing_cents"],
        "total_billed_terminal_cents": s["total_billed_terminal_cents"],
        "total_true_up_cents": s["total_true_up_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_settlement_line(l):
    return {
        "id": l["id"],
        "annual_settlement_id": l["annual_settlement_id"],
        "airline_id": l["airline_id"],
        "actual_airfield_share_cents": l["actual_airfield_share_cents"],
        "actual_terminal_share_cents": l["actual_terminal_share_cents"],
        "billed_landing_cents": l["billed_landing_cents"],
        "billed_terminal_cents": l["billed_terminal_cents"],
        "true_up_cents": l["true_up_cents"],
        "payment_status": l["payment_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_pfc(p):
    return {
        "id": p["id"],
        "fiscal_year_id": p["fiscal_year_id"],
        "airline_id": p["airline_id"],
        "enplaned_passengers": p["enplaned_passengers"],
        "pfc_amount_cents": p["pfc_amount_cents"],
        "status": p["status"],
        "rejection_reason": p["rejection_reason"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def fy_of(ent):
    return store.fiscal_years.get(ent["fiscal_year_id"])


def active_agreement(fy_id, airline_id):
    """The active (non-superseded) agreement for (airline, fiscal year)."""
    for ag in store.agreements.values():
        if (ag["fiscal_year_id"] == fy_id and ag["airline_id"] == airline_id
                and ag["superseded_by_id"] is None):
            return ag
    return None


def adopted_rates_setting(fy_id):
    """Latest schedule that reached ADOPTED on this year (current ADOPTED
    preferred; a superseded schedule still supplied the year's adopted rates
    until its replacement is itself adopted)."""
    best = None
    for rs in store.rates_settings.values():
        if rs["fiscal_year_id"] == fy_id and rs["adopted_at"] is not None:
            if best is None or (rs["_adopted_dt"], rs["_seq"]) > (best["_adopted_dt"], best["_seq"]):
                best = rs
    return best


def check_fy_open_guard(fy):
    """Priority 9: writes scoped beneath a CLOSED fiscal year are refused."""
    if fy["status"] == "CLOSED":
        raise errors.fiscal_year_closed()


# ---------------------------------------------------------------------------
# FiscalYear aggregate recomputes
# ---------------------------------------------------------------------------
def recompute_fy_activity_totals(fy):
    records = [r for r in store.activity_records.values() if r["fiscal_year_id"] == fy["id"]]
    total = sum(r["landed_weight_kg"] for r in records)
    sig = sum(r["landed_weight_kg"] for r in records
              if r["signature_status_at_activity"] == "SIGNATORY")
    if total != fy["total_projected_landed_weight_kg"] or sig != fy["total_signatory_landed_weight_kg"]:
        fy["total_projected_landed_weight_kg"] = total
        fy["total_signatory_landed_weight_kg"] = sig
        touch(fy)


def recompute_fy_rented_space(fy):
    """total_rented_space_sqft counts space under agreements that are active
    (not superseded) AND currently SIGNATORY (§3.1: countersign makes the
    space count; decline/lapse stops it counting)."""
    total = sum(
        ag["rented_space_sqft"] for ag in store.agreements.values()
        if ag["fiscal_year_id"] == fy["id"]
        and ag["superseded_by_id"] is None
        and ag["signature_status"] == "SIGNATORY"
    )
    if total != fy["total_rented_space_sqft"]:
        fy["total_rented_space_sqft"] = total
        touch(fy)


# ---------------------------------------------------------------------------
# calculation: landing_fee_rate + terminal_rental_rate (scaffold Table 3)
# ---------------------------------------------------------------------------
def derive_rates(fy):
    """Populate the four computed rate fields from the fiscal year's inputs.
    Evaluation order pinned: requirement -> denominator -> signatory rate ->
    non-signatory markup; terminal requirement -> per-sqft rate."""
    methodology = fy["methodology"]
    airfield_req = fy["airfield_opex_cents"] - fy["nonairline_airfield_revenue_cents"]
    if methodology == "RESIDUAL":
        airfield_req += fy["prior_year_surplus_cents"]
    elif methodology == "HYBRID":
        airfield_req += fy["prior_year_surplus_cents"] // 2  # floor halving
    # COMPENSATORY: carry-forward excluded entirely

    denom = fy["forecast_landed_weight_kg"]
    if denom == 0:
        raise errors.rate_not_derivable("Forecast landed weight divisor is zero")
    signatory_rate = rhu_div(airfield_req * RATE_UNIT_KG, denom)
    non_signatory_rate = ceil_pct_div(signatory_rate, NON_SIGNATORY_MARKUP_PCT, 100)

    terminal_req = fy["terminal_opex_cents"] - fy["nonairline_terminal_revenue_cents"]
    space = fy["terminal_total_space_sqft"]
    if space == 0:
        raise errors.rate_not_derivable("Terminal space divisor is zero")
    terminal_rate = rhu_div(terminal_req, space)

    # terminal rate * aggregate rented space must not exceed the terminal pool
    if terminal_rate * fy["total_rented_space_sqft"] > fy["terminal_opex_cents"]:
        raise errors.rate_not_derivable(
            "Terminal rate times aggregate rented space exceeds the terminal pool")

    return {
        "airfield_requirement_cents": airfield_req,
        "signatory_landing_fee_per_1000kg_cents": signatory_rate,
        "non_signatory_landing_fee_per_1000kg_cents": non_signatory_rate,
        "terminal_rental_rate_per_sqft_year_cents": terminal_rate,
    }


def rederive_rates_onto(rs):
    fy = store.fiscal_years[rs["fiscal_year_id"]]
    rs.update(derive_rates(fy))


# ---------------------------------------------------------------------------
# calculation: landing_fee_charge (ActivityRecord insert)
# ---------------------------------------------------------------------------
def landing_fee_charge(landed_weight_kg, signature_status_at_activity, rs):
    units = landed_weight_kg // RATE_UNIT_KG
    remainder = landed_weight_kg - units * RATE_UNIT_KG
    charge_units = units + (1 if remainder >= REMAINDER_ROUND_UP_KG else 0)
    if signature_status_at_activity == "SIGNATORY":
        rate = rs["signatory_landing_fee_per_1000kg_cents"]
    else:
        rate = rs["non_signatory_landing_fee_per_1000kg_cents"]
    return charge_units * rate


# ---------------------------------------------------------------------------
# calculation: pfc_amount
# ---------------------------------------------------------------------------
def pfc_amount(enplaned_passengers):
    return min(enplaned_passengers, PFC_ANNUAL_CAP_PAX) * PFC_PER_PAX_CENTS


# ---------------------------------------------------------------------------
# calculation: mii_tally (+ vote-open weight snapshot)
# ---------------------------------------------------------------------------
def eligible_voters(fy_id):
    """Distinct airlines holding an active, SIGNATORY agreement on the year."""
    out = []
    seen = set()
    for ag in sorted(store.agreements.values(), key=lambda a: a["_seq"]):
        if (ag["fiscal_year_id"] == fy_id and ag["superseded_by_id"] is None
                and ag["signature_status"] == "SIGNATORY"
                and ag["airline_id"] not in seen):
            seen.add(ag["airline_id"])
            out.append(ag["airline_id"])
    return out


def snapshot_mii_weights(fy_id):
    """At vote-open: freeze each signatory carrier's mii_eligible_weight_kg from
    its landed-weight activity in the rolling twelve-month window."""
    window_start = now_dt() - timedelta(days=MII_WINDOW_DAYS)
    for airline_id in eligible_voters(fy_id):
        weight = 0
        for r in store.activity_records.values():
            if r["airline_id"] != airline_id:
                continue
            adt = r["_activity_dt"]
            if window_start <= adt <= now_dt():
                weight += r["landed_weight_kg"]
        airline = store.airlines[airline_id]
        if airline["mii_eligible_weight_kg"] != weight:
            airline["mii_eligible_weight_kg"] = weight
            touch(airline)


def recompute_mii_tally(project):
    """Recompute tallies. APPROVE ballots count only while the voter remains an
    eligible signatory (the lapse/decline exclusion cascade); REJECT ballots
    stand once cast. Returns (changed, for_count, for_weight, against_weight);
    the caller decides when to touch the project."""
    fy_id = project["fiscal_year_id"]
    eligible = set(eligible_voters(fy_id))
    for_count = 0
    for_weight = 0
    against_weight = 0
    for v in store.mii_votes.values():
        if v["capital_project_id"] != project["id"]:
            continue
        weight = store.airlines[v["airline_id"]]["mii_eligible_weight_kg"]
        if v["ballot"] == "APPROVE":
            if v["airline_id"] in eligible:
                for_count += 1
                for_weight += weight
        else:
            against_weight += weight
    changed = (for_count != project["votes_for_count"]
               or for_weight != project["votes_for_weight_kg"]
               or against_weight != project["votes_against_weight_kg"])
    project["votes_for_count"] = for_count
    project["votes_for_weight_kg"] = for_weight
    project["votes_against_weight_kg"] = against_weight
    return changed, for_count, for_weight, against_weight


def mii_denominators(fy_id):
    voters = eligible_voters(fy_id)
    total_count = len(voters)
    total_weight = sum(store.airlines[a]["mii_eligible_weight_kg"] for a in voters)
    return total_count, total_weight


def mii_exclusion_cascade(fy_id, airline_id):
    """On SIGNATORY -> NON_SIGNATORY: exclude the carrier's APPROVE ballots from
    every project still in MII_VOTING on this year (tally recompute)."""
    for p in store.capital_projects.values():
        if p["fiscal_year_id"] == fy_id and p["status"] == "MII_VOTING":
            changed, *_ = recompute_mii_tally(p)
            if changed:
                touch(p)


# ---------------------------------------------------------------------------
# calculation: annual_true_up (final_actual mode)
# ---------------------------------------------------------------------------
def _airline_created_key(airline_id):
    a = store.airlines[airline_id]
    return (a["_created_dt"], a["_seq"])


def run_true_up(fy):
    """Compute settlement-level figures and per-airline line figures.
    Returns (settlement_fields, {airline_id: line_fields})."""
    fy_id = fy["id"]
    records = [r for r in store.activity_records.values() if r["fiscal_year_id"] == fy_id]
    adopted = adopted_rates_setting(fy_id)
    terminal_rate = (adopted["terminal_rental_rate_per_sqft_year_cents"] if adopted else 0)

    # actual requirements against actuals
    actual_airfield_req = fy["airfield_opex_cents"] - fy["nonairline_airfield_revenue_cents"]
    if fy["methodology"] == "RESIDUAL":
        actual_airfield_req += fy["prior_year_surplus_cents"]
    actual_terminal_req = fy["terminal_opex_cents"] - fy["nonairline_terminal_revenue_cents"]

    sig_weight = {}
    for r in records:
        if r["signature_status_at_activity"] == "SIGNATORY":
            sig_weight[r["airline_id"]] = sig_weight.get(r["airline_id"], 0) + r["landed_weight_kg"]
    pool_weight = sum(sig_weight.values())
    total_rented = fy["total_rented_space_sqft"]

    # participating airlines: any activity OR rented space under an active agreement
    active_agreements = {}  # airline_id -> agreement
    for ag in store.agreements.values():
        if ag["fiscal_year_id"] == fy_id and ag["superseded_by_id"] is None:
            active_agreements[ag["airline_id"]] = ag
    participants = set(r["airline_id"] for r in records)
    participants |= {aid for aid, ag in active_agreements.items() if ag["rented_space_sqft"] > 0}

    lines = {}
    for aid in sorted(participants, key=_airline_created_key):
        w = sig_weight.get(aid, 0)
        a_share = rhu_div(actual_airfield_req * w, pool_weight) if (w > 0 and pool_weight > 0) else 0
        ag = active_agreements.get(aid)
        space = ag["rented_space_sqft"] if ag else 0
        t_share = (rhu_div(actual_terminal_req * space, total_rented)
                   if (space > 0 and total_rented > 0) else 0)
        billed_landing = sum(r["billed_landing_fee_cents"] for r in records
                             if r["airline_id"] == aid)
        billed_terminal = space * terminal_rate if ag else 0
        lines[aid] = {
            "airline_id": aid,
            "actual_airfield_share_cents": a_share,
            "actual_terminal_share_cents": t_share,
            "billed_landing_cents": billed_landing,
            "billed_terminal_cents": billed_terminal,
            "_sig_weight": w,
            "_space": space,
        }

    # rounding-remainder reconciliation (mode b): delta to the largest share,
    # ties broken by Airline.created_at ascending
    delta_air = actual_airfield_req - sum(l["actual_airfield_share_cents"] for l in lines.values())
    air_participants = [l for l in lines.values() if l["_sig_weight"] > 0]
    if delta_air != 0 and air_participants:
        target = min(
            (l for l in air_participants if l["_sig_weight"] == max(x["_sig_weight"] for x in air_participants)),
            key=lambda l: _airline_created_key(l["airline_id"]))
        target["actual_airfield_share_cents"] += delta_air

    delta_term = actual_terminal_req - sum(l["actual_terminal_share_cents"] for l in lines.values())
    term_participants = [l for l in lines.values() if l["_space"] > 0]
    if delta_term != 0 and term_participants:
        target = min(
            (l for l in term_participants if l["_space"] == max(x["_space"] for x in term_participants)),
            key=lambda l: _airline_created_key(l["airline_id"]))
        target["actual_terminal_share_cents"] += delta_term

    for l in lines.values():
        l["true_up_cents"] = ((l["actual_airfield_share_cents"] + l["actual_terminal_share_cents"])
                              - (l["billed_landing_cents"] + l["billed_terminal_cents"]))

    total_billed_landing = sum(r["billed_landing_fee_cents"] for r in records)
    total_billed_terminal = sum(ag["rented_space_sqft"] * terminal_rate
                                for ag in active_agreements.values())
    settlement_fields = {
        "actual_airfield_requirement_cents": actual_airfield_req,
        "actual_terminal_requirement_cents": actual_terminal_req,
        "total_billed_landing_cents": total_billed_landing,
        "total_billed_terminal_cents": total_billed_terminal,
        "total_true_up_cents": sum(l["true_up_cents"] for l in lines.values()),
    }
    return settlement_fields, lines


# ---------------------------------------------------------------------------
# logical-clock automation sweep (delinquency + signature lapse)
# ---------------------------------------------------------------------------
def automation_sweep():
    """Fired when the logical clock is set. (a) A PENDING line whose payment due
    date has passed moves its carrier's agreement GOOD -> DELINQUENT.
    (b) A SIGNATORY agreement past its countersign deadline with an open
    past-due PENDING line lapses to NON_SIGNATORY."""
    now = now_dt()
    # (a) delinquency
    for line in store.settlement_lines.values():
        due = line.get("_due_dt")
        if line["payment_status"] == "PENDING" and due is not None and now > due:
            settlement = store.settlements.get(line["annual_settlement_id"])
            if settlement is None:
                continue
            ag = active_agreement(settlement["fiscal_year_id"], line["airline_id"])
            if ag is not None and ag["credit_standing"] == "GOOD":
                ag["credit_standing"] = "DELINQUENT"
                touch(ag)
    # (b) lapse
    for ag in list(store.agreements.values()):
        if ag["superseded_by_id"] is not None or ag["signature_status"] != "SIGNATORY":
            continue
        deadline = parse_iso(ag["countersign_deadline"]) if ag["countersign_deadline"] else None
        if deadline is None or now <= deadline:
            continue
        # requires an open settlement line PENDING past its due date
        has_past_due = False
        for line in store.settlement_lines.values():
            settlement = store.settlements.get(line["annual_settlement_id"])
            if (settlement is not None
                    and settlement["fiscal_year_id"] == ag["fiscal_year_id"]
                    and line["airline_id"] == ag["airline_id"]
                    and line["payment_status"] == "PENDING"
                    and line.get("_due_dt") is not None and now > line["_due_dt"]):
                has_past_due = True
                break
        if not has_past_due:
            continue
        ag["signature_status"] = "NON_SIGNATORY"
        touch(ag)
        fy = store.fiscal_years.get(ag["fiscal_year_id"])
        if fy is not None:
            recompute_fy_rented_space(fy)
        mii_exclusion_cascade(ag["fiscal_year_id"], ag["airline_id"])
