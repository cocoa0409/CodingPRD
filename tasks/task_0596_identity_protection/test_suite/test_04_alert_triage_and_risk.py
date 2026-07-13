"""Lost-wallet assist, alert triage, and the two identity risk numbers (PRD §3.4, §3.5)."""

from test_helpers import (
    ApiErrorId,
    acknowledge_alert,
    assert_alert,
    assert_instant_equals,
    assert_wallet_item,
    create_alert,
    create_family_member,
    create_verified_subscriber,
    create_wallet_item,
    get_bureau_profiles,
    get_case,
    get_subscriber,
    list_cases,
    make_subscriber_headers,
    set_clock,
    setup_escalation_ready,
    setup_mixed_alert_set,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLostWalletAssist:
    def test_reporting_an_ssn_card_lost_raises_an_alert_and_fires_freeze_assist(self, api):
        """PRD §3.4: "The item moves `ACTIVE → REPORTED_LOST` and stamps `reported_lost_at` with
        the logical clock; reporting an item that is already `REPORTED_LOST` is `ERR_INVALID_STATE`,
        and the owning subscriber must be `ACTIVE`."
        PRD §3.4: "The alert's classification depends on what was lost: an `SSN_CARD` produces an
        `alert_type` of `SSN_TRACE` at `CRITICAL` severity; a `CREDIT_CARD` or `DEBIT_CARD` produces
        an `ACCOUNT_TAKEOVER` alert at `HIGH` severity; anything else — a driver's licence, a
        passport, an insurance card — produces a `DARK_WEB` alert at `MEDIUM` severity."
        PRD §3.4: "Every bureau profile of that subscriber whose `freeze_status` is `UNFROZEN` is
        moved to `FREEZE_PENDING`, each such profile incrementing its own `version` by one, exactly
        as though the subscriber had requested each freeze by hand."

        Design: Corner/state_machines/wallet_report_lost_ssn_card_cascades_alert_and_freeze_requests
        """
        set_clock("2026-05-05T08:00:00Z")
        _, subscriber = create_verified_subscriber(full_name="Lost Wallet", ssn_last4="1717")
        sub_headers = make_subscriber_headers(subscriber["id"])
        item = create_wallet_item(
            subscriber["id"], item_type="SSN_CARD", issuer="SSA", last4="1717"
        )

        reported = validate_success(api.report_wallet_item_lost(item["id"], sub_headers))
        assert_wallet_item(reported)
        assert reported["status"] == "REPORTED_LOST"
        assert_instant_equals(
            reported["reported_lost_at"], "2026-05-05T08:00:00Z", "reported_lost_at"
        )

        alerts, _ = validate_paginated(
            api.list_alerts(sub_headers, params={"subscriber_id": subscriber["id"]})
        )
        assert len(alerts) == 1, "exactly one alert is raised by the report"
        raised = alerts[0]
        assert raised["alert_type"] == "SSN_TRACE"
        assert raised["severity"] == "CRITICAL"
        assert raised["status"] == "NEW"

        profiles = get_bureau_profiles(subscriber["id"])
        assert len(profiles) == 3
        assert all(p["freeze_status"] == "FREEZE_PENDING" for p in profiles), (
            "freeze assist moved every UNFROZEN bureau file to FREEZE_PENDING"
        )

        after = get_subscriber(subscriber["id"])
        assert after["risk_score"] == 10, "a NEW SSN_TRACE counts in neither variant"
        assert after["underwriting_risk_score"] == 10

    def test_report_lost_on_an_unknown_wallet_item_is_not_found(self, api, admin_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."

        Design: Corner/errors/report_lost_on_unknown_wallet_item_not_found
        """
        resp = api.report_wallet_item_lost(
            "12121212-3434-4565-8787-909090909090", admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_WALLET_ITEM_NOT_FOUND)


class TestAlertTriageTransitions:
    def test_acknowledging_an_already_acknowledged_alert_is_rejected(self, api, admin_headers):
        """PRD §3.5: "Triage is the subscriber's job. They **acknowledge** a `NEW` alert, moving it
        `NEW → ACKNOWLEDGED`."
        PRD §3.5: "Attempting a triage transition from the wrong state — dismissing a `NEW` alert,
        escalating one that was never confirmed — is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/alert_acknowledge_twice_second_call_rejected
        """
        _, subscriber = create_verified_subscriber(full_name="Ack Twice", ssn_last4="9999")
        alert = create_alert(
            subscriber["id"],
            alert_type="DARK_WEB",
            severity="LOW",
            source_detail="paste site",
        )
        acknowledge_alert(alert["id"])

        resp = api.acknowledge_alert(alert["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_alert(alert["id"], admin_headers))
        assert after["status"] == "ACKNOWLEDGED"

        subscriber_after = get_subscriber(subscriber["id"])
        assert subscriber_after["risk_score"] == 25, (
            "10 base + 15 for the acknowledged DARK_WEB hit, counted exactly once"
        )

    def test_confirming_fraud_on_a_new_alert_is_rejected(self, api, admin_headers):
        """PRD §3.5: "Down the first branch, the subscriber **confirms the alert as fraud**, moving
        it `ACKNOWLEDGED → CONFIRMED_FRAUD`."
        PRD §3.5: "Attempting a triage transition from the wrong state — dismissing a `NEW` alert,
        escalating one that was never confirmed — is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/alert_confirm_fraud_from_new_rejected
        """
        _, subscriber = create_verified_subscriber(full_name="Skip Ack", ssn_last4="1212")
        alert = create_alert(
            subscriber["id"],
            alert_type="SSN_TRACE",
            severity="HIGH",
            source_detail="SSN trace",
        )
        assert alert["status"] == "NEW"

        resp = api.confirm_fraud_alert(alert["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_alert(alert["id"], admin_headers))
        assert after["status"] == "NEW"
        assert list_cases(subscriber_id=subscriber["id"]) == [], (
            "no restoration case was opened by the rejected transition"
        )

    def test_dismissing_an_alert_opens_no_case_and_drops_its_risk_contribution(self, api):
        """PRD §3.5: "Down the second branch, the subscriber **dismisses the alert** as a false
        positive, supplying a `dismissal_reason` which is recorded on the alert, and moving it
        `ACKNOWLEDGED → DISMISSED`. No restoration case is created — none, ever, on this branch —
        and a `DISMISSED` alert contributes nothing to either risk variant from that moment on.
        `DISMISSED` is terminal."

        Design: Corner/state_machines/alert_dismiss_branch_creates_no_case_and_drops_risk_contribution
        """
        _, subscriber = create_verified_subscriber(full_name="Di Smiss", ssn_last4="1313")
        alert = create_alert(
            subscriber["id"],
            alert_type="DARK_WEB",
            severity="LOW",
            source_detail="old password in dump",
        )
        acknowledge_alert(alert["id"])
        assert get_subscriber(subscriber["id"])["risk_score"] == 25

        dismissed = validate_success(
            api.dismiss_alert(
                alert["id"],
                {"dismissal_reason": "Password already rotated years ago"},
                make_subscriber_headers(subscriber["id"]),
            )
        )
        assert_alert(dismissed)
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["dismissal_reason"] == "Password already rotated years ago"

        assert list_cases(subscriber_id=subscriber["id"]) == [], (
            "the dismiss branch never opens a restoration case"
        )
        after = get_subscriber(subscriber["id"])
        assert after["risk_score"] == 10, "a DISMISSED alert contributes nothing"
        assert after["underwriting_risk_score"] == 10

    def test_acknowledging_an_unknown_alert_is_not_found(self, api, admin_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."

        Design: Corner/errors/alert_acknowledge_on_unknown_alert_not_found
        """
        resp = api.acknowledge_alert("56565656-7878-4989-8a9a-b0b0b0b0b0b0", admin_headers)
        validate_error(resp, ApiErrorId.ERR_ALERT_NOT_FOUND)


class TestAlertListing:
    def test_alert_listing_pages_and_reports_the_pagination_envelope(self, api, admin_headers):
        """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and `has_more`
        inside the envelope's `meta` object. `total_count` counts the rows matching the filter
        *before* the page window is applied; `has_more` is true when rows remain beyond the current
        window."
        PRD §2.3: "Unless a specific listing states otherwise, list results are ordered by the
        resource's creation timestamp ascending."

        Design: Corner/entities/alerts_list_returns_pagination_envelope
        """
        _, subscriber = create_verified_subscriber(full_name="Page Lister", ssn_last4="8888")
        for detail in ("one", "two", "three"):
            create_alert(
                subscriber["id"],
                alert_type="DARK_WEB",
                severity="LOW",
                source_detail=detail,
            )

        resp = api.list_alerts(
            admin_headers,
            params={"subscriber_id": subscriber["id"], "limit": 2, "offset": 0},
        )
        assert resp.json()["response_type"] == "array"
        alerts, meta = validate_paginated(resp)

        assert len(alerts) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert [a["source_detail"] for a in alerts] == ["one", "two"], (
            "alerts are ordered by created_at ascending"
        )

    def test_alerts_can_be_filtered_down_to_a_single_dependent(self, api, admin_headers):
        """PRD §3.5: "Alerts are listable with filters on `subscriber_id`, `family_member_id` and
        `status`."
        PRD §3.5: "The monitoring feed ingests an **Alert** by naming the `subscriber_id` it
        concerns, optionally a `family_member_id` when the signal is about a dependent rather than
        the account holder, an `alert_type` of `DARK_WEB`, `SSN_TRACE`, `ACCOUNT_TAKEOVER` or
        `CREDIT_INQUIRY`, a `severity` of `LOW`, `MEDIUM`, `HIGH` or `CRITICAL`, and a
        `source_detail` recording where the signal came from — a breach name, a creditor's name, or
        the wallet-item reference described in §3.4."

        Design: Corner/endpoints/alerts_filtered_by_family_member_id
        """
        _, subscriber = create_verified_subscriber(
            plan_overrides={"child_monitoring_included": True, "max_family_members": 4},
            full_name="Filter Test",
            ssn_last4="4747",
        )
        child = create_family_member(
            subscriber["id"], full_name="Filter Kid", ssn_last4="4848", relationship="CHILD"
        )
        adult_alert = create_alert(
            subscriber["id"],
            alert_type="DARK_WEB",
            severity="LOW",
            source_detail="adult alert",
        )
        child_alert = create_alert(
            subscriber["id"],
            family_member_id=child["id"],
            alert_type="SSN_TRACE",
            severity="HIGH",
            source_detail="child alert",
        )

        filtered, meta = validate_paginated(
            api.list_alerts(admin_headers, params={"family_member_id": child["id"]})
        )
        assert meta["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["id"] == child_alert["id"]
        assert adult_alert["id"] not in [a["id"] for a in filtered]

        everything, all_meta = validate_paginated(
            api.list_alerts(admin_headers, params={"subscriber_id": subscriber["id"]})
        )
        assert all_meta["total_count"] == 2


class TestDualRiskVariants:
    """LIVE and UNDERWRITING diverge over one and the same alert set."""

    def test_credit_summary_reports_both_variants_diverging_in_one_response(self, api):
        """PRD §3.5: "It counts signals early: a `CREDIT_INQUIRY` counts from the moment it is
        ingested, that is in `NEW`, `ACKNOWLEDGED`, `CONFIRMED_FRAUD` or `ESCALATED`; a `DARK_WEB`
        hit begins counting once the subscriber acknowledges it, that is in `ACKNOWLEDGED`,
        `CONFIRMED_FRAUD` or `ESCALATED`; while `SSN_TRACE` and `ACCOUNT_TAKEOVER` count only in
        `CONFIRMED_FRAUD` or `ESCALATED`."
        PRD §3.5: "It counts *only* alerts the subscriber has actually confirmed as fraud —
        `CONFIRMED_FRAUD` or `ESCALATED` — and it applies that rule uniformly to all four alert
        types, so a `NEW` credit inquiry and an `ACKNOWLEDGED` dark-web hit are simply invisible to
        it. It never applies the family-child multiplier."

        Design: Difficulty/dual_variant_calc/live_vs_underwriting_risk_diverge_on_identical_alert_set
        """
        ctx = setup_mixed_alert_set()
        subscriber = ctx["subscriber"]

        summary = validate_success(
            api.get_credit_summary(
                subscriber["id"], make_subscriber_headers(subscriber["id"])
            )
        )
        # LIVE: 10 base + 25 (confirmed SSN_TRACE) + 15 (acknowledged DARK_WEB) + 8 (NEW inquiry)
        assert summary["risk_score"] == 58
        # UNDERWRITING: 10 base + 25 (confirmed SSN_TRACE) only
        assert summary["underwriting_risk_score"] == 35
        assert summary["risk_score"] != summary["underwriting_risk_score"], (
            "the two variants diverge in one and the same response body"
        )
        assert summary["composite_credit_score"] is None, "no bureau has reported a score"

    def test_subscriber_row_carries_the_same_two_divergent_variants(self, api):
        """PRD §3.5: "The **LIVE** variant is the consumer-facing "how exposed are you right now"
        number, written to `risk_score`."
        PRD §3.5: "The **UNDERWRITING** variant, written to `underwriting_risk_score`, is the number
        the insurance benefit is underwritten against."
        PRD §3.5: "On identical data, whenever any alert sits in `NEW` or `ACKNOWLEDGED`, the
        underwriting number is strictly the lower of the two."

        Design: Difficulty/dual_variant_calc/live_vs_underwriting_risk_diverge_on_identical_alert_set
        """
        ctx = setup_mixed_alert_set()

        row = get_subscriber(ctx["subscriber"]["id"])
        assert row["risk_score"] == 58
        assert row["underwriting_risk_score"] == 35
        assert row["underwriting_risk_score"] < row["risk_score"], (
            "NEW and ACKNOWLEDGED alerts exist, so UNDERWRITING is strictly lower"
        )


class TestEscalationPinnedOrder:
    """The escalation tier is read from the risk snapshot taken before the transition."""

    def test_escalation_tier_comes_from_the_pre_transition_risk_snapshot(self, api, admin_headers):
        """PRD §3.5: "First, snapshot the subscriber's `risk_score` exactly as it is persisted
        *before* this request mutates anything. Second, derive the tier from that snapshot alone:
        the tier is `TIER3` if the snapshot is at least 70 or the alert's `severity` is `CRITICAL`;
        otherwise it is `TIER2` if the snapshot is at least 40 or the alert's `severity` is `HIGH`;
        otherwise it is `TIER1`. Third, persist the transition — the alert's `status` becomes
        `ESCALATED`, `escalation_tier` is written, and `escalation_deadline` is set to the logical
        clock advanced by the tier's service-level allowance: seventy-two hours for a `TIER1`
        escalation, twenty-four hours for `TIER2`, and just four hours for `TIER3`."

        Design: Difficulty/combinatorial_formula/escalation_tier_pinned_to_pre_transition_risk_snapshot
        """
        ctx = setup_escalation_ready()
        assert ctx["subscriber"]["risk_score"] == 63, "the pre-transition snapshot is 63"

        escalated = validate_success(
            api.escalate_alert(ctx["ssn_alert"]["id"], admin_headers)
        )
        assert_alert(escalated)
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_tier"] == "TIER2", (
            "the tier reads the pre-transition 63, not the post-transition 73"
        )
        assert_instant_equals(
            escalated["escalation_deadline"],
            "2026-06-02T00:00:00Z",
            "escalation_deadline",
        )

    def test_escalation_recomputes_risk_afterwards_and_lifts_the_case_tier_floor(
        self, api, admin_headers
    ):
        """PRD §3.5: "Fourth, and only now, recompute both risk variants — the alert has become
        `ESCALATED`, so the escalation weight now enters the sum."
        PRD §3.5: "Next, add 10 points for every one of the subscriber's alerts — of any type —
        currently in `ESCALATED`; an escalated alert therefore contributes both its type weight and
        this escalation weight."
        PRD §3.6: "Escalation revisits this: when an alert is escalated, the origin case's
        `required_specialist_tier` is raised to whichever has the higher rank between the
        newly-chosen `escalation_tier` and whatever the case already required — the floor only ever
        goes up, never down."

        Design: Difficulty/combinatorial_formula/escalation_tier_pinned_to_pre_transition_risk_snapshot
        """
        ctx = setup_escalation_ready()
        assert ctx["ssn_case"]["required_specialist_tier"] == "TIER1", (
            "a MEDIUM alert on a TIER1-floor plan opens a TIER1 case"
        )

        validate_success(api.escalate_alert(ctx["ssn_alert"]["id"], admin_headers))

        after = get_subscriber(ctx["subscriber"]["id"])
        assert after["risk_score"] == 73, "63 + the 10-point escalation weight"
        assert after["underwriting_risk_score"] == 65, "10 + 25 + 20 + the escalation weight"

        case = get_case(ctx["ssn_case"]["id"])
        assert case["required_specialist_tier"] == "TIER2", (
            "the case floor is lifted to the newly-chosen escalation tier"
        )