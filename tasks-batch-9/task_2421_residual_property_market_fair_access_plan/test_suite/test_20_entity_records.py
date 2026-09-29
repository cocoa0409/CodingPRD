"""Entity records: creation echoes, defaults, computed fields, identity and lookups.

These tests exercise the registries the plan is built on — member insurers,
catastrophe territories, producers, applicants, properties, applications and
declination records — asserting what each create call stores, what it defaults,
what it refuses, and how an unresolved identifier is reported.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field_equals,
    assert_field_null,
    assert_fields_absent,
    assert_fields_equal,
    assert_identity_fields,
    assert_instant_equals,
    assert_pagination_meta,
    assert_pct,
    assert_ratio,
    assert_versioned_record,
)
from test_helpers.constants import (
    AGREEMENT_STATUS_APPOINTED,
    CLOCK_ORIGIN,
    COMMISSION_BPS_PREFERRED,
    COMMISSION_BPS_STANDARD,
    COMMISSION_TIER_PREFERRED,
    DEFAULT_RESTRICTED_MIN_CONDITION_SCORE,
    PERIL_HURRICANE,
    PERIL_WILDFIRE,
    ZONE_STATUS_OPEN,
)
from test_helpers.fixtures import (
    add_declination,
    build_foundations,
    create_appointed_producer,
    create_draft_application,
    create_member_insurer,
    create_zone,
    pin_clock,
    read_producer,
)
from test_helpers.test_users import (
    admin_headers,
    make_producer_headers,
    regulator_headers,
    reviewer_headers,
)

UNUSED_UUID = "00000000-0000-4000-8000-000000000000"


def test_member_insurer_created_with_all_required_fields_returns_201(client):
    """Admitting a carrier returns 201 and echoes the four submitted fields.

    PRD: "Admitting a carrier records its legal `name`, its regulator-issued
    `naic_code` (exactly five characters, and unique across all carriers), its
    statewide homeowners `market_share_pct`, and its share of statewide written
    premium as `written_premium_share_pct`."

    PRD: "A newly admitted carrier begins in `status` `ACTIVE`, with
    `takeout_credit_count` at 0 and `cumulative_assessed_cents` at 0."

    Design: Corner/entities/member_insurer_created_with_all_required_fields_returns_201
    """
    pin_clock(client, CLOCK_ORIGIN)

    response = client.create_member_insurer(
        f.member_insurer_payload(
            name="Carrier One",
            naic_code="10001",
            market_share_pct=30.00,
            written_premium_share_pct=10.00,
        ),
        admin_headers(),
    )

    member = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assert_fields_equal(member, {"name": "Carrier One", "naic_code": "10001"})
    assert_pct(member["market_share_pct"], "30.00", "market_share_pct")
    assert_pct(member["written_premium_share_pct"], "10.00", "written_premium_share_pct")


def test_cat_zone_retrieved_by_id_returns_the_stored_row(client):
    """A territory read back reports its stored creation fields and an open posture.

    PRD: "It is created with a unique `code`, a dominant `peril` drawn from
    `HURRICANE`, `WILDFIRE` and `EARTHQUAKE`, an `exposure_cap_cents` that must
    be greater than zero, and an optional `restricted_min_condition_score`
    between 0 and 100 inclusive that defaults to 70 when the creator omits it."

    PRD: "A newly created territory starts with an aggregate insured value of 0, a
    concentration ratio of 0.0 and a status of `OPEN`."

    Design: Corner/entities/cat_zone_retrieved_by_id_returns_the_stored_row
    """
    pin_clock(client, CLOCK_ORIGIN)
    zone = create_zone(
        client, code="HUR-01", peril=PERIL_HURRICANE, exposure_cap_cents=100_000_000
    )

    stored = validate_success(client.get_cat_zone(zone["id"], regulator_headers()), 200)

    assert_fields_equal(stored, {"code": "HUR-01", "peril": PERIL_HURRICANE})
    assert_cents(stored["exposure_cap_cents"], 100_000_000, "exposure_cap_cents")
    assert_cents(
        stored["aggregate_insured_value_cents"], 0, "aggregate_insured_value_cents"
    )
    assert_ratio(stored["concentration_ratio"], "0.0000", "concentration_ratio")
    assert_field_equals(stored, "status", ZONE_STATUS_OPEN)


def test_member_insurer_list_paginates_with_total_count_and_has_more(client):
    """Two pages over three carriers report the full count and the right has_more.

    PRD: "Every list response includes `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope. `total_count` is the number of rows
    matching the filters before pagination is applied, and `has_more` is true
    exactly when rows remain beyond the current page."

    Design: Corner/entities/member_insurer_list_paginates_with_total_count_and_has_more
    """
    pin_clock(client, CLOCK_ORIGIN)
    create_member_insurer(client, name="Carrier One", naic_code="10001")
    create_member_insurer(client, name="Carrier Two", naic_code="10002")
    create_member_insurer(
        client,
        name="Carrier Three",
        naic_code="10003",
        market_share_pct=40.00,
        written_premium_share_pct=80.00,
    )

    first_response = client.list_member_insurers(
        admin_headers(), {"limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)
    second_page, second_meta = validate_paginated(
        client.list_member_insurers(admin_headers(), {"limit": 2, "offset": 2})
    )

    assert first_response.json()["response_type"] == "array"
    assert_count(first_page, 2, "first page")
    assert_pagination_meta(first_meta, total_count=3, limit=2, offset=0, has_more=True)
    assert_count(second_page, 1, "second page")
    assert_pagination_meta(second_meta, total_count=3, limit=2, offset=2, has_more=False)


def test_member_insurer_get_with_unknown_id_returns_not_found(client):
    """An unused but well-formed UUID on the carrier read is a 404.

    PRD: "When a path contains several identifiers, they are resolved strictly **left
    to right**, and the first one that does not resolve produces `ERR_NOT_FOUND`
    (HTTP 404) before any identifier to its right is examined."

    Design: Corner/entities/member_insurer_get_with_unknown_id_returns_not_found
    """
    pin_clock(client, CLOCK_ORIGIN)

    response = client.get_member_insurer(UNUSED_UUID, admin_headers())

    validate_error(response, ERR_NOT_FOUND)
    assert response.json()["response_type"] == "error"


def test_producer_create_missing_commission_tier_returns_invalid_request(client):
    """Registering a producer without a commission tier is a schema violation.

    PRD: "Registering a licensed agent records `full_name`, a `license_number` unique
    across all producers, a `commission_tier` of either `STANDARD` or
    `PREFERRED`, and the agent's errors-and-omissions expiry as
    `e_and_o_expiry_date`."

    PRD: "Required body fields present, enum values recognized, integers non-negative,
    dates well-formed ISO-8601, condition scores between 0 and 100 inclusive,
    `limit` between 1 and 100, `offset` at least 0, `evidence_reference` a
    non-empty string, and no client-supplied `cancel_reason` of
    `TAKEOUT_ELECTION`. Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/producer_create_missing_commission_tier_returns_invalid_request
    """
    pin_clock(client, CLOCK_ORIGIN)
    payload = f.producer_payload(
        full_name="Pat Agent",
        license_number="P-1001",
        e_and_o_expiry_date="2027-06-30",
    )
    payload.pop("commission_tier")

    response = client.create_producer(payload, admin_headers())

    validate_error(response, ERR_INVALID_REQUEST)


def test_applicant_created_without_phone_defaults_to_null(client):
    """An applicant created without a phone stores null rather than an empty string.

    PRD: "The **named insured** is created with a `full_name`, an `email` unique
    across all applicants, and an optional `phone` that defaults to null."

    Design: Corner/entities/applicant_created_without_phone_defaults_to_null
    """
    pin_clock(client, CLOCK_ORIGIN)
    producer = create_appointed_producer(client)

    response = client.create_applicant(
        f.applicant_payload(full_name="Ann Owner", email="ann@example.com"),
        make_producer_headers(producer["id"]),
    )

    applicant = validate_success(response, 201)
    assert_fields_equal(applicant, {"full_name": "Ann Owner", "email": "ann@example.com"})
    assert_field_null(applicant, "phone")


def test_cat_zone_created_without_restricted_min_condition_score_defaults_to_seventy(
    client,
):
    """Omitting the restricted-territory condition floor stores exactly seventy.

    PRD: "It is created with a unique `code`, a dominant `peril` drawn from
    `HURRICANE`, `WILDFIRE` and `EARTHQUAKE`, an `exposure_cap_cents` that must
    be greater than zero, and an optional `restricted_min_condition_score`
    between 0 and 100 inclusive that defaults to 70 when the creator omits it."

    Design: Corner/entities/cat_zone_created_without_restricted_min_condition_score_defaults_to_seventy
    """
    pin_clock(client, CLOCK_ORIGIN)
    payload = f.cat_zone_payload(
        code="WF-01", peril=PERIL_WILDFIRE, exposure_cap_cents=100_000_000
    )
    payload.pop("restricted_min_condition_score")

    response = client.create_cat_zone(payload, admin_headers())

    zone = validate_success(response, 201)
    assert_field_equals(
        zone, "restricted_min_condition_score", DEFAULT_RESTRICTED_MIN_CONDITION_SCORE
    )


def test_producer_commission_rate_bps_computed_from_commission_tier(client):
    """The commission rate is zero until appointment, then fixed from the tier.

    PRD: "Registration leaves the agreement unexecuted: `agreement_status` is
    `PENDING`, `commission_rate_bps` is 0, `agreement_effective_date` is null,
    and the conserved `ytd_commission_cents` is 0."

    PRD: "Executing the producer agreement — which requires the agreement to
    currently be `PENDING` — carries an `agreement_effective_date` in the
    request, moves `agreement_status` from `PENDING` to `APPOINTED`, and fixes
    the commission rate from the tier: a `STANDARD` tier writes 1,000 basis
    points (ten percent of commissionable premium), and a `PREFERRED` tier
    writes 1,250 basis points (twelve and a half percent)."

    Design: Corner/entities/producer_commission_rate_bps_computed_from_commission_tier
    """
    pin_clock(client, CLOCK_ORIGIN)
    pending_standard = get_success_data(
        client.create_producer(
            f.producer_payload(full_name="Pat Agent", license_number="P-1001"),
            admin_headers(),
        )
    )
    pending_preferred = get_success_data(
        client.create_producer(
            f.producer_payload(
                full_name="Dana Agent",
                license_number="P-1002",
                commission_tier=COMMISSION_TIER_PREFERRED,
            ),
            admin_headers(),
        )
    )
    assert_field_equals(pending_standard, "commission_rate_bps", 0)
    assert_field_equals(pending_preferred, "commission_rate_bps", 0)

    validate_success(
        client.execute_producer_agreement(
            pending_standard["id"],
            f.agreement_execution_payload("2026-08-01"),
            admin_headers(),
        ),
        200,
    )
    validate_success(
        client.execute_producer_agreement(
            pending_preferred["id"],
            f.agreement_execution_payload("2026-08-01"),
            admin_headers(),
        ),
        200,
    )

    standard = read_producer(client, pending_standard["id"])
    preferred = read_producer(client, pending_preferred["id"])
    assert_field_equals(standard, "agreement_status", AGREEMENT_STATUS_APPOINTED)
    assert_field_equals(standard, "commission_rate_bps", COMMISSION_BPS_STANDARD)
    assert_field_equals(standard, "agreement_effective_date", "2026-08-01")
    assert_field_equals(preferred, "commission_rate_bps", COMMISSION_BPS_PREFERRED)


def test_member_insurer_system_fields_are_server_minted_with_version_one(client):
    """Identity, audit fields and the envelope meta are all minted by the server.

    PRD: "Every persisted record carries a server-minted `id` formatted as a UUID
    with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC
    string with three fractional digits."

    PRD: "Most records additionally carry two mutation-tracking fields: `updated_at`,
    an ISO 8601 UTC timestamp with three fractional digits refreshed on every
    change to the record, and `version`, an integer that begins at 1 when the
    record is created and increases by exactly one on every mutation of that
    record."

    PRD: "The server does not read wall-clock time for any business comparison. It
    maintains a **logical clock** whose value at process start is exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    PRD: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/entities/member_insurer_system_fields_are_server_minted_with_version_one
    """
    pin_clock(client, CLOCK_ORIGIN)

    response = client.create_member_insurer(f.member_insurer_payload(), admin_headers())

    member = validate_success(response, 201)
    assert_versioned_record(member, expected_version=1)
    assert_instant_equals(member["created_at"], CLOCK_ORIGIN, "created_at")
    assert_instant_equals(member["updated_at"], CLOCK_ORIGIN, "updated_at")
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert isinstance(meta.get("api_request_timestamp"), str)


def test_cat_zone_create_with_unknown_peril_enum_rejected(client):
    """A peril outside the three declared values is a schema violation.

    PRD: "It is created with a unique `code`, a dominant `peril` drawn from
    `HURRICANE`, `WILDFIRE` and `EARTHQUAKE`, an `exposure_cap_cents` that must
    be greater than zero, and an optional `restricted_min_condition_score`
    between 0 and 100 inclusive that defaults to 70 when the creator omits it."

    PRD: "Required body fields present, enum values recognized, integers non-negative,
    dates well-formed ISO-8601, condition scores between 0 and 100 inclusive,
    `limit` between 1 and 100, `offset` at least 0, `evidence_reference` a
    non-empty string, and no client-supplied `cancel_reason` of
    `TAKEOUT_ELECTION`. Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/cat_zone_create_with_unknown_peril_enum_rejected
    """
    pin_clock(client, CLOCK_ORIGIN)

    response = client.create_cat_zone(
        f.cat_zone_payload(code="FL-01", peril="FLOOD", exposure_cap_cents=100_000_000),
        admin_headers(),
    )

    validate_error(response, ERR_INVALID_REQUEST)


def test_property_create_with_condition_score_above_one_hundred_rejected(client):
    """A condition score of 101 is outside the inclusive zero-to-hundred range.

    PRD: "The **property** is created inside a territory, naming its `cat_zone_id`,
    its `address_line`, its `zip_code`, a `construction_type` of `FRAME`,
    `MASONRY` or `MOBILE`, a `roof_age_years` count of whole years that must be
    zero or greater, a `replacement_cost_cents` greater than zero, a
    producer-reported `condition_score` between 0 and 100 inclusive, and an
    `occupancy` of `OWNER_OCCUPIED`, `TENANT_OCCUPIED` or `VACANT`."

    PRD: "Required body fields present, enum values recognized, integers non-negative,
    dates well-formed ISO-8601, condition scores between 0 and 100 inclusive,
    `limit` between 1 and 100, `offset` at least 0, `evidence_reference` a
    non-empty string, and no client-supplied `cancel_reason` of
    `TAKEOUT_ELECTION`. Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/property_create_with_condition_score_above_one_hundred_rejected
    """
    pin_clock(client, CLOCK_ORIGIN)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    producer = create_appointed_producer(client)

    response = client.create_property(
        f.property_payload(cat_zone_id=zone["id"], condition_score=101),
        make_producer_headers(producer["id"]),
    )

    validate_error(response, ERR_INVALID_REQUEST)
    _rows, meta = validate_paginated(
        client.list_cat_zone_properties(zone["id"], admin_headers(), {"limit": 10})
    )
    assert_field_equals(meta, "total_count", 0)


def test_declination_record_is_immutable_and_exposes_no_version_field(client):
    """A declination carries only identity fields, with no mutation counters.

    PRD: "There is one deliberate exception. A declination record is an immutable
    piece of eligibility evidence: it carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from a declination record entirely."

    PRD: "At creation the server computes `verified`: it is true when the named
    carrier's membership `status` is `ACTIVE` at that moment **and** the
    `evidence_reference` is non-empty, and false otherwise."

    Design: Corner/entities/declination_record_is_immutable_and_exposes_no_version_field
    """
    foundations = build_foundations(client, clock=CLOCK_ORIGIN)
    chain = create_draft_application(client, foundations)
    add_declination(
        chain,
        foundations.member_ids[0],
        declined_on="2026-07-15",
        evidence_reference="DEC-1",
    )

    rows, meta = validate_paginated(
        client.list_application_declinations(
            chain.application_id, reviewer_headers(), {"limit": 10}
        )
    )

    assert_count(rows, 1, "declinations")
    assert_field_equals(meta, "total_count", 1)
    declination = rows[0]
    assert_identity_fields(declination)
    assert_fields_absent(declination, ("version", "updated_at"))
    assert_field_equals(declination, "verified", True)


def test_inspection_order_on_unknown_application_returns_not_found(client):
    """Ordering an inspection against an unused application id is a 404.

    PRD: "When a path contains several identifiers, they are resolved strictly **left
    to right**, and the first one that does not resolve produces `ERR_NOT_FOUND`
    (HTTP 404) before any identifier to its right is examined."

    Design: Corner/entities/inspection_order_on_unknown_application_returns_not_found
    """
    pin_clock(client, CLOCK_ORIGIN)

    response = client.order_inspection(UNUSED_UUID, {}, reviewer_headers())

    validate_error(response, ERR_NOT_FOUND)


def test_property_create_with_unknown_cat_zone_id_returns_not_found(client):
    """A body foreign key that resolves to no territory is a 404, not a 400.

    PRD: "Foreign keys supplied in a request body are resolved after path
    identifiers, and also produce `ERR_NOT_FOUND`."

    Design: Corner/entities/property_create_with_unknown_cat_zone_id_returns_not_found
    """
    pin_clock(client, CLOCK_ORIGIN)
    producer = create_appointed_producer(client)

    response = client.create_property(
        f.property_payload(cat_zone_id=UNUSED_UUID),
        make_producer_headers(producer["id"]),
    )

    validate_error(response, ERR_NOT_FOUND)
