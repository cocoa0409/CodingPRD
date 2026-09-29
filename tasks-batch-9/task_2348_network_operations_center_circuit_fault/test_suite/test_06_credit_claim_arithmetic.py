"""Credit claims: pinned rounding order, the exposure ledger and its threshold.

The money side of a fault is a chain of derivations with a fixed order — target,
restoration figure, breach, breach hours, percentage, per-path lines, ceiling —
and then a ledger whose threshold flag has to move in both directions.
"""

from test_helpers import (
    SHIFT_LEAD_USER_ID,
    VENDOR_MANAGER_HEADERS,
    ApiErrorId,
    assert_carrier_ledger,
    assert_credit_arithmetic,
    assert_incident_classification,
    assert_instant,
    assert_page,
    assert_whole_cents,
    build_approved_carrier_window,
    build_nlc_four_path,
    build_nlc_single_gold,
    claim_settle_payload,
    claim_submit_payload,
    count_claims_for_ticket,
    find_auto_drafted_claim,
    read_carrier,
    read_claim,
    read_incident,
    read_ticket,
    restore_and_confirm,
    sla_credit_claim_payload,
    stamped,
    validate_error,
    validate_paginated,
    validate_success,
    walk_incident_to_mitigated,
)

# The four-line NLC outage: mrc 920000 split over GOLD + SILVER + SILVER + BRONZE.
# Rounding each line first gives 20444 + 10222 + 10222 + 5111 = 45999 cents, one
# cent below the 46000 that summing the unrounded shares would produce.
FOUR_LINE_CREDIT_CENTS = 45999
SUM_THEN_ROUND_CREDIT_CENTS = 46000
# The carrier's cap of 50 percent of 920000 — a ceiling that never binds here.
CREDIT_CEILING_CENTS = 460000


def _four_line_outage_with_maintenance(api, ticket_reference: str) -> dict:
    """A 360-minute outage with an hour of approved carrier maintenance excluded."""
    state = build_nlc_four_path(
        api,
        "2026-08-10T00:00:00Z",
        ticket_reference=ticket_reference,
        ticket_opened_at="2026-08-10T00:30:00Z",
    )
    build_approved_carrier_window(
        api,
        state["circuit_id"],
        state["carrier_id"],
        "2026-08-10T02:00:00Z",
        "2026-08-10T03:00:00Z",
        suppresses_monitoring=False,
        risk_acknowledged=True,
    )
    state["confirmed_ticket"] = restore_and_confirm(
        api,
        state["ticket_id"],
        state["carrier_id"],
        state["alarm_id"],
        "2026-08-10T06:30:00Z",
        "2026-08-10T07:00:00Z",
        confirmer_user_id=SHIFT_LEAD_USER_ID,
    )
    return state


def _four_line_outage(api, ticket_reference: str, **carrier_overrides) -> dict:
    """The same outage without maintenance: 270 carrier minutes, 300 NOC minutes."""
    state = build_nlc_four_path(
        api,
        "2026-08-10T00:00:00Z",
        ticket_reference=ticket_reference,
        ticket_opened_at="2026-08-10T00:30:00Z",
        **carrier_overrides,
    )
    state["confirmed_ticket"] = restore_and_confirm(
        api,
        state["ticket_id"],
        state["carrier_id"],
        state["alarm_id"],
        "2026-08-10T05:00:00Z",
        "2026-08-10T05:30:00Z",
        confirmer_user_id=SHIFT_LEAD_USER_ID,
    )
    return state


