"""The ten pinned calculations (SCAFFOLD 1.4 / PRD 3.x)."""
from db import D, rhu, rhu_int, store
from errors import ApiError

# --- governance constants (PRD 3.9) ---------------------------------------
MAX_REMANDS = 2
MIN_SCORED_PEER_REVIEWS = 2
QUORUM_MIN_CAST_BALLOTS = 2
POINTS_CAP_PER_BALLOT = D("1000.00")
SERVICE_PERIOD_BUFFER_DAYS = 1
MAX_REOPENS = 1

# --- enums ---------------------------------------------------------------
CYCLE_STATES = ["OPEN_INTAKE", "SELF_ASSESSMENT", "PEER_REVIEW", "DELIBERATION",
                "AWARDS_PUBLISHED", "TRUE_UP_OPEN", "CLOSED"]
PRACTICE_GROUPS = ["LITIGATION", "CORPORATE", "TAX", "IP", "REGULATORY"]
COMPENSATION_MODELS = ["LOCKSTEP", "FORMULA", "DISCRETIONARY"]
PARTNER_STATES = ["ACTIVE", "NOTICE_GIVEN", "DEPARTED"]
MATTER_TYPES = ["NEW_CLIENT", "EXPANDED_MATTER", "CROSS_SELL", "EXISTING"]
MATTER_STATES = ["OPEN", "CLOSED", "WRITTEN_OFF"]
CREDIT_ROLES = ["ORIGINATING", "BILLING", "RESPONSIBLE", "WORKING"]
ALLOCATION_SOURCES = ["CLAIM_ALLOCATED", "SHARING_CONVENTION", "DEFAULT_BILLING",
                      "WORKING_DERIVED", "TRANSITION"]
ALLOCATION_STATES = ["ACTIVE", "TRANSFERRED", "SUPERSEDED"]
RECORD_KINDS = ["BILLABLE", "NON_BILLABLE"]
RECORD_CATEGORIES = ["CLIENT_WORK", "FIRM_MANAGEMENT", "RECRUITING", "PRO_BONO", "TRAINING"]
CLAIM_BASES = ["NEW_CLIENT", "EXPANDED_MATTER", "CROSS_SELL"]
CLAIM_STATES = ["DRAFT", "SUBMITTED", "DISPUTED", "ALLOCATED", "REJECTED"]
ASSESSMENT_STATES = ["DRAFT", "SUBMITTED", "ACCEPTED"]
REVIEW_STATES = ["ASSIGNED", "SCORED", "RECUSED"]
BALLOT_STATES = ["PENDING", "CAST", "ABSTAINED", "RECUSED"]
AWARD_STATES = ["PROPOSED", "PUBLISHED", "FINALIZED"]
PAYMENT_STATES = ["PENDING", "DRAWING", "TRUED_UP", "SETTLED"]
PAYMENT_KINDS = ["SCHEDULED_DRAW", "DRAW_REVERSAL", "TRUE_UP", "CLAWBACK", "CAPITAL_WITHHOLDING"]
TRANSITION_STATES = ["PROPOSED", "EFFECTIVE", "VOIDED"]

# --- calculation constants -----------------------------------------------
OVERHEAD_RATE_CENTS_PER_HOUR = D("9000")

ROLE_WEIGHTS = {
    "ORIGINATING": D("0.40"),
    "BILLING": D("0.20"),
    "RESPONSIBLE": D("0.15"),
    "WORKING": D("0.25"),
}

SHARE_BY_BASIS = {
    "NEW_CLIENT": D("100.00"),
    "EXPANDED_MATTER": D("60.00"),
    "CROSS_SELL": D("50.00"),
}

