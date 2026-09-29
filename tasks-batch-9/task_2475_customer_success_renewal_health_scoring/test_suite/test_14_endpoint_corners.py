"""Endpoint corners: amendment, recompute, projection and rejected writes.

Each test below drives one endpoint of PRD §4 to a state the endpoint's own
prose fixes exactly, and asserts the derived fields the PRD names rather than
the fields the request supplied.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    BASELINE_HEALTH_SCORE,
    EXECUTIVE_HEADERS,
    HEALTH_AMBER,
    HEALTH_RED,
    LIFECYCLE_ONBOARDING,
    LIKELIHOOD_AT_RISK,
    OPPORTUNITY_ACTION_HANDOFF,
    OPPORTUNITY_IDENTIFIED,
    OPS_ADMIN_HEADERS,
    SEGMENT_ENTERPRISE,
    SEVERITY_MEDIUM,
    SEVERITY_S1,
    SOURCE_EXEC_REQUEST,
    TIER_UNASSIGNED,
    add_support_signal,
    assert_common_fields,
    assert_field,
    assert_fields,
    assert_null,
    assert_ok,
    assert_page,
    assert_score,
    assert_scores,
    build_trending_account,
    create_account,
    create_csm,
    factories,
    identify_opportunity,
    make_csm_headers,
    read_account,
    read_health_summary,
    read_opportunity,
    read_signal,
    recompute_health,
    set_clock,
    validate_error,
)


class TestAccountAmendment:
    """PATCH /accounts/{id} writes the supplied commercial facts and nothing else."""

    def test_patch_updates_arr_and_bumps_version(self, api: ApiClient) -> None:
        """Amending name and arr_cents bumps version to 2 and leaves tier and health alone.

        PRD §3.1: "Commercial facts drift, and CS operations may amend `name`, `arr_cents`, `segment_band` or `contract_end_date` on an existing account."
        PRD §3.1: "Changing `arr_cents` or `segment_band` leaves `coverage_tier` exactly as it was — re-tiering happens only when a segmentation run is requested, never as a side effect of an edit."
        PRD §3.1: "Its `reference_calls_cap` is derived from the commercial band immediately: an `ENTERPRISE` account may support 6 reference calls per advocacy enrollment, a `MIDMARKET` account 4, and an `SMB` account 2."
        PRD §3.1: "Because a freshly registered account has no usage, no tickets, no sponsors and no goals, this deterministic first pass always produces `adoption_index` 0.00, `support_risk_penalty` 0.00, `exec_engagement_score` 25.00, `outcome_attainment_index` 60.00, `snapshot_health_score` and `trended_health_score` both 43.75, `health_tier` `RED`, `renewal_likelihood` `AT_RISK` and `coverage_posture` `RESTRICTED`."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation."

        Design: Corner/endpoints/patch_account_updates_arr_and_bumps_version
        """
        account = create_account(api)
        assert_common_fields(account, expected_version=1)

        patched = assert_ok(
            api.patch_account(
                account["id"],
                factories.account_patch(
                    name="Northwind Traders GmbH", arr_cents=40_000_000
                ),
                OPS_ADMIN_HEADERS,
            )
        )

        assert_fields(
            patched,
            {
                "name": "Northwind Traders GmbH",
                "arr_cents": 40_000_000,
                "segment_band": SEGMENT_ENTERPRISE,
                "contract_end_date": "2026-12-31",
                "coverage_tier": TIER_UNASSIGNED,
                "reference_calls_cap": 6,
                "health_tier": HEALTH_RED,
            },
        )
        assert_common_fields(patched, expected_version=2)
        assert_score(
            patched["snapshot_health_score"],
            BASELINE_HEALTH_SCORE,
            "snapshot_health_score",
        )


class TestHealthRecompute:
    """POST /accounts/{id}/health-recompute re-reads every window against the clock."""

    def test_recompute_drops_a_ticket_that_aged_out_of_the_support_window(
        self, api: ApiClient
    ) -> None:
        """A ticket 109 days old leaves the trailing support window, lifting the snapshot to 73.85.

        PRD §3.2: "The input set is the account's support rows whose `opened_at` falls strictly after the instant 90 days before the logical clock and at or before the logical clock itself — a ticket opened exactly 90 days before the clock is outside the window, and one opened exactly at the clock is inside it."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.2: "Its `penalty_points` is an integer sum of three terms: a severity term worth 12 points for `S1`, 7 for `S2`, 3 for `S3` and 1 for `S4`; a further 5 points when `breached_sla` is true; and a further 4 points when `csat_score` is present and is at most 2."
        PRD §3.2: "Consider an account whose three usage rows read 36.00, 56.00 and 86.00 with 86.00 newest, and which has no sponsors, tickets or goals: its point-in-time adoption term is 86.00 giving a `snapshot_health_score` of 73.85, while its trailing adoption term is 67.00 giving a `trended_health_score` of 67.20."
        PRD §3.2: "Both score floors are inclusive; the day threshold is strict, so an account exactly 60 days from its term end is not `UPSIDE`."

        Design: Corner/endpoints/health_recompute_drops_a_ticket_that_aged_out_of_the_support_window
        """
        state = build_trending_account(api)
        ticket = add_support_signal(
            api,
            state["account_id"],
            state["csm_id"],
            "2026-07-15T09:00:00Z",
            SEVERITY_S1,
            resolved_at="2026-07-18T09:00:00Z",
        )
        assert_field(ticket, "penalty_points", 12)

        set_clock(api, "2026-11-01T00:00:00Z")
        account = recompute_health(api, state["account_id"])

        assert_scores(
            account,
            {
                "support_risk_penalty": 0.00,
                "adoption_index": 67.00,
                "snapshot_health_score": 73.85,
                "trended_health_score": 67.20,
            },
        )
        assert_fields(
            account,
            {
                "health_tier": HEALTH_AMBER,
                "renewal_likelihood": LIKELIHOOD_AT_RISK,
                "lifecycle_state": LIFECYCLE_ONBOARDING,
            },
        )
        # The signal row itself is untouched; only the window moved past it.
        assert_field(read_signal(api, state["account_id"], ticket["id"]), "penalty_points", 12)
        summary = read_health_summary(api, state["account_id"])
        assert_score(summary["support_component"], 100.00, "support_component")


class TestHealthSummary:
    """GET /accounts/{id}/health-summary exposes the model's internals side by side."""

    def test_summary_returns_every_component_for_a_fresh_account(
        self, api: ApiClient
    ) -> None:
        """A registered account with no signals projects 0.00 / 100.00 / 25.00 / 60.00 / 43.75.

        PRD §3.2: "For inspection there is a read-only health projection that adds no state of its own and exposes the model's internals side by side: `adoption_index`, `support_component` (the complement of `support_risk_penalty`), `exec_engagement_score`, `outcome_attainment_index`, `snapshot_health_score`, `trended_health_score`, `variant_delta` (the point-in-time figure minus the trailing figure), `health_tier`, and `usage_rows_considered` (the number of usage rows the adoption calculation actually used, which is the smaller of 3 and the account's usage-row count)."
        PRD §3.1: "Because a freshly registered account has no usage, no tickets, no sponsors and no goals, this deterministic first pass always produces `adoption_index` 0.00, `support_risk_penalty` 0.00, `exec_engagement_score` 25.00, `outcome_attainment_index` 60.00, `snapshot_health_score` and `trended_health_score` both 43.75, `health_tier` `RED`, `renewal_likelihood` `AT_RISK` and `coverage_posture` `RESTRICTED`."

        Design: Corner/endpoints/health_summary_returns_every_component_for_a_fresh_account
        """
        account = create_account(api)

        summary = assert_ok(api.get_health_summary(account["id"], EXECUTIVE_HEADERS))

        assert_scores(
            summary,
            {
                "adoption_index": 0.00,
                "support_component": 100.00,
                "exec_engagement_score": 25.00,
                "outcome_attainment_index": 60.00,
                "snapshot_health_score": 43.75,
                "trended_health_score": 43.75,
                "variant_delta": 0.00,
            },
        )
        assert_fields(summary, {"health_tier": HEALTH_RED, "usage_rows_considered": 0})


