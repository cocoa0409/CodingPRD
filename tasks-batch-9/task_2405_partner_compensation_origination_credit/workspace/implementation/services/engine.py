"""Immediate-consistency recomputation engine (PRD 2.9)."""
from db import D, apply_changes, rhu, store
from services import calculations as calc


# --------------------------------------------------------------------------
# small query helpers
# --------------------------------------------------------------------------

def ordered(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def matter_allocations(matter_id, states=("ACTIVE",)):
    return ordered([a for a in store.allocations.values()
                    if a["matter_id"] == matter_id and a["state"] in states])


def award_payments(award_id):
    return ordered([p for p in store.payments.values() if p["award_id"] == award_id])


def cycle_awards(cycle_id):
    return ordered([a for a in store.awards.values() if a["cycle_id"] == cycle_id])


def cycle_assessments(cycle_id):
    return ordered([a for a in store.assessments.values() if a["cycle_id"] == cycle_id])


def assessment_reviews(assessment_id):
    return ordered([r for r in store.reviews.values()
                    if r["self_assessment_id"] == assessment_id])


def verified_billable_hours_on_matter(matter_id, partner_id=None):
    total = D("0")
    for record in store.records.values():
        if record["matter_id"] != matter_id:
            continue
        if record["kind"] != "BILLABLE" or not record["verified"]:
            continue
        if partner_id is not None and record["partner_id"] != partner_id:
            continue
        total += record["hours"]
    return total


# --------------------------------------------------------------------------
# interval overlap ceiling (PRD 3.4)
# --------------------------------------------------------------------------

def originating_intervals(matter_id, extra=(), skip_ids=()):
    rows = []
    for allocation in store.allocations.values():
        if allocation["matter_id"] != matter_id:
            continue
        if allocation["credit_role"] != "ORIGINATING":
            continue
        if allocation["state"] not in ("ACTIVE", "TRANSFERRED"):
            continue
        if allocation["id"] in skip_ids:
            continue
        rows.append((allocation["credit_from"], allocation["credit_through"],
                     allocation["credit_pct"]))
    rows.extend(extra)
    return rows


def interval_sum_exceeds_ceiling(rows):
    boundaries = sorted({row[0] for row in rows if row[0] is not None})
    for point in boundaries:
        total = D("0")
        for start, through, pct in rows:
            if start is not None and start > point:
                continue
            if through is not None and through <= point:
                continue
            total += pct
        if total > D("100.00"):
            return True
    return False


# --------------------------------------------------------------------------
# the recompute pass
# --------------------------------------------------------------------------

def recompute_all():
    anchor = calc.anchor_cycle()

    # ---- matters: hours, realization, profitability ---------------------
    for matter in store.matters.values():
        hours = rhu(verified_billable_hours_on_matter(matter["id"]), 2)
        realization, contribution, fully_loaded = calc.matter_economics(matter, hours)
        apply_changes(matter, {
            "verified_billable_hours": hours,
            "realization_pct": realization,
            "profitability_index_contribution": contribution,
            "profitability_index_fully_loaded": fully_loaded,
        })

    # ---- WORKING allocation percentages ---------------------------------
    for matter in store.matters.values():
        total_hours = matter["verified_billable_hours"]
        for allocation in matter_allocations(matter["id"]):
            if allocation["credit_role"] != "WORKING":
                continue
            if total_hours <= 0:
                continue
            partner_hours = verified_billable_hours_on_matter(
                matter["id"], allocation["partner_id"])
            apply_changes(allocation, {
                "credit_pct": rhu(D(100) * partner_hours / total_hours, 2),
            })

    # ---- matter origination percentage in force -------------------------
    for matter in store.matters.values():
        assigned = D("0")
        for allocation in matter_allocations(matter["id"]):
            if allocation["credit_role"] == "ORIGINATING":
                assigned += allocation["credit_pct"]
        apply_changes(matter, {"origination_pct_assigned": rhu(assigned, 2)})

    # ---- credited collections per allocation ----------------------------
    for matter in store.matters.values():
        active = matter_allocations(matter["id"])
        if matter["state"] in ("OPEN", "CLOSED"):
            basis_provisional = int(rhu(D(matter["billed_cents"]) * matter["realization_pct"], 0))
        else:
            basis_provisional = 0
        basis_final = matter["collected_cents"] if matter["state"] == "CLOSED" else 0
        provisional = calc.credited_collection_split(active, basis_provisional)
        final = calc.credited_collection_split(active, basis_final)
        for allocation in active:
            apply_changes(allocation, {
                "credited_collection_provisional_cents": provisional[allocation["id"]],
                "credited_collection_final_cents": final[allocation["id"]],
            })
    for allocation in store.allocations.values():
        if allocation["state"] != "ACTIVE":
            apply_changes(allocation, {
                "credited_collection_provisional_cents": 0,
                "credited_collection_final_cents": 0,
            })

    # ---- partner base inputs --------------------------------------------
    active_by_partner = {}
    for allocation in store.allocations.values():
        if allocation["state"] != "ACTIVE":
            continue
        active_by_partner.setdefault(allocation["partner_id"], []).append(allocation)

    for partner in store.partners.values():
        allocations = active_by_partner.get(partner["id"], [])
        credited_provisional = sum(a["credited_collection_provisional_cents"] for a in allocations)
        credited_final = sum(a["credited_collection_final_cents"] for a in allocations)
        if anchor is None:
            billable_hours = D("0.00")
        else:
            total = D("0")
            for record in store.records.values():
                if (record["partner_id"] == partner["id"]
                        and record["cycle_id"] == anchor["id"]
                        and record["kind"] == "BILLABLE"
                        and record["verified"]):
                    total += record["hours"]
            billable_hours = rhu(total, 2)
        apply_changes(partner, {
            "credited_collection_provisional_cents": credited_provisional if anchor else 0,
            "credited_collection_final_cents": credited_final if anchor else 0,
            "verified_billable_hours": billable_hours,
            "non_billable_points": calc.non_billable_points(partner, anchor),
            "committee_points": calc.committee_points(partner, anchor),
        })

    # ---- firm normalization + formula scores ----------------------------
    in_scope = [p for p in store.partners.values()
                if p["status"] in ("ACTIVE", "NOTICE_GIVEN")]
    firm_provisional = sum(p["credited_collection_provisional_cents"] for p in in_scope)
    firm_final = sum(p["credited_collection_final_cents"] for p in in_scope)
    factor_provisional = calc.normalization_factor(firm_provisional)
    factor_final = calc.normalization_factor(firm_final)

    for partner in store.partners.values():
        allocations = active_by_partner.get(partner["id"], [])
        if anchor is None:
            apply_changes(partner, {
                "normalized_credit_index_provisional": D("0.000000"),
                "normalized_credit_index_final": D("0.000000"),
                "blended_realization_pct": D("0.0000"),
                "weighted_profitability_points": D("0.0000"),
                "formula_score_provisional": D("0.0000"),
                "formula_score_final": D("0.0000"),
            })
            continue
        provisional = calc.formula_score(
            partner, allocations, "credited_collection_provisional_cents", factor_provisional)
        final = calc.formula_score(
            partner, allocations, "credited_collection_final_cents", factor_final)
        apply_changes(partner, {
            "normalized_credit_index_provisional": provisional["normalized_credit_index"],
            "normalized_credit_index_final": final["normalized_credit_index"],
            "blended_realization_pct": provisional["blended_realization_pct"],
            "weighted_profitability_points": provisional["weighted_profitability_points"],
            "formula_score_provisional": provisional["formula_score"],
            "formula_score_final": final["formula_score"],
        })

    # ---- partner capital, draws and responsibility counters -------------
    withheld_by_partner = {}
    drawn_by_partner = {}
    for payment in store.payments.values():
        award = store.awards.get(payment["award_id"])
        if award is None:
            continue
        partner_id = award["partner_id"]
        if payment["kind"] == "CAPITAL_WITHHOLDING":
            withheld_by_partner[partner_id] = (
                withheld_by_partner.get(partner_id, 0) + payment["amount_cents"])
        if payment["kind"] in ("SCHEDULED_DRAW", "DRAW_REVERSAL"):
            if anchor is not None and award["cycle_id"] == anchor["id"]:
                drawn_by_partner[partner_id] = (
                    drawn_by_partner.get(partner_id, 0) + payment["amount_cents"])

    for partner in store.partners.values():
        responsible = 0
        for matter in store.matters.values():
            if matter["state"] == "OPEN" and matter["responsible_attorney_id"] == partner["id"]:
                responsible += 1
        apply_changes(partner, {
            "capital_account_balance_cents": (partner["opening_capital_cents"]
                                             + partner["_voluntary_capital_cents"]
                                             + withheld_by_partner.get(partner["id"], 0)),
            "ytd_draw_paid_cents": drawn_by_partner.get(partner["id"], 0),
            "responsible_matter_count": responsible,
        })

    # ---- self-assessment peer review roll-up ----------------------------
    for assessment in store.assessments.values():
        scored = [r for r in assessment_reviews(assessment["id"]) if r["state"] == "SCORED"]
        if scored:
            total = sum((r["composite_score"] for r in scored), D("0"))
            mean = rhu(total / D(len(scored)), 4)
        else:
            mean = D("0.0000")
        apply_changes(assessment, {
            "scored_review_count": len(scored),
            "mean_peer_score": mean,
        })

    # ---- cycle aggregate totals -----------------------------------------
    for cycle in store.cycles.values():
        if anchor is not None and cycle["id"] == anchor["id"]:
            formula_total = D("0")
            committee_total = D("0")
            for partner in store.partners.values():
                if partner["status"] not in ("ACTIVE", "NOTICE_GIVEN"):
                    continue
                if partner["compensation_model"] == "FORMULA":
                    formula_total += partner["formula_score_provisional"]
                if partner["compensation_model"] == "DISCRETIONARY":
                    committee_total += partner["committee_points"]
            totals = {
                "total_formula_score": rhu(formula_total, 4),
                "total_committee_points": rhu(committee_total, 2),
            }
        else:
            totals = {
                "total_formula_score": D("0.0000"),
                "total_committee_points": D("0.00"),
            }
        totals["confidentiality_locked"] = cycle["state"] == "CLOSED"
        apply_changes(cycle, totals)

    # ---- awards ---------------------------------------------------------
    for award in store.awards.values():
        drawn = 0
        for payment in award_payments(award["id"]):
            if payment["kind"] in ("SCHEDULED_DRAW", "DRAW_REVERSAL"):
                drawn += payment["amount_cents"]
        changes = {"draw_paid_cents": drawn}
        # A freshly created award is created "with `target_award_cents` of 0"
        # (PRD 3.8) and only publication assigns it money. The PROPOSED-award
        # recompute of the cascades therefore applies only to an award that has
        # already been published once and returned to PROPOSED through a reopen.
        if award["award_state"] == "PROPOSED" and award["reconsideration_count"] > 0:
            changes["target_award_cents"] = calc.award_amount(award, "PROVISIONAL_DELIBERATION")
        apply_changes(award, changes)
        if award["payment_state"] in ("TRUED_UP", "SETTLED"):
            partner = store.partners[award["partner_id"]]
            shortfall = max(0, partner["target_capital_cents"]
                            - partner["capital_account_balance_cents"])
            changes = {"capital_shortfall_cents": shortfall}
            if award["payment_state"] == "TRUED_UP" and shortfall == 0:
                changes["payment_state"] = "SETTLED"
            apply_changes(award, changes)

    # ---- cycle cash counters --------------------------------------------
    for cycle in store.cycles.values():
        awards = cycle_awards(cycle["id"])
        award_ids = {a["id"] for a in awards}
        paid = 0
        for payment in store.payments.values():
            if payment["award_id"] in award_ids:
                paid += payment["amount_cents"]
        unsettled = sum(1 for a in awards if a["payment_state"] != "SETTLED")
        apply_changes(cycle, {
            "undistributed_cash_cents": cycle["distributable_pool_cents"] - paid,
            "unsettled_award_count": unsettled,
        })


def commit(entity):
    """Run the cascade, then hand the (possibly re-versioned) row back."""
    recompute_all()
    return entity
