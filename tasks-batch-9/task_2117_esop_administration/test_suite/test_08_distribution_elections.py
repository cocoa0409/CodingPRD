"""Distribution elections, the diversification window and installment delivery."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_distribution_election,
    assert_installment_payment,
    commence_election,
    create_distribution_election_payload,
    create_election,
    create_participant,
    create_plan,
    get_election,
    get_installment,
    get_participant,
    list_installments,
    make_participant_headers,
    set_clock,
    setup_cedar_valley_distribution,
    setup_forfeited_participant,
    setup_finalized_run,
    setup_ironwood_finalized_run,
    terminate_participant,
    validate_error,
    validate_paginated,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _ironwood_terminated_with_election():
    """Ironwood participant A: 876 shares, separated, election raised on 2026-07-01."""
    ctx = setup_ironwood_finalized_run(contributed_shares=2000)
    pa = ctx["participants"][0]
    terminate_participant(pa["id"], "2026-06-30", "TERMINATION")
    set_clock("2026-07-01T00:00:00Z", ADMIN)
    ctx["participant"] = get_participant(pa["id"])
    ctx["election"] = create_election(pa["id"], "TERMINATION", 876)
    return ctx


class TestParallelStateDimensions:
    def test_commence_moves_approval_only_and_builds_the_schedule(self, api):
        """PRD 3.7: "The `PlanAdministrator` commences an election, which drives
        `approval_status` from `REQUESTED` to `APPROVED` and nothing else — `payment_status`
        is deliberately left at `NOT_STARTED`, because dimension B moves only when shares
        actually move."
        PRD 3.7: "On success `approved_shares` is set to the `requested_shares` figure,
        `commenced_at_date` is set to the logical clock date, and the installment schedule is
        built."
        PRD 3.7: "Each installment takes `sequence_number` from 1 upward and
        `shares_scheduled` equal to the base, except the final installment, which takes the
        base plus the entire remainder."
        PRD 3.7: "Each installment's `scheduled_date` is the `commenced_at_date` advanced by
        one fewer whole years than its sequence number — the first is payable on the
        commencement date itself, the second one year later, and so on — keeping the same
        month and day, with 29 February mapping to 28 February in a target year that is not a
        leap year."

        Design: Difficulty/non_linear_state_machine/distribution_election_parallel_dimensions_move_independently
        """
        ctx = _ironwood_terminated_with_election()

        commenced = validate_success(
            api.commence_distribution_election(ctx["election"]["id"], ADMIN))
        assert_distribution_election(commenced)
        assert commenced["approval_status"] == "APPROVED"
        assert commenced["payment_status"] == "NOT_STARTED", (
            "dimension B does not move on commencement"
        )
        assert commenced["installment_count"] == 5
        assert commenced["approved_shares"] == 876
        assert commenced["commenced_at_date"] == "2026-07-01"

        installments = list_installments(ctx["election"]["id"])
        assert [i["shares_scheduled"] for i in installments] == [175, 175, 175, 175, 176], (
            "the remainder lands wholly on the last installment"
        )
        assert [i["sequence_number"] for i in installments] == [1, 2, 3, 4, 5]
        assert [i["scheduled_date"] for i in installments] == [
            "2026-07-01", "2027-07-01", "2028-07-01", "2029-07-01", "2030-07-01",
        ]
        for installment in installments:
            assert_installment_payment(installment)
            assert installment["status"] == "SCHEDULED"
            assert installment["shares_delivered"] == 0
            assert installment["paid_date"] is None

    def test_first_payment_moves_delivery_dimension_only(self, api):
        """PRD 3.7: "When a payment leaves at least one installment of the election still
        `SCHEDULED`, the election moves from `NOT_STARTED` to `IN_PROGRESS` — this is the
        first payment of a multi-installment schedule."
        PRD 3.7: "A successful payment sets `shares_delivered` equal to `shares_scheduled` and
        `paid_date` to the logical clock date. The participant's `allocated_shares` decreases
        by the delivered count, their `vested_shares` is recomputed from the reduced balance,
        and their `distributed_shares_cumulative` increases by the delivered count."

        Design: Difficulty/non_linear_state_machine/distribution_election_parallel_dimensions_move_independently
        """
        ctx = _ironwood_terminated_with_election()
        commence_election(ctx["election"]["id"])
        first = list_installments(ctx["election"]["id"])[0]

        paid = validate_success(api.pay_installment_payment(first["id"], ADMIN))
        assert paid["status"] == "PAID"
        assert paid["shares_delivered"] == 175
        assert paid["paid_date"] == "2026-07-01"

        election = get_election(ctx["election"]["id"])
        assert election["payment_status"] == "IN_PROGRESS"
        assert election["approval_status"] == "APPROVED", (
            "the approval dimension is unmoved by the payment"
        )

        participant = get_participant(ctx["participant"]["id"])
        assert participant["allocated_shares"] == 701
        assert participant["distributed_shares_cumulative"] == 175
        assert participant["status"] == "TERMINATED"


class TestElectionTypeGate:
    def _active_holder(self):
        return setup_finalized_run(
            contributed_shares=500,
            plan_overrides={"plan_name": "Gate Plan C", "sponsor_name": "Northgate Tooling Inc.",
                            "vesting_schedule": "CLIFF_3YR"},
            participants=[{"employee_number": "E-601"}],
        )

    def test_separation_election_for_an_active_participant_is_refused(self, api):
        """PRD 3.7: "`TERMINATION`, `RETIREMENT`, `DEATH` and `DISABILITY` are
        separation-based and require a participant who has already separated — one whose
        `status` is `TERMINATED`, `RETIRED` or `DECEASED`, and who has never reached
        `DISTRIBUTED`. `DIVERSIFICATION` is the opposite case: it is an in-service election,
        available only to a participant who is still `ACTIVE`. An election whose type does not
        match the participant's current status is refused with `ERR_ELECTION_NOT_PERMITTED`."

        Design: Difficulty/cross_entity_state_dependency/election_type_gated_by_participant_status_election_to_participant
        """
        ctx = self._active_holder()
        participant = ctx["participants"][0]
        assert participant["status"] == "ACTIVE"

        payload = create_distribution_election_payload(participant["id"], "TERMINATION", 500)
        validate_error(
            api.create_distribution_election(payload, make_participant_headers(participant["id"])),
            ApiErrorId.ERR_ELECTION_NOT_PERMITTED,
        )
        _rows, meta = validate_paginated(
            api.list_distribution_elections(ADMIN, params={"participant_id": participant["id"]})
        )
        assert meta["total_count"] == 0, "the refused election persists nothing"

    def test_the_same_election_succeeds_once_the_participant_separates(self, api):
        """PRD 3.7: "Every election is stored with both of its state dimensions at their
        initial values, `approval_status` at `REQUESTED` and `payment_status` at
        `NOT_STARTED`, with `approved_shares` and `installment_count` at 0 and
        `commenced_at_date` null. It also captures `share_price_at_election_cents`, a copy of
        the plan's `current_share_price_cents` taken at the moment the election was raised.
        For the four separation types, `diversification_year_index` and
        `diversification_cap_percent` are both null and stay null."

        Design: Difficulty/cross_entity_state_dependency/election_type_gated_by_participant_status_election_to_participant
        """
        ctx = self._active_holder()
        participant = ctx["participants"][0]
        payload = create_distribution_election_payload(participant["id"], "TERMINATION", 500)
        validate_error(
            api.create_distribution_election(payload, make_participant_headers(participant["id"])),
            ApiErrorId.ERR_ELECTION_NOT_PERMITTED,
        )

        separated = terminate_participant(participant["id"], "2026-03-31", "TERMINATION")
        assert separated["status"] == "TERMINATED"
        assert separated["vested_percentage"] == 100

        election = validate_success(
            api.create_distribution_election(payload, make_participant_headers(participant["id"])),
            201,
        )
        assert election["approval_status"] == "REQUESTED"
        assert election["payment_status"] == "NOT_STARTED"
        assert election["approved_shares"] == 0
        assert election["installment_count"] == 0
        assert election["commenced_at_date"] is None
        assert election["share_price_at_election_cents"] == 7125
        assert election["diversification_year_index"] is None
        assert election["diversification_cap_percent"] is None


class TestPutWindowCoolingBuffer:
    def _second_election_ready(self):
        """First 500 shares delivered on 2026-04-01; a second election for 400 commenced
        on 2026-06-28 and still SCHEDULED."""
        ctx = setup_cedar_valley_distribution(
            plan_overrides={"plan_name": "Buffer Plan"}, requested_shares=500)
        participant = ctx["participant"]
        set_clock("2026-06-28T00:00:00Z", ADMIN)
        second = create_election(participant["id"], "TERMINATION", 400)
        commence_election(second["id"])
        ctx["second_election"] = second
        ctx["second_installment"] = list_installments(second["id"])[0]
        return ctx

    def test_second_window_inside_the_cooling_buffer_is_refused(self, api):
        """PRD 3.7: "If the participant carries a `last_put_window_close_date` from an earlier
        window, the candidate opening date must not fall earlier than that previous closing
        date plus 30 days; an earlier candidate is refused with
        `ERR_PUT_WINDOW_BUFFER_VIOLATION`, and the whole payment fails with it."
        PRD 3.7: "Worked through: a payment on 2026-04-01 opens the window running from
        2026-04-01 through 2026-05-30. The next window may open no earlier than 2026-06-29 — a
        payment on 2026-06-28 is refused, and a payment on 2026-06-29 is admitted."

        Design: Difficulty/resource_temporal_overlap/put_window_closed_interval_plus_cooling_buffer_on_participant
        """
        ctx = self._second_election_ready()
        participant = get_participant(ctx["participant"]["id"])
        assert participant["put_window_open_date"] == "2026-04-01"
        assert participant["put_window_close_date"] == "2026-05-30"
        assert participant["last_put_window_close_date"] == "2026-05-30"

        validate_error(api.pay_installment_payment(ctx["second_installment"]["id"], ADMIN),
                       ApiErrorId.ERR_PUT_WINDOW_BUFFER_VIOLATION)

        assert get_installment(ctx["second_installment"]["id"])["status"] == "SCHEDULED"
        assert get_participant(participant["id"])["allocated_shares"] == 400, (
            "the whole payment fails, so no shares are delivered"
        )

    def test_payment_exactly_thirty_days_after_the_previous_close_is_admitted(self, api):
        """PRD 3.7: "The comparison is strictly less-than, so a candidate landing exactly on
        the previous close plus 30 days is admitted."
        PRD 3.7: "On success the participant's `put_window_open_date` and
        `put_window_close_date` are set to the candidate dates and `last_put_window_close_date`
        is set to the same closing date, which is retained after the window lapses so that the
        buffer can still be evaluated later."
        PRD 3.7: "If the participant's `allocated_shares` has reached 0 after the delivery,
        the participant advances to `DISTRIBUTED` — from `TERMINATED`, from `RETIRED` or from
        `DECEASED`, whichever they were in."

        Design: Difficulty/resource_temporal_overlap/put_window_closed_interval_plus_cooling_buffer_on_participant
        """
        ctx = self._second_election_ready()
        validate_error(api.pay_installment_payment(ctx["second_installment"]["id"], ADMIN),
                       ApiErrorId.ERR_PUT_WINDOW_BUFFER_VIOLATION)

        set_clock("2026-06-29T00:00:00Z", ADMIN)
        paid = validate_success(
            api.pay_installment_payment(ctx["second_installment"]["id"], ADMIN))
        assert paid["status"] == "PAID"
        assert paid["shares_delivered"] == 400

        participant = get_participant(ctx["participant"]["id"])
        assert participant["put_window_open_date"] == "2026-06-29"
        assert participant["put_window_close_date"] == "2026-08-27"
        assert participant["allocated_shares"] == 0
        assert participant["distributed_shares_cumulative"] == 900
        assert participant["status"] == "DISTRIBUTED"


class TestDiversificationWindow:
    def test_diversification_cap_at_twentyfive_percent_of_cumulative_shares(self, api):
        """PRD 3.7: "The cap is cumulative rather than per-election: the eligible base is the
        participant's current `allocated_shares` added to their `diversified_shares_cumulative`,
        the cumulative ceiling is that base multiplied by the cap percentage and divided by
        100, floored to whole shares, and the shares still available to elect are that
        cumulative ceiling less everything the participant has already had diversified out. A
        `requested_shares` greater than the available figure is refused with
        `ERR_DIVERSIFICATION_LIMIT_EXCEEDED`."
        PRD 3.7: "Continuing the earlier example — born 1968-05-20, hired 2010-08-15, anchor
        year 2023 — a plan year of 2026 gives an index of 4 and a cap of 25 percent, so an
        owner holding 900 allocated shares who has never diversified may elect at most 225
        shares."

        Design: Corner/calculations/diversification_cap_at_twentyfive_percent_of_cumulative_shares
        """
        ctx = setup_finalized_run(
            contributed_shares=900,
            plan_overrides={"plan_name": "Diversify Plan", "sponsor_name": "Corner Corp",
                            "vesting_schedule": "CLIFF_3YR", "diversification_min_age": 55,
                            "diversification_min_years": 10},
            participants=[{"employee_number": "E-820", "date_of_birth": "1968-05-20",
                           "hire_date": "2010-08-15"}],
        )
        participant = ctx["participants"][0]
        assert participant["allocated_shares"] == 900
        headers = make_participant_headers(participant["id"])

        over = create_distribution_election_payload(participant["id"], "DIVERSIFICATION", 226)
        validate_error(api.create_distribution_election(over, headers),
                       ApiErrorId.ERR_DIVERSIFICATION_LIMIT_EXCEEDED)

        at_cap = create_distribution_election_payload(participant["id"], "DIVERSIFICATION", 225)
        election = validate_success(api.create_distribution_election(at_cap, headers), 201)
        assert election["diversification_year_index"] == 4
        assert election["diversification_cap_percent"] == 25
        assert election["election_type"] == "DIVERSIFICATION"
        assert election["approval_status"] == "REQUESTED"

        refreshed = get_participant(participant["id"])
        assert refreshed["diversification_first_eligible_plan_year"] == 2023
        assert refreshed["diversification_eligible"] is True
        assert refreshed["diversified_shares_cumulative"] == 0, (
            "nothing is diversified out until an installment is paid"
        )

    def test_diversification_after_sixth_qualified_year_window_closed(self, api):
        """PRD 3.7: "The election's `diversification_year_index` is the plan's current
        `plan_year` less that anchor year, plus 1 — so the anchor year itself is index 1. An
        index below 1, or above 6, means the plan year lies outside the qualified period and
        the election is refused with `ERR_DIVERSIFICATION_WINDOW_CLOSED`."
        PRD 3.7: "Plan year 2028 is index 6 and lifts the cap to 50 percent; plan year 2029 is
        index 7 and closes the window altogether."

        Design: Corner/calculations/diversification_after_sixth_qualified_year_window_closed
        """
        set_clock("2029-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Late Diversify", sponsor_name="Corner Corp",
                           plan_year=2029, vesting_schedule="CLIFF_3YR",
                           diversification_min_age=55, diversification_min_years=10)
        participant = create_participant(plan["id"], employee_number="E-821",
                                         date_of_birth="1968-05-20", hire_date="2010-08-15",
                                         eligible_compensation_cents=34_500_000)
        headers = make_participant_headers(participant["id"])

        payload = create_distribution_election_payload(participant["id"], "DIVERSIFICATION", 10)
        validate_error(api.create_distribution_election(payload, headers),
                       ApiErrorId.ERR_DIVERSIFICATION_WINDOW_CLOSED)

        refreshed = get_participant(participant["id"])
        assert refreshed["diversification_first_eligible_plan_year"] == 2023
        assert refreshed["diversification_eligible"] is False
        _rows, meta = validate_paginated(
            api.list_distribution_elections(ADMIN, params={"participant_id": participant["id"]})
        )
        assert meta["total_count"] == 0


class TestElectionGuards:
    def test_election_requesting_more_than_vested_shares_rejected(self, api):
        """PRD 3.7: "The four separation types are limited by what the participant actually
        owns outright: `requested_shares` may not exceed the participant's `vested_shares`,
        and a larger request is refused with `ERR_INSUFFICIENT_SHARES`."

        Design: Corner/validations/election_requesting_more_than_vested_shares_rejected
        """
        ctx = setup_forfeited_participant(
            plan_overrides={"plan_name": "Shares Guard", "distribution_policy": "LUMP_SUM",
                            "forfeiture_sweep_threshold_shares": 1000})
        participant = ctx["participant"]
        assert participant["vested_shares"] == 580
        headers = make_participant_headers(participant["id"])

        over = create_distribution_election_payload(participant["id"], "TERMINATION", 581)
        validate_error(api.create_distribution_election(over, headers),
                       ApiErrorId.ERR_INSUFFICIENT_SHARES)

        exact = create_distribution_election_payload(participant["id"], "TERMINATION", 580)
        election = validate_success(api.create_distribution_election(exact, headers), 201)
        assert election["requested_shares"] == 580
        assert election["share_price_at_election_cents"] == 7125
        refreshed = get_participant(participant["id"])
        assert refreshed["vested_shares"] == 580
        assert refreshed["allocated_shares"] == 580

    def test_installment_paid_out_of_sequence_returns_not_due(self, api):
        """PRD 3.7: "The owning election must be `APPROVED`, the logical clock date must have
        reached the installment's `scheduled_date`, and every installment of the same election
        carrying a lower `sequence_number` must already be `PAID`; a payment that is early, or
        that jumps the queue, is refused with `ERR_INSTALLMENT_NOT_DUE`."

        Design: Corner/validations/installment_paid_out_of_sequence_returns_not_due
        """
        ctx = setup_finalized_run(
            contributed_shares=876,
            plan_overrides={"plan_name": "Sequence Plan",
                            "sponsor_name": "Ironwood Manufacturing Inc.",
                            "vesting_schedule": "CLIFF_3YR"},
            participants=[{"employee_number": "E-001"}],
        )
        participant = ctx["participants"][0]
        terminate_participant(participant["id"], "2026-06-30", "TERMINATION")
        set_clock("2026-07-01T00:00:00Z", ADMIN)
        election = create_election(participant["id"], "TERMINATION", 876)
        commence_election(election["id"])
        second = list_installments(election["id"])[1]

        validate_error(api.pay_installment_payment(second["id"], ADMIN),
                       ApiErrorId.ERR_INSTALLMENT_NOT_DUE)

        after = get_installment(second["id"])
        assert after["status"] == "SCHEDULED"
        assert after["shares_delivered"] == 0
        assert after["scheduled_date"] == "2027-07-01"
        assert get_election(election["id"])["payment_status"] == "NOT_STARTED"
        refreshed = get_participant(participant["id"])
        assert refreshed["allocated_shares"] == 876
        assert refreshed["put_window_open_date"] is None

    def test_participant_cannot_elect_on_another_participants_account(self, api):
        """PRD 2.1: "Three write operations are subject to this ownership check: raising a
        distribution or diversification election, where the `participant_id` in the payload
        must equal `X-User-ID`; raising a put option exercise, where the participant behind the
        named election must be the caller; and cancelling a put option exercise, where the
        exercise's own participant must be the caller. A mismatch on any of the three is
        refused with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."
        PRD 2.12: "Participant ownership — a `Participant` caller acts only on their own
        resources, else `ERR_NOT_RESOURCE_OWNER` (403). Applies to raising an election,
        raising a put option exercise, and cancelling a put option exercise."

        Design: Corner/validations/participant_cannot_elect_on_another_participants_account
        """
        set_clock("2026-02-01T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Owner Plan", sponsor_name="Corner Corp",
                           distribution_policy="LUMP_SUM")
        person_a = create_participant(plan["id"], employee_number="E-A",
                                      date_of_birth="1985-06-10", hire_date="2021-03-01",
                                      eligible_compensation_cents=34_500_000)
        person_b = create_participant(plan["id"], employee_number="E-B",
                                      date_of_birth="1986-06-10", hire_date="2021-03-01",
                                      eligible_compensation_cents=34_500_000)
        terminate_participant(person_b["id"], "2026-01-15", "TERMINATION")

        payload = create_distribution_election_payload(person_b["id"], "TERMINATION", 1)
        validate_error(
            api.create_distribution_election(payload, make_participant_headers(person_a["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )
        _rows, meta = validate_paginated(
            api.list_distribution_elections(ADMIN, params={"participant_id": person_b["id"]})
        )
        assert meta["total_count"] == 0
