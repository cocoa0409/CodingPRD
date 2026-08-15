"""PBGC transfers and forfeitures: amount bases, the confirmation cascade with
sponsor make-whole, rejection fork, segregation of duties, fiduciary
documentation, and the forfeiture-restoration variants."""
from test_helpers import (
    ApiErrorId,
    assert_fund_conservation,
    assert_instant_equal,
    begin_distributions,
    create_accepted_payout,
    create_case,
    create_dlr_with_covering_notice,
    create_recorded_forfeiture,
    create_search_protocol_summary,
    create_submitted_pbgc_transfer,
    effectuate_termination,
    escalate_search,
    file_dlr_on,
    get_case,
    get_participant,
    get_search_case,
    issue_noit,
    list_participant_forfeitures,
    list_participant_transfers,
    locate_participant,
    record_search_attempt,
    set_clock,
    setup_case_in_distribution,
    setup_exhausted_search,
    setup_missing_participant,
    add_participant,
    validate_error,
    validate_success,
    TEST_USERS,
    make_fiduciary_headers,
)

ADMIN = TEST_USERS["admin_headers"]
RECORDKEEPER = TEST_USERS["recordkeeper_headers"]
FIDUCIARY = TEST_USERS["fiduciary_headers"]


def _distribution_case_with_exhausted(api, balances, plan_name, plan_number,
                                      restoration_policy=None, document=True):
    """Case in DISTRIBUTION_IN_PROGRESS whose participants are all MISSING with
    exhausted (and optionally documented) search cases.
    Returns (case, participants, search_cases)."""
    case, plist = setup_case_in_distribution(
        participants=[(b, 100) for b in balances],
        plan_name=plan_name, plan_number=plan_number,
        restoration_policy=restoration_policy,
    )
    search_cases = []
    for participant in plist:
        search_cases.append(
            setup_exhausted_search(
                case["id"], participant["id"], document=document
            )
        )
    return get_case(case["id"]), plist, search_cases


class TestPbgcTransferAmountBases:
    def _setup_snapshot_case(self, api):
        """Participants 500000 / 500000 / 300000; the first two MISSING with
        searches exhausted (snapshot 500000 each) and documented; a 5000-cent
        pro-rata expense then debits 1923 / 1923 / 1154."""
        case, plist = setup_case_in_distribution(
            participants=[(500000, 100), (500000, 100), (300000, 100)],
            plan_name="Snapshot Co 401k", plan_number="020",
        )
        p_a, p_c, p_d = plist
        sc_a = setup_exhausted_search(case["id"], p_a["id"], document=True)
        sc_c = setup_exhausted_search(
            case["id"], p_c["id"], document=True,
            flag_clock="2026-11-19T00:00:00Z",
            attempt_dates=(
                "2026-11-19T00:00:00Z",
                "2026-11-20T00:00:00Z",
                "2026-11-21T00:00:00Z",
                "2026-11-22T00:00:00Z",
            ),
            exhaust_clock="2026-12-07T00:00:00Z",
        )
        assert sc_a["exhaustion_snapshot_cents"] == 500000
        assert sc_c["exhaustion_snapshot_cents"] == 500000
        # The expense allocation lands after both exhaustions.
        resp = api.create_expense_allocation(
            {
                "termination_case_id": case["id"],
                "method": "PRO_RATA_BY_BALANCE",
                "total_expense_cents": 5000,
                "description": "Final audit fee",
            },
            ADMIN,
        )
        validate_success(resp, 201)
        return case, (p_a, p_c, p_d)

    def test_pbgc_transfer_submission_net_reflects_expense(self, api):
        """PRD §3.4: "Under `SUBMISSION_NET`, the computed `amount_cents` is the
        participant's `net_distributable_cents` at the moment of creation; under
        `EXHAUSTION_SNAPSHOT`, it is the search case's frozen
        `exhaustion_snapshot_cents`."

        Design: Difficulty/dual_variant_calc/pbgc_transfer_submission_net_vs_exhaustion_snapshot
        """
        case, (p_a, p_c, p_d) = self._setup_snapshot_case(api)
        # 5000 * 500000 / 1300000 -> round_half_up(1923.0769) = 1923
        assert get_participant(p_a["id"])["net_distributable_cents"] == 498077
        transfer = create_submitted_pbgc_transfer(p_a["id"], "SUBMISSION_NET")
        assert transfer["status"] == "SUBMITTED"
        assert transfer["amount_cents"] == 498077, (
            "SUBMISSION_NET reflects the post-exhaustion expense debit"
        )

    def test_pbgc_transfer_exhaustion_snapshot_frozen(self, api):
        """PRD §3.4: "The two diverge exactly when an expense allocation has
        debited the participant between exhaustion and submission — the snapshot
        variant then produces the larger amount."

        Design: Difficulty/dual_variant_calc/pbgc_transfer_submission_net_vs_exhaustion_snapshot
        """
        case, (p_a, p_c, p_d) = self._setup_snapshot_case(api)
        assert get_participant(p_c["id"])["net_distributable_cents"] == 498077
        transfer_net = create_submitted_pbgc_transfer(p_a["id"], "SUBMISSION_NET")
        transfer_snapshot = create_submitted_pbgc_transfer(
            p_c["id"], "EXHAUSTION_SNAPSHOT"
        )
        assert transfer_snapshot["amount_cents"] == 500000, (
            "EXHAUSTION_SNAPSHOT froze the benefit at exhaustion"
        )
        assert transfer_net["amount_cents"] != transfer_snapshot["amount_cents"], (
            "identical pre-exhaustion balances produce different amounts under "
            "the two bases once an expense allocation intervenes"
        )


