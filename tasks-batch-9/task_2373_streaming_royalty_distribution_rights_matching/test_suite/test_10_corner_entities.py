"""Entity-level conformance tests: declared fields, computed fields, defaults,
structural validation, listing, junction traversal, identifier resolution and
statement-line immutability.

Every precondition is built through declared endpoints only, using the atoms and
composites of ``test_helpers.fixtures``.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_accounting_period,
    assert_rights_holder,
    assert_rights_registration,
    assert_statement_line,
    assert_usage_batch,
    assert_work,
    TEST_USERS,
    composition_payload,
    create_batch,
    create_collective,
    create_composition,
    create_label,
    create_period,
    create_publisher,
    create_recording,
    file_registration,
    make_rights_holder_user_headers,
    rights_holder_payload,
    rights_registration_payload,
    setup_all_matched_statement_issued,
    usage_line_payload,
    validate_error,
    validate_paginated,
    validate_success,
    work_payload,
    work_version,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR_HEADERS = TEST_USERS["regulatory_officer_headers"]
REVIEWER_HEADERS = TEST_USERS["reviewer_headers"]
HOLDER_HEADERS = TEST_USERS["rights_holder_user_headers"]


# ─────────────────────────────────────────────────────
# Local composite setups, built from the fixtures atoms
# ─────────────────────────────────────────────────────

def _setup_label_and_recording(api):
    """One LABEL holder plus one RECORDING work, with the work's current version.

    Returns ``(holder, work, work_version)`` so a registration create can carry a
    genuine ``expected_work_version`` and the caller can prove afterwards that a
    rejected create left the parent version untouched.
    """
    holder = create_label(api, legal_name="Northbeam Records", territory="GB", rate_bps=800)
    work = create_recording(
        api,
        identifier="GBABC2600001",
        title="Midnight Ledger",
        artist="The Reconcilers",
    )
    return holder, work, work_version(api, work["id"])


def _setup_open_batch(api):
    """One OPEN accounting period owning one OPEN usage batch with no lines."""
    period = create_period(api)
    batch = create_batch(api, period["id"])
    return period, batch


def _setup_twelve_works(api):
    """Ten RECORDING rows then two COMPOSITION rows, created in that order."""
    titles = [
        "Track One",
        "Track Two",
        "Track Three",
        "Track Four",
        "Track Five",
        "Track Six",
        "Track Seven",
        "Track Eight",
        "Track Nine",
        "Track Ten",
    ]
    recordings = [
        create_recording(
            api,
            identifier="GBABC26000%02d" % (index + 1),
            title=title,
            artist="The Reconcilers",
        )
        for index, title in enumerate(titles)
    ]
    compositions = [
        create_composition(api, identifier="T9001234567", title="Track One"),
        create_composition(api, identifier="T9001234568", title="Track Two"),
    ]
    return recordings, compositions


def _setup_composition_with_two_routings(api):
    """A COMPOSITION claimed twice by one publisher: once DIRECT (MECHANICAL) and
    once COLLECTIVE (PERFORMANCE) through a worldwide collective."""
    publisher = create_publisher(
        api, legal_name="Tidewater Songs", territory="GB", rate_bps=800
    )
    collective = create_collective(
        api, legal_name="Harbour Collecting Society", territory="WORLD"
    )
    composition = create_composition(api, identifier="T9001234567", title="Midnight Ledger")

    direct_registration = file_registration(
        api,
        composition["id"],
        publisher["id"],
        right_type="MECHANICAL",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["GB"],
    )
    collective_registration = file_registration(
        api,
        composition["id"],
        publisher["id"],
        collective_id=collective["id"],
        right_type="PERFORMANCE",
        routing="COLLECTIVE",
        share_bps=10000,
        territory_set=["GB"],
    )
    return {
        "publisher": publisher,
        "collective": collective,
        "composition": composition,
        "direct_registration": direct_registration,
        "collective_registration": collective_registration,
    }


# ─────────────────────────────────────────────────────
# Creation, computed fields and declared defaults
# ─────────────────────────────────────────────────────

class TestEntityCreation:
    def test_rights_holder_create_returns_declared_fields_and_zero_counters(self, api):
        """A freshly registered rights holder echoes every supplied field, starts both
        computed counters at 0 and is readable by another role with identical values.

        PRD: "A holder is born with `receivable_balance_cents` and `issued_statement_count` both at zero, and both are derived thereafter exactly as §2.9 specifies."

        Design: Corner/entities/rights_holder_create_returns_declared_fields_and_zero_counters
        """
        response = api.create_rights_holder(
            rights_holder_payload(
                legal_name="Northbeam Records",
                holder_type="LABEL",
                home_territory_code="GB",
                direct_deal_rate_bps=800,
            ),
            ADMIN_HEADERS,
        )
        created = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        assert_rights_holder(created)
        assert created["legal_name"] == "Northbeam Records"
        assert created["holder_type"] == "LABEL"
        assert created["home_territory_code"] == "GB"
        assert created["direct_deal_rate_bps"] == 800
        assert created["receivable_balance_cents"] == 0
        assert created["issued_statement_count"] == 0
        assert created["version"] == 1

        fetched = validate_success(
            api.get_rights_holder(created["id"], ANALYST_HEADERS), 200
        )
        for field in (
            "id",
            "legal_name",
            "holder_type",
            "home_territory_code",
            "direct_deal_rate_bps",
            "receivable_balance_cents",
            "issued_statement_count",
        ):
            assert fetched[field] == created[field], field

    def test_work_normalization_fields_are_computed_from_title_and_artist(self, api):
        """Normalization lowercases, strips punctuation, collapses interior space runs and
        trims, leaving the reported title and credit stored unchanged.

        PRD: "`normalized_title` is derived from `title` by lowercasing it, removing every character that is not a lowercase letter, a digit or a space, collapsing every run of consecutive spaces into a single space, and trimming leading and trailing spaces."

        Design: Corner/entities/work_normalization_fields_are_computed_from_title_and_artist
        """
        created = validate_success(
            api.create_work(
                work_payload(
                    work_type="RECORDING",
                    identifier="GBABC2600001",
                    title="  MIDNIGHT   LEDGER!! ",
                    artist_credit="The Reconcilers",
                ),
                ANALYST_HEADERS,
            ),
            201,
        )
        assert_work(created)
        assert created["normalized_title"] == "midnight ledger"
        assert len(created["normalized_title"]) == 15
        assert created["normalized_artist"] == "the reconcilers"
        assert created["title"] == "  MIDNIGHT   LEDGER!! "
        assert created["artist_credit"] == "The Reconcilers"
        assert created["rights_state"] == "UNMATCHED"
        assert created["approved_master_share_bps"] == 0

    def test_work_optional_inputs_omitted_take_declared_defaults(self, api):
        """Omitting both optional inputs on a composition leaves artist_credit,
        normalized_artist, linked_work_id and provisional_match_by_user_id null.

        PRD: "`normalized_artist` is the same transformation applied to `artist_credit`, and is null whenever `artist_credit` is null."

        Design: Corner/entities/work_optional_inputs_omitted_take_declared_defaults
        """
        created = validate_success(
            api.create_work(
                composition_payload(identifier="T9001234567", title="Midnight Ledger"),
                ANALYST_HEADERS,
            ),
            201,
        )
        assert_work(created)
        assert created["artist_credit"] is None
        assert created["normalized_artist"] is None
        assert created["linked_work_id"] is None
        assert created["provisional_match_by_user_id"] is None
        assert created["normalized_title"] == "midnight ledger"
        assert created["rights_state"] == "UNMATCHED"
        assert created["approved_master_share_bps"] == 0

    def test_usage_batch_counters_default_to_zero_on_creation(self, api):
        """A newly opened usage batch reports status OPEN and all five play-count
        aggregates at zero before any line is appended.

        PRD: "A new batch starts at `status` `OPEN` with `line_count`, `total_play_count`, `matched_play_count`, `unmatched_play_count` and `disputed_play_count` all at zero."

        Design: Corner/entities/usage_batch_counters_default_to_zero_on_creation
        """
        period = create_period(api, label="2026-06", usage_start="2026-06-01", usage_end="2026-06-30")
        assert_accounting_period(period)
        assert period["status"] == "OPEN"
        assert period["claim_window_closes_at"].startswith("2026-08-29T00:00:00")

        created = validate_success(
            api.create_usage_batch(
                {"period_id": period["id"], "source_label": "UK client feed"},
                ANALYST_HEADERS,
            ),
            201,
        )
        assert_usage_batch(created)
        assert created["status"] == "OPEN"
        assert created["line_count"] == 0
        assert created["total_play_count"] == 0
        assert created["matched_play_count"] == 0
        assert created["unmatched_play_count"] == 0
        assert created["disputed_play_count"] == 0
        assert created["period_id"] == period["id"]
        assert created["source_label"] == "UK client feed"


# ─────────────────────────────────────────────────────
# Structural validation of write bodies
# ─────────────────────────────────────────────────────

class TestStructuralValidation:
    def test_registration_create_missing_required_field_returns_invalid_request(self, api):
        """Omitting share_bps on a claim is a structural failure, so nothing is persisted
        and the parent work's version does not move.

        PRD: "Either a `RightsHolderUser` acting for itself or a `RightsOpsAnalyst` acting on a holder's behalf files one, naming the `work_id` whose rights are claimed, the `claimant_id` asserting the share, the `right_type` being claimed — `MASTER`, `MECHANICAL` or `PERFORMANCE` — the `routing`, which is `DIRECT` when the money goes straight to the claimant and `COLLECTIVE` when it flows through a society, the `share_bps` claimed, between 1 and 10,000, the `territory_set`, the `effective_from` and `effective_to` bounding the ownership interval, and the `expected_work_version` described in §2.8."

        Design: Corner/entities/registration_create_missing_required_field_returns_invalid_request
        """
        holder, work, version_before = _setup_label_and_recording(api)

        response = api.create_rights_registration(
            {
                "work_id": work["id"],
                "claimant_id": holder["id"],
                "right_type": "MASTER",
                "routing": "DIRECT",
                "territory_set": ["GB"],
                "effective_from": "2026-01-01",
                "effective_to": "2027-01-01",
                "expected_work_version": version_before,
            },
            make_rights_holder_user_headers(holder["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        rows, meta = validate_paginated(
            api.list_rights_registrations(ANALYST_HEADERS, params={"work_id": work["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert work_version(api, work["id"]) == version_before

    def test_usage_line_enum_outside_domain_returns_invalid_request(self, api):
        """A subscription_tier outside the declared enum is refused and leaves the open
        batch's counters and status untouched.

        PRD: "A line names its owning batch through `batch_id` and carries what the source actually reported: `reported_title`, non-empty and at most 300 characters; `reported_isrc`, which may be absent and may be wrong; `reported_artist`, which may be absent; the `territory_code` in which the plays happened, which must be exactly two uppercase letters, with the literal `WORLD` refused on a usage line; the `subscription_tier` of the subscribers who generated them, one of `FREE_AD_SUPPORTED`, `INDIVIDUAL`, `FAMILY` or `STUDENT`; and `play_count`, the number of qualifying plays, which must be at least 1."

        Design: Corner/entities/usage_line_enum_outside_domain_returns_invalid_request
        """
        _period, batch = _setup_open_batch(api)

        response = api.append_usage_line(
            batch["id"],
            usage_line_payload(
                reported_title="Midnight Ledger",
                territory_code="GB",
                subscription_tier="PLATINUM",
                play_count=100000,
            ),
            ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        after = validate_success(api.get_usage_batch(batch["id"], ANALYST_HEADERS), 200)
        assert after["line_count"] == 0
        assert after["total_play_count"] == 0
        assert after["status"] == "OPEN"

    def test_registration_share_bps_out_of_range_returns_invalid_request(self, api):
        """share_bps is bounded to 1..10,000 inclusive at create time, so 0 and 10,001 are
        both refused while 1 is accepted.

        PRD: "Either a `RightsHolderUser` acting for itself or a `RightsOpsAnalyst` acting on a holder's behalf files one, naming the `work_id` whose rights are claimed, the `claimant_id` asserting the share, the `right_type` being claimed — `MASTER`, `MECHANICAL` or `PERFORMANCE` — the `routing`, which is `DIRECT` when the money goes straight to the claimant and `COLLECTIVE` when it flows through a society, the `share_bps` claimed, between 1 and 10,000, the `territory_set`, the `effective_from` and `effective_to` bounding the ownership interval, and the `expected_work_version` described in §2.8."

        Design: Corner/entities/registration_share_bps_out_of_range_returns_invalid_request
        """
        holder, work, version_before = _setup_label_and_recording(api)
        holder_headers = make_rights_holder_user_headers(holder["id"])

        for rejected_share in (0, 10001):
            validate_error(
                api.create_rights_registration(
                    rights_registration_payload(
                        work["id"],
                        holder["id"],
                        version_before,
                        right_type="MASTER",
                        routing="DIRECT",
                        share_bps=rejected_share,
                        territory_set=["GB"],
                        effective_from="2026-01-01",
                        effective_to="2027-01-01",
                    ),
                    holder_headers,
                ),
                ApiErrorId.ERR_INVALID_REQUEST.value,
                400,
            )

        accepted = validate_success(
            api.create_rights_registration(
                rights_registration_payload(
                    work["id"],
                    holder["id"],
                    version_before,
                    right_type="MASTER",
                    routing="DIRECT",
                    share_bps=1,
                    territory_set=["GB"],
                    effective_from="2026-01-01",
                    effective_to="2027-01-01",
                ),
                holder_headers,
            ),
            201,
        )
        assert_rights_registration(accepted)
        assert accepted["share_bps"] == 1
        assert accepted["status"] == "SUBMITTED"

        rows, meta = validate_paginated(
            api.list_rights_registrations(ANALYST_HEADERS, params={"work_id": work["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [accepted["id"]]

    def test_registration_create_with_empty_territory_set_returns_invalid_request(self, api):
        """An empty territory_set is structurally invalid, so the claim is refused and no
        registration row is persisted.

        PRD: "A `territory_set` is either exactly the single-element list containing `WORLD`, or a non-empty list of between 1 and 250 distinct two-letter codes."

        Design: Corner/entities/registration_share_bps_out_of_range_returns_invalid_request
        """
        holder, work, version_before = _setup_label_and_recording(api)

        validate_error(
            api.create_rights_registration(
                rights_registration_payload(
                    work["id"],
                    holder["id"],
                    version_before,
                    right_type="MASTER",
                    routing="DIRECT",
                    share_bps=10000,
                    territory_set=[],
                    effective_from="2026-01-01",
                    effective_to="2027-01-01",
                ),
                make_rights_holder_user_headers(holder["id"]),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        rows, meta = validate_paginated(
            api.list_rights_registrations(ANALYST_HEADERS, params={"work_id": work["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0


# ─────────────────────────────────────────────────────
# Listing and junction traversal
# ─────────────────────────────────────────────────────

class TestListingAndGraph:
    def test_works_list_returns_default_page_of_ten(self, api):
        """With twelve works stored, the unfiltered list returns the default page of ten
        while reporting the full total_count and has_more true.

        PRD: "The `limit` parameter caps the number of records returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/entities/works_list_returns_default_page_and_honours_filters
        """
        recordings, _compositions = _setup_twelve_works(api)

        response = api.list_works(HOLDER_HEADERS)
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert len(rows) == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert rows[0]["id"] == recordings[0]["id"]

    def test_works_list_honours_equality_filters(self, api):
        """A work_type filter narrows total_count to the matching rows only, and a
        rights_state filter that matches nothing returns an empty page.

        PRD: "Works may be filtered by `work_type`, by `linked_work_id`, or by `rights_state`."

        Design: Corner/entities/works_list_returns_default_page_and_honours_filters
        """
        _setup_twelve_works(api)

        rows, meta = validate_paginated(
            api.list_works(HOLDER_HEADERS, params={"work_type": "COMPOSITION"})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["identifier"] for row in rows] == ["T9001234567", "T9001234568"]

        rows, meta = validate_paginated(
            api.list_works(HOLDER_HEADERS, params={"rights_state": "REGISTERED"})
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

    def test_registration_payee_holder_id_is_computed_from_routing(self, api):
        """On one composition claimed twice by one publisher, the DIRECT claim's payee is
        the claimant and the COLLECTIVE claim's payee is the collective.

        PRD: "The service computes `payee_holder_id` from the routing — it equals `collective_id` when `routing` is `COLLECTIVE` and `claimant_id` when `routing` is `DIRECT` — re-derives the work's `rights_state`, which becomes `PROVISIONAL` if no stronger state applies, and increments the work's `version`."

        Design: Corner/entities/registration_junction_supports_reverse_lookups_from_both_sides
        """
        fixture = _setup_composition_with_two_routings(api)
        direct = fixture["direct_registration"]
        collective_routed = fixture["collective_registration"]

        assert_rights_registration(direct)
        assert_rights_registration(collective_routed)
        assert direct["payee_holder_id"] == fixture["publisher"]["id"]
        assert direct["collective_id"] is None
        assert collective_routed["payee_holder_id"] == fixture["collective"]["id"]
        assert collective_routed["collective_id"] == fixture["collective"]["id"]

    def test_registration_junction_supports_reverse_lookups_from_both_sides(self, api):
        """The registration junction is traversable from the work side and from each of its
        three holder edges: claimant, collective and computed payee.

        PRD: "Rights registrations may be filtered by `work_id`, `claimant_id`, `collective_id`, `payee_holder_id`, `disputing_holder_id`, `status` or `right_type`."

        Design: Corner/entities/registration_junction_supports_reverse_lookups_from_both_sides
        """
        fixture = _setup_composition_with_two_routings(api)
        publisher_id = fixture["publisher"]["id"]
        collective_id = fixture["collective"]["id"]
        direct_id = fixture["direct_registration"]["id"]
        collective_routed_id = fixture["collective_registration"]["id"]

        def ids_for(**params):
            rows, meta = validate_paginated(
                api.list_rights_registrations(ADMIN_HEADERS, params=params)
            )
            assert meta["total_count"] == len(rows)
            return sorted(row["id"] for row in rows)

        both = sorted([direct_id, collective_routed_id])
        assert ids_for(work_id=fixture["composition"]["id"]) == both
        assert ids_for(claimant_id=publisher_id) == both
        assert ids_for(collective_id=collective_id) == [collective_routed_id]
        assert ids_for(payee_holder_id=publisher_id) == [direct_id]
        assert ids_for(payee_holder_id=collective_id) == [collective_routed_id]


# ─────────────────────────────────────────────────────
# Identifier resolution: the not-found family
# ─────────────────────────────────────────────────────

class TestIdentifierResolution:
    def test_rights_holder_get_with_unknown_id_returns_not_found(self, api):
        """Reading a rights holder by an unknown id returns the holder not-found error
        rather than an empty success body.

        PRD: "The first missing identifier decides which not-found error is returned, drawn from `ERR_RIGHTS_HOLDER_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_USAGE_BATCH_NOT_FOUND`, `ERR_USAGE_LINE_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_STATEMENT_LINE_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND` and `ERR_RATE_SCHEDULE_NOT_FOUND`."

        Design: Corner/entities/rights_holder_get_with_unknown_id_returns_not_found
        """
        response = api.get_rights_holder(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_RIGHTS_HOLDER_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"

    def test_registration_create_with_unknown_work_returns_not_found(self, api):
        """When both the work and the claimant are unknown, the work error wins because
        work_id resolves before claimant_id.

        PRD: "A registration create, for example, resolves `work_id` before `claimant_id` and `claimant_id` before `collective_id`, so a request naming both a non-existent work and a non-existent claimant reports `ERR_WORK_NOT_FOUND`."

        Design: Corner/entities/registration_create_with_unknown_work_returns_not_found
        """
        real_work = create_recording(
            api,
            identifier="GBABC2600001",
            title="Midnight Ledger",
            artist="The Reconcilers",
        )
        genuine_version = work_version(api, real_work["id"])
        unknown_claimant = "11111111-1111-4111-8111-111111111103"

        validate_error(
            api.create_rights_registration(
                rights_registration_payload(
                    NON_EXISTENT_UUID,
                    unknown_claimant,
                    genuine_version,
                    right_type="MASTER",
                    routing="DIRECT",
                    share_bps=10000,
                    territory_set=["GB"],
                    effective_from="2026-01-01",
                    effective_to="2027-01-01",
                ),
                make_rights_holder_user_headers(unknown_claimant),
            ),
            ApiErrorId.ERR_WORK_NOT_FOUND.value,
            404,
        )

    def test_pool_create_with_unknown_period_returns_not_found(self, api):
        """Creating a pool against an unknown period reports the period not-found error
        instead of any period-state error.

        PRD: "The practical consequence worth internalizing: authorization precedes existence, existence precedes shape, shape precedes uniqueness, ownership and duty separation precede every state check, all state checks precede the concurrency check, and every business rule about money, time and territory comes last."

        Design: Corner/entities/pool_create_with_unknown_period_returns_not_found
        """
        validate_error(
            api.create_pool(
                {
                    "period_id": NON_EXISTENT_UUID,
                    "territory_code": "GB",
                    "subscription_tier": "INDIVIDUAL",
                    "subscriber_count": 1000,
                    "gross_revenue_cents": 1428570,
                },
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_PERIOD_NOT_FOUND.value,
            404,
        )

    def test_usage_line_append_to_unknown_batch_returns_not_found(self, api):
        """Appending a line to an unknown batch reports the batch not-found error even when
        the body also carries a play_count below one.

        PRD: "Path parameters resolve first, in the order they appear in the path, so a request naming a non-existent parent never reports a missing child."

        Design: Corner/entities/usage_line_append_to_unknown_batch_returns_not_found
        """
        validate_error(
            api.append_usage_line(
                NON_EXISTENT_UUID,
                usage_line_payload(
                    reported_title="Midnight Ledger",
                    territory_code="GB",
                    subscription_tier="INDIVIDUAL",
                    play_count=0,
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_USAGE_BATCH_NOT_FOUND.value,
            404,
        )

    def test_usage_line_get_with_unknown_id_returns_not_found(self, api):
        """Reading a usage line by an unknown id reports the usage-line not-found error, not
        the parent batch's error.

        PRD: "The first missing identifier decides which not-found error is returned, drawn from `ERR_RIGHTS_HOLDER_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_USAGE_BATCH_NOT_FOUND`, `ERR_USAGE_LINE_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_STATEMENT_LINE_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND` and `ERR_RATE_SCHEDULE_NOT_FOUND`."

        Design: Corner/entities/usage_line_get_with_unknown_id_returns_not_found
        """
        validate_error(
            api.get_usage_line(NON_EXISTENT_UUID, ANALYST_HEADERS),
            ApiErrorId.ERR_USAGE_LINE_NOT_FOUND.value,
            404,
        )

    def test_registration_review_with_unknown_id_returns_not_found(self, api):
        """Taking an unknown registration into review reports the registration not-found
        error rather than a registration-state error.

        PRD: "The practical consequence worth internalizing: authorization precedes existence, existence precedes shape, shape precedes uniqueness, ownership and duty separation precede every state check, all state checks precede the concurrency check, and every business rule about money, time and territory comes last."

        Design: Corner/entities/registration_review_with_unknown_id_returns_not_found
        """
        validate_error(
            api.review_rights_registration(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value,
            404,
        )

    def test_pool_calculate_with_unknown_id_returns_not_found(self, api):
        """Calculating an unknown pool reports the pool not-found error, never the missing
        rate-schedule error, even with no effective schedule stored.

        PRD: "The practical consequence worth internalizing: authorization precedes existence, existence precedes shape, shape precedes uniqueness, ownership and duty separation precede every state check, all state checks precede the concurrency check, and every business rule about money, time and territory comes last."

        Design: Corner/entities/pool_calculate_with_unknown_id_returns_not_found
        """
        validate_error(
            api.calculate_pool(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_POOL_NOT_FOUND.value,
            404,
        )

    def test_statement_issue_with_unknown_id_returns_not_found(self, api):
        """Issuing an unknown statement reports the statement not-found error rather than
        the no-statement-lines error.

        PRD: "The practical consequence worth internalizing: authorization precedes existence, existence precedes shape, shape precedes uniqueness, ownership and duty separation precede every state check, all state checks precede the concurrency check, and every business rule about money, time and territory comes last."

        Design: Corner/entities/statement_issue_with_unknown_id_returns_not_found
        """
        validate_error(
            api.issue_statement(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_STATEMENT_NOT_FOUND.value,
            404,
        )

    def test_statement_line_get_with_unknown_id_returns_not_found(self, api):
        """A statement line is read-only but still resolvable, so an unknown line id reports
        the statement-line not-found error.

        PRD: "The first missing identifier decides which not-found error is returned, drawn from `ERR_RIGHTS_HOLDER_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_USAGE_BATCH_NOT_FOUND`, `ERR_USAGE_LINE_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_STATEMENT_LINE_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND` and `ERR_RATE_SCHEDULE_NOT_FOUND`."

        Design: Corner/entities/statement_line_get_with_unknown_id_returns_not_found
        """
        validate_error(
            api.get_statement_line(NON_EXISTENT_UUID, HOLDER_HEADERS),
            ApiErrorId.ERR_STATEMENT_LINE_NOT_FOUND.value,
            404,
        )

    def test_engagement_findings_with_unknown_id_returns_not_found(self, api):
        """Asserting a finding on an unknown engagement reports the engagement not-found
        error, ahead of both the ownership and the production-completeness rules.

        PRD: "The practical consequence worth internalizing: authorization precedes existence, existence precedes shape, shape precedes uniqueness, ownership and duty separation precede every state check, all state checks precede the concurrency check, and every business rule about money, time and territory comes last."

        Design: Corner/entities/engagement_findings_with_unknown_id_returns_not_found
        """
        validate_error(
            api.record_audit_findings(
                NON_EXISTENT_UUID,
                {"asserted_underpayment_cents": 5000},
                HOLDER_HEADERS,
            ),
            ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value,
            404,
        )

    def test_rate_schedule_promulgate_with_unknown_id_returns_not_found(self, api):
        """Promulgating an unknown rate schedule reports the schedule not-found error rather
        than a rate-schedule-state error.

        PRD: "The practical consequence worth internalizing: authorization precedes existence, existence precedes shape, shape precedes uniqueness, ownership and duty separation precede every state check, all state checks precede the concurrency check, and every business rule about money, time and territory comes last."

        Design: Corner/entities/rate_schedule_promulgate_with_unknown_id_returns_not_found
        """
        validate_error(
            api.promulgate_rate_schedule(NON_EXISTENT_UUID, REGULATOR_HEADERS, {}),
            ApiErrorId.ERR_RATE_SCHEDULE_NOT_FOUND.value,
            404,
        )


# ─────────────────────────────────────────────────────
# Statement-line immutability
# ─────────────────────────────────────────────────────

def test_statement_line_is_immutable_and_has_no_write_surface(api):
    """A materialised statement line carries only id and created_at alongside its
    business fields, exposing neither updated_at nor version to edit against.

    PRD: "It therefore carries only `id` and `created_at`; it has no `updated_at` field and no `version` field at all."

    Design: Corner/entities/statement_line_is_immutable_and_has_no_write_surface
    """
    fixture = setup_all_matched_statement_issued(api)
    statement_id = fixture["statement"]["id"]

    rows, meta = validate_paginated(api.list_statement_lines(ADMIN_HEADERS))
    assert meta["total_count"] >= 1
    assert rows, "an issued statement must carry at least one line"

    for row in rows:
        assert_statement_line(row)
        assert "updated_at" not in row
        assert "version" not in row
        assert row["adjustment_of_line_id"] is None

    listed = rows[0]
    assert listed["statement_id"] == statement_id

    fetched = validate_success(api.get_statement_line(listed["id"], ADMIN_HEADERS), 200)
    assert_statement_line(fetched)
    assert fetched == listed, "re-reading an immutable line must return identical values"

    refetched = validate_success(api.get_statement_line(listed["id"], ADMIN_HEADERS), 200)
    assert refetched == fetched