CATEGORY_WEIGHTS = {
    "FIRM_MANAGEMENT": D("1.50"),
    "RECRUITING": D("1.00"),
    "PRO_BONO": D("1.25"),
    "TRAINING": D("0.75"),
}
CATEGORY_CAPS = {
    "FIRM_MANAGEMENT": D("300"),
    "RECRUITING": D("150"),
    "PRO_BONO": D("200"),
    "TRAINING": D("100"),
}
DIMINISHING_THRESHOLD_HOURS = D("400")
DIMINISHING_FACTOR = D("0.50")
PRO_BONO_FLOOR_HOURS = D("50")
PRO_BONO_SHORTFALL_PENALTY = D("0.90")
MODEL_MULTIPLIERS = {
    "LOCKSTEP": D("0.60"),
    "FORMULA": D("1.00"),
    "DISCRETIONARY": D("1.20"),
}

W_CREDITED_COLLECTION = D("0.45")
W_WORKING_HOURS = D("0.20")
W_NON_BILLABLE = D("0.15")
W_PROFITABILITY = D("0.20")
FIRM_NORMALIZATION_TARGET_CENTS = D("1000000000")
HOURS_NORMALIZATION_DIVISOR = D("1800")

HAIRCUT_FLOOR_PCT = D("0.70")


# =========================================================================
# anchor_cycle_selection
# =========================================================================

def anchor_cycle():
    candidates = [c for c in store.cycles.values() if c["state"] != "CLOSED"]
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c["fiscal_year"], -c["_seq"]))


# =========================================================================
# matter_realization_and_profitability
# =========================================================================

def matter_economics(matter, verified_hours):
    billed = D(matter["billed_cents"])
    collected = D(matter["collected_cents"])
    cost = D(matter["direct_cost_cents"])
    if matter["billed_cents"] == 0:
        realization = D("0.0000")
    else:
        realization = rhu(collected / billed, 4)
    if matter["collected_cents"] == 0:
        contribution = D("0.0000")
        fully_loaded = D("0.0000")
    else:
        contribution = rhu((collected - cost) / collected, 4)
        overhead = OVERHEAD_RATE_CENTS_PER_HOUR * verified_hours
        fully_loaded = rhu((collected - cost - overhead) / collected, 4)
    return realization, contribution, fully_loaded


# =========================================================================
# credited_collection_split
# =========================================================================

def credited_collection_split(active_allocations, basis_cents):
    """Two-layer split of a matter basis over its ACTIVE allocations."""
    result = {a["id"]: 0 for a in active_allocations}
    if basis_cents == 0 or not active_allocations:
        return result
    by_role = {}
    for role in CREDIT_ROLES:
        rows = [a for a in active_allocations if a["credit_role"] == role]
        rows.sort(key=lambda a: a["_seq"])
        by_role[role] = rows
    raw = {}
    for role in CREDIT_ROLES:
        raw[role] = rhu_int(D(basis_cents) * ROLE_WEIGHTS[role])
    for role in ("BILLING", "RESPONSIBLE", "WORKING"):
        if not by_role[role]:
            raw["ORIGINATING"] += raw[role]
            raw[role] = 0
    raw["ORIGINATING"] += basis_cents - sum(raw.values())
    for role in CREDIT_ROLES:
        rows = by_role[role]
        pool = raw[role]
        if not rows or pool == 0:
            continue
        for row in rows:
            result[row["id"]] = rhu_int(D(pool) * row["credit_pct"] / D(100))
        residual = pool - sum(result[r["id"]] for r in rows)
        if residual != 0:
            winner = max(rows, key=lambda a: (a["credit_pct"], -a["_seq"]))
            result[winner["id"]] += residual
    return result


# =========================================================================
# origination_sharing_convention
# =========================================================================

def sharing_convention(matter, claim_basis, approved_pct, claimant_id):
    """Returns (claimant_pct, counterparty_pct, resolved_prior_originator_id)."""
    share = SHARE_BY_BASIS[claim_basis]
    claimant_pct = rhu(approved_pct * share / D(100), 2)
    counterparty_pct = rhu(approved_pct - claimant_pct, 2)

    siblings = [m for m in store.matters.values()
                if m["client_key"] == matter["client_key"]
                and m["id"] != matter["id"]
                and m["state"] != "WRITTEN_OFF"]
    if not siblings:
        return approved_pct, D("0.00"), None
    earliest = min(siblings, key=lambda m: (m["opened_on"], m["_seq"]))
    rows = [a for a in store.allocations.values()
            if a["matter_id"] == earliest["id"]
            and a["credit_role"] == "ORIGINATING"
            and a["state"] == "ACTIVE"]
    if rows:
        holder = max(rows, key=lambda a: (a["credit_pct"], -a["_seq"]))
        prior = holder["partner_id"]
    else:
        prior = earliest["billing_attorney_id"]
    if prior == claimant_id or counterparty_pct == 0:
        return approved_pct, D("0.00"), None
    return claimant_pct, counterparty_pct, prior


