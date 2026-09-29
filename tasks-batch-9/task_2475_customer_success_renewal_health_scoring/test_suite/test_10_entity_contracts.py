"""Entity-level contract checks: field surface, defaults, computed values and
the 404 / 400 / 422 refusals that guard a create or a read.
"""

from test_helpers import (
    BASELINE_ADOPTION_INDEX,
    BASELINE_EXEC_ENGAGEMENT_SCORE,
    BASELINE_HEALTH_SCORE,
    BASELINE_OUTCOME_ATTAINMENT_INDEX,
    BASELINE_SUPPORT_RISK_PENALTY,
    CSM_ACTIVE,
    HEALTH_RED,
    LIFECYCLE_ONBOARDING,
    LIKELIHOOD_AT_RISK,
    NON_EXISTENT_UUID,
    NORTHWIND,
    OPPORTUNITY_IDENTIFIED,
    OPS_ADMIN_HEADERS,
    PLAY_DRAFT,
    POSTURE_RESTRICTED,
    REFERENCE_CALLS_CAP_BY_BAND,
    SEGMENT_ENTERPRISE,
    SEVERITY_HIGH,
    TIER_HIGH_TOUCH,
    TIER_UNASSIGNED,
    ApiClient,
    assert_common_fields,
    assert_created,
    assert_fields,
    assert_null,
    assert_ok,
    assert_page,
    assert_present,
    assert_score,
    assert_scores,
    assert_signal_common_fields,
    create_account,
    create_csm,
    draft_save_play,
    factories,
    list_rows,
    make_csm_headers,
    read_account,
    read_save_play,
    read_signal,
    validate_error,
)

# The Account field surface PRD §3.1, §3.2, §2.4 and §2.8 declare together.
ACCOUNT_DECLARED_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "name",
    "arr_cents",
    "segment_band",
    "contract_start_date",
    "contract_end_date",
    "lifecycle_state",
    "coverage_tier",
    "coverage_posture",
    "assigned_csm_id",
    "health_tier",
    "renewal_likelihood",
    "adoption_index",
    "support_risk_penalty",
    "exec_engagement_score",
    "outcome_attainment_index",
    "snapshot_health_score",
    "trended_health_score",
    "open_save_play_count",
    "ttv_breach_flag",
    "contractual_ttv_days",
    "activation_ttv_days",
    "churn_root_cause_code",
    "win_back_offer_bp",
    "reference_calls_cap",
    "remediation_credit_outstanding_cents",
    "remediation_credit_settled_cents",
)


