"""Entity-level contracts: creation defaults, computed fields, listing shape, required
fields, parent resolution and the one append-only row."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_append_only_fields,
    assert_money_equals,
    create_candidate_payload,
    create_client_book_entry_payload,
    create_collection_record_payload,
    create_engagement_payload,
    create_questionnaire_payload,
    draft_offer,
    make_candidate_headers,
    new_engagement,
    new_practice_group,
    new_search_firm,
    read_questionnaire,
    setup_approached_candidate,
    setup_book,
    setup_cleared_candidate,
    setup_config,
    setup_questionnaire_in_draft,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]


def test_a_new_candidate_lands_in_both_opening_statuses_with_every_date_null():
    """The new row lands with `pipeline_status` `SOURCED` and `clearance_status`
    `NOT_STARTED`, and with `resignation_date`, `earliest_start_date`, `hire_date`, and
    `open_offer_id` all null.

    Design: Corner/entities/candidate_creation_initializes_both_status_dimensions
    """
    ctx = setup_config()

    candidate = validate_success(
        api_client.create_candidate(
            create_candidate_payload(
                ctx["practice_group"]["id"], ctx["engagement"]["id"]
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )

    assert candidate["pipeline_status"] == "SOURCED"
    assert candidate["clearance_status"] == "NOT_STARTED"
    assert candidate["resignation_date"] is None
    assert candidate["earliest_start_date"] is None
    assert candidate["hire_date"] is None
    assert candidate["open_offer_id"] is None
    assert candidate["notice_period_days"] == 45
    assert candidate["non_solicit_days"] == 30
    assert candidate["version"] == 1


def test_a_fresh_practice_group_reads_back_a_fully_available_guarantee_ledger():
    """On registration the group's `status` is `OPEN`, `available_guarantee_budget_usd` is
    set equal to `guarantee_budget_total_usd`, `reserved_guarantee_budget_usd` and
    `committed_guarantee_total_usd` are both `0.00`, and `active_onboarding_count` is `0`.

    Design: Corner/entities/practice_group_read_returns_the_initialized_guarantee_ledger
    """
    group = new_practice_group()

    read = validate_success(api_client.get_practice_group(group["id"], ADMIN))

    assert read["status"] == "OPEN"
    assert_money_equals(read["guarantee_budget_total_usd"], 5000000.00, "budget total")
    assert_money_equals(read["available_guarantee_budget_usd"], 5000000.00, "available")
    assert_money_equals(read["reserved_guarantee_budget_usd"], 0.00, "reserved")
    assert_money_equals(read["committed_guarantee_total_usd"], 0.00, "committed")
    assert read["active_onboarding_count"] == 0
    assert read["onboarding_capacity"] == 2
    assert_money_equals(read["leverage_ratio"], 3.20, "leverage_ratio")
    assert_money_equals(read["target_standard_rate_usd"], 950.00, "target rate")


def test_the_client_book_listing_pages_the_filtered_total_not_the_page_size():
    """The `meta` object of every list response carries `limit`, `offset`, `total_count` —
    the number of records matching the filters across all pages, not merely the number
    returned on this page — and `has_more`, a boolean that is true exactly when records
    matching the filters remain beyond the current page.

    Design: Corner/entities/client_book_entry_listing_paginates_and_filters_by_questionnaire
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "FULL")

    page_one, meta_one = validate_paginated(
        api_client.list_client_book_entries(
            COORDINATOR,
            params={
                "questionnaire_id": ctx["questionnaire"]["id"],
                "status": "ACTIVE",
                "limit": 2,
                "offset": 0,
            },
        )
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api_client.list_client_book_entries(
            COORDINATOR,
            params={
                "questionnaire_id": ctx["questionnaire"]["id"],
                "status": "ACTIVE",
                "limit": 2,
                "offset": 2,
            },
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2

    assert read_questionnaire(ctx["questionnaire"]["id"])["entry_count"] == 3


def test_reading_a_candidate_that_does_not_exist_reports_the_candidate_not_found_code():
    """**Existence** — every path-templated resource is resolved **left to right in path
    order**, and only then are body-referenced foreign keys resolved, in the order the
    endpoint's input list declares them.

    Design: Corner/entities/candidate_read_with_unknown_uuid_returns_not_found
    """
    ctx = setup_approached_candidate()

    response = api_client.get_candidate(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_CANDIDATE_NOT_FOUND.value)

    real = validate_success(api_client.get_candidate(ctx["candidate"]["id"], COORDINATOR))
    assert real["pipeline_status"] == "APPROACHED"


def test_a_candidate_create_missing_its_notice_period_is_a_schema_violation():
    """**Schema** — required body fields present, types correct, enum members recognised,
    numeric ranges honoured, array cardinalities honoured, ISO 8601 datetimes parseable,
    and pagination `limit` within 1 through 100 with `offset` at least 0. Failure:
    `ERR_INVALID_REQUEST` (400). Applies to every endpoint.

    Design: Corner/entities/candidate_create_without_notice_period_days_rejected
    """
    ctx = setup_config()

    payload = create_candidate_payload(
        ctx["practice_group"]["id"], ctx["engagement"]["id"]
    )
    del payload["notice_period_days"]

    response = api_client.create_candidate(payload, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _rows, meta = validate_paginated(api_client.list_candidates(COORDINATOR))
    assert meta["total_count"] == 0


def test_the_omitted_consent_status_and_confidential_flag_take_their_declared_defaults():
    """optionally a `client_consent_status` of `CONSENT_PENDING` or `CONSENT_CONFIRMED`,
    defaulting to `CONSENT_PENDING` when omitted
    and optionally `approach_confidential`, which defaults to true when omitted
    A new entry lands with `status` `ACTIVE`, `portable_status` `UNVALIDATED`,
    `baseline_portable_amount_usd` and `validated_portable_amount_usd` both `0.00`, and
    `verified_record_count` `0`; it increments the questionnaire's `entry_count` by 1, and
    it turns any assessment on that questionnaire whose `status` is `CURRENT` to `STALE`,
    because the book it valued has just grown.
    The `approach_confidential` flag is retained exactly as it was recorded at creation;
    the approach step never rewrites it.

    Design: Corner/entities/omitted_consent_status_and_confidential_flag_take_their_declared_defaults
    """
    ctx = _setup_questionnaire_without_the_optional_flags()

    payload = create_client_book_entry_payload()
    del payload["client_consent_status"]

    entry = validate_success(
        api_client.create_client_book_entry(
            ctx["questionnaire"]["id"], payload, ctx["candidate_headers"]
        ),
        expected_status=201,
    )

    assert entry["client_consent_status"] == "CONSENT_PENDING"
    assert entry["status"] == "ACTIVE"
    assert entry["portable_status"] == "UNVALIDATED"
    assert_money_equals(entry["baseline_portable_amount_usd"], 0.00, "baseline amount")
    assert_money_equals(entry["validated_portable_amount_usd"], 0.00, "validated amount")
    assert entry["verified_record_count"] == 0

    candidate = validate_success(
        api_client.get_candidate(ctx["candidate"]["id"], COORDINATOR)
    )
    assert candidate["approach_confidential"] is True


def test_the_firms_engagement_count_tracks_every_engagement_row_naming_it():
    """A new firm's `engagement_count` begins at `0` and thereafter counts every
    engagement row naming that firm, in any status whatsoever.

    Design: Corner/entities/search_firm_engagement_count_is_derived_from_its_engagements
    """
    firm = new_search_firm(max_concurrent_engagements=2)
    assert firm["engagement_count"] == 0

    group_one = new_practice_group()
    group_two = new_practice_group(name="Litigation")
    new_engagement(firm["id"], group_one["id"], tail_off_days=0)

    second = validate_success(
        api_client.create_search_firm_engagement(
            create_engagement_payload(
                firm["id"],
                group_two["id"],
                fee_pct=0.3000,
                fee_cap_usd=300000.00,
                exclusivity_start_date="2026-12-01T00:00:00.000Z",
                exclusivity_end_date="2027-04-01T00:00:00.000Z",
                tail_off_days=0,
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert second["status"] == "ACTIVE"
    assert second["fee_status"] == "NOT_DUE"
    assert second["fee_basis"] == "NONE"

    read_firm = validate_success(api_client.get_search_firm(firm["id"], COORDINATOR))
    assert read_firm["engagement_count"] == 2
    assert read_firm["max_concurrent_engagements"] == 2


def test_the_drafting_chairs_user_id_is_stamped_on_the_offer_it_creates():
    """The new offer records the acting chair's `X-User-ID` in `created_by_user_id`, lands
    with `status` `DRAFTED` and `round_number` `1`, and starts with `eligible_voter_count`
    null and all three vote counters — `votes_cast_total`, `active_vote_count`,
    `voided_vote_count` — at `0`.

    Design: Corner/entities/offer_create_stamps_created_by_user_id_from_the_request_header
    """
    ctx = setup_cleared_candidate("SLIM")

    offer = draft_offer(ctx)

    assert offer["created_by_user_id"] == "user-chair-1"
    assert offer["status"] == "DRAFTED"
    assert offer["round_number"] == 1
    assert offer["eligible_voter_count"] is None
    assert offer["votes_cast_total"] == 0
    assert offer["active_vote_count"] == 0
    assert offer["voided_vote_count"] == 0
    assert offer["accepted_at"] is None
    assert offer["version"] == 1


def test_an_unrecognised_role_and_an_out_of_band_percentage_are_both_schema_failures():
    """The payload carries a `client_name` of 1 to 120 characters; a `relationship_role` of
    `BILLING_ATTORNEY`, `RELATIONSHIP_PARTNER`, or `SERVICE_PARTNER`; optionally a
    `client_consent_status` of `CONSENT_PENDING` or `CONSENT_CONFIRMED`, defaulting to
    `CONSENT_PENDING` when omitted; a `claimed_annual_billings_usd` greater than zero
    carried to two decimal places; a `claimed_portability_pct` greater than zero and no
    more than `1.0000` carried to four decimal places; a `claimed_realization_rate` greater
    than zero and no more than `1.0000` carried to four decimal places; and `matter_types`,
    an array of 1 to 6 distinct strings each 1 to 60 characters.

    Design: Corner/entities/client_book_entry_create_with_unknown_relationship_role_rejected
    """
    ctx = setup_questionnaire_in_draft()

    bad_enum = api_client.create_client_book_entry(
        ctx["questionnaire"]["id"],
        create_client_book_entry_payload(
            relationship_role="OF_COUNSEL", matter_types=["M_AND_A"]
        ),
        ctx["candidate_headers"],
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value)

    bad_range = api_client.create_client_book_entry(
        ctx["questionnaire"]["id"],
        create_client_book_entry_payload(
            claimed_portability_pct=1.2000, matter_types=["M_AND_A"]
        ),
        ctx["candidate_headers"],
    )
    validate_error(bad_range, ApiErrorId.ERR_INVALID_REQUEST.value)

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["entry_count"] == 0
    assert questionnaire["status"] == "DRAFT"


def test_a_collection_record_reads_back_without_a_version_or_an_updated_at():
    """There is one exception: a `CollectionRecord` is an append-only observation. It
    carries only `id` and `created_at` — both `updated_at` and `version` are absent from
    its representation, because the row is never modified after it is written, has no
    update endpoint and no delete endpoint.

    Design: Corner/entities/collection_record_is_an_append_only_event_row
    """
    ctx = setup_questionnaire_in_draft()
    entry = validate_success(
        api_client.create_client_book_entry(
            ctx["questionnaire"]["id"],
            create_client_book_entry_payload(),
            ctx["candidate_headers"],
        ),
        expected_status=201,
    )

    created = validate_success(
        api_client.create_collection_record(
            ctx["candidate"]["id"],
            create_collection_record_payload(
                entry["id"],
                record_type="HISTORICAL",
                period_end_date="2025-12-31T00:00:00.000Z",
                amount_usd=1410000.00,
                status="VERIFIED",
                source="PRIOR_FIRM_STATEMENT",
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )

    read = validate_success(
        api_client.get_collection_record(created["id"], COORDINATOR)
    )
    assert read["record_type"] == "HISTORICAL"
    assert read["status"] == "VERIFIED"
    assert "version" not in read
    assert "updated_at" not in read
    assert_append_only_fields(read, "CollectionRecord")
    assert read["candidate_id"] == ctx["candidate"]["id"]
    assert read["client_book_entry_id"] == entry["id"]


def test_an_unknown_parent_questionnaire_is_reported_before_any_ownership_test():
    """So a request against a questionnaire's client book entries under an unknown
    `questionnaire_id` reports `ERR_QUESTIONNAIRE_NOT_FOUND`, never a client-book error.

    Design: Corner/entities/client_book_entry_create_under_unknown_questionnaire_returns_404
    """
    ctx = setup_questionnaire_in_draft()

    response = api_client.create_client_book_entry(
        NON_EXISTENT_UUID,
        create_client_book_entry_payload(),
        ctx["candidate_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_QUESTIONNAIRE_NOT_FOUND.value)
    assert error["error_id"] != ApiErrorId.ERR_NOT_RESOURCE_OWNER.value

    assert read_questionnaire(ctx["questionnaire"]["id"])["entry_count"] == 0


def test_a_post_hire_row_carries_no_entry_pointer_and_still_lists_under_its_candidate():
    """That last field is left null for post-hire firm-ledger rows that do not correspond
    to any declared client line.

    Design: Corner/entities/collection_record_binds_two_independent_aggregates_consistently
    """
    ctx = setup_questionnaire_in_draft()
    entry = validate_success(
        api_client.create_client_book_entry(
            ctx["questionnaire"]["id"],
            create_client_book_entry_payload(),
            ctx["candidate_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api_client.create_collection_record(
            ctx["candidate"]["id"],
            create_collection_record_payload(entry["id"]),
            COORDINATOR,
        ),
        expected_status=201,
    )

    bogus = api_client.create_collection_record(
        ctx["candidate"]["id"],
        create_collection_record_payload(NON_EXISTENT_UUID),
        COORDINATOR,
    )
    validate_error(bogus, ApiErrorId.ERR_CLIENT_BOOK_ENTRY_NOT_FOUND.value)

    post_hire = validate_success(
        api_client.create_collection_record(
            ctx["candidate"]["id"],
            create_collection_record_payload(
                record_type="POST_HIRE",
                period_end_date="2027-03-31T00:00:00.000Z",
                amount_usd=250000.00,
                status="VERIFIED",
                source="FIRM_LEDGER",
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert post_hire["client_book_entry_id"] is None
    assert post_hire["record_type"] == "POST_HIRE"

    _by_entry, entry_meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR, params={"client_book_entry_id": entry["id"]}
        )
    )
    assert entry_meta["total_count"] == 1

    _by_candidate, candidate_meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR, params={"candidate_id": ctx["candidate"]["id"]}
        )
    )
    assert candidate_meta["total_count"] == 2


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_questionnaire_without_the_optional_flags():
    """A candidate opened without `approach_confidential`, approached, with a DRAFT
    questionnaire and an empty book."""
    ctx = setup_config()

    payload = create_candidate_payload(
        ctx["practice_group"]["id"], ctx["engagement"]["id"]
    )
    del payload["approach_confidential"]
    ctx["candidate"] = validate_success(
        api_client.create_candidate(payload, COORDINATOR), expected_status=201
    )
    ctx["candidate_headers"] = make_candidate_headers(ctx["candidate"]["id"])
    ctx["candidate"] = validate_success(
        api_client.approach_candidate(ctx["candidate"]["id"], COORDINATOR)
    )
    ctx["questionnaire"] = validate_success(
        api_client.create_questionnaire(
            ctx["candidate"]["id"], create_questionnaire_payload(), COORDINATOR
        ),
        expected_status=201,
    )
    ctx["entries"] = {}
    ctx["records"] = []
    return ctx
