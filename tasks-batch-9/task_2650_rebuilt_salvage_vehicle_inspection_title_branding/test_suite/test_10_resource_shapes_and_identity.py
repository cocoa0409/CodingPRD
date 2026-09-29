"""Resource shapes, server-minted identity and the reverse-reachable graph.

Every row the program mints publishes a server-stamped identity and a set of
seeded system fields the caller never supplies: a freshly registered vehicle has
no brand and no live application, a freshly licensed rebuilder has an empty fee
ledger, a station without the optional flood flag reads false, and the carrier's
total-loss evaluation is append-only evidence that exposes neither `updated_at`
nor `version`. The list endpoints close the loop by making every foreign key
reverse-reachable, with `total_count` counting the filtered set rather than the
page.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_append_only_resource,
    assert_damage_report,
    assert_inspection_station,
    assert_rebuilder,
    assert_title_record,
    assert_versioned_resource,
    assert_vehicle,
    create_damage_report_payload,
    create_parts_document_payload,
    create_rebuilder_payload,
    create_vehicle_payload,
    get_success_data,
    make_inspector_headers,
    make_rebuilder_headers,
    next_station_code,
    next_vin,
    validate_error,
    validate_paginated,
    validate_success,
    verify_parts_document_payload,
)
from test_helpers.fixtures import (
    add_photo_set,
    file_damage_report,
    file_parts_document,
    issue_title,
    license_rebuilder,
    read_application,
    read_title,
    read_vehicle,
    register_vehicle,
    setup_draft_application,
    setup_salvage_titled_vehicle,
)

api = api_client

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["state_title_clerk_headers"]
ADJUSTER = TEST_USERS["insurer_adjuster_headers"]

CLOCK_EPOCH_PREFIX = "2026-08-01T00:00:00"


class TestRegistrySystemFields:
    """The registry rows the whole program hangs off."""

    def test_registering_a_vehicle_seeds_its_fraud_posture_and_brand_fields(self):
        """A freshly registered wreck carries no brand, no hold and no live application.

        PRD: "A newly registered vehicle starts with `fraud_hold` of `NONE`, `active_brand_code` of `NONE` and an empty `brand_history`."

        Design: Corner/entities/create_vehicle_returns_system_defaults_and_version_one
        """
        vin = next_vin()
        response = api.create_vehicle(
            create_vehicle_payload(vin=vin, body_class="SEDAN"), CLERK
        )
        created = validate_success(response, expected_status=201)
        assert response.json()["response_type"] == "object", (
            f"a single vehicle is an object envelope, got {response.json()['response_type']}"
        )

        vehicle = read_vehicle(created["id"])
        assert_vehicle(vehicle)
        assert vehicle["vin"] == vin, f"expected vin {vin}, got {vehicle['vin']}"
        assert vehicle["body_class"] == "SEDAN", (
            f"expected body_class SEDAN, got {vehicle['body_class']}"
        )
        assert vehicle["fraud_hold"] == "NONE", (
            f"a new vehicle carries no fraud hold, got {vehicle['fraud_hold']}"
        )
        assert vehicle["active_brand_code"] == "NONE", (
            f"a new vehicle carries no brand, got {vehicle['active_brand_code']}"
        )
        assert vehicle["brand_history"] == [], (
            f"a new vehicle has an empty brand history, got {vehicle['brand_history']}"
        )
        assert vehicle["open_application_count"] == 0, (
            f"expected 0 live applications, got {vehicle['open_application_count']}"
        )
        assert vehicle["version"] == 1, (
            f"version starts at 1 on creation, got {vehicle['version']}"
        )

    def test_a_vehicle_with_no_reading_on_file_publishes_a_null_odometer(self):
        """Before any evaluation or conveyance, the vehicle has no mileage of record.

        PRD: "Its `last_odometer_miles` is the highest `odometer_reading_miles` among the vehicle's damage reports and among its `RECORDED` conveyances whose effective instant is at or before the logical clock, and is null when no reading exists at all."

        Design: Corner/entities/create_vehicle_returns_system_defaults_and_version_one
        """
        vehicle = register_vehicle()
        fresh = read_vehicle(vehicle["id"])
        assert fresh["last_odometer_miles"] is None, (
            "a vehicle with no damage report and no conveyance has no reading, "
            f"got {fresh['last_odometer_miles']!r}"
        )

    def test_licensing_a_rebuilder_mints_identity_and_a_zeroed_fee_ledger(self):
        """A newly licensed repair business starts active with an empty money ledger.

        PRD: "A new rebuilder starts with `license_status` of `ACTIVE` and with every fee counter at zero: `fees_deposited_cents`, `fee_balance_cents`, `escrowed_fee_total_cents`, `fees_consumed_cents`, `open_referral_count`, `substantiated_referral_count` and `applications_titled_count` are all 0."

        Design: Corner/entities/system_fields_id_created_at_and_version_are_server_minted
        """
        response = api.create_rebuilder(create_rebuilder_payload(), ADMIN)
        created = validate_success(response, expected_status=201)
        assert created["version"] == 1, (
            f"a server-minted version starts at 1, got {created['version']}"
        )

        rebuilder = get_success_data(api.get_rebuilder(created["id"], ADMIN))
        assert_rebuilder(rebuilder)
        assert_versioned_resource(rebuilder, "rebuilder")
        assert rebuilder["created_at"].startswith(CLOCK_EPOCH_PREFIX), (
            f"created_at is stamped from the logical clock, got {rebuilder['created_at']}"
        )
        assert rebuilder["updated_at"].startswith(CLOCK_EPOCH_PREFIX), (
            f"updated_at is stamped from the logical clock, got {rebuilder['updated_at']}"
        )
        assert rebuilder["license_status"] == "ACTIVE", (
            f"a new licence reads ACTIVE, got {rebuilder['license_status']}"
        )
        for counter in (
            "fees_deposited_cents",
            "fee_balance_cents",
            "escrowed_fee_total_cents",
            "fees_consumed_cents",
            "open_referral_count",
            "substantiated_referral_count",
            "applications_titled_count",
        ):
            assert rebuilder[counter] == 0, (
                f"expected {counter} seeded to 0, got {rebuilder[counter]}"
            )

    def test_a_station_opened_without_the_flood_flag_reads_false(self):
        """A bay opened without the decontamination equipment flag is not flood capable.

        PRD: "Opening an inspection station takes a program-assigned `station_code` unique across all stations, a `bay_count` of at least 1 which caps how many attempts may occupy the station at overlapping times, an `address_state_code`, and an optional `supports_flood` boolean that defaults to false and records whether the station is equipped to inspect `FLOOD`-branded vehicles."

        Design: Corner/entities/omitting_supports_flood_defaults_the_station_to_false
        """
        payload = {
            "station_code": next_station_code(),
            "bay_count": 2,
            "address_state_code": "NV",
        }
        created = validate_success(
            api.create_inspection_station(payload, ADMIN), expected_status=201
        )

        station = get_success_data(api.get_inspection_station(created["id"], ADMIN))
        assert_inspection_station(station)
        assert station["supports_flood"] is False, (
            f"an omitted supports_flood defaults to false, got {station['supports_flood']!r}"
        )
        assert station["bay_count"] == 2, (
            f"expected bay_count 2, got {station['bay_count']}"
        )
        assert station["scheduled_occupancy_count"] == 0, (
            f"a new station holds no attempts, got {station['scheduled_occupancy_count']}"
        )


class TestBrandedTitleReadBack:
    """A minted instrument reads back exactly as the clerk's call left it."""

    def test_reading_a_salvage_title_returns_its_brand_and_issue_face_fields(self):
        """The title minted from a carrier evaluation publishes that evaluation's brand.

        PRD: "When `source_damage_report_id` is supplied, the title's `brand_code` is taken from that report's `recommended_brand_code`, and this is the sole route by which `SALVAGE`, `FLOOD` and `NON_REPAIRABLE` brands enter the system; the referenced report's own `vehicle_id` must equal the `vehicle_id` in the body."

        Design: Corner/entities/get_salvage_title_returns_stored_brand_and_issue_fields
        """
        env = setup_salvage_titled_vehicle(
            report_overrides={"odometer_reading_miles": 68000}
        )

        response = api.get_title_record(env["salvage_title_id"], CLERK)
        title = validate_success(response)
        assert response.json()["response_type"] == "object", (
            f"a single title is an object envelope, got {response.json()['response_type']}"
        )
        assert_title_record(title)

        assert title["brand_code"] == "SALVAGE", (
            f"an 0.80 damage ratio brands SALVAGE, got {title['brand_code']}"
        )
        assert title["brand_severity"] == 30, (
            f"SALVAGE sits at severity 30, got {title['brand_severity']}"
        )
        assert title["status"] == "ACTIVE", (
            f"a freshly minted title is ACTIVE, got {title['status']}"
        )
        assert title["recognition_state"] == "NOT_SUBMITTED", (
            f"no other state has been asked to honour the brand yet, "
            f"got {title['recognition_state']}"
        )
        assert title["issued_at"].startswith(CLOCK_EPOCH_PREFIX), (
            f"issued_at is stamped from the logical clock, got {title['issued_at']}"
        )
        assert title["is_current"] is True, (
            f"the only ACTIVE title of the vehicle is current, got {title['is_current']!r}"
        )
        assert title["transfer_sequence"] == 0, (
            f"the first title on a vehicle sits at chain position 0, "
            f"got {title['transfer_sequence']}"
        )
        assert title["odometer_at_issue_miles"] == 68000, (
            "the salvage title carries the carrier report's reading onto its face, "
            f"got {title['odometer_at_issue_miles']}"
        )

        vehicle = read_vehicle(env["vehicle_id"])
        assert vehicle["active_brand_code"] == "SALVAGE", (
            f"the vehicle's current brand follows its current title, "
            f"got {vehicle['active_brand_code']}"
        )

    def test_the_carrier_evaluation_is_append_only_evidence(self):
        """A filed total-loss evaluation is never edited, so it publishes no version.

        PRD: "Two entities are deliberately append-only and carry only `id` and `created_at`: `InsurerDamageReport` and `InspectionFinding` have no `updated_at` field and no `version` field at all."

        Design: Corner/entities/immutable_damage_report_exposes_no_version_and_no_update_endpoint
        """
        vehicle = register_vehicle()
        report = file_damage_report(vehicle["id"])

        response = api.get_damage_report(report["id"], ADJUSTER)
        read_back = validate_success(response)
        assert_damage_report(read_back)
        assert_append_only_resource(read_back, "damage report")
        assert "version" not in read_back, (
            f"a filed evaluation exposes no version, got {read_back.get('version')!r}"
        )
        assert "updated_at" not in read_back, (
            f"a filed evaluation exposes no updated_at, got {read_back.get('updated_at')!r}"
        )
        assert read_back["created_at"].startswith(CLOCK_EPOCH_PREFIX), (
            f"created_at survives on the append-only row, got {read_back['created_at']}"
        )


