"""What the server owns: enum ranges, append-only event rows, foreign-key order and secrets."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CLIENT_SUPPLIED_ID,
    UNKNOWN_CHANNEL_ID,
    UNKNOWN_FLIGHT_ID,
    UNKNOWN_JOB_FAMILY_ID_ALT,
    UNKNOWN_PERSONA_ID,
)
from test_helpers.test_users import (
    anonymous_headers,
    brand_lead_headers,
    community_manager_headers,
    media_buyer_headers,
    persona_researcher_headers,
    recruiting_ops_headers,
)


def test_an_out_of_range_rating_or_unknown_platform_is_refused_but_five_stars_is_not(api):
    """PRD §3.8: "Each `EmployerReview` names the program it is about, the `platform` it was
    observed on — one of `GLASSDOOR`, `INDEED` or `COMPARABLY` — an `external_ref` of 1 to 80
    characters that is the platform-side identifier and must be unique within that platform, a
    `rating` from 1 through 5 stars as published, and the `posted_at` instant of publication."
    PRD §3.8: "A rating of 1 or 2 gives 24 hours; a rating of exactly 3 gives 72 hours — three
    days; a rating of 4 or 5 gives 168 hours — a full week."
    PRD §3.8: "A new review is in `state` `NEW` with `sla_status` `PENDING`, `rejection_count` 0,
    `response_body` null, and `drafted_by_user_id`, `approved_by_user_id` and `responded_at` all
    null."

    Design: Corner/entities/create_employer_review_with_rating_out_of_range_returns_invalid_request
    """
    program = fx.create_program(api)

    too_many_stars = api.create_employer_review(
        f.review_payload(program["id"], external_ref="gd-1", rating=6, posted_at="2026-07-31T12:00:00Z"),
        community_manager_headers(),
    )
    unknown_platform = api.create_employer_review(
        f.review_payload(
            program["id"],
            platform="LINKEDIN",
            external_ref="li-1",
            rating=4,
            posted_at="2026-07-31T12:00:00Z",
        ),
        community_manager_headers(),
    )
    accepted = api.create_employer_review(
        f.review_payload(
            program["id"],
            platform="COMPARABLY",
            external_ref="cp-1",
            rating=5,
            posted_at="2026-07-31T12:00:00Z",
        ),
        community_manager_headers(),
    )

    validate_error(too_many_stars, ApiErrorId.INVALID_REQUEST, 422)
    validate_error(unknown_platform, ApiErrorId.INVALID_REQUEST, 422)
    review = validate_success(accepted, 201)
    assert review["rating"] == 5, review
    assert review["platform"] == "COMPARABLY", review
    assert review["state"] == "NEW", review
    assert review["sla_status"] == "PENDING", review
    assert review["rejection_count"] == 0, review
    assert review["response_body"] is None, review
    assert review["responded_at"] is None, review
    assert review["response_due_at"] == "2026-08-07T12:00:00.000Z", review
    a.assert_brand_health(fx.read_program(api, program["id"])["brand_health_score"], 100.00)


def test_an_ingested_touchpoint_is_an_append_only_row_without_a_version(api):
    """PRD §2.4: "Immutable event rows — `ChannelPreferenceSignal`, `Touchpoint`, `NurtureSend` and
    `BudgetLedgerEntry` — carry only `id` and `created_at`: for these four entity kinds `updated_at`
    and `version` are absent from the resource entirely, because the rows are written once and never
    edited."
    PRD §3.6: "A touchpoint is written with `credit_bp` 0; credit is assigned only when the owning
    application reaches `QUALIFIED`, and touchpoints are immutable event rows thereafter."

    Design: Corner/entities/touchpoint_is_immutable_and_exposes_no_version_field
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    posting = fx.published_posting(api, family["id"], channel["id"])
    application = fx.start_application(api, posting["id"], "immutable@example.com")

    created = api.create_touchpoint(
        f.touchpoint_payload(
            application["id"], channel["id"], "2026-07-30T08:00:00Z", touch_type="ORGANIC_VISIT"
        ),
        media_buyer_headers(),
    )
    read_back = api.get_touchpoint(validate_success(created, 201)["id"], recruiting_ops_headers())

    written = validate_success(created, 201)
    fetched = validate_success(read_back, 200)
    assert written["credit_bp"] == 0, written
    a.assert_cents(written["media_cost_cents"], 0, "media_cost_cents")
    assert written["media_flight_id"] is None, written
    for row in (written, fetched):
        a.assert_immutable_event_row(row)
        assert "updated_at" not in row, row
        assert "version" not in row, row
        assert is_valid_uuid(row["id"]), row
        assert is_iso8601_timestamp(row["created_at"]), row
    rows = fx.list_touchpoints(api, application_id=application["id"])
    assert [row["id"] for row in rows] == [written["id"]], rows