# =========================================================================
# non_billable_weighted_points
# =========================================================================

def non_billable_points(partner, anchor):
    if anchor is None:
        return D("0.00")
    capped = {}
    for category, cap in CATEGORY_CAPS.items():
        hours = D("0")
        for record in store.records.values():
            if (record["partner_id"] == partner["id"]
                    and record["cycle_id"] == anchor["id"]
                    and record["kind"] == "NON_BILLABLE"
                    and record["verified"]
                    and record["category"] == category):
                hours += record["hours"]
        capped[category] = min(hours, cap)
    base = D("0")
    for category, hours in capped.items():
        base += hours * CATEGORY_WEIGHTS[category]
    capped_total = sum(capped.values(), D("0"))
    if capped_total > DIMINISHING_THRESHOLD_HOURS:
        excess = capped_total - DIMINISHING_THRESHOLD_HOURS
        average = base / capped_total
        base = base - excess * average * (D(1) - DIMINISHING_FACTOR)
    if capped["PRO_BONO"] < PRO_BONO_FLOOR_HOURS:
        base = base * PRO_BONO_SHORTFALL_PENALTY
    return rhu(base * MODEL_MULTIPLIERS[partner["compensation_model"]], 2)


# =========================================================================
# partner_formula_score
# =========================================================================

def realization_tier_multiplier(blended):
    if blended >= D("0.9500"):
        return D("1.10")
    if blended >= D("0.8500"):
        return D("1.00")
    if blended >= D("0.7500"):
        return D("0.90")
    return D("0.75")


def normalization_factor(firm_total_cents):
    if firm_total_cents > 0:
        return rhu(FIRM_NORMALIZATION_TARGET_CENTS / D(firm_total_cents), 6)
    return D("1.000000")


def formula_score(partner, allocations, credited_key, factor):
    """Steps 5 through 8 of partner_formula_score for one variant."""
    partner_credited = 0
    for allocation in allocations:
        partner_credited += allocation[credited_key]
    nci = rhu(D(partner_credited) * factor / FIRM_NORMALIZATION_TARGET_CENTS, 6)
    if partner_credited > 0:
        realization_sum = D("0")
        profit_sum = D("0")
        for allocation in allocations:
            matter = store.matters[allocation["matter_id"]]
            amount = D(allocation[credited_key])
            realization_sum += amount * matter["realization_pct"]
            profit_sum += amount * matter["profitability_index_fully_loaded"]
        blended = rhu(realization_sum / D(partner_credited), 4)
        weighted_profitability = rhu(profit_sum / D(partner_credited), 4)
    else:
        blended = D("0.0000")
        weighted_profitability = D("0.0000")
    tier = realization_tier_multiplier(blended)
    hours_component = partner["verified_billable_hours"] / HOURS_NORMALIZATION_DIVISOR
    raw = (W_CREDITED_COLLECTION * nci * D(100)
           + W_WORKING_HOURS * hours_component * D(100)
           + W_NON_BILLABLE * partner["non_billable_points"] / D(100)
           + W_PROFITABILITY * weighted_profitability * D(100))
    score = rhu(raw * tier, 4)
    return {
        "credited": partner_credited,
        "normalized_credit_index": nci,
        "blended_realization_pct": blended,
        "weighted_profitability_points": weighted_profitability,
        "formula_score": score,
    }


# =========================================================================
# committee_points_trimmed_mean
# =========================================================================