class TestExpansionHandoffSchema:
    """HANDOFF is the one opportunity action that requires handoff_ae_user_id."""

    def test_handoff_without_an_ae_user_id_returns_invalid_request(
        self, api: ApiClient
    ) -> None:
        """The missing conditional field is caught before the posture and qualification gates.

        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §2.9: "This rule also carries the conditional requirements: a `CHURN` lifecycle action requires `churn_root_cause_code`, `WIN_BACK_TARGET` requires `win_back_offer_bp`, `REACTIVATE` requires `new_contract_end_date`, a `HANDOFF` expansion action requires `handoff_ae_user_id`, a `REJECT` expansion action requires `rejection_reason`, and a `COMPLETE` milestone action requires `completed_date`."
        PRD §3.7: "A revenue term is the account's `arr_cents` divided by a normaliser of 50,000,000, multiplied by 100, rounded half up to two decimal places and then capped at 100.00 — so an account at or above 500,000 dollars of ARR saturates that term."
        PRD §3.7: "The score is 0.50 of the account's `trended_health_score`, plus 0.30 of its `adoption_index`, plus 0.20 of the revenue term, rounded half up to two decimal places."

        Design: Corner/endpoints/expansion_handoff_without_an_ae_user_id_returns_invalid_request
        """
        csm = create_csm(api)
        account = create_account(api, name="Fresh Signal Co")
        opportunity = identify_opportunity(
            api,
            account["id"],
            csm["id"],
            estimated_value_cents=2_500_000,
            source_signal=SOURCE_EXEC_REQUEST,
        )
        # 0.50 x 43.75 + 0.30 x 0.00 + 0.20 x 60.00 = 33.875, rounded half up.
        assert_score(
            opportunity["qualification_score"], 33.88, "qualification_score"
        )

        response = api.transition_expansion_opportunity(
            opportunity["id"],
            factories.opportunity_transition(OPPORTUNITY_ACTION_HANDOFF),
            make_csm_headers(csm["id"]),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST)
        unchanged = read_opportunity(api, opportunity["id"])
        assert_field(unchanged, "state", OPPORTUNITY_IDENTIFIED)
        assert_null(unchanged, "handoff_ae_user_id")


