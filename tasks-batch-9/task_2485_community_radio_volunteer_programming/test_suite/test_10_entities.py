"""Record-level contracts: what a write returns, what a read echoes back.

These cases pin the declared field sets, the server-managed defaults, the two
envelope shapes and the not-found codes that guard both path identifiers and body
identifiers. They are deliberately shallow — one write or one read each — because
their subject is the shape of a record rather than any downstream consequence.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    TRAINER_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
)

CLOCK = "2026-08-01T00:00:00Z"
CERT_EXPIRY = "2028-08-01T00:00:00Z"


def _envelope(response):
    body = response.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    return body


class TestVolunteerRecord:
    def test_enrolment_echoes_the_inputs_and_seeds_the_prospect_defaults(self):
        """The create response carries the roster row before anything has moved it.

        "Every newly enrolled volunteer begins with `status` `PROSPECT`, a
        `strike_count` of 0, a `seniority_score` of `0.00`, and
        `needs_core_renewal` true". `committee_seat` is false "when the flag is
        omitted", and `version` "starts at 1 on creation" alongside a `created_at`
        "stamped when the row is first written".

        Design: Corner/entities/volunteer_creation_returns_declared_fields_and_prospect_defaults
        """
        fixtures.set_clock(CLOCK)

        response = api_client.create_volunteer(
            factories.create_volunteer_payload(
                legal_name="Ada Reyes",
                email="ada@krcr.example",
                role_track="PROGRAMMER",
                seniority_start_date="2024-08-01",
            ),
            TRAINER_HEADERS,
        )
        body = _envelope(response)
        assert body["response_type"] == "object"
        data = validate_success(response, 201)

        assert data["legal_name"] == "Ada Reyes"
        assert data["email"] == "ada@krcr.example"
        assert data["role_track"] == "PROGRAMMER"
        assert data["seniority_start_date"] == "2024-08-01"
        assert data["status"] == "PROSPECT"
        assert data["committee_seat"] is False
        assert data["strike_count"] == 0
        assertions.assert_two_decimals_equal(data["seniority_score"], 0.00, "seniority_score")
        assert data["needs_core_renewal"] is True
        assert data["current_certification_count"] == 0
        assert data["continuous_service_months"] == 24
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assertions.assert_instant_equals(data["created_at"], CLOCK, "created_at")
        assertions.assert_instant_equals(data["updated_at"], CLOCK, "updated_at")
        assertions.assert_volunteer(data)

    def test_the_single_row_read_returns_the_stored_row_unchanged(self):
        """A read recomputes nothing and does not advance the version.

        `version` "starts at 1 on creation and increases by exactly 1 on every
        mutation of the row", and a retrieval is not a mutation.

        Design: Corner/entities/volunteer_retrieval_echoes_the_stored_row
        """
        fixtures.set_clock(CLOCK)
        created = fixtures.create_volunteer()

        response = api_client.get_volunteer(created["id"], DIRECTOR_HEADERS)
        body = _envelope(response)
        assert body["response_type"] == "object"
        data = validate_success(response, 200)

        assert data["id"] == created["id"]
        assert data["legal_name"] == "Ada Reyes"
        assert data["status"] == "PROSPECT"
        assert data["version"] == 1

    def test_the_roster_listing_reports_the_declared_pagination_block(self):
        """Two rows come back out of three and `has_more` says so.

        "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the envelope's `meta` object. `total_count` reports the number of
        rows matching the filters before pagination is applied, and `has_more` is
        true when rows remain beyond the current page."

        Design: Corner/entities/volunteer_listing_paginates_and_reports_total_count
        """
        fixtures.set_clock(CLOCK)
        fixtures.create_volunteer()
        fixtures.create_volunteer(
            legal_name="Bo Lin",
            email="bo@krcr.example",
            seniority_start_date="2023-01-01",
            committee_seat=True,
        )
        fixtures.create_volunteer(
            legal_name="Cy Nakamura",
            email="cy@krcr.example",
            seniority_start_date="2023-01-01",
            committee_seat=True,
        )

        response = api_client.list_volunteers(
            DIRECTOR_HEADERS, params={"limit": 2, "offset": 0}
        )
        body = _envelope(response)
        assert body["response_type"] == "array"

        rows, meta = validate_paginated(response)
        assert len(rows) == 2
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_an_absent_volunteer_id_answers_the_roster_not_found_code(self):
        """A well-formed identifier that names nothing is a 404, not a 400.

        "A request for certification records under a volunteer that does not exist
        answers `ERR_VOLUNTEER_NOT_FOUND` (404)", and records addressed directly at
        their own collection likewise answer their own not-found code.

        Design: Corner/entities/volunteer_get_unknown_id_not_found
        """
        fixtures.set_clock(CLOCK)

        response = api_client.get_volunteer(NON_EXISTENT_UUID, DIRECTOR_HEADERS)
        body = _envelope(response)
        assert body["response_type"] == "error"
        validate_error(response, "ERR_VOLUNTEER_NOT_FOUND", 404)

    def test_an_enrolment_missing_the_role_track_is_refused(self):
        """The declared-required field is absent and nothing is written.

        A coordinator enrols "by supplying their `legal_name`, a contact `email`,
        the `role_track` they are enrolling in ... and a `seniority_start_date`", so
        a payload without `role_track` is a structural failure and is "rejected with
        `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/volunteer_create_missing_required_role_track_is_rejected
        """
        fixtures.set_clock(CLOCK)

        response = api_client.create_volunteer(
            {
                "legal_name": "No Track",
                "email": "notrack@krcr.example",
                "seniority_start_date": "2024-08-01",
            },
            TRAINER_HEADERS,
        )
        validate_error(response, "ERR_VALIDATION", 400)

        _, meta = validate_paginated(api_client.list_volunteers(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0

    def test_an_enrolment_outside_the_role_track_domain_is_refused(self):
        """The field is present but its value is not one of the three tracks.

        The `role_track` is "one of `PROGRAMMER`, `ENGINEER` or `DEVELOPMENT`", so a
        fourth value is refused with `ERR_VALIDATION`.

        Design: Corner/entities/volunteer_create_invalid_enum_role_track_is_rejected
        """
        fixtures.set_clock(CLOCK)

        response = api_client.create_volunteer(
            {
                "legal_name": "Wrong Track",
                "email": "wrong@krcr.example",
                "role_track": "PHONE_BANK",
                "seniority_start_date": "2024-08-01",
            },
            TRAINER_HEADERS,
        )
        validate_error(response, "ERR_VALIDATION", 400)


class TestDevelopmentRecords:
    def test_a_new_premium_seeds_its_stock_from_the_units_received(self):
        """One supplied quantity drives three counters and the derived status.

        "At registration `on_hand_qty` is initialised to exactly
        `units_received_qty`, with `reserved_qty` and `shipped_qty` both 0. A
        premium's `status` is derived, never supplied: it is `AVAILABLE` while
        `on_hand_qty` minus `reserved_qty` is greater than 0".

        Design: Corner/entities/premium_item_creation_seeds_inventory_and_system_fields
        """
        fixtures.set_clock(CLOCK)

        response = api_client.create_premium_item(
            factories.create_premium_item_payload(
                sku="MUG-01",
                name="Station mug",
                tier_threshold_cents=5000,
                fair_market_value_cents=1500,
                units_received_qty=2,
            ),
            DEVELOPMENT_HEADERS,
        )
        data = validate_success(response, 201)

        assert data["on_hand_qty"] == 2
        assert data["reserved_qty"] == 0
        assert data["shipped_qty"] == 0
        assert data["status"] == "AVAILABLE"
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assertions.assert_premium_unit_conservation(data)
        assertions.assert_derived_premium_status(data)

    def test_a_new_drive_starts_planned_with_every_money_total_at_zero(self):
        """The five aggregates and the attainment share all open at zero.

        "A new drive sits on `status` `PLANNED` with all five money aggregates at 0
        and `attainment_pct` at `0.00`." A two-decimal field "is emitted with its two
        decimals — `54.00`, not `54`".

        Design: Corner/entities/membership_drive_creation_defaults_to_planned_with_zero_totals
        """
        fixtures.set_clock(CLOCK)

        response = api_client.create_membership_drive(
            factories.create_membership_drive_payload(
                name="Fall Drive 2026",
                goal_cents=500000,
                start_at="2026-08-01T00:00:00Z",
                end_at="2026-08-10T00:00:00Z",
                phone_line_count=2,
            ),
            DEVELOPMENT_HEADERS,
        )
        data = validate_success(response, 201)

        assert data["status"] == "PLANNED"
        assert data["gross_pledged_cents"] == 0
        assert data["pledged_total_cents"] == 0
        assert data["fulfilled_total_cents"] == 0
        assert data["refunded_total_cents"] == 0
        assert data["lapsed_total_cents"] == 0
        assertions.assert_two_decimals_equal(data["attainment_pct"], 0.00, "attainment_pct")
        assert data["version"] == 1
        assertions.assert_membership_drive(data)


class TestCertificationRecord:
    def test_an_inline_graded_pass_writes_four_computed_fields_at_once(self):
        """One supplied score decides the state, the counter and both dates.

        "On a pass the record moves `PENDING_EXAM → PASSED`, `issued_on` is stamped
        with the clock's current instant, `expires_on` is set to twenty-four calendar
        months after `issued_on`, `last_attempt_at` is stamped with the same instant,
        and `attempt_count` rises by 1." A record opens with a null
        `revocation_reason`, and only a revocation writes one.

        Design: Corner/entities/certification_grading_computes_issue_and_expiry_dates
        """
        fixtures.set_clock(CLOCK)
        volunteer = fixtures.create_volunteer()

        response = api_client.create_certification(
            volunteer["id"],
            factories.create_certification_payload(cert_type="BOARD_OPERATION", exam_score=88),
            TRAINER_HEADERS,
        )
        data = validate_success(response, 201)

        assert data["status"] == "PASSED"
        assert data["attempt_count"] == 1
        assertions.assert_instant_equals(data["last_attempt_at"], CLOCK, "last_attempt_at")
        assertions.assert_instant_equals(data["issued_on"], CLOCK, "issued_on")
        assertions.assert_instant_equals(data["expires_on"], CERT_EXPIRY, "expires_on")
        assert data["volunteer_id"] == volunteer["id"]
        assert data["revocation_reason"] is None
        assertions.assert_certification(data)

    def test_a_certification_under_an_absent_volunteer_stops_at_the_path(self):
        """The path identifier is resolved first and answers on its own behalf.

        "the server resolves path identifiers strictly left to right and answers on
        the **first** identifier that names nothing. A request for certification
        records under a volunteer that does not exist answers
        `ERR_VOLUNTEER_NOT_FOUND` (404) and never looks at anything to its right."

        Design: Corner/entities/certification_create_under_unknown_volunteer_not_found
        """
        fixtures.set_clock(CLOCK)

        response = api_client.create_certification(
            NON_EXISTENT_UUID,
            factories.create_certification_payload(cert_type="BOARD_OPERATION", exam_score=88),
            TRAINER_HEADERS,
        )
        validate_error(response, "ERR_VOLUNTEER_NOT_FOUND", 404)

        _, meta = validate_paginated(api_client.list_certifications(TRAINER_HEADERS))
        assert meta["total_count"] == 0

    def test_the_reverse_lookup_is_scoped_by_the_parent_and_the_curriculum(self):
        """One of three core records comes back when the curriculum is named.

        The reverse lookup exists "because the reverse lookup is convenient (listing
        one volunteer's certification records)", and a certification record's
        `volunteer_id` "is taken from the volunteer being addressed rather than from
        the body".

        Design: Corner/entities/certifications_reverse_lookup_lists_only_that_volunteers_rows
        """
        fixtures.set_clock(CLOCK)
        host = fixtures.create_certified_host()

        response = api_client.list_volunteer_certifications(
            host["id"], TRAINER_HEADERS, params={"cert_type": "STATION_POLICY"}
        )
        body = _envelope(response)
        assert body["response_type"] == "array"

        rows, meta = validate_paginated(response)
        assert len(rows) == 1
        assert rows[0]["cert_type"] == "STATION_POLICY"
        assert rows[0]["volunteer_id"] == host["id"]
        assert meta["total_count"] == 1


class TestBodyForeignKeyResolution:
    def test_an_occupation_naming_an_absent_show_answers_before_any_arithmetic(self):
        """The grid resolves, the body reference does not, and the grid is untouched.

        "Once every path identifier resolves, identifiers supplied in the request
        body are resolved next, and a body identifier naming no row answers the 404
        belonging to that collection — ... `ERR_PROGRAM_NOT_FOUND` ... as
        appropriate."

        Design: Corner/entities/slot_assignment_create_with_unknown_program_id_not_found
        """
        fixtures.set_clock(CLOCK)
        grid = fixtures.create_grid()
        assert grid["status"] == "DRAFT"

        response = api_client.create_slot_assignment(
            grid["id"],
            factories.create_slot_assignment_payload(
                NON_EXISTENT_UUID,
                grid["version"],
                day_of_week=1,
                start_minute=540,
                duration_minutes=60,
            ),
            DIRECTOR_HEADERS,
        )
        validate_error(response, "ERR_PROGRAM_NOT_FOUND", 404)

        after = fixtures.read_grid(grid["id"])
        assert after["status"] == "DRAFT"
        assert after["total_assigned_minutes"] == 0
        assert after["version"] == grid["version"]