def committee_points(partner, anchor):
    if anchor is None:
        return D("0.00")
    rows = [b for b in store.ballots.values()
            if b["cycle_id"] == anchor["id"]
            and b["subject_partner_id"] == partner["id"]
            and b["state"] == "CAST"]
    if not rows:
        return D("0.00")
    rows.sort(key=lambda b: (b["points_proposed"], b["_seq"]))
    kept = rows[1:-1] if len(rows) >= 3 else rows
    total = sum((b["points_proposed"] for b in kept), D("0"))
    return rhu(total / D(len(kept)), 2)


# =========================================================================
# cycle_pool_waterfall
# =========================================================================

def cycle_pool_waterfall(cycle):
    """Returns the four pool fields, or raises ERR_POOL_INSUFFICIENT."""
    lockstep_gross = D("0")
    for partner in store.partners.values():
        if (partner["compensation_model"] == "LOCKSTEP"
                and partner["status"] in ("ACTIVE", "NOTICE_GIVEN")
                and partner["evaluation_required"]):
            lockstep_gross += D(partner["lockstep_step"]) * D(cycle["lockstep_unit_cents"])
    lockstep_gross = int(lockstep_gross)
    discretionary_gross = rhu_int(D(cycle["distributable_pool_cents"]) * cycle["discretionary_pool_pct"])
    residual = cycle["distributable_pool_cents"] - lockstep_gross - discretionary_gross
    if residual >= 0:
        return {
            "lockstep_reserved_cents": lockstep_gross,
            "discretionary_pool_cents": discretionary_gross,
            "formula_pool_cents": residual,
            "haircut_applied_pct": D("0.0000"),
        }
    deficit = -residual
    max_lockstep_cut = rhu_int(D(lockstep_gross) * (D(1) - HAIRCUT_FLOOR_PCT))
    lockstep_cut = min(deficit, max_lockstep_cut)
    if lockstep_gross > 0:
        haircut = rhu(D(lockstep_cut) / D(lockstep_gross), 4)
    else:
        haircut = D("0.0000")
    lockstep_reserved = lockstep_gross - lockstep_cut
    deficit -= lockstep_cut
    max_discretionary_cut = rhu_int(D(discretionary_gross) * (D(1) - HAIRCUT_FLOOR_PCT))
    discretionary_cut = min(deficit, max_discretionary_cut)
    discretionary_pool = discretionary_gross - discretionary_cut
    deficit -= discretionary_cut
    if deficit > 0:
        raise ApiError("ERR_POOL_INSUFFICIENT")
    return {
        "lockstep_reserved_cents": lockstep_reserved,
        "discretionary_pool_cents": discretionary_pool,
        "formula_pool_cents": 0,
        "haircut_applied_pct": haircut,
    }


# =========================================================================
# partner_award_cents
# =========================================================================

def award_amount(award, variant):
    cycle = store.cycles[award["cycle_id"]]
    partner = store.partners[award["partner_id"]]
    model = award["basis_model"]
    if model == "LOCKSTEP":
        return rhu_int(D(partner["lockstep_step"]) * D(cycle["lockstep_unit_cents"])
                       * (D(1) - cycle["haircut_applied_pct"]))
    if model == "FORMULA":
        score = (partner["formula_score_provisional"] if variant == "PROVISIONAL_DELIBERATION"
                 else partner["formula_score_final"])
        total = cycle["total_formula_score"]
        if total == 0:
            return 0
        return rhu_int(D(cycle["formula_pool_cents"]) * score / total)
    total = cycle["total_committee_points"]
    if total == 0:
        return 0
    return rhu_int(D(cycle["discretionary_pool_cents"]) * partner["committee_points"] / total)


def draw_schedule(award_cents, draw_pct):
    return rhu_int(D(award_cents) * draw_pct / D(12))


# =========================================================================
# peer review composite score
# =========================================================================

def composite_score(technical, collaboration, client_service):
    return rhu(D(technical) * D("0.50") + D(collaboration) * D("0.25")
               + D(client_service) * D("0.25"), 4)