class TestEscalationCaseBodyReferences:
    """POST /escalation-cases resolves its body foreign keys before any domain rule."""

    def test_unknown_save_play_returns_save_play_not_found(self, api: ApiClient) -> None:
        """A live account paired with a dangling save_play_id yields the save-play 404.

        PRD §2.9: "Every entity referenced by a request-body foreign key exists — `account_id`, `csm_id`, `sponsor_contact_id`, `save_play_id` and `owner_csm_id`."
        PRD §2.9: "Every write endpoint evaluates the rules below **in ascending order** and returns the error of the **first** rule that is violated."
        PRD §3.5: "The referenced play must belong to the same account as the case; a play from another account is refused with `ERR_CROSS_ACCOUNT_REFERENCE`."

        Design: Corner/endpoints/escalation_case_with_an_unknown_save_play_returns_save_play_not_found
        """
        csm = create_csm(api)
        account = create_account(api)

        response = api.create_escalation_case(
            factories.escalation_case(
                account["id"],
                NON_EXISTENT_UUID,
                severity=SEVERITY_MEDIUM,
                summary="Dangling save play reference",
            ),
            make_csm_headers(csm["id"]),
        )

        validate_error(response, ApiErrorId.SAVE_PLAY_NOT_FOUND)
        assert_page(
            api.list_escalation_cases(
                OPS_ADMIN_HEADERS, {"account_id": account["id"]}
            ),
            expected_total=0,
        )
        assert_field(read_account(api, account["id"]), "open_save_play_count", 0)
