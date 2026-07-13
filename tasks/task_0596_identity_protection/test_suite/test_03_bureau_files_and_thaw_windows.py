"""Bureau files: scores, the freeze/thaw cycle, and temporary thaw windows (PRD §3.3)."""

from test_helpers import (
    ApiErrorId,
    assert_bureau_profile,
    assert_instant_equals,
    assert_thaw_window,
    create_thaw_window,
    create_thaw_window_payload,
    create_verified_subscriber,
    get_bureau_profiles,
    get_credit_summary,
    get_subscriber,
    make_subscriber_headers,
    score_refresh,
    set_clock,
    setup_frozen_equifax_profile,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFreezeThawCycle:
    """UNFROZEN -> FREEZE_PENDING -> FROZEN -> THAW_PENDING -> UNFROZEN, and round again."""

    def test_full_freeze_thaw_cycle_returns_the_file_to_unfrozen(self, api, admin_headers):
        """PRD §3.3: "A `FREEZE` request against an `UNFROZEN` file moves it
        `UNFROZEN → FREEZE_PENDING`; the bureau's callback then confirms it, moving
        `FREEZE_PENDING → FROZEN`. A `THAW` request against a `FROZEN` file moves it
        `FROZEN → THAW_PENDING`; the same callback confirms it, moving `THAW_PENDING → UNFROZEN`,
        and the file is available for cycling again."
        PRD §3.3: "Every one of these four transitions increments the bureau profile's `version` by
        one."

        Design: Difficulty/non_linear_state_machine/bureau_profile_freeze_thaw_full_cycle_returns_to_unfrozen
        """
        _, subscriber = create_verified_subscriber(full_name="Tess Aubry", ssn_last4="7777")
        equifax = get_bureau_profiles(subscriber["id"])[0]
        assert equifax["bureau"] == "EQUIFAX"
        sub_headers = make_subscriber_headers(subscriber["id"])

        after_freeze_req = validate_success(
            api.freeze_request(equifax["id"], {"action": "FREEZE"}, sub_headers)
        )
        assert after_freeze_req["freeze_status"] == "FREEZE_PENDING"

        after_freeze = validate_success(api.confirm_bureau_profile(equifax["id"], admin_headers))
        assert after_freeze["freeze_status"] == "FROZEN"

        after_thaw_req = validate_success(
            api.freeze_request(equifax["id"], {"action": "THAW"}, sub_headers)
        )
        assert after_thaw_req["freeze_status"] == "THAW_PENDING"

        after_thaw = validate_success(api.confirm_bureau_profile(equifax["id"], admin_headers))
        assert_bureau_profile(after_thaw)
        assert after_thaw["freeze_status"] == "UNFROZEN", "the cycle closes back on UNFROZEN"
        assert after_thaw["version"] == 5, (
            "version 1 at provisioning plus one for each of the four cycle transitions"
        )

    def test_the_freeze_cycle_can_be_re_entered_once_it_returns_to_unfrozen(
        self, api, admin_headers
    ):
        """PRD §3.3: "A `THAW` request against a `FROZEN` file moves it `FROZEN → THAW_PENDING`;
        the same callback confirms it, moving `THAW_PENDING → UNFROZEN`, and the file is available
        for cycling again."

        Design: Difficulty/non_linear_state_machine/bureau_profile_freeze_thaw_full_cycle_returns_to_unfrozen
        """
        _, subscriber = create_verified_subscriber(full_name="Tess Aubry", ssn_last4="7777")
        equifax = get_bureau_profiles(subscriber["id"])[0]
        sub_headers = make_subscriber_headers(subscriber["id"])

        validate_success(api.freeze_request(equifax["id"], {"action": "FREEZE"}, sub_headers))
        validate_success(api.confirm_bureau_profile(equifax["id"], admin_headers))
        validate_success(api.freeze_request(equifax["id"], {"action": "THAW"}, sub_headers))
        validate_success(api.confirm_bureau_profile(equifax["id"], admin_headers))

        reentered = validate_success(
            api.freeze_request(equifax["id"], {"action": "FREEZE"}, sub_headers)
        )
        assert reentered["freeze_status"] == "FREEZE_PENDING", "the cycle is re-enterable"

    def test_confirming_a_file_with_nothing_pending_is_rejected(self, api, admin_headers):
        """PRD §3.3: "Requesting a freeze on a file that is not `UNFROZEN`, requesting a thaw on a
        file that is not `FROZEN`, or confirming a file that has nothing pending, all fail with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/bureau_confirm_from_unfrozen_rejected
        """
        _, subscriber = create_verified_subscriber(full_name="Un Frozen", ssn_last4="1616")
        equifax = get_bureau_profiles(subscriber["id"])[0]
        assert equifax["freeze_status"] == "UNFROZEN"

        resp = api.confirm_bureau_profile(equifax["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_bureau_profile(equifax["id"], admin_headers))
        assert after["freeze_status"] == "UNFROZEN"
        assert after["version"] == 1, "the rejected callback mutated nothing"


class TestCompositeCreditScore:
    def test_three_reporting_bureaus_produce_a_weighted_composite(self, api):
        """PRD §3.3: "Otherwise, each contributing profile carries a bureau weight: `EQUIFAX`
        weighs 0.35, `EXPERIAN` weighs 0.35, and `TRANSUNION` weighs 0.30."
        PRD §3.3: "The first refresh that yields a non-null composite is special. It carries the
        subscriber's monitoring dimension `PENDING_DATA → MONITORED`, and it writes
        `baseline_composite_credit_score` — a permanent snapshot of the composite as it stood the
        first time it existed. That baseline is never rewritten."

        Design: Corner/calculations/composite_score_three_bureaus_weighted_695
        """
        _, subscriber = create_verified_subscriber(full_name="Tri Score", ssn_last4="2121")
        equifax, experian, transunion = get_bureau_profiles(subscriber["id"])

        score_refresh(equifax["id"], 700)
        score_refresh(experian["id"], 720)
        score_refresh(transunion["id"], 660)

        summary = get_credit_summary(subscriber["id"])
        # 0.35*700 + 0.35*720 + 0.30*660 = 695.0, divided by a weight sum of 1.00
        assert summary["composite_credit_score"] == 695
        assert summary["baseline_composite_credit_score"] == 700, (
            "the baseline was written on the first non-null composite (EQUIFAX alone)"
        )
        assert summary["bureau_count"] == 3
        assert summary["scored_bureau_count"] == 3
        assert summary["monitoring_status"] == "MONITORED"

    def test_partially_reported_bureaus_renormalise_the_weight_sum(self, api):
        """PRD §3.3: "Take every bureau profile of the subscriber whose `credit_score` is non-null;
        profiles that have not yet reported are excluded entirely — they do not count as a zero."
        PRD §3.3: "Multiply each contributing profile's `credit_score` by its bureau's weight, sum
        those products, and divide that sum by the total of the weights of the contributing
        profiles only — this renormalisation is what makes a partially-reported subscriber's
        composite a properly weighted average rather than a deflated one."

        Design: Corner/calculations/composite_score_partial_bureaus_renormalised_682
        """
        _, subscriber = create_verified_subscriber(full_name="Part Score", ssn_last4="2323")
        equifax, _experian, transunion = get_bureau_profiles(subscriber["id"])

        score_refresh(equifax["id"], 700)
        score_refresh(transunion["id"], 660)

        summary = get_credit_summary(subscriber["id"])
        # (0.35*700 + 0.30*660) / 0.65 == 443 / 0.65 == 681.53..., rounded half up to 682.
        assert summary["composite_credit_score"] == 682, (
            "the unscored EXPERIAN weight leaves the denominator entirely"
        )
        assert summary["scored_bureau_count"] == 2
        assert summary["bureau_count"] == 3
        assert summary["monitoring_status"] == "MONITORED"

    def test_a_forty_point_score_drop_adds_twelve_to_both_variants(self, api):
        """PRD §3.5: "Next, if the subscriber has a non-null `baseline_composite_credit_score` and
        a non-null `composite_credit_score` and the baseline exceeds the current composite by at
        least 40 points, add a further 12 points for the score drop."
        PRD §3.3: "Every subsequent refresh recomputes `composite_credit_score` and leaves the
        monitoring dimension at `MONITORED` (a `MONITORED → MONITORED` self-transition), recomputes
        both risk variants, and leaves the baseline exactly where it was."

        Design: Corner/calculations/score_drop_term_adds_twelve_at_forty_point_drop
        """
        _, subscriber = create_verified_subscriber(full_name="Drop Test", ssn_last4="2424")
        equifax, experian, transunion = get_bureau_profiles(subscriber["id"])

        score_refresh(equifax["id"], 700)
        score_refresh(experian["id"], 720)
        score_refresh(transunion["id"], 660)
        score_refresh(equifax["id"], 650)
        score_refresh(experian["id"], 640)
        score_refresh(transunion["id"], 630)

        after = get_subscriber(subscriber["id"])
        assert after["baseline_composite_credit_score"] == 700, "the baseline is never rewritten"
        # 0.35*650 + 0.35*640 + 0.30*630 = 640.5, rounded half up to 641. 700 - 641 == 59 >= 40.
        assert after["composite_credit_score"] == 641
        assert after["risk_score"] == 22, "10 base + 12 score-drop, with no alerts on file"
        assert after["underwriting_risk_score"] == 22


class TestCreditSummaryEmptyScoredSet:
    """The empty scored-bureau set is a null composite, never a zero."""

    def test_credit_summary_reports_null_composite_before_any_bureau_reports(self, api):
        """PRD §3.3: "Take every bureau profile of the subscriber whose `credit_score` is non-null;
        profiles that have not yet reported are excluded entirely — they do not count as a zero. If
        that set is empty, the composite is null (not zero) and the subscriber's monitoring
        dimension stays at `PENDING_DATA`."
        PRD §3.1: "It answers with the `subscriber_id`, the `composite_credit_score`, the
        `baseline_composite_credit_score`, a `bureau_count` giving the number of bureau profiles the
        subscriber holds, a `scored_bureau_count` giving how many of those have actually reported a
        score, the current `monitoring_status`, both `risk_score` and `underwriting_risk_score`, and
        the `insurance_remaining_cents` with its `insurance_status`."

        Design: Difficulty/boundary_precision_check/credit_summary_empty_scored_set_is_null_not_zero
        """
        _, subscriber = create_verified_subscriber(full_name="Ione Wren", ssn_last4="5678")

        summary = validate_success(
            api.get_credit_summary(
                subscriber["id"], make_subscriber_headers(subscriber["id"])
            )
        )
        assert summary["composite_credit_score"] is None, "null, not 0"
        assert summary["baseline_composite_credit_score"] is None
        assert summary["bureau_count"] == 3, "the TRI plan provisioned three profiles"
        assert summary["scored_bureau_count"] == 0, "none of them has reported"
        assert summary["monitoring_status"] == "PENDING_DATA"

    def test_risk_variants_sit_at_ten_while_no_bureau_has_reported(self, api):
        """PRD §3.1: "Finally, both risk variants are computed for the first time; with no alerts
        on file, they land at `risk_score` of 10 and `underwriting_risk_score` of 10."
        PRD §3.3: "If that set is empty, the composite is null (not zero) and the subscriber's
        monitoring dimension stays at `PENDING_DATA`."

        Design: Difficulty/boundary_precision_check/credit_summary_empty_scored_set_is_null_not_zero
        """
        _, subscriber = create_verified_subscriber(full_name="Ione Wren", ssn_last4="5678")

        summary = get_credit_summary(subscriber["id"])
        assert summary["risk_score"] == 10
        assert summary["underwriting_risk_score"] == 10

        row = get_subscriber(subscriber["id"])
        assert row["composite_credit_score"] is None, (
            "the score-drop term cannot fire without a composite"
        )
        assert row["risk_score"] == 10
        assert row["underwriting_risk_score"] == 10


class TestLogicalClockAndScorePulls:
    def test_first_score_refresh_stamps_the_startup_clock(self, api):
        """PRD §2.4: "The server keeps a single logical clock whose value at startup is exactly
        `2026-05-01T00:00:00Z`, and an administrator may move it forward or backward by supplying a
        `to_iso8601` instant; the endpoint answers with the resulting `current_utc`."
        PRD §3.3: "The monitoring feed pushes a fresh pull by supplying a `credit_score`, which must
        be an integer between 300 and 850 inclusive. The profile records the score and stamps
        `score_pulled_at` with the logical clock."

        Design: Corner/endpoints/clock_startup_default_is_2026_05_01
        """
        _, subscriber = create_verified_subscriber(full_name="Clock Default", ssn_last4="4646")
        equifax = get_bureau_profiles(subscriber["id"])[0]

        refreshed = score_refresh(equifax["id"], 710)
        assert_instant_equals(
            refreshed["score_pulled_at"], "2026-05-01T00:00:00Z", "score_pulled_at"
        )
        assert refreshed["credit_score"] == 710

        after = get_subscriber(subscriber["id"])
        assert after["composite_credit_score"] == 710
        assert after["monitoring_status"] == "MONITORED"

    def test_score_refresh_on_an_unknown_bureau_profile_is_not_found(self, api, admin_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."

        Design: Corner/errors/bureau_profile_score_refresh_on_unknown_profile_not_found
        """
        resp = api.score_refresh(
            "abababab-cdcd-4efe-8f0f-101010101010", {"credit_score": 700}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_BUREAU_PROFILE_NOT_FOUND)


class TestThawWindows:
    """Closed intervals with a capacity of one — adjacency is collision."""

    def test_window_touching_the_previous_windows_end_collides(self, api):
        """PRD §3.3: "Thaw windows are **closed intervals with a capacity of one**: a new window
        collides with an existing window on the same profile whenever the new window's start is at
        or before the existing window's end *and* the existing window's start is at or before the
        new window's end. Windows that merely touch at an endpoint — the new one beginning at the
        exact instant the old one ends — therefore *do* collide, and the booking is rejected with
        `ERR_THAW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/thaw_window_closed_interval_touching_endpoint_collides
        """
        ctx = setup_frozen_equifax_profile()
        subscriber, equifax = ctx["subscriber"], ctx["equifax"]
        sub_headers = make_subscriber_headers(subscriber["id"])

        first = create_thaw_window(
            equifax["id"],
            subscriber["id"],
            "2026-06-01T09:00:00Z",
            "2026-06-01T12:00:00Z",
            purpose="MORTGAGE_APPLICATION",
        )
        assert_thaw_window(first)

        resp = api.create_thaw_window(
            equifax["id"],
            create_thaw_window_payload(
                "2026-06-01T12:00:00Z", "2026-06-01T15:00:00Z", purpose="AUTO_LOAN"
            ),
            sub_headers,
        )
        validate_error(resp, ApiErrorId.ERR_THAW_WINDOW_OVERLAP)

        windows, _ = validate_paginated(api.list_thaw_windows(equifax["id"], sub_headers))
        assert len(windows) == 1 and windows[0]["id"] == first["id"]

        profile = validate_success(
            api.get_bureau_profile(equifax["id"], sub_headers)
        )
        assert profile["freeze_status"] == "FROZEN"

    def test_window_starting_one_second_after_the_previous_end_is_accepted(self, api):
        """PRD §3.3: "Thaw windows are **closed intervals with a capacity of one**: a new window
        collides with an existing window on the same profile whenever the new window's start is at
        or before the existing window's end *and* the existing window's start is at or before the
        new window's end."

        Design: Difficulty/resource_temporal_overlap/thaw_window_closed_interval_touching_endpoint_collides
        """
        ctx = setup_frozen_equifax_profile()
        subscriber, equifax = ctx["subscriber"], ctx["equifax"]
        sub_headers = make_subscriber_headers(subscriber["id"])

        create_thaw_window(
            equifax["id"], subscriber["id"], "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z"
        )

        resp = api.create_thaw_window(
            equifax["id"],
            create_thaw_window_payload(
                "2026-06-01T12:00:01Z", "2026-06-01T15:00:00Z", purpose="AUTO_LOAN"
            ),
            sub_headers,
        )
        second = validate_success(resp, 201)
        assert_thaw_window(second)

        windows, meta = validate_paginated(api.list_thaw_windows(equifax["id"], sub_headers))
        assert meta["total_count"] == 2, "a one-second gap clears the closed interval"
        assert windows[1]["id"] == second["id"], "windows are ordered by window_start ascending"

    def test_window_end_not_after_window_start_is_rejected(self, api):
        """PRD §3.3: "`window_end` must be strictly later than `window_start`, or the request fails
        with `ERR_INVALID_WINDOW`; and `window_start` may not precede the logical clock — a start
        exactly at the current logical instant is acceptable, anything earlier fails with
        `ERR_WINDOW_IN_PAST`."

        Design: Corner/validations/thaw_window_end_before_start_returns_invalid_window
        """
        ctx = setup_frozen_equifax_profile()
        subscriber, equifax = ctx["subscriber"], ctx["equifax"]
        sub_headers = make_subscriber_headers(subscriber["id"])

        resp = api.create_thaw_window(
            equifax["id"],
            create_thaw_window_payload(
                "2026-06-10T12:00:00Z", "2026-06-10T12:00:00Z", purpose="CAR_LOAN"
            ),
            sub_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

        windows, _ = validate_paginated(api.list_thaw_windows(equifax["id"], sub_headers))
        assert windows == []

    def test_window_starting_before_the_logical_clock_is_rejected(self, api):
        """PRD §3.3: "`window_end` must be strictly later than `window_start`, or the request fails
        with `ERR_INVALID_WINDOW`; and `window_start` may not precede the logical clock — a start
        exactly at the current logical instant is acceptable, anything earlier fails with
        `ERR_WINDOW_IN_PAST`."

        Design: Corner/validations/thaw_window_start_before_logical_clock_returns_window_in_past
        """
        ctx = setup_frozen_equifax_profile()
        subscriber, equifax = ctx["subscriber"], ctx["equifax"]
        sub_headers = make_subscriber_headers(subscriber["id"])

        set_clock("2026-07-01T00:00:00Z")

        resp = api.create_thaw_window(
            equifax["id"],
            create_thaw_window_payload(
                "2026-06-30T09:00:00Z", "2026-06-30T17:00:00Z", purpose="BACKDATED"
            ),
            sub_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)

        windows, _ = validate_paginated(api.list_thaw_windows(equifax["id"], sub_headers))
        assert windows == []