class TestPerPathLineRounding:
    """Four service tiers on one circuit make four separately rounded credit lines."""

    def test_each_tier_line_is_rounded_before_the_lines_are_summed(self, api):
        """Rounding per line totals 45999 cents on a 920000-cent monthly charge.

        PRD 3.6: "Each line's share is its own service-tier weight — 4 for `GOLD`, 2 for `SILVER`, 1 for `BRONZE` — divided by the total weight of all lines."
        PRD 3.6: "**The rounding order is pinned:** each line's amount is the circuit's `mrc_cents` multiplied by that line's weight share, multiplied by the credit percentage, divided by 100, and rounded half up to whole cents *for that line*; only then are the rounded line amounts added together."

        Design: Difficulty/combinatorial_formula/sla_credit_per_path_line_rounding_before_summation
        """
        state = _four_line_outage_with_maintenance(api, "NLC-TT-88002")
        ticket = read_ticket(api, state["ticket_id"])
        assert ticket["state"] == "CLOSED_RESTORED", (
            f"the closure is what computes the credit, got {ticket['state']}"
        )

        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "a breached target drafts a claim as the ticket closes"
        assert_credit_arithmetic(
            claim,
            basis="CARRIER_CLOCK",
            sla_target_minutes=240,
            breach_minutes=60.00,
            breach_hours=1,
            credit_amount_cents=FOUR_LINE_CREDIT_CENTS,
        )
        assert claim["origin"] == "AUTO_DRAFT", (
            f"the claim was synthesised, not filed, got {claim['origin']}"
        )
        assert claim["state"] == "DRAFT", f"the new claim is a draft, got {claim['state']}"
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=FOUR_LINE_CREDIT_CENTS,
        )

    def test_the_sum_then_round_total_is_explicitly_not_the_answer(self, api):
        """The claim is one cent below 46000, and the percentage ceiling never binds.

        PRD 3.6: "Summing unrounded shares and rounding once at the end is explicitly not the rule and produces a different total."
        PRD 3.6: "A separate ceiling is computed as the circuit's `mrc_cents` multiplied by the carrier's `credit_pct_cap`, divided by 100 and rounded half up, and `credit_amount_cents` is the smaller of the line total and that ceiling."

        Design: Difficulty/combinatorial_formula/sla_credit_per_path_line_rounding_before_summation
        """
        state = _four_line_outage_with_maintenance(api, "NLC-TT-88002")
        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the closure drafted the claim under test"

        assert_whole_cents(claim["credit_amount_cents"], "credit_amount_cents")
        assert claim["credit_amount_cents"] == FOUR_LINE_CREDIT_CENTS, (
            f"four separately rounded lines total {FOUR_LINE_CREDIT_CENTS} cents, "
            f"got {claim['credit_amount_cents']}"
        )
        assert claim["credit_amount_cents"] != SUM_THEN_ROUND_CREDIT_CENTS, (
            f"{SUM_THEN_ROUND_CREDIT_CENTS} is the sum-then-round reading and is not the rule"
        )
        assert claim["credit_amount_cents"] < CREDIT_CEILING_CENTS, (
            "a one-breach-hour credit is far below the percentage ceiling, so the "
            "ceiling must not be what the claim reports"
        )
        assert_incident_classification(
            read_incident(api, state["incident_id"]), severity="SEV1"
        )
        assert read_incident(api, state["incident_id"])["affected_path_count"] == 4, (
            "all four paths ride the failed circuit, so the credit has four lines"
        )


