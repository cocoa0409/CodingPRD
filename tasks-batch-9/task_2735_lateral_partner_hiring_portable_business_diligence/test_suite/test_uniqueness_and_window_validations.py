"""Two validation families that both hinge on what the store already holds: client-name
uniqueness scoped to live rows, and the window-sanity rule across three endpoints."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_money_equals,
    create_assessment_payload,
    create_client_book_entry_payload,
    create_conflict_waiver_payload,
    create_engagement_payload,
    open_conflict_check,
    read_client_book_entry,
    read_conflict_check,
    read_questionnaire,
    setup_book,
    setup_questionnaire_in_draft,
    setup_questionnaire_under_review,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]

DUPLICATE_ENTRY = {
    "client_name": "Northwind Holdings",
    "relationship_role": "SERVICE_PARTNER",
    "client_consent_status": "CONSENT_PENDING",
    "claimed_annual_billings_usd": 100000.00,
    "claimed_portability_pct": 0.5000,
    "claimed_realization_rate": 0.9000,
    "matter_types": ["TAX"],
}


def test_a_client_name_collides_only_while_the_earlier_row_is_still_active():
    """Within one questionnaire, `client_name` must be unique among entries whose `status`
    is `ACTIVE`; a collision is refused with `ERR_DUPLICATE_CLIENT_ENTRY`. A withdrawn
    entry's name is therefore reusable. A new entry lands with `status` `ACTIVE`,
    `portable_status` `UNVALIDATED`, `baseline_portable_amount_usd` and
    `validated_portable_amount_usd` both `0.00`, and `verified_record_count` `0`; it
    increments the questionnaire's `entry_count` by 1, and it turns any assessment on that
    questionnaire whose `status` is `CURRENT` to `STALE`, because the book it valued has
    just grown.
    Soft-deleting an entry sets its `status` to `WITHDRAWN`, decrements the questionnaire's
    `entry_count` by 1, and likewise turns any `CURRENT` assessment on that questionnaire
    `STALE`.

    Design: Corner/validations/duplicate_client_name_collides_only_with_active_rows
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "SLIM")
    entry_a_id = ctx["entries"]["Northwind Holdings"]["id"]
    assert read_questionnaire(ctx["questionnaire"]["id"])["entry_count"] == 1

    collision = api_client.create_client_book_entry(
        ctx["questionnaire"]["id"],
        create_client_book_entry_payload(**DUPLICATE_ENTRY),
        ctx["candidate_headers"],
    )
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_CLIENT_ENTRY.value)

    validate_success(
        api_client.delete_client_book_entry(entry_a_id, ctx["candidate_headers"])
    )

    replay = validate_success(
        api_client.create_client_book_entry(
            ctx["questionnaire"]["id"],
            create_client_book_entry_payload(**DUPLICATE_ENTRY),
            ctx["candidate_headers"],
        ),
        expected_status=201,
    )

    withdrawn = read_client_book_entry(entry_a_id)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["client_name"] == "Northwind Holdings"

    fresh = read_client_book_entry(replay["id"])
    assert fresh["status"] == "ACTIVE"
    assert fresh["portable_status"] == "UNVALIDATED"
    assert fresh["verified_record_count"] == 0
    assert_money_equals(
        fresh["baseline_portable_amount_usd"], 0.00, "baseline_portable_amount_usd"
    )
    assert_money_equals(
        fresh["validated_portable_amount_usd"], 0.00, "validated_portable_amount_usd"
    )

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["entry_count"] == 1
    assert questionnaire["status"] == "DRAFT"


def test_degenerate_and_wrong_side_of_the_clock_instants_all_fail_window_sanity():
    """Separately, the requested `fee_pct` must not exceed the firm's `max_fee_pct`, or the
    create is refused with `ERR_FEE_PCT_ABOVE_FIRM_MAX`; and `exclusivity_end_date` must be
    strictly later than `exclusivity_start_date`, or the create is refused with
    `ERR_LOOKBACK_WINDOW_INVALID`.
    The `baseline_date` is the **exclusive** upper bound of the evidence window, and it may
    not lie in the future — a `baseline_date` later than the current logical clock is
    refused with `ERR_LOOKBACK_WINDOW_INVALID`.
    A counsel opens a `ConflictWaiver` — a waiver, below — on a `PENDING` check, supplying a
    `waiver_strategy` of `ADVANCE_CONSENT`, `ETHICAL_WALL`, or `MATTER_CARVE_OUT`, a
    `requested_from_client` name of 1 to 120 characters, and a `response_deadline_date` that
    must be strictly later than the current logical clock — a deadline already in the past is
    refused with `ERR_LOOKBACK_WINDOW_INVALID`.

    Design: Corner/validations/window_sanity_rejects_degenerate_and_future_dated_ranges
    """
    ctx = setup_questionnaire_under_review("SLIM")
    check = open_conflict_check(ctx, "Northwind Holdings")
    questionnaire_version = read_questionnaire(ctx["questionnaire"]["id"])["version"]

    degenerate = api_client.create_search_firm_engagement(
        create_engagement_payload(
            ctx["search_firm"]["id"],
            ctx["practice_group"]["id"],
            exclusivity_start_date="2027-03-01T00:00:00.000Z",
            exclusivity_end_date="2027-03-01T00:00:00.000Z",
        ),
        COORDINATOR,
    )
    validate_error(degenerate, ApiErrorId.ERR_LOOKBACK_WINDOW_INVALID.value)

    future_baseline = api_client.create_portability_assessment(
        ctx["questionnaire"]["id"],
        create_assessment_payload(
            questionnaire_version, baseline_date="2026-09-01T00:00:00.000Z"
        ),
        COORDINATOR,
    )
    validate_error(future_baseline, ApiErrorId.ERR_LOOKBACK_WINDOW_INVALID.value)

    deadline_on_the_clock = api_client.create_conflict_waiver(
        check["id"],
        create_conflict_waiver_payload(
            requested_from_client="Northwind Holdings",
            response_deadline_date="2026-08-01T00:00:00.000Z",
        ),
        COUNSEL,
    )
    validate_error(deadline_on_the_clock, ApiErrorId.ERR_LOOKBACK_WINDOW_INVALID.value)

    assessment = validate_success(
        api_client.create_portability_assessment(
            ctx["questionnaire"]["id"],
            create_assessment_payload(
                questionnaire_version, baseline_date="2026-07-01T00:00:00.000Z"
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert assessment["status"] == "CURRENT"
    assert_instant_equals(
        assessment["baseline_date"], "2026-07-01T00:00:00.000Z", "baseline_date"
    )
    assert_instant_equals(
        assessment["lookback_start_date"],
        "2023-07-01T00:00:00.000Z",
        "lookback_start_date",
    )
    assert_money_equals(
        assessment["gross_baseline_total_usd"], 1269000.00, "gross_baseline_total_usd"
    )

    firm = validate_success(
        api_client.get_search_firm(ctx["search_firm"]["id"], COORDINATOR)
    )
    assert firm["engagement_count"] == 1
    assert read_conflict_check(check["id"])["status"] == "PENDING"
