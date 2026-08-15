"""Penalty assessment tiers, OCC amendment, appeals, and segregation of
duties."""
from test_helpers import (
    ApiErrorId,
    assert_penalty,
    assert_version_incremented,
    assess_penalty,
    file_appeal,
    file_appeal_under_review,
    get_result_of,
    get_success_data,
    make_athlete_headers,
    make_referee_headers,
    setup_finished_race,
    setup_live_race,
    TEST_USERS,
    validate_error,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]


class TestDraftingPenaltyTiers:
    def test_drafting_penalty_tiered_branching(self, api):
        """PRD §3.7: "For `DRAFTING`, the system counts the registration's
        prior drafting penalties — those in `ASSESSED` or `CONFIRMED` status,
        excluding the penalty being created or amended. With no priors the
        penalty is 120 seconds; with one prior, 300 seconds; with two or more
        priors the penalty carries zero seconds and instead sets
        `triggers_dsq`, the disqualification flag."

        Design: Difficulty/combinatorial_formula/drafting_penalty_tiered_branching
        """
        ctx = setup_live_race(num_athletes=1)  # non-draft-legal wave
        registration = ctx["registrations"][0]

        p1 = validate_success(api.create_penalty(
            registration["id"], {"kind": "DRAFTING"},
            make_referee_headers("ref-1")), expected_status=201)
        assert_penalty(p1)
        assert p1["seconds"] == 120 and p1["triggers_dsq"] is False, \
            "0 priors -> 120 seconds"

        p2 = validate_success(api.create_penalty(
            registration["id"], {"kind": "DRAFTING"},
            make_referee_headers("ref-1")), expected_status=201)
        assert p2["seconds"] == 300 and p2["triggers_dsq"] is False, \
            "1 prior -> 300 seconds"

        p3 = validate_success(api.create_penalty(
            registration["id"], {"kind": "DRAFTING"},
            make_referee_headers("ref-1")), expected_status=201)
        assert p3["seconds"] == 0 and p3["triggers_dsq"] is True, \
            ">=2 priors -> 0 seconds with the DSQ flag"

    def test_fixed_penalty_kinds_are_flat_rates(self, api):
        """PRD §3.7: "The fixed kinds are simpler: `COURSE_VIOLATION` is
        always 300 seconds and `EQUIPMENT` always 60 seconds, and neither sets
        `triggers_dsq`."

        Design: Difficulty/combinatorial_formula/drafting_penalty_tiered_branching
        """
        ctx = setup_live_race(num_athletes=1)
        registration = ctx["registrations"][0]
        violation = assess_penalty(registration["id"], kind="COURSE_VIOLATION")
        assert violation["seconds"] == 300
        assert violation["triggers_dsq"] is False
        equipment = assess_penalty(registration["id"], kind="EQUIPMENT")
        assert equipment["seconds"] == 60
        assert equipment["triggers_dsq"] is False

    def test_draft_legal_wave_rejects_drafting_penalty(self, api):
        """PRD §3.7: "Drafting is policed per wave: assessing a `DRAFTING`
        penalty against a registration whose wave is `draft_legal` is rejected
        outright with `ERR_DRAFT_LEGAL_WAVE` (HTTP 400)."

        Design: Corner/validations/draft_legal_wave_rejects_drafting_penalty
        """
        ctx = setup_live_race(
            has_swim=False,
            wave_overrides=[{"division": "ELITE", "draft_legal": True,
                             "age_band_min": 18, "age_band_max": 99,
                             "scheduled_start_time": "2026-10-15T07:30:00Z"}],
            water_pool_units=100)
        registration = ctx["registrations"][0]
        assert registration["status"] == "RACING"

        resp = api.create_penalty(registration["id"], {"kind": "DRAFTING"},
                                  make_referee_headers("ref-1"))
        validate_error(resp, ApiErrorId.ERR_DRAFT_LEGAL_WAVE.value)

        # A non-drafting kind is unaffected by the wave's draft_legal flag.
        violation = assess_penalty(registration["id"], kind="COURSE_VIOLATION")
        assert violation["seconds"] == 300


