"""Entity-level corners: declared fields, defaults, computed and system-assigned
fields, enum and required-field rejection, not-found resolution, listing
pagination and the station/distributor junction.

Every test here starts against an empty database and builds its preconditions
through the PRD's own endpoints.
"""

from test_helpers import (
    DEFAULT_CLOCK_UTC,
    TEST_USERS,
    ApiErrorId,
    assert_distributor,
    assert_good_faith_log_entry,
    assert_negotiation,
    assert_station,
    assert_subscriber_report,
    create_affiliation_agreement,
    create_audit_finding_payload,
    create_distributor,
    create_distributor_payload,
    create_election,
    create_good_faith_log_payload,
    create_station,
    create_station_payload,
    create_subscriber_report_payload,
    file_election,
    make_compliance_officer_headers,
    make_distributor_rep_headers,
    make_station_negotiator_headers,
    negotiation_of_election,
    read_negotiation,
    read_station,
    set_clock,
    setup_open_negotiation,
    setup_station_and_distributor,
    validate_error,
    validate_paginated,
    validate_success,
)

# Syntactically valid UUIDs that resolve to no live row in an empty database.
UNKNOWN_REPORT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_STATION_ID = "22222222-2222-4222-8222-222222222222"


def test_station_creation_returns_every_declared_field(api):
    """Registering a station echoes back all five inputs plus its identity fields.

    PRD §3.1: "A `CarriageAdmin` registers each owned-and-operated **Station** with its
    `call_sign` - exactly four uppercase letters, and globally unique across the system,
    because two stations cannot share a call sign - together with the `market_code` of
    the designated market area it is licensed to serve, given as exactly three uppercase
    letters such as `SEA`."
    PRD §3.1: "A newly registered station begins with `filed_election_count` at 0."

    Design: Corner/entities/corner_station_create_returns_all_declared_fields
    """
    set_clock(DEFAULT_CLOCK_UTC)

    response = api.create_station(
        create_station_payload(
            call_sign="WXYZ",
            market_code="SEA",
            dma_rank=12,
            market_tv_households=1800000,
            network_affiliation="CBS",
        ),
        TEST_USERS["carriage_admin_headers"],
    )
    station = validate_success(response, 201)

    assert_station(station)
    assert station["call_sign"] == "WXYZ"
    assert station["market_code"] == "SEA"
    assert station["dma_rank"] == 12
    assert station["market_tv_households"] == 1800000
    assert station["network_affiliation"] == "CBS"
    assert station["filed_election_count"] == 0
    assert isinstance(station["id"], str) and station["id"]

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert isinstance(station["version"], int)


