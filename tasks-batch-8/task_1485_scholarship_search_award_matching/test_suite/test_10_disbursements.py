"""Disbursement scheduling, send/confirm gates, overlap windows, and splits."""
from test_helpers import (
    ApiErrorId,
    COORDINATOR_USER_ID,
    FAO_USER_ID,
    TEST_USERS,
    assert_instant_equal,
    create_disbursement_payload,
    get_award,
    get_fund,
    get_letter_for_award,
    get_success_data,
    list_disbursements,
    list_letters,
    make_coordinator_headers,
    make_fao_headers,
    send_and_confirm,
    set_clock,
    setup_accepted_award,
    setup_fully_disbursed_award,
    setup_offered_award,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestCrossEntityGate:
    def test_create_disbursement_against_offered_award_rejected(self, api):
        """PRD §3.7: "The award must be `ACCEPTED` with `funding_status`
        `ENCUMBERED` or `DISBURSING` (otherwise `ERR_AWARD_NOT_ACCEPTED`)."

        Design: Difficulty/cross_entity_state_dependency/disbursement_requires_award_accepted
        """
        ctx = setup_offered_award(amount_cents=500000)
        award = ctx["award"]
        assert award["offer_status"] == "OFFERED"

        resp = api.create_disbursement(
            create_disbursement_payload(award["id"], amount_cents=500000), COORD
        )
        validate_error(resp, ApiErrorId.ERR_AWARD_NOT_ACCEPTED)

    def test_rejected_create_persists_nothing(self, api):
        """PRD §3.7: "The award must be `ACCEPTED` with `funding_status`
        `ENCUMBERED` or `DISBURSING` (otherwise `ERR_AWARD_NOT_ACCEPTED`)."
        PRD §3.7: "disbursements are listed with optional filtering by
        `award_id` and `status`."

        Design: Difficulty/cross_entity_state_dependency/disbursement_requires_award_accepted
        """
        ctx = setup_offered_award(amount_cents=500000)
        award = ctx["award"]
        validate_error(
            api.create_disbursement(
                create_disbursement_payload(award["id"], amount_cents=500000),
                COORD,
            ),
            ApiErrorId.ERR_AWARD_NOT_ACCEPTED,
        )
        _, meta = list_disbursements({"award_id": award["id"]})
        assert meta["total_count"] == 0, "no disbursement persisted"


class TestSendDateGate:
    def test_send_before_scheduled_date_rejected_then_allowed(self, api):
        """PRD §3.7: "the current date must be on or after the
        `scheduled_date` — sending on the scheduled day itself is allowed,
        while an earlier send is refused with `ERR_DISBURSEMENT_TOO_EARLY`.
        The send stamps `sent_at` and records the sender's `X-User-ID` as
        `sent_by_user_id`."

        Design: Corner/state_machines/disbursement_send_before_schedule_rejected
        """
        ctx = setup_accepted_award(amount_cents=500000)
        disb = get_success_data(api.create_disbursement(
            create_disbursement_payload(
                ctx["award"]["id"],
                amount_cents=500000,
                scheduled_date="2026-09-01",
                term_start_date="2026-09-01",
                term_end_date="2027-01-31",
            ),
            COORD,
        ))
        assert disb["status"] == "SCHEDULED"

        # Default clock 2026-08-01 < scheduled 2026-09-01.
        resp = api.send_disbursement(
            disb["id"], make_coordinator_headers(COORDINATOR_USER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_TOO_EARLY)
        current = validate_success(api.get_disbursement(disb["id"], COORD))
        assert current["status"] == "SCHEDULED"

        set_clock("2026-09-01T00:00:00Z")
        sent = validate_success(
            api.send_disbursement(
                disb["id"], make_coordinator_headers(COORDINATOR_USER_ID)
            )
        )
        assert sent["status"] == "SENT", "sending on the scheduled day is allowed"
        assert_instant_equal(sent["sent_at"], "2026-09-01T00:00:00Z", "sent_at")
        assert sent["sent_by_user_id"] == COORDINATOR_USER_ID


class TestConfirmSegregation:
    def test_same_user_confirm_rejected(self, api):
        """PRD §2.10: "a disbursement is sent by a `ScholarshipCoordinator`
        and confirmed by a `FinancialAidOfficer`, and the confirmer's
        `X-User-ID` must differ from the recorded `sent_by_user_id`; a
        same-person confirmation is refused with the same
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/disbursement_confirm_same_user_segregation_rejected
        """
        ctx = setup_accepted_award(amount_cents=500000)
        disb = get_success_data(api.create_disbursement(
            create_disbursement_payload(ctx["award"]["id"], amount_cents=500000),
            COORD,
        ))
        sent = get_success_data(
            api.send_disbursement(
                disb["id"], make_coordinator_headers(COORDINATOR_USER_ID)
            )
        )
        assert sent["sent_by_user_id"] == COORDINATOR_USER_ID

        # The officer role is correct but the id collides with the sender.
        resp = api.confirm_disbursement(
            disb["id"], make_fao_headers(COORDINATOR_USER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_disbursement(disb["id"], COORD))
        assert current["status"] == "SENT"

        # A different officer confirms.
        confirmed = validate_success(
            api.confirm_disbursement(disb["id"], make_fao_headers(FAO_USER_ID))
        )
        assert confirmed["status"] == "CONFIRMED"


class TestTermWindowOverlap:
    def _setup_with_first_term(self, api):
        ctx = setup_accepted_award(
            amount_cents=600000,
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 600000},
        )
        disb_1 = get_success_data(api.create_disbursement(
            create_disbursement_payload(
                ctx["award"]["id"],
                term_seq=1,
                amount_cents=300000,
                scheduled_date="2026-09-01",
                term_start_date="2026-09-01",
                term_end_date="2027-01-15",
            ),
            COORD,
        ))
        return ctx, disb_1

    def test_shared_single_day_is_overlap(self, api):
        """PRD §3.7: "The new term window must not overlap any other
        disbursement of the same award whose status is `SCHEDULED`, `SENT`, or
        `CONFIRMED` — the check treats the windows as closed intervals, so
        sharing even a single calendar day counts as overlap, while `RETURNED`
        and `CANCELLED` rows free their windows (violations are refused with
        `ERR_DISBURSEMENT_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/disbursement_term_closed_interval_overlap
        """
        ctx, _ = self._setup_with_first_term(api)
        resp = api.create_disbursement(
            create_disbursement_payload(
                ctx["award"]["id"],
                term_seq=2,
                amount_cents=300000,
                scheduled_date="2027-01-15",
                term_start_date="2027-01-15",  # == term1's inclusive end
                term_end_date="2027-05-31",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_WINDOW_OVERLAP)

    def test_day_after_window_end_succeeds(self, api):
        """PRD §3.7: "the check treats the windows as closed intervals, so
        sharing even a single calendar day counts as overlap" — starting the
        day after the prior closed window's end shares no day and is legal.
        PRD §3.7: "the sum of the award's non-cancelled disbursements must not
        exceed the award's `amount_cents` (otherwise
        `ERR_AMOUNT_EXCEEDS_REMAINING`)" — equality at the cap is allowed.

        Design: Difficulty/resource_temporal_overlap/disbursement_term_closed_interval_overlap
        """
        ctx, _ = self._setup_with_first_term(api)
        disb_2 = validate_success(
            api.create_disbursement(
                create_disbursement_payload(
                    ctx["award"]["id"],
                    term_seq=2,
                    amount_cents=300000,
                    scheduled_date="2027-01-16",
                    term_start_date="2027-01-16",
                    term_end_date="2027-05-31",
                ),
                COORD,
            ),
            expected_status=201,
        )
        assert disb_2["status"] == "SCHEDULED"
        # Sum of non-cancelled disbursements is exactly the award amount.
        data, meta = list_disbursements({"award_id": ctx["award"]["id"]})
        assert meta["total_count"] == 2
        assert sum(d["amount_cents"] for d in data) == 600000


class TestAmountExceedsRemaining:
    def test_aggregate_over_amount_rejected_equality_allowed(self, api):
        """PRD §3.7: "the sum of the award's non-cancelled disbursements must
        not exceed the award's `amount_cents` (otherwise
        `ERR_AMOUNT_EXCEEDS_REMAINING`)."

        Design: Corner/validations/validation_amount_exceeds_remaining_at_create
        """
        ctx = setup_accepted_award(amount_cents=500000)
        get_success_data(api.create_disbursement(
            create_disbursement_payload(
                ctx["award"]["id"],
                term_seq=1,
                amount_cents=300000,
                scheduled_date="2026-09-01",
                term_start_date="2026-09-01",
                term_end_date="2027-01-15",
            ),
            COORD,
        ))
        # 300000 + 300000 = 600000 > 500000.
        resp = api.create_disbursement(
            create_disbursement_payload(
                ctx["award"]["id"],
                term_seq=2,
                amount_cents=300000,
                scheduled_date="2027-02-01",
                term_start_date="2027-02-01",
                term_end_date="2027-05-31",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_REMAINING)

        # 300000 + 200000 == 500000 exactly: allowed.
        disb_2 = validate_success(
            api.create_disbursement(
                create_disbursement_payload(
                    ctx["award"]["id"],
                    term_seq=2,
                    amount_cents=200000,
                    scheduled_date="2027-02-01",
                    term_start_date="2027-02-01",
                    term_end_date="2027-05-31",
                ),
                COORD,
            ),
            expected_status=201,
        )
        assert disb_2["status"] == "SCHEDULED"


class TestSplitPlan:
    def test_split_deals_remainder_to_earliest_terms(self, api):
        """PRD §3.7: "The division is pinned: the base per-term amount is the
        award's `amount_cents` divided by `term_count` rounded down, and the
        remainder cents — the amount minus base times `term_count` — are dealt
        one extra cent each to the earliest terms, so term *i* receives the
        base plus one cent when *i* is at most the remainder, and the base
        otherwise. For example, 1,000,000 cents split over 3 terms yields
        333,334, 333,333, and 333,333 cents in that order; the alternative
        residual-to-last convention would produce a different split and is not
        used."

        Design: Difficulty/combinatorial_formula/disbursement_split_remainder_to_earliest_terms
        """
        ctx = setup_accepted_award(
            amount_cents=1000000,
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 1000000},
        )
        data = validate_success(
            api.schedule_split(ctx["award"]["id"], {"term_count": 3}, COORD)
        )
        by_seq = {d["term_seq"]: d for d in data}
        assert set(by_seq) == {1, 2, 3}
        assert by_seq[1]["amount_cents"] == 333334, (
            "floor(1000000/3) = 333333, remainder 1 -> earliest term +1"
        )
        assert by_seq[2]["amount_cents"] == 333333
        assert by_seq[3]["amount_cents"] == 333333

    def test_split_conserves_amount_and_dates(self, api):
        """PRD §3.7: "Each term's window runs from the acceptance date plus
        (*i*−1) times 180 days through the acceptance date plus *i* times 180
        days minus one day — closed intervals, each ending the day before the
        next begins — and each term's `scheduled_date` equals its
        `term_start_date`, with `term_seq` numbering terms from 1."
        PRD §3.7: "A new disbursement starts `SCHEDULED`".

        Design: Difficulty/combinatorial_formula/disbursement_split_remainder_to_earliest_terms
        """
        ctx = setup_accepted_award(
            amount_cents=1000000,
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 1000000},
        )
        data = validate_success(
            api.schedule_split(ctx["award"]["id"], {"term_count": 3}, COORD)
        )
        assert len(data) == 3
        assert sum(d["amount_cents"] for d in data) == 1000000, (
            "no cent created or destroyed"
        )
        by_seq = {d["term_seq"]: d for d in data}
        for seq, disb in by_seq.items():
            assert disb["status"] == "SCHEDULED"
            assert disb["scheduled_date"] == disb["term_start_date"]
            assert disb["award_id"] == ctx["award"]["id"]
        # Acceptance at the 2026-08-01 default clock pins the closed windows.
        assert (by_seq[1]["term_start_date"], by_seq[1]["term_end_date"]) == (
            "2026-08-01", "2027-01-27",
        )
        assert (by_seq[2]["term_start_date"], by_seq[2]["term_end_date"]) == (
            "2027-01-28", "2027-07-26",
        )
        assert (by_seq[3]["term_start_date"], by_seq[3]["term_end_date"]) == (
            "2027-07-27", "2028-01-22",
        )


class TestReturnRescheduleRetryCycle:
    def test_return_unwinds_money_and_reconfirm_restores(self, api):
        """PRD §3.7: "From `CONFIRMED`, the clawback runs: the fund's
        `returned_cents` grows by the amount and its `reserved_cents` is
        recomputed, the student's `total_disbursed_cents` shrinks by the
        amount, and the award's `funding_status` is recomputed —
        `FULLY_DISBURSED` drops back to `DISBURSING` when the net confirmed
        amount falls below `amount_cents`, an `OVER_DISBURSED` award returns
        to `FULLY_DISBURSED` when returns bring the net confirmed amount back
        up to `amount_cents`, and `DISBURSING` drops back to `ENCUMBERED`
        when every confirmation has been returned and the net confirmed
        amount reaches zero."
        PRD §3.7: "on success the row returns to `SCHEDULED` with
        `scheduled_date` and the term window replaced and `sent_at`,
        `confirmed_at`, and `returned_at` cleared."
        PRD §3.9: "Re-reaching `FULLY_DISBURSED` never duplicates the letter."
        PRD §2.9: "`disbursed_cents` is the gross sum of `CONFIRMED`
        disbursement amounts over awards of the fund's programs."

        Design: Corner/state_machines/disbursement_return_reschedule_retry_cycle
        """
        ctx = setup_fully_disbursed_award(
            amount_cents=600000,
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 600000},
        )
        award_id = ctx["award"]["id"]
        assert ctx["award"]["funding_status"] == "FULLY_DISBURSED"
        assert get_letter_for_award(award_id)["auto_created"] is True
        disb = ctx["disbursements"][0]

        returned = validate_success(
            api.mark_returned(
                disb["id"],
                {"returned_reason": "Institution rejected: student not enrolled"},
                make_fao_headers(FAO_USER_ID),
            )
        )
        assert returned["status"] == "RETURNED"

        fund = get_fund(ctx["fund"]["id"])
        assert fund["returned_cents"] == 600000
        assert fund["disbursed_cents"] == 600000, "gross confirmed sum"
        # Award still ACCEPTED with net confirmed 0 -> reservation re-expands.
        assert fund["reserved_cents"] == 600000
        assert fund["available_cents"] == 5000000 - 600000 - 600000 + 600000

        award = get_award(award_id)
        assert award["funding_status"] == "ENCUMBERED", "net confirmed fell to 0"

        rescheduled = validate_success(
            api.reschedule_disbursement(
                disb["id"],
                {
                    "scheduled_date": "2026-08-10",
                    "term_start_date": "2026-08-10",
                    "term_end_date": "2027-02-10",
                },
                COORD,
            )
        )
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["sent_at"] is None
        assert rescheduled["confirmed_at"] is None
        assert rescheduled["returned_at"] is None

        set_clock("2026-08-10T00:00:00Z")
        reconfirmed = send_and_confirm(
            disb["id"], sender_id=COORDINATOR_USER_ID, confirmer_id=FAO_USER_ID
        )
        assert reconfirmed["status"] == "CONFIRMED"
        assert get_award(award_id)["funding_status"] == "FULLY_DISBURSED"

        _, meta = list_letters({"award_id": award_id})
        assert meta["total_count"] == 1, (
            "re-reaching FULLY_DISBURSED never duplicates the letter"
        )
