"""Authentication, role authorisation, entity-backed identity and the producer privacy gate."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_SERIAL_START,
    ain_for_serial,
    apply_tag_payload,
    create_producer_payload,
    create_tag_lot_payload,
    make_harvest_operator_headers,
    make_producer_headers,
    make_program_admin_headers,
    make_state_official_headers,
    make_supplier_rep_headers,
    make_trace_analyst_headers,
    open_trace,
    read_supplier,
    read_tag,
    register_premises,
    register_producer,
    register_supplier,
    retire_tag_payload,
    run_trace,
    setup_animal_scenario,
    setup_harvest_ready_animal,
    setup_isolated_animal_for_trace,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_REG = make_program_admin_headers("admin-reg")
ADMIN_APR = make_program_admin_headers("admin-apr")
OFFICIAL = make_state_official_headers("saho-1")
OPENING_ANALYST = make_trace_analyst_headers("fta-1")


class TestAuthentication:
    def test_absent_or_unrecognised_identity_headers_are_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting. If either header is absent, or if `X-User-Role` is not one of the six recognised role names, the request is rejected with `ERR_UNAUTHENTICATED`. The six recognised roles are `Producer`, `StateAnimalHealthOfficial`, `FederalTraceAnalyst`, `DeviceSupplierRep`, `HarvestFacilityOperator`, and `ProgramAdmin`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        payload = create_producer_payload(
            legal_name="No Auth Co", contact_email="x@x.example", state_code="CO"
        )

        no_headers = api.create_producer(payload, {"Content-Type": "application/json"})
        validate_error(no_headers, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

        unknown_role = api.create_producer(
            payload,
            {
                "X-User-ID": "someone",
                "X-User-Role": "HerdVeterinarian",
                "Content-Type": "application/json",
            },
        )
        validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

        accepted = api.create_producer(payload, ADMIN_REG)
        validate_success(accepted, expected_status=201)


class TestRoleAuthorisation:
    def test_a_producer_cannot_approve_its_own_premises_registration(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to invoke it (see the table in Section 4); a syntactically valid request from a role that is not on that endpoint's list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.1: "Registration review belongs to the state. Approval by a `StateAnimalHealthOfficial` moves a premises from `PENDING_REVIEW` to `ACTIVE`, and is permitted only while the premises is in `PENDING_REVIEW`; attempting it from any other registration state is an invalid transition."

        Design: Corner/validations/producer_cannot_approve_premises_role_forbidden
        """
        producer = register_producer(legal_name="Role Co")
        premises = register_premises(producer["id"], capacity=10)

        resp = api.approve_premises(premises["id"], make_producer_headers(producer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

        rows, _meta = validate_paginated(
            api.list_premises(ADMIN_REG, params={"producer_id": producer["id"]})
        )
        assert rows[0]["registration_status"] == "PENDING_REVIEW"

    def test_peer_roles_cannot_reach_each_others_exclusive_operations(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to invoke it (see the table in Section 4); a syntactically valid request from a role that is not on that endpoint's list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.3: "Only a `DeviceSupplierRep` may issue a lot, and only against its own supplier record."
        PRD §3.4: "Erroneous applications are unwound rather than deleted. Voiding an application is a `ProgramAdmin` compensating action, available only while the device is `APPLIED` and the tagged animal is `ACTIVE` — an animal that has been harvested or is in transit cannot have its application voided, and the attempt returns `ERR_INVALID_STATE`."

        Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
        """
        scenario = setup_animal_scenario(capacity=10, quantity=10, legal_name="Rbac Co")
        supplier_id = scenario["supplier"]["id"]

        producer_issuing_a_lot = api.create_tag_lot(
            create_tag_lot_payload(
                supplier_id,
                scenario["premises"]["id"],
                read_supplier(supplier_id)["version"],
                serial_start=DEFAULT_SERIAL_START + 10,
                quantity=10,
            ),
            scenario["producer_headers"],
        )
        validate_error(
            producer_issuing_a_lot, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403
        )

        supplier_applying_a_tag = api.apply_tag(
            scenario["lot"]["id"],
            apply_tag_payload(
                ain_for_serial(DEFAULT_SERIAL_START + 1), scenario["premises"]["id"]
            ),
            make_supplier_rep_headers(supplier_id),
        )
        validate_error(
            supplier_applying_a_tag, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403
        )

        official_voiding_an_application = api.void_tag_application(
            scenario["tag"]["id"], OFFICIAL
        )
        validate_error(
            official_voiding_an_application, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403
        )

        assert read_tag(scenario["tag"]["id"])["device_status"] == "APPLIED"
        _rows, meta = validate_paginated(
            api.list_tag_lots(ADMIN_REG, params={"supplier_id": supplier_id})
        )
        assert meta["total_count"] == 1


class TestEntityBackedIdentity:
    def test_harvest_operator_identity_is_the_harvest_premises_itself(self, api):
        """PRD §2.1: "When `X-User-Role` is `HarvestFacilityOperator`, `X-User-ID` is the `id` of the acting harvest `Premises` record — the facility is its own principal; ownership checks compare the request's `harvest_premises_id` to `X-User-ID`."
        PRD §3.8: "Retirement is the end of an animal's traceable life and the point at which the device leaves circulation. Only a `HarvestFacilityOperator` may retire a device, and only at its own facility: the supplied `harvest_premises_id` must equal the operator's `X-User-ID`."

        Design: Corner/rbac/harvest_operator_identity_is_the_premises_itself
        """
        scenario = setup_harvest_ready_animal(lot_quantity=10, extra_harvest_premises=True)
        target = scenario["harvest_premises"]["id"]
        other_facility = scenario["second_harvest_premises"]["id"]

        payload = retire_tag_payload(
            target, "2026-08-04T00:00:00Z", carcass_ref="CARC-9", tag_returned=True
        )
        wrong_principal = api.retire_tag(
            scenario["tag"]["id"], payload, make_harvest_operator_headers(other_facility)
        )
        validate_error(
            wrong_principal, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403
        )
        assert read_tag(scenario["tag"]["id"])["device_status"] == "APPLIED"

        retired = validate_success(
            api.retire_tag(
                scenario["tag"]["id"], payload, make_harvest_operator_headers(target)
            )
        )
        assert retired["device_status"] == "RETIRED"
        assert read_tag(scenario["tag"]["id"])["device_status"] == "RETIRED"


class TestSegregationOfDuties:
    def test_registering_admin_cannot_approve_and_opening_analyst_cannot_close(self, api):
        """PRD §2.1: "Two decisions in the programme are subject to **segregation of duties**, and both are enforced by comparing the acting `X-User-ID` against a previously stored user identifier. The `ProgramAdmin` who approves a device supplier must not be the same administrator recorded in `registered_by_user_id`, and the `FederalTraceAnalyst` who closes a trace request must not be the same analyst recorded in `opened_by_user_id`. Either violation returns `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.2: "Approval moves the supplier from `PENDING_REVIEW` to `APPROVED` and is available only from `PENDING_REVIEW`. It is the segregation-of-duties decision described in Section 2.1: a second `ProgramAdmin`, whose `X-User-ID` differs from the stored `registered_by_user_id`, must perform it, and the approving administrator's identifier is written to `approved_by_user_id`."
        PRD §3.7: "Closing is available only from `RUNNING` and is the second segregation-of-duties decision: the closing analyst's `X-User-ID` must differ from the stored `opened_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_blocks_self_approval_and_self_close
        """
        scenario = setup_isolated_animal_for_trace()
        self_registered = register_supplier(
            company_name="Second Devices", supplier_code="SEC2"
        )

        self_approval = api.approve_device_supplier(self_registered["id"], ADMIN_REG)
        validate_error(
            self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403
        )

        trace = open_trace(
            scenario["animal"]["id"],
            pathogen_class="DIRECT_CONTACT",
            direction="BOTH",
            lookback_days=30,
            max_hops=2,
        )
        run_trace(trace["id"])
        self_close = api.close_trace_request(trace["id"], OPENING_ANALYST)
        validate_error(self_close, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        supplier_after = validate_success(
            api.get_device_supplier(self_registered["id"], ADMIN_REG)
        )
        assert supplier_after["status"] == "PENDING_REVIEW"
        assert supplier_after["approved_by_user_id"] is None

        trace_after = validate_success(api.get_trace_request(trace["id"], ADMIN_REG))
        assert trace_after["status"] == "RUNNING"
        assert trace_after["closed_by_user_id"] is None


class TestProducerPrivacyGate:
    def test_restricted_untraced_animal_is_hidden_from_regulators_but_not_its_owner(self, api):
        """PRD §2.7: "A `StateAnimalHealthOfficial` may read any animal owned by a producer whose `privacy_level` is `STANDARD`; an animal owned by a `RESTRICTED` producer becomes readable only once its `trace_status` is `TRACE_HIT` or `CLEARED`."
        PRD §2.7: "A `FederalTraceAnalyst` may read only animals that are the index animal of some trace request or that appear in some trace request's hit set, and for those animals the producer's `privacy_level` is irrelevant."
        PRD §2.7: "Reading a single sighting inherits the gate applied to that sighting's animal. A denied single-resource read returns `ERR_DATA_ACCESS_DENIED`. List endpoints behave differently and deliberately: rather than erroring, they **silently omit** rows the caller may not read, so that a caller cannot probe the existence of a restricted herd through pagination totals."
        PRD §2.7: "A `Producer` may read only animals whose birth premises or current premises belongs to that producer."

        Design: Corner/validations/privacy_gate_hides_restricted_animals_and_untraced_animals
        """
        scenario = setup_animal_scenario(
            capacity=10, quantity=10, privacy_level="RESTRICTED",
            legal_name="Restricted Ranch",
        )
        animal_id = scenario["animal"]["id"]

        official_read = api.get_animal(animal_id, OFFICIAL)
        validate_error(official_read, ApiErrorId.ERR_DATA_ACCESS_DENIED, expected_status=403)

        analyst_read = api.get_animal(animal_id, OPENING_ANALYST)
        validate_error(analyst_read, ApiErrorId.ERR_DATA_ACCESS_DENIED, expected_status=403)

        owner_read = validate_success(api.get_animal(animal_id, scenario["producer_headers"]))
        assert owner_read["id"] == animal_id

        admin_read = validate_success(api.get_animal(animal_id, ADMIN_REG))
        assert admin_read["id"] == animal_id

        rows, meta = validate_paginated(
            api.list_animals(OFFICIAL, params={"birth_premises_id": scenario["premises"]["id"]})
        )
        assert rows == [], "unreadable rows are dropped from a listing rather than errored"
        assert meta["total_count"] == 0
