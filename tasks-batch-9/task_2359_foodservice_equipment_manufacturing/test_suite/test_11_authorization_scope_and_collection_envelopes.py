"""Authentication, role screening, ownership scope, two-person control and list envelopes."""

from test_helpers import (
    ApiErrorId,
    agency_decision_payload,
    certification_listing_payload,
    construction_program_payload,
    create_build_line,
    create_chain_account,
    create_chain_configuration,
    create_connected_unit,
    create_equipment_model,
    create_firmware_campaign,
    create_construction_program,
    create_service_partner,
    enrol_technician,
    equipment_model_payload,
    file_certification_listing,
    make_compliance_engineer_headers,
    make_headers,
    make_chain_admin_headers,
    make_listing_reviewer_headers,
    make_service_partner_headers,
    open_performance_validation,
    read_equipment_model,
    read_technician_certification,
    set_clock,
    setup_listed_model,
    technician_certification_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The five well-formed identifiers below name no row in an empty database.
UNKNOWN_MODEL_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_LISTING_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_LINE_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_PARTNER_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_CLAIM_ID = "00000000-0000-4000-8000-000000000005"

DIAL_ONLY = {"supported_controls_packages": ["STANDARD_DIAL"]}
PLAIN_CONFIG = {
    "option_codes": [],
    "controls_package": "STANDARD_DIAL",
    "branding_kit": "NONE",
}


def _page(response, expected_total):
    """Read a list response and assert its filtered total_count."""
    data, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"the filtered collection should hold {expected_total} rows, got "
        f"{meta['total_count']}"
    )
    return data, meta


class TestRoleScreeningPrecedesPayloadValidation:
    def test_an_unlisted_role_is_refused_before_the_invalid_enum_is_seen(
        self, api, compliance_engineer, production_planner
    ):
        """A ProductionPlanner posting an invalid category gets 403, not ERR_INVALID_REQUEST.

        PRD §2.9: "Beyond path resolution, the checks a request undergoes are strictly
        ordered, and the first failing check determines the response. Two checks that would
        both fail must produce the earlier one's error, which is why the ordering below is
        normative rather than descriptive:"

        PRD §2.1: "A recognised role that does not appear in the called endpoint's
        authorised-role list (see §4) is rejected with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/a_role_outside_the_endpoints_list_is_refused_before_any_payload_check
        """
        set_clock()

        refused = api.create_equipment_model(
            equipment_model_payload(category="SALAMANDER", **DIAL_ONLY),
            production_planner,
        )
        validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert (
            refused.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        ), (
            "role screening at check 2 runs before payload well-formedness at check 5, so "
            "the bogus category must never surface as ERR_INVALID_REQUEST"
        )

        created = validate_success(
            api.create_equipment_model(
                equipment_model_payload(**DIAL_ONLY), compliance_engineer
            ),
            201,
        )
        assert created["category"] == "FRYER", (
            f"the authorised create stores the supplied category, got {created['category']}"
        )

        data, _meta = _page(
            api.list_equipment_models(compliance_engineer, {"limit": 100}), 1
        )
        assert [row["id"] for row in data] == [created["id"]], (
            "the refused attempt left no catalogue row behind, so only the authorised "
            f"model is listed, got {[row['id'] for row in data]}"
        )


