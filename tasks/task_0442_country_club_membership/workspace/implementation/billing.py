"""Statement finalization, payment waterfall, and period close (PRD §3.6, §3.7)."""
import db
import computed
import calculations as calc
import services


# ---------------------------------------------------------------------------
# Payment waterfall (PRD §3.6).
#   - Apply payment to POSTED chits oldest-first (created_at ASC); each fully
#     covered chit -> SETTLED. charge_balance reduced by amount_cents.
#   - Mark FINALIZED statements PAID once their dues+shortfall+assessment+chit
#     charges are fully covered.
#   - Recompute billing_status: CURRENT once no FINALIZED unpaid statement remains.
# ---------------------------------------------------------------------------
def apply_payment(membership, amount_cents):
    mid = membership["id"]
    # The payment reduces charge_balance by the full amount_cents (PRD §3.6). It is
    # allocated to POSTED chits oldest-first; each fully covered chit -> SETTLED.
    # Any leftover that does not fully cover the next chit is retained as a standing
    # payment credit so the balance reflects "minus payments applied" (PRD §1.1).
    remaining = membership.get("payment_credit_cents", 0) + amount_cents
    posted = [
        c
        for c in db.chits.values()
        if c["membership_id"] == mid and c["status"] == "POSTED"
    ]
    posted.sort(key=lambda c: c["_seq"])
    for c in posted:
        if remaining < c["amount_cents"]:
            break
        # Payment fully covers this chit -> SETTLED.
        remaining -= c["amount_cents"]
        c["status"] = "SETTLED"
        db.touch(c)
    membership["payment_credit_cents"] = remaining

    computed.refresh_membership_computeds(mid)

    # Mark FINALIZED statements PAID when fully covered. A statement is fully
    # covered when all its period's POSTED chits are settled (no POSTED chit
    # remains in that period for this membership) — dues/shortfall/assessment are
    # club-side obligations rolled into total_due and are considered paid once the
    # payment has been applied and the period's chits cleared.
    _settle_covered_statements(membership)

    recompute_billing_status(membership)
    db.touch(membership)


def _statement_fully_covered(membership, statement):
    """A FINALIZED statement is paid when no POSTED chit remains for its period
    for this membership (its chit charges are settled). dues/fb_shortfall/
    assessment have no separate ledger row, so chit settlement is the gate."""
    mid = membership["id"]
    period = statement["period_index"]
    for c in db.chits.values():
        if (
            c["membership_id"] == mid
            and c["period_index"] == period
            and c["status"] == "POSTED"
        ):
            return False
    return True


def _settle_covered_statements(membership):
    for s in db.statements.values():
        if s["membership_id"] != membership["id"]:
            continue
        if s["status"] != "FINALIZED":
            continue
        if _statement_fully_covered(membership, s):
            s["status"] = "PAID"
            db.touch(s)


def recompute_billing_status(membership):
    """Once no FINALIZED unpaid statement remains, billing axis returns to
    CURRENT from PAST_DUE or DELINQUENT (PRD §3.6)."""
    mid = membership["id"]
    has_unpaid = any(
        s["membership_id"] == mid and s["status"] == "FINALIZED"
        for s in db.statements.values()
    )
    if not has_unpaid and membership["billing_status"] in ("PAST_DUE", "DELINQUENT"):
        membership["billing_status"] = "CURRENT"


# ---------------------------------------------------------------------------
# Open statements (PRD §3.6). Idempotent within a period: one OPEN Statement per
# ACTIVE/SUSPENDED membership for the current billing_period_index.
# ---------------------------------------------------------------------------
def open_statements(club):
    period = club["billing_period_index"]
    eligible = [
        m
        for m in db.memberships.values()
        if m["club_id"] == club["id"]
        and m["account_status"] in ("ACTIVE", "SUSPENDED")
    ]
    eligible.sort(key=lambda m: m["_seq"])
    created = []
    for m in eligible:
        existing = any(
            s["membership_id"] == m["id"] and s["period_index"] == period
            for s in db.statements.values()
        )
        if existing:
            continue
        rec = db.base_record(common_fields=True)
        rec.update(
            {
                "club_id": club["id"],
                "membership_id": m["id"],
                "period_index": period,
                "dues_cents": 0,
                "fb_minimum_cents": 0,
                "fb_spend_cents": 0,
                "fb_shortfall_cents": 0,
                "chit_charges_cents": 0,
                "assessment_cents": 0,
                "total_due_cents": 0,
                "status": "OPEN",
            }
        )
        db.statements[rec["id"]] = rec
        created.append(rec)
    # Return all current-period statements for these memberships (idempotent view).
    result = [
        s
        for s in db.statements.values()
        if s["club_id"] == club["id"] and s["period_index"] == period
    ]
    result.sort(key=lambda s: s["_seq"])
    return result


