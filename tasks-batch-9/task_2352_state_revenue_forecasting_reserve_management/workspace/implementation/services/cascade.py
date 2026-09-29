"""Derived-field propagation (PRD §2.8) — every cascade runs inside the request."""

from datetime import datetime, timedelta, timezone

from db import db, make_record, now_dt, now_iso, ordered, touch
from services import calc
from util import fiscal_year_of, fmt_dt, fy_first_day, parse_date_str, parse_dt

BRIEFING_BLACKOUT_HOURS = 48


# --------------------------------------------------------------------------
# Reserve fund derived state
# --------------------------------------------------------------------------
def refresh_fund_ledger(fund):
    """balance, fiscal-year figures, cooling_off_until, last_transaction_at."""
    rows = calc.transactions_of(fund["id"])
    reversed_ids = set()
    for r in rows:
        if r.get("reverses_transaction_id"):
            reversed_ids.add(r["reverses_transaction_id"])

    fund["balance_cents"] = fund["opening_balance_cents"] + sum(
        r["signed_amount_cents"] for r in rows
    )

    # PRD §3.7: fy_opening_balance_cents counts only rows created STRICTLY BEFORE
    # the start of the fiscal year holding the logical clock, so a deposit minted
    # inside the current fiscal year does not raise it — unless the first
    # certification of that fiscal year has rebased it (PRD §3.6).
    current_fy = fiscal_year_of(now_dt().date())
    fy_start = datetime(fy_first_day(current_fy).year, 7, 1, tzinfo=timezone.utc)
    rebase = fund.get("_fy_rebase")
    if rebase is not None and rebase["fiscal_year"] != current_fy:
        rebase = None

    fy_opening = fund["opening_balance_cents"]
    withdrawn = 0
    for r in rows:
        created = parse_dt(r["created_at"])
        if created < fy_start:
            fy_opening += r["signed_amount_cents"]
        elif r["origin"] == "WITHDRAWAL" and r["id"] not in reversed_ids:
            # A rebase resets fy_withdrawn_cents to 0, so only rows minted after
            # the rebase point count toward the fiscal year's drawn total.
            if rebase is None or r["_seq"] > rebase["seq"]:
                withdrawn += -r["signed_amount_cents"]
    if rebase is not None:
        fy_opening = rebase["opening_balance_cents"]
    fund["fy_opening_balance_cents"] = fy_opening
    fund["fy_withdrawn_cents"] = abs(withdrawn)

    cooling = None
    for r in rows:                                     # ascending: the last match wins
        if r["origin"] == "WITHDRAWAL" and r["id"] not in reversed_ids:
            cooling = r["created_at"]
    if cooling is None:
        fund["cooling_off_until"] = None
    else:
        fund["cooling_off_until"] = fmt_dt(
            parse_dt(cooling) + timedelta(days=fund["cooling_off_days"])
        )

    fund["last_transaction_at"] = rows[-1]["created_at"] if rows else None


def apply_adequacy(fund, ref=None):
    figures = calc.adequacy_figures(fund, ref)
    for key in (
        "volatility_index_bps",
        "target_pct_bps",
        "required_reserve_cents",
        "coverage_ratio_bps",
        "adequacy_band",
        "cushion_credit_bps",
        "disclosed_target_pct_bps",
        "cap_cents",
    ):
        fund[key] = figures[key]


def apply_posture(fund):
    cap = fund["cap_cents"]
    if cap is not None and fund["balance_cents"] >= cap:
        fund["deposit_posture"] = "AT_CAP"
    else:
        fund["deposit_posture"] = "ACCEPTING"


def stale_fund_briefings(fund_id):
    for b in calc.briefings_of_fund(fund_id):
        if b["status"] == "PUBLISHED":
            b["status"] = "STALE"
            b["stale_reason"] = "RESERVE_BALANCE_CHANGED"
            touch(b)


def stale_cycle_briefings(cycle_id):
    for b in calc.briefings_of_cycle(cycle_id):
        if b["status"] == "PUBLISHED":
            b["status"] = "STALE"
            b["stale_reason"] = "CYCLE_SUPERSEDED"
            touch(b)