class TestPbgcConfirmCascade:
    def _submitted_transfer(self, api):
        case, plist, _ = _distribution_case_with_exhausted(
            api, [400000], "Pbgc Co 401k", "052"
        )
        transfer = create_submitted_pbgc_transfer(plist[0]["id"], "SUBMISSION_NET")
        assert transfer["amount_cents"] == 400000
        return case, plist[0], transfer

    def test_pbgc_confirm_acceptance(self, api):
        """PRD §3.4: "Acceptance stamps `confirmed_at`, moves the transfer
        `SUBMITTED → ACCEPTED`, moves the participant's `distribution_status` to
        `PBGC_TRANSFERRED`, and settles the ledger with a sponsor make-whole".

        Design: Difficulty/transitive_cascade/pbgc_confirm_transfer_ledger_cascade
        """
        _, participant, transfer = self._submitted_transfer(api)
        resp = api.confirm_pbgc_transfer(transfer["id"], ADMIN)
        transfer = validate_success(resp)
        assert transfer["status"] == "ACCEPTED"
        assert_instant_equal(
            transfer["confirmed_at"], "2026-11-19T00:00:00Z", "confirmed_at"
        )
        participant = get_participant(participant["id"])
        assert participant["distribution_status"] == "PBGC_TRANSFERRED", (
            "acceptance flips the participant (cascade hop 2)"
        )

    def test_pbgc_confirm_ledger_recompute(self, api):
        """PRD §3.4: "Then `pbgc_transferred_cents` increases by `amount_cents`,
        `remaining_undistributed_cents` becomes its prior value minus
        `amount_cents` plus the excess, and `resolved_participant_count` is
        recomputed."

        Design: Difficulty/transitive_cascade/pbgc_confirm_transfer_ledger_cascade
        """
        case, participant, transfer = self._submitted_transfer(api)
        validate_success(api.confirm_pbgc_transfer(transfer["id"], ADMIN))
        case = get_case(case["id"])
        assert case["pbgc_transferred_cents"] == 400000
        assert case["remaining_undistributed_cents"] == 0
        assert case["resolved_participant_count"] == 1
        assert case["all_participants_resolved"] is True
        assert case["total_plan_assets_cents"] == 400000
        assert_fund_conservation(case)


