"""Writes whose admissibility is decided by rows the request never names."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    admit_eligible_panelists,
    api_client,
    assert_honoraria_waterfall,
    assert_notification,
    assert_vote,
    cast_seat_vote,
    draft_decision,
    fund_case_to_assessment,
    get_success_data,
    make_panelist_headers,
    make_registrar_headers,
    notification_payload,
    nominate_seat,
    read_appointment,
    read_case,
    read_decision,
    read_domain,
    read_panelist,
    screen_seat,
    seat_panelist_cleanly,
    set_domain_lock,
    setup_notification_pending_case,
    setup_responded_case,
    validate_error,
    validate_paginated,
    vote_payload,
    waive_seat,
)

GATED_DOCKET = {
    "iana_id": "IANA-2010",
    "domain_name": "gated.example",
    "legal_name": "Gated Ltd",
    "country_code": "FR",
}
SEAT_DOCKET = {
    "iana_id": "IANA-2111",
    "domain_name": "seatcheck.example",
    "legal_name": "Seat Check SA",
    "country_code": "FR",
}
QUORUM_DOCKET = {
    "iana_id": "IANA-2212",
    "domain_name": "quorum.example",
    "legal_name": "Quorum BV",
    "country_code": "FR",
}


class TestNotificationGatedOnTheDomainRow:
    def test_an_out_of_band_lock_release_blocks_a_case_that_did_not_change(self):
        """PRD §3.5: "The first dispatch requires the case to be in
        `NOTIFICATION_PENDING`, the domain to be in `lock_status` `LOCKED` —
        otherwise the attempt is refused with `ERR_DOMAIN_NOT_LOCKED`, which is
        exactly the situation the out-of-band lock release creates — and no existing
        notification attempt on the case to be sitting in `SENT`, since an attempt
        whose outcome has not yet been recorded blocks a further dispatch with
        `ERR_INVALID_CASE_STATE`."
        PRD §3.1: "Applying the lock records `locked_at` at the current
        logical-clock instant; releasing it returns `locked_at` to null."

        Design: Difficulty/cross_entity_state_dependency/respondent_notification_is_gated_on_the_domain_row_being_locked
        """
        bundle = setup_notification_pending_case(**GATED_DOCKET)
        case_id = bundle["case"]["id"]
        domain_id = bundle["domain"]["id"]
        locked = read_domain(domain_id)
        assert locked["lock_status"] == "LOCKED"
        assert locked["locked_at"] == "2026-08-01T00:00:00.000Z"
        assert bundle["case"]["status"] == "NOTIFICATION_PENDING"
        case_version_before = bundle["case"]["version"]

        released = set_domain_lock(
            domain_id, "UNLOCKED", make_registrar_headers(bundle["registrar"]["id"])
        )
        assert released["lock_status"] == "UNLOCKED"
        assert released["locked_at"] is None
        assert released["version"] > locked["version"]
        untouched = read_case(case_id)
        assert untouched["status"] == "NOTIFICATION_PENDING", (
            "the case itself was never written to"
        )
        assert untouched["version"] == case_version_before

        refused = api_client.create_notification(
            case_id, notification_payload("EMAIL"), CASE_MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_DOMAIN_NOT_LOCKED.value, 409)
        _, meta = validate_paginated(
            api_client.list_notifications(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0
        after = read_case(case_id)
        assert after["provisional_response_due_at"] is None
        assert after["response_due_at"] is None
        assert after["version"] == case_version_before

    def test_reapplying_the_lock_makes_the_identical_dispatch_succeed(self):
        """PRD §3.5: "The attempt is created in `status` `SENT` with `dispatched_at`
        stamped from the clock, `attempt_number` 1 on the first dispatch, and
        `transmission_allowance_days` fixed by the channel: 0 days for `EMAIL`, 2
        days for `COURIER`, and 5 days for `POSTAL`."
        PRD §3.5: "The response deadline is then projected in its **provisional**
        form: both `provisional_response_due_at` and `response_due_at` are set to
        the attempt's `dispatched_at` plus its `transmission_allowance_days` days
        plus the 20-day response period, and the case records
        `deadline_variant_applied` as `PROVISIONAL`."

        Design: Difficulty/cross_entity_state_dependency/respondent_notification_is_gated_on_the_domain_row_being_locked
        """
        bundle = setup_notification_pending_case(**GATED_DOCKET)
        case_id = bundle["case"]["id"]
        domain_id = bundle["domain"]["id"]
        registrar_headers = make_registrar_headers(bundle["registrar"]["id"])
        set_domain_lock(domain_id, "UNLOCKED", registrar_headers)
        refused = api_client.create_notification(
            case_id, notification_payload("EMAIL"), CASE_MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_DOMAIN_NOT_LOCKED.value, 409)

        relocked = set_domain_lock(domain_id, "LOCKED", registrar_headers)
        assert relocked["lock_status"] == "LOCKED"
        assert relocked["locked_at"] == "2026-08-01T00:00:00.000Z"

        notification = get_success_data(
            api_client.create_notification(case_id, notification_payload("EMAIL"), CASE_MANAGER),
            201,
        )
        assert_notification(notification)
        assert notification["status"] == "SENT"
        assert notification["attempt_number"] == 1
        assert notification["channel"] == "EMAIL"
        assert notification["dispatched_at"] == "2026-08-01T00:00:00.000Z"
        assert notification["transmission_allowance_days"] == 0

        commenced = read_case(case_id)
        assert commenced["status"] == "COMMENCED"
        assert commenced["commenced_at"] == "2026-08-01T00:00:00.000Z"
        assert commenced["provisional_response_due_at"] == "2026-08-21T00:00:00.000Z"
        assert commenced["response_due_at"] == "2026-08-21T00:00:00.000Z"
        assert commenced["deadline_variant_applied"] == "PROVISIONAL"


class TestBallotRequiresTheSeatOnThatVeryCase:
    def _drafted_single_member_case(self):
        bundle = setup_responded_case(remedy_requested="CANCELLATION", **SEAT_DOCKET)
        case_id = bundle["case"]["id"]
        fund_case_to_assessment(case_id)
        seated, outsider = admit_eligible_panelists(2)
        appointment = seat_panelist_cleanly(case_id, "SOLE", seated)
        assert appointment["status"] == "ACCEPTED"
        assert float(appointment["conflict_score"]) == 0.00
        decision = draft_decision(
            case_id, seated["id"],
            draft_summary="Cancellation is the appropriate remedy.",
        )
        bundle["panelists"] = [seated]
        bundle["outsider"] = outsider
        bundle["appointments"] = [appointment]
        bundle["decision"] = decision
        return bundle

    def test_a_roster_panelist_without_a_seat_on_this_case_can_neither_vote_nor_screen(self):
        """PRD §2.1: "A conflict screening is admissible only from the neutral who
        holds the seat, meaning `X-User-ID` must equal that appointment's
        `panelist_id`; a ballot is admissible only from a neutral holding an
        `ACCEPTED` seat on the decision's case."
        PRD §3.7: "The caller supplies the `seat` they are casting for, which must
        match the seat held by their own appointment in `ACCEPTED` on the decision's
        case; a caller with no such appointment, or one claiming a seat they do not
        hold, is refused with `ERR_NOT_SEAT_HOLDER`."

        Design: Difficulty/cross_entity_state_dependency/casting_a_vote_requires_an_accepted_seat_on_that_very_case
        """
        bundle = self._drafted_single_member_case()
        decision_id = bundle["decision"]["id"]
        appointment_id = bundle["appointments"][0]["id"]
        outsider = bundle["outsider"]

        refused_vote = api_client.cast_vote(
            decision_id,
            vote_payload("SOLE", "CANCELLATION", rationale="An outsider tries to vote."),
            make_panelist_headers(outsider["id"]),
        )
        validate_error(refused_vote, ApiErrorId.ERR_NOT_SEAT_HOLDER.value, 403)

        refused_screening = api_client.screen_conflict(
            appointment_id,
            {
                "disclosed_prior_representation": False,
                "disclosed_same_firm": False,
                "disclosed_financial_interest": False,
                "prior_appointments_with_complainant": 0,
            },
            make_panelist_headers(outsider["id"]),
        )
        validate_error(refused_screening, ApiErrorId.ERR_NOT_SEAT_HOLDER.value, 403)

        _, meta = validate_paginated(
            api_client.list_votes(decision_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0
        untouched = read_appointment(appointment_id)
        assert untouched["status"] == "ACCEPTED"
        assert float(untouched["conflict_score"]) == 0.00

    def test_the_seat_holder_votes_once_and_the_stored_ballot_is_immutable(self):
        """PRD §3.7: "Ballots are immutable once written and no seat may ballot twice
        on the same decision — a second attempt is refused with
        `ERR_VOTE_ALREADY_CAST`."
        PRD §3.7: "The server derives `voter_panelist_id` itself as the
        `panelist_id` of the accepted appointment holding that seat, records the
        draft being balloted on as the ballot's `decision_id`, and stamps `cast_at`
        from the clock."

        Design: Difficulty/cross_entity_state_dependency/casting_a_vote_requires_an_accepted_seat_on_that_very_case
        """
        bundle = self._drafted_single_member_case()
        decision_id = bundle["decision"]["id"]
        seated = bundle["panelists"][0]

        ballot = cast_seat_vote(
            decision_id, seated["id"], "SOLE", "CANCELLATION",
            rationale="The registration must be cancelled.",
        )
        assert_vote(ballot)
        assert ballot["voter_panelist_id"] == seated["id"]
        assert ballot["decision_id"] == decision_id
        assert ballot["seat"] == "SOLE"
        assert ballot["vote"] == "CANCELLATION"
        assert ballot["cast_at"] == "2026-08-01T00:00:00.000Z"

        second = api_client.cast_vote(
            decision_id,
            vote_payload("SOLE", "TRANSFER", rationale="A change of mind."),
            make_panelist_headers(seated["id"]),
        )
        validate_error(second, ApiErrorId.ERR_VOTE_ALREADY_CAST.value, 409)
        ballots, meta = validate_paginated(
            api_client.list_votes(decision_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert ballots[0]["vote"] == "CANCELLATION", "the refused ballot overwrote nothing"

        issued = get_success_data(api_client.issue_decision(decision_id, CASE_MANAGER))
        assert issued["outcome"] == "CANCELLATION"
        assert issued["cancellation_votes"] == 1
        assert issued["transfer_votes"] == 0
        assert issued["deny_votes"] == 0
        assert issued["dissent_present"] is False
        assert issued["outcome_basis"] == "STRICT_MAJORITY"
        assert read_case(bundle["case"]["id"])["status"] == "IMPLEMENTATION_WAITING"


class TestIssuanceDependsOnTheSiblingSeats:
    def _draft_over_a_pending_third_seat(self):
        bundle = setup_responded_case(requests_three_member_panel=True, **QUORUM_DOCKET)
        case_id = bundle["case"]["id"]
        fund_case_to_assessment(case_id)
        panelists = admit_eligible_panelists(3)
        presiding = seat_panelist_cleanly(case_id, "PRESIDING", panelists[0])
        co_one = seat_panelist_cleanly(case_id, "CO_PANELIST_1", panelists[1], nominated_by="COMPLAINANT")
        nominated = nominate_seat(
            case_id, "CO_PANELIST_2", panelists[2]["id"], nominated_by="RESPONDENT"
        )
        co_two = screen_seat(nominated["id"], panelists[2]["id"], disclosed_same_firm=True)
        decision = draft_decision(
            case_id, panelists[0]["id"],
            draft_summary="Draft circulated while the third seat is still pending a waiver.",
        )
        cast_seat_vote(
            decision["id"], panelists[0]["id"], "PRESIDING", "TRANSFER",
            rationale="All three elements are made out.",
        )
        cast_seat_vote(
            decision["id"], panelists[1]["id"], "CO_PANELIST_1", "TRANSFER",
            rationale="I concur with the presiding panelist.",
        )
        bundle["panelists"] = panelists
        bundle["appointments"] = [presiding, co_one, co_two]
        bundle["decision"] = decision
        bundle["case"] = read_case(case_id)
        return bundle

    def test_the_incomplete_panel_is_reported_before_the_missing_ballot(self):
        """PRD §3.7: "The panel must be genuinely constituted: the case must be in
        `PANEL_CONSTITUTED`, and its seats in `ACCEPTED` must cover each seat
        required by `required_seat_count` exactly once, with seats in `REPLACED`,
        `DECLINED`, `CONFLICTED` or `DISCHARGED` disregarded; a failure here is
        refused with `ERR_PANEL_NOT_CONSTITUTED`."
        PRD §2.10: "**Completeness**, in this internal order: the three mandatory
        grounds missing at clearance (`ERR_MISSING_REQUIRED_GROUND`); a panel that is
        not fully constituted at issuance (`ERR_PANEL_NOT_CONSTITUTED`); an empty
        eligible set when the provider must select a neutral
        (`ERR_NO_ELIGIBLE_PANELIST`); fewer ballots than seats at issuance
        (`ERR_VOTES_INCOMPLETE`); a waiver missing a required consent
        (`ERR_WAIVER_INCOMPLETE`)."

        Design: Difficulty/cross_entity_state_dependency/issuance_depends_on_the_aggregate_state_of_the_sibling_appointment_rows
        """
        bundle = self._draft_over_a_pending_third_seat()
        case = bundle["case"]
        presiding, co_one, co_two = bundle["appointments"]
        assert case["required_seat_count"] == 3
        assert case["status"] == "PANEL_APPOINTMENT"
        assert case["assessed_fee_cents"] == 400000
        assert case["honoraria_pool_cents"] == 280000
        assert case["paid_cents"] == 400000
        assert [presiding["status"], co_one["status"]] == ["ACCEPTED", "ACCEPTED"]
        assert co_two["status"] == "WAIVER_PENDING"
        assert float(co_two["conflict_score"]) == 35.00
        assert all(
            read_appointment(seat["id"])["honoraria_cents"] == 0
            for seat in bundle["appointments"]
        ), "the honoraria split only runs at constitution"

        refused = api_client.issue_decision(bundle["decision"]["id"], CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_PANEL_NOT_CONSTITUTED.value, 409)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_VOTES_INCOMPLETE.value
        assert refused.status_code != 422
        still_draft = read_decision(bundle["decision"]["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["issued_at"] is None
        assert still_draft["implementation_deadline_at"] is None

    def test_granting_the_waiver_constitutes_the_panel_and_moves_the_failure_to_the_ballots(self):
        """PRD §3.6: "The panel becomes constituted at the moment the count of seats
        in `ACCEPTED` on the case reaches `required_seat_count` and those seats cover
        the required set exactly once — `SOLE` alone on a single-member case, or
        `PRESIDING`, `CO_PANELIST_1` and `CO_PANELIST_2` on a three-member case."
        PRD §3.7: "And every seat must have balloted: the count of ballots on the
        decision must equal `required_seat_count`, or issuance is refused with
        `ERR_VOTES_INCOMPLETE`."
        PRD §3.6: "On a three-member panel the `PRESIDING` seat is entitled to 40
        percent and each co-panelist to 30 percent; each seat's raw entitlement is
        floored to a whole cent independently, and then the entire rounding remainder
        is handed to the `PRESIDING` seat so that the three `honoraria_cents` values
        sum to the pool exactly."

        Design: Difficulty/cross_entity_state_dependency/issuance_depends_on_the_aggregate_state_of_the_sibling_appointment_rows
        """
        bundle = self._draft_over_a_pending_third_seat()
        decision_id = bundle["decision"]["id"]
        presiding, co_one, co_two = bundle["appointments"]

        waived = waive_seat(co_two["id"])
        assert waived["status"] == "ACCEPTED"
        assert waived["accepted_at"] == "2026-08-01T00:00:00.000Z"
        assert waived["waiver_complainant"] is True
        assert waived["waiver_respondent"] is True

        constituted = read_case(bundle["case"]["id"])
        assert constituted["status"] == "PANEL_CONSTITUTED"
        seats = [read_appointment(seat["id"]) for seat in (presiding, co_one, co_two)]
        assert [seat["honoraria_cents"] for seat in seats] == [112000, 84000, 84000]
        assert_honoraria_waterfall(seats, 280000)

        short = api_client.issue_decision(decision_id, CASE_MANAGER)
        validate_error(short, ApiErrorId.ERR_VOTES_INCOMPLETE.value, 422)

        cast_seat_vote(
            decision_id, bundle["panelists"][2]["id"], "CO_PANELIST_2", "DENY",
            rationale="I would deny the complaint on the bad faith element.",
        )
        issued = get_success_data(api_client.issue_decision(decision_id, CASE_MANAGER))
        assert issued["outcome"] == "TRANSFER"
        assert issued["transfer_votes"] == 2
        assert issued["deny_votes"] == 1
        assert issued["cancellation_votes"] == 0
        assert issued["dissent_present"] is True
        assert issued["rdnh_finding"] is False
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] == "2026-08-01T00:00:00.000Z"
        assert issued["implementation_deadline_at"] == "2026-08-14T00:00:00.000Z"
        assert read_case(bundle["case"]["id"])["status"] == "IMPLEMENTATION_WAITING"
        assert [read_panelist(p["id"])["active_case_load"] for p in bundle["panelists"]] == [1, 1, 1]