def mint_transaction(fund, origin, signed_amount_cents, gross=None, overflow=None,
                     reverses=None, source_cycle_id=None, memo=None):
    row = make_record(
        {
            "fund_id": fund["id"],
            "origin": origin,
            "signed_amount_cents": signed_amount_cents,
            "gross_computed_cents": gross,
            "overflow_returned_cents": overflow,
            "reverses_transaction_id": reverses,
            "source_cycle_id": source_cycle_id,
            "memo": memo,
        },
        versioned=False,
    )
    db.transactions[row["id"]] = row
    return row


def balance_changed(fund, ref=None):
    """The fixed chain of PRD §2.8: adequacy, posture, briefings, one version bump."""
    refresh_fund_ledger(fund)
    apply_adequacy(fund, ref)
    apply_posture(fund)
    stale_fund_briefings(fund["id"])
    touch(fund)


# --------------------------------------------------------------------------
# Consensus rounds
# --------------------------------------------------------------------------
def supersede_rounds_of(cycle_id, exclude_id=None):
    for rnd in calc.rounds_of(cycle_id):
        if rnd["id"] == exclude_id:
            continue
        if rnd["status"] not in ("OPEN", "COMPARED", "DISPUTED"):
            continue
        rnd["status"] = "SUPERSEDED"
        for rec in calc.disagreements_of(rnd["id"]):
            if rec["status"] == "OPEN":
                rec["status"] = "VOIDED"
                touch(rec)
        rnd["open_disagreement_count"] = 0
        touch(rnd)


def mint_disagreement(rnd, source_id, exec_amount, leg_amount, variance_bps):
    rec = make_record(
        {
            "round_id": rnd["id"],
            "source_id": source_id,
            "exec_amount_cents": exec_amount,
            "leg_amount_cents": leg_amount,
            "variance_bps": variance_bps,
            "status": "OPEN",
            "resolution_method": None,
            "resolved_amount_cents": None,
            "resolved_by_user_id": None,
            "rationale": None,
            "resolved_at": None,
        }
    )
    db.disagreements[rec["id"]] = rec
    return rec


def compare_round(rnd):
    """Run the comparison fork when the second submission dimension lands."""
    per_source, exec_total, leg_total, variance_bps = calc.variance_figures(rnd)
    rnd["exec_total_cents"] = exec_total
    rnd["leg_total_cents"] = leg_total
    rnd["variance_bps"] = variance_bps

    breaching = [sid for sid, bps in per_source.items()
                 if bps > rnd["per_source_tolerance_bps"]]
    disputed = variance_bps > rnd["variance_tolerance_bps"] or bool(breaching)

    if not disputed:
        rnd["status"] = "COMPARED"
        rnd["open_disagreement_count"] = 0
        rnd["reconciled_total_cents"] = calc.reconciled_total_cents(rnd)
        return

    rnd["status"] = "DISPUTED"
    minted = 0
    for src in calc.active_sources():          # ascending source created_at
        if src["id"] not in per_source:
            continue
        if per_source[src["id"]] <= rnd["per_source_tolerance_bps"]:
            continue
        e = calc.estimate_for(rnd["id"], src["id"], "EXECUTIVE")
        l = calc.estimate_for(rnd["id"], src["id"], "LEGISLATIVE")
        mint_disagreement(rnd, src["id"], e["estimate_amount_cents"],
                          l["estimate_amount_cents"], per_source[src["id"]])
        minted += 1
    rnd["open_disagreement_count"] = minted
    rnd["reconciled_total_cents"] = calc.reconciled_total_cents(rnd)


