"""Resource creation, retrieval, defaults and request-shape validation."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    CombinedCapGroup,
    MeasureCategory,
    ProgramStatus,
    REVIEWER_HEADERS,
    add_catalog_item,
    assert_append_only_record,
    assert_fields,
    assert_full_audit_fields,
    assert_pagination_meta,
    build_assessment_payload,
    build_contractor_payload,
    build_enrollment_decision_payload,
    build_household_payload,
    build_income_verification_payload,
    build_inspector_payload,
    build_program_payload,
    build_verify_decision_payload,
    create_draft_program,
    create_household,
    create_open_program,
    household_version,
    is_valid_uuid,
    make_applicant_headers,
    make_contractor_headers,
    open_program,
    validate_error,
    validate_paginated,
    validate_success,
)

HP_HVAC = {
    "measure_code": "HP-HVAC-01",
    "measure_name": "Ducted air-source heat pump",
    "category": MeasureCategory.HVAC,
    "unit_incentive_cents": 800000,
    "measure_cap_cents": 800000,
    "combined_cap_group": CombinedCapGroup.HVAC_GROUP,
    "sort_order": 10,
    "required_panel_capacity_amps": 200,
    "qualifies_as_appliance_anchor": True,
}
WH_HPWH = {
    "measure_code": "WH-HPWH-01",
    "measure_name": "Heat-pump water heater",
    "category": MeasureCategory.WATER_HEATING,
    "unit_incentive_cents": 175000,
    "measure_cap_cents": 175000,
    "combined_cap_group": CombinedCapGroup.WATER_GROUP,
    "sort_order": 20,
    "required_panel_capacity_amps": 150,
    "qualifies_as_appliance_anchor": True,
}
EN_INSUL = {
    "measure_code": "EN-INSUL-01",
    "measure_name": "Attic insulation and air sealing",
    "category": MeasureCategory.ENVELOPE,
    "unit_incentive_cents": 160000,
    "measure_cap_cents": 160000,
    "combined_cap_group": CombinedCapGroup.NONE,
    "sort_order": 30,
}


class TestProgramAndHouseholdRecords:
    def test_program_creation_reports_draft_status_and_full_budget_availability(self, api):
        """A program created from its three required inputs is born in DRAFT.

        PRD §3.1: "A `ProgramAdmin` opens the season by creating a program, which
        is born in `DRAFT`." and "At creation the program's
        `budget_available_cents` is set equal to `budget_total_cents`, and
        `budget_reserved_cents`, `budget_committed_cents`, and
        `budget_clawed_back_cents` all start at 0."

        Design: Corner/entities/program_creation_returns_declared_fields_and_draft_status
        """
        response = api.create_program(
            build_program_payload(name="HEEHRA 2026 Base"), ADMIN_HEADERS
        )
        created = validate_success(response, 201)

        assert_full_audit_fields(created, "Program")
        assert created["version"] == 1, "A freshly created program must be at version 1"
        assert_fields(
            created,
            "Program",
            status=ProgramStatus.DRAFT,
            name="HEEHRA 2026 Base",
            state_code="CO",
            budget_total_cents=50000000,
            budget_available_cents=50000000,
            budget_reserved_cents=0,
            budget_committed_cents=0,
            budget_clawed_back_cents=0,
        )

        fetched = validate_success(api.get_program(created["id"], ADMIN_HEADERS))
        for field in (
            "status",
            "name",
            "state_code",
            "budget_total_cents",
            "budget_available_cents",
            "budget_reserved_cents",
            "budget_committed_cents",
            "budget_clawed_back_cents",
            "version",
        ):
            assert fetched[field] == created[field], (
                f"Program.{field} read back as {fetched[field]!r} but was created as "
                f"{created[field]!r}"
            )

    def test_household_read_reports_stored_inputs_with_no_entitlement_yet(self, api):
        """Intake stores the dwelling's inputs and assigns no entitlement.

        PRD §3.2: "At intake the household's `ami_percent` and `income_tier` are
        both null, and `rebate_cap_cents`, `lifetime_cap_remaining_cents`, and
        `encumbered_cents` are all 0; nothing is assigned until a verification is
        decided."

        Design: Corner/entities/household_retrieval_returns_stored_values_and_unassigned_tier_fields
        """
        program = create_open_program(api, name="HEEHRA 2026 Retrieval")
        household = create_household(
            api,
            program["id"],
            applicant_name="Ana Reyes",
            email="ana@example.com",
            service_address_line1="9 Aspen Ct",
            county_code="CO-031",
            utility_territory_code="XCEL-CO",
            household_size=4,
            existing_panel_amps=200,
        )

        headers = make_applicant_headers(household["id"])
        read = validate_success(api.get_household(household["id"], headers))

        assert_fields(
            read,
            "Household",
            program_id=program["id"],
            applicant_name="Ana Reyes",
            email="ana@example.com",
            service_address_line1="9 Aspen Ct",
            county_code="CO-031",
            utility_territory_code="XCEL-CO",
            household_size=4,
            existing_panel_amps=200,
            ami_percent=None,
            income_tier=None,
            rebate_cap_cents=0,
            lifetime_cap_remaining_cents=0,
            encumbered_cents=0,
        )
        assert read["version"] == 1, "A freshly registered household must be at version 1"

        again = validate_success(api.get_household(household["id"], headers))
        assert again["version"] == 1, (
            "A read is not a mutation, so the household version must stay at 1"
        )

    def test_computed_tier_fields_ignore_client_input_and_are_written_only_by_verification(
        self, api
    ):
        """Tier, AMI percent and cap are assigned by the verification decision alone.

        PRD §3.2: "At intake the household's `ami_percent` and `income_tier` are
        both null, and `rebate_cap_cents`, `lifetime_cap_remaining_cents`, and
        `encumbered_cents` are all 0; nothing is assigned until a verification is
        decided."

        Design: Corner/entities/household_computed_tier_fields_client_input_ignored
        """
        program = create_open_program(api, name="HEEHRA 2026 Computed")
        payload = build_household_payload(
            program["id"],
            applicant_name="Cai Nkemi",
            email="cai@example.com",
            service_address_line1="7 Cedar Ln",
            income_tier="LOW",
            ami_percent=12.3,
            rebate_cap_cents=9999999,
            lifetime_cap_remaining_cents=9999999,
        )
        household = validate_success(api.create_household(payload, ADMIN_HEADERS), 201)

        assert_fields(
            household,
            "Household",
            income_tier=None,
            ami_percent=None,
            rebate_cap_cents=0,
            lifetime_cap_remaining_cents=0,
        )

        applicant = make_applicant_headers(household["id"])
        verification = validate_success(
            api.create_income_verification(
                household["id"],
                build_income_verification_payload(document_reference=None),
                applicant,
            ),
            201,
        )
        decided = validate_success(
            api.verify_income_verification(
                verification["id"], {"decision": "VERIFY"}, REVIEWER_HEADERS
            )
        )
        assert_fields(
            decided,
            "IncomeVerification",
            computed_ami_percent=80.0,
            assigned_income_tier="LOW",
            assigned_cap_cents=1400000,
        )

        after = validate_success(api.get_household(household["id"], applicant))
        assert_fields(
            after,
            "Household",
            ami_percent=80.0,
            income_tier="LOW",
            rebate_cap_cents=1400000,
            lifetime_cap_remaining_cents=1400000,
            encumbered_cents=0,
        )
        assert after["version"] == 2, (
            "Exactly one write — the verification decision — should reach the household, "
            f"so version should be 2, got {after['version']}"
        )

    def test_system_managed_fields_are_server_generated_and_body_values_discarded(self, api):
        """Status, version and the actor stamps come from the server, not the body.

        PRD §2.1: "the server records it where a transition writes it — as
        `verified_by_user_id` on an income verification, `enrollment_decided_by_user_id`
        on a contractor, `approved_by_user_id` on an assessment, `reviewed_by_user_id`
        on a rebate project, `scheduled_by_user_id` on an inspection, and
        `recorded_by_user_id` on a clawback action — but never compares it to any
        entity's `id`."

        Design: Corner/entities/system_fields_generated_and_status_input_ignored
        """
        payload = build_program_payload(
            name="HEEHRA 2026 System", status="OPEN", version=99, budget_available_cents=1
        )
        program = validate_success(api.create_program(payload, ADMIN_HEADERS), 201)

        assert_fields(
            program,
            "Program",
            status=ProgramStatus.DRAFT,
            version=1,
            budget_available_cents=50000000,
        )
        assert is_valid_uuid(program["id"]), "The program id must be a server-minted UUID"

        opened = open_program(api, program["id"])
        assert opened["version"] == 2, (
            "The status transition is what advances the version, so it should read 2, "
            f"got {opened['version']}"
        )

        household = create_household(
            api,
            program["id"],
            applicant_name="Dev Rao",
            email="dev@example.com",
            service_address_line1="4 Dogwood Dr",
        )
        applicant = make_applicant_headers(household["id"])
        filed = validate_success(
            api.create_income_verification(
                household["id"],
                build_income_verification_payload(
                    document_reference=None, verified_by_user_id="reviewer-9"
                ),
                applicant,
            ),
            201,
        )
        assert filed["submitted_by_user_id"] == household["id"], (
            "submitted_by_user_id must be stamped from the filing Applicant's X-User-ID"
        )
        assert filed["verified_by_user_id"] is None, (
            "The body's verified_by_user_id must be discarded on filing"
        )

        verified = validate_success(
            api.verify_income_verification(
                filed["id"], build_verify_decision_payload(), REVIEWER_HEADERS
            )
        )
        assert verified["verified_by_user_id"] == "reviewer-1", (
            "verified_by_user_id must carry the deciding reviewer's X-User-ID, got "
            f"{verified['verified_by_user_id']!r}"
        )
        assert verified["verified_at"] is not None, "verified_at must be stamped on VERIFY"


class TestDeclaredDefaults:
    def test_program_and_catalog_defaults_apply_when_optional_inputs_are_omitted(self, api):
        """Every documented default lands when its input is left out.

        PRD §3.1: "the funding year `program_year` defaults to 2026;
        `reservation_ttl_days` defaults to 120; `extension_window_days` to 30;
        `max_extension_days` to 60; `max_extensions_per_reservation` to 1; the
        lifetime caps `low_tier_cap_cents`, `moderate_tier_cap_cents`, and
        `standard_tier_cap_cents` to 1400000, 800000, and 300000 cents
        respectively; the cost-share fractions `low_tier_cost_share_pct`,
        `moderate_tier_cost_share_pct`, and `standard_tier_cost_share_pct` to
        1.00, 0.50, and 0.30; the tier boundaries `ami_low_threshold_pct` and
        `ami_moderate_threshold_pct` to 80.0 and 150.0 percent;
        `group_cap_cents` to 800000; `panel_upgrade_cap_cents` to 400000;
        `federal_credit_pct` to 0.30 and `federal_credit_cap_cents` to 200000;
        `max_combined_benefit_pct` to 1.00; `max_remediations_per_project` to 1;
        `quality_suspension_threshold` to 70; and `recertification_threshold` to
        75."

        Design: Corner/entities/program_and_catalog_defaults_applied_when_optional_inputs_omitted
        """
        program = validate_success(
            api.create_program(build_program_payload(name="HEEHRA 2026 Defaults"), ADMIN_HEADERS),
            201,
        )

        assert_fields(
            program,
            "Program",
            program_year=2026,
            reservation_ttl_days=120,
            extension_window_days=30,
            max_extension_days=60,
            max_extensions_per_reservation=1,
            low_tier_cap_cents=1400000,
            moderate_tier_cap_cents=800000,
            standard_tier_cap_cents=300000,
            group_cap_cents=800000,
            panel_upgrade_cap_cents=400000,
            federal_credit_cap_cents=200000,
            max_remediations_per_project=1,
            quality_suspension_threshold=70,
            recertification_threshold=75,
        )
        assert program["low_tier_cost_share_pct"] == pytest.approx(1.00, abs=0.01)
        assert program["moderate_tier_cost_share_pct"] == pytest.approx(0.50, abs=0.01)
        assert program["standard_tier_cost_share_pct"] == pytest.approx(0.30, abs=0.01)
        assert program["ami_low_threshold_pct"] == pytest.approx(80.0, abs=0.01)
        assert program["ami_moderate_threshold_pct"] == pytest.approx(150.0, abs=0.01)
        assert program["federal_credit_pct"] == pytest.approx(0.30, abs=0.01)
        assert program["max_combined_benefit_pct"] == pytest.approx(1.00, abs=0.01)

        item = add_catalog_item(api, program["id"], dict(EN_INSUL))
        assert_fields(
            item,
            "MeasureCatalogItem",
            max_quantity=1,
            required_panel_capacity_amps=0,
            upgraded_capacity_amps=0,
            is_panel_upgrade=False,
            requires_qualifying_appliance=False,
            qualifies_as_appliance_anchor=False,
            standard_tier_eligible=False,
            active=True,
        )


class TestCatalogListing:
    def test_catalog_listing_paginates_and_filters_with_a_filtered_total_count(self, api):
        """Pagination and the category filter both report the filtered count.

        PRD §2.3: "`limit` caps the number of records returned; when omitted it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted
        value is 100. `offset` is the number of records to skip; when omitted it
        defaults to 0 and its minimum accepted value is 0."

        Design: Corner/entities/catalog_listing_paginates_and_filters_by_category
        """
        program = create_draft_program(api, name="HEEHRA 2026 Catalog")
        for payload in (HP_HVAC, WH_HPWH, EN_INSUL):
            add_catalog_item(api, program["id"], dict(payload))

        first, meta = validate_paginated(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(first) == 2, f"limit 2 should return 2 items, got {len(first)}"
        assert_pagination_meta(meta, total_count=3, limit=2, offset=0, has_more=True)

        second, meta = validate_paginated(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(second) == 1, f"offset 2 should return the remaining item, got {len(second)}"
        assert_pagination_meta(meta, total_count=3, has_more=False)

        filtered, meta = validate_paginated(
            api.list_catalog_items(
                program["id"], REVIEWER_HEADERS, {"category": MeasureCategory.WATER_HEATING}
            )
        )
        assert len(filtered) == 1, "Only one catalog item is in WATER_HEATING"
        assert filtered[0]["measure_code"] == "WH-HPWH-01"
        assert_pagination_meta(meta, total_count=1, has_more=False)

        everything, meta = validate_paginated(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS)
        )
        assert len(everything) == 3, "Omitting pagination should return all three items"
        assert_pagination_meta(meta, total_count=3, limit=10, offset=0, has_more=False)


class TestRequestShapeAndExistence:
    def test_unknown_program_id_is_a_not_found_error_envelope(self, api):
        """A valid but unknown path identifier is a rung-5 existence failure.

        PRD §2.10 rung 5: "**Path entities exist,** resolved strictly left to
        right along the path. The error names the leftmost missing segment, drawn
        from `ERR_PROGRAM_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`,
        `ERR_CONTRACTOR_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_INCOME_VERIFICATION_NOT_FOUND`,
        `ERR_PROJECT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, and `ERR_CLAWBACK_ACTION_NOT_FOUND`, each
        404."

        Design: Corner/entities/unknown_program_id_not_found
        """
        decoy = create_draft_program(api, name="HEEHRA 2026 Decoy")

        response = api.get_program(NON_EXISTENT_UUID, ADMIN_HEADERS)
        error = validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404)
        assert error["message"].strip(), "The error envelope must carry a message"

        still_there = validate_success(api.get_program(decoy["id"], ADMIN_HEADERS))
        assert still_there["id"] == decoy["id"], "The unrelated program must be untouched"

    @pytest.mark.parametrize("omitted_field", ["household_size", "existing_panel_amps"])
    def test_household_create_rejects_a_missing_required_input(self, api, omitted_field):
        """Each mandatory intake input is enforced at the request-shape rung.

        PRD §2.10 rung 3: "**Request shape.** The body or query parses; required
        fields are present; types and enumerated values are valid; numeric ranges
        are respected; a date or datetime range is ordered so that the end is not
        earlier than the start → otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/household_create_missing_required_field_rejected
        """
        program = create_open_program(api, name="HEEHRA 2026 Required")
        payload = build_household_payload(
            program["id"],
            applicant_name="Bea Cruz",
            email="bea@example.com",
            service_address_line1="1 Birch Rd",
            existing_panel_amps=100,
        )
        payload.pop(omitted_field)

        response = api.create_household(payload, ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        rows, meta = validate_paginated(
            api.list_program_households(program["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0, (
            f"A rejected intake must create no household row, found {rows}"
        )

    def test_enum_and_numeric_range_violations_are_rejected_before_any_lookup(self, api):
        """Out-of-enum values and below-range integers all fail the same rung.

        PRD §2.10 rung 3: "**Request shape.** The body or query parses; required
        fields are present; types and enumerated values are valid; numeric ranges
        are respected; a date or datetime range is ordered so that the end is not
        earlier than the start → otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/enum_and_numeric_range_constraints_rejected
        """
        program = create_open_program(api, name="HEEHRA 2026 Types")

        bad_category = dict(EN_INSUL)
        bad_category.update(
            {"measure_code": "PV-SOLAR-01", "measure_name": "Rooftop solar", "category": "SOLAR"}
        )
        validate_error(
            api.create_catalog_item(program["id"], bad_category, ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        negative_money = dict(EN_INSUL)
        negative_money["unit_incentive_cents"] = -1
        validate_error(
            api.create_catalog_item(program["id"], negative_money, ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        validate_error(
            api.create_household(
                build_household_payload(
                    program["id"],
                    applicant_name="Eli Park",
                    email="eli@example.com",
                    service_address_line1="2 Elm St",
                    household_size=0,
                    existing_panel_amps=100,
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        validate_error(
            api.set_program_status(program["id"], {"new_status": "PAUSED"}, ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        _items, item_meta = validate_paginated(
            api.list_catalog_items(program["id"], REVIEWER_HEADERS)
        )
        assert item_meta["total_count"] == 0, "No catalog item may survive a rung-3 rejection"
        _households, hh_meta = validate_paginated(
            api.list_program_households(program["id"], ADMIN_HEADERS)
        )
        assert hh_meta["total_count"] == 0, "No household may survive a rung-3 rejection"

        after = validate_success(api.get_program(program["id"], ADMIN_HEADERS))
        assert after["status"] == ProgramStatus.OPEN, "The rejected transition must not apply"
        assert after["version"] == 2, (
            "Only the accepted DRAFT -> OPEN transition should have advanced the version, "
            f"got {after['version']}"
        )

    def test_parent_program_is_validated_from_the_path_and_from_the_body(self, api):
        """An unknown parent is a 404 whether it arrives in the path or the body.

        PRD §2.10 rung 6: "**Body-referenced entities exist and belong to the
        same program.** This covers `program_id`, `household_id`,
        `contractor_id`, `inspector_id`, `assessment_id`,
        `income_verification_id`, `project_id`, and every `measure_code` that
        must resolve to a catalog item of that program."

        Design: Corner/entities/catalog_item_requires_existing_parent_program
        """
        program = create_draft_program(api, name="HEEHRA 2026 Parent")

        validate_error(
            api.create_catalog_item(NON_EXISTENT_UUID, dict(HP_HVAC), ADMIN_HEADERS),
            ApiErrorId.ERR_PROGRAM_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_household(
                build_household_payload(
                    NON_EXISTENT_UUID,
                    applicant_name="Gil Amara",
                    email="gil@example.com",
                    service_address_line1="6 Fir Ave",
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_PROGRAM_NOT_FOUND,
            404,
        )

        accepted = validate_success(
            api.create_household(
                build_household_payload(
                    program["id"],
                    applicant_name="Gil Amara",
                    email="gil@example.com",
                    service_address_line1="6 Fir Ave",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert accepted["program_id"] == program["id"]

        _items, meta = validate_paginated(api.list_catalog_items(program["id"], REVIEWER_HEADERS))
        assert meta["total_count"] == 0, (
            "The rejected catalog item must not have been attached to the real program"
        )

    def test_body_reference_belonging_to_another_program_is_treated_as_absent(self, api):
        """A contractor enrolled under a different program is not found at all.

        PRD §2.10 rung 6: "**Body-referenced entities exist and belong to the
        same program.** This covers `program_id`, `household_id`,
        `contractor_id`, `inspector_id`, `assessment_id`,
        `income_verification_id`, `project_id`, and every `measure_code` that
        must resolve to a catalog item of that program."

        Design: Corner/entities/cross_program_body_reference_rejected
        """
        program_a = create_open_program(api, name="HEEHRA 2026 Program A")
        add_catalog_item(api, program_a["id"], dict(HP_HVAC))
        program_b = create_open_program(api, name="HEEHRA 2026 Program B", state_code="NM")

        household = create_household(
            api,
            program_a["id"],
            applicant_name="Hana Ito",
            email="hana@example.com",
            service_address_line1="3 Hazel St",
        )
        applicant = make_applicant_headers(household["id"])
        verification = validate_success(
            api.create_income_verification(
                household["id"],
                build_income_verification_payload(document_reference=None),
                applicant,
            ),
            201,
        )
        validate_success(
            api.verify_income_verification(
                verification["id"], {"decision": "VERIFY"}, REVIEWER_HEADERS
            )
        )

        contractor_a = validate_success(
            api.create_contractor(
                build_contractor_payload(
                    program_a["id"], business_name="Program A Mechanical", license_number="MC-2001"
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        validate_success(
            api.decide_contractor_enrollment(
                contractor_a["id"], build_enrollment_decision_payload(), REVIEWER_HEADERS
            )
        )
        contractor_b = validate_success(
            api.create_contractor(
                build_contractor_payload(
                    program_b["id"], business_name="Program B Mechanical", license_number="MC-2002"
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        version = household_version(api, household["id"])
        measures = [
            {"measure_code": "HP-HVAC-01", "proposed_quantity": 1, "estimated_cost_cents": 1000000}
        ]

        foreign = api.create_assessment(
            build_assessment_payload(
                household["id"],
                contractor_b["id"],
                version,
                measures,
                assessed_panel_amps=200,
                assessment_notes=None,
            ),
            ADMIN_HEADERS,
        )
        validate_error(foreign, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND, 404)

        accepted = validate_success(
            api.create_assessment(
                build_assessment_payload(
                    household["id"],
                    contractor_a["id"],
                    version,
                    measures,
                    assessed_panel_amps=200,
                    assessment_notes=None,
                ),
                make_contractor_headers(contractor_a["id"]),
            ),
            201,
        )
        assert_fields(
            accepted,
            "Assessment",
            status="PENDING_REVIEW",
            qualified_measure_count=1,
            effective_panel_amps=200,
        )

        rows, meta = validate_paginated(
            api.list_assessments(REVIEWER_HEADERS, {"household_id": household["id"]})
        )
        assert meta["total_count"] == 1, (
            f"Only the accepted assessment may exist, found {len(rows)}"
        )


class TestAppendOnlyRecords:
    def test_inspector_record_carries_no_version_and_no_updated_at(self, api):
        """An inspector is an append-only row with no update path.

        PRD §2.4: "Three record types are append-only audit rows and carry only
        `id` and `created_at` — they have **no** `updated_at` and **no**
        `version` field at all: `Inspector`, `EligibleMeasure`, and
        `ClawbackAction`."

        Design: Corner/entities/inspector_is_immutable_with_no_version_field
        """
        program = create_draft_program(api, name="HEEHRA 2026 Immutable")

        created = validate_success(
            api.create_inspector(
                build_inspector_payload(
                    program["id"],
                    inspector_name="Fern Oyelaran",
                    certification_id="INS-11",
                    certification_expires_on="2027-12-31",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_append_only_record(created, "Inspector")

        read = validate_success(api.get_inspector(created["id"], ADMIN_HEADERS))
        assert_append_only_record(read, "Inspector")
        assert_fields(
            read,
            "Inspector",
            inspector_name="Fern Oyelaran",
            certification_id="INS-11",
            certification_expires_on="2027-12-31",
        )

        _rows, meta = validate_paginated(
            api.list_program_inspectors(program["id"], REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 1, "The program should list its single inspector"
