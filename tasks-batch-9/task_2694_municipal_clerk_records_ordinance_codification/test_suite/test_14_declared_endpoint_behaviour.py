"""What the individual endpoints answer: a partial revision that leaves the rest
of the record alone, an action that closes a book, a link that must line up on two
axes, a read that recomputes its money, a gate on the disposition, and a filter
that isolates one child collection from its sibling.
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
    DEPUTY_CLERK,
    RECORDS_OFFICER,
    make_requester_headers,
)

FLAT_LINE = [f.fee_line(page_count=40, staff_minutes=40, delivery_medium="PAPER")]
CLAIMS = ["attorney-client privilege", "active investigation"]


def test_revising_only_the_capacity_leaves_the_other_venue_attributes_standing():
    """The revision names one field, so the 45-minute buffer and the availability the
    room was registered with survive it, and only the version moves.

    PRD 3.1: "The clerk may later revise a venue's `capacity`,
    `teardown_buffer_minutes` or `status`; each such revision advances the venue's
    `version`."

    Design: Corner/endpoints/updating_a_venue_replaces_only_the_supplied_fields_and_bumps_the_version
    """
    created = fx.create_venue(teardown_buffer_minutes=45)

    updated = validate_success(
        api_client.update_venue(created["id"], {"capacity": 200}, CITY_CLERK)
    )
    read = validate_success(api_client.get_venue(created["id"], DEPUTY_CLERK))

    a.assert_fields(
        updated,
        capacity=200,
        teardown_buffer_minutes=45,
        status="AVAILABLE",
        name=created["name"],
        address=created["address"],
        created_at=created["created_at"],
    )
    a.assert_version_advanced_by(created, updated)
    for field in ("capacity", "teardown_buffer_minutes", "status", "name", "version"):
        assert read[field] == updated[field], (
            f"the read disagrees with the revision on {field}: "
            f"{read[field]} vs {updated[field]}"
        )


def test_closing_the_book_leaves_its_counters_alone_and_stops_the_next_introduction():
    """The close is a state change and nothing more: the sequence still stands at 5
    with nothing minted, yet the book will no longer back an ordinance.

    PRD 3.5: "The series must also be `OPEN`; introducing against a closed series is
    `ERR_NUMBER_SERIES_CLOSED` (HTTP 409)."

    Design: Corner/endpoints/closing_a_number_series_stops_it_backing_new_instruments
    """
    series = fx.create_number_series(next_sequence=5)

    closed = validate_success(
        api_client.close_number_series(series["id"], CITY_CLERK)
    )
    refused = api_client.create_instrument(
        f.ordinance_payload(series["id"]), CITY_CLERK
    )

    a.assert_fields(closed, status="CLOSED", next_sequence=5, minted_count=0)
    validate_error(refused, ApiErrorId.NUMBER_SERIES_CLOSED.value, 409)
    _, meta = validate_paginated(
        api_client.list_instruments(CITY_CLERK, {"number_series_id": series["id"]})
    )
    a.assert_pagination_meta(meta, total_count=0)


def test_the_submission_is_refused_until_the_cycle_and_the_section_both_line_up():
    """An unknown cycle is a resolution failure and a section the instrument does not
    cite is a shape failure; only the aligned pair is filed, and it is then reachable
    from either side of the link.

    PRD 3.7: "And the references must line up: the submission's `code_section_ref`
    must equal the instrument's own `code_section_ref`, and the instrument's
    `code_title_id` must equal the cycle's `code_title_id`, or the filing is
    `ERR_CODE_SECTION_UNKNOWN` (HTTP 422)."

    Design: Corner/endpoints/a_submission_links_a_cycle_and_an_instrument_and_both_must_line_up
    """
    number_series = fx.create_number_series()
    pair = fx.code_title_with_open_cycle()
    title_id = pair["code_title"]["id"]
    cycle_id = pair["cycle"]["id"]
    instrument = fx.create_code_amendment(
        number_series["id"], title_id, "12.04.030", title="Amending 12.04.030"
    )
    expected_version = fx.code_title_version(title_id)

    unknown_cycle = api_client.create_codification_submission(
        f.codification_submission_payload(
            NON_EXISTENT_UUID, instrument["id"], expected_version, "12.04.030", "ADD"
        ),
        CODIFICATION_EDITOR,
    )
    wrong_section = api_client.create_codification_submission(
        f.codification_submission_payload(
            cycle_id, instrument["id"], expected_version, "12.04.031", "ADD"
        ),
        CODIFICATION_EDITOR,
    )
    filed = validate_success(
        api_client.create_codification_submission(
            f.codification_submission_payload(
                cycle_id, instrument["id"], expected_version, "12.04.030", "ADD"
            ),
            CODIFICATION_EDITOR,
        ),
        201,
    )

    validate_error(unknown_cycle, ApiErrorId.CYCLE_NOT_FOUND.value, 404)
    validate_error(wrong_section, ApiErrorId.CODE_SECTION_UNKNOWN.value, 422)
    a.assert_fields(
        filed,
        cycle_id=cycle_id,
        instrument_id=instrument["id"],
        code_section_ref="12.04.030",
        action="ADD",
    )
    _, by_cycle = validate_paginated(
        api_client.list_codification_submissions(
            CODIFICATION_EDITOR, {"cycle_id": cycle_id}
        )
    )
    a.assert_pagination_meta(by_cycle, total_count=1)
    _, by_instrument = validate_paginated(
        api_client.list_codification_submissions(
            CODIFICATION_EDITOR, {"instrument_id": instrument["id"]}
        )
    )
    a.assert_pagination_meta(by_instrument, total_count=1)


def test_the_read_answers_with_a_ledger_that_reconciles_against_its_counters():
    """A 1375-cent flat assessment and a 375-cent part payment read back as four
    counters and two readings that agree with each other, on a disclosure axis the
    money never touched.

    PRD 3.8: "The ledger itself is four stored counters and two derived readings, and
    the derived readings are recomputed from the counters on **every** money-axis
    write rather than being patched incrementally."

    Design: Corner/endpoints/reading_a_request_returns_the_derived_ledger_not_stored_arithmetic
    """
    request = fx.assessed_request(
        FLAT_LINE,
        fee_schedule_variant="FLAT_SCHEDULE",
        subject_description="Ordinance files 2024",
    )
    validate_success(
        api_client.record_payment(
            request["id"], f.payment_payload(375), make_requester_headers(request["id"])
        )
    )

    read = validate_success(
        api_client.get_records_request(request["id"], RECORDS_OFFICER)
    )

    a.assert_fee_ledger(
        read,
        assessed=1375,
        waived=0,
        collected=375,
        refunded=0,
        balance=1000,
        net_cash=375,
    )
    a.assert_axes(read, fulfillment_status="UNDER_REVIEW", fee_status="DEPOSIT_HELD")
    a.assert_fields(read, due_on="2026-08-07", fee_schedule_variant="FLAT_SCHEDULE")
    a.assert_all_cents_integers(read)


def test_a_denial_needs_a_claim_on_the_file_not_merely_the_right_state():
    """Both files sit in exemption review and both denials cite a basis; the one whose
    review claimed nothing is refused, which shows the gate is the claim count.

    PRD 3.8: "A partial release or a denial attempted while `exemption_count` is 0 is
    refused with `ERR_DENIAL_WITHOUT_EXEMPTION` (HTTP 422)."

    Design: Corner/endpoints/a_denial_is_allowed_only_when_an_exemption_was_claimed
    """
    without_claims = fx.request_in_exemption_review(
        [], subject_description="Personnel investigation file"
    )
    with_claims = fx.request_in_exemption_review(
        CLAIMS, subject_description="Litigation hold correspondence"
    )

    refused = api_client.record_disposition(
        without_claims["id"],
        f.disposition_payload("DENIAL", denial_basis="Active investigation"),
        RECORDS_OFFICER,
    )
    denied = validate_success(
        api_client.record_disposition(
            with_claims["id"],
            f.disposition_payload("DENIAL", denial_basis="Attorney-client privilege"),
            RECORDS_OFFICER,
        )
    )

    validate_error(refused, ApiErrorId.DENIAL_WITHOUT_EXEMPTION.value, 422)
    standing = fx.read_records_request(without_claims["id"])
    a.assert_fields(standing, fulfillment_status="EXEMPTION_REVIEW", exemption_count=0)
    a.assert_nulls(standing, "denial_basis")
    a.assert_fields(
        denied,
        fulfillment_status="DENIED",
        exemption_count=2,
        denial_basis="Attorney-client privilege",
    )


def test_the_item_filter_returns_one_revisions_agenda_and_not_the_others():
    """The superseded revision's two items are still on file and still readable, but a
    filtered read never mixes them with the current revision's single item.

    PRD 3.2: "An item, once added, is a printed artefact and is never edited or
    removed; items are read individually or listed either within their packet — in
    `sequence_number` order — or across packets with optional `packet_id` and
    `item_type` filters."

    Design: Corner/endpoints/the_agenda_item_filter_isolates_one_packet_from_another
    """
    base = fx.scheduled_meeting()
    first = fx.draft_packet(base["meeting"]["id"])
    report = fx.add_item(first["id"], 1, "REPORT", title="Quarterly finance report")
    hearing = fx.add_item(
        first["id"], 2, "PUBLIC_HEARING", title="Hearing on the Elm Street rezoning"
    )
    second = fx.draft_packet(base["meeting"]["id"])
    consent = fx.add_item(second["id"], 1, "CONSENT", title="Consent calendar")

    first_rows, first_meta = validate_paginated(
        api_client.list_agenda_items(DEPUTY_CLERK, {"packet_id": first["id"]})
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_agenda_items(DEPUTY_CLERK, {"packet_id": second["id"]})
    )
    hearings, hearing_meta = validate_paginated(
        api_client.list_agenda_items(
            DEPUTY_CLERK, {"packet_id": first["id"], "item_type": "PUBLIC_HEARING"}
        )
    )
    nested_rows, _ = validate_paginated(
        api_client.list_packet_agenda_items(first["id"], DEPUTY_CLERK)
    )

    a.assert_pagination_meta(first_meta, total_count=2)
    a.assert_ids_equal(first_rows, [report["id"], hearing["id"]])
    a.assert_pagination_meta(second_meta, total_count=1)
    a.assert_ids_equal(second_rows, [consent["id"]])
    a.assert_pagination_meta(hearing_meta, total_count=1)
    a.assert_ids_equal(hearings, [hearing["id"]])
    a.assert_ids_equal(nested_rows, [report["id"], hearing["id"]])
    a.assert_ascending_by(nested_rows, "sequence_number")
    a.assert_status(fx.read_packet(first["id"]), "SUPERSEDED")
