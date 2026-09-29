"""The operational registry: payers, patients, providers, contracts — plus the
response envelope and the resource-specific not-found codes."""
from test_helpers import (
    CASE_MANAGER,
    PLATFORM_ADMIN,
    ApiErrorId,
    assert_error_envelope,
    assert_network_contract,
    assert_no_type_prefix,
    assert_patient,
    assert_payer,
    assert_success_envelope,
    is_iso8601_timestamp,
    seed_network_contract,
    seed_patient,
    seed_payer,
    seed_provider,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNUSED_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_payer_registration_applies_declared_defaults(api):
    """PRD §3.1: "`snf_auth_required` states whether a placement at a skilled-nursing,
    inpatient-rehab or long-term-acute-care facility may only be chosen once coverage
    has been granted; `hh_auth_required` states the same for home health. Both default
    to `true` when omitted from the request. `auth_expiry_days` is the number of days
    added to a decision instant to produce the moment coverage lapses, and it defaults
    to 30 when omitted."
    PRD §2.4: "Every resource in this system is identified by a server-minted UUID
    exposed as `id`, with no type prefix of any kind."
    PRD §2.4: "and `version`, an integer that starts at 1 when the row is created and
    increments by exactly 1 on each mutation of that row."

    Design: Corner/entities/payer_creation_applies_declared_defaults_and_system_fields
    """
    set_logical_clock("2026-08-01T00:00:00Z")

    data = validate_success(
        api.create_payer({"name": "Bare Minimum Plan", "coinsurance_pct": 0.100}, PLATFORM_ADMIN),
        201,
    )

    assert_payer(data)
    assert data["snf_auth_required"] is True, "snf_auth_required defaults to true"
    assert data["hh_auth_required"] is True, "hh_auth_required defaults to true"
    assert data["auth_expiry_days"] == 30, "auth_expiry_days defaults to 30"
    assert float(data["coinsurance_pct"]) == 0.100
    assert data["version"] == 1
    assert_no_type_prefix(data["id"])


def test_patient_registration_round_trips_through_single_read(api):
    """PRD §3.1: "Each patient carries an `mrn` — the medical record number, which must
    be unique across every patient row, on pain of `ERR_DUPLICATE_MRN` — plus
    `full_name` and `date_of_birth` as an ISO 8601 calendar date in year-month-day form."
    PRD §3.1: "Three further attributes feed the readmission-risk model directly rather
    than being administrative colour: `prior_admissions_180d`, a non-negative count of
    the patient's inpatient admissions over the trailing half-year; `lives_alone`, the
    social-support flag; and `has_pcp`, whether the patient has an established primary
    care provider."
    PRD §2.4: "additionally carry `updated_at`, an ISO 8601 UTC timestamp with three
    fractional digits refreshed on every mutation, and `version`, an integer that starts
    at 1 when the row is created and increments by exactly 1 on each mutation of that row."

    Design: Corner/entities/patient_creation_and_single_read_roundtrip
    """
    payer = seed_payer(name="Lakeside Choice", coinsurance_pct=0.200)
    created = validate_success(
        api.create_patient(
            {
                "mrn": "MRN-C001", "full_name": "Ana Bello", "date_of_birth": "1952-02-02",
                "primary_payer_id": payer["id"], "prior_admissions_180d": 1,
                "lives_alone": True, "has_pcp": False,
            },
            PLATFORM_ADMIN,
        ),
        201,
    )

    data = validate_success(api.get_patient(created["id"], CASE_MANAGER))

    assert_patient(data)
    assert data["mrn"] == "MRN-C001"
    assert data["full_name"] == "Ana Bello"
    assert data["date_of_birth"] == "1952-02-02"
    assert data["primary_payer_id"] == payer["id"]
    assert data["prior_admissions_180d"] == 1
    assert data["lives_alone"] is True
    assert data["has_pcp"] is False
    assert data["version"] == 1, "a never-mutated row is still at version 1"
    assert data["created_at"] == data["updated_at"], (
        "updated_at is refreshed on every mutation, so a never-mutated row still "
        f"reads its creation instant: {data['created_at']} vs {data['updated_at']}"
    )


def test_episode_read_with_unused_identifier_returns_episode_not_found(api):
    """PRD §2.8: "Each resource type has its own 404 code: `ERR_EPISODE_NOT_FOUND`,
    `ERR_SCREENING_NOT_FOUND`, `ERR_BARRIER_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_BED_OFFER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`,
    `ERR_LOGISTICS_ORDER_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, and
    `ERR_NETWORK_CONTRACT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/episode_get_with_unknown_id_returns_not_found
    """
    set_logical_clock("2026-08-01T00:00:00Z")

    response = api.get_episode(UNUSED_UUID, CASE_MANAGER)

    validate_error(response, ApiErrorId.ERR_EPISODE_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"


def test_patient_create_without_mrn_is_rejected_as_validation(api):
    """PRD §2.8: "then request-body well-formedness, meaning required fields present,
    enum values that are declared members, integers inside their declared ranges — the
    three screening scores between 0 and 10 inclusive, `quality_star_rating` between 1
    and 5 inclusive, `coinsurance_pct` between 0.000 and 0.500 inclusive, rates and day
    counts strictly positive — and `limit` inside 1 through 100, all failing as
    `ERR_VALIDATION`"

    Design: Corner/entities/patient_create_missing_required_mrn_returns_validation
    """
    payer = seed_payer(name="Lakeside Choice", coinsurance_pct=0.200)

    response = api.create_patient(
        {
            "full_name": "No Mrn", "date_of_birth": "1952-02-02",
            "primary_payer_id": payer["id"], "prior_admissions_180d": 1,
            "lives_alone": True, "has_pcp": False,
        },
        PLATFORM_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
    _, meta = validate_paginated(api.list_patients(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, "the refused create must leave no Patient row behind"


def test_provider_create_above_star_rating_range_is_rejected_as_validation(api):
    """PRD §2.8: "then request-body well-formedness, meaning required fields present,
    enum values that are declared members, integers inside their declared ranges — the
    three screening scores between 0 and 10 inclusive, `quality_star_rating` between 1
    and 5 inclusive, `coinsurance_pct` between 0.000 and 0.500 inclusive, rates and day
    counts strictly positive — and `limit` inside 1 through 100, all failing as
    `ERR_VALIDATION`"
    PRD §3.1: "Post-acute providers are registered with a `name`, a `provider_type` of
    `SNF`, `HOME_HEALTH`, `IRF`, `LTACH`, or `DME_SUPPLIER`, a `quality_star_rating`
    between 1 and 5 inclusive, a whole-mile `distance_miles_from_hospital` of zero or
    more, and `bed_unit_codes`, the list of bed-unit code strings the facility can hold
    beds under."

    Design: Corner/entities/provider_create_with_out_of_range_star_rating_returns_validation
    """
    set_logical_clock("2026-08-01T00:00:00Z")

    response = api.create_provider(
        {
            "name": "Over Rated SNF", "provider_type": "SNF", "quality_star_rating": 6,
            "distance_miles_from_hospital": 4, "bed_unit_codes": ["UNIT-A"],
        },
        PLATFORM_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
    _, meta = validate_paginated(api.list_providers(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, "the refused create must leave no provider row behind"


def test_episode_create_ignores_client_supplied_system_fields(api):
    """PRD §3.2: "A new episode starts with `case_status` of `ADMITTED`,
    `barrier_posture` of `CLEAR`, `assigned_case_manager_id` set to the creating
    operator's `X-User-ID`, `current_risk_score` of 0, `current_risk_band` of `LOW`,
    `risk_variant_applied` of `ADMISSION_VARIANT`, `logistics_committed_cents` and
    `authorized_days_total` both at zero, `discharge_disposition` null, and all four
    intervention flags false."

    Design: Corner/entities/episode_create_system_fields_input_ignored
    """
    payer = seed_payer(name="Lakeside Choice", coinsurance_pct=0.200)
    patient = seed_patient(
        payer["id"], mrn="MRN-C002", full_name="Bea Cruz", date_of_birth="1950-05-05",
        prior_admissions_180d=0, lives_alone=False, has_pcp=True,
    )

    data = validate_success(
        api.create_episode(
            {
                "patient_id": patient["id"], "admission_type": "ELECTIVE",
                "drg_code": "DRG-470", "drg_gmlos_days": 3.5, "attending_unit": "7E",
                "admitted_at": "2026-08-01T00:00:00Z",
                "case_status": "DISCHARGED", "barrier_posture": "ESCALATED",
                "logistics_committed_cents": 999999,
            },
            CASE_MANAGER,
        ),
        201,
    )

    assert data["case_status"] == "ADMITTED"
    assert data["barrier_posture"] == "CLEAR"
    assert data["logistics_committed_cents"] == 0
    assert data["assigned_case_manager_id"] == "cm-alpha"
    assert data["current_risk_score"] == 0
    assert data["current_risk_band"] == "LOW"
    assert data["version"] == 1


def test_patient_listing_filters_by_payer_and_paginates_in_creation_order(api):
    """PRD §2.3: "List results are always ordered by `created_at` ascending. Each list
    response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta`
    object, where `total_count` is the number of records matching the filters before
    pagination is applied and `has_more` indicates whether records remain beyond the
    current page."
    PRD §3.1: "The patient list is filterable by `primary_payer_id` or by `mrn`."

    Design: Corner/entities/patients_listing_paginates_and_filters_by_payer
    """
    payer_a = seed_payer(name="Payer A", coinsurance_pct=0.200)
    payer_b = seed_payer(name="Payer B", coinsurance_pct=0.150)
    p1 = seed_patient(payer_a["id"], mrn="MRN-C101", full_name="P One")
    seed_patient(payer_a["id"], mrn="MRN-C102", full_name="P Two")
    seed_patient(payer_a["id"], mrn="MRN-C103", full_name="P Three")
    p4 = seed_patient(payer_b["id"], mrn="MRN-C104", full_name="P Four")

    rows, meta = validate_paginated(
        api.list_patients(
            PLATFORM_ADMIN,
            params={"primary_payer_id": payer_a["id"], "limit": 2, "offset": 0},
        )
    )

    assert meta["total_count"] == 3, "total_count counts matches before pagination"
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(rows) == 2
    assert rows[0]["id"] == p1["id"], "rows come back in created_at ascending order"
    assert p4["id"] not in [row["id"] for row in rows], "payer B's patient is filtered out"


def test_network_contracts_are_discoverable_from_payer_and_provider_sides(api):
    """PRD §3.1: "The bridge between the payer world and the provider world is the
    network contract, which links one `payer_id` to one `provider_id` and records
    whether the relationship is `in_network` along with the contracted per-diem in
    `negotiated_daily_rate_cents`, which must be strictly positive."
    PRD §3.1: "Contracts can be listed and filtered by `payer_id` or `provider_id`."

    Design: Corner/entities/network_contract_many_to_many_reverse_lookup_from_both_sides
    """
    payer = seed_payer(name="Lakeside Choice", coinsurance_pct=0.200)
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    birch = seed_provider(
        name="Birch SNF", quality_star_rating=5, distance_miles_from_hospital=22,
        bed_unit_codes=["UNIT-A"],
    )
    nc_a = seed_network_contract(payer["id"], cedar["id"], in_network=True,
                                 negotiated_daily_rate_cents=30000)
    nc_b = seed_network_contract(payer["id"], birch["id"], in_network=False,
                                 negotiated_daily_rate_cents=41000)

    by_payer, payer_meta = validate_paginated(
        api.list_network_contracts(PLATFORM_ADMIN, params={"payer_id": payer["id"]})
    )
    by_provider, provider_meta = validate_paginated(
        api.list_network_contracts(PLATFORM_ADMIN, params={"provider_id": birch["id"]})
    )

    assert payer_meta["total_count"] == 2
    assert {row["id"] for row in by_payer} == {nc_a["id"], nc_b["id"]}
    assert provider_meta["total_count"] == 1
    assert by_provider[0]["id"] == nc_b["id"]
    assert by_provider[0]["in_network"] is False
    assert by_provider[0]["negotiated_daily_rate_cents"] == 41000

    single = validate_success(api.get_network_contract(nc_a["id"], PLATFORM_ADMIN))
    assert_network_contract(single)
    assert single["in_network"] is True


def test_second_patient_with_an_existing_mrn_is_rejected(api):
    """PRD §2.8: "A `Patient`'s `mrn` must be unique across all patient rows; a
    duplicate is rejected with `ERR_DUPLICATE_MRN` (HTTP 409)."

    Design: Corner/validations/duplicate_mrn_returns_duplicate_mrn
    """
    payer = seed_payer(name="Lakeside Choice", coinsurance_pct=0.200)
    first = seed_patient(payer["id"], mrn="MRN-D001", full_name="First Owner",
                         date_of_birth="1950-01-01", prior_admissions_180d=0)

    response = api.create_patient(
        {
            "mrn": "MRN-D001", "full_name": "Second Claimant",
            "date_of_birth": "1970-12-31", "primary_payer_id": payer["id"],
            "prior_admissions_180d": 3, "lives_alone": True, "has_pcp": False,
        },
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_MRN, 409)
    _, meta = validate_paginated(api.list_patients(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, "the duplicate must not create a second row"
    kept = validate_success(api.get_patient(first["id"], PLATFORM_ADMIN))
    assert kept["full_name"] == "First Owner"


def test_second_network_contract_for_the_same_pair_is_rejected(api):
    """PRD §2.8: "At most one `NetworkContract` row may exist for a given combination of
    `payer_id` and `provider_id`; a second one is rejected with
    `ERR_DUPLICATE_NETWORK_CONTRACT` (HTTP 409)."

    Design: Corner/validations/duplicate_network_contract_pair_returns_duplicate_network_contract
    """
    payer = seed_payer(name="Lakeside Choice", coinsurance_pct=0.200)
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    original = seed_network_contract(payer["id"], cedar["id"], in_network=True,
                                     negotiated_daily_rate_cents=30000)

    response = api.create_network_contract(
        {
            "payer_id": payer["id"], "provider_id": cedar["id"],
            "in_network": False, "negotiated_daily_rate_cents": 41000,
        },
        PLATFORM_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_NETWORK_CONTRACT, 409)
    _, meta = validate_paginated(
        api.list_network_contracts(PLATFORM_ADMIN, params={"provider_id": cedar["id"]})
    )
    assert meta["total_count"] == 1
    kept = validate_success(api.get_network_contract(original["id"], PLATFORM_ADMIN))
    assert kept["in_network"] is True
    assert kept["negotiated_daily_rate_cents"] == 30000


def test_success_and_error_envelopes_carry_the_declared_meta_and_data_shapes(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_on_error
    """
    set_logical_clock("2026-08-01T00:00:00Z")

    create_response = api.create_payer(
        {"name": "Envelope Plan", "coinsurance_pct": 0.200}, PLATFORM_ADMIN
    )
    created = validate_success(create_response, 201)
    body = create_response.json()
    assert_success_envelope(body, "object")
    assert body["data"]["id"] == created["id"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    error_response = api.get_payer(UNUSED_UUID, PLATFORM_ADMIN)
    validate_error(error_response, ApiErrorId.ERR_PAYER_NOT_FOUND, 404)
    assert_error_envelope(error_response.json(), "ERR_PAYER_NOT_FOUND")

    reread = validate_success(api.get_payer(created["id"], PLATFORM_ADMIN))
    assert reread["id"] == created["id"]


def test_every_collection_reports_its_own_not_found_code(api):
    """PRD §2.8: "Each resource type has its own 404 code: `ERR_EPISODE_NOT_FOUND`,
    `ERR_SCREENING_NOT_FOUND`, `ERR_BARRIER_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_BED_OFFER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`,
    `ERR_LOGISTICS_ORDER_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, and
    `ERR_NETWORK_CONTRACT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/not_found_errors_are_resource_specific_per_path_segment
    """
    set_logical_clock("2026-08-01T00:00:00Z")

    probes = [
        (api.get_payer(UNUSED_UUID, PLATFORM_ADMIN), ApiErrorId.ERR_PAYER_NOT_FOUND),
        (api.get_patient(UNUSED_UUID, PLATFORM_ADMIN), ApiErrorId.ERR_PATIENT_NOT_FOUND),
        (api.get_provider(UNUSED_UUID, PLATFORM_ADMIN), ApiErrorId.ERR_PROVIDER_NOT_FOUND),
        (api.get_vehicle(UNUSED_UUID, PLATFORM_ADMIN), ApiErrorId.ERR_VEHICLE_NOT_FOUND),
        (api.get_network_contract(UNUSED_UUID, PLATFORM_ADMIN),
         ApiErrorId.ERR_NETWORK_CONTRACT_NOT_FOUND),
        (api.get_referral(UNUSED_UUID, CASE_MANAGER), ApiErrorId.ERR_REFERRAL_NOT_FOUND),
        (api.get_offer(UNUSED_UUID, CASE_MANAGER), ApiErrorId.ERR_BED_OFFER_NOT_FOUND),
        (api.get_authorization(UNUSED_UUID, CASE_MANAGER),
         ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND),
        (api.get_logistics_order(UNUSED_UUID, CASE_MANAGER),
         ApiErrorId.ERR_LOGISTICS_ORDER_NOT_FOUND),
        (api.submit_screening(UNUSED_UUID, CASE_MANAGER), ApiErrorId.ERR_SCREENING_NOT_FOUND),
        (api.change_barrier_status(UNUSED_UUID, {"to_status": "RESOLVED"}, CASE_MANAGER),
         ApiErrorId.ERR_BARRIER_NOT_FOUND),
    ]

    seen = []
    for response, expected in probes:
        assert response.status_code == 404, (
            f"expected HTTP 404 for {expected}, got {response.status_code}: {response.text}"
        )
        validate_error(response, expected, 404)
        seen.append(response.json()["data"]["error_id"])

    assert len(set(seen)) == len(seen), (
        f"each collection must report its own distinct 404 code, got {seen}"
    )
