"""Declared error catalogue: distinct ids, distinct scopes and ladder order."""

from test_helpers import (
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDuplicateBusinessKeys:
    def test_the_six_uniqueness_clashes_report_six_distinct_ids(self, api):
        """PRD §2.11: "8. Uniqueness constraints — otherwise
        `ERR_DUPLICATE_LOCATION_CODE`, `ERR_DUPLICATE_AGREEMENT_CODE`,
        `ERR_DUPLICATE_CASING_SERIAL`, `ERR_DUPLICATE_TIRE_POLICY`,
        `ERR_DUPLICATE_VEHICLE_UNIT` or `ERR_DUPLICATE_LINE_CODE`."
        PRD §3.1: "Fleet units are registered under the fleet account by a
        `DealerAdmin` or the `FleetManager` itself, carrying a `unit_number` that must
        be unique within the fleet — a repeat is rejected with
        `ERR_DUPLICATE_VEHICLE_UNIT` — a `vehicle_type` of `TRACTOR`, `TRAILER` or
        `STRAIGHT_TRUCK` that later serves as a cost-per-mile grouping dimension, and a
        starting `current_odometer_miles` of 0 or more."

        Design: Corner/errors/six_duplicate_business_key_errors_are_distinct
        """
        location_a = fixtures.create_location(
            name="Unique Commercial",
            location_code="UQC",
            state_code="OH",
            scrap_permit_number="OH-SCRAP-4032",
            is_retread_plant=True,
        )
        location_b = fixtures.create_location(
            name="Unique Second",
            location_code="UQD",
            state_code="IN",
            scrap_permit_number="IN-SCRAP-4032",
            is_retread_plant=True,
        )
        fleet_a = fixtures.create_fleet(
            location_a["id"],
            name="Unique Fleet A",
            account_type="NATIONAL_ACCOUNT",
            billing_mode="CROSS_LOCATION",
        )
        fleet_b = fixtures.create_fleet(
            location_b["id"], name="Unique Fleet B"
        )
        validate_success(
            api.create_vehicle(
                fleet_a["id"],
                factories.vehicle_payload(
                    unit_number="T-200", current_odometer_miles=1000
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )
        fixtures.create_policy(fleet_a["id"], position="DRIVE")
        fixtures.create_retread_line(location_a["id"], line_code="L1")
        validate_success(
            api.create_national_agreement(
                factories.national_agreement_payload(
                    fleet_a["id"],
                    agreement_code="UQ-2026",
                    tier_discount_pct=0.10,
                    casing_credit_rate_cents=14000,
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )
        fixtures.create_casing(fleet_a["id"], casing_serial="CS-4032")

        clashes = [
            validate_error(
                api.create_service_location(
                    factories.service_location_payload(
                        name="Clash Location",
                        location_code="UQC",
                        state_code="KY",
                        scrap_permit_number="KY-SCRAP-4032",
                    ),
                    fixtures.ADMIN,
                ),
                "ERR_DUPLICATE_LOCATION_CODE",
                expected_status=409,
            )["error_id"],
            validate_error(
                api.create_casing(
                    factories.casing_payload(fleet_b["id"], casing_serial="CS-4032"),
                    fixtures.ADMIN,
                ),
                "ERR_DUPLICATE_CASING_SERIAL",
                expected_status=409,
            )["error_id"],
            validate_error(
                api.create_vehicle(
                    fleet_a["id"],
                    factories.vehicle_payload(
                        unit_number="T-200",
                        vehicle_type="TRAILER",
                        current_odometer_miles=5,
                    ),
                    fixtures.ADMIN,
                ),
                "ERR_DUPLICATE_VEHICLE_UNIT",
                expected_status=409,
            )["error_id"],
            validate_error(
                api.create_tire_policy(
                    fleet_a["id"],
                    factories.tire_policy_payload(
                        position="DRIVE",
                        target_pressure_psi=105,
                        approved_brands=["Michelin"],
                    ),
                    fixtures.ADMIN,
                ),
                "ERR_DUPLICATE_TIRE_POLICY",
                expected_status=409,
            )["error_id"],
            validate_error(
                api.create_retread_line(
                    location_a["id"],
                    factories.retread_line_payload(
                        line_code="L1", cure_cooldown_minutes=45
                    ),
                    fixtures.ADMIN,
                ),
                "ERR_DUPLICATE_LINE_CODE",
                expected_status=409,
            )["error_id"],
            validate_error(
                api.create_national_agreement(
                    factories.national_agreement_payload(
                        fleet_b["id"],
                        agreement_code="UQ-2026",
                        tier_discount_pct=0.05,
                        casing_credit_rate_cents=9000,
                    ),
                    fixtures.ADMIN,
                ),
                "ERR_DUPLICATE_AGREEMENT_CODE",
                expected_status=409,
            )["error_id"],
        ]
        assert len(set(clashes)) == 6, (
            "six uniqueness rules share one status but never one identifier"
        )

        # The scopes differ, and the two accepted requests are what proves it.
        accepted_unit = validate_success(
            api.create_vehicle(
                fleet_b["id"],
                factories.vehicle_payload(
                    unit_number="T-200", current_odometer_miles=10
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )
        assert accepted_unit["unit_number"] == "T-200", (
            "unit numbers are unique within a fleet, not across the dealer"
        )
        accepted_line = validate_success(
            api.create_retread_line(
                location_b["id"],
                factories.retread_line_payload(line_code="L1"),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )
        assert accepted_line["line_code"] == "L1", (
            "line codes are unique within a location"
        )


class TestPerCollectionNotFound:
    def test_each_collection_reports_its_own_not_found_identifier(self, api):
        """PRD §2.6: "When a path contains more than one identifier, identifiers are
        resolved strictly left to right, and the first one that fails to resolve
        determines the error."
        PRD §2.6: "Each entity type has its own not-found code —
        `ERR_SERVICE_LOCATION_NOT_FOUND`, `ERR_FLEET_ACCOUNT_NOT_FOUND`,
        `ERR_NATIONAL_AGREEMENT_NOT_FOUND`, `ERR_TIRE_POLICY_NOT_FOUND`,
        `ERR_VEHICLE_NOT_FOUND`, `ERR_CASING_NOT_FOUND`, `ERR_TIRE_ASSET_NOT_FOUND`,
        `ERR_TIRE_SURVEY_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`,
        `ERR_RETREAD_LINE_NOT_FOUND`, `ERR_RETREAD_JOB_NOT_FOUND`,
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_ROAD_SERVICE_CALL_NOT_FOUND`,
        `ERR_SCRAP_MANIFEST_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND` — all at HTTP 404."

        Design: Corner/errors/every_path_parameter_has_its_own_not_found_error
        """
        missing = "00000000-0000-0000-0000-0000000000{:02d}"
        reads = [
            (api.get_service_location, "ERR_SERVICE_LOCATION_NOT_FOUND"),
            (api.get_fleet_account, "ERR_FLEET_ACCOUNT_NOT_FOUND"),
            (api.get_national_agreement, "ERR_NATIONAL_AGREEMENT_NOT_FOUND"),
            (api.get_tire_policy, "ERR_TIRE_POLICY_NOT_FOUND"),
            (api.get_vehicle, "ERR_VEHICLE_NOT_FOUND"),
            (api.get_tire_asset, "ERR_TIRE_ASSET_NOT_FOUND"),
            (api.get_tire_survey, "ERR_TIRE_SURVEY_NOT_FOUND"),
            (api.get_retread_line, "ERR_RETREAD_LINE_NOT_FOUND"),
            (api.get_retread_job, "ERR_RETREAD_JOB_NOT_FOUND"),
            (api.get_technician, "ERR_TECHNICIAN_NOT_FOUND"),
            (api.get_road_service_call, "ERR_ROAD_SERVICE_CALL_NOT_FOUND"),
            (api.get_scrap_manifest, "ERR_SCRAP_MANIFEST_NOT_FOUND"),
            (api.get_cross_location_invoice, "ERR_INVOICE_NOT_FOUND"),
            (api.get_casing_credit_entry, "ERR_CREDIT_ENTRY_NOT_FOUND"),
        ]

        reported = []
        for index, (read, expected_error_id) in enumerate(reads, start=1):
            error = validate_error(
                read(missing.format(index), fixtures.ADMIN),
                expected_error_id,
                expected_status=404,
            )
            assert isinstance(error["message"], str) and error["message"], (
                f"{expected_error_id} carries a human-readable message"
            )
            reported.append(error["error_id"])

        assert len(set(reported)) == 14, (
            "no two collections collapse onto a shared generic not-found code"
        )


class TestSigningInspectorSegregation:
    def test_an_officer_may_not_sign_off_the_carcass_they_condemned(self, api):
        """PRD §3.7: "Second, segregation of duties: the signing officer's `X-User-ID`
        must differ from the `inspected_by_user_id` of **every** casing listed on the
        manifest, so that the person who graded a carcass into a credit accrual cannot
        also be the person who signs the paperwork that will write it off; a collision
        is rejected with `ERR_SOD_INSPECTOR_CANNOT_SIGN`."
        PRD §3.7: "A successful signature advances the manifest `DRAFT → SIGNED`,
        records `signed_by_user_id` from the acting officer and `signed_at` from the
        supplied instant, and increments the manifest's `version`."

        Design: Corner/errors/sign_manifest_by_the_inspecting_user_rejected
        """
        program = fixtures.setup_fleet_program(
            location_overrides={
                "name": "Sod Commercial",
                "location_code": "SDC",
                "scrap_permit_expires_on": "2027-06-30",
            }
        )
        fleet_id = program["fleet"]["id"]
        location_id = program["location"]["id"]

        casing_p = fixtures.create_condemned_casing(
            fleet_id,
            location_id,
            inspector_user_id=fixtures.DUAL_OFFICER_INSPECTOR_ID,
            casing_serial="CS-4033P",
            scrap_weight_lbs=130,
        )
        casing_q = fixtures.create_condemned_casing(
            fleet_id,
            location_id,
            inspector_user_id="inspector-2",
            casing_serial="CS-4033Q",
            scrap_weight_lbs=131,
        )
        dual_headers = fixtures.officer_headers(fixtures.DUAL_OFFICER_INSPECTOR_ID)
        manifest_one = validate_success(
            api.create_scrap_manifest(
                location_id,
                factories.scrap_manifest_payload(
                    hauler_permit_number="HP-4033A", hauler_capacity_lbs=1000
                ),
                dual_headers,
            ),
            expected_status=201,
        )
        manifest_two = validate_success(
            api.create_scrap_manifest(
                location_id,
                factories.scrap_manifest_payload(
                    hauler_permit_number="HP-4033B", hauler_capacity_lbs=1000
                ),
                dual_headers,
            ),
            expected_status=201,
        )
        fixtures.add_manifest_line(manifest_one["id"], casing_p["id"], dual_headers)
        fixtures.add_manifest_line(manifest_two["id"], casing_q["id"], dual_headers)

        validate_error(
            api.sign_scrap_manifest(
                manifest_one["id"],
                factories.sign_manifest_payload("2026-08-26T10:00:00Z"),
                dual_headers,
            ),
            "ERR_SOD_INSPECTOR_CANNOT_SIGN",
            expected_status=422,
        )
        blocked = fixtures.read_manifest(manifest_one["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked.get("signed_by_user_id") is None

        # The same user, on a load they did not grade, is a legitimate signer.
        signed_two = validate_success(
            api.sign_scrap_manifest(
                manifest_two["id"],
                factories.sign_manifest_payload("2026-08-26T10:05:00Z"),
                dual_headers,
            )
        )
        assert signed_two["status"] == "SIGNED", (
            "the rule compares identities per listed casing, not per user"
        )
        assert signed_two["signed_by_user_id"] == fixtures.DUAL_OFFICER_INSPECTOR_ID

        signed_one = validate_success(
            api.sign_scrap_manifest(
                manifest_one["id"],
                factories.sign_manifest_payload("2026-08-26T10:10:00Z"),
                fixtures.officer_headers(),
            )
        )
        assert signed_one["status"] == "SIGNED"
        assert signed_one["signed_by_user_id"] == "officer-signer"
        assert signed_one["signed_at"] == "2026-08-26T10:10:00Z"


class TestCertifyingSignerSegregation:
    def test_the_signer_may_not_also_certify_the_destruction(self, api):
        """PRD §3.7: "Segregation of duties applies again: the certifying officer's
        `X-User-ID` must differ from the manifest's `signed_by_user_id`, so that two
        distinct officers are structurally required per load; a collision is rejected
        with `ERR_SOD_SIGNER_CANNOT_CERTIFY`."
        PRD §3.7: "In hop 3, for each casing that reached `SCRAPPED` while carrying a
        non-zero `provisional_credit_cents`, an `EXPIRY` ledger entry is posted whose
        `amount_cents` is the negation of that casing's `provisional_credit_cents`,
        with `source_entity_type` of `SCRAP_MANIFEST` and `source_entity_id` naming
        this manifest — one entry per such casing."

        Design: Corner/errors/certify_destruction_by_the_signing_user_rejected
        """
        program = fixtures.setup_fleet_program(
            location_overrides={
                "name": "Certify Commercial",
                "location_code": "CFC",
            }
        )
        fleet_id = program["fleet"]["id"]
        casing = fixtures.create_condemned_casing(
            fleet_id,
            program["location"]["id"],
            casing_serial="CS-4034",
            scrap_weight_lbs=132,
        )
        assert casing["provisional_credit_cents"] == 0

        manifest = fixtures.create_manifest(
            program["location"]["id"],
            hauler_permit_number="HP-4034",
            hauler_capacity_lbs=1000,
        )
        fixtures.add_manifest_line(manifest["id"], casing["id"])
        fixtures.sign_manifest(manifest["id"], "2026-08-27T10:00:00Z")
        transported = fixtures.transport_manifest(
            manifest["id"], "2026-08-27T12:00:00Z"
        )
        assert transported["status"] == "TRANSPORTED", (
            "transport is not one of the two guarded hops"
        )

        validate_error(
            api.certify_scrap_manifest_destruction(
                manifest["id"],
                factories.certify_destruction_payload("2026-08-28T09:00:00Z"),
                fixtures.officer_headers(),
            ),
            "ERR_SOD_SIGNER_CANNOT_CERTIFY",
            expected_status=422,
        )
        blocked = fixtures.read_manifest(manifest["id"])
        assert blocked["status"] == "TRANSPORTED"
        assert blocked.get("certified_by_user_id") is None

        certified = validate_success(
            api.certify_scrap_manifest_destruction(
                manifest["id"],
                factories.certify_destruction_payload("2026-08-28T09:05:00Z"),
                fixtures.officer_headers("officer-certifier"),
            )
        )
        assert certified["status"] == "CERTIFIED_DESTROYED"
        assert certified["certified_by_user_id"] == "officer-certifier", (
            "three distinct identities are structurally required end to end"
        )
        assert certified["destruction_facility_code"] == "PROC-9"
        assert fixtures.read_casing(casing["id"])["status"] == "SCRAPPED"
        assert fixtures.list_ledger(fleet_id) == [], (
            "a condemned carcass carried no credit, so there is nothing to expire"
        )


class TestScrapPermitExpiry:
    def test_signing_is_blocked_the_day_after_the_permit_lapses(self, api):
        """PRD §3.7: "First the permit: the signing location's
        `scrap_permit_expires_on` must fall on or after the logical clock's UTC date —
        a permit lapsing today is still good today, and one that lapsed yesterday
        rejects the signature with `ERR_SCRAP_PERMIT_EXPIRED`."
        PRD §2.5: "An administrative capability sets the clock to an arbitrary instant
        supplied as `current_utc`, and its response echoes `current_utc` alongside
        `expired_agreement_ids`."

        Design: Corner/errors/sign_manifest_with_expired_scrap_permit_rejected
        """
        program = fixtures.setup_fleet_program(
            location_overrides={
                "name": "Permit Commercial",
                "location_code": "PMC",
                "scrap_permit_number": "OH-SCRAP-4035",
                "scrap_permit_expires_on": "2026-08-15",
            }
        )
        assert program["agreement"] is None, (
            "no agreement exists, so moving the clock expires nothing collaterally"
        )
        casing = fixtures.create_condemned_casing(
            program["fleet"]["id"],
            program["location"]["id"],
            casing_serial="CS-4035",
            scrap_weight_lbs=133,
        )
        manifest = fixtures.create_manifest(
            program["location"]["id"],
            hauler_permit_number="HP-4035",
            hauler_capacity_lbs=1000,
        )

        lapsed = fixtures.set_clock("2026-08-16T00:00:00Z")
        assert lapsed["expired_agreement_ids"] == []

        loaded = fixtures.add_manifest_line(manifest["id"], casing["id"])
        assert loaded["tire_count"] == 1, "the permit guards signing, not loading"

        validate_error(
            api.sign_scrap_manifest(
                manifest["id"],
                factories.sign_manifest_payload("2026-08-16T09:00:00Z"),
                fixtures.officer_headers(),
            ),
            "ERR_SCRAP_PERMIT_EXPIRED",
            expected_status=422,
        )
        assert fixtures.read_manifest(manifest["id"])["status"] == "DRAFT"

        still_good = fixtures.set_clock("2026-08-15T23:59:00Z")
        assert still_good["expired_agreement_ids"] == []

        signed = validate_success(
            api.sign_scrap_manifest(
                manifest["id"],
                factories.sign_manifest_payload("2026-08-15T23:59:00Z"),
                fixtures.officer_headers(),
            )
        )
        assert signed["status"] == "SIGNED", (
            "the comparison is on-or-after, so the expiry date itself is still good"
        )


class TestDispatchAvailabilityFamily:
    def test_the_three_dispatch_refusals_stay_distinguishable(self, api):
        """PRD §3.6: "A `technician_id` may be named explicitly, in which case that
        technician's `service_location_id` must equal the call's
        `service_location_id`, or the request is rejected with
        `ERR_TECHNICIAN_LOCATION_MISMATCH`, and that technician's `status` must be
        `AVAILABLE`, or the request is rejected with `ERR_TECHNICIAN_UNAVAILABLE`."
        PRD §3.6: "If the eligible pool is empty the dispatch is refused with
        `ERR_NO_TECHNICIAN_AVAILABLE` and the call remains `OPEN`, ready to be retried
        when someone frees up."

        Design: Corner/errors/dispatch_technician_availability_error_family
        """
        program = fixtures.setup_fleet_program(
            location_overrides={"name": "Dispatch A", "location_code": "DPA"}
        )
        location_b = fixtures.create_location(
            name="Dispatch B",
            location_code="DPB",
            state_code="IN",
            scrap_permit_number="IN-SCRAP-4036",
        )
        vehicle = fixtures.create_vehicle(
            program["fleet"]["id"], unit_number="T-126", current_odometer_miles=88000
        )
        technician_a = fixtures.create_technician(
            program["location"]["id"],
            name="Alpha Tech",
            certification_level="TIA_CERTIFIED",
        )
        technician_b = fixtures.create_technician(
            location_b["id"], name="Bravo Tech", certification_level="TIA_CERTIFIED"
        )
        fixtures.set_technician_off_duty(technician_a["id"])

        call = fixtures.open_call(
            program["fleet"]["id"],
            vehicle["id"],
            program["location"]["id"],
            "2026-08-29T09:00:00Z",
        )

        validate_error(
            api.dispatch_road_service_call(
                call["id"],
                factories.dispatch_payload(
                    "2026-08-29T09:10:00Z", 4, technician_id=technician_b["id"]
                ),
                fixtures.DISPATCHER,
            ),
            "ERR_TECHNICIAN_LOCATION_MISMATCH",
            expected_status=422,
        )
        assert fixtures.read_technician(technician_b["id"])["status"] == "AVAILABLE", (
            "the foreign technician was available; location outranks availability"
        )

        validate_error(
            api.dispatch_road_service_call(
                call["id"],
                factories.dispatch_payload(
                    "2026-08-29T09:15:00Z", 4, technician_id=technician_a["id"]
                ),
                fixtures.DISPATCHER,
            ),
            "ERR_TECHNICIAN_UNAVAILABLE",
            expected_status=409,
        )
        validate_error(
            api.dispatch_road_service_call(
                call["id"],
                factories.dispatch_payload("2026-08-29T09:20:00Z", 4),
                fixtures.DISPATCHER,
            ),
            "ERR_NO_TECHNICIAN_AVAILABLE",
            expected_status=409,
        )

        still_open = fixtures.read_call(call["id"])
        assert still_open["dispatch_status"] == "OPEN", (
            "three refusals in a row left the call exactly as it was, retryable"
        )
        assert still_open.get("technician_id") is None

        fixtures.set_technician_available(technician_a["id"])
        dispatched = validate_success(
            api.dispatch_road_service_call(
                call["id"],
                factories.dispatch_payload("2026-08-29T09:30:00Z", 4),
                fixtures.DISPATCHER,
            )
        )
        assert dispatched["dispatch_status"] == "DISPATCHED"
        assert dispatched["technician_id"] == technician_a["id"], (
            "the refusal left the call retryable the moment the roster freed up"
        )


class TestInvoiceFiscalPreconditions:
    def test_the_same_request_reports_three_fiscal_failures_in_ladder_order(self, api):
        """PRD §3.8: "The billing period is a closed date interval:
        `billing_period_end` must fall on or after `billing_period_start`, and the
        inclusive span must be no longer than 92 days — roughly a calendar quarter —
        with anything else rejected as `ERR_INVALID_BILLING_PERIOD`."
        PRD §3.8: "The pricing agreement is resolved as the fleet's `ACTIVE` national
        agreement whose closed window covers `billing_period_start`, and its identifier
        is stored on the invoice as `national_agreement_id`; when no such agreement
        exists the creation is refused with `ERR_NO_ACTIVE_AGREEMENT`."
        PRD §3.8: "When that resolution yields nothing, the creation is refused with
        `ERR_NO_BILLABLE_LINES` rather than producing a zero invoice."

        Design: Corner/errors/invoice_creation_fiscal_precondition_error_family
        """
        program = fixtures.setup_fleet_program(
            location_overrides={"name": "Fiscal Commercial", "location_code": "FSC"},
            fleet_overrides={
                "name": "Fiscal Freight",
                "account_type": "NATIONAL_ACCOUNT",
                "billing_mode": "CROSS_LOCATION",
            },
        )
        fleet_id = program["fleet"]["id"]
        agreement = fixtures.create_agreement(
            fleet_id,
            activate=False,
            agreement_code="FSC-2026",
            tier_discount_pct=0.15,
            casing_credit_rate_cents=16000,
            emergency_response_minutes=75,
            emergency_labor_rate_cents_per_hour=14000,
        )
        assert agreement["status"] == "DRAFT"
        fleet_version = fixtures.read_fleet(fleet_id, fixtures.CLERK)["version"]

        validate_error(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id, "2026-08-01", "2026-11-02", fleet_version
                ),
                fixtures.CLERK,
            ),
            "ERR_INVALID_BILLING_PERIOD",
            expected_status=422,
        )
        validate_error(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id, "2026-08-31", "2026-08-01", fleet_version
                ),
                fixtures.CLERK,
            ),
            "ERR_INVALID_BILLING_PERIOD",
            expected_status=422,
        )
        validate_error(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id, "2026-08-01", "2026-08-31", fleet_version
                ),
                fixtures.CLERK,
            ),
            "ERR_NO_ACTIVE_AGREEMENT",
            expected_status=422,
        )

        activated = validate_success(
            api.activate_national_agreement(agreement["id"], {}, fixtures.ADMIN)
        )
        assert activated["status"] == "ACTIVE"

        validate_error(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id,
                    "2026-08-01",
                    "2026-08-31",
                    fixtures.read_fleet(fleet_id, fixtures.CLERK)["version"],
                ),
                fixtures.CLERK,
            ),
            "ERR_NO_BILLABLE_LINES",
            expected_status=422,
        )

        assert fixtures.count_invoices(fleet_id) == 0, (
            "four refusals in a row created nothing, not even a zero invoice"
        )


class TestRetreadJobReferentialLadder:
    def test_the_missing_policy_and_the_exhausted_casing_each_outrank_the_bad_slot(
        self, api
    ):
        """PRD §3.4: "Grading requires a tire policy for the casing's fleet and
        `intended_position`, otherwise `ERR_TIRE_POLICY_MISSING`."
        PRD §3.5: "The casing's `retread_count` must be **strictly less than** that
        policy's `max_retread_count`; a carcass whose count already equals or exceeds
        the cap has no retread capacity left and is rejected with
        `ERR_MAX_RETREAD_COUNT_REACHED`."
        PRD §2.11: "This ordering is normative: a request that violates rules at
        positions 9 and 31 reports the position-9 error."

        Design: Corner/errors/retread_job_creation_referential_error_family
        """
        location = fixtures.create_location(
            name="Refer Plant",
            location_code="RFP",
            scrap_permit_number="OH-SCRAP-4038",
            is_retread_plant=True,
        )
        line = fixtures.create_retread_line(location["id"], line_code="LF")
        fleet = fixtures.create_fleet(location["id"], name="Refer Freight")
        collected = fixtures.create_collected_casing(
            fleet["id"],
            location["id"],
            casing_serial="CS-4038",
            scrap_weight_lbs=134,
            retread_count=3,
        )

        # No policy for the casing's fleet and intended_position yet, so the act
        # that would make the carcass retreadable at all is refused first.
        validate_error(
            api.inspect_casing(
                collected["id"],
                factories.inspect_casing_payload("B", collected["version"]),
                fixtures.inspector_headers(),
            ),
            "ERR_TIRE_POLICY_MISSING",
            expected_status=422,
        )

        fixtures.create_policy(fleet["id"], position="DRIVE", max_retread_count=3)
        casing = fixtures.inspect_casing(collected["id"], "B", collected["version"])

        short_slot = factories.retread_job_payload(
            casing["id"],
            line["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T08:20:00Z",
            tread_design_code="TD-DRIVE-1",
        )
        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    casing["id"],
                    line["id"],
                    "2026-09-01T08:00:00Z",
                    "2026-09-01T12:00:00Z",
                    tread_design_code="TD-DRIVE-1",
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_MAX_RETREAD_COUNT_REACHED",
            expected_status=422,
        )
        validate_error(
            api.create_retread_job(short_slot, fixtures.SCHEDULER),
            "ERR_MAX_RETREAD_COUNT_REACHED",
            expected_status=422,
        )

        untouched = fixtures.read_line(line["id"])
        assert untouched["booked_minutes"] == 0
        assert untouched["status"] == "AVAILABLE"
        assert fixtures.count_jobs_for_casing(casing["id"]) == 0
        assert fixtures.read_casing(casing["id"])["status"] == "INSPECTED"


class TestManifestEligibilityAndEmptiness:
    def test_the_two_gates_bracket_the_only_path_to_a_signed_manifest(self, api):
        """PRD §3.7: "The casing's `status` must be `REJECTED`, because only a
        condemned carcass is scrap; anything else is rejected with
        `ERR_CASING_NOT_SCRAP_ELIGIBLE`."
        PRD §3.7: "Fourth, the manifest must not be empty — `tire_count` must be at
        least 1, and a manifest with nothing on it is rejected with
        `ERR_MANIFEST_EMPTY`."

        Design: Corner/errors/manifest_eligibility_and_emptiness_error_family
        """
        program = fixtures.setup_fleet_program(
            location_overrides={
                "name": "Eligible Commercial",
                "location_code": "ELC",
            },
            with_policy=False,
        )
        casing = fixtures.create_collected_casing(
            program["fleet"]["id"],
            program["location"]["id"],
            casing_serial="CS-4039",
            scrap_weight_lbs=135,
        )
        manifest = fixtures.create_manifest(
            program["location"]["id"],
            hauler_permit_number="HP-4039",
            hauler_capacity_lbs=1000,
        )

        validate_error(
            api.sign_scrap_manifest(
                manifest["id"],
                factories.sign_manifest_payload("2026-08-30T09:00:00Z"),
                fixtures.officer_headers(),
            ),
            "ERR_MANIFEST_EMPTY",
            expected_status=422,
        )
        validate_error(
            api.add_scrap_manifest_line(
                manifest["id"],
                factories.manifest_line_payload(casing["id"]),
                fixtures.officer_headers(),
            ),
            "ERR_CASING_NOT_SCRAP_ELIGIBLE",
            expected_status=422,
        )

        unchanged = fixtures.read_manifest(manifest["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["tire_count"] == 0
        assert unchanged["total_weight_lbs"] == 0

        held = fixtures.read_casing(casing["id"])
        assert held["status"] == "COLLECTED", (
            "the load cannot be reordered around either gate"
        )
        assert held.get("scrap_manifest_id") is None

        rows, meta = validate_paginated(
            api.list_scrap_manifests(
                fixtures.OFFICER,
                params={"service_location_id": program["location"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "DRAFT"
