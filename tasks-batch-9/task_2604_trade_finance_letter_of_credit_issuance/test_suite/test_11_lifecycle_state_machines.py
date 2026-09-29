"""Declared lifecycle edges of every instrument, walked one transition at a time.

Initial states, the single legal from-state of each transition, the full side-effect set of
the densest transition, terminal-state lockdown, non-idempotent conclusion, the facility's
cyclic suspend/reinstate loop, its guarded close, the amendment acceptance ledger sync, the
conditional sweep cascade and the confirmation dimension's retry cycle.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    api_client,
    approved_credit,
    assert_facility_ledger,
    assert_instant_with_milliseconds,
    assert_issuance_charges,
    assert_screening_outcome,
    assert_sweep_counters,
    cancel_credit,
    change_facility_status,
    consent_to_amendment,
    create_bank,
    credit_officer_headers,
    discrepant_presentation,
    document_examiner_headers,
    draft_amendment,
    draft_credit,
    factories,
    issue_amendment,
    issue_credit,
    issued_credit,
    list_amendment_rows,
    list_credit_allocation_rows,
    list_credit_screening_rows,
    make_correspondent_bank_headers,
    open_presentation,
    request_confirmation,
    respond_to_confirmation,
    run_sweep,
    set_clock,
    setup_parties,
    submit_credit_for_approval,
    trade_finance_officer_headers,
    TRADE_FINANCE_OFFICER_1,
)

CONSENT_REFERENCE = "BEN-CONSENT-2026-0044"


def _read_bank(bank_id):
    return validate_success(api_client.get_bank(bank_id, credit_officer_headers()))


def _requirement_rows(credit_id):
    return validate_paginated(
        api_client.list_documentary_requirements(credit_id, trade_finance_officer_headers())
    )


class TestInitialStates:
    """A fresh credit, a fresh amendment and a fresh presentation file."""

    def test_a_new_credit_rests_in_draft_with_the_declared_fields_unset(self, clock):
        """DRAFT / UNCONFIRMED, `amendment_seq` 0, and four fields deliberately unset.

        PRD 3.2: "Its `amendment_seq` starts at 0, its `drafted_by_user_id` records the
        acting operator, and `issued_by_user_id`, `issue_date`, `confirming_bank_id` and
        `cancelled_reason` all start unset."

        PRD 3.2: "The new draft is stamped with `status` `DRAFT` and `confirmation_status`
        `UNCONFIRMED` — the two lifecycle dimensions a credit carries, which evolve
        independently of each other for the whole life of the instrument."

        Design: Corner/state_machines/credit_starts_in_draft_and_amendment_starts_in_draft
        """
        parties = setup_parties(facility={"limit_cents": 50000000})

        ctx = draft_credit(parties)

        credit = ctx.credit
        assert credit["status"] == "DRAFT"
        assert credit["confirmation_status"] == "UNCONFIRMED"
        assert credit["amendment_seq"] == 0
        assert credit["drafted_by_user_id"] == TRADE_FINANCE_OFFICER_1
        assert credit["issued_by_user_id"] is None
        assert credit["issue_date"] is None
        assert credit["confirming_bank_id"] is None
        assert credit["cancelled_reason"] is None

    def test_a_new_draft_leaves_the_facility_ledger_completely_untouched(self, clock):
        """The provisional estimate is written on the credit and nowhere else.

        PRD 3.2: "And a **provisional exposure estimate** is written to
        `provisional_allocation_cents`, which is important to understand for what it is not:
        it never debits the facility, no allocation row is created, and the facility's
        `allocated_cents` is untouched."

        Design: Corner/state_machines/credit_starts_in_draft_and_amendment_starts_in_draft
        """
        parties = setup_parties(facility={"limit_cents": 50000000})

        ctx = draft_credit(parties)

        assert ctx.credit["provisional_allocation_cents"] == 10000000
        assert ctx.credit["max_drawable_cents"] == 10000000
        assert ctx.credit["presentation_deadline_date"] == "2026-11-21"
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )
        assert list_credit_allocation_rows(ctx.credit_id) == []

    def test_a_new_amendment_rests_in_draft_with_no_window_yet(self, clock):
        """`seq` is one plus the existing rows and the consent window is still unset.

        PRD 3.5: "A successful draft sets `status` to `DRAFT`, records `drafted_by_user_id`
        as the acting `X-User-ID`, and assigns `seq` as one plus the number of Amendment
        rows that already exist for this credit."

        PRD 3.5: "On both branches, and before the branch is taken, the amendment acquires
        its window: `consent_window_start` is set to the clock date, `consent_deadline_date`
        to the clock date plus ten days, and `window_end_effective` to
        `consent_deadline_date`."

        Design: Corner/state_machines/credit_starts_in_draft_and_amendment_starts_in_draft
        """
        ctx = issued_credit(setup_parties(facility={"limit_cents": 50000000}), None)

        amendment = draft_amendment(ctx, {"amount_cents": 8000000})

        assert amendment["status"] == "DRAFT"
        assert amendment["seq"] == 1
        assert amendment["drafted_by_user_id"] == TRADE_FINANCE_OFFICER_1
        assert amendment["consent_window_start"] is None
        assert amendment["consent_deadline_date"] is None
        assert amendment["window_end_effective"] is None
        assert amendment["resolved_at"] is None
        assert amendment["version"] == 1

    def test_a_new_presentation_file_rests_in_received_with_no_deadline_yet(self, clock):
        """The examination clock does not start when the file is opened.

        PRD 3.6: "The new file takes `examination_status` `RECEIVED`, `settlement_status`
        `UNSETTLED`, `received_at` at the clock instant, `received_date` as the clock date,
        `document_count` 0 and `drawn_amount_cents` 0."

        PRD 3.6: "`examination_deadline` deliberately stays unset until submission: the five
        banking days run from the day the documents are actually presented as a complete
        set, not from the day the file was opened."

        Design: Corner/state_machines/credit_starts_in_draft_and_amendment_starts_in_draft
        """
        ctx = issued_credit(setup_parties(facility={"limit_cents": 50000000}), None)
        set_clock("2026-09-14T09:00:00Z")

        pctx = open_presentation(ctx)

        row = pctx.presentation
        assert row["examination_status"] == "RECEIVED"
        assert row["settlement_status"] == "UNSETTLED"
        assert row["received_date"] == "2026-09-14"
        assert_instant_with_milliseconds(row["received_at"], "received_at")
        assert row["received_at"] == "2026-09-14T09:00:00.000Z"
        assert row["document_count"] == 0
        assert row["drawn_amount_cents"] == 0
        assert row["examination_deadline"] is None


class TestSubmitForApprovalHasExactlyOneLegalFromState:
    """`DRAFT` is the only state submission and requirement drafting run from."""

    def _pending_credit(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        ctx = draft_credit(parties)
        submit_credit_for_approval(ctx.credit_id)
        return ctx

    def test_a_second_submit_for_approval_reports_credit_not_draft(self, clock):
        """From `PENDING_CREDIT_APPROVAL` the submit edge simply does not exist.

        PRD 3.2: "Sending the draft to the credit officer moves it `DRAFT →
        PENDING_CREDIT_APPROVAL`, optionally accompanied by a `submission_note`, and
        re-derives `provisional_allocation_cents` by the same provisional rule against the
        facility's collateral posture as it stands at submission — a collateral posting made
        between drafting and submission therefore shows up here."

        Design: Corner/state_machines/second_submit_for_approval_rejected_because_credit_is_not_draft
        """
        ctx = self._pending_credit()
        assert ctx.refresh()["status"] == "PENDING_CREDIT_APPROVAL"

        response = api_client.submit_credit_for_approval(
            ctx.credit_id,
            factories.submit_for_approval_payload(),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_CREDIT_NOT_DRAFT", 409)
        assert ctx.refresh()["status"] == "PENDING_CREDIT_APPROVAL"

    def test_drafting_a_further_requirement_from_the_same_state_reports_the_same_error(
        self, clock
    ):
        """Requirement drafting shares the DRAFT-only gate, and no third row appears.

        PRD 3.2: "**Documentary requirements** are drafted into the credit one at a time,
        and only while the credit is still `DRAFT` — an attempt on a credit in any other
        status is refused with `ERR_CREDIT_NOT_DRAFT` (409)."

        Design: Corner/state_machines/second_submit_for_approval_rejected_because_credit_is_not_draft
        """
        ctx = self._pending_credit()

        response = api_client.create_documentary_requirement(
            ctx.credit_id,
            factories.insurance_requirement_payload(),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_CREDIT_NOT_DRAFT", 409)
        rows, meta = _requirement_rows(ctx.credit_id)
        assert meta["total_count"] == 2
        assert len(rows) == 2
        assert {row["doc_type"] for row in rows} == {"COMMERCIAL_INVOICE", "BILL_OF_LADING"}
        assert ctx.refresh()["status"] == "PENDING_CREDIT_APPROVAL"


class TestIssueTransitionAppliesEveryDeclaredSideEffect:
    """One `APPROVED → ISSUED` call, and the whole side-effect set it owes."""

    def _approved(self):
        return approved_credit(setup_parties(facility={"limit_cents": 50000000}), None)

    def test_one_issue_call_writes_the_whole_pricing_chain_and_both_windows(self, clock):
        """Status, stamps, exposure, commission tier, deadline and confirmation window.

        PRD 3.3: "Third, `base_commission_cents` is the larger of a 25,000-cent floor and
        the result of multiplying `gross_exposure_cents` by `commission_bps_applied` and by
        the quarter count, dividing by 10,000 and rounding half up."

        PRD 3.3: "The confirmation window is opened with `confirmation_window_start` equal to
        `issue_date`, inclusive, and `confirmation_window_end` equal to `expiry_date`
        advanced by `presentation_period_days` days — and that end date is **exclusive**,
        which is a different convention from the presentation deadline on purpose."

        Design: Corner/state_machines/issue_transition_applies_every_declared_side_effect
        """
        ctx = self._approved()

        response = api_client.issue_credit(
            ctx.credit_id, factories.issue_payload(), trade_finance_officer_headers()
        )

        validate_success(response, 200)
        credit = ctx.refresh()
        assert credit["status"] == "ISSUED"
        assert credit["issue_date"] == "2026-08-10"
        assert credit["issued_by_user_id"] == TRADE_FINANCE_OFFICER_1
        assert_issuance_charges(
            credit,
            max_drawable_cents=10000000,
            gross_exposure_cents=10000000,
            committed_allocation_cents=10000000,
            commission_bps_applied=10,
            base_commission_cents=25000,
            confirmation_charge_cents=0,
            total_charge_cents=25000,
            chargeable_utilisation_cents=10025000,
        )
        assert credit["presentation_deadline_date"] == "2026-11-21"
        assert credit["confirmation_window_start"] == "2026-08-10"
        assert credit["confirmation_window_end"] == "2026-12-21"
        assert credit["available_cents"] == 10000000

    def test_the_same_call_raises_the_allocation_the_screening_and_the_facility_ledger(
        self, clock
    ):
        """Hop one's row, the parties screening and hop two's re-driven facility ledger.

        PRD 3.3: "**Hop one** creates a facility allocation row: its `facility_id` and
        `credit_id` name the facility and the credit, its `basis` is `COMMITTED_ISSUANCE`,
        its `status` is `OPEN`, its `allocated_cents` is the credit's
        `committed_allocation_cents` and its `charge_cents` is the credit's
        `total_charge_cents`; its `released_cents` starts at 0 and its `released_at` is
        unset."

        PRD 3.3: "A screening of the credit's parties is created as part of issuance, with
        `scope` `CREDIT_PARTIES`, `credit_id` pointing at this credit, `presentation_id`
        unset, and `screened_by_user_id` recorded as the literal value `system` rather than
        any operator."

        Design: Corner/state_machines/issue_transition_applies_every_declared_side_effect
        """
        ctx = self._approved()

        issue_credit(ctx.credit_id)

        allocations = list_credit_allocation_rows(ctx.credit_id)
        assert len(allocations) == 1
        assert allocations[0]["status"] == "OPEN"
        assert allocations[0]["basis"] == "COMMITTED_ISSUANCE"
        assert allocations[0]["allocated_cents"] == 10000000
        assert allocations[0]["charge_cents"] == 25000
        assert allocations[0]["released_cents"] == 0
        assert allocations[0]["released_at"] is None

        screenings = list_credit_screening_rows(ctx.credit_id)
        assert len(screenings) == 1
        assert_screening_outcome(
            screenings[0],
            result="CLEAR",
            risk_score=0,
            country_hits=0,
            dual_use_hits=0,
            keyword_hits=0,
            transit_hits=0,
            scope="CREDIT_PARTIES",
            screened_by_user_id="system",
        )
        assert screenings[0]["presentation_id"] is None

        assert_facility_ledger(
            ctx.refresh_facility(),
            allocated_cents=10025000,
            available_cents=39975000,
            restrict_threshold_cents=47500000,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )


class TestIncotermDocumentPairingGuardsSubmission:
    """A `CIF` credit owes an insurance certificate before it may leave `DRAFT`."""

    def _cif_draft(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        return parties, draft_credit(parties, None, incoterm="CIF")

    def _attempt_submit(self, credit_id):
        return api_client.submit_credit_for_approval(
            credit_id,
            factories.submit_for_approval_payload(),
            trade_finance_officer_headers(),
        )

    def test_a_cif_credit_carrying_only_invoice_and_bill_of_lading_is_refused(self, clock):
        """The delivery term decides which documents the paperwork must demand.

        PRD 3.2: "On top of that, a credit whose `incoterm` is `CIF` or `CIP` must carry a
        mandatory `INSURANCE_CERTIFICATE` requirement, because under those terms the seller
        insures the goods; conversely, a credit whose `incoterm` is `FOB`, `FCA` or `EXW`
        must **not** carry an `INSURANCE_CERTIFICATE` requirement, because under those terms
        it is not the seller's insurance to produce."

        Design: Corner/state_machines/submit_for_approval_rejected_when_cif_credit_omits_insurance_requirement
        """
        parties, ctx = self._cif_draft()

        response = self._attempt_submit(ctx.credit_id)

        validate_error(response, "ERR_INCOTERM_DOCUMENT_MISMATCH", 422)
        assert ctx.refresh()["status"] == "DRAFT"
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=0)

    def test_adding_the_insurance_requirement_makes_the_identical_call_succeed(self, clock):
        """The same submission passes once the missing requirement is drafted in.

        PRD 3.2: "Every one of these failures reports `ERR_INCOTERM_DOCUMENT_MISMATCH`
        (422)."

        Design: Corner/state_machines/submit_for_approval_rejected_when_cif_credit_omits_insurance_requirement
        """
        parties, ctx = self._cif_draft()
        validate_error(
            self._attempt_submit(ctx.credit_id), "ERR_INCOTERM_DOCUMENT_MISMATCH", 422
        )

        added = api_client.create_documentary_requirement(
            ctx.credit_id,
            factories.insurance_requirement_payload(),
            trade_finance_officer_headers(),
        )
        validate_success(added, 201)
        submitted = validate_success(self._attempt_submit(ctx.credit_id), 200)

        assert submitted["status"] == "PENDING_CREDIT_APPROVAL"
        assert submitted["provisional_allocation_cents"] == 10000000
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=0)
        _rows, meta = _requirement_rows(ctx.credit_id)
        assert meta["total_count"] == 3


class TestCancelledCreditIsTerminalAndLocksEveryFurtherTransition:
    """`CANCELLED` admits no outgoing edge at all, whatever the verb."""

    def _cancelled(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        ctx = issued_credit(parties, None)
        cancelled = cancel_credit(
            ctx.credit_id,
            reason="Underlying contract terminated",
            beneficiary_consent_reference=CONSENT_REFERENCE,
        )
        return parties, ctx, cancelled

    def test_the_consented_cancellation_lands_on_the_terminal_state(self, clock):
        """An issued credit reaches `CANCELLED` and the facility returns to zero.

        PRD 3.3: "Cancellation is the compensating action for all of this, and it is
        available from `DRAFT`, `PENDING_CREDIT_APPROVAL`, `APPROVED`, `ON_HOLD` and
        `ISSUED`, always landing on the terminal `CANCELLED`."

        PRD 3.3: "That release is hop two's cause: the facility's `allocated_cents` falls by
        exactly `released_cents`, restoring the precise pre-issuance value, and the
        facility's `version` increments."

        Design: Corner/state_machines/cancelled_credit_is_terminal_and_every_further_transition_rejected
        """
        parties, ctx, cancelled = self._cancelled()

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_reason"] == "Underlying contract terminated"
        assert ctx.refresh()["status"] == "CANCELLED"
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )

    def test_amending_presenting_and_cancelling_again_all_report_credit_terminal(self, clock):
        """Three different verbs, one shared terminal-state error, no rows created.

        PRD 3.2: "Any transition attempted against a credit already in a terminal state is
        refused with `ERR_CREDIT_TERMINAL` (409)."

        Design: Corner/state_machines/cancelled_credit_is_terminal_and_every_further_transition_rejected
        """
        parties, ctx, cancelled = self._cancelled()

        amendment_attempt = api_client.create_amendment(
            ctx.credit_id,
            factories.amendment_payload({"amount_cents": 8000000}, cancelled["version"]),
            trade_finance_officer_headers(),
        )
        presentation_attempt = api_client.create_presentation(
            factories.presentation_payload(ctx.credit_id, parties.nominated_bank_id),
            parties.nominated_bank_headers,
        )
        second_cancel_attempt = api_client.cancel_credit(
            ctx.credit_id,
            factories.cancel_payload(beneficiary_consent_reference=CONSENT_REFERENCE),
            trade_finance_officer_headers(),
        )

        validate_error(amendment_attempt, "ERR_CREDIT_TERMINAL", 409)
        validate_error(presentation_attempt, "ERR_CREDIT_TERMINAL", 409)
        validate_error(second_cancel_attempt, "ERR_CREDIT_TERMINAL", 409)
        assert list_amendment_rows(ctx.credit_id) == []
        _rows, meta = validate_paginated(
            api_client.list_presentations(
                document_examiner_headers(), {"credit_id": ctx.credit_id}
            )
        )
        assert meta["total_count"] == 0
        assert ctx.refresh()["cancelled_reason"] == "Underlying contract terminated"


class TestConcludeExaminationIsNotIdempotent:
    """A concluded file cannot be concluded twice, and the count does not move."""

    def _discrepant_file(self):
        ctx = issued_credit(setup_parties(facility={"limit_cents": 50000000}), None)
        set_clock("2026-09-14T09:00:00Z")
        return discrepant_presentation(
            ctx, "GOODS_DESCRIPTION_MISMATCH", "MATERIAL", (2000000,)
        )

    def test_a_second_conclusion_reports_already_concluded_rather_than_not_examinable(
        self, clock
    ):
        """The specific already-concluded error, not the generic examinability error.

        PRD 3.6: "A second conclusion on an already-concluded presentation is refused with
        `ERR_PRESENTATION_ALREADY_CONCLUDED` (409)."

        Design: Corner/state_machines/second_conclude_examination_rejected_as_already_concluded
        """
        pctx = self._discrepant_file()
        assert pctx.presentation["examination_status"] == "DISCREPANT"

        response = api_client.conclude_examination(
            pctx.presentation_id,
            factories.conclude_examination_payload(),
            document_examiner_headers(),
        )

        validate_error(response, "ERR_PRESENTATION_ALREADY_CONCLUDED", 409)

    def test_the_refused_second_call_re_runs_nothing_on_the_presentation(self, clock):
        """Status, discrepancy count and the banking-day deadline are all unmoved.

        PRD 3.6: "The outcome is decided purely by the count: `discrepancy_count` equal to
        zero moves `UNDER_EXAMINATION → COMPLYING`, and a count of one or more moves
        `UNDER_EXAMINATION → DISCREPANT`."

        Design: Corner/state_machines/second_conclude_examination_rejected_as_already_concluded
        """
        pctx = self._discrepant_file()
        validate_error(
            api_client.conclude_examination(
                pctx.presentation_id,
                factories.conclude_examination_payload(),
                document_examiner_headers(),
            ),
            "ERR_PRESENTATION_ALREADY_CONCLUDED",
            409,
        )

        row = pctx.refresh()
        assert row["examination_status"] == "DISCREPANT"
        assert row["discrepancy_count"] == 1
        assert row["examination_deadline"] == "2026-09-21T23:59:59.999Z"


class TestFacilitySuspendThenReinstateCompletesTheCyclicLoop:
    """`ACTIVE → SUSPENDED → ACTIVE` returns the facility to its starting state."""

    def _approved_on_a_clean_facility(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        return parties, approved_credit(parties, None)

    def _attempt_status_change(self, facility_id, action):
        return api_client.create_facility_status_change(
            facility_id,
            factories.facility_status_change_payload(action),
            credit_officer_headers(),
        )

    def test_a_manual_suspension_records_its_own_reason_and_holds_the_sibling(self, clock):
        """`MANUAL_SUSPENSION`, not `RESTRICT_THRESHOLD_BREACH`, and issuance is barred.

        PRD 3.1: "A manual suspension takes an `ACTIVE` facility to `SUSPENDED` with
        `suspended_reason` set to `MANUAL_SUSPENSION`; note the asymmetry with the automatic
        path — `utilisation_posture` is recomputed from the exposure figures as usual but is
        **not** forced to `RESTRICTED`."

        Design: Corner/state_machines/facility_suspend_then_reinstate_completes_the_cyclic_loop
        """
        parties, ctx = self._approved_on_a_clean_facility()

        suspended = validate_success(
            self._attempt_status_change(parties.facility_id, "SUSPEND"), 200
        )

        assert_facility_ledger(
            suspended,
            allocated_cents=0,
            status="SUSPENDED",
            suspended_reason="MANUAL_SUSPENSION",
            utilisation_posture="OPEN",
        )
        assert ctx.refresh()["status"] == "ON_HOLD"
        # PRD 2.9 band four checks the addressed row's own transition first -- "the addressed
        # row is in a state from which the requested transition exists, else the specific 409
        # for that instrument (`ERR_CREDIT_NOT_DRAFT`, `ERR_CREDIT_NOT_APPROVED`, ...);
        # cross-entity state guards hold" -- and the cascade has already left this credit
        # ON_HOLD, so its own state, not the facility's, decides the refusal.
        validate_error(
            api_client.issue_credit(
                ctx.credit_id, factories.issue_payload(), trade_finance_officer_headers()
            ),
            "ERR_CREDIT_NOT_APPROVED",
            409,
        )

    def test_reinstatement_closes_the_loop_and_the_credit_can_then_be_issued(self, clock):
        """The facility and its held sibling both return to exactly where they began.

        PRD 3.1: "Reinstatement takes a `SUSPENDED` facility back to `ACTIVE`, clears
        `suspended_reason`, and returns every `ON_HOLD` credit on the facility to `APPROVED`
        in `created_at` ascending order — but it is permitted only when the suspension was
        manual."

        Design: Corner/state_machines/facility_suspend_then_reinstate_completes_the_cyclic_loop
        """
        parties, ctx = self._approved_on_a_clean_facility()
        change_facility_status(parties.facility_id, "SUSPEND")
        assert ctx.refresh()["status"] == "ON_HOLD"

        reinstated = validate_success(
            self._attempt_status_change(parties.facility_id, "REINSTATE"), 200
        )

        assert_facility_ledger(
            reinstated,
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            suspended_reason=None,
            utilisation_posture="OPEN",
        )
        assert ctx.refresh()["status"] == "APPROVED"
        validate_success(
            api_client.issue_credit(
                ctx.credit_id, factories.issue_payload(), trade_finance_officer_headers()
            ),
            200,
        )
        assert ctx.refresh()["status"] == "ISSUED"
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=10025000)


class TestFacilityCloseIsGuardedByItsChildLedgerThenFreezesThePosture:
    """`CLOSE` waits for the allocation ledger to empty, then cascades downward."""

    def _one_issued_one_approved(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        first = issued_credit(parties, None)
        second = approved_credit(parties, None)
        return parties, first, second

    def _attempt_close(self, facility_id):
        return api_client.create_facility_status_change(
            facility_id,
            factories.facility_status_change_payload("CLOSE"),
            credit_officer_headers(),
        )

    def test_close_is_refused_while_one_allocation_row_is_still_open(self, clock):
        """The child ledger vetoes the parent's terminal transition.

        PRD 3.1: "Closing takes an `ACTIVE` or `SUSPENDED` facility to the terminal `CLOSED`
        state and sets `utilisation_posture` to `FROZEN`, and it requires that no allocation
        row on the facility is still `OPEN` — equivalently that `allocated_cents` is zero —
        failing which the request is rejected with `ERR_FACILITY_HAS_OPEN_ALLOCATION` (409)."

        Design: Corner/state_machines/facility_close_rejected_while_an_allocation_is_open_then_freezes_posture
        """
        parties, first, _second = self._one_issued_one_approved()
        assert list_credit_allocation_rows(first.credit_id)[0]["status"] == "OPEN"

        response = self._attempt_close(parties.facility_id)

        validate_error(response, "ERR_FACILITY_HAS_OPEN_ALLOCATION", 409)
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=10025000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )

    def test_after_the_release_close_succeeds_and_the_frozen_posture_bars_the_sibling(
        self, clock
    ):
        """`FROZEN` is read by the issuance gate, so the approved sibling is stranded.

        PRD 3.1: "From that figure, `available_cents` is `limit_cents` minus
        `allocated_cents` and may never go negative, and `utilisation_posture` is re-derived:
        it is `FROZEN` whenever the facility's `status` is `CLOSED`; otherwise it is
        `RESTRICTED` whenever `allocated_cents` has reached or passed
        `restrict_threshold_cents`; otherwise it is `OPEN`."

        PRD 3.3: "The facility must be `ACTIVE` and its `utilisation_posture` must not be
        `FROZEN`, else `ERR_FACILITY_NOT_ACTIVE` (409)."

        Design: Corner/state_machines/facility_close_rejected_while_an_allocation_is_open_then_freezes_posture
        """
        parties, first, second = self._one_issued_one_approved()
        validate_error(
            self._attempt_close(parties.facility_id), "ERR_FACILITY_HAS_OPEN_ALLOCATION", 409
        )
        cancelled = cancel_credit(
            first.credit_id, beneficiary_consent_reference=CONSENT_REFERENCE
        )
        assert cancelled["status"] == "CANCELLED"

        closed = validate_success(self._attempt_close(parties.facility_id), 200)

        assert_facility_ledger(
            closed,
            allocated_cents=0,
            available_cents=50000000,
            status="CLOSED",
            utilisation_posture="FROZEN",
        )
        validate_error(
            api_client.issue_credit(
                second.credit_id, factories.issue_payload(), trade_finance_officer_headers()
            ),
            "ERR_FACILITY_NOT_ACTIVE",
            409,
        )
        assert second.refresh()["status"] == "APPROVED"


class TestAmendmentAcceptanceLedgerSyncReconcilesCreditAndFacility:
    """A consented decrease from 10,000,000 to 8,000,000, tracked on both ledgers."""

    def _pending_decrease(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        ctx = issued_credit(parties, None)
        allocated_before = parties.refresh_facility()["allocated_cents"]
        amendment = draft_amendment(ctx, {"amount_cents": 8000000})
        issue_amendment(amendment["id"])
        set_clock("2026-08-12T09:00:00Z")
        return parties, ctx, amendment, allocated_before

    def test_the_accepted_decrease_re_derives_the_credit_without_re_pricing_it(self, clock):
        """Exposure and drawable figures fall; the commission chain does not move.

        PRD 3.5: "`ACCEPT` moves `PENDING_CONSENT → ACCEPTED`, sets `resolved_at` to the
        clock instant, and pulls `window_end_effective` back to the clock date, which is the
        point from which the cooling-off buffer for any subsequent amendment is measured."

        PRD 3.5: "Exactly these credit fields are re-derived: `presentation_deadline_date`
        and the confirmation window bounds, `max_drawable_cents`, `gross_exposure_cents`,
        `committed_allocation_cents`, `chargeable_utilisation_cents` and `available_cents`."

        Design: Corner/state_machines/amendment_acceptance_ledger_sync_reconciles_credit_and_facility
        """
        parties, ctx, amendment, _before = self._pending_decrease()

        accepted = consent_to_amendment(amendment["id"], parties.beneficiary_id, "ACCEPT")

        assert accepted["status"] == "ACCEPTED"
        assert accepted["requires_beneficiary_consent"] is True
        assert accepted["seq"] == 1
        assert accepted["exposure_delta_cents"] == -2000000
        assert accepted["amendment_fee_cents"] == 7500
        assert accepted["window_end_effective"] == "2026-08-12"
        assert_instant_with_milliseconds(accepted["resolved_at"], "resolved_at")
        assert accepted["resolved_at"] == "2026-08-12T09:00:00.000Z"

        credit = ctx.refresh()
        assert credit["status"] == "ISSUED"
        assert credit["amount_cents"] == 8000000
        assert credit["amendment_seq"] == 1
        assert_issuance_charges(
            credit,
            max_drawable_cents=8000000,
            gross_exposure_cents=8000000,
            committed_allocation_cents=8000000,
            commission_bps_applied=10,
            base_commission_cents=25000,
            total_charge_cents=25000,
            chargeable_utilisation_cents=8025000,
        )
        assert credit["available_cents"] == 8000000
        assert credit["presentation_deadline_date"] == "2026-11-21"

    def test_the_allocation_is_re_cut_and_the_facility_settles_above_the_credit_figure(
        self, clock
    ):
        """The 7,500 fee occupies the facility but never the credit's own utilisation.

        PRD 3.5: "The credit's existing `OPEN` FacilityAllocation row flips to `RELEASED`,
        with `released_cents` set to that row's own `allocated_cents` plus its `charge_cents`
        and `released_at` set to the clock instant, and exactly one new row is opened whose
        `allocated_cents` is the credit's new `committed_allocation_cents` and whose
        `charge_cents` is the released row's `charge_cents` plus the amendment's
        `amendment_fee_cents`."

        PRD 3.5: "Note the deliberate asymmetry this creates: the amendment fee occupies the
        facility through the allocation's `charge_cents`, but the credit's own
        `chargeable_utilisation_cents` remains `committed_allocation_cents` plus
        `total_charge_cents` under the pinned charge order and therefore excludes amendment
        fees altogether."

        Design: Corner/state_machines/amendment_acceptance_ledger_sync_reconciles_credit_and_facility
        """
        parties, ctx, amendment, allocated_before = self._pending_decrease()
        assert allocated_before == 10025000

        consent_to_amendment(amendment["id"], parties.beneficiary_id, "ACCEPT")

        rows = list_credit_allocation_rows(ctx.credit_id)
        assert len(rows) == 2
        released = [row for row in rows if row["status"] == "RELEASED"]
        opened = [row for row in rows if row["status"] == "OPEN"]
        assert len(released) == 1 and len(opened) == 1
        assert released[0]["released_cents"] == 10025000
        assert released[0]["released_at"] == "2026-08-12T09:00:00.000Z"
        assert opened[0]["basis"] == "AMENDED_DECREASE"
        assert opened[0]["allocated_cents"] == 8000000
        assert opened[0]["charge_cents"] == 32500

        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=8032500,
            available_cents=41967500,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )
        assert ctx.refresh()["chargeable_utilisation_cents"] == 8025000


class TestExpirySweepConditionalCascadeSkipsDraftAndTerminalCredits:
    """Pass four scans `ISSUED` rows only, whatever the deadline says."""

    SHORT_DATES = {
        "latest_shipment_date": "2026-08-14",
        "expiry_date": "2026-08-20",
        "presentation_period_days": 5,
    }

    def _three_credits_past_their_deadline(self):
        parties = setup_parties(facility={"limit_cents": 50000000})
        first = issued_credit(parties, None, **self.SHORT_DATES)
        second = issued_credit(parties, None, **self.SHORT_DATES)
        cancel_credit(second.credit_id, beneficiary_consent_reference=CONSENT_REFERENCE)
        third = draft_credit(parties, None, **self.SHORT_DATES)
        set_clock("2026-08-21T09:00:00Z")
        return parties, first, second, third

    def test_the_dry_run_reports_the_counters_and_mutates_nothing(self, clock):
        """One credit and one allocation are counted while every row stays put.

        PRD 3.9: "When `dry_run` is true the counts are reported and nothing is mutated."

        Design: Corner/state_machines/expiry_sweep_conditional_cascade_skips_draft_and_terminal_credits
        """
        parties, first, _second, third = self._three_credits_past_their_deadline()

        report = run_sweep(dry_run=True)

        assert_sweep_counters(report, credits_expired=1, allocations_released=1)
        assert first.refresh()["status"] == "ISSUED"
        assert third.refresh()["status"] == "DRAFT"
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=10025000)

    def test_the_wet_run_expires_only_the_issued_credit(self, clock):
        """The cancelled and drafted rows share the deadline and are still skipped.

        PRD 3.9: "Pass four expires credits: every credit whose
        `presentation_deadline_date` is strictly before the clock date, whose `status` is
        `ISSUED`, and whose `reserved_cents` is zero moves to `EXPIRED`, which is terminal,
        releasing its `OPEN` FacilityAllocation and any confirmation occupation it held."

        PRD 3.9: "Only `ISSUED` credits are scanned here, and that is sufficient precisely
        because pass three has already returned every credit whose consent window lapsed
        from `AMENDMENT_PENDING` to `ISSUED`, so the same sweep still catches it."

        Design: Corner/state_machines/expiry_sweep_conditional_cascade_skips_draft_and_terminal_credits
        """
        parties, first, second, third = self._three_credits_past_their_deadline()
        run_sweep(dry_run=True)

        report = run_sweep(dry_run=False)

        assert_sweep_counters(
            report,
            credits_expired=1,
            allocations_released=1,
            presentations_precluded=0,
            waiver_requests_expired=0,
            amendments_lapsed=0,
            facilities_reactivated=0,
        )
        expired = first.refresh()
        assert expired["status"] == "EXPIRED"
        assert expired["presentation_deadline_date"] == "2026-08-19"
        assert second.refresh()["status"] == "CANCELLED"
        drafted = third.refresh()
        assert drafted["status"] == "DRAFT"
        assert drafted["presentation_deadline_date"] == "2026-08-19"
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )


class TestConfirmationDeclinedCreditCanBeReRequestedAndThenConfirmed:
    """The confirmation dimension's retry cycle, priced on the second bank's risk."""

    def _issued_with_two_candidates(self):
        parties = setup_parties(
            facility={"limit_cents": 50000000}, beneficiary={"country_code": "LV"}
        )
        ctx = issued_credit(parties, None)
        singapore = create_bank(
            country_code="SG",
            country_risk_score=35,
            credit_rating="A",
            confirmation_appetite_cents=40000000,
        )
        swiss = create_bank(
            country_code="CH",
            country_risk_score=15,
            credit_rating="AA",
            confirmation_appetite_cents=40000000,
        )
        return parties, ctx, singapore["id"], swiss["id"]

    def test_a_decline_releases_the_occupation_and_clears_the_confirming_bank(self, clock):
        """The declining bank's line drops back to zero and the credit's field is unset.

        PRD 3.4: "Declining moves `confirmation_status` `CONFIRMATION_REQUESTED →
        CONFIRMATION_DECLINED`, clears `confirming_bank_id` back to unset, re-derives the
        declining bank's `confirming_line_used_cents` — its occupation is removed — and
        increments that bank's `version` by one, as well as the credit's."

        Design: Corner/state_machines/confirmation_declined_credit_can_be_re_requested_and_then_confirmed
        """
        _parties, ctx, singapore_id, _swiss_id = self._issued_with_two_candidates()

        requested = validate_success(
            api_client.create_confirmation_request(
                ctx.credit_id,
                factories.confirmation_request_payload(singapore_id),
                trade_finance_officer_headers(),
            ),
            200,
        )
        assert requested["confirmation_status"] == "CONFIRMATION_REQUESTED"
        assert _read_bank(singapore_id)["confirming_line_used_cents"] == 10000000

        declined = validate_success(
            api_client.create_confirmation_response(
                ctx.credit_id,
                factories.confirmation_response_payload(
                    decision="DECLINE", declined_reason="country limit already committed"
                ),
                make_correspondent_bank_headers(singapore_id),
            ),
            200,
        )

        assert declined["confirmation_status"] == "CONFIRMATION_DECLINED"
        assert declined["confirming_bank_id"] is None
        assert declined["confirmation_charge_cents"] == 0
        assert _read_bank(singapore_id)["confirming_line_used_cents"] == 0

    def test_the_retry_edge_confirms_with_the_second_bank_and_prices_its_risk(self, clock):
        """35 basis points over two quarters is 70,000, added on top of the base 25,000.

        PRD 3.4: "A fresh request may then be made against a different bank, closing the
        retry cycle `CONFIRMATION_REQUESTED → CONFIRMATION_DECLINED →
        CONFIRMATION_REQUESTED`, which carries exactly the same eligibility, country-risk and
        confirming-line preconditions and exactly the same side effects as the first request
        did."

        PRD 3.4: "The rate is 20 basis points plus one further basis point for each point of
        the confirming bank's `country_risk_score`; `confirmation_charge_cents` is then
        `gross_exposure_cents` multiplied by that rate, multiplied by the same
        inclusive-both-ends quarter count used at issuance, divided by 10,000 and rounded
        half up — computed from `gross_exposure_cents` and never from any running total."

        Design: Corner/state_machines/confirmation_declined_credit_can_be_re_requested_and_then_confirmed
        """
        parties, ctx, singapore_id, swiss_id = self._issued_with_two_candidates()
        request_confirmation(ctx.credit_id, singapore_id)
        respond_to_confirmation(
            ctx.credit_id,
            singapore_id,
            "DECLINE",
            declined_reason="country limit already committed",
        )

        re_requested = request_confirmation(ctx.credit_id, swiss_id)
        assert re_requested["confirmation_status"] == "CONFIRMATION_REQUESTED"
        assert re_requested["confirming_bank_id"] == swiss_id
        assert _read_bank(swiss_id)["confirming_line_used_cents"] == 10000000

        confirmed = respond_to_confirmation(ctx.credit_id, swiss_id, "CONFIRM")

        assert confirmed["confirmation_status"] == "CONFIRMED"
        assert_issuance_charges(
            confirmed,
            base_commission_cents=25000,
            confirmation_charge_cents=70000,
            total_charge_cents=95000,
            chargeable_utilisation_cents=10095000,
        )
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=10095000,
            available_cents=39905000,
            utilisation_posture="OPEN",
        )
