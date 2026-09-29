"""Cross-cutting layers of the streaming royalty distribution API: optimistic
concurrency on the two version-carrying creates, the immediate visibility of
derived aggregates, the uniform error envelope across every status class, and
the fixed rejection ladder of PRD §2.10.
"""

from test_helpers import (
    ANALYST_FUZZY_MATCHER_USER_ID,
    CANONICAL_SCHEDULE,
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    append_line,
    approve_registration,
    assert_pool_value_conservation,
    create_batch,
    create_effective_schedule,
    create_label,
    create_period,
    create_pool,
    create_publisher,
    create_recording,
    get_success_data,
    make_rights_holder_user_headers,
    period_version,
    pool_payload,
    rate_schedule_payload,
    review_registration,
    rights_registration_payload,
    seal_and_match_batch,
    setup_all_matched_pool_finalized,
    statement_payload,
    validate_error,
    validate_success,
    work_version,
)

ADMIN = TEST_USERS["royalty_admin_headers"]
ANALYST = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR = TEST_USERS["regulatory_officer_headers"]

# Identifiers that are well formed UUIDs but name nothing.
UNKNOWN_WORK_ID = "11111111-1111-4111-8111-111111111150"
UNKNOWN_PERIOD_ID = "11111111-1111-4111-8111-111111111151"


# ─────────────────────────────────────────────────────
# Composite preambles this module needs and fixtures.py lacks
# ─────────────────────────────────────────────────────

def _setup_fuzzy_matched_recording(api):
    """A label, an OPEN period, and one recording whose ``version`` is captured
    BEFORE any matching happens.

    The batch carries a single line that reports the title and the artist but no
    ISRC, so matching accepts a metadata inference at 7,500 basis points and
    stamps ``provisional_match_by_user_id`` on the work — a mutation the filing
    claimant never asked for.
    """
    label = create_label(
        api, legal_name="Northbeam Records", territory="GB", rate_bps=800
    )
    period = create_period(api)
    recording = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )
    batch = create_batch(api, period["id"])
    append_line(
        api,
        batch["id"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        reported_artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=450000,
    )
    return {
        "label": label,
        "period": period,
        "recording": recording,
        "version_before_match": recording["version"],
        "batch": batch,
        "batch_after_match": seal_and_match_batch(api, batch["id"]),
    }


def _setup_distributed_period_with_a_second_holder(api):
    """The single-group fixture carried to a DISTRIBUTED period, plus a publisher
    that owns no approved registration and so will assemble an empty statement."""
    fixture = setup_all_matched_pool_finalized(api)
    fixture["publisher"] = create_publisher(
        api, legal_name="Tidewater Songs", territory="GB", rate_bps=1000
    )
    return fixture


def _setup_pool_over_only_unmatched_usage(api):
    """A GB/INDIVIDUAL pool of 100 subscribers and 100001 cents of revenue over a
    batch whose two lines match nothing at all, because the catalogue is empty."""
    fixture = {"schedule": create_effective_schedule(api, **CANONICAL_SCHEDULE)}
    fixture["period"] = create_period(api)
    fixture["batch"] = create_batch(
        api, fixture["period"]["id"], source_label="Partner feed"
    )
    fixture["first_line"] = append_line(
        api,
        fixture["batch"]["id"],
        reported_title="Unknown Signal",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=150000,
    )
    fixture["second_line"] = append_line(
        api,
        fixture["batch"]["id"],
        reported_title="Second Unknown",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=50000,
    )
    fixture["batch_after_match"] = seal_and_match_batch(api, fixture["batch"]["id"])
    fixture["pool"] = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=100,
        gross_revenue_cents=100001,
    )
    return fixture


# ─────────────────────────────────────────────────────
# Optimistic concurrency across the two version-carrying creates
# ─────────────────────────────────────────────────────