def test_body_foreign_keys_resolve_in_the_order_the_endpoint_declares_them(api):
    """PRD §2.8: "A request that supplies a path identifier resolves that identifier before anything
    else about the request body is considered, and where a request carries several identifiers they
    are resolved strictly left to right in the path and then in the order the fields appear in the
    endpoint's input list."
    PRD §3.3: "Each `ChannelPreferenceSignal` is submitted with a payload naming the persona it
    informs as `persona_id` and the channel it scores as `channel_id`, and carries a
    `preference_score` from 0 through 100 taken from the research instrument, a `sample_size` of at
    least 1 respondent, an optional `engagement_events` count of zero or more observed interactions
    defaulting to 0, and a `collected_at` instant."
    PRD §2.8: "A program identifier that does not resolve yields `ERR_PROGRAM_NOT_FOUND`; a job
    family identifier — including `interest_job_family_id` on a talent-community member — yields
    `ERR_JOB_FAMILY_NOT_FOUND`; a channel identifier yields `ERR_CHANNEL_NOT_FOUND`; a persona
    identifier yields `ERR_PERSONA_NOT_FOUND`; a posting identifier, including `job_posting_id`,
    yields `ERR_POSTING_NOT_FOUND`; a flight identifier, including `media_flight_id`, yields
    `ERR_FLIGHT_NOT_FOUND`; an application identifier, including `application_id`, yields
    `ERR_APPLICATION_NOT_FOUND`; a member identifier, including `member_id`, yields
    `ERR_MEMBER_NOT_FOUND`; a campaign identifier, including `campaign_id`, yields
    `ERR_CAMPAIGN_NOT_FOUND`; an employer-review identifier yields `ERR_REVIEW_NOT_FOUND`; an
    event-presence identifier yields `ERR_PRESENCE_NOT_FOUND`."

    Design: Corner/entities/body_foreign_keys_are_validated_in_declared_input_order
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    persona = fx.create_persona(api, family["id"])

    ghost_family = api.create_job_posting(
        f.posting_payload(UNKNOWN_JOB_FAMILY_ID_ALT, title="Ghost Role"), brand_lead_headers()
    )
    two_bad_keys = api.create_channel_preference_signal(
        f.signal_payload(UNKNOWN_PERSONA_ID, UNKNOWN_CHANNEL_ID), persona_researcher_headers()
    )

    validate_error(ghost_family, ApiErrorId.JOB_FAMILY_NOT_FOUND, 404)
    validate_error(two_bad_keys, ApiErrorId.PERSONA_NOT_FOUND, 404)
    assert fx.list_postings(api, job_family_id=family["id"]) == []
    unchanged = fx.read_persona(api, persona["id"])
    assert unchanged["signal_count"] == 0, unchanged
    assert unchanged["channel_mix"] == [], unchanged


def test_a_client_cannot_seed_a_channels_computed_counters(api):
    """PRD §3.2: "A new channel reports `spent_cents` 0, `credited_qualified_bp` 0,
    `active_flight_count` 0, `pacing_status` `PACING_UNKNOWN`, `idle_since` null, and both
    `blended_target_cents` and `cpqa_cents` null."
    PRD §2.6: "`committed_budget_cents` is the sum of `delta_cents` over every ledger entry of that
    program, and `available_budget_cents` is the sum of `pool_job_board_cents`, `pool_social_cents`,
    `pool_programmatic_cents`, `flex_reserve_cents` and the `dedicated_budget_cents` of every
    `JobFamily` belonging to that program, less `committed_budget_cents`."

    Design: Corner/entities/computed_fields_reject_client_values_supplied_as_an_extra_field
    """
    program = fx.create_program(api)

    response = api.create_channel(
        {
            "program_id": program["id"],
            "name": "Board A",
            "channel_type": "JOB_BOARD",
            "daily_capacity_cents": 100000,
            "spent_cents": 999999,
            "pacing_status": "ON_TARGET",
            "credited_qualified_bp": 5000,
        },
        brand_lead_headers(),
    )

    if response.status_code == 201:
        channel = validate_success(response, 201)
        a.assert_cents(channel["spent_cents"], 0, "spent_cents")
        assert channel["credited_qualified_bp"] == 0, channel
        assert channel["pacing_status"] == "PACING_UNKNOWN", channel
        assert channel["cpqa_cents"] is None, channel
        assert channel["blended_target_cents"] is None, channel
        a.assert_cents(channel["daily_capacity_cents"], 100000, "daily_capacity_cents")
    else:
        validate_error(response, ApiErrorId.INVALID_REQUEST, 422)
        assert fx.list_channels(api, program_id=program["id"]) == []
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        0,
        "committed_budget_cents",
    )


def test_the_server_mints_identities_and_the_consent_token_it_alone_accepts(api):
    """PRD §2.4: "Every resource the service persists is addressed by a server-minted `id`,
    formatted as a UUID with no type prefix of any kind."
    PRD §2.4: "Clients never supply an `id`; they supply foreign keys that reference ids already
    minted."
    PRD §3.7: "Confirmation is performed by an `Anonymous` visitor following the emailed link or by
    the `Candidate` themselves, and requires the request's `consent_token` to equal the stored
    `consent_token`, refusing a mismatch with `ERR_CONSENT_TOKEN_INVALID` (HTTP 422)."

    Design: Corner/entities/system_fields_are_server_generated_and_client_input_ignored
    """
    response = api.create_program(
        {
            "name": "Talent Brand FY26",
            "fiscal_year": 2026,
            "id": CLIENT_SUPPLIED_ID,
            "version": 99,
        },
        brand_lead_headers(),
    )

    if response.status_code == 201:
        program = validate_success(response, 201)
        assert program["id"] != CLIENT_SUPPLIED_ID, program
        assert program["version"] == 1, program
    else:
        validate_error(response, ApiErrorId.INVALID_REQUEST, 422)
        program = fx.create_program(api)

    joined = api.create_talent_community_member(
        {
            "program_id": program["id"],
            "email": "tokenpicker@example.com",
            "consent_token": "i-choose-this",
        },
        anonymous_headers(),
    )
    if joined.status_code == 201:
        member = validate_success(joined, 201)
    else:
        validate_error(joined, ApiErrorId.INVALID_REQUEST, 422)
        member = fx.join_community(api, program["id"], "tokenpicker@example.com")

    assert member["consent_token"] != "i-choose-this", member
    guessed = api.confirm_consent(
        member["id"], f.confirm_consent_payload("i-choose-this"), anonymous_headers()
    )
    validate_error(guessed, ApiErrorId.CONSENT_TOKEN_INVALID, 422)
    assert fx.read_member(api, member["id"])["consent_status"] == "PENDING_CONFIRMATION"
    confirmed = fx.confirm_member(api, member["id"], member["consent_token"])
    assert confirmed["consent_status"] == "SUBSCRIBED", confirmed


def test_an_unresolvable_flight_id_reports_the_flight_specific_not_found_code(api):
    """PRD §2.8: "A program identifier that does not resolve yields `ERR_PROGRAM_NOT_FOUND`; a job
    family identifier — including `interest_job_family_id` on a talent-community member — yields
    `ERR_JOB_FAMILY_NOT_FOUND`; a channel identifier yields `ERR_CHANNEL_NOT_FOUND`; a persona
    identifier yields `ERR_PERSONA_NOT_FOUND`; a posting identifier, including `job_posting_id`,
    yields `ERR_POSTING_NOT_FOUND`; a flight identifier, including `media_flight_id`, yields
    `ERR_FLIGHT_NOT_FOUND`; an application identifier, including `application_id`, yields
    `ERR_APPLICATION_NOT_FOUND`; a member identifier, including `member_id`, yields
    `ERR_MEMBER_NOT_FOUND`; a campaign identifier, including `campaign_id`, yields
    `ERR_CAMPAIGN_NOT_FOUND`; an employer-review identifier yields `ERR_REVIEW_NOT_FOUND`; an
    event-presence identifier yields `ERR_PRESENCE_NOT_FOUND`."
    PRD §2.9: "6. Every path identifier must resolve, left to right, with the per-kind codes of
    §2.8 (404)."

    Design: Corner/entities/get_unknown_media_flight_id_returns_flight_not_found
    """
    missing = api.get_media_flight(UNKNOWN_FLIGHT_ID, media_buyer_headers())

    validate_error(missing, ApiErrorId.FLIGHT_NOT_FOUND, 404)
    body = missing.json()["data"]
    assert isinstance(body["message"], str) and body["message"].strip(), body
    assert fx.list_flights(api) == []