class TestAutoDraftFeedsTheExposureLedger:
    """Closing a ticket is a financial cascade ending in a threshold flag."""

    def test_closing_the_ticket_drafts_the_claim_and_charges_the_carrier(self, api):
        """One confirmation produces exactly one claim and moves the ledger to 45999.

        PRD 3.6: "At the moment a ticket closes as `CLOSED_RESTORED`, the service computes what the outage is worth on the carrier clock and, when that amount comes out strictly greater than zero, synthesises a claim automatically: `origin` `AUTO_DRAFT`, `state` `DRAFT`, `basis` `CARRIER_CLOCK`."
        PRD 3.6: "A drafted claim immediately enters the carrier's open exposure, raising `open_credit_exposure_cents` by its `credit_amount_cents`, and if that raises exposure to or above the carrier's `watchlist_exposure_threshold_cents`, `watchlist_state` flips `ACTIVE → WATCHLIST`."

        Design: Difficulty/transitive_cascade/confirm_restoration_to_auto_claim_to_exposure_ledger_to_watchlist
        """
        state = _four_line_outage(
            api, "NLC-TT-88004", watchlist_exposure_threshold_cents=45999
        )
        closed = state["confirmed_ticket"]

        assert closed["state"] == "CLOSED_RESTORED", (
            f"the confirmation closed the ticket, got {closed['state']}"
        )
        assert_instant(
            closed["confirmed_at"], stamped("2026-08-10", "05:30"), "confirmed_at"
        )
        assert closed["restoration_confirmed_by_user_id"] == SHIFT_LEAD_USER_ID, (
            "the confirming lead is recorded on the ticket"
        )

        rows, meta = validate_paginated(
            api.list_sla_credit_claims(
                VENDOR_MANAGER_HEADERS, params={"carrier_id": state["carrier_id"]}
            )
        )
        assert_page(meta, total_count=1)
        claim = rows[0]
        assert claim["origin"] == "AUTO_DRAFT", (
            f"the claim was synthesised by the closure, got {claim['origin']}"
        )
        assert claim["state"] == "DRAFT", f"it lands in DRAFT, got {claim['state']}"
        assert_credit_arithmetic(
            claim,
            basis="CARRIER_CLOCK",
            sla_target_minutes=240,
            breach_minutes=30.00,
            breach_hours=1,
            credit_amount_cents=FOUR_LINE_CREDIT_CENTS,
        )
        assert claim["carrier_ticket_id"] == state["ticket_id"], (
            "the claim is anchored to the ticket that closed"
        )

    def test_exposure_reaching_the_threshold_exactly_flips_the_watchlist(self, api):
        """A ledger of exactly the threshold is enough: `ACTIVE` becomes `WATCHLIST`.

        PRD 3.6: "The invariant to preserve across all of this is the one stated in Section 2.10: `open_credit_exposure_cents` always equals the sum of `credit_amount_cents` over that carrier's claims in `DRAFT`, `SUBMITTED` or `ACKNOWLEDGED`, and `watchlist_state` is `WATCHLIST` exactly when that sum has reached or passed `watchlist_exposure_threshold_cents`."
        PRD 3.1: "A freshly created carrier starts with `open_credit_exposure_cents` at 0, `committed_upgrade_mbps` at 0, `chronic_circuit_count` at 0 and `watchlist_state` `ACTIVE`; the alternative posture, `WATCHLIST`, is only ever reached by the derivations in Sections 3.6 and 3.8."

        Design: Difficulty/transitive_cascade/confirm_restoration_to_auto_claim_to_exposure_ledger_to_watchlist
        """
        state = build_nlc_four_path(
            api,
            "2026-08-10T00:00:00Z",
            ticket_reference="NLC-TT-88004",
            ticket_opened_at="2026-08-10T00:30:00Z",
            watchlist_exposure_threshold_cents=45999,
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=0,
            watchlist_state="ACTIVE",
        )

        restore_and_confirm(
            api,
            state["ticket_id"],
            state["carrier_id"],
            state["alarm_id"],
            "2026-08-10T05:00:00Z",
            "2026-08-10T05:30:00Z",
            confirmer_user_id=SHIFT_LEAD_USER_ID,
        )

        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=FOUR_LINE_CREDIT_CENTS,
            watchlist_state="WATCHLIST",
        )
        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the flip is driven by a real drafted claim"
        assert claim["credit_amount_cents"] == FOUR_LINE_CREDIT_CENTS, (
            "the exposure is exactly the claim amount, so the threshold is met and not exceeded"
        )