class TestAccountCreationContract:
    """The registration response: field surface, baseline, defaults and stamps."""

    def test_create_returns_every_declared_field_with_the_empty_signal_baseline(
        self, api: ApiClient, clock: str
    ) -> None:
        """Registration echoes the five inputs and the deterministic first health pass.

        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.1: "Because a freshly registered account has no usage, no tickets, no sponsors and no goals, this deterministic first pass always produces `adoption_index` 0.00, `support_risk_penalty` 0.00, `exec_engagement_score` 25.00, `outcome_attainment_index` 60.00, `snapshot_health_score` and `trended_health_score` both 43.75, `health_tier` `RED`, `renewal_likelihood` `AT_RISK` and `coverage_posture` `RESTRICTED`."
        PRD §3.1: "Its `reference_calls_cap` is derived from the commercial band immediately: an `ENTERPRISE` account may support 6 reference calls per advocacy enrollment, a `MIDMARKET` account 4, and an `SMB` account 2."

        Design: Corner/entities/account_create_returns_all_declared_fields_with_computed_baseline
        """
        data = assert_created(api.create_account(factories.account(), OPS_ADMIN_HEADERS))

        assert_present(data, *ACCOUNT_DECLARED_FIELDS)
        assert_fields(
            data,
            {
                "name": "Northwind Traders",
                "arr_cents": 30_000_000,
                "segment_band": SEGMENT_ENTERPRISE,
                "contract_start_date": "2026-01-01",
                "contract_end_date": "2026-12-31",
                "lifecycle_state": LIFECYCLE_ONBOARDING,
                "health_tier": HEALTH_RED,
                "renewal_likelihood": LIKELIHOOD_AT_RISK,
                "coverage_posture": POSTURE_RESTRICTED,
                "reference_calls_cap": REFERENCE_CALLS_CAP_BY_BAND[SEGMENT_ENTERPRISE],
            },
        )
        assert_scores(
            data,
            {
                "adoption_index": BASELINE_ADOPTION_INDEX,
                "support_risk_penalty": BASELINE_SUPPORT_RISK_PENALTY,
                "exec_engagement_score": BASELINE_EXEC_ENGAGEMENT_SCORE,
                "outcome_attainment_index": BASELINE_OUTCOME_ATTAINMENT_INDEX,
                "snapshot_health_score": BASELINE_HEALTH_SCORE,
                "trended_health_score": BASELINE_HEALTH_SCORE,
            },
        )

    def test_create_applies_the_declared_defaults_for_every_unsupplied_field(
        self, api: ApiClient, clock: str
    ) -> None:
        """None of the derived or system fields is client-supplied, yet all land on their defaults.

        PRD §3.1: "The account lands in `lifecycle_state` `ONBOARDING` with `coverage_tier` `UNASSIGNED`, `assigned_csm_id` null, `open_save_play_count` 0, `ttv_breach_flag` false, `contractual_ttv_days` and `activation_ttv_days` both null, `churn_root_cause_code` and `win_back_offer_bp` both null, and both credit counters — `remediation_credit_outstanding_cents` and `remediation_credit_settled_cents` — at 0."
        PRD §3.1: "Because a freshly registered account has no usage, no tickets, no sponsors and no goals, this deterministic first pass always produces `adoption_index` 0.00, `support_risk_penalty` 0.00, `exec_engagement_score` 25.00, `outcome_attainment_index` 60.00, `snapshot_health_score` and `trended_health_score` both 43.75, `health_tier` `RED`, `renewal_likelihood` `AT_RISK` and `coverage_posture` `RESTRICTED`."

        Design: Corner/entities/account_create_applies_declared_defaults_for_system_and_computed_fields
        """
        data = assert_created(
            api.create_account(
                factories.account(name="Default Probe"), OPS_ADMIN_HEADERS
            )
        )

        assert_fields(
            data,
            {
                "lifecycle_state": LIFECYCLE_ONBOARDING,
                "coverage_tier": TIER_UNASSIGNED,
                "coverage_posture": POSTURE_RESTRICTED,
                "renewal_likelihood": LIKELIHOOD_AT_RISK,
                "ttv_breach_flag": False,
                "open_save_play_count": 0,
                "remediation_credit_outstanding_cents": 0,
                "remediation_credit_settled_cents": 0,
            },
        )
        assert_null(
            data,
            "assigned_csm_id",
            "churn_root_cause_code",
            "win_back_offer_bp",
            "contractual_ttv_days",
            "activation_ttv_days",
        )

    def test_create_stamps_a_server_id_the_logical_clock_and_version_one(
        self, api: ApiClient, clock: str
    ) -> None:
        """`id`, `created_at`, `updated_at` and `version` are minted by the server.

        PRD §2.4: "Every resource the API mints carries an `id`: a server-generated UUID with no type prefix and no embedded semantics."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation."

        Design: Corner/entities/account_create_stamps_system_id_created_at_and_version_one
        """
        data = assert_created(
            api.create_account(
                factories.account(name="System Field Probe"), OPS_ADMIN_HEADERS
            )
        )
        # `created_at`/`updated_at` are asserted for shape only: PRD §2.4 fixes them
        # as "an ISO 8601 UTC timestamp with three fractional digits" without naming
        # the clock they are drawn from, so their instant is not pinned here.
        assert_common_fields(data, expected_version=1)

        reread = assert_ok(api.get_account(data["id"], OPS_ADMIN_HEADERS))
        assert_fields(
            reread,
            {
                "id": data["id"],
                "created_at": data["created_at"],
                "version": 1,
            },
        )

    def test_create_with_an_off_enum_segment_band_is_refused_and_writes_nothing(
        self, api: ApiClient
    ) -> None:
        """`MIDMARKETT` is outside the declared band set, so the intake is malformed.

        PRD §3.1: "The intake payload carries the customer's `name` (between 1 and 120 characters), its `arr_cents` (annual recurring revenue in integer cents, zero or greater), its commercial `segment_band` — one of `ENTERPRISE`, `MIDMARKET` or `SMB` — and the two calendar dates bounding the current term, `contract_start_date` and `contract_end_date`."
        PRD §2.9: "All required body fields are present; enum values are drawn from their declared sets; integers are non-negative wherever this document says so; calendar dates are ISO `YYYY-MM-DD` and instants are ISO 8601 UTC; `limit` is between 1 and 100 inclusive; `offset` is at least 0."

        Design: Corner/entities/account_create_with_invalid_segment_band_returns_invalid_request
        """
        validate_error(
            api.create_account(
                factories.account(name="Bad Enum", segment_band="MIDMARKETT"),
                OPS_ADMIN_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            expected_status=400,
        )
        assert_page(api.list_accounts(OPS_ADMIN_HEADERS), expected_total=0)


class TestCsmRetrievalContract:
    """The manager row as stored on creation."""

    def test_get_returns_the_stored_capacity_row(self, api: ApiClient) -> None:
        """A manager with no assignments reads 0 committed and a full available figure.

        PRD §3.4: "On creation `capacity_units_committed` is 0, `capacity_units_available` equals `capacity_units_total`, and `status` is `ACTIVE`."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation."

        Design: Corner/entities/csm_get_returns_the_stored_capacity_row
        """
        created = create_csm(
            api,
            full_name="Ada Lovelace",
            coverage_specialty=TIER_HIGH_TOUCH,
            capacity_units_total=40,
        )

        data = assert_ok(api.get_csm(created["id"], OPS_ADMIN_HEADERS))
        assert_fields(
            data,
            {
                "id": created["id"],
                "full_name": "Ada Lovelace",
                "coverage_specialty": TIER_HIGH_TOUCH,
                "capacity_units_total": 40,
                "capacity_units_committed": 0,
                "capacity_units_available": 40,
                "status": CSM_ACTIVE,
                "version": 1,
            },
        )


class TestAccountListingEnvelope:
    """The pagination block a collection endpoint returns."""

    def test_list_reports_total_count_and_has_more_across_two_pages(
        self, api: ApiClient
    ) -> None:
        """Three stored accounts paged two at a time expose the full count on each page.

        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page."
        PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/entities/account_list_returns_pagination_envelope_with_total_count_and_has_more
        """
        for name, arr_cents in (
            ("Account A", 30_000_000),
            ("Account B", 20_000_000),
            ("Account C", 10_000_000),
        ):
            create_account(api, **{**NORTHWIND, "name": name, "arr_cents": arr_cents})

        first = assert_page(
            api.list_accounts(OPS_ADMIN_HEADERS, {"limit": 2}),
            expected_total=3,
            expected_has_more=True,
            expected_limit=2,
            expected_offset=0,
        )
        assert len(first) == 2, f"expected 2 rows on the first page, got {len(first)}"

        second = assert_page(
            api.list_accounts(OPS_ADMIN_HEADERS, {"limit": 2, "offset": 2}),
            expected_total=3,
            expected_has_more=False,
            expected_limit=2,
            expected_offset=2,
        )
        assert len(second) == 1, f"expected 1 row on the second page, got {len(second)}"


class TestPathAndBodyReferenceResolution:
    """404s raised before anything about the body is examined."""

    def test_account_get_with_unknown_id_returns_account_not_found(
        self, api: ApiClient
    ) -> None:
        """A well-formed UUID naming no account is a 404, not an empty success.

        PRD §2.9: "Every entity addressed by a path parameter exists, checked outermost-first."

        Design: Corner/entities/account_get_with_unknown_id_returns_account_not_found
        """
        validate_error(
            api.get_account(NON_EXISTENT_UUID, OPS_ADMIN_HEADERS),
            "ERR_ACCOUNT_NOT_FOUND",
            expected_status=404,
        )

    def test_outcome_goal_create_under_unknown_account_returns_account_not_found(
        self, api: ApiClient
    ) -> None:
        """The missing parent outranks the goal's own body checks.

        PRD §2.9: "Path existence in particular is resolved outermost-first — when a route addresses a child through its parent, the parent is looked up and rejected before any part of the body is examined."

        Design: Corner/entities/outcome_goal_create_under_unknown_account_returns_account_not_found
        """
        csm = create_csm(api)

        validate_error(
            api.create_outcome_goal(
                NON_EXISTENT_UUID,
                factories.outcome_goal(5000, 100.00),
                make_csm_headers(csm["id"]),
            ),
            "ERR_ACCOUNT_NOT_FOUND",
            expected_status=404,
        )


class TestRequiredFieldAndCrossAccountGuards:
    """Refusals that leave the addressed aggregates untouched."""

    def test_save_play_create_without_window_start_date_is_refused(
        self, api: ApiClient
    ) -> None:
        """A play with no window start is malformed and no row survives the call.

        PRD §3.5: "The play names the `account_id`, the `owner_csm_id` of the accountable manager, a `risk_code` diagnosing the driver — `ADOPTION_DECLINE`, `SUPPORT_ESCALATION`, `SPONSOR_LOSS`, `OUTCOME_MISS` or `BUDGET_PRESSURE` — a `play_type` naming the intervention pattern — `EXEC_ALIGNMENT`, `ENABLEMENT_SPRINT`, `COMMERCIAL_CONCESSION` or `TECHNICAL_REMEDIATION` — and the closed calendar window it will occupy, from `window_start_date` through `window_end_date` inclusive."
        PRD §2.9: "All required body fields are present; enum values are drawn from their declared sets; integers are non-negative wherever this document says so; calendar dates are ISO `YYYY-MM-DD` and instants are ISO 8601 UTC; `limit` is between 1 and 100 inclusive; `offset` is at least 0."

        Design: Corner/entities/save_play_create_missing_required_window_start_date_returns_invalid_request
        """
        csm = create_csm(api)
        account = create_account(api, **NORTHWIND)

        payload = factories.save_play(
            account["id"], csm["id"], "2026-08-05", "2026-08-20"
        )
        payload.pop("window_start_date")

        validate_error(
            api.create_save_play(payload, make_csm_headers(csm["id"])),
            "ERR_INVALID_REQUEST",
            expected_status=400,
        )
        assert_page(
            api.list_save_plays(OPS_ADMIN_HEADERS, {"account_id": account["id"]}),
            expected_total=0,
        )
        assert read_account(api, account["id"])["open_save_play_count"] == 0

    def test_escalation_case_naming_another_accounts_play_is_refused(
        self, api: ApiClient
    ) -> None:
        """Both referenced rows exist, but they belong to different accounts.

        PRD §2.9: "Cross-aggregate references stay inside one account: an escalation case's `save_play_id` must name a save play whose `account_id` equals the case's `account_id`, and an engagement's `sponsor_contact_id` must name a sponsor contact whose `account_id` equals the account in the path."
        PRD §3.5: "The referenced play must belong to the same account as the case; a play from another account is refused with `ERR_CROSS_ACCOUNT_REFERENCE`."

        Design: Corner/entities/escalation_case_across_two_accounts_returns_cross_account_reference
        """
        csm = create_csm(api)
        account_a = create_account(api, **{**NORTHWIND, "name": "Account A"})
        account_b = create_account(api, **{**NORTHWIND, "name": "Account B"})
        play_b = draft_save_play(
            api, account_b["id"], csm["id"], "2026-08-05", "2026-08-20"
        )

        validate_error(
            api.create_escalation_case(
                factories.escalation_case(account_a["id"], play_b["id"], SEVERITY_HIGH),
                make_csm_headers(csm["id"]),
            ),
            "ERR_CROSS_ACCOUNT_REFERENCE",
            expected_status=422,
        )
        assert_page(
            api.list_escalation_cases(
                OPS_ADMIN_HEADERS, {"account_id": account_a["id"]}
            ),
            expected_total=0,
        )
        assert read_save_play(api, play_b["id"])["state"] == PLAY_DRAFT


class TestComputedAndImmutableRows:
    """Values the server derives, and the row shape that carries no version."""

    def test_expansion_opportunity_qualification_score_is_derived_from_stored_state(
        self, api: ApiClient, clock: str, trending_account: dict
    ) -> None:
        """The score is computed from the trailing health figure, never supplied.

        PRD §3.7: "The `qualification_score` is computed at the moment the row is written and is never refreshed afterwards, so it records the account's condition when the opportunity was raised."
        PRD §3.7: "The health input is the **trailing** figure and never the point-in-time one: an account with a `trended_health_score` of 67.20, an `adoption_index` of 67.00 and `arr_cents` of 30,000,000 has a revenue term of 60.00 and a `qualification_score` of 33.60 plus 20.10 plus 12.00, or 65.70 — which clears the handoff floor, whereas substituting the point-in-time figure of 73.85 would give 69.03 and a materially different pipeline."
        PRD §3.7: "The row is created in state `IDENTIFIED` with `identified_at` stamped from the logical clock, `recycled_from_opportunity_id` null, `handoff_ae_user_id` null and `rejection_reason` null."

        Design: Corner/entities/expansion_opportunity_qualification_score_is_computed_not_supplied
        """
        account = trending_account["account"]
        assert_score(account["trended_health_score"], 67.20, "trended_health_score")
        assert_score(account["adoption_index"], 67.00, "adoption_index")

        data = assert_created(
            api.create_expansion_opportunity(
                factories.expansion_opportunity(
                    trending_account["account_id"], estimated_value_cents=4_000_000
                ),
                trending_account["csm_headers"],
            )
        )

        assert_score(data["qualification_score"], 65.70, "qualification_score")
        assert data["state"] == OPPORTUNITY_IDENTIFIED
        assert_null(data, "recycled_from_opportunity_id")
        assert data["identified_at"].startswith("2026-08-01T00:00:00"), (
            f"identified_at should carry the logical clock, got {data['identified_at']!r}"
        )

    def test_usage_signal_row_carries_no_version_and_no_updated_at(
        self, api: ApiClient, roster_and_account: dict
    ) -> None:
        """A signal is immutable, so it carries only `id` and `created_at` alongside its data.

        PRD §2.4: "Account signal rows — the usage periods and support tickets that feed the health model — carry only `id` and `created_at`."
        PRD §2.4: "They have **no** `updated_at` field and **no** `version` field, because a signal row is immutable once written: there is no endpoint that edits or deletes one, and the server never rewrites the input fields of a signal after creation."
        PRD §3.2: "A row with 90 weekly active users against 100 licensed seats and a `feature_depth_pct` of 80.00 therefore yields `seat_utilisation_pct` 90.00 and `usage_row_index` 86.00."

        Design: Corner/entities/account_signal_row_has_no_version_and_no_update_endpoint
        """
        account_id = roster_and_account["account_id"]

        data = assert_created(
            api.create_signal(
                account_id,
                factories.usage_signal("2026-07-31", 90, 100, 80.00),
                roster_and_account["csm_headers"],
            )
        )

        assert_signal_common_fields(data)
        assert_scores(
            data, {"seat_utilisation_pct": 90.00, "usage_row_index": 86.00}
        )

        stored = read_signal(api, account_id, data["id"])
        assert_signal_common_fields(stored)
        rows = list_rows(api.list_signals(account_id, OPS_ADMIN_HEADERS))
        assert [row["id"] for row in rows] == [data["id"]]
