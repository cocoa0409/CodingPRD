"""Version tokens, reconciled counters, and same-response visibility.

A snapshot token goes stale the moment any component is written and again the
moment it is spent, a responding district's open counter walks up and back down
as requests arrive and are denied, and every derived value is already correct in
the body of the write that produced it.
"""
from test_helpers import (
    ADMIN,
    OFFICER_1,
    api_client,
    assert_cumulative_file,
    assert_district,
    assert_file_component,
    assert_records_request,
    certify_component,
    certify_component_payload,
    collect_component,
    create_district,
    create_records_request,
    create_state_rule,
    create_student,
    deny_request,
    file_version,
    get_components,
    get_cumulative_file_id,
    get_file,
    make_receiving_registrar_headers,
    mark_ready_payload,
    validate_error,
    validate_paginated,
    validate_request,
    validate_success,
)

CA_RULE = dict(
    transfer_response_days=10,
    discipline_inclusion_mode="SUSPENSIONS_AND_EXPULSIONS",
    discipline_min_days_removed=10,
    include_pending_investigations=False,
    sped_requires_consent=True,
    amendment_hearing_days=30,
    destruction_min_age_years=5,
    directory_optout_grace_days=14,
    notification_wait_days=7,
)
TX_RULE = dict(
    transfer_response_days=30,
    discipline_inclusion_mode="ALL_INCIDENTS",
    discipline_min_days_removed=10,
    include_pending_investigations=True,
    sped_requires_consent=False,
    amendment_hearing_days=45,
    destruction_min_age_years=7,
    directory_optout_grace_days=10,
    notification_wait_days=3,
)


def _both_rules():
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)


def _get_request(request_id):
    return validate_success(api_client.get_records_request(request_id, OFFICER_1))


def _mark_ready(request_id, expected_version):
    return api_client.mark_ready_records_request(
        request_id, mark_ready_payload(expected_version), OFFICER_1
    )