class TestSubmissionCheckOrder:
    """Submission runs a state check before it ever looks at the money."""

    def test_the_incident_state_refusal_outranks_the_minimum_amount_refusal(self, api):
        """Both conditions hold, and the answer names the incident, not the amount.

        PRD 2.7: "Checks are evaluated strictly in the ascending sequence below; the first failure short-circuits the request and no later check runs."
        PRD 3.6: "The incident behind that ticket must have `response_state` `MITIGATED` or `RESOLVED`, otherwise `ERR_INCIDENT_NOT_MITIGATED`."

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_incident_not_mitigated_beats_claim_below_minimum
        """
        state = _four_line_outage(
            api, "NLC-TT-88005", min_claim_amount_cents=100000
        )
        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the closure drafted the claim under test"
        assert claim["credit_amount_cents"] == FOUR_LINE_CREDIT_CENTS, (
            "the drafted amount is well below the carrier's 100000-cent minimum"
        )
        assert_incident_classification(
            read_incident(api, state["incident_id"]), response_state="DETECTED"
        )

        validate_error(
            api.submit_sla_credit_claim(
                claim["id"],
                claim_submit_payload(
                    basis="CARRIER_CLOCK",
                    attestation_note="restoration exceeded the 4-hour target",
                ),
                VENDOR_MANAGER_HEADERS,
            ),
            ApiErrorId.ERR_INCIDENT_NOT_MITIGATED,
        )

        stored = read_claim(api, claim["id"])
        assert stored["state"] == "DRAFT", (
            f"the refused submission leaves the claim in DRAFT, got {stored['state']}"
        )
        assert stored["submitted_at"] is None, "nothing was submitted, so no stamp"
        assert stored["submitted_by_user_id"] is None, (
            "no submitter is recorded on a refused submission"
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=FOUR_LINE_CREDIT_CENTS,
        )

    def test_the_minimum_amount_refusal_was_waiting_underneath(self, api):
        """With the incident mitigated the same request fails on fiscal admissibility.

        PRD 3.6: "The `credit_amount_cents` must be strictly greater than zero, otherwise `ERR_NO_SLA_BREACH`, and must be at least the carrier's `min_claim_amount_cents`, otherwise `ERR_CLAIM_BELOW_MINIMUM`."
        PRD 3.1: "`min_claim_amount_cents` is the contractual floor beneath which a claim may not be submitted at all and defaults to 5000 cents, with zero permitted."

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_incident_not_mitigated_beats_claim_below_minimum
        """
        state = _four_line_outage(
            api, "NLC-TT-88005", min_claim_amount_cents=100000
        )
        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the closure drafted the claim under test"

        walk_incident_to_mitigated(api, state["incident_id"])
        assert_incident_classification(
            read_incident(api, state["incident_id"]), response_state="MITIGATED"
        )

        validate_error(
            api.submit_sla_credit_claim(
                claim["id"],
                claim_submit_payload(
                    basis="CARRIER_CLOCK",
                    attestation_note="restoration exceeded the 4-hour target",
                ),
                VENDOR_MANAGER_HEADERS,
            ),
            ApiErrorId.ERR_CLAIM_BELOW_MINIMUM,
        )

        stored = read_claim(api, claim["id"])
        assert stored["state"] == "DRAFT", (
            f"the claim survives both refusals in DRAFT, got {stored['state']}"
        )
        assert stored["credit_amount_cents"] == FOUR_LINE_CREDIT_CENTS, (
            "re-stating the same basis leaves the amount where it was"
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=FOUR_LINE_CREDIT_CENTS,
        )


