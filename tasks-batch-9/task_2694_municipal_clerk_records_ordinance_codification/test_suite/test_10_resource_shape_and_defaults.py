"""The declared shape of the resources themselves: which inputs are optional,
which fields the server mints, which are derived from children, and what the
surface answers when an identifier was never issued.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    CITY_CLERK,
    CODIFICATION_EDITOR,
    RECORDS_OFFICER,
)


def test_a_new_venue_takes_the_declared_buffer_and_availability_defaults():
    """A room registered with only its name, address and capacity comes back with
    a half-hour teardown buffer, open for business, at version 1.

    PRD 3.1: "`teardown_buffer_minutes` is the number of minutes appended to the
    **end** of every meeting occupation of that room before another body may
    occupy it; it defaults to 30 minutes and may be set anywhere from 0 up to and
    including 240 minutes — four hours — for chambers that need to be reconfigured
    between bodies."

    Design: Corner/entities/create_venue_with_required_fields_returns_201_with_defaults
    """
    created = validate_success(
        api_client.create_venue(
            {"name": "Council Chamber", "address": "1 Civic Plaza", "capacity": 120},
            CITY_CLERK,
        ),
        201,
    )

    a.assert_fields(
        created,
        name="Council Chamber",
        capacity=120,
        teardown_buffer_minutes=30,
        status="AVAILABLE",
        version=1,
    )
    a.assert_common_fields(created)


def test_a_number_series_reads_back_the_minting_state_creation_stored():
    """Opening the 2026 ordinance book at sequence 5 and reading it back returns
    the same sequence, nothing minted yet, and the book still open.

    PRD 3.5: "The clerk may optionally supply `next_sequence` to start the series
    at a number other than 1; left unset it starts at 1."

    Design: Corner/entities/read_number_series_returns_the_stored_minting_state
    """
    series = fx.create_number_series(next_sequence=5)

    read = validate_success(api_client.get_number_series(series["id"], CITY_CLERK))

    a.assert_fields(
        read,
        series_year=2026,
        instrument_class="ORDINANCE",
        prefix="ORD",
        next_sequence=5,
        minted_count=0,
        status="OPEN",
    )


def test_the_meeting_list_pages_by_limit_and_offset_with_a_stable_total():
    """Three sittings in one room page two-then-one, and the total stays 3 across
    both pages while has_more turns over.

    PRD 2.3: "`total_count` reports the number of records matching the filters
    before pagination is applied, and `has_more` is true exactly when records
    matching the filters remain beyond the current page."

    Design: Corner/entities/list_meetings_paginates_with_total_count_and_has_more
    """
    venue = fx.create_venue()
    for start, end in (
        ("2026-09-01T18:00:00Z", "2026-09-01T21:00:00Z"),
        ("2026-09-15T18:00:00Z", "2026-09-15T21:00:00Z"),
        ("2026-10-06T18:00:00Z", "2026-10-06T21:00:00Z"),
    ):
        fx.create_meeting(venue["id"], scheduled_start=start, scheduled_end=end)

    first_rows, first_meta = validate_paginated(
        api_client.list_meetings(
            CITY_CLERK, {"venue_id": venue["id"], "limit": 2, "offset": 0}
        )
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_meetings(
            CITY_CLERK, {"venue_id": venue["id"], "limit": 2, "offset": 2}
        )
    )

    assert len(first_rows) == 2, f"expected a full first page, got {first_rows}"
    a.assert_pagination_meta(
        first_meta, total_count=3, has_more=True, limit=2, offset=0
    )
    assert len(second_rows) == 1, f"expected a short second page, got {second_rows}"
    a.assert_pagination_meta(
        second_meta, total_count=3, has_more=False, limit=2, offset=2
    )
    a.assert_ascending_by(first_rows, "created_at")


def test_reading_a_meeting_that_was_never_issued_is_a_meeting_not_found():
    """The meeting path variable has its own not-found code.

    PRD 2.6: "The path variables the surface uses are `venue_id`, `meeting_id`,
    `packet_id`, `item_id`, `minutes_id`, `motion_id`, `instrument_id`,
    `notice_id`, `title_id`, `cycle_id`, `submission_id`, `request_id`,
    `series_id` and `batch_id`, and each has its own not-found code:
    `ERR_VENUE_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`,
    `ERR_AGENDA_ITEM_NOT_FOUND`, `ERR_MOTION_NOT_FOUND`, `ERR_MINUTES_NOT_FOUND`,
    `ERR_NUMBER_SERIES_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`,
    `ERR_NOTICE_NOT_FOUND`, `ERR_CODE_TITLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_SERIES_NOT_FOUND`
    and `ERR_BATCH_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/get_meeting_with_unknown_id_returns_meeting_not_found
    """
    response = api_client.get_meeting(NON_EXISTENT_UUID, CITY_CLERK)

    validate_error(response, ApiErrorId.MEETING_NOT_FOUND.value, 404)


def test_a_meeting_without_a_quorum_figure_is_refused_and_nothing_is_scheduled():
    """`quorum_required` has no default, so a booking that omits it is a shape
    failure and the calendar stays empty.

    PRD 3.1: "The clerk supplies the `body_type` of the governing body that will
    meet — `COUNCIL`, `PLANNING_COMMISSION` or `BOARD_OF_ADJUSTMENT` — the
    statutory `meeting_type`, which is one of `REGULAR`, `SPECIAL`, `EMERGENCY` or
    `WORKSHOP`, the `venue_id` of the room, the `scheduled_start` and
    `scheduled_end` instants in ISO 8601 UTC, and `quorum_required`, the minimum
    number of members that must be present to convene, which must be at least 1."

    Design: Corner/entities/create_meeting_missing_quorum_required_is_rejected_as_invalid_request
    """
    venue = fx.create_venue()

    response = api_client.create_meeting(
        {
            "body_type": "COUNCIL",
            "meeting_type": "REGULAR",
            "venue_id": venue["id"],
            "scheduled_start": "2026-09-15T18:00:00Z",
            "scheduled_end": "2026-09-15T21:00:00Z",
        },
        CITY_CLERK,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)
    _, meta = validate_paginated(
        api_client.list_meetings(CITY_CLERK, {"venue_id": venue["id"]})
    )
    a.assert_pagination_meta(meta, total_count=0)


def test_a_record_series_filed_without_its_optional_flags_takes_the_defaults():
    """A schedule item filed with only its four required inputs is not permanent,
    is under no hold, holds nothing, and has no anchor to compute from.

    PRD 3.9: "A new series starts with `total_accessioned_count`,
    `active_item_count` and `destroyed_item_count` all at 0, `last_accessioned_on`
    null, and `eligible_through_on` null, because no anchor exists yet."

    Design: Corner/entities/create_record_series_omitting_optional_flags_applies_declared_defaults
    """
    created = validate_success(
        api_client.create_record_series(
            {
                "series_code": "CC-01",
                "name": "Council correspondence",
                "retention_years": 5,
                "retention_trigger": "CREATION",
            },
            RECORDS_OFFICER,
        ),
        201,
    )

    a.assert_fields(created, permanent=False, legal_hold_status="NONE")
    a.assert_custody_triple(created, total=0, active=0, destroyed=0)
    a.assert_nulls(created, "last_accessioned_on", "eligible_through_on")


def test_the_packets_counters_are_derived_from_its_items_not_supplied():
    """Creation accepts no counters at all, and both of them move purely as a
    consequence of printing items onto the agenda.

    PRD 2.10: "`AgendaPacket.item_count` and `AgendaPacket.contains_public_hearing`
    are derived from the packet's items."

    Design: Corner/entities/packet_computed_fields_are_derived_not_supplied
    """
    base = fx.scheduled_meeting()
    packet = fx.draft_packet(base["meeting"]["id"])
    a.assert_fields(
        packet,
        revision_number=1,
        item_count=0,
        contains_public_hearing=False,
        late_addendum=False,
        notice_compliant=False,
        status="DRAFT",
    )
    a.assert_nulls(packet, "posted_at")

    fx.add_item(packet["id"], 1, "REPORT", title="Quarterly finance report")
    fx.add_item(
        packet["id"], 2, "PUBLIC_HEARING", title="Public hearing on the Elm Street rezoning"
    )

    after = fx.read_packet(packet["id"])
    a.assert_fields(
        after, item_count=2, contains_public_hearing=True, status="DRAFT"
    )


def test_identity_and_version_are_minted_by_the_server_for_a_new_code_title():
    """Nothing about the title's identity, timestamps, version or supplement state
    is client input.

    PRD 2.5: "Most resources additionally carry `updated_at`, in the same
    timestamp format, and `version`, an integer that begins at 1 when the record
    is created and increases by exactly 1 on every mutation of that record."

    Design: Corner/entities/system_fields_are_server_generated_and_client_input_is_ignored
    """
    created = validate_success(
        api_client.create_code_title(
            {"title_number": 12, "name": "Streets, Sidewalks and Public Places"},
            CODIFICATION_EDITOR,
        ),
        201,
    )

    a.assert_common_fields(created)
    a.assert_initial_version(created)
    a.assert_fields(created, current_supplement_number=0, status="ACTIVE")
    a.assert_section_refs(created, [])


def test_an_unknown_body_type_and_a_zero_length_window_are_both_invalid_requests():
    """Enum membership and the start-before-end pairing are reported by the same
    single shape code, and neither booking is recorded.

    PRD 2.6: "Only after every identifier resolves does the service validate
    request shape — required fields present, enum values inside their declared
    sets, numeric ranges honoured, dates well formed — reporting
    `ERR_INVALID_REQUEST` (HTTP 422) for any failure."

    Design: Corner/entities/create_meeting_with_an_invalid_body_type_enum_is_rejected
    """
    venue = fx.create_venue()

    bad_enum = api_client.create_meeting(
        f.meeting_payload(venue["id"], body_type="SCHOOL_BOARD"), CITY_CLERK
    )
    empty_window = api_client.create_meeting(
        f.meeting_payload(
            venue["id"],
            scheduled_start="2026-09-15T18:00:00Z",
            scheduled_end="2026-09-15T18:00:00Z",
        ),
        CITY_CLERK,
    )

    validate_error(bad_enum, ApiErrorId.INVALID_REQUEST.value, 422)
    validate_error(empty_window, ApiErrorId.INVALID_REQUEST.value, 422)
    _, meta = validate_paginated(
        api_client.list_meetings(CITY_CLERK, {"venue_id": venue["id"]})
    )
    a.assert_pagination_meta(meta, total_count=0)


def test_an_agenda_item_carries_no_version_and_its_sequence_number_cannot_be_reused():
    """The printed item is the one resource without a version, and its printed
    order is unique inside its packet.

    PRD 2.5: "An agenda item is immutable once printed: it carries only `id` and
    `created_at`, and both `updated_at` and `version` are **absent** from it."

    Design: Corner/entities/agenda_item_is_immutable_with_no_update_endpoint_and_no_version_field
    """
    base = fx.scheduled_meeting()
    packet = fx.draft_packet(base["meeting"]["id"])
    item = fx.add_item(packet["id"], 1, "REPORT", title="Quarterly finance report")

    read = validate_success(api_client.get_agenda_item(item["id"], CITY_CLERK))
    duplicate = api_client.create_agenda_item(
        packet["id"],
        f.agenda_item_payload(1, "CONSENT", title="Consent calendar"),
        CITY_CLERK,
    )

    a.assert_common_fields(read, versioned=False)
    a.assert_fields(read, title="Quarterly finance report", item_type="REPORT")
    validate_error(duplicate, ApiErrorId.DUPLICATE_SEQUENCE_NUMBER.value, 422)
    _, meta = validate_paginated(
        api_client.list_agenda_items(CITY_CLERK, {"packet_id": packet["id"]})
    )
    a.assert_pagination_meta(meta, total_count=1)


def test_an_item_filed_under_an_unknown_packet_fails_on_the_parent_first():
    """The packet in the path is resolved before the body is inspected, so an
    invalid item_type never gets a chance to be reported.

    PRD 2.6: "Nested paths are resolved strictly left to right. A request to a
    path that names a parent and a child resolves the parent first, and if the
    parent does not exist the request fails on the parent even when the child
    identifier is also unknown."

    Design: Corner/entities/create_agenda_item_under_an_unknown_packet_returns_packet_not_found
    """
    response = api_client.create_agenda_item(
        NON_EXISTENT_UUID,
        {"sequence_number": 1, "item_type": "NOT_A_TYPE", "title": "Orphan item"},
        CITY_CLERK,
    )

    body = validate_error(response, ApiErrorId.PACKET_NOT_FOUND.value, 404)
    assert body["error_id"] != ApiErrorId.INVALID_REQUEST.value


def test_one_motion_binds_its_meeting_an_agenda_item_and_another_meetings_minutes():
    """A minutes-approval motion sits in the October register, under an October
    agenda item, pointed at the September minutes, and carries no instrument.

    PRD 3.3: "Optionally the motion names the `agenda_item_id` of the agenda item
    it was moved under."

    Design: Corner/entities/motion_binds_meeting_instrument_and_minutes_across_three_aggregates
    """
    september = fx.adjourned_meeting_with_minutes(7)
    minutes = fx.submitted_minutes(
        september["minutes"]["id"], "Minutes of 15 September 2026."
    )
    october = fx.additional_meeting_in_session(
        scheduled_start="2026-10-06T18:00:00Z",
        scheduled_end="2026-10-06T21:00:00Z",
        post_at="2026-10-03T18:00:00Z",
        convene_at="2026-10-06T18:00:00Z",
        present_member_count=7,
        item_types=["MINUTES"],
        venue_name="Annex Hearing Room",
        venue_address="9 Civic Plaza",
    )
    items, _ = validate_paginated(
        api_client.list_packet_agenda_items(october["packet"]["id"], CITY_CLERK)
    )
    agenda_item = items[0]

    moved = validate_success(
        api_client.create_motion(
            f.motion_payload(
                october["meeting"]["id"],
                "MINUTES_APPROVAL",
                "SIMPLE",
                agenda_item_id=agenda_item["id"],
                target_minutes_id=minutes["id"],
            ),
            CITY_CLERK,
        ),
        201,
    )

    a.assert_fields(
        moved,
        meeting_id=october["meeting"]["id"],
        agenda_item_id=agenda_item["id"],
        target_minutes_id=minutes["id"],
    )
    a.assert_nulls(moved, "instrument_id")
    _, by_minutes = validate_paginated(
        api_client.list_motions(CITY_CLERK, {"target_minutes_id": minutes["id"]})
    )
    a.assert_pagination_meta(by_minutes, total_count=1)
    _, by_item = validate_paginated(
        api_client.list_motions(CITY_CLERK, {"agenda_item_id": agenda_item["id"]})
    )
    a.assert_pagination_meta(by_item, total_count=1)