def _fritz_with_a_token_that_went_stale():
    """The token is read while the file is COMPLETE at sixty certified pages, and
    an optional-component write immediately afterwards moves the file on."""
    _both_rules()
    responding = create_district("SEND01", state_code="CA", name="Sending Unified")
    requesting = create_district("RECV01", state_code="TX", name="Receiving Unified")
    student = create_student(
        responding["id"],
        first_name="Fritz",
        last_name="Aalto",
        dob="2012-09-02",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-fritz",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30)):
        component_id = components[component_type]["id"]
        collect_component(file_id, component_id, pages, 0)
        certify_component(file_id, component_id)

    request = create_records_request(
        student["id"],
        requesting["id"],
        responding["id"],
        authorization_reference="ENR-2026-9100",
    )
    assembling = validate_request(request["id"])
    assert assembling["status"] == "ASSEMBLING"

    stale_version = file_version(file_id)
    collect_component(file_id, components["SPECIAL_EDUCATION"]["id"], 15, 0)
    return dict(
        file_id=file_id,
        request_id=request["id"],
        stale_version=stale_version,
        components=components,
    )


class TestStaleCumulativeFileVersionOnMarkReady:
    def test_a_token_read_before_a_component_write_is_no_longer_current(self):
        """The optional-component write moved the file's version on by exactly one,
        so the token captured before it no longer equals the current version and the
        snapshot is refused without touching the request.

        PRD: "If it does not equal that file's current `version`, the request is rejected with `ERR_STALE_CUMULATIVE_FILE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_cumulative_file_version_rejects_mark_ready_with_412
        """
        scenario = _fritz_with_a_token_that_went_stale()

        response = _mark_ready(scenario["request_id"], scenario["stale_version"])

        validate_error(response, "ERR_STALE_CUMULATIVE_FILE_VERSION", 412)

        untouched = _get_request(scenario["request_id"])
        assert_records_request(untouched)
        assert untouched["status"] == "ASSEMBLING"
        assert untouched["packet_status"] == "NONE"
        assert untouched["packet_page_count"] is None

        assert file_version(scenario["file_id"]) == scenario["stale_version"] + 1

    def test_the_current_token_snapshots_only_the_certified_pages(self):
        """Re-read against the version the file actually holds, the identical call
        succeeds and freezes sixty pages: the fifteen collected special-education
        pages are not certified and so are not in the packet.

        PRD: "Only `CERTIFIED` components contribute; `PENDING`, `COLLECTED`, and `EXCLUDED` components contribute nothing, which is precisely why excluding a certified component both reopens the request and changes the page count of the next snapshot."

        Design: Corner/cross_cutting_layers/stale_cumulative_file_version_rejects_mark_ready_with_412
        """
        scenario = _fritz_with_a_token_that_went_stale()
        fresh_version = file_version(scenario["file_id"])

        ready = validate_success(_mark_ready(scenario["request_id"], fresh_version))

        assert_records_request(ready)
        assert ready["status"] == "READY_FOR_RELEASE"
        assert ready["packet_status"] == "SNAPSHOT"
        assert ready["packet_page_count"] == 60

        uncertified = get_components(scenario["file_id"])["SPECIAL_EDUCATION"]
        assert_file_component(uncertified)
        assert uncertified["status"] == "COLLECTED"
        assert uncertified["page_count"] == 15

        file_read = get_file(scenario["file_id"])
        assert_cumulative_file(file_read)
        assert file_read["total_page_count"] == 75
        assert file_read["last_packet_snapshot_at"] == "2026-08-01T00:00:00.000Z"

    def test_the_snapshot_invalidates_the_very_token_that_spent_it(self):
        """Taking the snapshot increments the file's version, so replaying the token
        that had just worked is refused exactly as the stale one was, and the request
        keeps the packet it already froze.

        PRD: "The cumulative file's `last_packet_snapshot_at` is set to the current logical clock instant and the file's `version` is incremented by one — which is why an officer who intends to take a second snapshot must re-read the file before doing so."

        Design: Corner/cross_cutting_layers/stale_cumulative_file_version_rejects_mark_ready_with_412
        """
        scenario = _fritz_with_a_token_that_went_stale()
        fresh_version = file_version(scenario["file_id"])
        validate_success(_mark_ready(scenario["request_id"], fresh_version))

        assert file_version(scenario["file_id"]) == fresh_version + 1

        replay = _mark_ready(scenario["request_id"], fresh_version)

        validate_error(replay, "ERR_STALE_CUMULATIVE_FILE_VERSION", 412)

        still_ready = _get_request(scenario["request_id"])
        assert still_ready["status"] == "READY_FOR_RELEASE"
        assert still_ready["packet_status"] == "SNAPSHOT"
        assert still_ready["packet_page_count"] == 60
        assert still_ready["reopen_count"] == 0


def _one_responding_district_and_three_receivers():
    """Greta sits in SEND01; RECV01, RECV02 and RECV03 each file one request for
    her, so the responding district carries three open rows."""
    _both_rules()
    responding = create_district("SEND01", state_code="CA", name="Sending Unified")
    receivers = [
        create_district("RECV01", state_code="TX", name="Receiving One"),
        create_district("RECV02", state_code="TX", name="Receiving Two"),
        create_district("RECV03", state_code="TX", name="Receiving Three"),
    ]
    student = create_student(
        responding["id"],
        first_name="Greta",
        last_name="Bauer",
        dob="2012-10-03",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-greta",
    )
    assert _open_count(responding["id"]) == 0
    requests = [
        create_records_request(
            student["id"],
            receiver["id"],
            responding["id"],
            authorization_reference=f"ENR-2026-911{index}",
        )
        for index, receiver in enumerate(receivers)
    ]
    return responding, receivers, requests


def _open_count(district_id):
    district = validate_success(api_client.get_district(district_id, ADMIN))
    assert_district(district)
    return district["open_request_count"]


class TestOpenRequestCountReconciles:
    def test_the_counter_counts_responding_rows_only(self):
        """Three arrivals walk the responding district's counter to three, while
        each receiving district stays at zero even though it filed one of them — the
        counter is keyed on the responding side.

        PRD: "Each district also exposes `open_request_count`, a derived counter that starts at 0 and always equals the number of records requests whose responding district is this district and whose status is `RECEIVED`, `VALIDATED`, `ASSEMBLING`, or `READY_FOR_RELEASE`."

        Design: Corner/cross_cutting_layers/district_open_request_count_reconciles_on_every_status_change
        """
        responding, receivers, requests = _one_responding_district_and_three_receivers()

        assert _open_count(responding["id"]) == 3
        for receiver in receivers:
            assert _open_count(receiver["id"]) == 0, (
                f"{receiver['district_code']} filed a request but responds to none"
            )

        for request in requests:
            assert_records_request(request)
            assert request["status"] == "RECEIVED"

    def test_each_denial_takes_its_row_out_of_the_open_set_at_once(self):
        """Denial is a status change like any other, so the counter is recomputed in
        the same response cycle: three becomes two and then one, and the listing
        splits into two denied rows and the one still open.

        PRD: "The request moves to `DENIED`, the reason is stored, and the responding district's `open_request_count` is recomputed."

        Design: Corner/cross_cutting_layers/district_open_request_count_reconciles_on_every_status_change
        """
        responding, _receivers, requests = _one_responding_district_and_three_receivers()

        first_denial = deny_request(requests[0]["id"], "STUDENT_NOT_IN_DISTRICT")
        assert first_denial["status"] == "DENIED"
        assert first_denial["denial_reason"] == "STUDENT_NOT_IN_DISTRICT"
        assert _open_count(responding["id"]) == 2

        second_denial = deny_request(requests[1]["id"], "DUPLICATE_REQUEST")
        assert second_denial["status"] == "DENIED"
        assert _open_count(responding["id"]) == 1

        _denied, denied_meta = validate_paginated(
            api_client.list_records_requests(
                OFFICER_1,
                params={"responding_district_id": responding["id"], "status": "DENIED"},
            )
        )
        assert denied_meta["total_count"] == 2

        open_rows, open_meta = validate_paginated(
            api_client.list_records_requests(
                OFFICER_1,
                params={"responding_district_id": responding["id"], "status": "RECEIVED"},
            )
        )
        assert open_meta["total_count"] == 1
        assert open_rows[0]["id"] == requests[2]["id"]


def _hugo_one_certification_short():
    """Two of three required components are certified and the request is already
    validated, so the next certification is the one that completes the file."""
    _both_rules()
    responding = create_district("SEND01", state_code="CA", name="Sending Unified")
    requesting = create_district("RECV01", state_code="TX", name="Receiving Unified")
    student = create_student(
        responding["id"],
        first_name="Hugo",
        last_name="Mbeki",
        dob="2012-11-04",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-hugo",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30)):
        collect_component(file_id, components[component_type]["id"], pages, 0)
    certify_component(file_id, components["ACADEMIC"]["id"])
    certify_component(file_id, components["HEALTH"]["id"])

    request = create_records_request(
        student["id"],
        requesting["id"],
        responding["id"],
        authorization_reference="ENR-2026-9120",
    )
    validated = validate_request(request["id"])
    return dict(
        requesting=requesting,
        file_id=file_id,
        components=components,
        request_id=request["id"],
        validated=validated,
    )


class TestDerivedValuesAreVisibleInTheSameResponse:
    def test_the_validate_response_already_carries_the_automatic_bubble(self):
        """The move out of VALIDATED needs no second call, so the validate response
        itself reads ASSEMBLING, and the third certification's own body reports the
        component certified while the file it re-derived reads complete.

        PRD: "The request then bubbles `VALIDATED → ASSEMBLING` immediately, without a further call, whenever the student's cumulative file already sits in `IN_ASSEMBLY` or `COMPLETE`; if the file has not started assembling yet, the request waits in `VALIDATED` and makes the same automatic move as soon as the file enters `IN_ASSEMBLY`."

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response
        """
        scenario = _hugo_one_certification_short()

        assert_records_request(scenario["validated"])
        assert scenario["validated"]["status"] == "ASSEMBLING"
        assert scenario["validated"]["authorization_verified"] is True

        certified = validate_success(
            api_client.update_file_component(
                scenario["file_id"],
                scenario["components"]["DISCIPLINE"]["id"],
                certify_component_payload(),
                OFFICER_1,
            )
        )
        assert_file_component(certified)
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_at"] == "2026-08-01T00:00:00.000Z"

        file_read = get_file(scenario["file_id"])
        assert_cumulative_file(file_read)
        assert file_read["assembly_status"] == "COMPLETE"
        assert file_read["completeness_pct"] == 100.0
        assert file_read["certified_component_count"] == 3
        assert file_read["total_page_count"] == 60
        assert file_read["included_page_count"] == 60
        assert file_read["disclosable_page_count"] == 60

    def test_the_mark_ready_body_matches_the_read_that_follows_it_exactly(self):
        """The write returns the updated resource, so the snapshot's page count and
        status are readable with no intervening call, and a fresh read by the
        receiving district's own registrar reports the identical values.

        PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response
        """
        scenario = _hugo_one_certification_short()
        certify_component(scenario["file_id"], scenario["components"]["DISCIPLINE"]["id"])

        written = validate_success(
            _mark_ready(scenario["request_id"], file_version(scenario["file_id"]))
        )
        assert_records_request(written)
        assert written["status"] == "READY_FOR_RELEASE"
        assert written["packet_status"] == "SNAPSHOT"
        assert written["packet_page_count"] == 60

        read_back = validate_success(
            api_client.get_records_request(
                scenario["request_id"],
                make_receiving_registrar_headers(scenario["requesting"]["id"]),
            )
        )
        assert read_back["status"] == written["status"]
        assert read_back["packet_status"] == written["packet_status"]
        assert read_back["packet_page_count"] == written["packet_page_count"]

        file_read = get_file(scenario["file_id"])
        assert file_read["last_packet_snapshot_at"] == "2026-08-01T00:00:00.000Z"