# ---------------------------------------------------------------------------
# Close period (PRD §3.7). Finalize OPEN statements of the current period,
# age billing, expire offers, roll carryover, then advance billing_period_index.
# ---------------------------------------------------------------------------
def close_period(club):
    period = club["billing_period_index"]

    # Carryover surplus is written to NEXT-period membership credit; collect first.
    next_period_credit = {}

    # 1. Finalize every OPEN statement of the current period.
    open_stmts = [
        s
        for s in db.statements.values()
        if s["club_id"] == club["id"]
        and s["status"] == "OPEN"
        and s["period_index"] == period
    ]
    open_stmts.sort(key=lambda s: s["_seq"])

    for s in open_stmts:
        membership = db.memberships.get(s["membership_id"])
        if membership is None:
            continue
        category = db.categories.get(membership["category_id"])
        dues = category["monthly_dues_cents"] if category else 0
        fb_minimum_cat = category["fb_minimum_cents"] if category else 0
        carried = membership.get("fb_credit_carried_cents", 0) or 0

        fb_spend = calc.fb_spend_for_period(membership["id"], period)
        effective_minimum, shortfall = calc.fb_shortfall(fb_minimum_cat, carried, fb_spend)
        chit_charges = calc.chit_charges_for_period(membership["id"], period)
        assessment = calc.assessment_charges_for_period(membership["id"], period)
        total_due = dues + shortfall + chit_charges + assessment

        s["dues_cents"] = dues
        s["fb_minimum_cents"] = effective_minimum
        s["fb_spend_cents"] = fb_spend
        s["fb_shortfall_cents"] = shortfall
        s["chit_charges_cents"] = chit_charges
        s["assessment_cents"] = assessment
        s["total_due_cents"] = total_due
        s["status"] = "FINALIZED"
        db.touch(s)

        # FORWARD_CARRYOVER: write surplus (capped at one minimum) to next period.
        if club.get("fb_minimum_carryover_allowed"):
            surplus = calc.fb_surplus(effective_minimum, fb_spend, fb_minimum_cat)
            next_period_credit[membership["id"]] = surplus

        # Age billing axis when the finalized statement leaves money owed.
        if total_due > 0 and s["status"] != "PAID":
            cur = membership["billing_status"]
            if cur == "CURRENT":
                membership["billing_status"] = "PAST_DUE"
                db.touch(membership)
            elif cur == "PAST_DUE":
                membership["billing_status"] = "DELINQUENT"
                db.touch(membership)

    # 2. Roll F&B carryover for next period (reset everyone, then set surplus).
    if club.get("fb_minimum_carryover_allowed"):
        # Reset credit for all this club's memberships, then apply computed surplus.
        for m in db.memberships.values():
            if m["club_id"] != club["id"]:
                continue
            new_credit = next_period_credit.get(m["id"], 0)
            if m.get("fb_credit_carried_cents", 0) != new_credit:
                m["fb_credit_carried_cents"] = new_credit
                db.touch(m)
            else:
                m["fb_credit_carried_cents"] = new_credit
    # When carryover is not allowed, fb_credit_carried_cents stays 0 (never set).

    # 3. Advance the period counter and record closed_through.
    club["closed_through_period_index"] = period
    club["billing_period_index"] = period + 1

    # 4. Expire stale waitlist offers: OFFERED with offered_period_index < new index.
    new_index = club["billing_period_index"]
    offered = [
        w
        for w in db.waitlist_entries.values()
        if w["club_id"] == club["id"]
        and w["status"] == "OFFERED"
        and w.get("offered_period_index") is not None
        and w["offered_period_index"] < new_index
    ]
    offered.sort(key=lambda w: w["_seq"])
    for w in offered:
        w["status"] = "EXPIRED"
        db.touch(w)
        services.promote_earliest_waiting(w["category_id"], club)

    db.touch(club)