class TestCrossCuttingComplexityLayers:

    def test_registration_built_on_the_pre_match_work_version_is_refused(self, api):
        """A registration create carrying the work version read before a fuzzy match
        bumped it is refused with ERR_STALE_WORK_VERSION, while the identical body
        carrying the re-read version is accepted.

        PRD: "If that value does not equal the `Work`'s current `version`, the create is rejected with `ERR_STALE_WORK_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_work_version_on_registration_create
        """
        fixture = _setup_fuzzy_matched_recording(api)
        work_id = fixture["recording"]["id"]
        label_id = fixture["label"]["id"]
        claimant_headers = make_rights_holder_user_headers(label_id)

        work = get_success_data(api.get_work(work_id, ANALYST))
        assert work["provisional_match_by_user_id"] == ANALYST_FUZZY_MATCHER_USER_ID
        assert work["version"] > fixture["version_before_match"]

        stale = api.create_rights_registration(
            rights_registration_payload(
                work_id,
                label_id,
                fixture["version_before_match"],
                territory_set=["GB"],
            ),
            claimant_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_WORK_VERSION.value, 412)

        rows = get_success_data(
            api.list_rights_registrations(ANALYST, params={"work_id": work_id})
        )
        assert len(rows) == 0

        fresh = api.create_rights_registration(
            rights_registration_payload(
                work_id,
                label_id,
                work_version(api, work_id),
                territory_set=["GB"],
            ),
            claimant_headers,
        )
        created = validate_success(fresh, 201)
        assert created["status"] == "SUBMITTED"

    def test_work_version_token_cannot_be_replayed_after_an_approval(self, api):
        """Approving the first claim bumps the work version again, so replaying the
        token that was current a moment ago is refused with ERR_STALE_WORK_VERSION.

        PRD: "If that value does not equal the `Work`'s current `version`, the create is rejected with `ERR_STALE_WORK_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_work_version_on_registration_create
        """
        fixture = _setup_fuzzy_matched_recording(api)
        work_id = fixture["recording"]["id"]
        label_id = fixture["label"]["id"]
        claimant_headers = make_rights_holder_user_headers(label_id)

        version_after_match = work_version(api, work_id)
        registration = validate_success(
            api.create_rights_registration(
                rights_registration_payload(
                    work_id, label_id, version_after_match, territory_set=["GB"]
                ),
                claimant_headers,
            ),
            201,
        )
        review_registration(api, registration["id"])
        approve_registration(api, registration["id"])

        version_after_approval = work_version(api, work_id)
        assert version_after_approval > version_after_match

        replay = api.create_rights_registration(
            rights_registration_payload(
                work_id, label_id, version_after_match, territory_set=["FR"]
            ),
            claimant_headers,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_WORK_VERSION.value, 412)

    def test_second_statement_reusing_the_pre_build_period_version_is_refused(self, api):
        """Building one holder's statement advances the period version, so a second
        statement for a different holder reusing the earlier token is refused with
        ERR_STALE_PERIOD_VERSION rather than a duplicate-statement conflict.

        PRD: "If that value does not equal the period's current `version`, the create is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_period_version_on_statement_create
        """
        fixture = _setup_distributed_period_with_a_second_holder(api)
        period_id = fixture["period"]["id"]
        label_id = fixture["label"]["id"]
        publisher_id = fixture["publisher"]["id"]

        period = get_success_data(api.get_period(period_id, ADMIN))
        assert period["status"] == "DISTRIBUTED"
        version_before_build = period["version"]

        label_statement = validate_success(
            api.create_statement(
                statement_payload(label_id, period_id, version_before_build), ADMIN
            ),
            201,
        )
        assert label_statement["line_count"] == 1

        stale = api.create_statement(
            statement_payload(publisher_id, period_id, version_before_build), ADMIN
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PERIOD_VERSION.value, 412)

        version_after_build = period_version(api, period_id)
        assert version_after_build > version_before_build

        publisher_statement = validate_success(
            api.create_statement(
                statement_payload(publisher_id, period_id, version_after_build), ADMIN
            ),
            201,
        )
        assert publisher_statement["status"] == "DRAFT"
        assert publisher_statement["line_count"] == 0

        rows = get_success_data(
            api.list_statements(ADMIN, params={"period_id": period_id})
        )
        assert len(rows) == 2
        by_holder = {row["rights_holder_id"]: row for row in rows}
        assert by_holder[label_id]["line_count"] == 1
        assert by_holder[publisher_id]["line_count"] == 0