class TestPbgcSearchGate:
    def _case_with_mid_protocol_participant(self, api):
        """Participant MISSING with the search case at STEP3_CREDIT_BUREAU and
        the protocol-summary log already recorded."""
        case, plist = setup_case_in_distribution(
            participants=[(400000, 100)], plan_name="Search Gate Co 401k",
            plan_number="082",
        )
        participant = plist[0]
        _, search_case = setup_missing_participant(
            participant["id"], flag_clock="2026-11-01T00:00:00Z"
        )
        sc_id = search_case["id"]
        set_clock("2026-11-01T00:00:00Z")
        record_search_attempt(sc_id, "COMMERCIAL_LOCATOR", "2026-11-01T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-02T00:00:00Z")
        record_search_attempt(sc_id, "PUBLIC_RECORDS", "2026-11-02T00:00:00Z")
        escalate_search(sc_id)
        assert get_search_case(sc_id)["status"] == "STEP3_CREDIT_BUREAU"
        create_search_protocol_summary(case["id"], sc_id)
        return case, participant, sc_id

    def test_pbgc_blocked_until_search_exhausted(self, api):
        """PRD §3.4: "the participant's active search case must be `EXHAUSTED`,
        otherwise `ERR_SEARCH_PROTOCOL_INCOMPLETE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/pbgc_blocked_until_search_exhausted
        """
        _, participant, sc_id = self._case_with_mid_protocol_participant(api)
        resp = api.create_pbgc_transfer(
            {"participant_id": participant["id"], "amount_basis": "SUBMISSION_NET"},
            FIDUCIARY,
        )
        validate_error(resp, ApiErrorId.ERR_SEARCH_PROTOCOL_INCOMPLETE)
        assert list_participant_transfers(participant["id"]) == [], (
            "the rejected creation persists no transfer row"
        )

    def test_pbgc_allowed_after_exhaustion(self, api):
        """PRD §3.4: "With the search exhausted, two dispositions are available
        to the `IndependentFiduciary`, and both share the same front gates."

        Design: Difficulty/cross_entity_state_dependency/pbgc_blocked_until_search_exhausted
        """
        _, participant, sc_id = self._case_with_mid_protocol_participant(api)
        # Finish the protocol: credit-bureau attempt, then certified mail plus
        # the 15-day response window, then exhaust.
        set_clock("2026-11-03T00:00:00Z")
        record_search_attempt(sc_id, "CREDIT_BUREAU", "2026-11-03T00:00:00Z")
        escalate_search(sc_id)
        set_clock("2026-11-04T00:00:00Z")
        record_search_attempt(sc_id, "CERTIFIED_MAIL", "2026-11-04T00:00:00Z")
        set_clock("2026-11-19T00:00:00Z")
        search_case = escalate_search(sc_id)
        assert search_case["status"] == "EXHAUSTED"
        resp = api.create_pbgc_transfer(
            {"participant_id": participant["id"], "amount_basis": "SUBMISSION_NET"},
            FIDUCIARY,
        )
        transfer = validate_success(resp, 201)
        assert transfer["status"] == "SUBMITTED"
        assert transfer["amount_cents"] == 400000


class TestPbgcRejectionFork:
    def test_pbgc_record_rejection_keeps_participant_pending(self, api):
        """PRD §3.4: "Recording a rejection instead requires the same
        `SUBMITTED` state (otherwise `ERR_PBGC_TRANSFER_NOT_SUBMITTED`) and
        carries a mandatory `reason` (stored as `rejection_reason`); the
        transfer moves to `REJECTED` while the participant remains `MISSING`
        with `distribution_status` `PENDING_ELECTION` — the plan must then elect
        forfeiture or make a fresh PBGC submission."

        Design: Corner/state_machines/pbgc_record_rejection_keeps_participant_pending
        """
        case, plist, _ = _distribution_case_with_exhausted(
            api, [400000], "Reject Co 401k", "121"
        )
        participant = plist[0]
        transfer = create_submitted_pbgc_transfer(participant["id"], "SUBMISSION_NET")
        resp = api.record_pbgc_rejection(
            transfer["id"],
            {"reason": "PBGC returned the filing for a missing participant signature page."},
            ADMIN,
        )
        transfer = validate_success(resp)
        assert transfer["status"] == "REJECTED"
        assert transfer["rejection_reason"] == (
            "PBGC returned the filing for a missing participant signature page."
        )
        participant = get_participant(participant["id"])
        assert participant["locate_status"] == "MISSING"
        assert participant["distribution_status"] == "PENDING_ELECTION"
        case = get_case(case["id"])
        assert case["pbgc_transferred_cents"] == 0
        assert case["remaining_undistributed_cents"] == 400000

        # The forfeiture alternative remains available afterwards.
        forfeiture = create_recorded_forfeiture(participant["id"])
        assert forfeiture["status"] == "RECORDED"
        assert (
            get_participant(participant["id"])["distribution_status"] == "FORFEITED"
        )