class TestBreachRequiresExceedingTheTarget:
    """The target minute itself is not a breach; the next step past it is."""

    def test_restoration_exactly_at_the_target_is_not_a_breach(self, api):
        """A 240.00-minute carrier clock against a 240-minute target drafts nothing.

        PRD 3.6: "`breach_minutes` is the amount by which the restoration figure exceeds the target, and zero when it does not exceed it."
        PRD 3.6: "When the computed amount is exactly zero — the carrier beat its target — no claim row is created at all."

        Design: Difficulty/boundary_precision_check/sla_breach_requires_strictly_exceeding_the_target_minute
        """
        state = build_nlc_four_path(
            api,
            "2026-08-10T00:00:00Z",
            ticket_reference="NLC-TT-88006",
            ticket_opened_at="2026-08-10T00:30:00Z",
        )
        closed = restore_and_confirm(
            api,
            state["ticket_id"],
            state["carrier_id"],
            state["alarm_id"],
            "2026-08-10T04:30:00Z",
            "2026-08-10T05:00:00Z",
            confirmer_user_id=SHIFT_LEAD_USER_ID,
        )

        assert closed["restoration_minutes_carrier_clock"] == 240.00, (
            f"the carrier clock lands exactly on the target, "
            f"got {closed['restoration_minutes_carrier_clock']}"
        )
        assert closed["restoration_minutes_noc_clock"] == 270.00, (
            f"the NOC clock is 30 minutes longer, "
            f"got {closed['restoration_minutes_noc_clock']}"
        )
        assert count_claims_for_ticket(api, state["ticket_id"]) == 0, (
            "a restoration that only reaches the target is not a breach and drafts nothing"
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), exposure_cents=0)

        validate_error(
            api.create_sla_credit_claim(
                sla_credit_claim_payload(
                    state["ticket_id"], closed["version"], basis="CARRIER_CLOCK"
                ),
                VENDOR_MANAGER_HEADERS,
            ),
            ApiErrorId.ERR_NO_SLA_BREACH,
        )
        assert count_claims_for_ticket(api, state["ticket_id"]) == 0, (
            "the refused manual create left no row behind"
        )

    def test_the_noc_clock_reading_of_the_same_outage_is_billable(self, api):
        """One step past the target on the other variant yields a 45999-cent manual claim.

        PRD 3.6: "Then the restoration figure is taken from the ticket according to the claim's `basis` — `restoration_minutes_carrier_clock` for `CARRIER_CLOCK`, `restoration_minutes_noc_clock` for `NOC_CLOCK`."
        PRD 3.6: "Such a claim is created with `origin` `MANUAL` in `DRAFT`, with `carrier_id` copied from the ticket, `submitted_by_user_id` and `submitted_at` null, `paid_amount_cents` and `rejection_reason` null, and `revision_count` 0."

        Design: Difficulty/boundary_precision_check/sla_breach_requires_strictly_exceeding_the_target_minute
        """
        state = build_nlc_four_path(
            api,
            "2026-08-10T00:00:00Z",
            ticket_reference="NLC-TT-88006",
            ticket_opened_at="2026-08-10T00:30:00Z",
        )
        closed = restore_and_confirm(
            api,
            state["ticket_id"],
            state["carrier_id"],
            state["alarm_id"],
            "2026-08-10T04:30:00Z",
            "2026-08-10T05:00:00Z",
            confirmer_user_id=SHIFT_LEAD_USER_ID,
        )

        claim = validate_success(
            api.create_sla_credit_claim(
                sla_credit_claim_payload(
                    state["ticket_id"], closed["version"], basis="NOC_CLOCK"
                ),
                VENDOR_MANAGER_HEADERS,
            ),
            201,
        )["data"]

        assert claim["origin"] == "MANUAL", (
            f"a hand-filed claim is MANUAL, got {claim['origin']}"
        )
        assert claim["state"] == "DRAFT", f"it starts in DRAFT, got {claim['state']}"
        assert_credit_arithmetic(
            claim,
            basis="NOC_CLOCK",
            sla_target_minutes=240,
            breach_minutes=30.00,
            breach_hours=1,
            credit_amount_cents=FOUR_LINE_CREDIT_CENTS,
        )
        assert claim["carrier_id"] == state["carrier_id"], (
            "the carrier is copied from the ticket rather than supplied"
        )
        assert claim["submitted_at"] is None, "creation is not submission"
        assert claim["submitted_by_user_id"] is None, "no submitter yet"
        assert claim["paid_amount_cents"] is None, "no money has moved"
        assert claim["rejection_reason"] is None, "nothing has been rejected"
        assert claim["revision_count"] == 0, "a first filing has no revisions"
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=FOUR_LINE_CREDIT_CENTS,
        )


