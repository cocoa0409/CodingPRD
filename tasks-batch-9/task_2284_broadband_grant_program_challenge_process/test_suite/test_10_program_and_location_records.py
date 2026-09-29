"""Program and location records: defaults, required inputs, listing, envelope."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_eligible_location,
    assert_error_envelope_meta,
    assert_grant_program,
    create_location_payload,
    create_program,
    create_program_payload,
    ingest_canonical_location,
    ingest_location,
    read_program,
    register_subgrantee,
    setup_challenge_open_program,
    setup_draft_program_with_locations,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST
from test_helpers.test_users import TEST_USERS


def test_program_creation_stamps_every_omitted_policy_default():
    """A creation body carrying only the mandatory identity, appropriation and
    window fields still comes back with all nine policy parameters populated, the
    three balances initialised from the appropriation and the row on its first
    version.

    PRD 3.1: "Ten policy parameters may be supplied at creation and otherwise
    take their programme defaults."
    PRD 3.1: "`min_match_pct` is the minimum non-federal match an application
    must offer and defaults to 25.0."
    PRD 3.1: "On creation the program starts in `DRAFT`, its
    `uncommitted_balance_cents` equals `total_appropriation_cents`,
    `obligated_balance_cents` and `disbursed_balance_cents` are both 0, and
    `scoring_posture` is `FROZEN`."
    PRD 2.4: "`version` (integer): an integer that starts at 1 and increments by
    one on every mutation of the row."

    Design: Corner/entities/program_create_applies_all_optional_defaults
    """
    payload = create_program_payload(total_appropriation_cents=50000000)
    for omitted in (
        "min_match_pct",
        "holdback_pct",
        "unserved_down_mbps_threshold",
        "unserved_up_mbps_threshold",
        "served_down_mbps_threshold",
        "served_up_mbps_threshold",
        "max_latency_ms",
        "ehcl_threshold_cents",
        "ehcl_waiver_enabled",
    ):
        assert omitted not in payload, "The body must leave every policy field unset"

    program = validate_success(api_client.create_program(payload, ADMIN), 201)
    assert_grant_program(program)

    assert program["min_match_pct"] == 25.0
    assert program["holdback_pct"] == 10.0
    assert program["unserved_down_mbps_threshold"] == 25
    assert program["unserved_up_mbps_threshold"] == 3
    assert program["served_down_mbps_threshold"] == 100
    assert program["served_up_mbps_threshold"] == 20
    assert program["max_latency_ms"] == 100
    assert program["ehcl_threshold_cents"] == 2500000
    assert program["ehcl_waiver_enabled"] is True

    assert program["program_state"] == "DRAFT"
    assert program["scoring_posture"] == "FROZEN"
    assert program["stale_score_sheet_count"] == 0
    assert program["location_count_total"] == 0
    assert program["uncommitted_balance_cents"] == 50000000
    assert program["obligated_balance_cents"] == 0
    assert program["disbursed_balance_cents"] == 0
    assert program["version"] == 1


def test_location_creation_without_the_reported_speeds_is_refused():
    """The reported performance triple is part of the ingestion input, so a body
    missing the two speed readings never reaches the classification walk and
    leaves the inventory empty.

    PRD 3.1: "An `EligibleLocation` is ingested with its `program_id`, the map's
    broadband serviceable location identifier `address_id`, the reported
    performance triple `reported_down_mbps`, `reported_up_mbps` and
    `reported_latency_ms`, the `reported_technology`, and
    `reporting_provider_user_id` — the opaque identifier of the provider that
    reported this service, which later becomes the only provider identity
    permitted to file rebuttal evidence against challenges on this location."
    PRD 2.12: "3. **Priority 14 — request validity.** Body parses as JSON; every
    required input field present; enum values in range; integer fields integral;
    percentage fields within 0 through 100; every `*_cents` field at least 0; ISO
    8601 timestamps parse and carry an explicit UTC offset →
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/location_create_missing_required_reported_speeds_rejected
    """
    program = create_program()
    payload = create_location_payload(program["id"], "ADDR-0001")
    del payload["reported_down_mbps"]
    del payload["reported_up_mbps"]

    refused = api_client.create_location(payload, ANALYST)
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST)

    assert read_program(program["id"])["location_count_total"] == 0
    rows, meta = validate_paginated(api_client.list_locations(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_the_location_list_reports_the_matching_total_before_the_page_is_cut():
    """Five ingested locations are paged two at a time: every page repeats the
    same unpaginated total, the three pages partition the inventory exactly, and
    `has_more` turns false only on the page that reaches the end of the set.

    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, where `total_count` is the
    number of rows matching the filters before pagination is applied and
    `has_more` states whether rows remain beyond the current page."
    PRD 3.1: "The program row also publishes `location_count_total`, the number
    of eligible locations recorded against it across every `eligibility_state`
    value."

    Design: Corner/entities/locations_list_filter_paginates_with_total_count
    """
    program = create_program()
    ingested = {
        ingest_canonical_location(program["id"], "L1")["id"],
        ingest_canonical_location(program["id"], "L2")["id"],
        ingest_canonical_location(program["id"], "L3")["id"],
        ingest_location(
            program["id"],
            "ADDR-0004",
            reported_down_mbps=5,
            reported_up_mbps=1,
            reported_latency_ms=90,
            reported_technology="DSL",
        )["id"],
        ingest_canonical_location(program["id"], "L5")["id"],
    }
    assert len(ingested) == 5
    assert read_program(program["id"])["location_count_total"] == 5

    whole, whole_meta = validate_paginated(api_client.list_locations(ADMIN))
    assert whole_meta["total_count"] == 5
    assert whole_meta["limit"] == 10
    assert whole_meta["offset"] == 0
    assert whole_meta["has_more"] is False
    assert {row["id"] for row in whole} == ingested

    first, first_meta = validate_paginated(
        api_client.list_locations(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert first_meta["total_count"] == 5, (
        "The total counts the matching rows, not the rows on this page"
    )
    assert first_meta["limit"] == 2
    assert first_meta["has_more"] is True
    assert len(first) == 2

    middle, middle_meta = validate_paginated(
        api_client.list_locations(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert middle_meta["total_count"] == 5
    assert middle_meta["offset"] == 2
    assert middle_meta["has_more"] is True
    assert len(middle) == 2

    last, last_meta = validate_paginated(
        api_client.list_locations(ADMIN, params={"limit": 2, "offset": 4})
    )
    assert last_meta["total_count"] == 5
    assert last_meta["has_more"] is False
    assert len(last) == 1

    paged = [row["id"] for row in first + middle + last]
    assert len(set(paged)) == 5, "The three pages never repeat a row"
    assert set(paged) == ingested, "The three pages together cover the inventory"


def test_pagination_bounds_are_checked_before_the_program_filter_resolves():
    """Each of the three out-of-range pagination inputs is refused on its own,
    and an out-of-range limit still wins when the request also names a program
    that does not exist.

    PRD 2.3: "`limit` is the maximum number of rows returned; it defaults to 10,
    its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD 2.3: "A `limit` outside 1 through 100, a non-integer `limit`, a negative
    `offset` or a non-integer `offset` is rejected with
    `ERR_INVALID_PAGINATION`."
    PRD 2.12: "When more than one rule could reject a request, the rule with the
    lowest priority number wins and its error is the one returned; evaluation
    stops at the first violation."

    Design: Corner/entities/locations_list_limit_out_of_range_rejected
    """
    program = create_program()
    ingest_canonical_location(program["id"], "L1")

    for params in (
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ):
        validate_error(
            api_client.list_locations(ADMIN, params=params),
            ApiErrorId.ERR_INVALID_PAGINATION,
        )

    both_broken = api_client.list_locations(
        ADMIN, params={"program_id": NON_EXISTENT_UUID, "limit": 0}
    )
    validate_error(both_broken, ApiErrorId.ERR_INVALID_PAGINATION)


def test_a_fresh_location_and_its_program_start_on_their_declared_states():
    """A newly ingested location sits on the first value of both of its
    independent axes at once, and the program and the applicant registered
    alongside it are on their own opening states.

    PRD 3.1: "The **eligibility axis**, `eligibility_state`, follows the map,
    challenge and allocation lifecycle through `MAPPED`, `CHALLENGED`,
    `AFFIRMED`, `RECLASSIFIED`, `AWARD_BOUND` and the terminal
    `DEFERRED_HIGH_COST`, starting at `MAPPED`."
    PRD 3.1: "The **service axis**, `service_state`, follows physical deployment
    through `NOT_BUILT`, `UNDER_CONSTRUCTION`, `SERVICE_AVAILABLE`, `CERTIFIED`
    and `AUDIT_FAILED`, starting at `NOT_BUILT`."
    PRD 3.4: "Registration starts `capability_state` at `REGISTERED` with
    `remediation_count` and `withdrawn_personnel_count` both at 0."

    Design: Corner/state_machines/location_creation_starts_on_both_initial_states
    """
    ctx = setup_draft_program_with_locations(("L3",))
    location = ctx["locations"]["L3"]
    assert_eligible_location(location)

    assert location["eligibility_state"] == "MAPPED"
    assert location["service_state"] == "NOT_BUILT"
    assert location["classification_status"] == "UNSERVED"
    assert location["classification_source"] == "NATIONAL_MAP"
    assert location["challenge_count"] == 0
    assert location["awarded_award_id"] is None
    assert location["certified_at"] is None

    # Priority 40 forbids subgrantee operations on a DRAFT program, so the
    # applicant is registered under a sibling program whose challenge window is
    # open while the DRAFT program above keeps its opening states.
    open_ctx = setup_challenge_open_program(("L3",))
    subgrantee = register_subgrantee(open_ctx["program_id"])
    assert subgrantee["capability_state"] == "REGISTERED"
    assert subgrantee["remediation_count"] == 0
    assert subgrantee["withdrawn_personnel_count"] == 0

    program = read_program(ctx["program_id"])
    assert program["program_state"] == "DRAFT"
    assert program["scoring_posture"] == "FROZEN"


def test_either_inverted_window_pair_is_refused_on_program_creation():
    """The ordering rule covers the challenge pair and the application pair
    independently, so a body whose challenge window is perfectly ordered is still
    refused when its application window runs backwards, and nothing is persisted.

    PRD 2.12: "29. **Priority 70 — window ordering.** On application creation
    `proposed_construction_start` must be strictly before
    `proposed_construction_end`; on audit creation `window_start` strictly before
    `window_end`; on program creation `challenge_window_start` strictly before
    `challenge_window_end` and `application_window_start` strictly before
    `application_window_end` → `ERR_WINDOW_ORDER_INVALID`."
    PRD 3.1: "Both windows are half-open: the start instant is inside the window
    and the end instant is outside it."

    Design: Corner/validations/program_window_order_invalid_rejected
    """
    inverted_challenge = api_client.create_program(
        create_program_payload(
            challenge_window_start="2026-09-05T00:00:00Z",
            challenge_window_end="2026-08-05T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(inverted_challenge, ApiErrorId.ERR_WINDOW_ORDER_INVALID)

    inverted_application = api_client.create_program(
        create_program_payload(
            application_window_start="2026-09-05T00:00:00Z",
            application_window_end="2026-08-05T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(inverted_application, ApiErrorId.ERR_WINDOW_ORDER_INVALID)

    rows, meta = validate_paginated(api_client.list_programs(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_the_envelope_is_identical_on_the_read_and_on_the_error_path():
    """A created program reads back field for field inside an object envelope, an
    unknown id returns the error envelope with the same two meta keys, and the
    collection read applies the default page window.

    PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD 2.3: "`offset` is the number of rows skipped before the page begins; it
    defaults to 0 and its minimum accepted value is 0."
    PRD 2.12: "5. **Priorities 20 through 28 — existence,** resolved in this order:
    `program_id` in path or body → `ERR_PROGRAM_NOT_FOUND`; `location_id` in path or
    body → `ERR_LOCATION_NOT_FOUND`; the challenge id in the path →
    `ERR_CHALLENGE_NOT_FOUND`; `subgrantee_id` in path or body →
    `ERR_SUBGRANTEE_NOT_FOUND`; `application_id` in path or body →
    `ERR_APPLICATION_NOT_FOUND`; `award_id` in path or body →
    `ERR_AWARD_NOT_FOUND`; the milestone id in the path, which must belong to the
    award named earlier in the path → `ERR_MILESTONE_NOT_FOUND`; the audit id in the
    path, which must likewise belong to that award, and the environmental-review
    sub-path, which must resolve to an existing review of that award →
    `ERR_AUDIT_NOT_FOUND`; and, for environmental-review sub-actions, the award
    having a review row at all → `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`."

    Design: Corner/endpoints/program_create_and_read_round_trip
    """
    created = validate_success(
        api_client.create_program(create_program_payload(), ADMIN), 201
    )

    read_response = api_client.get_program(created["id"], ADMIN)
    assert read_response.status_code == 200
    body = read_response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    fetched = body["data"]
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "BEAD Round 1"
    assert fetched["fiscal_year"] == 2026
    assert fetched["total_appropriation_cents"] == 100000000
    assert fetched["challenge_window_start"] == created["challenge_window_start"]
    assert fetched["application_window_end"] == created["application_window_end"]

    missing = api_client.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing, ApiErrorId.ERR_PROGRAM_NOT_FOUND)
    assert_error_envelope_meta(missing)

    listed = api_client.list_programs(TEST_USERS["scoring_officer_headers"])
    listed_body = listed.json()
    assert listed_body["response_type"] == "array"
    rows, meta = validate_paginated(listed)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert [row["id"] for row in rows] == [created["id"]]