class TestDispositionGates:
    def _zero_balance_exhausted(self, api, document=True):
        return _distribution_case_with_exhausted(
            api, [0], "Zero Co 401k", "153", document=document
        )

    def test_zero_balance_pbgc_rejected(self, api):
        """PRD §3.4: "A participant with a zero transferable amount —
        `net_distributable_cents` (or the exhaustion snapshot, per the basis)
        equal to 0 — is rejected with `ERR_ZERO_BALANCE_TRANSFER` (HTTP 422),
        and a participant who already has a `SUBMITTED` transfer is rejected
        with `ERR_PBGC_TRANSFER_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/validations/zero_balance_pbgc_returns_error
        """
        _, plist, _ = self._zero_balance_exhausted(api)
        resp = api.create_pbgc_transfer(
            {"participant_id": plist[0]["id"], "amount_basis": "SUBMISSION_NET"},
            FIDUCIARY,
        )
        validate_error(resp, ApiErrorId.ERR_ZERO_BALANCE_TRANSFER)
        assert list_participant_transfers(plist[0]["id"]) == []

    def test_fiduciary_doc_missing_blocks_pbgc(self, api):
        """PRD §2.7: "Creating a PBGC transfer or a forfeiture requires that a
        `FiduciaryLogEntry` with `entry_type` `SEARCH_PROTOCOL_SUMMARY` exists
        whose `related_entity_id` equals the id of the exhausted search case;
        closing a termination case requires that at least one
        `FiduciaryLogEntry` with `entry_type` `CLOSURE_SIGNOFF` exists for the
        case. Absence of the required entry is rejected with
        `ERR_FIDUCIARY_DOC_MISSING` (HTTP 422)."

        Design: Corner/validations/fiduciary_doc_missing_blocks_pbgc
        """
        _, plist, _ = _distribution_case_with_exhausted(
            api, [400000], "Doc Co 401k", "154", document=False
        )
        resp = api.create_pbgc_transfer(
            {"participant_id": plist[0]["id"], "amount_basis": "SUBMISSION_NET"},
            FIDUCIARY,
        )
        validate_error(resp, ApiErrorId.ERR_FIDUCIARY_DOC_MISSING)
        assert list_participant_transfers(plist[0]["id"]) == []

    def test_sod_beats_zero_balance(self, api):
        """PRD §2.7: "Subsequently, any request to create a PBGC transfer or a
        forfeiture for that participant whose `X-User-ID` equals the recorded
        `exhausted_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."
        PRD §2.9: "Seventh, segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). Eighth, fiduciary documentation
        (`ERR_FIDUCIARY_DOC_MISSING`)."
        PRD §2.9: "Twelfth and last, money rules — so a request that is both
        temporally invalid and fiscally invalid reports the temporal failure
        first."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_zero_balance
        """
        _, plist, _ = self._zero_balance_exhausted(api)
        # The search was exhausted by admin-1; a forfeiture filed under that
        # same user id violates segregation of duties (and the balance is also
        # zero — the safety gate is evaluated before the money rule).
        resp = api.create_forfeiture(
            {
                "participant_id": plist[0]["id"],
                "rationale": "Attempted forfeiture by the same user who ran the search protocol to exhaustion.",
            },
            make_fiduciary_headers("admin-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_sod_violation_persists_no_forfeiture(self, api):
        """PRD §2.7: "Subsequently, any request to create a PBGC transfer or a
        forfeiture for that participant whose `X-User-ID` equals the recorded
        `exhausted_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_zero_balance
        """
        _, plist, _ = self._zero_balance_exhausted(api)
        api.create_forfeiture(
            {
                "participant_id": plist[0]["id"],
                "rationale": "Attempted forfeiture by the same user who ran the search protocol to exhaustion.",
            },
            make_fiduciary_headers("admin-1"),
        )
        assert list_participant_forfeitures(plist[0]["id"]) == [], (
            "the rejected forfeiture leaves no row behind"
        )


class TestForfeitureRestorationVariants:
    def _forfeited_participant(self, api, restoration_policy):
        """Participant 800000, MISSING, search exhausted + documented,
        forfeiture RECORDED at 2026-11-19; clock then moved 30 days out."""
        case, plist, _ = _distribution_case_with_exhausted(
            api, [800000], "Restore Co 401k", "055",
            restoration_policy=restoration_policy,
        )
        participant = plist[0]
        forfeiture = create_recorded_forfeiture(participant["id"])
        assert forfeiture["forfeited_amount_cents"] == 800000
        set_clock("2026-12-19T00:00:00Z")  # exactly 30 days after creation
        return case, participant, forfeiture

    def test_forfeiture_restoration_nominal(self, api):
        """PRD §3.4: "Under `NOMINAL`, the restoration amount equals the
        forfeited amount exactly."

        Design: Difficulty/dual_variant_calc/forfeiture_restoration_nominal_vs_adjusted
        """
        case, participant, forfeiture = self._forfeited_participant(api, "NOMINAL")
        locate_participant(participant["id"], verified_address="9 Pine Ave")
        restored = list_participant_forfeitures(participant["id"])[0]
        assert restored["status"] == "RESTORED"
        assert restored["restoration_amount_cents"] == 800000, (
            "NOMINAL restores exactly the forfeited amount"
        )
        case = get_case(case["id"])
        assert case["total_plan_assets_cents"] == 800000
        assert case["sponsor_contribution_cents"] == 0
        assert case["remaining_undistributed_cents"] == 800000
        assert case["forfeited_cents"] == 0
        assert get_participant(participant["id"])["distribution_status"] == "RESTORED"

    def test_forfeiture_restoration_earnings_adjusted(self, api):
        """PRD §3.4: "Under `EARNINGS_ADJUSTED`, the restoration amount is the
        forfeited amount plus simple earnings: the forfeited amount multiplied
        by an annual rate of 4.5 percent, multiplied by the elapsed whole days,
        divided by 365, rounded half up to whole cents, added to the forfeited
        amount — strictly larger than nominal whenever at least one day has
        elapsed."
        PRD §3.4: "under `EARNINGS_ADJUSTED` the earnings part (the restoration
        amount minus the forfeited amount) additionally increases
        `sponsor_contribution_cents` and `total_plan_assets_cents`, raises
        `remaining_undistributed_cents` by the same earnings part, and adds it
        to the participant's `restoration_credit_cents`, where it waits to be
        paid out with the participant's next payout."

        Design: Difficulty/dual_variant_calc/forfeiture_restoration_nominal_vs_adjusted
        """
        case, participant, forfeiture = self._forfeited_participant(
            api, "EARNINGS_ADJUSTED"
        )
        locate_participant(participant["id"], verified_address="7 Birch Rd")
        restored = list_participant_forfeitures(participant["id"])[0]
        # round_half_up(800000 * 0.045 * 30 / 365) = round_half_up(2958.90) = 2959
        assert restored["restoration_amount_cents"] == 802959, (
            f"expected 800000 + 2959 = 802959, got {restored['restoration_amount_cents']}"
        )
        case = get_case(case["id"])
        assert case["sponsor_contribution_cents"] == 2959
        assert case["total_plan_assets_cents"] == 802959
        assert case["remaining_undistributed_cents"] == 802959
        participant = get_participant(participant["id"])
        assert participant["distribution_status"] == "RESTORED"
        assert participant["restoration_credit_cents"] == 2959


class TestLocateRestorationCascade:
    def _forfeited_case(self, api):
        case, plist, _ = _distribution_case_with_exhausted(
            api, [800000], "Cascade Co 401k", "050"
        )
        participant = plist[0]
        forfeiture = create_recorded_forfeiture(participant["id"])
        case = get_case(case["id"])
        assert case["forfeited_cents"] == 800000
        assert case["remaining_undistributed_cents"] == 0
        assert case["resolved_participant_count"] == 1
        return case, participant, forfeiture

    def test_locate_cascade_participant_and_forfeiture_hops(self, api):
        """PRD §3.4: "Restoration is the system-driven unwind, chained as four
        hops from a single locate event. When a `MISSING` participant is located
        while `FORFEITED`, hop two flips the participant `FORFEITED → RESTORED`;
        hop three flips the participant's `RECORDED` forfeiture to `RESTORED`,
        stamping `restored_at` and computing `restoration_amount_cents` per the
        case's `restoration_policy`, with elapsed time measured in whole
        calendar days from the forfeiture's `created_at` to now."

        Design: Difficulty/transitive_cascade/locate_triggers_restoration_ledger_cascade
        """
        _, participant, forfeiture = self._forfeited_case(api)
        resp = api.locate_participant(
            participant["id"], {"verified_address": "11 Found Ave"}, ADMIN
        )
        located = validate_success(resp)
        assert located["locate_status"] == "LOCATED"  # hop 1
        assert located["distribution_status"] == "RESTORED"  # hop 2, caused by hop 1
        restored = list_participant_forfeitures(participant["id"])[0]
        assert restored["status"] == "RESTORED"  # hop 3, caused by hop 2
        assert restored["restoration_amount_cents"] == 800000
        assert restored["restored_at"] is not None

    def test_locate_cascade_ledger_repair_hop(self, api):
        """PRD §3.4: "Hop four repairs the ledger: `forfeited_cents` decreases by
        the forfeited amount and `remaining_undistributed_cents` increases by
        it; under `EARNINGS_ADJUSTED` the earnings part (the restoration amount
        minus the forfeited amount) additionally increases
        `sponsor_contribution_cents` and `total_plan_assets_cents`, raises
        `remaining_undistributed_cents` by the same earnings part, and adds it
        to the participant's `restoration_credit_cents`, where it waits to be
        paid out with the participant's next payout. Finally
        `resolved_participant_count` is recomputed — the restored participant
        leaves the resolved set."
        PRD §2.8: "At every moment, `total_plan_assets_cents` equals the sum of
        `paid_out_cents`, `pbgc_transferred_cents`, `forfeited_cents`,
        `expense_paid_cents`, and `remaining_undistributed_cents`".

        Design: Difficulty/transitive_cascade/locate_triggers_restoration_ledger_cascade
        """
        case, participant, _ = self._forfeited_case(api)
        locate_participant(participant["id"], verified_address="11 Found Ave")
        case = get_case(case["id"])
        assert case["forfeited_cents"] == 0
        assert case["remaining_undistributed_cents"] == 800000
        assert case["resolved_participant_count"] == 0
        assert case["total_plan_assets_cents"] == 800000, (
            "a NOMINAL restoration injects no sponsor money; the conserved "
            "total is unchanged"
        )
        assert_fund_conservation(case)


class TestDuplicateOpenRecords:
    def test_duplicate_open_records_rejected(self, api):
        """PRD §3.4: "a participant who already has a `SUBMITTED` transfer is
        rejected with `ERR_PBGC_TRANSFER_ALREADY_OPEN` (HTTP 409)".
        PRD §3.7: "but only one open request exists at a time: a create while
        any request of the case is `DRAFT`, `FILED`, or `ADVERSE` is rejected
        with `ERR_DLR_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/consistency_model/duplicate_open_records_return_already_open_errors
        """
        case = create_case(plan_name="Dupe Co 401k", plan_number="200")
        p_a = add_participant(case["id"], 400000, full_name="Dupe A", ssn="121110080")
        p_b = add_participant(case["id"], 400000, full_name="Dupe B", ssn="121110081")
        # The DLR is created and filed while the clock is inside its window.
        dlr = create_dlr_with_covering_notice(case["id"])
        file_dlr_on(dlr["id"])
        issue_noit(case["id"])
        effectuate_termination(case["id"])
        begin_distributions(case["id"])
        setup_exhausted_search(case["id"], p_a["id"], document=True)
        setup_exhausted_search(case["id"], p_b["id"], document=True)
        create_submitted_pbgc_transfer(p_a["id"], "SUBMISSION_NET")
        create_recorded_forfeiture(p_b["id"])

        resp = api.create_pbgc_transfer(
            {"participant_id": p_a["id"], "amount_basis": "SUBMISSION_NET"},
            FIDUCIARY,
        )
        validate_error(resp, ApiErrorId.ERR_PBGC_TRANSFER_ALREADY_OPEN)

        resp = api.create_dlr(
            {
                "termination_case_id": case["id"],
                "intended_filing_date": "2026-09-10T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DLR_ALREADY_OPEN)


class TestFromStateSweep:
    def test_from_state_errors_across_dlr_payout_transfer_and_locate(self, api):
        """PRD §3.7: "Recording the IRS outcome requires the request to be
        `FILED` (otherwise `ERR_DLR_INVALID_STATE`)".
        PRD §3.6: "Voiding requires the payout to be `STALE_UNCASHED` (otherwise
        `ERR_PAYOUT_NOT_VOIDABLE`, HTTP 409)."
        PRD §3.4: "Confirmation requires the transfer to be `SUBMITTED`
        (otherwise `ERR_PBGC_TRANSFER_NOT_SUBMITTED`, HTTP 409)".
        PRD §3.3: "from any other `locate_status` the direct locate is rejected
        with `ERR_PARTICIPANT_NOT_MISSING` (HTTP 409)".

        Design: Corner/consistency_model/from_state_errors_across_dlr_payout_transfer_and_locate
        """
        case = create_case(plan_name="FromState Co 401k", plan_number="201")
        p_pay = add_participant(case["id"], 250000, full_name="Fs Pay", ssn="121110090")
        p_q = add_participant(case["id"], 250000, full_name="Fs Queue", ssn="121110091")
        p_m = add_participant(case["id"], 400000, full_name="Fs Em", ssn="121110092")
        dlr = create_dlr_with_covering_notice(case["id"])  # stays DRAFT
        issue_noit(case["id"])
        effectuate_termination(case["id"])
        begin_distributions(case["id"])
        _, payout = create_accepted_payout(p_pay["id"], "DIRECT_ROLLOVER_IRA")
        setup_exhausted_search(case["id"], p_m["id"], document=True)
        transfer = create_submitted_pbgc_transfer(p_m["id"], "SUBMISSION_NET")
        validate_success(
            api.record_pbgc_rejection(
                transfer["id"],
                {"reason": "PBGC returned the filing for corrections."},
                ADMIN,
            )
        )

        resp = api.record_determination(dlr["id"], {"outcome": "FAVORABLE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DLR_INVALID_STATE)

        resp = api.void_payout(payout["id"], RECORDKEEPER)
        validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_VOIDABLE)

        resp = api.confirm_pbgc_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PBGC_TRANSFER_NOT_SUBMITTED)

        resp = api.locate_participant(p_q["id"], {}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_MISSING)


class TestSnapshotMakeWhole:
    def test_snapshot_confirm_sponsor_make_whole(self, api):
        """PRD §3.4: "Acceptance stamps `confirmed_at`, moves the transfer
        `SUBMITTED → ACCEPTED`, moves the participant's `distribution_status` to
        `PBGC_TRANSFERRED`, and settles the ledger with a sponsor make-whole:
        the excess is the amount by which the frozen `amount_cents` exceeds the
        participant's current `net_distributable_cents`, floored at zero; when
        the excess is positive, the case's `sponsor_contribution_cents` and
        `total_plan_assets_cents` each increase by the excess — the sponsor
        funds the frozen benefit above the participant's post-expense net."

        Design: Corner/calculations/snapshot_confirm_sponsor_make_whole
        """
        case, plist = setup_case_in_distribution(
            participants=[(500000, 100), (300000, 100)],
            plan_name="MakeWhole Co 401k", plan_number="135",
        )
        p_a, p_d = plist
        setup_exhausted_search(case["id"], p_a["id"], document=True)
        # Pro-rata 5000 over vested balances 500000 / 300000 -> 3125 / 1875.
        validate_success(
            api.create_expense_allocation(
                {
                    "termination_case_id": case["id"],
                    "method": "PRO_RATA_BY_BALANCE",
                    "total_expense_cents": 5000,
                    "description": "Final audit fee",
                },
                ADMIN,
            ),
            201,
        )
        assert get_participant(p_a["id"])["net_distributable_cents"] == 496875
        transfer = create_submitted_pbgc_transfer(p_a["id"], "EXHAUSTION_SNAPSHOT")
        assert transfer["amount_cents"] == 500000, "the snapshot froze 500000"

        validate_success(api.confirm_pbgc_transfer(transfer["id"], ADMIN))
        case = get_case(case["id"])
        # excess = 500000 - 496875 = 3125, sponsor-funded on confirmation
        assert case["sponsor_contribution_cents"] == 3125
        assert case["total_plan_assets_cents"] == 803125
        assert case["pbgc_transferred_cents"] == 500000
        assert case["remaining_undistributed_cents"] == 298125
        assert_fund_conservation(case)
        assert get_participant(p_a["id"])["distribution_status"] == "PBGC_TRANSFERRED"