class TestListingAndFiltering:
    """Every foreign key is reverse-reachable, and the window never rewrites the count."""

    def test_a_filtered_parts_document_page_counts_the_filtered_set(self):
        """A window over one application's photographs still reports the whole filtered set.

        PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page."

        Design: Corner/entities/list_parts_documents_with_filter_limit_and_offset_reports_total_count
        """
        env = setup_draft_application(body_class="TRAILER")
        add_photo_set(env)

        response = api.list_parts_documents(
            CLERK,
            {"application_id": env["application_id"], "limit": 2, "offset": 2},
        )
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array", (
            f"a list is an array envelope, got {response.json()['response_type']}"
        )
        assert len(rows) == 2, f"expected 2 rows on the page, got {len(rows)}"
        assert meta["total_count"] == 4, (
            f"total_count counts the four filtered documents, got {meta['total_count']}"
        )
        assert meta["limit"] == 2, f"expected limit 2, got {meta['limit']}"
        assert meta["offset"] == 2, f"expected offset 2, got {meta['offset']}"
        assert meta["has_more"] is False, (
            f"rows 3 and 4 exhaust the filtered set, got has_more {meta['has_more']!r}"
        )
        for row in rows:
            assert row["application_id"] == env["application_id"], (
                f"the filter must bind, got application_id {row['application_id']}"
            )
            assert row["part_class"] == "PHOTO_SET", (
                f"photographs are filed under PHOTO_SET, got {row['part_class']}"
            )

    def test_a_donor_document_reaches_both_its_application_and_the_donor_title(self):
        """A harvested part hangs off its own application while citing the donor's title.

        PRD: "Each filed document starts with `status` of `SUBMITTED` and a null `rejection_reason`, and the server computes its `traceable` flag, which is true exactly when `source_type` is `NEW` or when `donor_title_id` is not null, and false otherwise."

        Design: Corner/entities/donor_parts_document_links_both_its_application_and_a_donor_title
        """
        env = setup_draft_application()
        donor_vehicle = register_vehicle()
        donor_title = issue_title(donor_vehicle["id"], owner_name="Vega Auto Recyclers")
        assert donor_title["brand_code"] == "NONE", (
            f"the donor carries a clean title, got {donor_title['brand_code']}"
        )

        document = file_parts_document(
            env["application_id"],
            env["rebuilder_id"],
            doc_type="PARTS_INVOICE",
            part_class="STRUCTURAL",
            source_type="USED_DONOR",
            amount_cents=300_000,
            vendor_name="Vega Auto Recyclers",
            donor_vin=donor_vehicle["vin"],
            donor_title_id=donor_title["id"],
        )
        assert document["traceable"] is True, (
            f"a document naming a donor title is traceable, got {document['traceable']!r}"
        )

        verified = validate_success(
            api.verify_parts_document(
                document["id"],
                verify_parts_document_payload(),
                make_inspector_headers(env["inspector_id"]),
            )
        )
        assert verified["status"] == "VERIFIED", (
            f"expected VERIFIED after the inspector accepts it, got {verified['status']}"
        )
        assert verified["traceable"] is True, (
            f"traceability survives verification, got {verified['traceable']!r}"
        )
        assert verified["application_id"] == env["application_id"], (
            f"the document hangs off its own application, got {verified['application_id']}"
        )
        assert verified["donor_title_id"] == donor_title["id"], (
            f"the sideways link is kept, got {verified['donor_title_id']}"
        )
        assert verified["verified_by_inspector_id"] == env["inspector_id"], (
            "the verifying inspector is recorded from the acting principal, "
            f"got {verified['verified_by_inspector_id']}"
        )

        donor_read_back = read_title(donor_title["id"])
        assert donor_read_back["status"] == "ACTIVE", (
            f"the donor title is still ACTIVE, got {donor_read_back['status']}"
        )

        application = read_application(env["application_id"])
        assert application["documented_parts_cost_cents"] == 300_000, (
            "the verified amount enters the documented parts cost, "
            f"got {application['documented_parts_cost_cents']}"
        )

        rows, meta = validate_paginated(
            api.list_parts_documents(CLERK, {"donor_title_id": donor_title["id"]})
        )
        assert meta["total_count"] == 1, (
            f"exactly one document cites this donor title, got {meta['total_count']}"
        )
        assert rows[0]["id"] == document["id"], (
            f"expected the donor document, got {rows[0]['id']}"
        )


