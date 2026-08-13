"""Appeal ladder: levels, windows, outcomes, and the recovery ledger (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_case_money_ledger,
    create_appeal,
    create_appeal_payload,
    create_record_outcome_payload,
    file_appeal,
    get_case,
    get_claim,
    make_finance_director_headers,
    make_recovery_manager_headers,
    record_appeal_outcome,
    set_clock,
    setup_case_at_mediation,
    setup_case_under_review,
    setup_case_with_filed_appeal,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    withdraw_appeal,
)
from test_helpers.fixtures import RM


class TestAppealLevelAndWindow:
    def test_appeal_level_mismatch_on_skip(self, api):
        """PRD §3.7: "The requested `level` must equal the case's current
        `escalation_level` plus one — progression — or equal the current
        `escalation_level` when the most recent appeal at that same level is
        `WITHDRAWN`, which is the only refile path; any other combination is
        `ERR_APPEAL_LEVEL_MISMATCH`."

        Design: Corner/errors/err_appeal_level_mismatch_on_skip
        """
        ctx = setup_case_under_review(
            paid_amount_cents=100000, claim_overrides={"claim_number": "CL-LM1"}
        )
        case = ctx["case"]
        assert case["escalation_level"] == 0
        resp = api.create_appeal(
            create_appeal_payload(case["id"], 2), make_recovery_manager_headers("rm-1")
        )
        # PRD §3.7 names two adjacent guards for this request without pinning
        # which fires on a level-skip from UNDER_REVIEW: the from-state guard
        # ("valid from-state for the requested level" -> INVALID_STATE) and
        # the level guard ("any other combination" -> LEVEL_MISMATCH).
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_APPEAL_LEVEL_MISMATCH.value,
                ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            ],
        )
        case_after = get_case(case["id"])
        assert case_after["status"] == "UNDER_REVIEW"
        assert case_after["escalation_level"] == 0

    def test_appeal_already_open_second_appeal(self, api):
        """PRD §3.7: "The case may not already hold an appeal in `DRAFT` or
        `FILED` (`ERR_APPEAL_ALREADY_OPEN`)."

        Design: Corner/errors/err_appeal_already_open_second_appeal
        """
        ctx = setup_case_under_review(
            paid_amount_cents=100000, claim_overrides={"claim_number": "CL-AO2"}
        )
        appeal = create_appeal(ctx["case"]["id"], 1)
        resp = api.create_appeal(
            create_appeal_payload(ctx["case"]["id"], 2),
            make_recovery_manager_headers("rm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_OPEN.value)
        data, meta = validate_paginated(
            api.list_appeals(RM, params={"case_id": ctx["case"]["id"]})
        )
        assert len(data) == 1
        assert data[0]["id"] == appeal["id"]
        assert data[0]["status"] == "DRAFT"

    def test_appeal_window_closed_after_deadline(self, api):
        """PRD §3.7: "a level-1 appeal must be created on or before the case's
        `appeal_filing_deadline`", the deadline being the "computed
        `appeal_filing_deadline` equal to `queued_date` plus the payer's
        `appeal_deadline_days`" (§3.7). Violations "are
        `ERR_APPEAL_WINDOW_CLOSED`".

        Design: Corner/errors/err_appeal_window_closed_after_deadline
        """
        ctx = setup_case_under_review(
            paid_amount_cents=100000, claim_overrides={"claim_number": "CL-WC1"}
        )
        # Queued 2026-08-01 with appeal_deadline_days 45 -> deadline 2026-09-15.
        set_clock("2026-09-16T00:00:00Z")
        resp = api.create_appeal(
            create_appeal_payload(ctx["case"]["id"], 1),
            make_recovery_manager_headers("rm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)
        assert get_case(ctx["case"]["id"])["status"] == "UNDER_REVIEW"


class TestAppealFiling:
    def test_appeal_file_sets_response_due_date(self, api):
        """PRD §3.7: "Filing an appeal — available to either recovery role
        while the appeal is `DRAFT` — moves it to `FILED`, stamps
        `filed_date` with today, and starts the payer's response clock:
        `response_due_date` is the filed date plus 30 calendar days at levels
        1 and 2, 45 days at level 3, and 60 days at level 4." and "its
        `channel` derived from the level: level 1 is an `INTERNAL_REVIEW`".

        Design: Corner/state_machines/sm_appeal_file_sets_response_due_date
        """
        ctx = setup_case_under_review(
            paid_amount_cents=100000, claim_overrides={"claim_number": "CL-RD1"}
        )
        appeal = create_appeal(ctx["case"]["id"], 1)
        assert appeal["channel"] == "INTERNAL_REVIEW"
        filed = file_appeal(appeal["id"])
        assert filed["status"] == "FILED"
        assert filed["filed_date"] == "2026-08-01"
        assert filed["response_due_date"] == "2026-08-31"

    def test_filed_appeal_refiling_rejected(self, api):
        """PRD §3.7: "Filing an appeal — available to either recovery role
        while the appeal is `DRAFT` — moves it to `FILED`"; a `FILED` appeal
        is not in the from-state, so the replay is rejected per PRD §2.8 rung
        6 ("State violations not covered by a more specific identifier are
        rejected as `ERR_INVALID_STATE_TRANSITION`").

        Design: Corner/state_machines/sm_filed_appeal_refiling_rejected
        """
        ctx = setup_case_with_filed_appeal(
            level=1, paid_amount_cents=100000,
            claim_overrides={"claim_number": "CL-FI1"},
        )
        appeal = ctx["appeal"]
        assert appeal["filed_date"] == "2026-08-01"
        resp = api.file_appeal(appeal["id"], make_recovery_manager_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        after = validate_success(api.get_appeal(appeal["id"], RM))
        assert after["status"] == "FILED"
        assert after["filed_date"] == "2026-08-01"


class TestAppealOutcomes:
    def test_recovery_amount_invalid_at_outstanding(self, api):
        """PRD §3.7: "`PARTIAL_PAYMENT` takes the caller's
        `recovered_amount_cents`, which must be strictly greater than zero and
        strictly less than the case's `current_outstanding_cents`
        (`ERR_RECOVERY_AMOUNT_INVALID`)".

        Design: Corner/errors/err_recovery_amount_invalid_at_outstanding
        """
        ctx = setup_case_with_filed_appeal(
            level=1, paid_amount_cents=150000,
            claim_overrides={"claim_number": "CL-RI1"},
        )
        case = get_case(ctx["case"]["id"])
        assert case["current_outstanding_cents"] == 50000
        resp = api.record_appeal_outcome(
            ctx["appeal"]["id"],
            create_record_outcome_payload(
                "PARTIAL_PAYMENT", recovered_amount_cents=50000
            ),
            make_recovery_manager_headers("rm-2"),
        )
        validate_error(resp, ApiErrorId.ERR_RECOVERY_AMOUNT_INVALID.value)
        appeal_after = validate_success(api.get_appeal(ctx["appeal"]["id"], RM))
        assert appeal_after["status"] == "FILED"
        data, _meta = validate_paginated(
            api.list_remittances(RM, params={"appeal_id": ctx["appeal"]["id"]})
        )
        assert data == []

    def test_escalation_min_not_met_on_arbitration(self, api):
        """PRD §3.7: "Arbitration adds a size gate: the case's
        `current_outstanding_cents` must be at least 100000 cents — one
        thousand dollars — else `ERR_ESCALATION_MIN_NOT_MET`."

        Design: Corner/errors/err_escalation_min_not_met_on_arbitration
        """
        ctx = setup_case_at_mediation(
            claim_overrides={"claim_number": "CL-AM1"}
        )
        case = ctx["case"]
        assert case["status"] == "MEDIATION"
        assert case["escalation_level"] == 3
        assert case["current_outstanding_cents"] == 50000
        resp = api.create_appeal(
            create_appeal_payload(case["id"], 4), make_recovery_manager_headers("rm-1")
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATION_MIN_NOT_MET.value)
        case_after = get_case(case["id"])
        assert case_after["status"] == "MEDIATION"
        assert case_after["escalation_level"] == 3


class TestLevel2GateOnLevel1Outcome:
    """Escalation evidence: level n>1 needs a qualifying prior outcome."""

    def _setup_withdrawn_level1(self, api):
        """Case APPEAL_L1 whose only level-1 appeal was withdrawn in DRAFT."""
        ctx = setup_case_under_review(
            paid_amount_cents=100000, claim_overrides={"claim_number": "CL-XA1"}
        )
        appeal1 = create_appeal(ctx["case"]["id"], 1)
        withdraw_appeal(appeal1["id"])
        ctx["appeal1"] = appeal1
        return ctx

    def test_level2_blocked_without_qualifying_level1_outcome(self, api):
        """PRD §3.7: "Finally, the evidence rule: escalating to any level
        above 1 requires the case's most recent non-`WITHDRAWN` appeal at the
        prior level to have closed with outcome `DENIED`, `EXPIRED`, or
        `PARTIAL_PAYMENT`, else `ERR_ESCALATION_BLOCKED`." and "Withdrawing an
        appeal — from `DRAFT` or `FILED`, by either recovery role — moves it
        to terminal `WITHDRAWN`, leaves the case at its current level, and
        preserves the option to file a fresh appeal at that same level under
        the refile rule above."

        Design: Difficulty/cross_entity_state_dependency/appeal_level2_gated_on_level1_outcome
        """
        ctx = self._setup_withdrawn_level1(api)
        case_id = ctx["case"]["id"]
        # Level 2 == escalation_level + 1 passes the level check, but no
        # non-WITHDRAWN level-1 appeal has an outcome: evidence blocks it.
        resp = api.create_appeal(
            create_appeal_payload(case_id, 2), make_recovery_manager_headers("rm-1")
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATION_BLOCKED.value)
        # The same-level refile path stays open after the withdrawal.
        appeal2 = create_appeal(case_id, 1)
        assert appeal2["level"] == 1
        assert appeal2["status"] == "DRAFT"

    def test_level2_allowed_after_level1_denied(self, api):
        """PRD §3.7: "The new appeal is born `DRAFT` with outcome `PENDING`
        and `recovered_amount_cents` zero, its `channel` derived from the
        level: level 1 is an `INTERNAL_REVIEW`, level 2 a `FORMAL_APPEAL`" and
        "Creation is also what escalates the case: a level-1 appeal moves the
        case from `UNDER_REVIEW` to `APPEAL_L1`, and subsequent levels move it
        from `APPEAL_L1` to `APPEAL_L2`".

        Design: Difficulty/cross_entity_state_dependency/appeal_level2_gated_on_level1_outcome
        """
        ctx = self._setup_withdrawn_level1(api)
        case_id = ctx["case"]["id"]
        # Refile level 1, file it, record DENIED -> qualifying outcome.
        appeal2 = create_appeal(case_id, 1)
        file_appeal(appeal2["id"])
        record_appeal_outcome(appeal2["id"], "DENIED")
        # Now level-2 creation succeeds and escalates the case.
        appeal3 = validate_success(
            api.create_appeal(
                create_appeal_payload(case_id, 2),
                make_recovery_manager_headers("rm-1"),
            ),
            expected_status=201,
        )
        assert appeal3["level"] == 2
        assert appeal3["channel"] == "FORMAL_APPEAL"
        case_after = get_case(case_id)
        assert case_after["status"] == "APPEAL_L2"
        assert case_after["escalation_level"] == 2


class TestAppealRecoveryLedger:
    """Case money ledger: original == outstanding + recovered + write_off."""

    def _setup_partial_payment(self, api):
        ctx = setup_case_with_filed_appeal(
            level=1, paid_amount_cents=100000,
            claim_overrides={"claim_number": "CL-CI1"},
        )
        return ctx

    def test_partial_payment_preserves_case_money_ledger(self, api):
        """PRD §3.7: "The case's money ledger obeys one invariant in every
        status: `original_variance_cents` always equals the sum of
        `current_outstanding_cents`, `recovered_to_date_cents`, and
        `write_off_amount_cents`, with the outstanding figure computed as the
        original variance minus recoveries minus write-offs." and
        "`PARTIAL_PAYMENT` ... likewise creates an `APPEAL_RECOVERY`
        remittance for the recovered amount, recomputes the claim, reduces the
        case's outstanding, and leaves the case at its current level for
        further work."

        Design: Difficulty/compensating_invariant/appeal_recovery_then_reversal_preserves_case_money_ledger
        """
        ctx = self._setup_partial_payment(api)
        case_id = ctx["case"]["id"]
        appeal = record_appeal_outcome(
            ctx["appeal"]["id"], "PARTIAL_PAYMENT", recovered_amount_cents=30000
        )
        assert appeal["recovered_amount_cents"] == 30000
        case_after = get_case(case_id)
        assert case_after["current_outstanding_cents"] == 70000
        assert case_after["recovered_to_date_cents"] == 30000
        assert case_after["write_off_amount_cents"] == 0
        assert_case_money_ledger(case_after)  # 100000 == 70000 + 30000 + 0
        assert case_after["status"] == "APPEAL_L1"
        # The recovery remittance exists, stamped with source and appeal id.
        data, _meta = validate_paginated(
            api.list_remittances(RM, params={"appeal_id": ctx["appeal"]["id"]})
        )
        assert len(data) == 1
        assert data[0]["source"] == "APPEAL_RECOVERY"
        assert data[0]["paid_amount_cents"] == 30000
        ctx["recovery_remittance"] = data[0]
        return ctx

    def test_reversal_of_recovery_restores_case_money_ledger(self, api):
        """PRD §3.7: a case tracks "`recovered_to_date_cents` — the sum of
        `recovered_amount_cents` over its appeals whose outcome is
        `PAID_IN_FULL` or `PARTIAL_PAYMENT`, minus the paid amount of every
        `REVERSED` appeal-recovery remittance linked to those appeals, since
        a reversal cancels its recovery". PRD §3.6: "a remittance born of an
        appeal recovery may be reversed only while the linked appeal's case is
        still non-terminal, else `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/compensating_invariant/appeal_recovery_then_reversal_preserves_case_money_ledger
        """
        ctx = self._setup_partial_payment(api)
        case_id = ctx["case"]["id"]
        record_appeal_outcome(
            ctx["appeal"]["id"], "PARTIAL_PAYMENT", recovered_amount_cents=30000
        )
        data, _meta = validate_paginated(
            api.list_remittances(RM, params={"appeal_id": ctx["appeal"]["id"]})
        )
        recovery_remittance = data[0]
        reversed_remittance = validate_success(
            api.reverse_remittance(
                recovery_remittance["id"], make_finance_director_headers("fd-9")
            )
        )
        assert reversed_remittance["status"] == "REVERSED"

        case_after = get_case(case_id)
        assert case_after["current_outstanding_cents"] == 100000
        assert case_after["recovered_to_date_cents"] == 0
        assert case_after["write_off_amount_cents"] == 0
        assert_case_money_ledger(case_after)  # 100000 == 100000 + 0 + 0
        assert case_after["status"] == "APPEAL_L1"
        claim_after = get_claim(ctx["claim"]["id"])
        assert claim_after["paid_amount_cents"] == 100000
        assert claim_after["variance_cents"] == 100000