# ─────────────────────────────────────────────────────
# Immediate consistency of derived aggregates
# ─────────────────────────────────────────────────────

class TestConsistencyModel:

    def test_derived_totals_are_visible_in_the_response_that_causes_them(self, api):
        """The calculate and finalize responses already carry their derived totals and
        the elected residual payee, and the very next reads already show the line
        attributed, the period distributed and the batch reconciled.

        PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/derived_totals_are_visible_in_the_same_response_that_causes_them
        """
        fixture = _setup_pool_over_only_unmatched_usage(api)
        pool_id = fixture["pool"]["id"]

        calculated = validate_success(api.calculate_pool(pool_id, ADMIN), 200)
        assert calculated["status"] == "CALCULATED"
        assert calculated["distributable_cents"] == 70001
        assert calculated["matched_attributed_cents"] == 0
        assert calculated["holding_cents"] == 70000
        assert calculated["rounding_residual_cents"] == 1
        assert_pool_value_conservation(calculated)

        first_line = get_success_data(
            api.get_usage_line(fixture["first_line"]["id"], ADMIN)
        )
        assert first_line["attributed_revenue_cents"] == 52500
        second_line = get_success_data(
            api.get_usage_line(fixture["second_line"]["id"], ADMIN)
        )
        assert second_line["attributed_revenue_cents"] == 17500

        finalized = validate_success(api.finalize_pool(pool_id, ADMIN), 200)
        assert finalized["status"] == "FINALIZED"
        assert finalized["residual_payee_holder_id"] is None

        period = get_success_data(api.get_period(fixture["period"]["id"], ADMIN))
        assert period["status"] == "DISTRIBUTED"
        assert period["total_holding_cents"] == 70000

        batch = get_success_data(api.get_usage_batch(fixture["batch"]["id"], ADMIN))
        assert batch["status"] == "RECONCILED"


# ─────────────────────────────────────────────────────
# Error envelope uniformity and the rejection ladder
# ─────────────────────────────────────────────────────