class TestUnknownIdentifiersAndMalformedBodies:
    """Existence is resolved before anything else, and a closed enum stays closed."""

    def test_an_unknown_application_id_is_a_not_found_rather_than_an_empty_body(self):
        """A syntactically valid identifier the office never issued resolves to nothing.

        PRD: "Depending on the segment, this yields `ERR_VEHICLE_NOT_FOUND`, `ERR_REBUILDER_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_PARTS_DOCUMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_RECOGNITION_REQUEST_NOT_FOUND`, `ERR_DAMAGE_REPORT_NOT_FOUND` or `ERR_TRANSFER_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_application_with_unknown_id_returns_not_found
        """
        register_vehicle()

        response = api.get_application(NON_EXISTENT_UUID, CLERK)
        validate_error(response, "ERR_APPLICATION_NOT_FOUND")
        assert response.json()["response_type"] == "error", (
            f"an unresolved read is an error envelope, got {response.json()['response_type']}"
        )

    def test_filing_a_document_under_an_unknown_application_reports_the_parent(self):
        """The path parent is resolved before the draft-state gate ever speaks.

        PRD: "Existence of every resource named by a path segment, validated strictly left to right, so that a nested path reports the leftmost unresolvable segment."

        Design: Corner/entities/parts_document_creation_under_unknown_application_returns_not_found
        """
        rebuilder = license_rebuilder()

        response = api.create_parts_document(
            NON_EXISTENT_UUID,
            create_parts_document_payload(),
            make_rebuilder_headers(rebuilder["id"]),
        )
        validate_error(response, "ERR_APPLICATION_NOT_FOUND")
        assert response.json()["data"]["error_id"] != "ERR_APPLICATION_NOT_DRAFT", (
            "an unresolvable parent outranks the draft-state gate, "
            f"got {response.json()['data']['error_id']}"
        )

    @pytest.mark.parametrize(
        "missing_field",
        [
            "acv_cents",
            "repair_estimate_cents",
            "basis_code",
            "damage_type",
            "claim_number",
            "report_effective_at",
        ],
    )
    def test_a_total_loss_evaluation_missing_a_required_field_is_malformed(
        self, missing_field
    ):
        """A carrier filing that leaves out a required field files nothing at all.

        PRD: "This covers a missing required field, an enum value that is not a declared member, a negative money or mileage amount where the field is constrained to be non-negative, a timestamp that is not ISO 8601, a `scheduled_end_at` that is at or before `scheduled_start_at`, a `limit` outside 1 through 100 or a negative `offset`, a `vin` that is not exactly seventeen legal characters, a `checkpoint_results` array that is missing one of the weighted checkpoints, and an `attestation_signed` value that is not true."

        Design: Corner/entities/create_damage_report_missing_acv_cents_returns_invalid_request
        """
        vehicle = register_vehicle()
        payload = create_damage_report_payload(vehicle["id"])
        payload.pop(missing_field)

        validate_error(api.create_damage_report(payload, ADJUSTER), "ERR_INVALID_REQUEST")

        rows, meta = validate_paginated(
            api.list_damage_reports(ADJUSTER, {"vehicle_id": vehicle["id"]})
        )
        assert meta["total_count"] == 0, (
            f"a malformed filing creates no evaluation row, got {meta['total_count']}"
        )
        assert rows == [], f"expected no rows on file, got {len(rows)}"

    @pytest.mark.parametrize("illegal_body_class", ["HOVERCRAFT", "sedan", "VAN", ""])
    def test_a_body_class_outside_the_declared_set_registers_nothing(
        self, illegal_body_class
    ):
        """The body classification is a closed list, because it drives the parts record.

        PRD: "The `body_class` is one of `SEDAN`, `SUV`, `TRUCK`, `MOTORCYCLE` or `TRAILER`, and it is more consequential than it looks: it selects the list of part classes the rebuilder will later be required to document."

        Design: Corner/entities/invalid_body_class_enum_on_vehicle_create_is_rejected
        """
        vin = next_vin()
        validate_error(
            api.create_vehicle(
                create_vehicle_payload(vin=vin, body_class=illegal_body_class), CLERK
            ),
            "ERR_INVALID_REQUEST",
        )

        # The identification number is globally unique, so a clean re-registration
        # under the same vin proves the rejected call persisted nothing.
        retry = validate_success(
            api.create_vehicle(create_vehicle_payload(vin=vin, body_class="SEDAN"), CLERK),
            expected_status=201,
        )
        assert retry["vin"] == vin, (
            f"the rejected call must not have consumed the vin, got {retry['vin']}"
        )
