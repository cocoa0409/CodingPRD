"""Business-logic reconciliation: rollups, ledger, SAP, refunds, cascades.

All computed fields on an EnrollmentAgreement are re-derived synchronously from
the underlying ledger rows (attendance, disbursements) whenever any contributing
mutation occurs. Each such re-derivation is a mutation of the agreement and bumps
its version exactly once per client request (the caller is responsible for the
single bump; the recompute functions here only set values, they do NOT bump).
"""
from decimal import Decimal

from db import store, now_ts
from helpers import bump, round_half_up_cents, round_half_up_4


# --------------------------------------------------------------------------
# Lookups by foreign key
# --------------------------------------------------------------------------
def attendance_rows_for(agreement_id):
    return [e for e in store.attendance_entries.values()
            if e["agreement_id"] == agreement_id]


def disbursements_for(agreement_id):
    return [e for e in store.aid_disbursements.values()
            if e["agreement_id"] == agreement_id]


def assignments_for(agreement_id):
    return [e for e in store.externship_assignments.values()
            if e["agreement_id"] == agreement_id]


def sap_standings_for(agreement_id):
    return [e for e in store.sap_standings.values()
            if e["agreement_id"] == agreement_id]


def latest_sap_standing(agreement_id):
    """Most recent SapStanding for an agreement by creation order (_seq)."""
    rows = sap_standings_for(agreement_id)
    if not rows:
        return None
    rows.sort(key=lambda e: e.get("_seq", 0))
    return rows[-1]


# --------------------------------------------------------------------------
# §1.3 clock_hour_rollup + attendance_pct + completion_pct + ledger + licensure
# Recompute ALL agreement-derived figures from current ledger state.
# Does NOT bump the agreement version (caller does that exactly once).
# --------------------------------------------------------------------------
def recompute_agreement(agreement):
    rows = attendance_rows_for(agreement["id"])

    theory = Decimal("0")
    externship = Decimal("0")
    scheduled_denom = Decimal("0")
    for r in rows:
        st = r["status"]
        if st == "VOIDED":
            continue
        # POSTED contributes attended to its bucket; both POSTED+EXCUSED count
        # scheduled_hours into the denominator.
        if st == "POSTED":
            ah = Decimal(str(r["attended_hours"]))
            if r["kind"] == "THEORY":
                theory += ah
            else:  # EXTERNSHIP
                externship += ah
        scheduled_denom += Decimal(str(r["scheduled_hours"]))

    clock = theory + externship

    agreement["theory_hours_completed"] = _num(theory)
    agreement["externship_hours_completed"] = _num(externship)
    agreement["clock_hours_completed"] = _num(clock)
    agreement["scheduled_hours_to_date"] = _num(scheduled_denom)

    program = store.programs[agreement["program_id"]]
    required = Decimal(str(program["required_clock_hours"]))

    # completion_pct = clock / required (required > 0 by program constraint)
    agreement["completion_pct"] = _num(clock / required) if required != 0 else 0.0

    # attendance_pct: 1.0 when denominator is 0
    if scheduled_denom == 0:
        agreement["attendance_pct"] = 1.0
    else:
        agreement["attendance_pct"] = _num(clock / scheduled_denom)

    # Ledger: disbursed = sum of RELEASED amount_cents
    disbursed = 0
    for d in disbursements_for(agreement["id"]):
        if d["status"] == "RELEASED":
            disbursed += d["amount_cents"]
    agreement["disbursed_aid_cents"] = disbursed
    agreement["ledger_balance_cents"] = agreement["contract_tuition_cents"] - disbursed

    # sap_standing mirror is maintained explicitly by SAP/appeal flows; default
    # GOOD when no review exists (do not overwrite an explicit mirror here).
    agreement.setdefault("sap_standing", "GOOD")

    # licensure_eligible derived (see §1.3 licensure_eligibility)
    agreement["licensure_eligible"] = _compute_licensure(agreement, program)


