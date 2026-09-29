"""Registry record shapes, declared defaults, derived fields and navigation.

These tests pin what the register actually stores and returns: the common record
properties the server mints, the declared opening values of every optional or
computed field, the field-level shape checks that run ahead of any business
rule, the per-entity not-found codes, and the listing envelope that makes the
graph walkable.

Every test builds its own registry state from scratch through the program's own
endpoints, so no test depends on another's residue.
"""
import pytest

from test_helpers import (
    CANONICAL_BASELINE_UNITS,
    CLOCK_STARTUP_DEFAULT,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_certificate,
    assert_certificate_transfer,
    assert_conservation_easement,
    assert_party,
    assert_receiving_area,
    assert_same_instant,
    assert_sending_parcel,
    create_active_sending_area,
    create_party_payload,
    create_receiving_area_payload,
    create_sending_parcel_payload,
    create_severance_application_payload,
    designate_sending_area,
    fetch_certificate,
    fetch_easement,
    fetch_party,
    fetch_sending_area,
    is_valid_uuid,
    make_landowner_headers,
    register_landowner,
    set_clock,
    setup_certified_severance,
    split_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLOCK = "2026-08-10T00:00:00Z"
EAST_AREA_CODE = "SA-EAST"
EAST_NEIGHBORHOOD = "NB-EAST"


def test_party_creation_returns_the_full_declared_field_set():
    """Registering a party returns every declared field at its opening value.

    PRD §3.1: "A `ProgramAdministrator` registers each participant as a **Party**,
    supplying its `kind`, its `legal_name` (between 1 and 120 characters), its
    `contact_email` (which must contain an at-sign), and optionally its
    `neighborhood_code` (between 1 and 24 characters when supplied, and null when
    omitted, where it is used only in equity reporting)."

    PRD §3.1: "A newly registered party opens with `cash_balance_cents` at 0,
    `fee_revenue_cents` at 0, `units_held` at 0, `certificates_held_count` at 0,
    and `status` of `ACTIVE`."

    PRD §2.4: "Every resource the API returns carries an `id`, which is a
    server-minted UUID with no type prefix and no embedded meaning."

    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly one on every mutation of that row, including
    mutations reached through a cascade rather than through a direct request."

    PRD §2.4: "`created_at` is the instant the row was first persisted,
    `updated_at` is the instant of its most recent mutation, and both are ISO 8601
    UTC timestamps with exactly three fractional digits (for example,
    `2026-08-01T00:00:00.000Z`)."

    PRD §2.5: "Nothing in this program reads wall-clock time." "Before any
    administrator sets it, that clock reads exactly `2026-08-01T00:00:00Z` — a
    fixed startup default that is never replaced by real time."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`." "The `response_type` is either "object"
    for a single resource or "array" for a list of resources."

    Design: Corner/entities/party_creation_returns_the_full_declared_field_set
    """
    resp = api_client.create_party(
        {
            "kind": "LANDOWNER",
            "legal_name": "Ridge Farm LLC",
            "contact_email": "ridge@example.org",
            "neighborhood_code": EAST_NEIGHBORHOOD,
        },
        ADMIN,
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object", (
        f"a single created resource is response_type object, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )

    assert_party(data)
    assert data["kind"] == "LANDOWNER", f"kind not echoed: {data['kind']!r}"
    assert data["legal_name"] == "Ridge Farm LLC", f"legal_name not echoed: {data['legal_name']!r}"
    assert data["contact_email"] == "ridge@example.org", (
        f"contact_email not echoed: {data['contact_email']!r}"
    )
    assert data["neighborhood_code"] == EAST_NEIGHBORHOOD, (
        f"neighborhood_code not echoed: {data['neighborhood_code']!r}"
    )

    assert data["cash_balance_cents"] == 0, "a new party opens with cash_balance_cents at 0"
    assert data["fee_revenue_cents"] == 0, "a new party opens with fee_revenue_cents at 0"
    assert data["units_held"] == 0, "a new party opens with units_held at 0"
    assert data["certificates_held_count"] == 0, (
        "a new party opens with certificates_held_count at 0"
    )
    assert data["status"] == "ACTIVE", f"a new party opens ACTIVE, got {data['status']!r}"
    assert data["version"] == 1, f"a freshly created row is at version 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID with no type prefix: {data['id']!r}"

    assert_same_instant(data["created_at"], CLOCK_STARTUP_DEFAULT, "Party.created_at")
    assert_same_instant(data["updated_at"], CLOCK_STARTUP_DEFAULT, "Party.updated_at")


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults():
    """An omitted neighborhood_code is null; an omitted whitelist is the empty list.

    PRD §3.1: "A `ProgramAdministrator` registers each participant as a **Party**,
    supplying its `kind`, its `legal_name` (between 1 and 120 characters), its
    `contact_email` (which must contain an at-sign), and optionally its
    `neighborhood_code` (between 1 and 24 characters when supplied, and null when
    omitted, where it is used only in equity reporting)."

    PRD §3.2: "That whitelist defaults to the empty list, and an empty list means
    every sending area is eligible; a non-empty list means only certificates whose
    origin sending area `code` appears in it may be redeemed here, with anything
    else rejected as `ERR_SENDING_RECEIVING_PAIR_NOT_ELIGIBLE`."

    PRD §3.2: "A new receiving area opens in `status` `DRAFT` with `absorbed_units`
    and `reserved_units` at 0, and activation moves it `DRAFT → ACTIVE` with a
    `version` increment, again rejecting a non-`DRAFT` area with
    `ERR_AREA_NOT_DRAFT`."

    Design: Corner/entities/party_neighborhood_code_defaults_to_null_when_omitted
    """
    party_payload = create_party_payload("DEVELOPER", legal_name="Core Block Partners")
    party_payload.pop("neighborhood_code")
    developer = validate_success(api_client.create_party(party_payload, ADMIN), 201)
    assert developer.get("neighborhood_code") is None, (
        "an omitted neighborhood_code is null, not an empty string: "
        f"{developer.get('neighborhood_code')!r}"
    )

    area_payload = create_receiving_area_payload(name="Core Receiving Area")
    area_payload.pop("eligible_sending_area_codes")
    area = validate_success(api_client.create_receiving_area(area_payload, ADMIN), 201)
    assert_receiving_area(area)
    assert area["eligible_sending_area_codes"] == [], (
        "an omitted eligible_sending_area_codes defaults to the empty list, not null: "
        f"{area['eligible_sending_area_codes']!r}"
    )
    assert area["absorbed_units"] == 0, "a new receiving area opens with absorbed_units at 0"
    assert area["reserved_units"] == 0, "a new receiving area opens with reserved_units at 0"
    assert area["status"] == "DRAFT", (
        f"a newly designated receiving area opens DRAFT, got {area['status']!r}"
    )
    assert area["version"] == 1, f"a freshly designated area is at version 1, got {area['version']}"


def test_account_action_amount_cents_combination_is_shape_checked():
    """CREDIT needs an amount; SUSPEND forbids one, and both misuses are 400s.

    PRD §3.1: "`amount_cents` is required for `CREDIT` and for `DEBIT`, and must be
    omitted for `SUSPEND` and `REINSTATE`; supplying it in the wrong combination is
    a malformed request."

    PRD §3.1: "A `CREDIT` adds `amount_cents` to `cash_balance_cents`; a `DEBIT`
    subtracts it, and is rejected with `ERR_INSUFFICIENT_FUNDS` when the resulting
    balance would be negative."

    PRD §2.10 rung 4: "**Request shape** — every required input field is present;
    types, enum membership, string lengths, decimal places and numeric ranges are
    honoured; `period_start` is not after `period_end`; `effective_from` is
    strictly before `effective_to`; any `units` figure is greater than zero; every
    field whose name ends in `_cents` is a non-negative integer; unknown fields are
    ignored rather than rejected. A failure here is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/account_action_credit_without_amount_is_rejected
    """
    party = validate_success(
        api_client.create_party(create_party_payload("DEVELOPER"), ADMIN), 201
    )
    observed_version = party["version"]

    credit_without_amount = api_client.party_account_action(
        party["id"], {"action": "CREDIT", "expected_party_version": observed_version}, ADMIN
    )
    validate_error(credit_without_amount, ApiErrorId.ERR_INVALID_REQUEST.value)

    suspend_with_amount = api_client.party_account_action(
        party["id"],
        {"action": "SUSPEND", "amount_cents": 100, "expected_party_version": observed_version},
        ADMIN,
    )
    validate_error(suspend_with_amount, ApiErrorId.ERR_INVALID_REQUEST.value)

    after = fetch_party(party["id"])
    assert after["cash_balance_cents"] == 0, (
        f"a rejected CREDIT moved money: {after['cash_balance_cents']}"
    )
    assert after["status"] == "ACTIVE", f"a rejected SUSPEND changed status: {after['status']!r}"
    assert after["version"] == observed_version, (
        f"a rejected account action bumped Party.version: {after['version']}"
    )


def test_field_level_constraints_reject_a_bad_enum_and_a_bad_email():
    """An out-of-enum soil_class and an at-sign-less email are both shape errors.

    PRD §3.3: "The `soil_class` is one of `PRIME`, `STATEWIDE`, `LOCAL`, or `NONE`."

    PRD §3.1: "A `ProgramAdministrator` registers each participant as a **Party**,
    supplying its `kind`, its `legal_name` (between 1 and 120 characters), its
    `contact_email` (which must contain an at-sign), and optionally its
    `neighborhood_code` (between 1 and 24 characters when supplied, and null when
    omitted, where it is used only in equity reporting)."

    PRD §2.10 rung 4: "**Request shape** — every required input field is present;
    types, enum membership, string lengths, decimal places and numeric ranges are
    honoured; `period_start` is not after `period_end`; `effective_from` is
    strictly before `effective_to`; any `units` figure is greater than zero; every
    field whose name ends in `_cents` is a non-negative integer; unknown fields are
    ignored rather than rejected. A failure here is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/sending_parcel_invalid_soil_class_enum_rejected
    """
    owner = register_landowner(neighborhood_code=EAST_NEIGHBORHOOD)
    area = create_active_sending_area(
        neighborhood_code=EAST_NEIGHBORHOOD,
        equity_tier="UNDERSERVED",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
    )

    bad_soil = create_sending_parcel_payload(
        owner["id"], area["id"], gross_acres=100.00, constrained_acres=22.00,
        soil_class="ROCKY", existing_dwelling_units=2,
    )
    validate_error(
        api_client.create_sending_parcel(bad_soil, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    bad_email = create_party_payload(
        "DEVELOPER", legal_name="No At Sign Ltd", contact_email="core-example.org"
    )
    validate_error(api_client.create_party(bad_email, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value)

    parcels, parcel_meta = validate_paginated(
        api_client.list_sending_parcels(ADMIN, params={"sending_area_id": area["id"]})
    )
    assert parcel_meta["total_count"] == 0, (
        f"the rejected enrollment persisted a parcel: {parcel_meta['total_count']}"
    )
    assert parcels == [], f"the rejected enrollment persisted a parcel: {parcels!r}"

    _, party_meta = validate_paginated(
        api_client.list_parties(ADMIN, params={"kind": "DEVELOPER"})
    )
    assert party_meta["total_count"] == 0, (
        f"the rejected registration persisted a party: {party_meta['total_count']}"
    )


def test_parcel_baseline_allocation_is_derived_at_enrollment():
    """baseline_allocation_units is computed from the parcel, never supplied.

    PRD §3.3: "Enrollment is where the parcel's development-right endowment is
    fixed, and it is fixed once. `baseline_allocation_units` is computed at
    enrollment and is **never recomputed afterwards**; every later severance reads
    it rather than restating it, so a subsequent ordinance amendment to the area's
    rates or formula cannot retroactively change what an already-enrolled parcel is
    worth. The computation proceeds in four steps. First, a soil multiplier is
    selected from the parcel's `soil_class`: `PRIME` yields a multiplier of 1.25,
    `STATEWIDE` yields 1.10, `LOCAL` yields 1.00, and `NONE` yields 0.75. Second,
    the eligible acreage is derived, and this is where the two ordinance formulas
    diverge. Under `V1_NET_ACRE`, eligible acreage is `gross_acres` minus
    `constrained_acres`, and `gross_discount_factor` is ignored entirely."

    PRD §3.3: "Third, a raw figure is formed as the eligible acreage multiplied by
    the area's `base_rate_units_per_acre` multiplied by the soil multiplier.
    Fourth, that raw figure is floored to a whole number — truncated downward,
    never rounded — the parcel's `existing_dwelling_units` are subtracted from the
    floored value because each already-built dwelling consumes one allocated right,
    and the result is taken as zero if the subtraction would go negative."

    PRD §3.3: "On enrollment the derived ledger fields open at their starting
    values: `remaining_units` equals `baseline_allocation_units`, `severed_units`
    is 0, `restricted_acres` is 0, `easement_status` is `NONE`, and `parcel_status`
    is `UNSEVERED`."

    PRD §3.2: "A newly designated sending area opens in `status` `DRAFT` with
    `severed_units_total` and `issued_certificate_count` both at 0."

    Design: Corner/entities/sending_parcel_baseline_is_computed_not_supplied
    """
    owner = register_landowner(neighborhood_code=EAST_NEIGHBORHOOD)
    area = create_active_sending_area(
        neighborhood_code=EAST_NEIGHBORHOOD,
        equity_tier="UNDERSERVED",
        allocation_formula_version="V1_NET_ACRE",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        sending_cap_units=200,
    )

    parcel = validate_success(
        api_client.create_sending_parcel(
            create_sending_parcel_payload(
                owner["id"], area["id"], gross_acres=50.00, constrained_acres=10.00,
                soil_class="STATEWIDE", existing_dwelling_units=1,
            ),
            ADMIN,
        ),
        201,
    )
    assert_sending_parcel(parcel)

    # (50.00 - 10.00) x 0.25 x 1.10 = 11.0, floored to 11, less 1 existing dwelling.
    assert parcel["baseline_allocation_units"] == 10, (
        "baseline_allocation_units must be derived at enrollment: expected 10, got "
        f"{parcel['baseline_allocation_units']}"
    )
    assert parcel["remaining_units"] == 10, (
        f"remaining_units opens equal to the baseline, got {parcel['remaining_units']}"
    )
    assert parcel["severed_units"] == 0, f"severed_units opens at 0, got {parcel['severed_units']}"
    assert float(parcel["restricted_acres"]) == pytest.approx(0.00, abs=0.01), (
        f"restricted_acres opens at 0.00, got {parcel['restricted_acres']}"
    )
    assert parcel["easement_status"] == "NONE", (
        f"easement_status opens NONE, got {parcel['easement_status']!r}"
    )
    assert parcel["parcel_status"] == "UNSEVERED", (
        f"parcel_status opens UNSEVERED, got {parcel['parcel_status']!r}"
    )

    assert fetch_sending_area(area["id"])["severed_units_total"] == 0, (
        "enrolling a parcel severs nothing, so severed_units_total stays 0"
    )


def test_unknown_path_identifier_returns_the_entitys_own_not_found_code():
    """A valid UUID naming no row yields that entity's own 404 identifier.

    PRD §2.9: "Path identifiers are resolved strictly left to right, and the
    leftmost identifier that fails to resolve decides the error. Each entity has
    its own not-found code, all at HTTP 404: `ERR_PARTY_NOT_FOUND`,
    `ERR_SENDING_AREA_NOT_FOUND`, `ERR_RECEIVING_AREA_NOT_FOUND`,
    `ERR_APPRAISAL_SCHEDULE_NOT_FOUND`, `ERR_SENDING_PARCEL_NOT_FOUND`,
    `ERR_SEVERANCE_APPLICATION_NOT_FOUND`, `ERR_CONSERVATION_EASEMENT_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CERTIFICATE_TRANSFER_NOT_FOUND`,
    `ERR_MARKET_TRANSACTION_NOT_FOUND`,
    `ERR_RECEIVING_SITE_APPLICATION_NOT_FOUND`,
    `ERR_CERTIFICATE_REDEMPTION_NOT_FOUND`, `ERR_MONITORING_INSPECTION_NOT_FOUND`,
    and `ERR_PROGRAM_EVALUATION_NOT_FOUND`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error." "The `message` provides a human-readable explanation of
    what went wrong."

    Design: Corner/entities/sending_parcel_unknown_id_returns_not_found
    """
    parcel_read = api_client.get_sending_parcel(NON_EXISTENT_UUID, ADMIN)
    validate_error(parcel_read, ApiErrorId.ERR_SENDING_PARCEL_NOT_FOUND.value)
    assert parcel_read.json()["response_type"] == "error", (
        "a rejection carries response_type error"
    )

    certificate_read = api_client.get_certificate(NON_EXISTENT_UUID, ADMIN)
    validate_error(certificate_read, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND.value)
    assert certificate_read.json()["response_type"] == "error", (
        "a rejection carries response_type error"
    )


def test_sending_area_listing_honours_filters_and_pagination():
    """The list envelope reports the filtered set and the default page size.

    PRD §2.3: "Every list endpoint accepts two optional query parameters. `limit`
    controls page size: it defaults to 10, may be no smaller than 1, and may be no
    larger than 100. `offset` controls the starting position in the result set: it
    defaults to 0 and may be no smaller than 0."

    PRD §2.3: "Unless a specific listing says otherwise, results are ordered by
    `created_at` ascending. Four pagination fields ride in the `meta` object of a
    list response alongside `api_request_id` and `api_request_timestamp`: `limit`
    and `offset` echo the values in force for the page, `total_count` reports how
    many rows matched the filters before the page window was applied, and
    `has_more` is true when rows remain beyond the current window."

    PRD §2.3: "Filters on a listing narrow the matched set before pagination and
    before `total_count` is computed."

    PRD §3.2: "Sending areas accept `status`, `neighborhood_code`, `equity_tier`,
    and `allocation_formula_version` filters; receiving areas accept `status`,
    `neighborhood_code`, and `design_review_required`."

    Design: Corner/entities/sending_area_listing_honors_pagination_and_filters
    """
    # Distinct creation instants so the created_at ascending order is a total one.
    set_clock("2026-08-01T00:00:00Z")
    east_active_one = create_active_sending_area(
        name="East One", neighborhood_code=EAST_NEIGHBORHOOD, equity_tier="UNDERSERVED",
        allocation_formula_version="V1_NET_ACRE",
    )
    set_clock("2026-08-02T00:00:00Z")
    east_active_two = create_active_sending_area(
        name="East Two", neighborhood_code=EAST_NEIGHBORHOOD, equity_tier="MODERATE",
        allocation_formula_version="V2_GROSS_DISCOUNTED",
    )
    set_clock("2026-08-03T00:00:00Z")
    east_draft = designate_sending_area(
        name="East Three", neighborhood_code=EAST_NEIGHBORHOOD, equity_tier="HIGH_VALUE",
        allocation_formula_version="V1_NET_ACRE",
    )
    set_clock("2026-08-04T00:00:00Z")
    west_active = create_active_sending_area(
        name="West One", neighborhood_code="NB-WEST", equity_tier="HIGH_VALUE",
        allocation_formula_version="V1_NET_ACRE",
    )

    unfiltered, meta = validate_paginated(api_client.list_sending_areas(ADMIN))
    assert meta["total_count"] == 4, f"four areas were designated, got {meta['total_count']}"
    assert meta["limit"] == 10, f"limit defaults to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"
    assert meta["has_more"] is False, "four rows fit inside a default page of ten"
    assert len(unfiltered) == 4, f"the default page carries all four rows, got {len(unfiltered)}"

    filtered, filtered_meta = validate_paginated(
        api_client.list_sending_areas(
            ADMIN, params={"neighborhood_code": EAST_NEIGHBORHOOD, "status": "ACTIVE"}
        )
    )
    assert filtered_meta["total_count"] == 2, (
        f"two ACTIVE NB-EAST areas exist, got {filtered_meta['total_count']}"
    )
    assert {row["id"] for row in filtered} == {east_active_one["id"], east_active_two["id"]}, (
        "the filtered page must hold exactly the two ACTIVE NB-EAST areas"
    )
    returned_ids = {row["id"] for row in filtered}
    assert east_draft["id"] not in returned_ids, "a DRAFT area fails the status filter"
    assert west_active["id"] not in returned_ids, "an NB-WEST area fails the neighborhood filter"

    first_page, first_meta = validate_paginated(
        api_client.list_sending_areas(
            ADMIN, params={"neighborhood_code": EAST_NEIGHBORHOOD, "limit": 1, "offset": 0}
        )
    )
    second_page, second_meta = validate_paginated(
        api_client.list_sending_areas(
            ADMIN, params={"neighborhood_code": EAST_NEIGHBORHOOD, "limit": 1, "offset": 1}
        )
    )
    assert second_meta["total_count"] == 3, (
        f"three NB-EAST areas match before the window applies, got {second_meta['total_count']}"
    )
    assert second_meta["limit"] == 1 and second_meta["offset"] == 1, (
        f"meta must echo the page in force, got {second_meta}"
    )
    assert len(second_page) == 1, f"a limit of 1 returns one row, got {len(second_page)}"
    assert second_meta["has_more"] is True, "two of the three NB-EAST rows remain beyond offset 1"
    assert first_page[0]["id"] == east_active_one["id"], (
        "created_at ascending puts the earliest NB-EAST area first"
    )
    assert second_page[0]["id"] == east_active_two["id"], (
        "offset 1 must walk to the second NB-EAST area in created_at order"
    )
    assert second_page[0]["id"] != first_page[0]["id"], (
        "offset must advance the window rather than repeat the first row"
    )


def test_certified_certificate_reads_back_its_whole_unit_ledger():
    """A freshly issued root certificate reads back with a consistent ledger.

    PRD §3.5: "Alongside the cascade, the same request mints exactly one root
    **Certificate**. Its `units_face` and `units_remaining` both equal
    `allocated_units`; `holder_party_id` is the application's
    `applicant_party_id`; `conservation_easement_id` is the easement from link one;
    `origin_sending_area_id` is the parcel's `sending_area_id`;
    `origin_neighborhood_code` is a copy of that area's `neighborhood_code`, taken
    at issuance so the certificate keeps pointing at the right appraisal schedule
    even if the area is later re-coded; `parent_certificate_id` is unset because
    this is a root; `generation` is 1; `split_count` is 0; `units_split_out`,
    `units_encumbered`, `units_redeemed`, and `units_retired` are all 0;
    `lifecycle_status` is `ISSUED`; `market_status` is `HELD`; and `issued_at` is
    the current logical clock. `serial_number` is minted deterministically as
    `TDR-`, the area's `code`, a hyphen, and the area's `issued_certificate_count`
    after its increment rendered as five digits with leading zeros — so the first
    certificate out of an area coded `SND-01` is `TDR-SND-01-00001`."

    Design: Corner/entities/certificate_read_returns_the_stored_unit_ledger
    """
    scenario = setup_certified_severance(
        units=CANONICAL_BASELINE_UNITS, clock=CLOCK, equity_tier="UNDERSERVED",
        neighborhood_code=EAST_NEIGHBORHOOD, area_overrides={"code": EAST_AREA_CODE},
    )
    landowner, area = scenario["landowner"], scenario["area"]
    certificate_id = scenario["certificate"]["id"]

    resp = api_client.get_certificate(certificate_id, make_landowner_headers(landowner["id"]))
    data = validate_success(resp)
    assert resp.json()["response_type"] == "object", "a detail read is response_type object"
    assert_certificate(data)

    assert data["units_face"] == CANONICAL_BASELINE_UNITS, (
        f"units_face equals the certified allocation, got {data['units_face']}"
    )
    assert data["units_remaining"] == CANONICAL_BASELINE_UNITS, (
        f"units_remaining opens equal to units_face, got {data['units_remaining']}"
    )
    for field in ("units_split_out", "units_encumbered", "units_redeemed", "units_retired"):
        assert data[field] == 0, f"{field} opens at 0 on a root certificate, got {data[field]}"
    assert data["split_count"] == 0, f"split_count opens at 0, got {data['split_count']}"
    assert data["generation"] == 1, f"a root certificate is generation 1, got {data['generation']}"
    assert data.get("parent_certificate_id") is None, (
        f"a root certificate has no parent, got {data.get('parent_certificate_id')!r}"
    )
    assert data["lifecycle_status"] == "ISSUED", (
        f"a new certificate is ISSUED, got {data['lifecycle_status']!r}"
    )
    assert data["market_status"] == "HELD", (
        f"a new certificate is HELD, got {data['market_status']!r}"
    )
    assert data["holder_party_id"] == landowner["id"], (
        "the holder is the severance applicant"
    )
    assert data["origin_sending_area_id"] == area["id"], (
        "origin_sending_area_id is the parcel's sending area"
    )
    assert data["origin_neighborhood_code"] == EAST_NEIGHBORHOOD, (
        f"origin_neighborhood_code copies the area's code, got {data['origin_neighborhood_code']!r}"
    )
    assert data["conservation_easement_id"] == scenario["easement"]["id"], (
        "conservation_easement_id names the easement recorded by the same certification"
    )
    assert data["serial_number"] == f"TDR-{EAST_AREA_CODE}-00001", (
        f"serial_number must be TDR-{EAST_AREA_CODE}-00001, got {data['serial_number']!r}"
    )
    assert_same_instant(data["issued_at"], CLOCK, "Certificate.issued_at")


def test_issuance_chain_of_title_row_is_append_only_and_versionless():
    """The issuance row carries only id and created_at beyond its own fields.

    PRD §3.5: "The registry's chain of title opens at the same moment: a
    **CertificateTransfer** row is appended for the new certificate with
    `transfer_type` of `ISSUANCE`, `seq_no` of 1, `from_party_id` unset,
    `to_party_id` set to the applicant, `units` equal to `allocated_units`,
    `price_cents` unset, `market_transaction_id` unset, and `recorded_at` at the
    current logical clock."

    PRD §2.4: "`CertificateTransfer` is the one deliberate exception. A chain-of-title
    row is append-only: once written it is never modified, so it carries only `id`
    and `created_at`. Both `updated_at` and `version` are absent from a
    `CertificateTransfer` altogether."

    Design: Corner/entities/certificate_transfer_log_is_append_only_and_versionless
    """
    scenario = setup_certified_severance(
        units=CANONICAL_BASELINE_UNITS, clock=CLOCK, equity_tier="UNDERSERVED",
        neighborhood_code=EAST_NEIGHBORHOOD, area_overrides={"code": EAST_AREA_CODE},
    )
    certificate_id = scenario["certificate"]["id"]

    rows, meta = validate_paginated(
        api_client.list_certificate_transfers(ADMIN, params={"certificate_id": certificate_id})
    )
    assert meta["total_count"] == 1, (
        f"certification appends exactly one chain-of-title row, got {meta['total_count']}"
    )
    row = rows[0]
    assert_certificate_transfer(row)
    assert row["transfer_type"] == "ISSUANCE", (
        f"the opening row is an ISSUANCE, got {row['transfer_type']!r}"
    )
    assert row["seq_no"] == 1, f"the opening row is seq_no 1, got {row['seq_no']}"
    assert row.get("from_party_id") is None, (
        f"an ISSUANCE row has no transferor, got {row.get('from_party_id')!r}"
    )
    assert row["to_party_id"] == scenario["landowner"]["id"], (
        "the transferee on an ISSUANCE row is the applicant"
    )
    assert row["units"] == CANONICAL_BASELINE_UNITS, (
        f"the issuance row carries the certified units, got {row['units']}"
    )
    assert row.get("price_cents") is None, (
        f"an ISSUANCE row carries no price, got {row.get('price_cents')!r}"
    )
    assert row.get("market_transaction_id") is None, (
        f"an ISSUANCE row names no market transaction, got {row.get('market_transaction_id')!r}"
    )
    assert_same_instant(row["recorded_at"], CLOCK, "CertificateTransfer.recorded_at")
    assert "updated_at" not in row, "a chain-of-title row carries no updated_at"
    assert "version" not in row, "a chain-of-title row carries no version"


def test_severance_filing_naming_an_unknown_parcel_is_a_not_found():
    """A body foreign key that does not resolve yields that entity's 404 code.

    PRD §2.9: "Path identifiers are resolved strictly left to right, and the
    leftmost identifier that fails to resolve decides the error. Each entity has
    its own not-found code, all at HTTP 404: `ERR_PARTY_NOT_FOUND`,
    `ERR_SENDING_AREA_NOT_FOUND`, `ERR_RECEIVING_AREA_NOT_FOUND`,
    `ERR_APPRAISAL_SCHEDULE_NOT_FOUND`, `ERR_SENDING_PARCEL_NOT_FOUND`,
    `ERR_SEVERANCE_APPLICATION_NOT_FOUND`, `ERR_CONSERVATION_EASEMENT_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CERTIFICATE_TRANSFER_NOT_FOUND`,
    `ERR_MARKET_TRANSACTION_NOT_FOUND`,
    `ERR_RECEIVING_SITE_APPLICATION_NOT_FOUND`,
    `ERR_CERTIFICATE_REDEMPTION_NOT_FOUND`, `ERR_MONITORING_INSPECTION_NOT_FOUND`,
    and `ERR_PROGRAM_EVALUATION_NOT_FOUND`."

    PRD §2.9: "Foreign keys supplied in a request body are resolved the same way
    and produce the same codes, but only after the request's shape has been
    validated. Body foreign keys are checked in the order the endpoint declares
    its input fields, and the first unresolved reference decides the error. This
    applies to parcel enrollment, severance application filing, market transaction
    proposal, receiving-site application filing, and redemption allocation."

    PRD §3.4: "Applications can be listed with `sending_parcel_id`,
    `applicant_party_id`, and `status` filters plus `limit` and `offset`."

    Design: Corner/entities/severance_application_naming_an_unknown_parcel_is_not_found
    """
    set_clock(CLOCK)
    landowner = register_landowner(legal_name="Unresolved Parcel Owner")
    owner_headers = make_landowner_headers(landowner["id"])

    resp = api_client.create_severance_application(
        create_severance_application_payload(NON_EXISTENT_UUID, landowner["id"], 5),
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SENDING_PARCEL_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error", "a rejection is response_type error"

    rows, meta = validate_paginated(
        api_client.list_severance_applications(
            ADMIN, params={"applicant_party_id": landowner["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a rejected filing persists nothing, got total_count {meta['total_count']}"
    )
    assert rows == [], f"a rejected filing persists nothing, got {len(rows)} rows"


def test_lineage_and_redemption_junctions_are_navigable_by_filter():
    """Splitting a root exposes the family through the registry's filters.

    PRD §3.6: "The child certificate is minted with `parent_certificate_id`
    pointing at the parent, with `conservation_easement_id`,
    `origin_sending_area_id` and `origin_neighborhood_code` copied down the lineage
    unchanged, with `holder_party_id` equal to the parent's holder, with
    `units_face` and `units_remaining` both equal to the requested `units`, with
    `generation` one higher than the parent's `generation`, with `split_count` at
    0, with `lifecycle_status` of `ISSUED` and `market_status` of `HELD`, and with
    `issued_at` at the current logical clock."

    PRD §3.6: "The registry can be listed with `holder_party_id`,
    `conservation_easement_id`, `parent_certificate_id`, `origin_sending_area_id`,
    `lifecycle_status`, and `market_status` filters plus `limit` and `offset`,
    which is how a lineage is walked: filtering on `parent_certificate_id` yields
    one generation of children, and filtering on `conservation_easement_id` yields
    the whole family descended from one severance."

    PRD §3.6: "The source easement's `units_issued_total` and `units_outstanding`
    are completely unchanged by a split — the rights have moved, not multiplied."

    PRD §3.8: "redemptions can be listed with `receiving_site_application_id`,
    `certificate_id`, `source_easement_id`, and `status` filters plus `limit` and
    `offset`."

    Design: Corner/entities/certificate_graph_is_reachable_through_lineage_and_redemption_junction
    """
    scenario = setup_certified_severance(
        units=CANONICAL_BASELINE_UNITS, clock=CLOCK, equity_tier="UNDERSERVED",
        neighborhood_code=EAST_NEIGHBORHOOD, area_overrides={"code": EAST_AREA_CODE},
    )
    landowner = scenario["landowner"]
    owner_headers = make_landowner_headers(landowner["id"])
    root_id = scenario["certificate"]["id"]
    easement_id = scenario["easement"]["id"]

    child = split_certificate(root_id, 8, owner_headers, expected_certificate_version=1)
    assert child["parent_certificate_id"] == root_id, "the child points back at its parent"
    assert child["generation"] == 2, f"the child is generation 2, got {child['generation']}"
    assert child["units_face"] == 8, f"the child's face value is the split units, got {child['units_face']}"
    assert child["units_remaining"] == 8, (
        f"the child opens with all units remaining, got {child['units_remaining']}"
    )
    assert child["conservation_easement_id"] == easement_id, (
        "the easement is copied down the lineage unchanged"
    )

    children, child_meta = validate_paginated(
        api_client.list_certificates(owner_headers, params={"parent_certificate_id": root_id})
    )
    assert child_meta["total_count"] == 1, (
        f"one generation of children means exactly one row, got {child_meta['total_count']}"
    )
    assert children[0]["id"] == child["id"], "the child generation lists the split child"

    family, family_meta = validate_paginated(
        api_client.list_certificates(owner_headers, params={"conservation_easement_id": easement_id})
    )
    assert family_meta["total_count"] == 2, (
        f"the whole family is the root plus its child, got {family_meta['total_count']}"
    )
    assert {row["id"] for row in family} == {root_id, child["id"]}, (
        "the easement filter yields the whole family descended from one severance"
    )

    redemptions_resp = api_client.list_certificate_redemptions(
        ADMIN, params={"certificate_id": root_id}
    )
    redemptions, redemption_meta = validate_paginated(redemptions_resp)
    assert redemptions_resp.json()["response_type"] == "array", (
        "a listing is response_type array even when empty"
    )
    assert redemption_meta["total_count"] == 0, (
        f"no permit has drawn on this certificate yet, got {redemption_meta['total_count']}"
    )
    assert redemptions == [], "no permit has drawn on this certificate yet"

    parent = fetch_certificate(root_id, owner_headers)
    assert parent["split_count"] == 1, f"the parent has split once, got {parent['split_count']}"
    assert parent["units_split_out"] == 8, (
        f"the parent has 8 units split out, got {parent['units_split_out']}"
    )
    assert parent["units_remaining"] == CANONICAL_BASELINE_UNITS - 8, (
        f"the parent keeps the balance, got {parent['units_remaining']}"
    )

    easement = fetch_easement(easement_id, ADMIN)
    assert_conservation_easement(easement)
    assert easement["units_issued_total"] == CANONICAL_BASELINE_UNITS, (
        f"a split does not multiply issued rights, got {easement['units_issued_total']}"
    )
    assert easement["units_outstanding"] == CANONICAL_BASELINE_UNITS, (
        f"a split leaves outstanding rights untouched, got {easement['units_outstanding']}"
    )