class TestAuthenticationPrecedesRoleScreening:
    def test_missing_and_unknown_role_headers_are_both_unauthenticated(self, api):
        """A header-less call and a `FactoryIntern` call both answer 401, never 403.

        PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
        principal, and `X-User-Role`, declaring the capacity it is acting in. A request
        missing either header, or naming a role the system does not recognise, is rejected
        with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_or_unknown_role_header_is_unauthenticated_not_forbidden
        """
        set_clock()

        headerless = api.raw_request("GET", "/equipment-models", None, {})
        validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        role_only = api.raw_request(
            "GET", "/equipment-models", None, {"X-User-Role": "ComplianceEngineer"}
        )
        validate_error(role_only, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        unknown_role = api.list_equipment_models(
            make_headers("intern-1", "FactoryIntern")
        )
        validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert (
            unknown_role.json()["data"]["error_id"]
            != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        ), (
            "an unrecognised role name fails authentication at check 1, so it must not be "
            "reported as the 403 that a recognised-but-unlisted role would earn"
        )


class TestChainOwnershipScope:
    def test_a_chain_admin_cannot_open_or_read_another_chains_programme(self, api):
        """CHN-2's admin is refused on CHN-1's programme both on create and on read.

        PRD §2.1: "When `X-User-Role` is `ChainAdmin`, `X-User-ID` is the `id` of the acting
        `ChainAccount`; ownership checks compare the targeted resource's owning account to
        `X-User-ID` — directly through `ChainConfiguration.chain_account_id` or
        `ConstructionProgram.chain_account_id`, and for a site order through the
        `chain_account_id` of the `ConstructionProgram` it belongs to."

        Design: Corner/rbac/chain_admin_cannot_reach_another_chains_program
        """
        set_clock()
        first = create_chain_account(account_code="CHN-1", contracted_unit_volume=250)
        second = create_chain_account(
            account_code="CHN-2", name="Griddle Group", contracted_unit_volume=60
        )
        payload = construction_program_payload(
            first["id"], program_code="PRG-X", program_type="REMODEL",
            site_count_planned=2,
        )

        intruder = api.create_construction_program(
            payload, make_chain_admin_headers(second["id"])
        )
        validate_error(intruder, ApiErrorId.ERR_CHAIN_SCOPE_VIOLATION.value, 403)

        _page(
            api.list_construction_programs(
                make_chain_admin_headers(first["id"]), {"limit": 100}
            ),
            0,
        )

        owned = validate_success(
            api.create_construction_program(
                payload, make_chain_admin_headers(first["id"])
            ),
            201,
        )
        assert owned["commit_posture"] == "ON_TRACK", (
            "a programme with no site orders yet is on track, got "
            f"{owned['commit_posture']}"
        )
        assert owned["chain_account_id"] == first["id"], (
            f"and belongs to the acting chain, got {owned['chain_account_id']}"
        )

        cross_read = api.get_construction_program(
            owned["id"], make_chain_admin_headers(second["id"])
        )
        validate_error(cross_read, ApiErrorId.ERR_CHAIN_SCOPE_VIOLATION.value, 403)


class TestPartnerOwnershipScope:
    def test_a_partner_user_cannot_enrol_or_read_under_another_partners_id(self, api):
        """SP-2's user is refused on SP-1's body reference, read and child row.

        PRD §2.1: "When `X-User-Role` is `ServicePartnerUser`, `X-User-ID` is the `id` of the
        acting `ServicePartner`; ownership checks compare
        `TechnicianCertification.service_partner_id`, `WarrantyClaim.service_partner_id` and
        any `service_partner_id` supplied in a request body to `X-User-ID`, and a mismatch is
        rejected with `ERR_PARTNER_SCOPE_VIOLATION`."

        Design: Corner/rbac/service_partner_user_cannot_file_under_another_partners_id
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        first = create_service_partner(partner_code="SP-1")
        second = create_service_partner(
            partner_code="SP-2", name="Harbor Service", region_code="SE"
        )

        cross_write = api.create_technician_certification(
            technician_certification_payload(first["id"], model["id"], "T1", 40),
            make_service_partner_headers(second["id"]),
        )
        validate_error(cross_write, ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION.value, 403)

        cross_partner_read = api.get_service_partner(
            first["id"], make_service_partner_headers(second["id"])
        )
        validate_error(
            cross_partner_read, ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION.value, 403
        )

        own = enrol_technician(first["id"], model["id"], "T1", 40)
        assert own["status"] == "ENROLLED", (
            f"the partner's own enrolment succeeds, got {own['status']}"
        )
        assert own["service_partner_id"] == first["id"], (
            f"under its own identity, got {own['service_partner_id']}"
        )

        mine = read_technician_certification(own["id"])
        assert mine["status"] == "ENROLLED" and mine["training_hours"] == 40, (
            "the owning partner reads the row back unchanged, got "
            f"{mine['status']} / {mine['training_hours']}"
        )

        cross_child_read = api.get_technician_certification(
            own["id"], make_service_partner_headers(second["id"])
        )
        validate_error(
            cross_child_read, ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION.value, 403
        )


class TestSegregationOfDuties:
    def test_the_submitting_user_id_cannot_record_the_agency_decision(self, api):
        """`dual-hat-1` is refused as reviewer while `lr-1` acknowledges the same listing.

        PRD §2.10: "On a certification listing, the operator recording an agency decision
        must not be the operator who last submitted the application: the acting `X-User-ID`
        must differ from `submitted_by_user_id`, for every disposition the decision endpoint
        accepts."

        PRD §2.10: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP
        409."

        Design: Corner/rbac/the_listing_submitter_cannot_also_record_the_agency_decision
        """
        set_clock()
        dual_hat = make_compliance_engineer_headers("dual-hat-1")
        model = validate_success(
            api.create_equipment_model(equipment_model_payload(**DIAL_ONLY), dual_hat),
            201,
        )
        listing = validate_success(
            api.create_certification_listing(
                certification_listing_payload(
                    model["id"], "AGENCY_GAMMA", ["SANITATION", "ELECTRICAL"]
                ),
                dual_hat,
            ),
            201,
        )
        submitted = validate_success(
            api.submit_certification_listing(listing["id"], {}, dual_hat)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the application is now with the agency, got {submitted['status']}"
        )
        assert submitted["submitted_by_user_id"] == "dual-hat-1", (
            "the acting operator identifier is recorded for the two-person control, got "
            f"{submitted['submitted_by_user_id']}"
        )

        dual_hatted = api.record_agency_decision(
            listing["id"],
            agency_decision_payload("ACKNOWLEDGE_REVIEW"),
            make_listing_reviewer_headers("dual-hat-1"),
        )
        validate_error(dual_hatted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

        untouched = validate_success(
            api.get_certification_listing(listing["id"], dual_hat)
        )
        assert untouched["status"] == "SUBMITTED", (
            "the refused decision left the application where it was, got "
            f"{untouched['status']}"
        )
        assert untouched["decided_by_user_id"] is None, (
            f"and recorded no decider, got {untouched['decided_by_user_id']}"
        )

        accepted = validate_success(
            api.record_agency_decision(
                listing["id"],
                agency_decision_payload("ACKNOWLEDGE_REVIEW"),
                make_listing_reviewer_headers("lr-1"),
            )
        )
        assert accepted["status"] == "UNDER_REVIEW", (
            "a different operator id on the identical call is accepted, got "
            f"{accepted['status']}"
        )
        assert accepted["decided_by_user_id"] == "lr-1", (
            f"and is recorded as the decider, got {accepted['decided_by_user_id']}"
        )


class TestSharedReadsVersusExclusiveWrites:
    def test_two_read_only_roles_reach_the_model_but_cannot_patch_it(
        self, api, warranty_adjudicator
    ):
        """A ServicePartnerUser and a WarrantyAdjudicator read the model; the PATCH is 403.

        PRD §2.1: "A recognised role that does not appear in the called endpoint's
        authorised-role list (see §4) is rejected with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/shared_reads_are_open_to_every_listed_role_while_writes_stay_exclusive
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        partner = create_service_partner(partner_code="SP-1")

        as_partner = validate_success(
            api.get_equipment_model(
                model["id"], make_service_partner_headers(partner["id"])
            )
        )
        assert as_partner["base_price_cents"] == 1850020, (
            "the shared read returns the catalogue price to the partner user, got "
            f"{as_partner['base_price_cents']}"
        )

        as_adjudicator = validate_success(
            api.get_equipment_model(model["id"], warranty_adjudicator)
        )
        assert as_adjudicator["base_price_cents"] == 1850020, (
            "and the same figure to the adjudicator, got "
            f"{as_adjudicator['base_price_cents']}"
        )

        refused = api.patch_equipment_model(
            model["id"], {"base_price_cents": 1}, warranty_adjudicator
        )
        validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        stored = read_equipment_model(model["id"])
        assert stored["base_price_cents"] == 1850020, (
            f"the refused write changed nothing, got {stored['base_price_cents']}"
        )
        assert stored["version"] == 1, (
            f"and did not count as a mutation, got version {stored['version']}"
        )


class TestNotFoundFamilies:
    def test_each_resource_family_answers_with_its_own_not_found_error(
        self, api, compliance_engineer, production_planner, channel_manager,
        warranty_adjudicator,
    ):
        """Five unknown identifiers produce five distinct 404 error ids.

        PRD §2.9: "Path identifiers are resolved left to right, and the first identifier
        that names no existing row determines the 404 the caller receives; the server does
        not look further right in the path once a segment has failed."

        PRD §2.9: "The warranty claim named in the path resolves. Applies to
        `GET /warranty-claims/{id}`, `POST /warranty-claims/{id}/adjudication` and
        `POST /warranty-claims/{id}/reversal`. `ERR_WARRANTY_CLAIM_NOT_FOUND`."

        Design: Corner/errors/every_not_found_family_answers_with_its_own_error_id
        """
        set_clock()

        probes = [
            (
                api.get_equipment_model(UNKNOWN_MODEL_ID, compliance_engineer),
                ApiErrorId.ERR_EQUIPMENT_MODEL_NOT_FOUND.value,
            ),
            (
                api.get_certification_listing(UNKNOWN_LISTING_ID, compliance_engineer),
                ApiErrorId.ERR_COMPLIANCE_RESOURCE_NOT_FOUND.value,
            ),
            (
                api.get_build_line(UNKNOWN_LINE_ID, production_planner),
                ApiErrorId.ERR_PRODUCTION_RESOURCE_NOT_FOUND.value,
            ),
            (
                api.get_service_partner(UNKNOWN_PARTNER_ID, channel_manager),
                ApiErrorId.ERR_CHANNEL_RESOURCE_NOT_FOUND.value,
            ),
            (
                api.get_warranty_claim(UNKNOWN_CLAIM_ID, warranty_adjudicator),
                ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND.value,
            ),
        ]

        for response, expected_error_id in probes:
            validate_error(response, expected_error_id, 404)
            body = response.json()
            assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
                f"the {expected_error_id} envelope carries a human-readable message, got "
                f"{body['data'].get('message')!r}"
            )

        returned = [response.json()["data"]["error_id"] for response, _ in probes]
        assert len(set(returned)) == 5, (
            "the catalogue splits not-found by resource family rather than using one "
            f"generic code, got {returned}"
        )


