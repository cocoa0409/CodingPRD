"""Edges of the placement, milestone, claim, handoff and enforcement machines.

The placement carries a placement dimension and a billing dimension, and the
household lifecycle is a cycle that leaves through suspension and comes back
through settlement; each test drives one of those edges and reads the whole
neighbourhood back.
"""
from test_helpers import (
    BASE_SCENARIO,
    BILLING,
    CASE_OPENER,
    CASE_RESOLVER,
    CONSULTANT,
    PRINCIPAL,
    api_client,
    attest_handoff_payload,
    confirm_start,
    extend_offer,
    file_claim,
    file_enforcement_case,
    invoice_and_pay,
    invoice_milestone,
    provide_claim_info_payload,
    read_candidate,
    read_case,
    read_claim,
    read_client,
    read_handoff,
    read_ledger,
    read_milestone,
    read_placement,
    read_requisition,
    resolve_case,
    resolve_case_payload,
    review_claim,
    review_claim_payload,
    set_clock,
    settle_case,
    settle_case_payload,
    setup_active_placement,
    setup_attested_handoff,
    setup_claim_under_review,
    setup_investigating_case,
    setup_placement_with_first_two_paid,
    setup_scenario,
    setup_substantiated_case,
    setup_terminated_placement,
    terminate_placement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

DISCOVERED_ON = "2026-10-01"
GUARANTEE_EXPIRY_CLOCK = "2026-11-30T00:00:00Z"
PENALTY_CENTS = 1_500_000


class TestPlacementMachine:
    def test_01_an_offer_enters_on_two_dimensions_and_the_provisional_variant(self):
        """Both dimensions and the fee variant start together, household copied.

        PRD §3.6: "Second, the new placement is created with `placement_status`
        `PENDING_ACCEPTANCE`, `billing_status` `UNBILLED`, `fee_variant`
        `PROVISIONAL`, `client_id` taken from the requisition,
        `snapshot_fee_schedule_id`, `fee_percent_bps` and `guarantee_window_days`
        copied from the requisition's resolved snapshot, `guarantee_expires_on`
        computed as `start_date` plus `guarantee_window_days` days, a null
        `separation_date`, a null `void_reason`, `created_by_user_id` stamped from
        `X-User-ID`, and `fee_cents` computed by the `PROVISIONAL` variant described
        in §3.2."

        PRD §3.6: "Fourth, the candidate moves `ON_TRIAL → OFFER_HELD`, or takes
        the `OFFER_HELD → OFFER_HELD` self-loop on the supersede path."

        PRD §3.6: "Fifth, the requisition moves `TRIALING → OFFER_PENDING`, or
        takes the `OFFER_PENDING → OFFER_PENDING` self-loop on the supersede path,
        and its `version` is incremented."

        Design: Corner/state_machines/placement_initial_state_holds_both_dimensions_and_the_provisional_variant
        """
        scenario = setup_scenario(stage="term_accepted")

        placement = extend_offer(scenario["requisition"], scenario["candidate"])
        assert placement["placement_status"] == "PENDING_ACCEPTANCE"
        assert placement["billing_status"] == "UNBILLED"
        assert placement["fee_variant"] == "PROVISIONAL"
        assert placement["client_id"] == scenario["client"]["id"]
        assert placement["separation_date"] is None
        assert placement["void_reason"] is None

        assert read_candidate(scenario["candidate"])["availability_status"] == (
            "OFFER_HELD"
        )
        assert read_requisition(scenario["requisition"])["status"] == "OFFER_PENDING"

    def test_02_confirming_the_start_moves_four_rows_at_once(self):
        """One call re-prices the fee and advances placement, candidate,
        requisition and household.

        PRD §3.6: "Then the **`FINAL` fee** is computed: each of the four
        components is multiplied by the re-resolved `fee_percent_bps`, divided by
        10000 and **rounded half up individually**, in the fixed order
        `base_salary_cents`, then `guaranteed_bonus_cents`, then
        `accommodation_imputed_cents`, then `overtime_allowance_cents`; the four
        rounded results are then summed, and that sum is stored as `fee_cents` with
        `fee_variant` set to `FINAL`."

        PRD §3.6: "Next, `guarantee_expires_on` is recomputed as `start_date` plus
        the re-resolved `guarantee_window_days` days, and the window it describes is
        half-open: it covers `start_date` inclusive up to but excluding
        `guarantee_expires_on`."

        PRD §3.6: "Finally the cascade fans out: the placement moves
        `PENDING_ACCEPTANCE → ACTIVE`, the candidate moves `OFFER_HELD → PLACED`,
        the requisition moves `OFFER_PENDING → PLACED`, and on the household both
        `placement_count` and `non_solicitation_expires_on` are recomputed, the
        latter becoming this `start_date` plus 730 days when this is the household's
        latest placement."

        Design: Corner/state_machines/confirm_start_advances_four_entities_in_one_call
        """
        scenario = setup_scenario(stage="placement_pending")
        set_clock(f"{BASE_SCENARIO['START_DATE']}T00:00:00Z")

        data = confirm_start(scenario["placement"])
        assert data["placement_status"] == "ACTIVE"
        assert data["fee_variant"] == "FINAL"
        assert data["fee_cents"] == 2_000_000
        assert data["guarantee_expires_on"] == BASE_SCENARIO["GUARANTEE_EXPIRES_ON"]

        assert read_candidate(scenario["candidate"])["availability_status"] == "PLACED"
        assert read_requisition(scenario["requisition"])["status"] == "PLACED"

        client = read_client(scenario["client"])
        assert client["placement_count"] == 1
        assert client["non_solicitation_expires_on"] == "2028-08-31"

    def test_03_a_pending_offer_cannot_be_terminated(self):
        """The clock is past the separation date, so only the state guard can fire.

        PRD §3.6: "The placement must be `ACTIVE`; a terminal placement is refused
        with `ERR_ENTITY_TERMINAL` and any other non-terminal state with
        `ERR_PLACEMENT_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/state_machines/terminating_before_confirmation_is_refused
        """
        scenario = setup_scenario(stage="placement_pending")
        set_clock("2026-09-02T00:00:00Z")

        validate_error(
            api_client.terminate_placement(
                scenario["placement"]["id"],
                terminate_placement_payload("2026-09-02"),
                CONSULTANT,
            ),
            "ERR_PLACEMENT_NOT_ACTIVE",
            409,
        )

        after = read_placement(scenario["placement"])
        assert after["placement_status"] == "PENDING_ACCEPTANCE"
        assert after["separation_date"] is None
        assert read_candidate(scenario["candidate"])["availability_status"] == (
            "OFFER_HELD"
        )

    def test_04_an_expired_guarantee_answers_with_the_terminal_lock(self):
        """The sweep made the row terminal, which outranks the ACTIVE precondition.

        PRD §3.8: "And the ops sweep moves any `ACTIVE` placement whose
        `guarantee_expires_on` is on or before the new logical-clock date to
        `GUARANTEE_EXPIRED`, after which no claim may be filed at all."

        PRD §2.11: "Ranked immediately below it, a row already in a terminal state
        yields `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/a_guarantee_expired_placement_is_locked_against_termination
        """
        scenario = setup_active_placement()
        set_clock(GUARANTEE_EXPIRY_CLOCK)
        assert read_placement(scenario["placement"])["placement_status"] == (
            "GUARANTEE_EXPIRED"
        )

        validate_error(
            api_client.terminate_placement(
                scenario["placement"]["id"],
                terminate_placement_payload("2026-11-30"),
                CONSULTANT,
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        after = read_placement(scenario["placement"])
        assert after["placement_status"] == "GUARANTEE_EXPIRED"
        assert after["separation_date"] is None


class TestMilestoneMachine:
    def test_05_invoicing_posts_the_receivable_and_opens_the_billing_axis(self):
        """One invoice stamps net terms, appends one ledger row and moves the
        billing dimension only.

        PRD §3.7: "Invoicing moves the row `PENDING → INVOICED`, stamps
        `invoiced_on` with the logical-clock date, `due_date` as `invoiced_on` plus
        14 days — net two weeks — and `invoiced_by_user_id` from `X-User-ID`;
        appends a `LedgerEntry` of `entry_type` `FEE_INVOICED` with
        `signed_amount_cents` equal to positive `amount_cents` and
        `related_ref_type` `FEE_MILESTONE` pointing at the milestone through
        `related_ref_id`; recomputes the household's `outstanding_balance_cents`;
        and advances the placement's `billing_status` `UNBILLED →
        PARTIALLY_BILLED`, which is admissible when at least one of the placement's
        milestones is now `INVOICED`, `OVERDUE` or `PAID` and at least one is still
        `PENDING`."

        Design: Corner/state_machines/invoicing_a_milestone_posts_the_receivable_and_starts_the_billing_dimension
        """
        scenario = setup_active_placement()
        first = scenario["milestones"][0]

        data = invoice_milestone(first)
        assert data["invoice_status"] == "INVOICED"
        assert data["invoiced_on"] == "2026-09-01"
        assert data["due_date"] == "2026-09-15"
        assert data["invoiced_by_user_id"] is not None
        assert data["amount_cents"] == 600_000

        assert read_client(scenario["client"])["outstanding_balance_cents"] == 600_000
        entries = read_ledger(scenario["client"])
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "FEE_INVOICED"
        assert entries[0]["signed_amount_cents"] == 600_000
        assert entries[0]["sequence_no"] == 1
        assert entries[0]["balance_after_cents"] == 600_000

        placement = read_placement(scenario["placement"])
        assert placement["billing_status"] == "PARTIALLY_BILLED"
        assert placement["placement_status"] == "ACTIVE"

    def test_06_an_uninvoiced_milestone_cannot_be_paid(self):
        """The amount is exact, so the refusal is the state guard, not the amount.

        PRD §3.7: "The row must be `INVOICED` or `OVERDUE`, and any other
        non-terminal state is refused with `ERR_MILESTONE_NOT_INVOICED` (HTTP 409)
        while a terminal row is refused with `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/recording_payment_on_a_pending_milestone_is_refused
        """
        scenario = setup_active_placement()
        first = scenario["milestones"][0]
        assert first["invoice_status"] == "PENDING"

        validate_error(
            api_client.record_milestone_payment(
                first["id"],
                {
                    "paid_amount_cents": first["amount_cents"],
                    "payment_reference": BASE_SCENARIO["PAYMENT_REFERENCE"],
                },
                BILLING,
            ),
            "ERR_MILESTONE_NOT_INVOICED",
            409,
        )

        after = read_milestone(first)
        assert after["invoice_status"] == "PENDING"
        assert after["paid_on"] is None
        assert after["payment_reference"] is None
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0

    def test_07_a_settled_milestone_cannot_be_reversed(self):
        """PAID is terminal, so the settled ledger pair is left exactly as it is.

        PRD §3.7: "Reversal is available to the `BillingAdministrator` with an
        optional `reason`, and is also driven by the system on the placement-void
        cascade."

        PRD §3.7: "The row must be `INVOICED` or `OVERDUE`, or the request is
        refused with `ERR_MILESTONE_NOT_INVOICED`; a terminal row is refused with
        `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/a_paid_milestone_is_locked_against_reversal
        """
        scenario = setup_active_placement()
        paid = invoice_and_pay(scenario["milestones"][0])
        assert paid["invoice_status"] == "PAID"

        validate_error(
            api_client.reverse_fee_milestone(
                paid["id"], {"reason": "Invoice raised in error."}, BILLING
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        assert read_milestone(paid)["invoice_status"] == "PAID"
        entries = read_ledger(scenario["client"])
        assert [entry["entry_type"] for entry in entries] == [
            "FEE_INVOICED",
            "FEE_PAYMENT",
        ]
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0

    def test_08_the_third_payment_completes_the_billing_dimension(self):
        """FULLY_BILLED needs no PENDING row left, so only the last payment does it.

        PRD §3.7: "Recording payment moves the row `INVOICED → PAID` or `OVERDUE →
        PAID`, stamps `paid_on` with the logical-clock date and `payment_reference`,
        appends a `LedgerEntry` of `entry_type` `FEE_PAYMENT` with
        `signed_amount_cents` equal to the negative of `amount_cents`, recomputes
        `outstanding_balance_cents`, and advances the placement's `billing_status`
        `PARTIALLY_BILLED → FULLY_BILLED` once every milestone of the placement has
        an `invoice_status` in `INVOICED`, `OVERDUE`, `PAID`, `VOIDED` or
        `REVERSED` — that is, none remains `PENDING` — and at least one is `PAID`."

        PRD §3.7: "Additionally, for a `START_DATE` milestone, a `PayrollHandoff`
        of that placement must have reached `status` `ATTESTED`, or the invoice is
        refused with `ERR_PAYROLL_HANDOFF_NOT_ATTESTED` (HTTP 409) — a cross-arm
        gate in which the compliance desk blocks the billing desk."

        Design: Corner/state_machines/paying_the_last_open_milestone_completes_the_billing_dimension
        """
        scenario = setup_placement_with_first_two_paid()
        assert read_placement(scenario["placement"])["billing_status"] == (
            "PARTIALLY_BILLED"
        )
        setup_attested_handoff(scenario)
        third = invoice_milestone(scenario["milestones"][2])
        assert third["invoice_status"] == "INVOICED"

        data = validate_success(
            api_client.record_milestone_payment(
                third["id"],
                {
                    "paid_amount_cents": 800_000,
                    "payment_reference": BASE_SCENARIO["PAYMENT_REFERENCE"],
                },
                BILLING,
            )
        )
        assert data["invoice_status"] == "PAID"
        assert data["paid_on"] == "2026-09-01"

        assert read_placement(scenario["placement"])["billing_status"] == "FULLY_BILLED"
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 0
        entries = read_ledger(scenario["client"])
        assert [entry["entry_type"] for entry in entries] == [
            "FEE_INVOICED",
            "FEE_PAYMENT",
            "FEE_INVOICED",
            "FEE_PAYMENT",
            "FEE_INVOICED",
            "FEE_PAYMENT",
        ]
        assert entries[-1]["balance_after_cents"] == 0


class TestClaimMachine:
    def test_09_the_information_loop_returns_the_claim_to_review(self):
        """The claim comes back to the state it left, but the round is counted.

        PRD §3.8: "An `action` of `REQUEST_INFO` moves it `UNDER_REVIEW →
        INFO_REQUESTED` and increments `info_request_round` by 1."

        PRD §3.8: "The household answers by supplying an `info_note`, which is
        exclusive to the `Client` role and moves the claim `INFO_REQUESTED →
        UNDER_REVIEW`, appending the supplied note to `decision_note`; a claim in
        any other state is refused with `ERR_INVALID_STATE_TRANSITION`, and a
        terminal claim with `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/the_claim_information_loop_returns_the_claim_to_review
        """
        scenario = setup_claim_under_review()
        assert scenario["claim"]["status"] == "UNDER_REVIEW"
        assert scenario["claim"]["info_request_round"] == 0

        requested = review_claim(scenario["claim"], "REQUEST_INFO")
        assert requested["status"] == "INFO_REQUESTED"
        assert requested["info_request_round"] == 1

        data = validate_success(
            api_client.provide_claim_info(
                requested["id"],
                provide_claim_info_payload(),
                scenario["client_headers"],
            )
        )
        assert data["status"] == "UNDER_REVIEW"
        assert data["info_request_round"] == 1
        assert read_placement(scenario["placement"])["placement_status"] == (
            "TERMINATED_NO_REMEDY"
        )

    def test_10_a_second_filing_supersedes_the_denied_one(self):
        """DENIED is not terminal for the household's right to re-file.

        PRD §3.8: "Re-filing after a refusal is expressly allowed and
        **supersedes** it: an existing `DENIED` claim on the same placement moves
        `DENIED → SUPERSEDED` with its `version` incremented."

        PRD §3.8: "The new claim is created with `status` `SUBMITTED`,
        `info_request_round` 0, and `elapsed_days`, `unused_days`,
        `gross_refund_cents`, `retained_admin_fee_cents`, `net_refund_cents` and
        `decision_note` all null; `Placement.version` is incremented."

        Design: Corner/state_machines/refiling_after_a_denial_supersedes_the_denied_claim
        """
        scenario = setup_claim_under_review("REPLACEMENT")
        denied = review_claim(scenario["claim"], "DENY")
        assert denied["status"] == "DENIED"

        refiled = file_claim(
            scenario["placement"],
            scenario["client_headers"],
            "REPLACEMENT",
            scenario["separation_date"],
        )
        assert refiled["status"] == "SUBMITTED"
        assert refiled["info_request_round"] == 0

        assert read_claim(denied)["status"] == "SUPERSEDED"
        rows, meta = validate_paginated(
            api_client.list_placement_replacement_claims(
                scenario["placement"]["id"], PRINCIPAL
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {denied["id"], refiled["id"]}

    def test_11_a_submitted_claim_cannot_be_decided(self):
        """The decision edges leave UNDER_REVIEW only, so the placement is untouched.

        PRD §3.8: "Every one of the three deciding actions —
        `APPROVE_REPLACEMENT`, `APPROVE_REFUND` and `DENY` — requires the claim to
        be `UNDER_REVIEW`, and a claim in `SUBMITTED` or `INFO_REQUESTED` is refused
        with `ERR_CLAIM_NOT_UNDER_REVIEW` (HTTP 409) while a claim already in
        `APPROVED_REPLACEMENT`, `APPROVED_REFUND`, `DENIED` or `SUPERSEDED` is
        refused with `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/approving_a_claim_that_is_still_submitted_is_refused
        """
        scenario = setup_terminated_placement()
        claim = file_claim(
            scenario["placement"],
            scenario["client_headers"],
            "REPLACEMENT",
            scenario["separation_date"],
        )
        assert claim["status"] == "SUBMITTED"

        validate_error(
            api_client.review_replacement_claim(
                claim["id"], review_claim_payload("APPROVE_REPLACEMENT"), PRINCIPAL
            ),
            "ERR_CLAIM_NOT_UNDER_REVIEW",
            409,
        )

        assert read_claim(claim)["status"] == "SUBMITTED"
        assert read_placement(scenario["placement"])["placement_status"] == (
            "TERMINATED_NO_REMEDY"
        )


class TestPayrollHandoffMachine:
    def test_12_a_second_attestation_cannot_restamp_the_handoff(self):
        """ATTESTED is terminal even though caller and payload are both valid.

        PRD §3.7: "Attestation moves the handoff `PREPARED → ATTESTED`, stamps
        `attested_by_name` and `attested_at` from the logical clock, increments
        `PayrollHandoff.version`, and is the single act that unblocks the
        `START_DATE` milestone for invoicing."

        PRD §3.7: "The handoff must be `PREPARED`, or the request is refused with
        `ERR_ENTITY_TERMINAL`, and its `ein_status` must be exactly `ISSUED`, or it
        is refused with `ERR_EIN_NOT_ISSUED` (HTTP 409)."

        Design: Corner/state_machines/attesting_a_payroll_handoff_twice_hits_the_terminal_lock
        """
        scenario = setup_active_placement()
        handoff = setup_attested_handoff(scenario)
        assert handoff["status"] == "ATTESTED"
        assert handoff["attested_by_name"] == BASE_SCENARIO["SIGNATORY_NAME"]
        assert handoff["attested_at"].startswith("2026-09-01T00:00:00")

        validate_error(
            api_client.attest_payroll_handoff(
                handoff["id"],
                attest_handoff_payload(attested_by_name="R. Fairholme"),
                scenario["client_headers"],
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        after = read_handoff(handoff)
        assert after["status"] == "ATTESTED"
        assert after["attested_by_name"] == BASE_SCENARIO["SIGNATORY_NAME"]
        assert after["attested_at"] == handoff["attested_at"]


class TestEnforcementMachine:
    def test_13_an_alleged_case_cannot_be_resolved(self):
        """The resolver differs from the opener, isolating the state guard.

        PRD §3.9: "The case must be `INVESTIGATING`, and any other non-terminal
        state is refused with `ERR_CASE_NOT_INVESTIGATING` (HTTP 409)."

        PRD §3.9: "The case is created with `status` `ALLEGED`,
        `prior_substantiated_count` 0, null `penalty_cents`,
        `settlement_amount_cents`, `investigation_opened_at`, `substantiated_at`,
        `resolved_by_user_id` and `findings_note`, and `opened_by_user_id` stamped
        from `X-User-ID`."

        Design: Corner/state_machines/resolving_a_case_before_investigating_it_is_refused
        """
        scenario = setup_active_placement()
        set_clock(f"{DISCOVERED_ON}T00:00:00Z")
        case = file_enforcement_case(
            scenario["client"],
            scenario["candidate"],
            DISCOVERED_ON,
            source_placement=scenario["placement"],
        )
        assert case["status"] == "ALLEGED"
        assert case["opened_by_user_id"] == CASE_OPENER["X-User-ID"]

        validate_error(
            api_client.resolve_non_solicitation_case(
                case["id"], resolve_case_payload("SUBSTANTIATE"), CASE_RESOLVER
            ),
            "ERR_CASE_NOT_INVESTIGATING",
            409,
        )

        after = read_case(case)
        assert after["status"] == "ALLEGED"
        assert after["penalty_cents"] is None
        assert after["substantiated_at"] is None
        assert read_client(scenario["client"])["status"] == "ONBOARDED"

    def test_14_a_dismissed_case_cannot_be_settled(self):
        """Dismissal is terminal, so no PENALTY_SETTLED row may be posted.

        PRD §3.9: "`UNSUBSTANTIATE` is the quiet branch: the case moves
        `INVESTIGATING → UNSUBSTANTIATED`, `resolved_by_user_id` and
        `findings_note` are stamped, `penalty_cents` stays null, and no ledger row
        is appended and no household state changes at all."

        PRD §3.9: "The case must be `SUBSTANTIATED`, and any other non-terminal
        state is refused with `ERR_INVALID_STATE_TRANSITION` while
        `UNSUBSTANTIATED` or `SETTLED` is refused with `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/an_unsubstantiated_case_is_locked_against_settlement
        """
        scenario = setup_investigating_case(DISCOVERED_ON)
        dismissed = resolve_case(scenario["case"], "UNSUBSTANTIATE")
        assert dismissed["status"] == "UNSUBSTANTIATED"
        assert dismissed["penalty_cents"] is None

        validate_error(
            api_client.settle_non_solicitation_case(
                dismissed["id"], settle_case_payload(1), BILLING
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        after = read_case(dismissed)
        assert after["status"] == "UNSUBSTANTIATED"
        assert after["settlement_amount_cents"] is None
        _, meta = validate_paginated(
            api_client.list_ledger_entries(scenario["client"]["id"], BILLING)
        )
        assert meta["total_count"] == 0

    def test_15_settling_the_last_substantiated_case_readmits_the_household(self):
        """The household lifecycle closes its cycle back to ONBOARDED.

        PRD §3.9: "Settlement moves the case `SUBSTANTIATED → SETTLED`, stamps
        `settlement_amount_cents`, appends a `LedgerEntry` of `entry_type`
        `PENALTY_SETTLED` with `signed_amount_cents` equal to the negative of
        `settlement_amount_cents`, recomputes the household's
        `outstanding_balance_cents`, and moves the household `SUSPENDED →
        ONBOARDED` — but only once no other case against that household remains in
        `SUBSTANTIATED`."

        PRD §3.9: "Hop two appends a `LedgerEntry` of `entry_type`
        `PENALTY_ASSESSED` with `signed_amount_cents` equal to positive
        `penalty_cents` and `related_ref_type` `NON_SOLICITATION_CASE`."

        Design: Corner/state_machines/settling_the_only_substantiated_case_reinstates_the_household
        """
        scenario = setup_substantiated_case(DISCOVERED_ON)
        assert scenario["case"]["status"] == "SUBSTANTIATED"
        assert scenario["case"]["penalty_cents"] == PENALTY_CENTS
        assert scenario["client"]["status"] == "SUSPENDED"

        data = settle_case(scenario["case"], PENALTY_CENTS)
        assert data["status"] == "SETTLED"
        assert data["settlement_amount_cents"] == PENALTY_CENTS

        client = read_client(scenario["client"])
        assert client["status"] == "ONBOARDED"
        assert client["outstanding_balance_cents"] == 0

        entries = read_ledger(scenario["client"])
        assert [entry["entry_type"] for entry in entries] == [
            "PENALTY_ASSESSED",
            "PENALTY_SETTLED",
        ]
        assert [entry["signed_amount_cents"] for entry in entries] == [
            PENALTY_CENTS,
            -PENALTY_CENTS,
        ]
        assert entries[-1]["balance_after_cents"] == 0
