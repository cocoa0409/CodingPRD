"""Entity surface: creation echoes, derived fields, system fields and the graph.

These exercise the declared shape of each resource — which fields the server
generates, which it derives, which it refuses to accept from a client — plus the
listing envelope and the parent links that close the preservation graph.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ABSENT_UUID,
    OFFICER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_append_only_fields,
    assert_funding_commitment,
    assert_parcel,
    assert_program,
    create_application_payload,
    create_landowner,
    create_parcel,
    create_parcel_payload,
    create_program,
    create_program_payload,
    create_program_required_only_payload,
    engage_appraisal_payload,
    file_application,
    file_counter,
    list_negotiation_log,
    make_landowner_headers,
    patch_parcel_payload,
    read_application,
    read_parcel,
    set_clock,
    setup_filed_application,
    setup_funded_application,
    setup_offered_application,
    setup_program_with_round,
    setup_recorded_easement,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]


class TestProgramCreation:
    """The configuration root and its two optional-field behaviours."""

    def test_program_creation_echoes_every_declared_field(self):
        """All fourteen inputs come back, with the three server-set fields.

        PRD §3.1: "A new program opens with `status` set to `ACTIVE` — the
        enumeration is `ACTIVE` and `CLOSED` — and with `total_preserved_acres`
        at 0."

        Design: Corner/entities/program_creation_returns_every_declared_field
        """
        payload = create_program_payload()
        program = validate_success(api_client.create_program(payload, ADMIN), 201)
        assert_program(program)

        for field, expected in payload.items():
            if isinstance(expected, float):
                assert program[field] == pytest.approx(expected, abs=0.01), field
            else:
                assert program[field] == expected, field

        assert program["status"] == "ACTIVE"
        assert program["total_preserved_acres"] == pytest.approx(0.00, abs=0.01)
        # Version starts at 1 on creation.
        assert program["version"] == 1

    def test_omitting_the_three_optional_fields_applies_the_declared_defaults(self):
        """The optional trio falls back rather than landing as null.

        PRD §3.1: "`monitoring_interval_days` is the gap from one monitoring
        anchor to the next due date; it lies between 30 and 1095 days and
        defaults to a full year of 365 days. `monitoring_grace_days` is the
        forgiveness period after a due date before an easement is treated as
        delinquent; it lies between 0 and 365 days and defaults to 30.
        `appraisal_engagement_buffer_days` is the buffer padded symmetrically
        onto both ends of an appraisal engagement for conflict detection; it lies
        between 0 and 30 days and defaults to 3."

        Design: Corner/entities/program_create_omitting_monitoring_fields_applies_declared_defaults
        """
        payload = create_program_required_only_payload(
            name="Default Configuration Program", amendment_policy="CONDITIONAL"
        )
        assert "monitoring_interval_days" not in payload
        assert "monitoring_grace_days" not in payload
        assert "appraisal_engagement_buffer_days" not in payload

        program = validate_success(api_client.create_program(payload, ADMIN), 201)
        assert program["monitoring_interval_days"] == 365
        assert program["monitoring_grace_days"] == 30
        assert program["appraisal_engagement_buffer_days"] == 3
        # The eleven required inputs are still honoured verbatim.
        assert program["amendment_policy"] == "CONDITIONAL"
        assert program["status"] == "ACTIVE"


class TestParcelSurface:
    """Registration derives two scores and refuses to be told either of them."""

    def test_parcel_retrieval_returns_the_stored_inputs_and_both_scores(self):
        """The read echoes what was stored plus what registration computed.

        PRD §3.2: "Registration immediately computes two scores.
        `soil_quality_score` credits prime farmland soil at full weight and soil
        of statewide importance at 60 percent of that weight."

        Design: Corner/entities/parcel_retrieval_returns_stored_and_derived_values
        """
        program = create_program()
        assert program["status"] == "ACTIVE"
        landowner = create_landowner()
        set_clock("2026-08-10T00:00:00Z")
        created = create_parcel(landowner["id"])

        parcel = validate_success(
            api_client.get_parcel(created["id"], make_landowner_headers(landowner["id"]))
        )
        assert_parcel(parcel)
        assert parcel["acres"] == pytest.approx(160.00, abs=0.01)
        assert parcel["prime_soil_acres"] == pytest.approx(120.00, abs=0.01)
        assert parcel["statewide_important_soil_acres"] == pytest.approx(24.00, abs=0.01)
        assert parcel["contiguous_preserved_acres"] == pytest.approx(80.00, abs=0.01)
        assert parcel["road_frontage_feet"] == 640
        assert parcel["sewer_available"] is True
        assert parcel["zoning_min_lot_acres"] == pytest.approx(2.0, abs=0.01)
        # (120/160 + 24/160 x 0.60) x 100
        assert parcel["soil_quality_score"] == pytest.approx(84.00, abs=0.01)
        # 18 frontage points + 25 sewer points + 35 zoning points
        assert parcel["development_pressure_score"] == pytest.approx(78.00, abs=0.01)
        assert parcel["mortgage_lienholder_name"] == "Midstate Farm Credit"
        assert parcel["status"] == "ELIGIBLE"
        assert parcel["version"] == 1

    def test_a_client_supplied_score_is_rejected_rather_than_honoured(self):
        """Neither score is an input, so supplying one is an unknown field.

        PRD §2.6: "A body that is not a JSON object, omits a required field,
        carries an unknown field, uses the wrong type for a field, or names an
        enum member that does not exist is likewise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/parcel_computed_scores_are_derived_and_client_supplied_values_rejected
        """
        create_program()
        landowner = create_landowner()
        landowner_headers = make_landowner_headers(landowner["id"])
        set_clock("2026-08-10T00:00:00Z")

        derived = create_parcel(landowner["id"])
        assert derived["soil_quality_score"] == pytest.approx(84.00, abs=0.01)
        assert derived["development_pressure_score"] == pytest.approx(78.00, abs=0.01)

        dictated = create_parcel_payload(landowner["id"], soil_quality_score=100.00)
        response = api_client.create_parcel(dictated, landowner_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        rows, meta = validate_paginated(
            api_client.list_parcels(
                landowner_headers, {"landowner_id": landowner["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["soil_quality_score"] != pytest.approx(100.00, abs=0.01)

    def test_domain_and_enum_violations_all_land_on_invalid_request(self):
        """Three unrelated domain breaches share one code.

        PRD §2.6: "The domains are: `acres` strictly positive;
        `prime_soil_acres` and `statewide_important_soil_acres` non-negative with
        their sum no greater than `acres`; every field whose name ends in
        `_cents` non-negative; `donation_pct` at least 0 and strictly less than
        1; `installment_years` between 2 and 10 inclusive; every fractional share
        field strictly above 0 and no greater than 1; `limit` between 1 and 100;
        `offset` non-negative; and every timestamp a valid ISO 8601 UTC instant."

        Design: Corner/entities/parcel_enum_and_numeric_type_constraints_are_rejected
        """
        scenario = setup_filed_application()
        landowner_headers = scenario["landowner_headers"]
        landowner_id = scenario["landowner"]["id"]

        # `acres` must be strictly positive.
        zero_acres = create_parcel_payload(
            landowner_id,
            acres=0.00,
            prime_soil_acres=0.00,
            statewide_important_soil_acres=0.00,
            contiguous_preserved_acres=0.00,
            baseline_dwelling_rights=1,
            unrestricted_value_cents=1_000_000,
            restricted_value_cents=500_000,
        )
        validate_error(
            api_client.create_parcel(zero_acres, landowner_headers),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        # 120.00 prime plus 50.00 statewide-important exceeds 160.00 acres.
        oversubscribed_soils = create_parcel_payload(
            landowner_id, statewide_important_soil_acres=50.00
        )
        validate_error(
            api_client.create_parcel(oversubscribed_soils, landowner_headers),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        # NARRATIVE is not a member of the appraisal method enumeration.
        validate_error(
            api_client.engage_appraisal(
                scenario["application"]["id"],
                engage_appraisal_payload(method="NARRATIVE"),
                OFFICER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        _, parcel_meta = validate_paginated(
            api_client.list_parcels(ADMIN, {"landowner_id": landowner_id})
        )
        assert parcel_meta["total_count"] == 1
        _, appraisal_meta = validate_paginated(
            api_client.list_appraisals(scenario["application"]["id"], ADMIN)
        )
        assert appraisal_meta["total_count"] == 0
        assert read_application(scenario["application"]["id"])["status"] == "RECEIVED"


class TestListingAndSystemFields:
    """The pagination envelope and the four server-generated fields."""

    def test_parcel_listing_paginates_and_filters_on_landowner_and_status(self):
        """Two pages, disjoint rows, and a status filter that drops one row.

        PRD §2.3: "Every list endpoint accepts two query parameters. `limit` caps
        the number of records returned; it defaults to 10, may be no smaller than
        1 and no larger than 100. `offset` is the number of records to skip; it
        defaults to 0 and may not be negative."

        Design: Corner/entities/parcel_listing_paginates_with_landowner_and_status_filters
        """
        scenario = setup_program_with_round()
        landowner_id = scenario["landowner"]["id"]
        landowner_headers = scenario["landowner_headers"]

        first = create_parcel(landowner_id)
        second = create_parcel(
            landowner_id,
            acres=200.00,
            prime_soil_acres=160.00,
            statewide_important_soil_acres=0.00,
            contiguous_preserved_acres=90.00,
            road_frontage_feet=150,
            sewer_available=False,
            zoning_min_lot_acres=5.0,
            baseline_dwelling_rights=5,
            unrestricted_value_cents=300_000_000,
            restricted_value_cents=150_000_000,
        )
        third = create_parcel(
            landowner_id,
            county="Berks",
            acres=80.00,
            prime_soil_acres=72.00,
            statewide_important_soil_acres=8.00,
            contiguous_preserved_acres=60.00,
            road_frontage_feet=400,
            sewer_available=True,
            zoning_min_lot_acres=1.5,
            baseline_dwelling_rights=3,
            unrestricted_value_cents=120_000_000,
            restricted_value_cents=45_500_000,
        )

        page_one, meta_one = validate_paginated(
            api_client.list_parcels(
                landowner_headers,
                {
                    "landowner_id": landowner_id,
                    "status": "ELIGIBLE",
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0

        page_two, meta_two = validate_paginated(
            api_client.list_parcels(
                landowner_headers,
                {
                    "landowner_id": landowner_id,
                    "status": "ELIGIBLE",
                    "limit": 2,
                    "offset": 2,
                },
            )
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2

        first_ids = {row["id"] for row in page_one}
        second_ids = {row["id"] for row in page_two}
        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == {first["id"], second["id"], third["id"]}

        file_application(scenario["round"]["id"], first["id"], landowner_id)

        eligible, eligible_meta = validate_paginated(
            api_client.list_parcels(
                landowner_headers, {"landowner_id": landowner_id, "status": "ELIGIBLE"}
            )
        )
        assert eligible_meta["total_count"] == 2
        assert first["id"] not in {row["id"] for row in eligible}

        _, unfiltered_meta = validate_paginated(
            api_client.list_parcels(landowner_headers, {"landowner_id": landowner_id})
        )
        assert unfiltered_meta["total_count"] == 3
        assert unfiltered_meta["has_more"] is False
        # The declared defaults apply when neither parameter is supplied.
        assert unfiltered_meta["limit"] == 10
        assert unfiltered_meta["offset"] == 0
        assert read_parcel(first["id"])["status"] == "UNDER_APPLICATION"

    def test_system_fields_are_server_generated_and_updated_at_advances(self):
        """`created_at` freezes, `updated_at` moves and `version` counts writes.

        PRD §2.4: "Thirteen of the fourteen resource types additionally carry
        `updated_at` — an ISO 8601 UTC instant refreshed on every mutation — and
        `version`, an integer that starts at 1 on creation and increments by
        exactly one on every mutation of that row, including mutations caused by
        a cascade the client did not request directly."

        Design: Corner/entities/system_fields_are_server_generated_and_updated_at_advances_on_write
        """
        create_program()
        landowner = create_landowner()
        set_clock("2026-08-10T00:00:00Z")
        parcel = create_parcel(landowner["id"])
        assert parcel["version"] == 1
        assert parcel["updated_at"] == parcel["created_at"]

        set_clock("2026-08-20T00:00:00Z")
        patched = validate_success(
            api_client.patch_parcel(
                parcel["id"],
                patch_parcel_payload(1, contiguous_preserved_acres=160.00),
                ADMIN,
            )
        )
        assert patched["version"] == 2
        # `created_at` freezes on creation; `updated_at` is re-stamped by the write.
        assert patched["created_at"] == parcel["created_at"]
        assert patched["updated_at"] >= parcel["updated_at"]
        assert patched["contiguous_preserved_acres"] == pytest.approx(160.00, abs=0.01)
        # The identifier is minted once and never rewritten.
        assert patched["id"] == parcel["id"]

    def test_the_negotiation_log_is_append_only_and_carries_no_version(self):
        """Only the log lacks `updated_at` and `version`, and it only grows.

        PRD §2.4: "The single exception is the negotiation log. A
        `NegotiationRound` is append-only and immutable once written; it carries
        `id` and `created_at` only, and both `updated_at` and `version` are
        absent from it entirely."

        Design: Corner/entities/negotiation_round_is_immutable_and_exposes_no_version_field
        """
        scenario = setup_offered_application(
            offer_cents=170_000_000, structure="BARGAIN_SALE"
        )
        application_id = scenario["application"]["id"]
        assert scenario["application"]["certified_easement_value_cents"] == 175_550_000

        before = list_negotiation_log(application_id, {"limit": 100})
        assert len(before) == 1
        offer_before = before[0]

        file_counter(
            application_id,
            scenario["landowner"]["id"],
            175_000_000,
            rationale="matching the certified value",
        )

        rows, meta = validate_paginated(
            api_client.list_negotiation_rounds(application_id, ADMIN, {"limit": 100})
        )
        assert meta["total_count"] == 2
        by_kind = {row["kind"]: row for row in rows}

        offer = by_kind["OFFER"]
        assert offer["amount_cents"] == 170_000_000
        assert offer["round_index"] == 1
        assert offer["actor_role"] == "AcquisitionOfficer"
        assert offer["actor_user_id"] == OFFICER_USER_ID

        counter = by_kind["COUNTER"]
        assert counter["amount_cents"] == 175_000_000
        # A counter answers the offer it replies to, so it reuses its round index.
        assert counter["round_index"] == 1
        assert counter["actor_role"] == "Landowner"
        assert counter["actor_user_id"] == scenario["landowner"]["id"]

        for row in rows:
            assert_append_only_fields(row, f"{row['kind']} entry")
        # The appended COUNTER leaves the OFFER row exactly as it was written.
        assert offer == offer_before


class TestGraphLinks:
    """The junction table and the row that closes the graph cycle."""

    def test_filing_for_another_landowners_parcel_is_refused(self):
        """The chain Application to Parcel to Landowner must close on the caller.

        PRD §3.3: "The parcel's recorded `landowner_id` must equal the body's
        `landowner_id`, and `X-User-ID` must equal it too, otherwise
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/entities/application_for_a_parcel_owned_by_another_landowner_is_rejected
        """
        scenario = setup_program_with_round()
        owner_id = scenario["landowner"]["id"]
        parcel = create_parcel(owner_id)

        intruder = create_landowner(
            legal_name="Coulter Orchards Inc", tax_id_last4="9902"
        )
        intruder_headers = make_landowner_headers(intruder["id"])

        response = api_client.create_application(
            create_application_payload(
                scenario["round"]["id"], parcel["id"], intruder["id"]
            ),
            intruder_headers,
        )
        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        untouched = read_parcel(parcel["id"])
        assert untouched["status"] == "ELIGIBLE"
        assert untouched["landowner_id"] == owner_id

        funding_round = validate_success(
            api_client.get_funding_round(scenario["round"]["id"], ADMIN)
        )
        assert funding_round["application_count"] == 0

        _, meta = validate_paginated(
            api_client.list_applications(ADMIN, {"landowner_id": intruder["id"]})
        )
        assert meta["total_count"] == 0

    def test_commitments_are_enumerable_from_both_of_their_parents(self):
        """One plan mints three rows reachable by application and by source.

        PRD §3.6: "Each new `FundingCommitment` records its `application_id`, its
        `funding_source_id`, its strictly positive `amount_cents`, its
        `sweep_order`, its `absorbed_remainder_cents`, and a frozen copy of the
        source's obligation window as `window_start` and `window_end` for later
        capacity reasoning."

        Design: Corner/entities/funding_commitment_junction_is_reachable_from_both_application_and_source
        """
        scenario = setup_funded_application()
        application_id = scenario["application"]["id"]
        sources = scenario["sources"]
        assert scenario["application"]["total_program_cost_cents"] == 160_364_925

        by_application, application_meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id, "limit": 100}
            )
        )
        assert application_meta["total_count"] == 3
        assert {row["status"] for row in by_application} == {"RESERVED"}
        assert sorted(row["sweep_order"] for row in by_application) == [1, 2, 3]
        for row in by_application:
            assert_funding_commitment(row)
            assert row["application_id"] == application_id

        by_federal, federal_meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"funding_source_id": sources["federal"]["id"]}
            )
        )
        assert federal_meta["total_count"] == 1
        # The last non-zero take absorbs the single cent the flooring left over.
        assert by_federal[0]["amount_cents"] == 40_091_232
        assert by_federal[0]["absorbed_remainder_cents"] == 1

        one_row = validate_success(
            api_client.get_funding_commitment(by_application[0]["id"], ADMIN)
        )
        assert one_row["application_id"] == application_id
        assert one_row["funding_source_id"] in {
            sources["local"]["id"],
            sources["state"]["id"],
            sources["federal"]["id"],
        }

        by_local, local_meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN,
                {"funding_source_id": sources["local"]["id"], "status": "RESERVED"},
            )
        )
        assert local_meta["total_count"] == 1
        assert by_local[0]["amount_cents"] == 56_127_723

    def test_the_easement_resolves_both_of_its_parents(self):
        """Filtering on either parent returns the same single row.

        PRD §2.3: "Easements filter on `parcel_id`, `application_id`, `status`,
        `compliance_status` and `stewardship_status`."

        Design: Corner/entities/easement_resolves_its_parcel_and_application_parents_across_the_graph
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        parcel_id = scenario["parcel"]["id"]
        application_id = scenario["application"]["id"]

        by_parcel, parcel_meta = validate_paginated(
            api_client.list_easements(ADMIN, {"parcel_id": parcel_id})
        )
        assert parcel_meta["total_count"] == 1
        assert by_parcel[0]["id"] == easement_id

        by_application, application_meta = validate_paginated(
            api_client.list_easements(ADMIN, {"application_id": application_id})
        )
        assert application_meta["total_count"] == 1
        assert by_application[0]["id"] == easement_id

        easement = validate_success(api_client.get_easement(easement_id, ADMIN))
        assert easement["parcel_id"] == parcel_id
        assert easement["application_id"] == application_id
        assert easement["recorded_on"].startswith("2026-12-15")
        assert easement["protected_acres"] == pytest.approx(160.00, abs=0.01)
        assert easement["permitted_uses"] == [
            "CROP_PRODUCTION",
            "LIVESTOCK",
            "FARM_STAND",
        ]
        assert easement["subdivision_permitted"] is False

        assert read_parcel(parcel_id)["status"] == "ENCUMBERED"
        program = validate_success(
            api_client.get_program(scenario["program"]["id"], ADMIN)
        )
        assert program["total_preserved_acres"] == pytest.approx(160.00, abs=0.01)