class TestCollectionEnvelopes:
    def test_every_collection_family_answers_with_a_filtered_paginated_envelope(
        self, api, compliance_engineer, application_engineer, production_planner,
        connected_ops_engineer, channel_manager, warranty_adjudicator,
    ):
        """Ten families answer their declared filters; empty and non-matching reads return 0.

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the envelope's `meta` object."

        PRD §2.3: "Beyond pagination, list endpoints expose filters that narrow the
        collection without changing its ordering."

        Design: Corner/entities/every_collection_family_answers_with_a_filtered_paginated_envelope
        """
        set_clock()
        listed = setup_listed_model(**DIAL_ONLY)
        model_id = listed["model"]["id"]
        chain = create_chain_account(account_code="CHN-1")
        config = create_chain_configuration(chain["id"], model_id, **PLAIN_CONFIG)
        validation = open_performance_validation(config["id"])
        program = create_construction_program(
            chain["id"], program_code="PRG-1", site_count_planned=3
        )
        line = create_build_line()
        campaign = create_firmware_campaign(model_id)
        partner = create_service_partner(partner_code="SP-1")
        certification = enrol_technician(partner["id"], model_id)

        matches, meta = _page(
            api.list_certification_listings(
                compliance_engineer,
                {"equipment_model_id": model_id, "status": "LISTED"},
            ),
            1,
        )
        assert matches[0]["id"] == listed["listing"]["id"], (
            f"the granted listing answers the LISTED filter, got {matches[0]['id']}"
        )
        assert meta["has_more"] is False, (
            f"a single-row page is complete, got has_more {meta['has_more']}"
        )

        empty, empty_meta = _page(
            api.list_certification_listings(
                compliance_engineer,
                {"equipment_model_id": model_id, "status": "DRAFT"},
            ),
            0,
        )
        assert empty == [], (
            f"a non-matching status filter returns an empty array, not a 404, got {empty}"
        )
        assert empty_meta["has_more"] is False, (
            f"and reports no further pages, got {empty_meta['has_more']}"
        )

        expected_rows = [
            (api.list_chain_accounts(channel_manager, {"limit": 10, "offset": 0}), chain["id"]),
            (
                api.list_performance_validations(
                    application_engineer,
                    {"chain_configuration_id": config["id"], "status": "IN_PROGRESS"},
                ),
                validation["id"],
            ),
            (
                api.list_construction_programs(
                    production_planner,
                    {"chain_account_id": chain["id"], "commit_posture": "ON_TRACK"},
                ),
                program["id"],
            ),
            (api.list_build_lines(production_planner, {"plant_code": "P1"}), line["id"]),
            (
                api.list_firmware_campaigns(
                    connected_ops_engineer,
                    {"equipment_model_id": model_id, "status": "DRAFT"},
                ),
                campaign["id"],
            ),
            (
                api.list_service_partners(
                    channel_manager, {"region_code": "NE", "status": "APPLIED"}
                ),
                partner["id"],
            ),
            (
                api.list_technician_certifications(
                    channel_manager, {"service_partner_id": partner["id"]}
                ),
                certification["id"],
            ),
        ]
        for response, expected_id in expected_rows:
            data, _meta = _page(response, 1)
            assert data[0]["id"] == expected_id, (
                f"the declared filter must select {expected_id}, got {data[0]['id']}"
            )

        no_slots, _ = _page(
            api.list_production_slots(
                production_planner, {"build_line_id": line["id"]}
            ),
            0,
        )
        assert no_slots == [], (
            f"no slot was ever reserved on the line, got {no_slots}"
        )

        no_claims, _ = _page(
            api.list_warranty_claims(
                warranty_adjudicator, {"service_partner_id": partner["id"]}
            ),
            0,
        )
        assert no_claims == [], (
            f"and the partner has filed nothing, got {no_claims}"
        )

    def test_the_configuration_list_pages_the_filtered_set_not_the_page(
        self, api, channel_manager
    ):
        """Three configurations page as 2 + 1 with total_count 3 throughout.

        PRD §2.3: "List endpoints accept two pagination query parameters. `limit` caps the
        number of items returned; it defaults to 10 when omitted, has a minimum of 1 and a
        maximum of 100. `offset` is the number of items to skip; it defaults to 0 and may not
        be negative."

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the envelope's `meta` object."

        Design: Corner/entities/chain_configuration_list_paginates_with_total_count_and_has_more
        """
        set_clock()
        model = create_equipment_model(
            supported_controls_packages=["STANDARD_DIAL", "TOUCH_PRO"]
        )
        chain = create_chain_account(account_code="CHN-1")
        create_chain_configuration(chain["id"], model["id"], config_code="CFG-1", **PLAIN_CONFIG)
        create_chain_configuration(
            chain["id"], model["id"], config_code="CFG-2",
            option_codes=["LEFT_HINGE"], controls_package="STANDARD_DIAL",
            branding_kit="NONE",
        )
        create_chain_configuration(
            chain["id"], model["id"], config_code="CFG-3",
            option_codes=["ENERGY_SAVER"], controls_package="TOUCH_PRO",
            branding_kit="LOGO_BADGE",
        )

        first_response = api.list_chain_configurations(
            channel_manager, {"chain_account_id": chain["id"], "limit": 2, "offset": 0}
        )
        first_page, first_meta = _page(first_response, 3)
        body = first_response.json()
        assert body["response_type"] == "array", (
            f"a list read is an array response, got {body['response_type']}"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "the envelope still carries a server-minted request id, got "
            f"{body['meta'].get('api_request_id')}"
        )
        assert isinstance(body["meta"]["api_request_timestamp"], str), (
            "and a request timestamp, got "
            f"{body['meta'].get('api_request_timestamp')!r}"
        )
        assert len(first_page) == 2, (
            f"the first page is capped at the requested limit, got {len(first_page)}"
        )
        assert first_meta["limit"] == 2 and first_meta["offset"] == 0, (
            "the echoed pagination inputs are the requested ones, got "
            f"{first_meta['limit']} / {first_meta['offset']}"
        )
        assert first_meta["has_more"] is True, (
            f"a third row remains beyond the page, got {first_meta['has_more']}"
        )

        second_page, second_meta = _page(
            api.list_chain_configurations(
                channel_manager,
                {"chain_account_id": chain["id"], "limit": 2, "offset": 2},
            ),
            3,
        )
        assert len(second_page) == 1, (
            f"the tail page holds the remaining row, got {len(second_page)}"
        )
        assert second_meta["has_more"] is False, (
            f"and nothing follows it, got {second_meta['has_more']}"
        )

        codes = sorted(row["config_code"] for row in first_page + second_page)
        assert codes == ["CFG-1", "CFG-2", "CFG-3"], (
            "total_count counts the filtered set, and the two pages together return every "
            f"configuration exactly once, got {codes}"
        )