class TestPenaltyAmendOCC:
    def test_stale_penalty_version_occ(self, api):
        """PRD §2.8: "Amending an assessed penalty (the `POST
        /penalties/{id}/amend` capability) requires
        `expected_penalty_version` in the request body, carrying the version
        of the Penalty the client last observed; if it does not match the
        Penalty's current `version`, the request is rejected with
        `ERR_STALE_PENALTY_VERSION` (HTTP 412)."
        PRD §3.7: "the amendment recomputes `seconds` and `triggers_dsq` from
        the current prior-penalty counts and increments the penalty's
        `version` by one, leaving it `ASSESSED`."

        Design: Corner/errors/error_stale_penalty_version_occ
        """
        ctx = setup_live_race(num_athletes=1)
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="DRAFTING")
        observed_version = penalty["version"]

        amended = validate_success(api.amend_penalty(
            penalty["id"],
            {"expected_penalty_version": observed_version,
             "notes": "video review confirms"},
            make_referee_headers("ref-1")))
        assert_version_incremented(amended["version"], observed_version)
        assert amended["status"] == "ASSESSED", "amend leaves the state unchanged"

        stale = api.amend_penalty(
            penalty["id"],
            {"expected_penalty_version": observed_version,
             "kind": "COURSE_VIOLATION"},
            make_referee_headers("ref-1"))
        validate_error(stale, ApiErrorId.ERR_STALE_PENALTY_VERSION.value)

        after = validate_success(api.get_penalty(penalty["id"], RD))
        assert after["kind"] == "DRAFTING", "stale amend did not apply"
        assert after["notes"] == "video review confirms"