class TestNotFoundAndRequiredFields:
    """Two negative reads that must not degrade into empty successes."""

    def test_an_unminted_funding_source_id_returns_its_own_not_found_code(self):
        """A well-formed id that names no row is a 404, not an empty object.

        PRD §2.10: "When a path contains an identifier, that identifier must
        resolve to an existing row of the endpoint's own entity type before any
        body parsing or business rule runs."

        Design: Corner/entities/funding_source_get_with_unknown_id_returns_source_not_found
        """
        program = create_program()

        response = api_client.get_funding_source(ABSENT_UUID, ADMIN)
        validate_error(response, ApiErrorId.ERR_SOURCE_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"
        assert response.json()["data"]["message"].strip()

        _, meta = validate_paginated(
            api_client.list_funding_sources(ADMIN, {"program_id": program["id"]})
        )
        assert meta["total_count"] == 0

    def test_filing_without_the_requested_price_creates_nothing(self):
        """A missing required field is rejected before anything is written.

        PRD §3.3: "The landowner files it by naming `funding_round_id`,
        `parcel_id`, `landowner_id` and a strictly positive
        `requested_price_cents`, and five gates must clear."

        Design: Corner/entities/application_create_missing_requested_price_returns_invalid_request
        """
        scenario = setup_program_with_round()
        landowner_id = scenario["landowner"]["id"]
        parcel = create_parcel(landowner_id)

        payload = create_application_payload(
            scenario["round"]["id"], parcel["id"], landowner_id
        )
        payload.pop("requested_price_cents")
        response = api_client.create_application(payload, scenario["landowner_headers"])
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

        untouched = read_parcel(parcel["id"])
        assert untouched["status"] == "ELIGIBLE"
        assert untouched["version"] == 1

        funding_round = validate_success(
            api_client.get_funding_round(scenario["round"]["id"], ADMIN)
        )
        assert funding_round["application_count"] == 0

        _, meta = validate_paginated(
            api_client.list_applications(
                ADMIN, {"funding_round_id": scenario["round"]["id"]}
            )
        )
        assert meta["total_count"] == 0