def recompute_round(rnd):
    """Recompute a round after its estimates moved. Bumps version only on change."""
    if rnd["status"] not in ("OPEN", "COMPARED", "DISPUTED"):
        return
    before = (
        rnd["exec_total_cents"],
        rnd["leg_total_cents"],
        rnd["variance_bps"],
        rnd["reconciled_total_cents"],
        rnd["status"],
        rnd["open_disagreement_count"],
    )

    estimates = calc.estimates_of(rnd["id"])
    if rnd["exec_submission_status"] == "SUBMITTED":
        rnd["exec_total_cents"] = sum(e["estimate_amount_cents"] for e in estimates
                                      if e["body"] == "EXECUTIVE")
    if rnd["leg_submission_status"] == "SUBMITTED":
        rnd["leg_total_cents"] = sum(e["estimate_amount_cents"] for e in estimates
                                     if e["body"] == "LEGISLATIVE")

    if rnd["status"] in ("COMPARED", "DISPUTED"):
        per_source, exec_total, leg_total, variance_bps = calc.variance_figures(rnd)
        rnd["exec_total_cents"] = exec_total
        rnd["leg_total_cents"] = leg_total
        rnd["variance_bps"] = variance_bps

        # A recompute may push a COMPARED round back to DISPUTED (PRD §3.3/§3.4).
        for src in calc.active_sources():
            bps = per_source.get(src["id"])
            if bps is None or bps <= rnd["per_source_tolerance_bps"]:
                continue
            existing = [r for r in calc.disagreements_of(rnd["id"], src["id"])
                        if r["status"] in ("OPEN", "RESOLVED")]
            if existing:
                continue
            e = calc.estimate_for(rnd["id"], src["id"], "EXECUTIVE")
            l = calc.estimate_for(rnd["id"], src["id"], "LEGISLATIVE")
            mint_disagreement(rnd, src["id"], e["estimate_amount_cents"],
                              l["estimate_amount_cents"], bps)

        open_count = len([r for r in calc.disagreements_of(rnd["id"])
                          if r["status"] == "OPEN"])
        rnd["open_disagreement_count"] = open_count
        if open_count > 0:
            rnd["status"] = "DISPUTED"
        rnd["reconciled_total_cents"] = calc.reconciled_total_cents(rnd)

    after = (
        rnd["exec_total_cents"],
        rnd["leg_total_cents"],
        rnd["variance_bps"],
        rnd["reconciled_total_cents"],
        rnd["status"],
        rnd["open_disagreement_count"],
    )
    if before != after:
        touch(rnd)


def recompute_estimate_components(est, cycle, source):
    """Rewrite the four components of an estimate; bumps version only on change."""
    before = (est["weighted_scenario_cents"], est["policy_adjustment_cents"],
              est["one_time_cents"], est["recurring_component_cents"],
              est["estimate_amount_cents"])
    est["one_time_cents"] = calc.one_time_cents(cycle["id"], source["id"])
    est["recurring_component_cents"] = (
        est["weighted_scenario_cents"]
        + est["policy_adjustment_cents"]
        + est["judgmental_adjustment_cents"]
    )
    est["estimate_amount_cents"] = est["recurring_component_cents"] + est["one_time_cents"]
    after = (est["weighted_scenario_cents"], est["policy_adjustment_cents"],
             est["one_time_cents"], est["recurring_component_cents"],
             est["estimate_amount_cents"])
    if before != after:
        touch(est)
        return True
    return False


def one_time_item_cascade(item):
    """Recompute every unlocked estimate of (cycle, source), then its rounds."""
    cycle = db.cycles.get(item["cycle_id"])
    source = db.sources.get(item["source_id"])
    if cycle is None or source is None:
        return
    affected_rounds = []
    for rnd in calc.rounds_of(cycle["id"]):
        if rnd["status"] not in ("OPEN", "COMPARED", "DISPUTED"):
            continue
        changed = False
        for est in calc.estimates_of(rnd["id"]):
            if est["source_id"] != source["id"] or est["locked"]:
                continue
            if recompute_estimate_components(est, cycle, source):
                changed = True
        if changed:
            affected_rounds.append(rnd)
    for rnd in affected_rounds:
        recompute_round(rnd)