class TestErrors:

    def test_error_envelope_is_uniform_across_every_status_class(self, api):
        """A 401, a 403, a 404, a 400, a 409, a 412 and a 422 all come back in the
        same error envelope, carrying exactly error_id and message in data.

        PRD: "All error API responses (4xx status codes) follow this standard envelope format:"

        Design: Corner/errors/error_envelope_is_uniform_across_every_status_class
        """
        label = create_label(
            api, legal_name="Northbeam Records", territory="GB", rate_bps=800
        )
        create_period(api)
        recording = create_recording(
            api,
            identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
            title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
        )
        work_id = recording["id"]
        label_id = label["id"]
        version_at_creation = recording["version"]
        claimant_headers = make_rights_holder_user_headers(label_id)

        no_headers = api.create_work(
            {
                "work_type": "RECORDING",
                "identifier": "GBABC2600099",
                "title": "No Headers",
            },
            {},
        )
        wrong_role = api.create_work(
            {
                "work_type": "RECORDING",
                "identifier": "GBABC2600098",
                "title": "Wrong Role",
            },
            REGULATOR,
        )
        unknown_work = api.create_rights_registration(
            rights_registration_payload(
                UNKNOWN_WORK_ID, label_id, version_at_creation
            ),
            ANALYST,
        )
        missing_field = api.create_period(
            {"label": "2026-07", "usage_start": "2026-07-01"}, ADMIN
        )
        duplicate_label = api.create_period(
            {
                "label": "2026-06",
                "usage_start": "2026-09-01",
                "usage_end": "2026-09-30",
            },
            ADMIN,
        )

        registration = validate_success(
            api.create_rights_registration(
                rights_registration_payload(work_id, label_id, version_at_creation),
                claimant_headers,
            ),
            201,
        )
        review_registration(api, registration["id"])
        approve_registration(api, registration["id"])

        approved_work = get_success_data(api.get_work(work_id, ANALYST))
        assert approved_work["rights_state"] == "REGISTERED"
        assert approved_work["version"] > version_at_creation

        stale_version = api.create_rights_registration(
            rights_registration_payload(
                work_id, label_id, version_at_creation, territory_set=["FR"]
            ),
            claimant_headers,
        )
        inverted_window = api.create_rate_schedule(
            rate_schedule_payload(
                proceeding_ref="CRB-2026-ZZ",
                effective_from="2026-06-01",
                effective_to="2026-01-01",
            ),
            REGULATOR,
        )

        ladder = [
            (no_headers, ApiErrorId.ERR_UNAUTHENTICATED, 401),
            (wrong_role, ApiErrorId.ERR_FORBIDDEN_ROLE, 403),
            (unknown_work, ApiErrorId.ERR_WORK_NOT_FOUND, 404),
            (missing_field, ApiErrorId.ERR_INVALID_REQUEST, 400),
            (duplicate_label, ApiErrorId.ERR_DUPLICATE_PERIOD_LABEL, 409),
            (stale_version, ApiErrorId.ERR_STALE_WORK_VERSION, 412),
            (inverted_window, ApiErrorId.ERR_INVALID_EFFECTIVE_PERIOD, 422),
        ]
        for response, error_id, expected_status in ladder:
            validate_error(response, error_id.value, expected_status)
            body = response.json()
            assert body["response_type"] == "error", error_id.value
            assert set(body["data"].keys()) == {"error_id", "message"}, error_id.value
            assert body["data"]["error_id"].strip(), error_id.value
            assert body["data"]["message"].strip(), error_id.value
            assert set(body["meta"].keys()) == {
                "api_request_id",
                "api_request_timestamp",
            }, error_id.value

        registrations = get_success_data(api.list_rights_registrations(ANALYST))
        assert len(registrations) == 1

        # The rejected create wrote nothing, so the label 2026-07 is still free.
        validate_success(
            api.create_period(
                {
                    "label": "2026-07",
                    "usage_start": "2026-07-01",
                    "usage_end": "2026-07-31",
                },
                ADMIN,
            ),
            201,
        )

    def test_ladder_rung_1_missing_headers_beats_every_other_defect(self, api):
        """A pool create with no headers, an unknown period and an incomplete body
        reports ERR_UNAUTHENTICATED, because authentication is checked first.

        PRD: "A request missing either header, or presenting an `X-User-Role` that is not one of those four strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_id_walks_down_the_priority_ladder_as_each_defect_is_removed
        """
        create_period(api)
        response = api.create_pool(
            {
                "period_id": UNKNOWN_PERIOD_ID,
                "territory_code": "GB",
                "subscription_tier": "INDIVIDUAL",
            },
            {},
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_ladder_rung_2_wrong_role_beats_existence_and_shape(self, api):
        """With the headers repaired but the role unauthorized, the same pool create
        reports ERR_FORBIDDEN_ROLE rather than the missing period or the short body.

        PRD: "A well-formed request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/errors/error_id_walks_down_the_priority_ladder_as_each_defect_is_removed
        """
        create_period(api)
        response = api.create_pool(
            {
                "period_id": UNKNOWN_PERIOD_ID,
                "territory_code": "GB",
                "subscription_tier": "INDIVIDUAL",
            },
            ANALYST,
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_ladder_rung_3_unknown_period_beats_the_incomplete_body(self, api):
        """With the role repaired, the unknown period_id reports
        ERR_PERIOD_NOT_FOUND rather than the still-incomplete body.

        PRD: "The first missing identifier decides which not-found error is returned, drawn from `ERR_RIGHTS_HOLDER_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_USAGE_BATCH_NOT_FOUND`, `ERR_USAGE_LINE_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_STATEMENT_LINE_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND` and `ERR_RATE_SCHEDULE_NOT_FOUND`."

        Design: Corner/errors/error_id_walks_down_the_priority_ladder_as_each_defect_is_removed
        """
        create_period(api)
        response = api.create_pool(
            {
                "period_id": UNKNOWN_PERIOD_ID,
                "territory_code": "GB",
                "subscription_tier": "INDIVIDUAL",
            },
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_NOT_FOUND.value, 404)

    def test_ladder_rung_4_incomplete_body_surfaces_once_existence_holds(self, api):
        """With headers, role and period all repaired, the missing money fields are
        the only remaining defect and report ERR_INVALID_REQUEST.

        PRD: "Checks are therefore evaluated in the following fixed order, and the first failure decides the response."

        Design: Corner/errors/error_id_walks_down_the_priority_ladder_as_each_defect_is_removed
        """
        period = create_period(api)
        response = api.create_pool(
            {
                "period_id": period["id"],
                "territory_code": "GB",
                "subscription_tier": "INDIVIDUAL",
            },
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_ladder_rung_5_complete_pool_create_is_accepted(self, api):
        """With every defect repaired the pool create succeeds at 201, landing in
        DRAFT with every computed money field at zero and every derived reference null.

        PRD: "A new pool starts at `status` `DRAFT` with every computed money field at zero, `applied_rate_schedule_id`, `denominator_basis`, `allocation_basis` and `residual_payee_holder_id` all null."

        Design: Corner/errors/error_id_walks_down_the_priority_ladder_as_each_defect_is_removed
        """
        period = create_period(api)
        pool = validate_success(
            api.create_pool(
                pool_payload(
                    period["id"], subscriber_count=1000, gross_revenue_cents=1428570
                ),
                ADMIN,
            ),
            201,
        )
        assert pool["status"] == "DRAFT"
        assert pool["distributable_cents"] == 0
        assert pool["matched_attributed_cents"] == 0
        assert pool["holding_cents"] == 0
        assert pool["rounding_residual_cents"] == 0
        assert pool["applied_rate_schedule_id"] is None
        assert pool["denominator_basis"] is None
        assert pool["allocation_basis"] is None
        assert pool["residual_payee_holder_id"] is None

    def test_ladder_rung_6_repeating_the_cell_yields_duplicate_pool(self, api):
        """A second pool for the same period, territory and tier is refused with
        ERR_DUPLICATE_POOL, the stored pool is untouched, and another tier is free.

        PRD: "The triple of period, territory and tier is unique; a second pool for the same cell is refused with `ERR_DUPLICATE_POOL`."

        Design: Corner/errors/error_id_walks_down_the_priority_ladder_as_each_defect_is_removed
        """
        period = create_period(api)
        pool = create_pool(
            api, period["id"], subscriber_count=1000, gross_revenue_cents=1428570
        )

        duplicate = api.create_pool(
            {
                "period_id": period["id"],
                "territory_code": "GB",
                "subscription_tier": "INDIVIDUAL",
                "subscriber_count": 999,
                "gross_revenue_cents": 1,
            },
            ADMIN,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_POOL.value, 409)

        stored = get_success_data(api.get_pool(pool["id"], ADMIN))
        assert stored["subscriber_count"] == 1000
        assert stored["gross_revenue_cents"] == 1428570

        validate_success(
            api.create_pool(
                pool_payload(
                    period["id"],
                    subscription_tier="FAMILY",
                    subscriber_count=400,
                    gross_revenue_cents=200000,
                ),
                ADMIN,
            ),
            201,
        )

        rows = get_success_data(
            api.list_pools(ADMIN, params={"period_id": period["id"]})
        )
        assert len(rows) == 2
