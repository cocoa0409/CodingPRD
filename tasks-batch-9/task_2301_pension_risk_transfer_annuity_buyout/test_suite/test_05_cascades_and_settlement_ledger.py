"""Long cascades: complaint triage into plan accounting, window settlement into the
residual transition, the strict recognition threshold, and the append-only reversal.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors, administrator_headers
from test_helpers.constants import (
    accounting_liability,
    cash_credited_value,
    cash_transfer_expense,
    data_confidence_for,
    funded_status_bp,
    net_lump_sum_cents_for,
    raw_lump_sum_pv,
    recomputed_monthly_benefit,
    round_half_up,
    settlement_liability,
)
from test_helpers.fixtures import (
    InsurerSpec,
    ParticipantSpec,
    QuoteSpec,
    build_authorized_plan,
    build_locked_tranche,
    build_settled_window,
    create_insurer_panel,
    file_complaint,
    initiate_cash_transfer,
    latest_audit,
    list_settlement_entries,
    read_complaint,
    read_funded_status,
    read_participant,
    read_plan,
    read_strategy,
    read_tranche,
    resolve_audit,
    resolve_complaint,
    review_transfer,
    settle_tranche,
    triage_complaint,
    update_valuation,
)

DEFERRED = "DEFERRED_VESTED"

# --- the shared balance sheet -------------------------------------------------
TOTAL_LIABILITY_CENTS = 100000000
PLAN_ASSETS_CENTS = 92000000
SERVICE_COST_CENTS = 3000000
INTEREST_COST_CENTS = 9000000
UNRECOGNIZED_LOSS_CENTS = 4000000

PLAN_OVERRIDES = {
    "total_liability_cents": TOTAL_LIABILITY_CENTS,
    "plan_assets_cents": PLAN_ASSETS_CENTS,
    "service_cost_cents": SERVICE_COST_CENTS,
    "interest_cost_cents": INTEREST_COST_CENTS,
    "unrecognized_actuarial_loss_cents": UNRECOGNIZED_LOSS_CENTS,
    "discount_rate_bps": 500,
}

# --- the buyout tranche, sized so cost lands exactly on the threshold --------
TRANCHE_BENEFIT_CENTS = 100000
TRANSFER_GROSS_CENTS = 12000000
TRANSFER_EXPENSE_CENTS = cash_transfer_expense(TRANSFER_GROSS_CENTS)
PREMIUM_CENTS = cash_credited_value(TRANSFER_GROSS_CENTS)
SETTLEMENT_COST_CENTS = PREMIUM_CENTS + TRANSFER_EXPENSE_CENTS
PBO_SETTLED_CENTS = accounting_liability(TRANCHE_BENEFIT_CENTS, DEFERRED)
GAIN_LOSS_CENTS = SETTLEMENT_COST_CENTS - PBO_SETTLED_CENTS
PRO_RATA_LOSS_CENTS = round_half_up(
    UNRECOGNIZED_LOSS_CENTS * PBO_SETTLED_CENTS, TOTAL_LIABILITY_CENTS
)
TOTAL_CHARGE_CENTS = GAIN_LOSS_CENTS + PRO_RATA_LOSS_CENTS

PANEL = (InsurerSpec("Aurora Life Assurance", "AA_PLUS", 4200, 200000000),)


def _transfer_and_settle(api, tranche, insurer_id):
    transfer = initiate_cash_transfer(
        api, tranche["id"], TRANSFER_GROSS_CENTS, tranche["version"]
    )
    review_transfer(api, transfer["id"], insurer_id, "ACCEPT")
    return settle_tranche(api, tranche["id"])


def _build_buyout(api, participant_specs):
    """Authorize a plan, lock one tranche per participant, and fund each in cash."""
    authorized = build_authorized_plan(
        api, participants=participant_specs, amendment_scope="BUYOUT_ONLY", **PLAN_OVERRIDES
    )
    insurer = create_insurer_panel(api, PANEL)[0]
    tranches = [
        build_locked_tranche(
            api,
            authorized.plan_id,
            [participant],
            [QuoteSpec(insurer["id"], PREMIUM_CENTS, 90, 90)],
            target_cohort=DEFERRED,
            tranche_name="Deferred Vested Tranche {}".format(index + 1),
        )
        for index, participant in enumerate(authorized.participants)
    ]
    return authorized, insurer, tranches


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/settlement_threshold_strict_inequality_at_exact_equality
# ---------------------------------------------------------------------------


def test_a_settlement_cost_equal_to_the_threshold_defers_the_whole_charge(api):
    """Exact equality fails the strict comparison, so nothing hits earnings.

    PRD: "Whether the total charge hits current earnings turns on one **strict**
    comparison: only when the settlement cost is strictly greater than the threshold
    is the total charge recognised immediately, with the deferred amount set to 0. At
    exact equality — and at anything below — the whole total charge is deferred into
    accumulated other comprehensive income instead, and the recognised amount is 0."

    Design: Difficulty/boundary_precision_check/settlement_threshold_strict_inequality_at_exact_equality
    """
    authorized, insurer, tranches = _build_buyout(
        api, [ParticipantSpec(TRANCHE_BENEFIT_CENTS, cohort=DEFERRED)]
    )

    assert SETTLEMENT_COST_CENTS == SERVICE_COST_CENTS + INTEREST_COST_CENTS

    settled = _transfer_and_settle(api, tranches[0], insurer["id"])

    assert settled["tranche_status"] == "SETTLED"
    assert settled["settlement_gain_loss_cents"] == GAIN_LOSS_CENTS

    entries = list_settlement_entries(api, plan_id=authorized.plan_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entry_type"] == "BUYOUT_RECOGNITION"
    assert entry["tranche_id"] == tranches[0]["id"]
    assert entry["window_id"] is None
    assert entry["pbo_settled_cents"] == PBO_SETTLED_CENTS
    assert entry["gain_loss_cents"] == GAIN_LOSS_CENTS
    assert entry["amount_cents"] == 0
    assert entry["deferred_amount_cents"] == TOTAL_CHARGE_CENTS

    plan = read_plan(api, authorized.plan_id)
    assert plan["cumulative_settlement_charge_cents"] == 0
    assert plan["deferred_settlement_charge_cents"] == TOTAL_CHARGE_CENTS


def test_dropping_the_threshold_by_one_cent_relocates_the_identical_charge(api):
    """The same arithmetic recognises everything once the threshold falls below the cost.

    PRD: "The recognition threshold is the plan's `service_cost_cents` plus its
    `interest_cost_cents`, both read as they stood immediately before the cascade."

    PRD: "Whether the total charge hits current earnings turns on one **strict**
    comparison: only when the settlement cost is strictly greater than the threshold
    is the total charge recognised immediately, with the deferred amount set to 0. At
    exact equality — and at anything below — the whole total charge is deferred into
    accumulated other comprehensive income instead, and the recognised amount is 0."

    Design: Difficulty/boundary_precision_check/settlement_threshold_strict_inequality_at_exact_equality
    """
    authorized, insurer, tranches = _build_buyout(
        api,
        [
            ParticipantSpec(TRANCHE_BENEFIT_CENTS, cohort=DEFERRED),
            ParticipantSpec(TRANCHE_BENEFIT_CENTS, cohort=DEFERRED),
        ],
    )

    first = _transfer_and_settle(api, tranches[0], insurer["id"])

    # Restore the balance sheet and shave one cent off the interest cost.
    update_valuation(
        api,
        authorized.plan_id,
        total_liability_cents=TOTAL_LIABILITY_CENTS,
        plan_assets_cents=PLAN_ASSETS_CENTS,
        service_cost_cents=SERVICE_COST_CENTS,
        interest_cost_cents=INTEREST_COST_CENTS - 1,
        unrecognized_actuarial_loss_cents=UNRECOGNIZED_LOSS_CENTS,
    )
    restored = read_plan(api, authorized.plan_id)
    assert restored["interest_cost_cents"] == INTEREST_COST_CENTS - 1
    assert restored["total_liability_cents"] == TOTAL_LIABILITY_CENTS
    assert restored["plan_assets_cents"] == PLAN_ASSETS_CENTS

    second = _transfer_and_settle(api, tranches[1], insurer["id"])

    assert first["settlement_gain_loss_cents"] == second["settlement_gain_loss_cents"]
    assert second["settlement_gain_loss_cents"] == GAIN_LOSS_CENTS

    entries = list_settlement_entries(api, plan_id=authorized.plan_id)
    assert len(entries) == 2
    by_tranche = {entry["tranche_id"]: entry for entry in entries}
    deferred_entry = by_tranche[tranches[0]["id"]]
    recognised_entry = by_tranche[tranches[1]["id"]]

    assert deferred_entry["amount_cents"] == 0
    assert deferred_entry["deferred_amount_cents"] == TOTAL_CHARGE_CENTS
    assert recognised_entry["amount_cents"] == TOTAL_CHARGE_CENTS
    assert recognised_entry["deferred_amount_cents"] == 0
    assert recognised_entry["pbo_settled_cents"] == deferred_entry["pbo_settled_cents"]
    assert recognised_entry["gain_loss_cents"] == deferred_entry["gain_loss_cents"]

    funded = read_funded_status(api, authorized.plan_id)
    assert funded["cumulative_settlement_charge_cents"] == TOTAL_CHARGE_CENTS
    assert funded["deferred_settlement_charge_cents"] == TOTAL_CHARGE_CENTS

    plan = read_plan(api, authorized.plan_id)
    expected_liability = TOTAL_LIABILITY_CENTS - PBO_SETTLED_CENTS
    expected_assets = PLAN_ASSETS_CENTS - TRANSFER_GROSS_CENTS
    assert plan["total_liability_cents"] == expected_liability
    assert plan["plan_assets_cents"] == expected_assets
    assert funded["accounting_funded_status_bp"] == funded_status_bp(
        expected_assets, expected_liability
    )
    assert plan["plan_status"] == "RESIDUAL"


# ---------------------------------------------------------------------------
# Design: Difficulty/transitive_cascade/complaint_triage_reopens_audit_then_remediation_moves_funded_status
# ---------------------------------------------------------------------------

#: Earnings chosen so the recomputation overshoots the stated benefit by 400 cents,
#: inside the audit tolerance yet enough to move the participant's liabilities.
UNDERSTATED_EARNINGS_CENTS = 200800
CORRECTED_BENEFIT_CENTS = 100400
REMEDIATION_CENTS = 250000


def _settled_buyout_with_a_complaint(api):
    authorized, insurer, tranches = _build_buyout(
        api,
        [
            ParticipantSpec(
                TRANCHE_BENEFIT_CENTS,
                cohort=DEFERRED,
                final_average_monthly_earnings_cents=UNDERSTATED_EARNINGS_CENTS,
            )
        ],
    )
    settled = _transfer_and_settle(api, tranches[0], insurer["id"])
    participant = authorized.participants[0]
    complaint = file_complaint(api, participant["id"], "BENEFIT_AMOUNT")
    return authorized, participant, settled, complaint


def test_triage_reopens_the_audit_and_then_blocks_its_own_resolution(api):
    """The reopen hop fires, and the reopened audit gates the money hop behind it.

    PRD: "When the determination is `SPONSOR_RESPONSIBLE`, three further hops fire.
    First, the participant's latest non-superseded benefit audit, selected by the
    highest `audit_sequence`, transitions to `REOPENED` with `reopened_by_complaint_id`
    set to this complaint."

    PRD: "The participant's `benefit_audit_status` must not be `REOPENED`, otherwise
    `ERR_AUDIT_STATE_INVALID` — a complaint cannot be closed while the audit it
    reopened is still outstanding."

    Design: Difficulty/transitive_cascade/complaint_triage_reopens_audit_then_remediation_moves_funded_status
    """
    _authorized, participant, settled, complaint = _settled_buyout_with_a_complaint(api)

    triaged = triage_complaint(api, complaint["id"], "SPONSOR_RESPONSIBLE")
    assert triaged["complaint_status"] == "TRIAGED"
    assert triaged["triage_count"] == 1

    audit = latest_audit(api, participant["id"])
    assert audit["audit_status"] == "REOPENED"
    assert audit["reopened_by_complaint_id"] == complaint["id"]

    reopened_participant = read_participant(api, participant["id"])
    assert reopened_participant["benefit_audit_status"] == "REOPENED"
    assert reopened_participant["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "REOPENED"
    )
    assert reopened_participant["data_status"] == "CLEAN"

    # The third triage hop is suppressed: the tranche is already settled.
    tranche = read_tranche(api, settled["id"])
    assert tranche["tranche_status"] == "SETTLED"
    assert reopened_participant["tranche_id"] == tranche["id"]
    assert tranche["data_readiness_flag"] == settled["data_readiness_flag"]

    blocked = api.post_complaint_resolution(
        complaint["id"],
        {"remediation_amount_cents": REMEDIATION_CENTS},
        administrator_headers(),
    )
    validate_error(blocked, api_errors.ERR_AUDIT_STATE_INVALID)

    still_triaged = read_complaint(api, complaint["id"])
    assert still_triaged["complaint_status"] == "TRIAGED"
    assert still_triaged["resolved_at"] is None


def test_correcting_the_reopened_audit_then_resolving_moves_the_plan_funded_status(api):
    """A participant grievance runs all the way into the plan's funded status.

    PRD: "From `REOPENED` the actuary may apply the correction again, moving the audit
    `REOPENED → CORRECTED` with exactly the same consequences as the correction applied
    from `CORRECTION_REQUIRED`, or accept as is with a non-empty `override_rationale`,
    moving it `REOPENED → PASSED_CLOSED` with the same consequences as the override from
    `CORRECTION_REQUIRED`."

    PRD: "When the determination is `SPONSOR_RESPONSIBLE` it additionally appends one
    settlement accounting entry with an `entry_type` of `REMEDIATION` and
    `amount_cents` equal to the remediation amount, increases the plan's
    `cumulative_settlement_charge_cents` by that amount, decreases the plan's
    `plan_assets_cents` by that amount, and recomputes the plan's
    `accounting_funded_status_bp`."

    Design: Difficulty/transitive_cascade/complaint_triage_reopens_audit_then_remediation_moves_funded_status
    """
    authorized, participant, _settled, complaint = _settled_buyout_with_a_complaint(api)

    liability_after_buyout = TOTAL_LIABILITY_CENTS - PBO_SETTLED_CENTS
    assets_after_buyout = PLAN_ASSETS_CENTS - TRANSFER_GROSS_CENTS
    before = read_funded_status(api, authorized.plan_id)
    assert before["accounting_funded_status_bp"] == funded_status_bp(
        assets_after_buyout, liability_after_buyout
    )

    triage_complaint(api, complaint["id"], "SPONSOR_RESPONSIBLE")
    audit = latest_audit(api, participant["id"])
    resolve_audit(api, audit["id"], "APPLY_CORRECTION")

    assert recomputed_monthly_benefit(UNDERSTATED_EARNINGS_CENTS, 400) == (
        CORRECTED_BENEFIT_CENTS
    )
    corrected = read_participant(api, participant["id"])
    assert latest_audit(api, participant["id"])["audit_status"] == "CORRECTED"
    assert corrected["audited_monthly_benefit_cents"] == CORRECTED_BENEFIT_CENTS
    assert corrected["benefit_audit_status"] == "CORRECTED"
    assert corrected["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "CORRECTED"
    )
    assert corrected["accounting_liability_cents"] == accounting_liability(
        CORRECTED_BENEFIT_CENTS, DEFERRED
    )
    assert corrected["settlement_liability_cents"] == settlement_liability(
        CORRECTED_BENEFIT_CENTS, DEFERRED
    )
    # The transferred participant is outside the aggregated population.
    assert read_plan(api, authorized.plan_id)["total_liability_cents"] == liability_after_buyout

    resolved = resolve_complaint(api, complaint["id"], REMEDIATION_CENTS)
    assert resolved["complaint_status"] == "RESOLVED"
    assert resolved["remediation_amount_cents"] == REMEDIATION_CENTS
    assert resolved["triage_count"] == 1

    entries = list_settlement_entries(api, plan_id=authorized.plan_id)
    assert len(entries) == 2
    remediation = [entry for entry in entries if entry["entry_type"] == "REMEDIATION"]
    assert len(remediation) == 1
    assert remediation[0]["amount_cents"] == REMEDIATION_CENTS
    assert remediation[0]["tranche_id"] is None
    assert remediation[0]["window_id"] is None

    plan = read_plan(api, authorized.plan_id)
    expected_assets = assets_after_buyout - REMEDIATION_CENTS
    assert plan["cumulative_settlement_charge_cents"] == REMEDIATION_CENTS
    assert plan["plan_assets_cents"] == expected_assets
    assert plan["plan_status"] == "RESIDUAL"

    after = read_funded_status(api, authorized.plan_id)
    assert after["accounting_funded_status_bp"] == funded_status_bp(
        expected_assets, liability_after_buyout
    )
    assert after["accounting_funded_status_bp"] < before["accounting_funded_status_bp"]


# ---------------------------------------------------------------------------
# Design: Difficulty/compensating_invariant/complaint_retriage_reverses_remediation_without_erasing_the_ledger
# ---------------------------------------------------------------------------


def _remediated_plan(api):
    authorized, participant, _settled, complaint = _settled_buyout_with_a_complaint(api)
    triage_complaint(api, complaint["id"], "SPONSOR_RESPONSIBLE")
    audit = latest_audit(api, participant["id"])
    resolve_audit(api, audit["id"], "APPLY_CORRECTION")
    resolve_complaint(api, complaint["id"], REMEDIATION_CENTS)
    return authorized, participant, complaint


def test_a_retriage_to_no_error_appends_a_negative_reversal_and_restores_the_plan(api):
    """The ledger is append-only, so the unwind is a new negative row.

    PRD: "When the stored determination was `SPONSOR_RESPONSIBLE`, the recorded
    `remediation_amount_cents` is above 0, and the new determination is `NO_ERROR`, the
    money is unwound exactly: one settlement accounting entry is appended with an
    `entry_type` of `REMEDIATION_REVERSAL` and an `amount_cents` equal to the negative
    of the recorded remediation amount, the complaint's `reversed_amount_cents` is set
    to that remediation amount, the plan's `cumulative_settlement_charge_cents` is
    decreased by it, the plan's `plan_assets_cents` is increased by it, and the plan's
    `accounting_funded_status_bp` is recomputed."

    Design: Difficulty/compensating_invariant/complaint_retriage_reverses_remediation_without_erasing_the_ledger
    """
    authorized, _participant, complaint = _remediated_plan(api)

    liability_after_buyout = TOTAL_LIABILITY_CENTS - PBO_SETTLED_CENTS
    assets_after_buyout = PLAN_ASSETS_CENTS - TRANSFER_GROSS_CENTS

    before = read_funded_status(api, authorized.plan_id)
    assert before["cumulative_settlement_charge_cents"] == REMEDIATION_CENTS
    assert before["deferred_settlement_charge_cents"] == TOTAL_CHARGE_CENTS
    entries_before = list_settlement_entries(api, plan_id=authorized.plan_id)
    assert len(entries_before) == 2

    retriaged = triage_complaint(
        api,
        complaint["id"],
        "NO_ERROR",
        determination_rationale=(
            "Re-review found the notice estimate, not the paid benefit, in error."
        ),
    )

    assert retriaged["complaint_status"] == "TRIAGED"
    assert retriaged["responsibility_determination"] == "NO_ERROR"
    assert retriaged["triage_count"] == 2
    assert retriaged["resolved_at"] is None
    assert retriaged["reversed_amount_cents"] == REMEDIATION_CENTS

    entries_after = list_settlement_entries(api, plan_id=authorized.plan_id)
    assert len(entries_after) == 3
    reversals = [
        entry for entry in entries_after if entry["entry_type"] == "REMEDIATION_REVERSAL"
    ]
    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == -REMEDIATION_CENTS

    # The original remediation row survives untouched.
    original = [entry for entry in entries_after if entry["entry_type"] == "REMEDIATION"]
    assert len(original) == 1
    assert original[0]["amount_cents"] == REMEDIATION_CENTS
    assert original[0]["id"] == [
        entry for entry in entries_before if entry["entry_type"] == "REMEDIATION"
    ][0]["id"]

    plan = read_plan(api, authorized.plan_id)
    assert plan["cumulative_settlement_charge_cents"] == 0
    assert plan["plan_assets_cents"] == assets_after_buyout
    assert plan["total_liability_cents"] == liability_after_buyout

    after = read_funded_status(api, authorized.plan_id)
    assert after["accounting_funded_status_bp"] == funded_status_bp(
        assets_after_buyout, liability_after_buyout
    )
    assert after["accounting_funded_status_bp"] > before["accounting_funded_status_bp"]
    assert after["deferred_settlement_charge_cents"] == TOTAL_CHARGE_CENTS


def test_the_reversal_conserves_the_ledger_identity_and_leaves_the_audit_closed(api):
    """The charge always equals the summed ledger, and the reopen hop does not re-fire.

    PRD: "Its `amount_cents` is the charge recognised immediately in earnings, negative
    for a reversal, and every entry's `amount_cents` sums into the plan's
    `cumulative_settlement_charge_cents`."

    PRD: "In every case the re-triage records the new determination and
    `determination_rationale`, increments `triage_count` by one, clears `resolved_at`,
    and bumps the `version`."

    Design: Difficulty/compensating_invariant/complaint_retriage_reverses_remediation_without_erasing_the_ledger
    """
    authorized, participant, complaint = _remediated_plan(api)

    def ledger_matches_plan():
        entries = list_settlement_entries(api, plan_id=authorized.plan_id)
        plan = read_plan(api, authorized.plan_id)
        assert plan["cumulative_settlement_charge_cents"] == sum(
            entry["amount_cents"] for entry in entries
        )
        return entries

    assert len(ledger_matches_plan()) == 2

    triage_complaint(
        api,
        complaint["id"],
        "NO_ERROR",
        determination_rationale=(
            "Re-review found the notice estimate, not the paid benefit, in error."
        ),
    )

    assert len(ledger_matches_plan()) == 3

    # The reopen cascade is conditioned on the new determination, so it stays closed.
    assert latest_audit(api, participant["id"])["audit_status"] == "CORRECTED"
    unchanged = read_participant(api, participant["id"])
    assert unchanged["benefit_audit_status"] == "CORRECTED"
    assert unchanged["data_confidence_score"] == data_confidence_for(
        "CONFIRMED", "ALIVE_CONFIRMED", "CORRECTED"
    )


# ---------------------------------------------------------------------------
# Design: Difficulty/transitive_cascade/window_settlement_cascades_elections_participants_plan_then_residual
# ---------------------------------------------------------------------------

WINDOW_BENEFITS = (100000, 20000)
WINDOW_CLOSES_AT = "2026-10-31T00:00:00.000Z"


def _lump_sum_plan_with_two_electors(api):
    authorized = build_authorized_plan(
        api,
        participants=[ParticipantSpec(benefit, cohort=DEFERRED) for benefit in WINDOW_BENEFITS],
        strategy_type="LUMP_SUM_WINDOW",
        amendment_scope="LUMP_SUM_ONLY",
        **PLAN_OVERRIDES
    )
    return authorized


def test_window_settlement_pays_the_elections_and_moves_both_participants_out(api):
    """One sponsor call pays every honoured election and empties the roster.

    PRD: "In the first hop, every election of the window still in `ELECTED_LUMP_SUM`
    transitions to `PAID`, with `paid_at` stamped from the logical clock and
    `paid_amount_cents` set to that election's `net_lump_sum_cents`. In the second hop,
    because those elections became `PAID`, each corresponding participant transitions
    `IN_PLAN → SETTLED_LUMP_SUM` and has its `tranche_id` cleared."

    Design: Difficulty/transitive_cascade/window_settlement_cascades_elections_participants_plan_then_residual
    """
    authorized = _lump_sum_plan_with_two_electors(api)
    initial = read_funded_status(api, authorized.plan_id)
    assert initial["accounting_funded_status_bp"] == funded_status_bp(
        PLAN_ASSETS_CENTS, TOTAL_LIABILITY_CENTS
    )

    settled = build_settled_window(
        api, authorized.plan_id, authorized.participants, closes_at=WINDOW_CLOSES_AT
    )

    expected_nets = [
        net_lump_sum_cents_for(raw_lump_sum_pv(benefit, DEFERRED)) for benefit in WINDOW_BENEFITS
    ]
    paid_total = sum(expected_nets)

    assert settled.window["window_status"] == "SETTLED"
    assert settled.window["notice_count"] == 2
    assert settled.window["approved_lump_sum_total_cents"] == paid_total
    assert settled.window["paid_lump_sum_total_cents"] == paid_total
    assert settled.window["settled_at"] == WINDOW_CLOSES_AT

    for election, expected_net in zip(settled.elections, expected_nets):
        assert election["election_status"] == "PAID"
        assert election["net_lump_sum_cents"] == expected_net
        assert election["paid_amount_cents"] == expected_net

    for participant in authorized.participants:
        row = read_participant(api, participant["id"])
        assert row["participant_status"] == "SETTLED_LUMP_SUM"
        assert row["tranche_id"] is None


def test_paying_cash_to_shed_liability_lowers_the_funded_status_and_ends_the_plan(api):
    """The cash leaving and the liability leaving are different figures.

    PRD: "In the third hop, because those participants have left the `IN_PLAN` and
    `ASSIGNED` population, the plan's `total_liability_cents` is reduced by the sum of
    the paid participants' `accounting_liability_cents`, the plan's `plan_assets_cents`
    is reduced by `paid_lump_sum_total_cents`, and the plan's
    `participant_liability_total_cents` and `accounting_funded_status_bp` are
    recomputed."

    PRD: "Its `pbo_settled_cents` is the sum of the paid participants'
    `accounting_liability_cents`, its `amount_cents` is `paid_lump_sum_total_cents`
    minus that `pbo_settled_cents`, and its `deferred_amount_cents` is 0 — a lump-sum
    disbursement is recognised immediately and nothing is held back in accumulated
    other comprehensive income."

    Design: Difficulty/transitive_cascade/window_settlement_cascades_elections_participants_plan_then_residual
    """
    authorized = _lump_sum_plan_with_two_electors(api)
    before = read_funded_status(api, authorized.plan_id)

    settled = build_settled_window(
        api, authorized.plan_id, authorized.participants, closes_at=WINDOW_CLOSES_AT
    )

    paid_total = sum(
        net_lump_sum_cents_for(raw_lump_sum_pv(benefit, DEFERRED)) for benefit in WINDOW_BENEFITS
    )
    pbo_settled = sum(accounting_liability(benefit, DEFERRED) for benefit in WINDOW_BENEFITS)
    expected_liability = TOTAL_LIABILITY_CENTS - pbo_settled
    expected_assets = PLAN_ASSETS_CENTS - paid_total

    # The cash out and the liability out are genuinely different amounts.
    assert paid_total != pbo_settled

    plan = read_plan(api, authorized.plan_id)
    assert plan["total_liability_cents"] == expected_liability
    assert plan["plan_assets_cents"] == expected_assets
    assert plan["cumulative_settlement_charge_cents"] == paid_total - pbo_settled

    after = read_funded_status(api, authorized.plan_id)
    assert after["participant_liability_total_cents"] == 0
    assert after["accounting_funded_status_bp"] == funded_status_bp(
        expected_assets, expected_liability
    )
    assert after["accounting_funded_status_bp"] < before["accounting_funded_status_bp"]

    entries = list_settlement_entries(api, plan_id=authorized.plan_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entry_type"] == "LUMP_SUM_RECOGNITION"
    assert entry["window_id"] == settled.window_id
    assert entry["tranche_id"] is None
    assert entry["pbo_settled_cents"] == pbo_settled
    assert entry["amount_cents"] == paid_total - pbo_settled
    assert entry["deferred_amount_cents"] == 0


def test_the_plan_becomes_residual_and_drags_the_approved_strategy_to_executed(api):
    """The fourth hop turns the plan residual, which itself executes the strategy.

    PRD: "In the fourth hop, because the plan's liability changed and every window and
    tranche of the plan may now be terminal, the plan is re-evaluated for the residual
    transition described in §3.9 and moves `SETTLEMENT_AUTHORIZED → RESIDUAL` when that
    transition's preconditions hold."

    PRD: "The transition stamps `residual_effective_at` from the logical clock,
    recomputes `accounting_funded_status_bp` and `participant_liability_total_cents`,
    cascades every de-risking strategy of the plan still in `APPROVED` to `EXECUTED`,
    and bumps the plan's `version` along with each strategy's."

    Design: Difficulty/transitive_cascade/window_settlement_cascades_elections_participants_plan_then_residual
    """
    authorized = _lump_sum_plan_with_two_electors(api)
    assert authorized.strategy["strategy_status"] == "APPROVED"

    build_settled_window(
        api, authorized.plan_id, authorized.participants, closes_at=WINDOW_CLOSES_AT
    )

    plan = read_plan(api, authorized.plan_id)
    assert plan["plan_status"] == "RESIDUAL"
    assert plan["residual_effective_at"] == WINDOW_CLOSES_AT

    strategy = read_strategy(api, authorized.plan_id, authorized.strategy["id"])
    assert strategy["strategy_status"] == "EXECUTED"