def _compute_licensure(agreement, program):
    clock = Decimal(str(agreement["clock_hours_completed"]))
    theory = Decimal(str(agreement["theory_hours_completed"]))
    externship = Decimal(str(agreement["externship_hours_completed"]))
    graduation_ready = (
        clock >= Decimal(str(program["required_clock_hours"]))
        and theory >= Decimal(str(program["required_theory_hours"]))
        and externship >= Decimal(str(program["required_externship_hours"]))
    )
    att = Decimal(str(agreement["attendance_pct"]))
    min_att = Decimal(str(program["licensure_min_attendance_pct"]))
    return bool(
        graduation_ready
        and att >= min_att
        and agreement.get("sap_standing", "GOOD") in ("GOOD", "WARNING")
    )


def _num(dec):
    """Render a Decimal as int when integral, else float (exact-ish for display)."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# --------------------------------------------------------------------------
# §1.3 sap_pace + sap_standing_classification
# --------------------------------------------------------------------------
def compute_sap(agreement, cohort, program, checkpoint_term_index):
    """Return (measured_pace_pct, measured_attendance_pct, standing)."""
    span = Decimal(str(cohort["end_term_index"])) - Decimal(str(cohort["start_term_index"]))
    # span > 0 by cohort constraint
    elapsed = Decimal(str(checkpoint_term_index)) - Decimal(str(cohort["start_term_index"]))
    elapsed_fraction = elapsed / span
    if elapsed_fraction < Decimal("0"):
        elapsed_fraction = Decimal("0")
    if elapsed_fraction > Decimal("1"):
        elapsed_fraction = Decimal("1")

    required = Decimal(str(program["required_clock_hours"]))
    expected_hours = elapsed_fraction * required
    clock = Decimal(str(agreement["clock_hours_completed"]))
    if expected_hours == 0:
        pace = Decimal("1.0")
    else:
        pace = clock / expected_hours

    measured_pace_pct = round_half_up_4(pace)
    measured_attendance_pct = agreement["attendance_pct"]

    # Classification keyed on pace + prior standing chain.
    prior_row = latest_sap_standing(agreement["id"])
    prior = prior_row["standing"] if prior_row else "GOOD"

    warn_floor = Decimal(str(program["sap_warning_min_pace_pct"]))
    prob_floor = Decimal(str(program["sap_probation_min_pace_pct"]))
    # Compare against thresholds using the rounded stored pace value (>=).
    pace_cmp = Decimal(str(measured_pace_pct))
    if pace_cmp >= warn_floor:
        standing = "GOOD"
    elif pace_cmp >= prob_floor:
        standing = "WARNING"
    else:
        if prior in ("WARNING", "PROBATION"):
            standing = "DISMISSED"
        else:
            standing = "PROBATION"

    return measured_pace_pct, measured_attendance_pct, standing


def refresh_agreement_sap_mirror(agreement):
    """Set agreement.sap_standing to the latest review's standing (GOOD if none)."""
    row = latest_sap_standing(agreement["id"])
    agreement["sap_standing"] = row["standing"] if row else "GOOD"


