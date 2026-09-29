"""Shapes, defaults, derived fields and rejection shapes of the registry rows.

Every precondition is built through the documented endpoints against an empty
database whose logical clock reads 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    assert_assurance,
    assert_immutable_row,
    assert_mass,
    assert_ratio,
    assert_unit_state,
    fixtures,
    make_generator_headers,
)
from test_helpers.factories import (
    OMIT,
    container_payload,
    facility_payload,
    manifest_line_payload,
    manifest_payload,
    sample_payload,
    storage_unit_payload,
    waste_profile_payload,
)
from test_helpers.test_users import CHEMIST_USER_ID


class TestFacilityRegistryShape:
    def test_registration_publishes_the_whole_derived_assurance_stack(self, api):
        """A facility registered against an empty inventory already prices its closure obligation.

        A newly registered facility opens with `permit_status` of `ACTIVE`, with `renewal_requested_at` and `requested_permit_expires_at` both null, and with every derived mass and assurance figure computed from an empty inventory.
        `closure_base_cost_cents` is 25,000,000 cents of fixed closure overhead plus 1,800 cents for every kilogram of `held_mass_kg`, that per-kilogram product being rounded half up to whole cents before it is added to the fixed component.
        `assurance_tier` is `TIER_1` when `closure_base_cost_cents` is below 30,000,000 cents, `TIER_2` when it is below 60,000,000 cents but not below 30,000,000, and `TIER_3` otherwise.
        The rate is 5 percent for `TIER_1`, 10 percent for `TIER_2` and 18 percent for `TIER_3`.
        `required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`.
        `posted_assurance_cents` is the sum of `face_amount_cents` over the facility's instruments whose `status` is `ACTIVE`, and `assurance_shortfall_cents` is the amount by which the required total exceeds the posted total, or zero when the posted total is at least the required total.
        `open_snc_finding_count` counts the facility's findings whose `finding_class` is `SNC` and whose `status` is `OPEN`, `RESPONDED` or `REOPENED`.
        `corrective_action_status` is `NONE` when the facility has no findings at all, otherwise `OPEN` when any finding is `OPEN` or `REOPENED`, otherwise `IN_PROGRESS` when any finding is `RESPONDED`, and otherwise `COMPLETED` — that last case meaning every finding is `CLOSED`.
        `corrective_action_reserve_cents` is 5,000,000 cents for each finding counted in `open_snc_finding_count`.
        `mass_ledger_kg` is the sum of those five destinations, and it must equal `received_mass_kg` after every operation, with no rounding drift.
        Operations that mint a new resource return HTTP 201.

        Design: Corner/entities/facility_create_returns_declared_and_derived_assurance_fields
        """
        fixtures.set_clock()

        facility = validate_success(
            api.create_facility(facility_payload(), TEST_USERS["admin"]), expected_status=201
        )

        assert is_valid_uuid(facility["id"])
        assert is_iso8601_timestamp(facility["created_at"])
        assert facility["version"] == 1
        assert facility["permit_status"] == "ACTIVE"
        assert facility["renewal_requested_at"] is None
        assert facility["requested_permit_expires_at"] is None
        assert facility["open_snc_finding_count"] == 0
        assert facility["corrective_action_status"] == "NONE"

        assert_mass(facility["received_mass_kg"], 0.0, "received_mass_kg")
        assert_mass(facility["held_mass_kg"], 0.0, "held_mass_kg")
        assert_mass(facility["mass_ledger_kg"], 0.0, "mass_ledger_kg")

        # 25,000,000 fixed overhead on no held mass, TIER_1 surcharge of 5 percent,
        # plus the 8,000,000-cent post-closure estimate, against nothing posted.
        assert_assurance(
            facility,
            base_cents=25_000_000,
            tier="TIER_1",
            estimate_cents=26_250_000,
            reserve_cents=0,
            liability_cents=0,
            required_cents=34_250_000,
            posted_cents=0,
            shortfall_cents=34_250_000,
        )

    def test_retrieval_shows_stored_inputs_and_the_posted_assurance(self, api):
        """A read after the instrument post shows the declared inputs plus the funded figures.

        A `PlatformAdmin` brings a facility into the system by supplying its legal `name` (between 1 and 120 characters), its 12-character `epa_id` handler identifier, its RCRA Part B `permit_number`, the instant `permit_expires_at` at which the current permit lapses, the non-empty list of `permitted_methods` the permit authorises, the permit's cap on simultaneously scheduled runs in `max_concurrent_treatment_batches` (at least 1), and the approved post-closure care cost estimate `post_closure_cost_cents` (zero or greater).
        The new instrument opens `ACTIVE`.
        As a cascade, the facility's prior `ACTIVE` instrument moves to `SUPERSEDED`, with its `superseded_by_instrument_id` set to the new instrument's identifier and its `superseded_at` stamped with the current clock instant; the facility's `version` advances; and `posted_assurance_cents` and `assurance_shortfall_cents` are recomputed from the surviving `ACTIVE` instrument alone.
        Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed whenever any stored or derived property of the row changes, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of the row.
        `posted_assurance_cents` is the sum of `face_amount_cents` over the facility's instruments whose `status` is `ACTIVE`, and `assurance_shortfall_cents` is the amount by which the required total exceeds the posted total, or zero when the posted total is at least the required total.
        Reads return HTTP 200.

        Design: Corner/entities/facility_retrieval_returns_stored_row_with_posted_assurance
        """
        fixtures.set_clock()
        created = fixtures.create_facility()
        instrument = fixtures.post_instrument(
            created["id"],
            face_amount_cents=90_000_000,
            expected_facility_version=created["version"],
        )
        assert instrument["status"] == "ACTIVE"

        facility = validate_success(api.get_facility(created["id"], TEST_USERS["inspector"]))

        assert facility["epa_id"] == TEST_DEFAULTS["facility_epa_id"]
        assert facility["permit_number"] == TEST_DEFAULTS["permit_number"]
        assert facility["max_concurrent_treatment_batches"] == 5
        assert facility["post_closure_cost_cents"] == TEST_DEFAULTS["post_closure_cost_cents"]
        assert facility["permitted_methods"] == [
            "INCINERATION",
            "STABILIZATION",
            "NEUTRALIZATION",
        ]

        # Posting the instrument mutated the facility row, so it now reads version 2.
        assert facility["version"] == 2
        assert_assurance(
            facility,
            posted_cents=90_000_000,
            required_cents=34_250_000,
            shortfall_cents=0,
        )


class TestGeneratorRegistryListing:
    def test_listing_reports_the_filtered_total_not_the_page(self, api):
        """Two pages of a three-generator registry, plus the documented equality filters.

        `limit` is the maximum number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100.
        List responses include `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page.
        Generators may be filtered by `status`, `epa_id` and `generator_category`.
        A generator opens with `status` of `ACTIVE`, with `suspension_reason_code` null, with all four charge balances — `open_charge_cents`, `settled_charge_cents`, `voided_charge_cents` and `charge_adjustment_cents` — at zero, and with both reliability scores at 100, because no manifest of that generator has closed yet.

        Design: Corner/entities/generator_listing_paginates_with_total_count_and_has_more
        """
        fixtures.set_clock()
        first = fixtures.create_generator()
        second = fixtures.create_generator(
            epa_id="TXR000555777", name="Gulf Platers", generator_category="SQG"
        )
        third = fixtures.create_generator(
            epa_id="TXR000555888",
            name="Delta Labs",
            generator_category="VSQG",
            state_code="LA",
        )

        page_one_response = api.list_generators(
            TEST_USERS["admin"], params={"limit": 2, "offset": 0}
        )
        page_one, meta_one = validate_paginated(page_one_response)
        assert page_one_response.json()["response_type"] == "array"
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0

        page_two, meta_two = validate_paginated(
            api.list_generators(TEST_USERS["admin"], params={"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["limit"] == 2
        assert meta_two["offset"] == 2

        # The two pages together cover the registry exactly once.
        assert {row["id"] for row in page_one + page_two} == {
            first["id"],
            second["id"],
            third["id"],
        }

        by_category, category_meta = validate_paginated(
            api.list_generators(TEST_USERS["admin"], params={"generator_category": "SQG"})
        )
        assert category_meta["total_count"] == 1
        assert [row["id"] for row in by_category] == [second["id"]]

        _, active_meta = validate_paginated(
            api.list_generators(TEST_USERS["admin"], params={"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 3


class TestWasteProfileDefaults:
    def test_creation_defaults_recertification_and_sorts_waste_codes(self, api):
        """An omitted recertification term becomes twelve months and the codes are stored ascending.

        A waste stream reaches the facility as a **waste profile**, created either by the generator itself or by a `ComplianceManager` on its behalf. Creation supplies the `generator_id` that characterised the stream, the `facility_id` the profile is filed with, a non-empty array of EPA `waste_codes`, the `physical_form` (`BULK_LIQUID`, `SLUDGE`, `SOLID` or `LAB_PACK`), the `compatibility_class` (`ACID`, `ALKALINE`, `OXIDIZER`, `CYANIDE_BEARING`, `WATER_REACTIVE` or `ORGANIC_SOLVENT`), the `ldr_subcategory` naming the land disposal restriction treatment standard family (`NONE`, `D001_IGNITABLE`, `D008_LEAD` or `F001_SOLVENTS`), the generator's characterisation figures `declared_constituent_ppm` (zero or greater), `declared_flash_point_c` as a closed-cup flash point in degrees Celsius and `declared_ph` (between 0 and 14), the `requested_treatment_method` drawn from the same five methods a permit may authorise, and optionally `recertification_months` — the number of calendar months an approval remains valid, between 1 and 24, defaulting to 12 when omitted.
        The `waste_codes` array is stored sorted in ascending order.
        A new profile opens in `DRAFT`, with `sample_attempt_count` at zero, `latest_sample_result` of `NONE`, and `approved_treatment_method`, `approved_at`, `approved_by_user_id`, `recertification_due_at` and `suspension_reason_code` all null.

        Design: Corner/entities/waste_profile_create_applies_default_recertification_and_sorts_codes
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        generator = fixtures.create_generator()

        profile = validate_success(
            api.create_waste_profile(
                waste_profile_payload(
                    generator["id"],
                    facility["id"],
                    waste_codes=["F003", "D001"],
                    recertification_months=OMIT,
                ),
                make_generator_headers(generator["id"]),
            ),
            expected_status=201,
        )

        assert profile["recertification_months"] == 12
        assert profile["waste_codes"] == ["D001", "F003"]
        assert profile["status"] == "DRAFT"
        assert profile["sample_attempt_count"] == 0
        assert profile["latest_sample_result"] == "NONE"
        assert profile["approved_treatment_method"] is None
        assert profile["approved_at"] is None
        assert profile["approved_by_user_id"] is None
        assert profile["recertification_due_at"] is None
        assert profile["suspension_reason_code"] is None
        assert profile["version"] == 1


class TestContainerDerivedFigures:
    def test_placement_derives_fill_ratio_accumulation_and_profile_link(self, api):
        """A 200 kg drum in a 250 kg shell, marked as accumulating since 25 July.

        The **headspace rule** requires `net_weight_kg` to be no greater than 95 percent of `capacity_kg`, and the container's `fill_ratio` — `net_weight_kg` divided by `capacity_kg`, carried to 4 decimals — is exposed so the margin is visible.
        `accumulation_days` is the number of whole 86,400-second days that have elapsed from `accumulation_start_date` to the current clock instant, taking the floor, and it is recomputed on every read.
        `ten_day_overdue` is true when the container sits in a unit whose `unit_type` is `TEN_DAY_TRANSFER` and its `accumulation_days` is strictly greater than 10.
        The container's `waste_profile_id` is not supplied by the caller: it is copied from the manifest line at creation and is thereafter the authority for compatibility, labelling and land-disposal-restriction checks on that container.
        A new container opens with `custody_state` of `FILLING`, `compliance_state` of `COMPLIANT`, `last_finding_code` null, and `treatment_batch_id` null.
        **Mass allocation** requires the container's `net_weight_kg` to be no greater than what remains on its receipt line, that remainder being the line's `accepted_quantity_kg` less its `allocated_container_mass_kg`, where `allocated_container_mass_kg` is the sum of `net_weight_kg` over the line's containers whose custody is anything other than `VOIDED`.

        Design: Corner/entities/container_computed_fields_derived_from_inputs_and_clock
        """
        scenario = fixtures.setup_received_manifest()

        container = validate_success(
            api.create_container(
                container_payload(
                    scenario.line["id"],
                    scenario.unit["id"],
                    net_weight_kg=200.0,
                    capacity_kg=250.0,
                    accumulation_start_date="2026-07-25T00:00:00Z",
                ),
                TEST_USERS["clerk"],
            ),
            expected_status=201,
        )

        assert_ratio(container["fill_ratio"], 0.8, "fill_ratio")
        # Seven whole days separate 25 July from the clock instant of 1 August.
        assert container["accumulation_days"] == 7
        assert container["ten_day_overdue"] is False
        assert container["custody_state"] == "FILLING"
        assert container["compliance_state"] == "COMPLIANT"
        assert container["last_finding_code"] is None
        assert container["treatment_batch_id"] is None
        assert container["waste_profile_id"] == scenario.profile["id"]
        assert container["version"] == 1

        line = fixtures.read_line(scenario.manifest["id"], 1)
        assert_mass(line["allocated_container_mass_kg"], 200.0, "allocated_container_mass_kg")


class TestProfileSampleImmutability:
    def test_laboratory_record_carries_only_identity_and_creation_time(self, api):
        """The laboratory run is an append-only record of a moment, not a mutable row.

        Two resources are append-only records of a moment in time and therefore carry **only** `id` and `created_at`: a `ProfileSample` and an `InspectionEvent` have no `updated_at` field and no `version` field at all.
        The sample row records `recorded_by_user_id` from the acting `X-User-ID` and `recorded_at` from the logical clock, and it references the profile it checks through `waste_profile_id`.
        The tolerance set is chosen by the profile's `required_sample_type`, and the choice actually made is copied onto the sample as `applied_tolerance_type` so that the decision is auditable after the fact.
        That recomputation is a single threshold: `required_sample_type` becomes `FULL` when the generator's rolling reliability score is below 60, or when the profile's `sample_attempt_count` is at least 1; otherwise it becomes `FINGERPRINT`.
        If none breaches, the sample's `result` is `PASS` and `failure_reason_code` is `NONE`.

        Design: Corner/entities/profile_sample_is_immutable_and_carries_no_version
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        generator = fixtures.create_generator()
        profile = fixtures.create_draft_profile(generator["id"], facility["id"])
        submitted = fixtures.submit_profile(profile["id"], generator["id"])

        sample = validate_success(
            api.create_profile_sample(
                profile["id"],
                sample_payload(submitted["version"]),
                TEST_USERS["chemist"],
            ),
            expected_status=201,
        )

        assert_immutable_row(sample)
        assert sample["waste_profile_id"] == profile["id"]
        assert sample["recorded_by_user_id"] == CHEMIST_USER_ID
        assert is_iso8601_timestamp(sample["recorded_at"])
        assert sample["recorded_at"].startswith("2026-08-01T00:00:00")
        # A generator with no closed manifests scores 100 and the profile has never
        # been sampled, so the fingerprint tolerance set is the one applied.
        assert sample["applied_tolerance_type"] == "FINGERPRINT"
        assert sample["result"] == "PASS"
        assert sample["failure_reason_code"] == "NONE"

        rows, meta = validate_paginated(
            api.list_profile_samples(profile["id"], TEST_USERS["chemist"])
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [sample["id"]]
        assert_immutable_row(rows[0])


class TestNotFoundByPathFamily:
    def test_each_path_family_answers_with_its_own_missing_row_error(self, api):
        """An empty database, so nothing but the addressed collection can decide the error.

        Not-found errors are entity-specific.
        A missing facility yields `ERR_FACILITY_NOT_FOUND`, a missing generator `ERR_GENERATOR_NOT_FOUND`, a missing waste profile `ERR_WASTE_PROFILE_NOT_FOUND`, a missing manifest `ERR_MANIFEST_NOT_FOUND`, a missing storage unit `ERR_STORAGE_UNIT_NOT_FOUND`, a missing container `ERR_CONTAINER_NOT_FOUND`, and a missing treatment batch `ERR_TREATMENT_BATCH_NOT_FOUND`.
        Instruments, samples, inspection events, emission repair orders and compliance findings share the generic `ERR_RESOURCE_NOT_FOUND`.
        All of these carry HTTP 404.

        Design: Corner/entities/entity_specific_not_found_errors_returned_per_path_family
        """
        fixtures.set_clock()
        admin = TEST_USERS["admin"]

        missing_facility = api.get_facility(NON_EXISTENT_UUID, admin)
        validate_error(missing_facility, "ERR_FACILITY_NOT_FOUND")
        validate_error(api.get_generator(NON_EXISTENT_UUID, admin), "ERR_GENERATOR_NOT_FOUND")
        validate_error(
            api.get_waste_profile(NON_EXISTENT_UUID, admin), "ERR_WASTE_PROFILE_NOT_FOUND"
        )
        validate_error(api.get_manifest(NON_EXISTENT_UUID, admin), "ERR_MANIFEST_NOT_FOUND")
        validate_error(
            api.get_storage_unit(NON_EXISTENT_UUID, admin), "ERR_STORAGE_UNIT_NOT_FOUND"
        )
        validate_error(api.get_container(NON_EXISTENT_UUID, admin), "ERR_CONTAINER_NOT_FOUND")
        validate_error(
            api.get_treatment_batch(NON_EXISTENT_UUID, admin), "ERR_TREATMENT_BATCH_NOT_FOUND"
        )

        # The registry-style rows collapse onto the generic missing-row error.
        validate_error(api.get_instrument(NON_EXISTENT_UUID, admin), "ERR_RESOURCE_NOT_FOUND")
        validate_error(api.get_repair_order(NON_EXISTENT_UUID, admin), "ERR_RESOURCE_NOT_FOUND")
        validate_error(
            api.get_compliance_finding(NON_EXISTENT_UUID, admin), "ERR_RESOURCE_NOT_FOUND"
        )

        body = missing_facility.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestWriteSchemaRejections:
    def test_manifest_without_its_lines_array_is_refused(self, api):
        """A shipment announcement must carry the ordered lines it declares.

        A `Generator` or a `ReceivingClerk` creates a manifest naming the `generator_id` that offers the waste, the `facility_id` designated to receive it, the uniform hazardous waste `manifest_tracking_number` (unique across all manifests), the `transporter_epa_id` of the delivering transporter, the `shipped_on` date on which the shipment left the generator as an ISO 8601 calendar date, and an ordered `lines` array.
        Required fields are present, types are correct, enumerated values are in range, numeric constraints hold, `window_end` is strictly later than `window_start`, each supplied `accepted_quantity_kg` is no greater than the line's `received_quantity_kg`, and unknown fields are rejected — `ERR_INVALID_REQUEST` (400).

        Design: Corner/entities/manifest_create_without_lines_rejected
        """
        fixtures.set_clock()
        facility = fixtures.create_facility(permitted_methods=["INCINERATION"])
        generator = fixtures.create_generator()

        payload = manifest_payload(generator["id"], facility["id"])
        payload.pop("lines")

        validate_error(api.create_manifest(payload, TEST_USERS["clerk"]), "ERR_INVALID_REQUEST")

        rows, meta = validate_paginated(
            api.list_manifests(TEST_USERS["clerk"], params={"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_storage_unit_with_an_undeclared_unit_type_is_refused_as_invalid(self, api):
        """An out-of-domain unit type loses to no later rule, not even the inspection ceiling.

        Required fields are present, types are correct, enumerated values are in range, numeric constraints hold, `window_end` is strictly later than `window_start`, each supplied `accepted_quantity_kg` is no greater than the line's `received_quantity_kg`, and unknown fields are rejected — `ERR_INVALID_REQUEST` (400).
        All validations are evaluated in ascending priority order and **the first violated rule wins**; no later rule may mask an earlier one, and no earlier rule may be skipped because a later one would also fail.
        `inspection_frequency_days` respects the ceiling for the declared `unit_type` — `ERR_INSPECTION_FREQUENCY_INVALID` (422).

        Design: Corner/entities/storage_unit_create_with_invalid_unit_type_enum_rejected
        """
        fixtures.set_clock()
        facility = fixtures.create_facility(permitted_methods=["INCINERATION"])

        # The frequency of 30 days would also breach the ceiling, but that ceiling is
        # keyed on the very unit type being rejected here.
        validate_error(
            api.create_storage_unit(
                storage_unit_payload(
                    facility["id"],
                    unit_type="DRUM_ROW",
                    inspection_frequency_days=30,
                    allowed_compatibility_classes=["ORGANIC_SOLVENT"],
                ),
                TEST_USERS["admin"],
            ),
            "ERR_INVALID_REQUEST",
        )

        rows, meta = validate_paginated(
            api.list_storage_units(TEST_USERS["admin"], params={"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_container_drawing_on_an_unknown_receipt_line_reports_a_missing_reference(self, api):
        """The receipt line is a body reference, so an unknown value is a missing reference.

        A foreign key in a request body that resolves to nothing yields `ERR_REFERENCE_NOT_FOUND`, also HTTP 404.
        A new unit opens with `status` of `ACTIVE`, `closure_plan_ref` null, `last_inspection_at` initialised to the unit's own `created_at`, and `posture` of `OPEN`.
        `container_count` is the number of containers in the unit whose custody is `FILLING`, `SEALED` or `STAGED`.
        `stored_kg` is the sum of `net_weight_kg` over those same containers, to 3 decimals.

        Design: Corner/entities/container_create_with_unknown_manifest_line_not_found
        """
        fixtures.set_clock()
        facility, _instrument = fixtures.create_funded_facility()
        unit = fixtures.create_storage_unit(facility["id"])

        validate_error(
            api.create_container(
                container_payload(NON_EXISTENT_UUID, unit["id"]), TEST_USERS["clerk"]
            ),
            "ERR_REFERENCE_NOT_FOUND",
        )

        assert_unit_state(
            fixtures.read_unit(unit["id"]),
            container_count=0,
            stored_kg=0.0,
            posture="OPEN",
        )


class TestCrossFacilityReferenceIntegrity:
    def test_manifest_line_naming_another_facilitys_profile_is_out_of_scope(self, api):
        """An approved profile filed with one facility cannot ship on another facility's manifest.

        A container's storage unit must belong to the same facility as the manifest behind its receipt line; a treatment batch's storage unit must belong to the batch's own facility; a manifest line's waste profile must have been filed with the same facility the manifest designates; and a compliance finding's storage unit, when one is named, must belong to the cited facility.
        A crossed reference is rejected with `ERR_FACILITY_SCOPE_MISMATCH` (HTTP 409).

        Design: Corner/entities/manifest_line_profile_from_another_facility_rejected
        """
        fixtures.set_clock()
        receiving_facility = fixtures.create_facility(permitted_methods=["INCINERATION"])
        other_facility = fixtures.create_facility(
            name="Sabine TSDF",
            epa_id="TXD000333444",
            permit_number="TX-HW-0092",
            permitted_methods=["INCINERATION"],
        )
        generator = fixtures.create_generator()
        profile = fixtures.create_approved_profile(generator["id"], other_facility["id"])
        assert profile["status"] == "APPROVED"

        validate_error(
            api.create_manifest(
                manifest_payload(
                    generator["id"],
                    receiving_facility["id"],
                    lines=[manifest_line_payload(profile["id"], 1000.0, 4, False)],
                ),
                TEST_USERS["clerk"],
            ),
            "ERR_FACILITY_SCOPE_MISMATCH",
        )

        # The profile itself is untouched and still fit to ship to its own facility.
        assert fixtures.read_profile(profile["id"])["status"] == "APPROVED"

        rows, meta = validate_paginated(
            api.list_manifests(
                TEST_USERS["clerk"], params={"facility_id": receiving_facility["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
