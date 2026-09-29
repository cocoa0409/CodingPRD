"""Row shapes as the register hands them back: declared defaults, stored inputs
echoed on retrieval, filtered pagination, absence, missing and undeclared inputs,
computed fields and the identifiers the server writes for itself.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CERT_VALID_FROM,
    CERT_VALID_UNTIL,
    MEASUREMENT_A,
    SAFETY_COURSE_OK_UNTIL,
    UNKNOWN_UUID,
    ApiErrorId,
    add_crew,
    add_crew_payload,
    create_boat_payload,
    create_certificate_payload,
    create_club_member_payload,
    create_division_payload,
    create_entry_payload,
    create_mark_boat_payload,
    enrol_member,
    file_certificate,
    make_club_admin_headers,
    make_competitor_headers,
    make_measurer_headers,
    open_regatta,
    publish_nor,
    read_boat,
    read_entry,
    register_boat,
    submit_entry,
)

ADMIN = make_club_admin_headers()


def test_a_member_enrolled_with_only_the_two_required_inputs_carries_row_defaults(api):
    """PRD 3.1: "Three credential fields are optional at enrolment and default to
    nothing: `measurer_license_id` defaults to null, `judge_certification_level`
    defaults to `NONE`, and `safety_course_expiry_utc` defaults to null. The
    certification ladder runs `NONE`, `CLUB`, `REGIONAL`, `NATIONAL`,
    `INTERNATIONAL`, and only the top three rungs qualify a member to chair a jury.
    A member's duty ledger, `assigned_duty_minutes`, is initialised to 0."

    Design: Corner/entities/club_member_creation_returns_declared_defaults
    """
    plain = validate_success(
        api.create_club_member(create_club_member_payload(full_name="Owen Clay"), ADMIN),
        expected_status=201,
    )

    assert plain["measurer_license_id"] is None
    assert plain["judge_certification_level"] == "NONE"
    assert plain["safety_course_expiry_utc"] is None
    assert plain["assigned_duty_minutes"] == 0
    assert plain["version"] == 1
    assert is_valid_uuid(plain["id"])
    assert is_iso8601_timestamp(plain["created_at"])
    assert is_iso8601_timestamp(plain["updated_at"])

    credentialed = validate_success(
        api.create_club_member(
            create_club_member_payload(
                full_name="Mara Vance",
                measurer_license_id="M-101",
                judge_certification_level="REGIONAL",
                safety_course_expiry_utc=SAFETY_COURSE_OK_UNTIL,
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    assert credentialed["measurer_license_id"] == "M-101", (
        "the defaults are row defaults, not a server that ignores optional inputs"
    )
    assert credentialed["judge_certification_level"] == "REGIONAL"
    assert credentialed["safety_course_expiry_utc"] == SAFETY_COURSE_OK_UNTIL
    assert credentialed["assigned_duty_minutes"] == 0


def test_a_boat_read_back_returns_the_registration_it_stored(api):
    """PRD 3.1: "A registration carries a `sail_number` unique across every boat in
    the register — again compared case-insensitively, between 3 and 12 characters,
    and refused with `ERR_DUPLICATE_RECORD` on collision — a `boat_name`, an
    `owner_member_id` naming the member of record who may submit entries for that
    boat, a `boat_type` of `MONOHULL`, `MULTIHULL` or `KEELBOAT_SPORT`, and a
    declared `loa_meters` greater than 0 and at most 40."

    PRD 3.1 also fixes the version the read must show: "A newly registered boat's
    `version` is 1, which is the value the first certificate creation must echo."

    Design: Corner/entities/boat_retrieval_returns_stored_measurement_owner_and_version
    """
    owner = enrol_member(full_name="Owen Clay")
    created = validate_success(
        api.create_boat(
            create_boat_payload(
                owner["id"], sail_number="USA-4410", boat_name="Windward Rose",
                boat_type="MONOHULL", loa_meters=11.3,
            ),
            make_competitor_headers(owner["id"]),
        ),
        expected_status=201,
    )

    stored = validate_success(api.get_boat(created["id"], ADMIN))

    assert stored["id"] == created["id"]
    assert stored["sail_number"] == "USA-4410"
    assert stored["boat_name"] == "Windward Rose"
    assert stored["owner_member_id"] == owner["id"]
    assert stored["boat_type"] == "MONOHULL"
    assert stored["loa_meters"] == 11.3
    assert stored["version"] == 1, "no certificate has been filed against it yet"


def test_the_boat_listing_pages_and_filters_and_counts_the_filtered_set(api):
    """PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` in `meta`, where `total_count` is the number of rows matching the
    filters before the page window is applied and `has_more` states whether any
    matching row remains after the current window."

    PRD 2.11 names the two filters this collection offers: "Boats filter on
    `owner_member_id` and `boat_type`."

    Design: Corner/entities/boats_listing_paginates_and_filters_by_hull_type
    """
    first_owner = enrol_member(full_name="Owen Clay")
    second_owner = enrol_member(full_name="Rhea Voss")
    mono_a = register_boat(first_owner["id"])
    mono_b = register_boat(second_owner["id"])
    multi = register_boat(first_owner["id"], boat_type="MULTIHULL")

    page_one, meta_one = validate_paginated(api.list_boats(ADMIN, {"limit": 2, "offset": 0}))
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(api.list_boats(ADMIN, {"limit": 2, "offset": 2}))
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False

    multis, meta_multi = validate_paginated(
        api.list_boats(ADMIN, {"boat_type": "MULTIHULL", "limit": 10, "offset": 0})
    )
    assert [row["id"] for row in multis] == [multi["id"]]
    assert meta_multi["total_count"] == 1, "total_count counts the filtered set"
    assert meta_multi["has_more"] is False

    owned, meta_owned = validate_paginated(
        api.list_boats(ADMIN, {"owner_member_id": first_owner["id"], "limit": 10, "offset": 0})
    )
    assert meta_owned["total_count"] == 2
    assert sorted(row["id"] for row in owned) == sorted([mono_a["id"], multi["id"]])
    assert mono_b["id"] not in [row["id"] for row in owned]


def test_an_unknown_certificate_id_is_absence_rather_than_a_broken_route(api, roster):
    """PRD 2.7 item 8: "Every `id` in the path resolves, checked left to right, and
    then every foreign key in the body resolves, checked in the order the endpoint
    declares its inputs, else `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/rating_certificate_not_found_returns_404
    """
    boat = register_boat(roster["helm_1"]["id"])
    certificate = file_certificate(boat["id"], roster["measurer"]["id"])

    validate_error(
        api.get_certificate(UNKNOWN_UUID, ADMIN),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        expected_status=404,
    )

    found = validate_success(api.get_certificate(certificate["id"], ADMIN))
    assert found["id"] == certificate["id"]
    assert found["status"] == "DRAFT"


def test_a_division_missing_its_upper_band_and_one_carrying_a_foreign_field_are_both_shape_errors(api, roster, headers):
    """PRD 2.7 item 6: "The body parses, every required input field of the endpoint
    is present and non-null, no unknown field is present, every enum-valued field
    carries a declared member, and every numeric field satisfies its declared range,
    else `ERR_INVALID_REQUEST`."

    The shape check outranks the phase check, so the regatta being still `DRAFT`
    never masks either rejection.

    Design: Corner/entities/division_missing_rating_band_high_returns_invalid_request
    """
    regatta = open_regatta(roster["chair"]["id"])
    chair = headers["chair"]
    payload = create_division_payload(regatta["id"])
    payload.pop("rating_band_high")

    validate_error(
        api.create_division(payload, chair),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )
    validate_error(
        api.create_division(create_division_payload(regatta["id"], fleet_minimum=2), chair),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    rows, pagination = validate_paginated(
        api.list_divisions(chair, {"regatta_id": regatta["id"]})
    )
    assert rows == []
    assert pagination["total_count"] == 0, "neither rejected call created a row"
    assert validate_success(api.get_regatta(regatta["id"], chair))["status"] == "DRAFT"
    assert validate_success(api.get_regatta(regatta["id"], chair))["version"] == 1


def test_a_mark_boat_chartered_without_its_two_knobs_takes_the_declared_defaults(api, roster, headers):
    """PRD 3.6: "`concurrent_assignment_limit`, defaulting to 2 and constrained to
    between 1 and 6, caps how many non-released duties may overlap that boat at any
    instant. `turnaround_buffer_minutes`, defaulting to 20 minutes and constrained
    to between 0 and 120, is added to **both** ends of every window already
    committed on that boat before overlap is tested, which is why two windows that
    merely touch nose-to-tail still collide on a mark boat. A newly chartered boat's
    `committed_minutes` is 0."

    Design: Corner/entities/mark_boat_defaults_apply_limit_two_and_buffer_twenty
    """
    regatta = open_regatta(roster["chair"]["id"])
    chair = headers["chair"]

    defaulted = validate_success(
        api.create_mark_boat(
            create_mark_boat_payload(regatta["id"], crew_capacity=4), chair
        ),
        expected_status=201,
    )

    assert defaulted["concurrent_assignment_limit"] == 2
    assert defaulted["turnaround_buffer_minutes"] == 20
    assert defaulted["committed_minutes"] == 0
    assert defaulted["crew_capacity"] == 4
    assert defaulted["version"] == 1

    explicit = validate_success(
        api.create_mark_boat(
            create_mark_boat_payload(
                regatta["id"], crew_capacity=3,
                concurrent_assignment_limit=1, turnaround_buffer_minutes=0,
            ),
            chair,
        ),
        expected_status=201,
    )

    assert explicit["concurrent_assignment_limit"] == 1
    assert explicit["turnaround_buffer_minutes"] == 0, (
        "the defaults are not hard-wired constants in the overlap rule"
    )


def _crewed_entry(roster):
    """One submitted entry carrying a helm at 84.5 kg and a trimmer at 79.25 kg,
    so its computed crew weight sums to 163.75 before rounding."""
    regatta = open_regatta(roster["chair"]["id"])
    publish_nor(regatta["id"], roster["chair"]["id"])
    boat = register_boat(roster["helm_1"]["id"])
    certificate = file_certificate(boat["id"], roster["measurer"]["id"])
    entry = submit_entry(
        regatta["id"], boat["id"], certificate["id"], roster["helm_1"]["id"],
        declared_crew_count=3,
    )
    add_crew(entry["id"], roster["helm_1"]["id"], roster["helm_1"]["id"],
             position="HELM", weight_kg=84.5)
    entry = add_crew(entry["id"], roster["helm_1"]["id"], roster["helm_2"]["id"],
                     position="TRIM", weight_kg=79.25)
    return entry


def test_the_crew_weight_is_recomputed_by_the_server_and_may_not_be_supplied(api, roster):
    """PRD 3.5: "Each addition appends an element to `crew_manifest`, increments
    `registered_crew_count` by one, adds the declared `weight_kg` into
    `crew_weight_kg` — which is maintained rounded half-up to one decimal place —
    and advances the entry's `version`."

    PRD 2.7 item 6 forbids the client from writing it: "The body parses, every
    required input field of the endpoint is present and non-null, no unknown field
    is present, every enum-valued field carries a declared member, and every numeric
    field satisfies its declared range, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/crew_weight_recomputed_from_manifest_and_extra_field_rejected
    """
    entry = _crewed_entry(roster)
    helm = make_competitor_headers(roster["helm_1"]["id"])

    validate_error(
        api.add_crew(
            entry["id"],
            add_crew_payload(
                roster["helm_3"]["id"], position="BOW", weight_kg=70.0,
                crew_weight_kg=500.0,
            ),
            helm,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    unchanged = read_entry(entry["id"])
    assert unchanged["crew_weight_kg"] == 163.8, (
        "84.5 plus 79.25 is 163.75, which rounds half-up to 163.8"
    )
    assert unchanged["registered_crew_count"] == 2
    assert unchanged["declared_crew_count"] == 3
    assert len(unchanged["crew_manifest"]) == 2
    positions = {row["member_id"]: row["position"] for row in unchanged["crew_manifest"]}
    assert positions[roster["helm_1"]["id"]] == "HELM"
    assert positions[roster["helm_2"]["id"]] == "TRIM"
    assert unchanged["version"] == 3, (
        "submission plus one per accepted crew call, with nothing from the refusal"
    )


def test_the_certificate_records_the_measurer_from_the_header_not_the_body(api, roster):
    """PRD 3.2: "The filed row is minted in status `DRAFT`, its
    `measured_by_member_id` is set from the acting measurer's identity,
    `suspension_reason_code` and `supersedes_certificate_id` both start null, and
    the boat's `version` advances by one."

    Design: Corner/entities/certificate_measured_by_member_id_taken_from_actor_header
    """
    measurer_id = roster["measurer"]["id"]
    boat = register_boat(roster["helm_1"]["id"])
    assert read_boat(boat["id"])["version"] == 1

    created = validate_success(
        api.create_certificate(
            create_certificate_payload(
                boat["id"], 1,
                rule_code="TOD_PHRF",
                valid_from=CERT_VALID_FROM, valid_until=CERT_VALID_UNTIL,
                **MEASUREMENT_A,
            ),
            make_measurer_headers(measurer_id),
        ),
        expected_status=201,
    )

    assert created["measured_by_member_id"] == measurer_id, (
        "copied from the acting identity, not from the body"
    )
    assert created["status"] == "DRAFT"
    assert created["supersedes_certificate_id"] is None
    assert created["suspension_reason_code"] is None
    assert created["raw_speed_index"] == 0.6545
    assert created["rating_value"] == 171.3
    assert created["band_key_spm"] == 171.3
    assert created["version"] == 1
    assert read_boat(boat["id"])["version"] == 2, (
        "the certificate create is also the version bump the next create must echo"
    )


def test_an_undeclared_hull_type_and_an_over_length_boat_are_both_shape_errors(api):
    """PRD 3.1: "A registration carries a `sail_number` unique across every boat in
    the register — again compared case-insensitively, between 3 and 12 characters,
    and refused with `ERR_DUPLICATE_RECORD` on collision — a `boat_name`, an
    `owner_member_id` naming the member of record who may submit entries for that
    boat, a `boat_type` of `MONOHULL`, `MULTIHULL` or `KEELBOAT_SPORT`, and a
    declared `loa_meters` greater than 0 and at most 40."

    Design: Corner/entities/boat_type_invalid_enum_rejected
    """
    owner = enrol_member(full_name="Owen Clay")
    competitor = make_competitor_headers(owner["id"])

    validate_error(
        api.create_boat(
            create_boat_payload(owner["id"], sail_number="USA-4410", boat_type="TRIMARAN"),
            competitor,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )
    validate_error(
        api.create_boat(
            create_boat_payload(owner["id"], sail_number="USA-4410", loa_meters=45.0),
            competitor,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    accepted = validate_success(
        api.create_boat(
            create_boat_payload(owner["id"], sail_number="USA-4410", loa_meters=11.3),
            competitor,
        ),
        expected_status=201,
    )
    assert accepted["loa_meters"] == 11.3
    assert accepted["boat_type"] == "MONOHULL"

    rows, pagination = validate_paginated(
        api.list_boats(ADMIN, {"owner_member_id": owner["id"]})
    )
    assert pagination["total_count"] == 1, "the two rejected calls created nothing"
    assert rows[0]["id"] == accepted["id"]


def test_an_entry_may_not_pin_a_certificate_measured_on_a_different_boat(api, roster):
    """PRD 3.5: "At submission the pinned certificate's validity window must cover
    the regatta's `series_start_utc`, both bounds inclusive, or the submission is
    refused with `ERR_CERTIFICATE_EXPIRED`; and the certificate must belong to the
    boat named by the entry and the boat must belong to the same event context, or
    the submission is refused with `ERR_CROSS_REGATTA_REFERENCE`."

    PRD 3.5 also fixes the shape of the row the legal request creates: "A new entry
    carries two independent status dimensions: `registration_status` starts at
    `SUBMITTED` and `inspection_status` at `NOT_INSPECTED`."

    Design: Corner/entities/entry_certificate_of_another_boat_rejected
    """
    regatta = open_regatta(roster["chair"]["id"])
    publish_nor(regatta["id"], roster["chair"]["id"])
    own_boat = register_boat(roster["helm_1"]["id"])
    other_boat = register_boat(roster["helm_2"]["id"])
    own_certificate = file_certificate(own_boat["id"], roster["measurer"]["id"])
    other_certificate = file_certificate(other_boat["id"], roster["measurer"]["id"])
    helm = make_competitor_headers(roster["helm_1"]["id"])

    validate_error(
        api.create_entry(
            create_entry_payload(
                regatta["id"], own_boat["id"], other_certificate["id"],
                roster["helm_1"]["id"],
            ),
            helm,
        ),
        ApiErrorId.ERR_CROSS_REGATTA_REFERENCE,
        expected_status=409,
    )

    accepted = validate_success(
        api.create_entry(
            create_entry_payload(
                regatta["id"], own_boat["id"], own_certificate["id"],
                roster["helm_1"]["id"],
            ),
            helm,
        ),
        expected_status=201,
    )

    assert accepted["certificate_id"] == own_certificate["id"]
    assert accepted["registration_status"] == "SUBMITTED"
    assert accepted["inspection_status"] == "NOT_INSPECTED"
    assert accepted["division_id"] is None

    rows, pagination = validate_paginated(
        api.list_entries(ADMIN, {"regatta_id": regatta["id"]})
    )
    assert pagination["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]