class TestAppealLifecycle:
    def test_appeal_decide_reduced_sets_seconds(self, api):
        """PRD §3.7: "The decision stamps `decision` and `decided_by_user_id`
        and resolves the penalty: `UPHELD` confirms it at its original
        seconds, `REDUCED` confirms it at `reduced_seconds`, and `OVERTURNED`
        overturns it — with totals, ranks, and any disqualification cascade
        recomputed accordingly."
        PRD §3.6: "`penalty_seconds_total` sums the `seconds` of the
        registration's penalties in `CONFIRMED` status only".

        Design: Corner/state_machines/appeal_decide_reduced_sets_seconds
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="DRAFTING",
                                 referee_id="ref-1")
        assert penalty["seconds"] == 120
        appeal = file_appeal_under_review(penalty["id"], athlete,
                                          reviewer_id="ref-2",
                                          grounds="too harsh")

        decided = validate_success(api.decide_appeal(
            appeal["id"], {"decision": "REDUCED", "reduced_seconds": 60},
            make_referee_headers("ref-2")))
        assert decided["decision"] == "REDUCED"
        assert decided["status"] == "DECIDED"

        penalty_after = validate_success(api.get_penalty(penalty["id"], RD))
        assert penalty_after["status"] == "CONFIRMED"
        assert penalty_after["seconds"] == 60, \
            "REDUCED confirms the penalty at the substituted seconds"
        result = get_result_of(registration["id"])
        assert result["penalty_seconds_total"] == 60

    def test_segregation_of_duties_assessor_cannot_decide(self, api):
        """PRD §3.7: "the deciding referee's `X-User-ID` must differ from the
        penalty's `assessed_by_user_id` — segregation of duties, rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

        Design: Corner/state_machines/segregation_of_duties_assessor_cannot_decide
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="COURSE_VIOLATION",
                                 referee_id="ref-1")
        appeal = file_appeal(penalty["id"], athlete, grounds="stayed on course")
        get_success_data(api.begin_review_appeal(
            appeal["id"], make_referee_headers("ref-1")))

        resp = api.decide_appeal(appeal["id"], {"decision": "UPHELD"},
                                 make_referee_headers("ref-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        appeal_after = validate_success(api.get_appeal(appeal["id"], RD))
        penalty_after = validate_success(api.get_penalty(penalty["id"], RD))
        assert appeal_after["status"] == "UNDER_REVIEW"
        assert penalty_after["status"] == "ASSESSED"

    def test_appeal_decide_requires_penalty_assessed(self, api):
        """PRD §3.7: "Decision carries three guards: the penalty must still be
        `ASSESSED` (`ERR_PENALTY_NOT_ASSESSED`)".

        Design: Difficulty/cross_entity_state_dependency/appeal_decide_requires_penalty_assessed
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="EQUIPMENT",
                                 referee_id="ref-1")
        appeal_one = file_appeal(penalty["id"], athlete, grounds="first appeal")
        appeal_two = file_appeal(penalty["id"], athlete, grounds="second appeal")

        get_success_data(api.begin_review_appeal(
            appeal_one["id"], make_referee_headers("ref-2")))
        get_success_data(api.decide_appeal(
            appeal_one["id"], {"decision": "OVERTURNED"},
            make_referee_headers("ref-2")))
        penalty_after = validate_success(api.get_penalty(penalty["id"], RD))
        assert penalty_after["status"] == "OVERTURNED", \
            "the first appeal's decision resolved the penalty"

        get_success_data(api.begin_review_appeal(
            appeal_two["id"], make_referee_headers("ref-2")))
        resp = api.decide_appeal(appeal_two["id"], {"decision": "UPHELD"},
                                 make_referee_headers("ref-2"))
        validate_error(resp, ApiErrorId.ERR_PENALTY_NOT_ASSESSED.value)

        appeal_two_after = validate_success(api.get_appeal(appeal_two["id"], RD))
        assert appeal_two_after["status"] == "UNDER_REVIEW", \
            "rejected decide leaves the appeal UNDER_REVIEW"
        assert validate_success(api.get_penalty(penalty["id"], RD))["status"] == "OVERTURNED"

    def test_overturned_penalty_stops_contributing(self, api):
        """PRD §3.7: "Overturning recomputes `penalty_seconds_total` so the
        overturned penalty stops contributing." With the penalty ASSESSED the
        sum is already zero; after an UPHELD-then-OVERTURNED contrast is not
        reachable, so the check is that OVERTURNED never enters the
        CONFIRMED-only sum.
        PRD §3.6: "`penalty_seconds_total` sums the `seconds` of the
        registration's penalties in `CONFIRMED` status only — assessed and
        overturned penalties contribute nothing."

        Design: Difficulty/cross_entity_state_dependency/appeal_decide_requires_penalty_assessed
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="EQUIPMENT",
                                 referee_id="ref-1")
        appeal = file_appeal_under_review(penalty["id"], athlete,
                                          reviewer_id="ref-2")
        get_success_data(api.decide_appeal(
            appeal["id"], {"decision": "OVERTURNED"},
            make_referee_headers("ref-2")))
        result = get_result_of(registration["id"])
        assert result["penalty_seconds_total"] == 0, \
            "an OVERTURNED penalty contributes nothing to the total"

    def test_appeal_window_expired_temporal(self, api):
        """PRD §3.7: "The athlete (or a `RaceDirector` on their behalf) may
        appeal an `ASSESSED` penalty by filing `grounds` against it, provided
        the logical clock is at or before the penalty's
        `appeal_window_expires_at` — filing after that instant is rejected
        with `ERR_APPEAL_WINDOW_EXPIRED`."
        PRD §3.7: "`assessed_at` stamped from the clock, and
        `appeal_window_expires_at` computed as `assessed_at` plus the event's
        `appeal_window_minutes`."

        Design: Corner/validations/appeal_window_expired_temporal
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        # Assessed at the race-start clock 2026-10-15T08:00:00Z; the default
        # 60-minute window expires at 09:00:00Z.
        penalty = assess_penalty(registration["id"], kind="EQUIPMENT",
                                 referee_id="ref-1")
        assert penalty["assessed_at"] == "2026-10-15T08:00:00Z"
        assert penalty["appeal_window_expires_at"] == "2026-10-15T09:00:00Z"

        get_success_data(api.set_clock("2026-10-15T09:00:01Z", RD))
        resp = api.create_appeal(penalty["id"], {"grounds": "late"},
                                 make_athlete_headers(athlete["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value)

    def test_withdraw_appeal_pending_beats_refund_requirement(self, api):
        """PRD §3.4: "Two guards apply: no penalty of the registration may
        have an appeal in `FILED` or `UNDER_REVIEW` (`ERR_APPEAL_PENDING`),
        and when the computed provisional refund is above zero a
        `refund_destination` payout destination must be supplied
        (`ERR_REFUND_DESTINATION_REQUIRED`, HTTP 400)."
        PRD §2.10: "After body validation come the integrity-of-competition
        guards (an open appeal blocking withdrawal, `ERR_APPEAL_PENDING`; an
        appeal decider who assessed the penalty, `ERR_SEGREGATION_OF_DUTIES`),
        then state-machine from-state validity (`ERR_INVALID_STATE`)". The
        fiscal refund-destination rule sits with "the operation-specific
        business constraints" evaluated last, so the open-appeal guard
        surfaces first.

        Design: Difficulty/priority_pair_validation_conflict/withdraw_appeal_pending_vs_refund_fiscal
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="DRAFTING",
                                 referee_id="ref-1")
        file_appeal(penalty["id"], athlete, grounds="no draft occurred")

        # No refund_destination supplied; the open appeal must be the error.
        resp = api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={})
        err = validate_error(resp, ApiErrorId.ERR_APPEAL_PENDING.value)
        assert err["error_id"] != ApiErrorId.ERR_REFUND_DESTINATION_REQUIRED.value

        after = validate_success(api.get_registration(registration["id"], RD))
        assert after["status"] == "RACING", "no withdrawal side effects fired"

    def test_withdraw_blocked_by_open_appeal_even_with_destination(self, api):
        """PRD §3.4: "no penalty of the registration may have an appeal in
        `FILED` or `UNDER_REVIEW` (`ERR_APPEAL_PENDING`)".

        Design: Difficulty/priority_pair_validation_conflict/withdraw_appeal_pending_vs_refund_fiscal
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="EQUIPMENT",
                                 referee_id="ref-1")
        file_appeal(penalty["id"], athlete, grounds="equipment was legal")

        resp = api.withdraw_registration(
            registration["id"], make_athlete_headers(athlete["id"]),
            payload={"refund_destination": "card-1"})
        validate_error(resp, ApiErrorId.ERR_APPEAL_PENDING.value)
        after = validate_success(api.get_registration(registration["id"], RD))
        assert after["status"] == "RACING"