# --------------------------------------------------------------------------
# Certification (PRD §3.6)
# --------------------------------------------------------------------------
def certify_cascade(cycle):
    ratified = db.rounds.get(cycle["ratified_round_id"])

    # PRD §3.6: is this the FIRST certification of this fiscal_year? Decided
    # before this cycle stamps its own certified_at.
    first_of_fiscal_year = not any(
        other["id"] != cycle["id"]
        and other["fiscal_year"] == cycle["fiscal_year"]
        and other.get("certified_at") is not None
        for other in db.cycles.values()
    )

    # LINK 1 — certified aggregates and the shortfall.
    cycle["certified_total_cents"] = ratified["reconciled_total_cents"] or 0
    cycle["certified_one_time_cents"] = sum(
        it["amount_cents"] for it in calc.items_of(cycle["id"])
    )
    cycle["certified_recurring_total_cents"] = (
        cycle["certified_total_cents"] - cycle["certified_one_time_cents"]
    )
    cycle["certified_at"] = now_iso()
    gap, pct = calc.shortfall_figures(cycle["enacted_appropriation_cents"],
                                      cycle["certified_total_cents"])
    cycle["shortfall_gap_cents"] = gap
    cycle["shortfall_pct_bps"] = pct
    cycle["status"] = "CERTIFIED"

    # LINKS 2-4 — per fund, in ascending created_at order.
    for fund in ordered(db.funds):
        figures = calc.deposit_computation(cycle, fund, ratified)
        if figures["deposited_cents"] > 0:
            mint_transaction(
                fund,
                "CERTIFICATION_DEPOSIT",
                figures["deposited_cents"],
                gross=figures["gross_computed_cents"],
                overflow=figures["overflow_returned_cents"],
                source_cycle_id=cycle["id"],
                memo="Certification deposit for fiscal year %d" % cycle["fiscal_year"],
            )
        refresh_fund_ledger(fund)

        # PRD §3.6: on the FIRST certification of a given fiscal_year, after the
        # deposit has been applied, every fund's fy_opening_balance_cents is set
        # to its post-deposit balance_cents and fy_withdrawn_cents reset to 0.
        if first_of_fiscal_year:
            rows = calc.transactions_of(fund["id"])
            fund["_fy_rebase"] = {
                "fiscal_year": cycle["fiscal_year"],
                "opening_balance_cents": fund["balance_cents"],
                "seq": max((r["_seq"] for r in rows), default=0),
            }
            refresh_fund_ledger(fund)

        apply_adequacy(fund, cycle)
        apply_posture(fund)
        if figures["deposited_cents"] > 0:
            stale_fund_briefings(fund["id"])
        touch(fund)

    # BRANCH — a revision supersedes its predecessor.
    if cycle["cycle_type"] == "REVISION" and cycle.get("supersedes_cycle_id"):
        pred = db.cycles.get(cycle["supersedes_cycle_id"])
        if (pred is not None and pred["status"] == "CERTIFIED"
                and pred["fiscal_year"] == cycle["fiscal_year"]):
            pred["status"] = "SUPERSEDED"
            touch(pred)
            stale_cycle_briefings(pred["id"])

    touch(cycle)


# --------------------------------------------------------------------------
# Withdrawal execution (PRD §3.8)
# --------------------------------------------------------------------------
def execute_cascade(request, fund):
    amount = request["authorized_amount_cents"]
    row = mint_transaction(
        fund,
        "WITHDRAWAL",
        -amount,
        source_cycle_id=request["cycle_id"],
        memo="Authorized withdrawal execution",
    )
    request["executed_at"] = now_iso()
    request["executed_transaction_id"] = row["id"]
    request["status"] = "EXECUTED"
    balance_changed(fund)          # fy_withdrawn_cents is derived from the ledger
    touch(request)
    return row


# --------------------------------------------------------------------------
# The logical clock (PRD §2.5)
# --------------------------------------------------------------------------
def advance_clock(new_iso):
    db.clock_iso = new_iso
    clock_date = now_dt().date()

    # The fiscal-year figures are relative to the clock; no version bump for them.
    for fund in ordered(db.funds):
        refresh_fund_ledger(fund)

    lapsed = 0
    for req in ordered(db.requests):
        if req["status"] != "APPROVED":
            continue
        deadline = parse_date_str(req["deadline_date"])
        if clock_date > deadline:
            req["status"] = "LAPSED"
            touch(req)
            lapsed += 1
    return lapsed