class TestWithdrawalCompensatesExactly:
    """Withdrawal must leave no residue on either ledger field."""

    def test_withdrawing_a_draft_returns_the_exposure_to_zero(self, api):
        """The ledger is recomputed from the surviving claims, so it lands on 0.

        PRD 3.6: "Withdrawing from `DRAFT` or from `SUBMITTED` subtracts from `open_credit_exposure_cents` exactly the amount that was added when the claim entered the open set, restoring the ledger — and, when exposure falls back below the threshold, flipping `watchlist_state` `WATCHLIST → ACTIVE`."
        PRD 3.6: "Withdrawal is the compensating action and is available from `DRAFT`, `SUBMITTED` or `REJECTED`; any other state is `ERR_CLAIM_STATE_INVALID`."

        Design: Difficulty/compensating_invariant/claim_withdraw_restores_exposure_and_watchlist_exactly
        """
        state = _four_line_outage(
            api, "NLC-TT-88007", watchlist_exposure_threshold_cents=45999
        )
        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the closure drafted the claim under test"
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=FOUR_LINE_CREDIT_CENTS,
            watchlist_state="WATCHLIST",
        )

        withdrawn = validate_success(
            api.withdraw_sla_credit_claim(claim["id"], {}, VENDOR_MANAGER_HEADERS)
        )["data"]

        assert withdrawn["state"] == "WITHDRAWN", (
            f"the claim is withdrawn, got {withdrawn['state']}"
        )
        assert withdrawn["credit_amount_cents"] == FOUR_LINE_CREDIT_CENTS, (
            "the historical amount stays on the withdrawn row"
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), exposure_cents=0)

    def test_withdrawal_also_reverses_the_watchlist_and_touches_nothing_else(self, api):
        """`WATCHLIST` falls back to `ACTIVE` while the ticket and bandwidth stand still.

        PRD 3.6: "The invariant to preserve across all of this is the one stated in Section 2.10: `open_credit_exposure_cents` always equals the sum of `credit_amount_cents` over that carrier's claims in `DRAFT`, `SUBMITTED` or `ACKNOWLEDGED`, and `watchlist_state` is `WATCHLIST` exactly when that sum has reached or passed `watchlist_exposure_threshold_cents`."
        PRD 2.10: "`committed_upgrade_mbps` is the sum of `delta_mbps` over upgrade orders on that carrier's circuits whose `state` is `DRAFT`, `SUBMITTED`, `APPROVED` or `IN_PROGRESS`; orders in `COMPLETED` or `CANCELLED` are outside the committed set."

        Design: Difficulty/compensating_invariant/claim_withdraw_restores_exposure_and_watchlist_exactly
        """
        state = _four_line_outage(
            api, "NLC-TT-88007", watchlist_exposure_threshold_cents=45999
        )
        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the closure drafted the claim under test"

        validate_success(
            api.withdraw_sla_credit_claim(claim["id"], {}, VENDOR_MANAGER_HEADERS)
        )

        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=0,
            watchlist_state="ACTIVE",
            committed_mbps=0,
        )
        assert read_ticket(api, state["ticket_id"])["state"] == "CLOSED_RESTORED", (
            "a money compensation must not reopen the ticket"
        )
        assert read_claim(api, claim["id"])["state"] == "WITHDRAWN", (
            "the withdrawal is durable"
        )


class TestSettlementRequiresAcknowledgement:
    """Settlement is reachable from one state only, and the check comes first."""

    def test_settling_a_draft_claim_is_refused_on_state(self, api):
        """The paid amount matches exactly and is still never compared.

        PRD 3.6: "It applies only to a claim in `ACKNOWLEDGED`, otherwise `ERR_CLAIM_STATE_INVALID`, and the supplied `paid_amount_cents` must equal the claim's `credit_amount_cents` exactly — partial settlement is not modelled, and a mismatch in either direction is `ERR_CREDIT_AMOUNT_MISMATCH`."
        PRD 2.7: "Checks are evaluated strictly in the ascending sequence below; the first failure short-circuits the request and no later check runs."

        Design: Corner/state_machines/corner_claim_settle_from_draft_rejected
        """
        state = build_nlc_single_gold(
            api,
            "2026-08-15T00:00:00Z",
            ticket_reference="NLC-TT-90001",
            ticket_opened_at="2026-08-15T00:30:00Z",
        )
        restore_and_confirm(
            api,
            state["ticket_id"],
            state["carrier_id"],
            state["alarm_id"],
            "2026-08-15T06:00:00Z",
            "2026-08-15T06:30:00Z",
            confirmer_user_id=SHIFT_LEAD_USER_ID,
        )

        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "the closure drafted the claim under test"
        assert_credit_arithmetic(
            claim,
            basis="CARRIER_CLOCK",
            sla_target_minutes=240,
            breach_minutes=90.00,
            breach_hours=2,
            credit_amount_cents=92000,
        )

        validate_error(
            api.settle_sla_credit_claim(
                claim["id"], claim_settle_payload(92000), VENDOR_MANAGER_HEADERS
            ),
            ApiErrorId.ERR_CLAIM_STATE_INVALID,
        )

        stored = read_claim(api, claim["id"])
        assert stored["state"] == "DRAFT", (
            f"the refused settlement leaves the claim in DRAFT, got {stored['state']}"
        )
        assert stored["paid_amount_cents"] is None, "no payment was recorded"
        assert stored["credit_amount_cents"] == 92000, (
            "a single gold line takes the whole share of the monthly charge"
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), exposure_cents=92000
        )