def test_station_creation_without_network_affiliation_is_rejected(api):
    """network_affiliation has no default, so omitting it is a schema violation.

    PRD §3.1: "Finally, the station declares its `network_affiliation`, which is one of
    `ABC`, `CBS`, `NBC`, `FOX`, `CW`, or `INDEPENDENT`."
    PRD §2.8: "This covers missing required fields, enum values outside their declared
    sets, non-integer or negative integers where a non-negative integer is required, a
    proposed base rate above 600 cents, an escalator above 1,000 basis points, a
    penetration commitment outside 0 through 10,000 basis points, a term length outside
    12 through 120 months, an extension length outside 1 through 90 days, a reporting or
    settlement period whose end is not strictly after its start, a carriage term whose
    end is not strictly after its start, a `limit` outside 1 through 100, a negative
    `offset`, and any timestamp that does not parse as an ISO 8601 UTC instant."

    Design: Corner/entities/corner_station_create_missing_network_affiliation_rejected
    """
    set_clock(DEFAULT_CLOCK_UTC)

    payload = create_station_payload(
        call_sign="WABC",
        market_code="PDX",
        dma_rank=22,
        market_tv_households=1100000,
    )
    payload.pop("network_affiliation")

    response = api.create_station(payload, TEST_USERS["carriage_admin_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    # Nothing was persisted: the call sign is still free, and call signs are globally
    # unique, so a complete registration under the same call sign now succeeds.
    retry = api.create_station(
        create_station_payload(
            call_sign="WABC",
            market_code="PDX",
            dma_rank=22,
            market_tv_households=1100000,
            network_affiliation="CBS",
        ),
        TEST_USERS["carriage_admin_headers"],
    )
    station = validate_success(retry, 201)
    assert station["call_sign"] == "WABC"


def test_subscriber_report_free_trial_count_defaults_to_zero(api):
    """Omitting the free-trial figure leaves the adjusted count equal to the raw count.

    PRD §3.4: "The free-trial figure defaults to 0 when omitted, must be at least 0, and
    may not exceed `reported_subscriber_count`."
    PRD §3.4: "First, the adjusted subscriber count is derived: take
    `reported_subscriber_count`, subtract `excluded_free_trial_count`, and add
    `audit_adjustment_subscribers`."
    PRD §3.4: "The report names the `station_id` whose signal the counts relate to; its
    `distributor_id` is never accepted from the body but is taken from the reporting
    representative's own `X-User-ID`."

    Design: Corner/entities/corner_subscriber_report_excluded_free_trial_defaults_to_zero
    """
    ctx = setup_station_and_distributor(
        distributor={
            "distributor_type": "CABLE",
            "subscriber_measurement_method": "BILLED_HOUSEHOLDS",
            "video_household_count": 240000,
        }
    )

    payload = create_subscriber_report_payload(
        ctx["station"]["id"],
        period_label="2027-01",
        period_start_utc="2027-01-01T00:00:00Z",
        period_end_utc="2027-02-01T00:00:00Z",
        reported_subscriber_count=100000,
    )
    payload.pop("excluded_free_trial_count")

    response = api.create_subscriber_report(payload, ctx["rep_headers"])
    report = validate_success(response, 201)

    assert_subscriber_report(report)
    assert report["excluded_free_trial_count"] == 0
    assert report["adjusted_subscriber_count"] == 100000
    assert report["billable_subscriber_basis"] == 100000
    assert report["as_reported_basis"] == 100000
    assert report["audit_adjustment_subscribers"] == 0
    assert report["status"] == "REPORTED"
    assert report["measurement_method_snapshot"] == "BILLED_HOUSEHOLDS"
    assert report["distributor_id"] == ctx["distributor"]["id"]


def test_distributor_notice_days_are_computed_from_the_distributor_type(api):
    """A CABLE distributor is stamped with 30 notice days and a VMVPD with 14.

    PRD §3.2: "A traditional distributor - `CABLE`, `DBS` or `TELCO` - must be given 30
    days of advance subscriber notice before a signal may go dark."
    PRD §3.2: "A `VMVPD` gets 14 days, on the theory that a streaming subscriber can
    change services within a billing cycle."
    PRD §3.2: "A newly registered distributor begins with `open_true_up_count` at 0."

    Design: Corner/entities/corner_distributor_required_notice_days_computed_from_type
    """
    set_clock(DEFAULT_CLOCK_UTC)

    cable = validate_success(
        api.create_distributor(
            create_distributor_payload(
                name="Cascade Cable",
                distributor_type="CABLE",
                subscriber_measurement_method="BILLED_HOUSEHOLDS",
                video_household_count=240000,
            ),
            TEST_USERS["carriage_admin_headers"],
        ),
        201,
    )
    vmvpd = validate_success(
        api.create_distributor(
            create_distributor_payload(
                name="StreamRiver TV",
                distributor_type="VMVPD",
                subscriber_measurement_method="WEIGHTED_STREAMING_DEVICES",
                video_household_count=90000,
            ),
            TEST_USERS["carriage_admin_headers"],
        ),
        201,
    )

    assert_distributor(cable)
    assert_distributor(vmvpd)
    assert cable["required_blackout_notice_days"] == 30
    assert vmvpd["required_blackout_notice_days"] == 14
    assert cable["open_true_up_count"] == 0
    assert vmvpd["open_true_up_count"] == 0


def test_good_faith_entries_get_server_assigned_sequence_and_actor_role(api):
    """Two entries appended by different roles carry 1 then 2 and record their caller.

    PRD §3.6: "The entry is immutable once written: the server stamps `actor_role` from
    the caller's role - one of `StationGroupNegotiator`, `DistributorRep` or
    `ComplianceOfficer` - and assigns `sequence_index` as a 1-based append position
    within the negotiation, ordered by creation timestamp ascending."
    PRD §3.6: "Entries whose `event_type` is `MEETING_HELD` feed the negotiation's
    `good_faith_meeting_count`; the other four event types are recorded but do not count
    toward it."

    Design: Corner/entities/corner_good_faith_log_sequence_index_and_actor_role_are_system_assigned
    """
    ctx = setup_open_negotiation()

    first = validate_success(
        api.create_good_faith_log_entry(
            ctx["negotiation"]["id"],
            create_good_faith_log_payload(
                event_type="INFORMATION_REQUEST",
                occurred_at_utc="2026-08-03T00:00:00Z",
                summary="Station group requests subscriber tape",
            ),
            ctx["negotiator_headers"],
        ),
        201,
    )
    second = validate_success(
        api.create_good_faith_log_entry(
            ctx["negotiation"]["id"],
            create_good_faith_log_payload(
                event_type="MEETING_HELD",
                occurred_at_utc="2026-08-04T00:00:00Z",
                summary="First session",
            ),
            ctx["rep_headers"],
        ),
        201,
    )

    assert_good_faith_log_entry(first)
    assert_good_faith_log_entry(second)
    assert first["sequence_index"] == 1
    assert second["sequence_index"] == 2
    assert first["actor_role"] == "StationGroupNegotiator"
    assert second["actor_role"] == "DistributorRep"

    negotiation = read_negotiation(ctx["negotiation"]["id"])
    assert_negotiation(negotiation)
    assert negotiation["good_faith_meeting_count"] == 1


def test_good_faith_log_rows_expose_no_version_and_no_updated_at(api):
    """The append-only conduct record carries only id and created_at.

    PRD §2.4: "`GoodFaithLog` is the sole exception."
    PRD §2.4: "Entries of that kind carry only `id` and `created_at`; both `updated_at`
    and `version` are absent from a `GoodFaithLog` representation entirely."
    PRD §3.6: "The log can be read back in append order and narrowed by `event_type`."

    Design: Corner/entities/corner_good_faith_log_is_immutable_with_no_version_field
    """
    ctx = setup_open_negotiation()
    validate_success(
        api.create_good_faith_log_entry(
            ctx["negotiation"]["id"],
            create_good_faith_log_payload(
                event_type="PROPOSAL_EXCHANGED",
                occurred_at_utc="2026-08-06T00:00:00Z",
                summary="Term sheet exchanged",
            ),
            ctx["negotiator_headers"],
        ),
        201,
    )

    response = api.list_good_faith_log(
        ctx["negotiation"]["id"],
        make_compliance_officer_headers(),
        params={"event_type": "PROPOSAL_EXCHANGED"},
    )
    entries, meta = validate_paginated(response)

    assert meta["total_count"] == 1
    assert len(entries) == 1
    entry = entries[0]
    assert entry["sequence_index"] == 1
    assert entry["event_type"] == "PROPOSAL_EXCHANGED"
    assert "version" not in entry
    assert "updated_at" not in entry
    assert "id" in entry and "created_at" in entry
    assert_good_faith_log_entry(entry)


def test_distributor_registration_refuses_an_unknown_measurement_method(api):
    """A measurement convention outside the three declared members is a schema violation.

    PRD §3.2: "Measurement method is where virtual distributors diverge most sharply from
    traditional ones, and the distributor must declare which convention it uses as
    `subscriber_measurement_method`: `BILLED_HOUSEHOLDS`, `WEIGHTED_STREAMING_DEVICES`,
    or `AVERAGE_MONTHLY_UNIQUE`."
    PRD §2.8: "This covers missing required fields, enum values outside their declared
    sets, non-integer or negative integers where a non-negative integer is required, a
    proposed base rate above 600 cents, an escalator above 1,000 basis points, a
    penetration commitment outside 0 through 10,000 basis points, a term length outside
    12 through 120 months, an extension length outside 1 through 90 days, a reporting or
    settlement period whose end is not strictly after its start, a carriage term whose
    end is not strictly after its start, a `limit` outside 1 through 100, a negative
    `offset`, and any timestamp that does not parse as an ISO 8601 UTC instant."

    Design: Corner/entities/corner_distributor_unknown_measurement_method_enum_rejected
    """
    set_clock(DEFAULT_CLOCK_UTC)

    response = api.create_distributor(
        create_distributor_payload(
            name="Bad Method Cable",
            distributor_type="CABLE",
            subscriber_measurement_method="SET_TOP_BOX_TAPS",
            video_household_count=240000,
        ),
        TEST_USERS["carriage_admin_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_audit_finding_against_an_unknown_report_reports_the_report_as_missing(api):
    """Path resolution runs before the counterparty check, so the 404 wins.

    PRD §2.8: "Each resource kind has its own not-found code: `ERR_STATION_NOT_FOUND`,
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_AUDIT_FINDING_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, and
    `ERR_SETTLEMENT_NOT_FOUND`."
    PRD §2.8: "A request that violates more than one rule must report the violation that
    comes first in the following sequence, and the checks are numbered so that a lower
    number always wins:"

    Design: Corner/entities/corner_audit_finding_on_unknown_report_returns_report_not_found
    """
    station = create_station()

    response = api.create_audit_finding(
        UNKNOWN_REPORT_ID,
        create_audit_finding_payload(
            adjustment_subscribers=500,
            basis_note="Audit against a report that does not exist",
        ),
        make_station_negotiator_headers(station["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REPORT_NOT_FOUND.value, 404)


def test_reading_an_unknown_station_reports_the_station_as_missing(api):
    """A well-formed but unknown station id yields the station's own not-found code.

    PRD §2.8: "Each resource kind has its own not-found code: `ERR_STATION_NOT_FOUND`,
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_AUDIT_FINDING_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, and
    `ERR_SETTLEMENT_NOT_FOUND`."

    Design: Corner/entities/corner_get_unknown_station_returns_station_not_found
    """
    set_clock(DEFAULT_CLOCK_UTC)

    response = api.get_station(
        UNKNOWN_STATION_ID, TEST_USERS["carriage_admin_headers"]
    )
    validate_error(response, ApiErrorId.ERR_STATION_NOT_FOUND.value, 404)


def test_election_list_first_page_reports_the_full_count_and_creation_order(api):
    """A limit of 1 over two elections pages the oldest row and flags more to come.

    PRD §2.3: "`limit` caps the number of items returned; it defaults to 10 when omitted,
    may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "Unless a specific operation states otherwise, every list is ordered by the
    resource's creation timestamp ascending."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope described in §2.2."

    Design: Corner/entities/corner_elections_list_pagination_and_status_filter
    """
    ctx = setup_station_and_distributor()
    station_id = ctx["station"]["id"]
    second_distributor = create_distributor(
        name="Rainier Telco",
        distributor_type="TELCO",
        subscriber_measurement_method="BILLED_HOUSEHOLDS",
        video_household_count=60000,
    )
    first_election = create_election(
        station_id, ctx["distributor"]["id"], incumbent_rate_per_sub_cents=220
    )
    create_election(
        station_id, second_distributor["id"], incumbent_rate_per_sub_cents=180
    )
    file_election(first_election["id"], station_id)

    response = api.list_elections(
        TEST_USERS["carriage_admin_headers"],
        params={"station_id": station_id, "limit": 1, "offset": 0},
    )
    elections, meta = validate_paginated(response)

    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert len(elections) == 1
    assert elections[0]["id"] == first_election["id"]


def test_election_list_status_filter_narrows_to_the_filed_election(api):
    """Filtering on NEGOTIATING drops the election still sitting in DRAFT.

    PRD §3.3: "Elections can be listed and narrowed by `station_id`, `distributor_id`,
    `election_type`, `status` and `cycle_label`, and the negotiations created by filing a
    given election - zero of them on the must-carry branch, exactly one on the
    retransmission-consent branch - can be listed from the election itself."
    PRD §3.3: "On the retransmission-consent branch, filing an election whose
    `election_type` is `RETRANS_CONSENT` advances it `DRAFT -> NEGOTIATING`."

    Design: Corner/entities/corner_elections_list_pagination_and_status_filter
    """
    ctx = setup_station_and_distributor()
    station_id = ctx["station"]["id"]
    second_distributor = create_distributor(
        name="Rainier Telco",
        distributor_type="TELCO",
        subscriber_measurement_method="BILLED_HOUSEHOLDS",
        video_household_count=60000,
    )
    first_election = create_election(
        station_id, ctx["distributor"]["id"], incumbent_rate_per_sub_cents=220
    )
    second_election = create_election(
        station_id, second_distributor["id"], incumbent_rate_per_sub_cents=180
    )
    file_election(first_election["id"], station_id)

    response = api.list_elections(
        TEST_USERS["carriage_admin_headers"],
        params={
            "station_id": station_id,
            "status": "NEGOTIATING",
            "limit": 10,
            "offset": 0,
        },
    )
    elections, meta = validate_paginated(response)

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(elections) == 1
    assert elections[0]["id"] == first_election["id"]
    assert elections[0]["status"] == "NEGOTIATING"

    unfiled = validate_success(
        api.get_election(second_election["id"], TEST_USERS["carriage_admin_headers"]),
        200,
    )
    assert unfiled["status"] == "DRAFT"


def test_one_distributor_faces_two_stations_through_the_election_junction(api):
    """Filtering by distributor returns both stations' elections, each with its own
    independent negotiation.

    PRD §3.3: "The **carriage election** is the junction record that joins one station to
    one distributor for one three-year cycle, and it is where the statutory fork lives."
    PRD §3.3: "Filing on this branch stamps `filed_at_utc` with the current logical clock,
    creates exactly one **Negotiation** whose `election_id` points back at the election,
    whose `status` starts at `OPEN` and whose `round_number` starts at 0, computes that
    negotiation's `blackout_notice_deadline_utc` as described in §3.6, and recomputes the
    station's `filed_election_count`."
    PRD §2.9: "`Station.filed_election_count` counts that station's elections in status
    `NEGOTIATING`, `ELECTION_EFFECTIVE` or `CONSENT_GRANTED`."

    Design: Corner/entities/corner_one_distributor_faces_two_stations_through_election_junction
    """
    first_station = create_station(
        call_sign="WXYZ",
        market_code="SEA",
        dma_rank=12,
        market_tv_households=1800000,
        network_affiliation="CBS",
    )
    second_station = create_station(
        call_sign="WQRS",
        market_code="SPO",
        dma_rank=73,
        market_tv_households=420000,
        network_affiliation="CBS",
    )
    create_affiliation_agreement(first_station["id"])
    create_affiliation_agreement(
        second_station["id"],
        reverse_comp_floor_per_sub_cents=80,
        split_premium_bp=0,
        digital_rights_grantable=False,
        ooh_rights_grantable=False,
        streaming_rights_grantable=False,
    )
    distributor = create_distributor()

    first_election = create_election(
        first_station["id"],
        distributor["id"],
        requested_tier="EXPANDED_BASIC",
        incumbent_rate_per_sub_cents=220,
    )
    second_election = create_election(
        second_station["id"],
        distributor["id"],
        requested_tier="BROADCAST_BASIC",
        incumbent_rate_per_sub_cents=140,
    )
    file_election(first_election["id"], first_station["id"])
    file_election(second_election["id"], second_station["id"])

    response = api.list_elections(
        make_distributor_rep_headers(distributor["id"]),
        params={"distributor_id": distributor["id"], "limit": 10, "offset": 0},
    )
    elections, meta = validate_paginated(response)

    assert meta["total_count"] == 2
    assert len(elections) == 2
    assert elections[0]["station_id"] == first_station["id"]
    assert elections[1]["station_id"] == second_station["id"]
    assert elections[0]["distributor_id"] == distributor["id"]
    assert elections[1]["distributor_id"] == distributor["id"]

    assert read_station(first_station["id"])["filed_election_count"] == 1
    assert read_station(second_station["id"])["filed_election_count"] == 1

    first_negotiation = negotiation_of_election(first_election["id"])
    second_negotiation = negotiation_of_election(second_election["id"])
    assert_negotiation(first_negotiation)
    assert_negotiation(second_negotiation)
    assert first_negotiation["id"] != second_negotiation["id"]
    assert first_negotiation["election_id"] == first_election["id"]
    assert second_negotiation["election_id"] == second_election["id"]
    assert first_negotiation["status"] == "OPEN"
    assert second_negotiation["status"] == "OPEN"
    assert first_negotiation["round_number"] == 0
    assert second_negotiation["round_number"] == 0