class TestDeclaredInitialStates:
    def test_every_state_bearing_row_is_born_in_its_declared_initial_state(self):
        """One sweep over seven creates: DRAFT, DRAFT, IN_PROGRESS, APPLIED, ENROLLED, ...

        PRD §3.1: "A new application starts in `DRAFT` with `revision` at 0,
        `conditions_note`, `listed_on`, `expires_on`, `submitted_by_user_id` and
        `decided_by_user_id` all null."

        PRD §3.3: "It sets the new configuration's `status` to `DRAFT` with `revision` at 0,
        `revision_note` null, `branding_signed_off` false, `firm_unit_price_cents` null and
        `pinned_model_version` null."

        PRD §3.4: "Opening a validation increments the parent configuration's `version` by
        one, sets the new row's `status` to `IN_PROGRESS` with `attempt_count` at 0 and
        `test_runs` an empty array, leaves `certified_throughput_units_per_hour`,
        `as_tested_throughput_units_per_hour` and `failure_reason` null, and supersedes any
        prior validation for the same configuration and `menu_item_code`, moving it
        `IN_PROGRESS → SUPERSEDED`, `PASSED → SUPERSEDED` or `FAILED → SUPERSEDED` as the
        case may be and freezing its `test_runs` where they stood."

        PRD §3.9: "A new partner sits at `status` `APPLIED` with an empty
        `authorized_model_ids`."

        PRD §3.9: "A new certification sits at `status` `ENROLLED` with `exam_score`,
        `certified_on` and `expires_on` null."

        PRD §3.8: "A draft campaign reports `status` `DRAFT`, an empty `cohort_unit_ids`,
        `success_count` and `failure_count` at zero and `success_rate` null."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        set_clock()
        model = create_equipment_model(**DIAL_ONLY)
        chain = create_chain_account(account_code="CHN-1")

        listing = file_certification_listing(model["id"], "AGENCY_GAMMA", ["SANITATION"])
        assert listing["status"] == "DRAFT", (
            f"a filed application starts in DRAFT, got {listing['status']}"
        )

        config = create_chain_configuration(chain["id"], model["id"], **PLAIN_CONFIG)
        assert config["status"] == "DRAFT", (
            f"as does a new configuration, got {config['status']}"
        )

        validation = open_performance_validation(config["id"])
        assert validation["status"] == "IN_PROGRESS", (
            f"a fresh validation opens IN_PROGRESS, got {validation['status']}"
        )
        assert validation["attempt_count"] == 0, (
            "with no concluded attempt yet, got "
            f"{validation['attempt_count']}"
        )

        partner = create_service_partner(partner_code="SP-1")
        assert partner["status"] == "APPLIED", (
            f"a registered partner sits at APPLIED, got {partner['status']}"
        )
        assert partner["authorized_model_ids"] == [], (
            "and carries no model authority yet, got "
            f"{partner['authorized_model_ids']}"
        )

        certification = enrol_technician(partner["id"], model["id"])
        assert certification["status"] == "ENROLLED", (
            f"an enrolled technician starts at ENROLLED, got {certification['status']}"
        )

        unit = create_connected_unit(model["id"], "SN-1")
        assert unit["service_program_status"] == "PENDING_INSTALL", (
            "a registered unit awaits installation, got "
            f"{unit['service_program_status']}"
        )

        campaign = create_firmware_campaign(model["id"])
        assert campaign["status"] == "DRAFT", (
            f"a drafted campaign starts in DRAFT, got {campaign['status']}"
        )
        assert campaign["cohort_unit_ids"] == [], (
            "and selects no cohort until it is scheduled, got "
            f"{campaign['cohort_unit_ids']}"
        )