# --------------------------------------------------------------------------
# §1.3 refund_amount + aid_return
# --------------------------------------------------------------------------
def compute_refund(agreement, cohort, program, method, withdrawal_term_index):
    """Return dict of the four monetary refund figures."""
    contract = agreement["contract_tuition_cents"]
    span = Decimal(str(cohort["end_term_index"])) - Decimal(str(cohort["start_term_index"]))
    elapsed = Decimal(str(withdrawal_term_index)) - Decimal(str(cohort["start_term_index"]))

    # aid_return first (needed for student_refund), based on program progress.
    aid_return_cents = compute_aid_return(agreement, program)

    if withdrawal_term_index <= agreement["cancellation_window_term_index"]:
        tuition_earned = 0
    else:
        if method == "PRO_RATA":
            required = Decimal(str(program["required_clock_hours"]))
            clock = Decimal(str(agreement["clock_hours_completed"]))
            earned_fraction = clock / required if required != 0 else Decimal("0")
            if earned_fraction > Decimal("1"):
                earned_fraction = Decimal("1")
            tuition_earned = round_half_up_cents(Decimal(contract) * earned_fraction)
        else:  # STATE_TABLE
            term_fraction = elapsed / span
            if term_fraction <= Decimal("0.10"):
                retain = Decimal("0.00")
            elif term_fraction <= Decimal("0.25"):
                retain = Decimal("0.25")
            elif term_fraction <= Decimal("0.50"):
                retain = Decimal("0.50")
            elif term_fraction <= Decimal("0.75"):
                retain = Decimal("0.75")
            else:
                retain = Decimal("1.00")
            tuition_earned = round_half_up_cents(Decimal(contract) * retain)

    tuition_refund = max(0, contract - tuition_earned)
    student_refund = max(0, tuition_refund - aid_return_cents)

    return {
        "tuition_earned_cents": tuition_earned,
        "tuition_refund_cents": tuition_refund,
        "aid_return_cents": aid_return_cents,
        "student_refund_cents": student_refund,
    }


def compute_aid_return(agreement, program):
    """Aggregate aid_return_cents: unearned portion of disbursed aid, capped."""
    required = Decimal(str(program["required_clock_hours"]))
    clock = Decimal(str(agreement["clock_hours_completed"]))
    earned_fraction = clock / required if required != 0 else Decimal("0")
    if earned_fraction > Decimal("1"):
        earned_fraction = Decimal("1")
    unearned_fraction = Decimal("1") - earned_fraction
    disbursed = agreement["disbursed_aid_cents"]
    aid_return = round_half_up_cents(Decimal(disbursed) * unearned_fraction)
    if aid_return > disbursed:
        aid_return = disbursed
    return aid_return


def settle_clawback(agreement, aid_return_cents):
    """Claw back aid_return_cents from RELEASED draws, descending index order.

    Each affected draw: RELEASED -> RETURNED, amount_cents reduced by clawed
    share, agreement disbursed/ledger recomputed. Returns list of touched draws.
    The per-draw share is min(remaining, draw.amount_cents); remainder naturally
    lands on the lowest-index drawn-against draw because we iterate desc and stop
    when remaining is exhausted.
    """
    released = [d for d in disbursements_for(agreement["id"]) if d["status"] == "RELEASED"]
    released.sort(key=lambda d: d["disbursement_index"], reverse=True)
    remaining = aid_return_cents
    touched = []
    for draw in released:
        if remaining <= 0:
            break
        share = min(remaining, draw["amount_cents"])
        draw["amount_cents"] = draw["amount_cents"] - share
        draw["status"] = "RETURNED"
        bump(draw)
        remaining -= share
        touched.append(draw)
    return touched


# --------------------------------------------------------------------------
# Cascade: withdraw an agreement (used by withdraw endpoint and denied appeal)
# --------------------------------------------------------------------------
def cascade_withdraw(agreement):
    """Withdraw agreement: record term, decrement cohort, terminate externships.

    Bumps cohort.version and each affected site.version. Bumps the agreement
    version exactly once. Caller must have already validated state.
    """
    agreement["status"] = "WITHDRAWN"
    agreement["withdrawal_term_index"] = store.clock()["current_term_index"]

    cohort = store.cohorts[agreement["cohort_id"]]
    cohort["enrolled_count"] = cohort["enrolled_count"] - 1
    bump(cohort)

    for asg in assignments_for(agreement["id"]):
        if asg["status"] in ("PLACED", "IN_PROGRESS"):
            asg["status"] = "TERMINATED"
            bump(asg)
            site = store.externship_sites[asg["site_id"]]
            site["active_assignment_count"] = site["active_assignment_count"] - 1
            bump(site)

    recompute_agreement(agreement)
    bump(agreement)
