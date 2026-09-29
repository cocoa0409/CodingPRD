"""Unknown identifiers, malformed request shapes and the element dependency graph."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_element,
    create_program,
    create_program_element_payload,
    create_supplier,
    create_venue,
    draft_contract,
    read_program,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
SM = TEST_USERS["supplier_manager_headers"]


class TestUnknownIdentifiers:
    def test_an_unknown_programme_id_reports_the_programme_not_found_code(self, api):
        """PRD §2.8: "Each resource type has its own not-found code, all of them HTTP 404:
        `ERR_PROGRAM_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_ELEMENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
        `ERR_SEGMENT_NOT_FOUND`, `ERR_MANIFEST_ENTRY_NOT_FOUND`,
        `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`,
        `ERR_RECONCILIATION_LINE_NOT_FOUND` and `ERR_SETTLEMENT_PAYMENT_NOT_FOUND`."

        Design: Corner/entities/get_program_unknown_id_not_found
        """
        response = api.get_program(NON_EXISTENT_UUID, PD)

        validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"

    def test_an_unknown_manifest_entry_reports_its_own_code_not_its_parents(self, api):
        """PRD §2.8: "Endpoint paths in this API are flat: each write or read addresses one
        resource by one identifier."

        Design: Corner/entities/get_manifest_entry_unknown_id_not_found
        """
        response = api.get_manifest_entry(NON_EXISTENT_UUID, OC)

        validate_error(response, ApiErrorId.ERR_MANIFEST_ENTRY_NOT_FOUND.value, 404)
        assert (
            response.json()["data"]["error_id"] != ApiErrorId.ERR_SEGMENT_NOT_FOUND.value
        )


class TestRequestShapeRefusals:
    def test_a_programme_filed_without_a_guaranteed_count_is_rejected(self, api):
        """PRD §2.9: "Request shape: required fields present, enum members legal, integers
        at or above their declared minima, datetime pairs strictly ordered, pagination in
        range — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_program_missing_guaranteed_count_invalid_request
        """
        response = api.create_program(
            {
                "client_name": "Incomplete Client",
                "group_name": "Incomplete Group",
                "arrival_date": "2026-09-10",
                "departure_date": "2026-09-14",
                "markup_pct": 0.18,
            },
            PD,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        _, meta = validate_paginated(
            api.list_programs(PD, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0


class TestElementCreationReferences:
    BAD_ENUM_ELEMENT = {
        "element_type": "GALA_DINNER",
        "title": "Bad Enum",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }

    def _venue_supplier_and_draft_programme(self, client_name, group_name, venue_name):
        venue = create_venue(name=venue_name, capacity_seated=100, capacity_reception=200)
        supplier = create_supplier(legal_name=f"{venue_name} Supplier")
        program = create_program(
            client_name=client_name, group_name=group_name, guaranteed_count=20
        )
        return venue, supplier, program

    def test_an_element_type_outside_the_declared_enum_is_a_bad_request(self, api):
        """PRD §3.2: "Each element is created with the `program_id` it belongs to, the
        `supplier_id` delivering it, an `element_type` drawn from `ACTIVITY`, `DINE_AROUND`,
        `OFF_PREMISE_EVENT` and `TRANSFER_BLOCK`, the `title` that will print on the
        production timeline, a `starts_at` and `ends_at` bounding the venue occupation (with
        `ends_at` strictly after `starts_at`), the `planned_headcount` and
        `guaranteed_headcount` (both at least 0), the `per_person_cost_cents` the supplier
        charges per billed head (at least 0), and the `expected_program_version` guard
        described in §2.5."

        Design: Corner/entities/create_element_with_unknown_element_type_invalid_enum
        """
        venue, supplier, program = self._venue_supplier_and_draft_programme(
            "Enum Client", "Enum Group", "Enum Test Venue"
        )
        version_before = program["version"]

        response = api.create_program_element(
            create_program_element_payload(
                program["id"],
                supplier["id"],
                version_before,
                venue_id=venue["id"],
                **self.BAD_ENUM_ELEMENT,
            ),
            PD,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        stored = validate_success(api.get_program(program["id"], PD))
        assert stored["element_count"] == 0
        assert stored["version"] == version_before

    def test_an_element_hung_off_a_missing_programme_is_a_not_found_not_a_stale_version(
        self, api
    ):
        """PRD §2.9: "Existence of every foreign key in the body, in declared field order —
        the same not-found codes."

        Design: Corner/entities/create_element_with_unknown_program_id_not_found
        """
        venue, supplier, bystander = self._venue_supplier_and_draft_programme(
            "Bystander Client", "Bystander Group", "Orphan Test Venue"
        )

        response = api.create_program_element(
            create_program_element_payload(
                NON_EXISTENT_UUID,
                supplier["id"],
                bystander["version"],
                venue_id=venue["id"],
                element_type="ACTIVITY",
                title="Orphan Element",
                starts_at="2026-09-11T09:00:00Z",
                ends_at="2026-09-11T11:00:00Z",
                planned_headcount=20,
                guaranteed_headcount=20,
                per_person_cost_cents=4_000,
            ),
            PD,
        )

        validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_STALE_PROGRAM_VERSION.value
        )
        stored = validate_success(api.get_program(bystander["id"], PD))
        assert stored["element_count"] == 0


class TestProgramSupplierGraph:
    ACTIVITY = {
        "element_type": "ACTIVITY",
        "title": "Supplier One Activity",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    DINNER = {
        "element_type": "DINE_AROUND",
        "title": "Supplier Two Dinner",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
    }

    def _one_programme_bound_to_two_suppliers(self):
        venue_a = create_venue(
            name="Graph Venue A", capacity_seated=100, capacity_reception=200
        )
        venue_b = create_venue(
            name="Graph Venue B", capacity_seated=100, capacity_reception=200
        )
        supplier_one = create_supplier(legal_name="Graph Supplier One")
        supplier_two = create_supplier(
            legal_name="Graph Supplier Two", supplier_type="VENUE_SERVICES"
        )
        program = create_program(
            client_name="Graph Client", group_name="Graph Group", guaranteed_count=40
        )
        element_one = add_element(
            program["id"], supplier_one["id"], venue_id=venue_a["id"], **self.ACTIVITY
        )
        element_two = add_element(
            program["id"], supplier_two["id"], venue_id=venue_b["id"], **self.DINNER
        )
        contract_one = draft_contract(
            program["id"], supplier_one["id"], contract_value_cents=80_000
        )
        contract_two = draft_contract(
            program["id"],
            supplier_two["id"],
            contract_value_cents=100_000,
            cancellation_tier="STRICT",
        )
        return {
            "program": program,
            "supplier_two": supplier_two,
            "element_two": element_two,
            "contract_two": contract_two,
            "element_one": element_one,
            "contract_one": contract_one,
        }

    def test_the_association_resolves_from_both_ends(self, api):
        """PRD §2.3: "Relationship filters are available where the workflow needs them:
        `program_id` on supplier contracts, program elements, transport segments, staff
        assignments, reconciliation lines and settlement payments; `supplier_id` on supplier
        contracts, program elements, reconciliation lines and settlement payments;
        `contract_id` on settlement payments; `venue_id`, `predecessor_element_id` and
        `alternative_for_element_id` on program elements; `element_id` on permits, program
        elements' own children, staff assignments and reconciliation lines; `segment_id` on
        manifest entries and staff assignments; and `staff_id` on staff assignments."

        Design: Corner/entities/graph_topology_program_supplier_many_to_many_reverse_lookups
        """
        graph = self._one_programme_bound_to_two_suppliers()

        _, by_program = validate_paginated(
            api.list_supplier_contracts(
                SM, params={"program_id": graph["program"]["id"], "limit": 10, "offset": 0}
            )
        )
        contracts, by_supplier = validate_paginated(
            api.list_supplier_contracts(
                SM,
                params={
                    "supplier_id": graph["supplier_two"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        elements, by_element_supplier = validate_paginated(
            api.list_program_elements(
                PD,
                params={
                    "supplier_id": graph["supplier_two"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )

        assert by_program["total_count"] == 2
        assert by_supplier["total_count"] == 1
        assert contracts[0]["id"] == graph["contract_two"]["id"]
        assert by_element_supplier["total_count"] == 1
        assert elements[0]["id"] == graph["element_two"]["id"]
        program = validate_success(api.get_program(graph["program"]["id"], PD))
        assert program["element_count"] == 2


class TestProductionTimelineAcyclicity:
    FIRST = {
        "element_type": "ACTIVITY",
        "title": "Element A",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    SECOND = {
        "element_type": "ACTIVITY",
        "title": "Element B",
        # 12:30Z clears the venue's 90-minute turnover buffer after Element A.
        "starts_at": "2026-09-11T12:30:00Z",
        "ends_at": "2026-09-11T14:30:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }

    def _b_already_depends_on_a(self):
        venue = create_venue(
            name="Cycle Test Venue",
            capacity_seated=100,
            capacity_reception=200,
            turnover_buffer_minutes=90,
        )
        supplier = create_supplier(legal_name="Cycle Test Supplier")
        program = create_program(
            client_name="Cycle Client", group_name="Cycle Group", guaranteed_count=20
        )
        element_a = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], **self.FIRST
        )
        element_b = add_element(
            program["id"],
            supplier["id"],
            venue_id=venue["id"],
            predecessor_element_id=element_a["id"],
            **self.SECOND,
        )
        return {"program": program, "a": element_a, "b": element_b}

    def test_closing_a_two_node_loop_on_patch_is_refused(self, api):
        """PRD §3.2: "The production timeline formed by `predecessor_element_id` is a
        directed graph, and it must stay acyclic."

        Design: Corner/entities/self_referential_predecessor_cycle_rejected_on_patch
        """
        ctx = self._b_already_depends_on_a()

        response = api.patch_program_element(
            ctx["a"]["id"], {"predecessor_element_id": ctx["b"]["id"]}, PD
        )

        validate_error(response, ApiErrorId.ERR_ELEMENT_DEPENDENCY_CYCLE.value, 422)

    def test_the_refused_rewiring_leaves_both_edges_as_they_were(self, api):
        """PRD §3.2: "Following the predecessor chain transitively from a candidate element
        must terminate without ever arriving back at the candidate; a self-reference or any
        longer cycle is refused with `ERR_ELEMENT_DEPENDENCY_CYCLE`."

        Design: Corner/entities/self_referential_predecessor_cycle_rejected_on_patch
        """
        ctx = self._b_already_depends_on_a()
        api.patch_program_element(
            ctx["a"]["id"], {"predecessor_element_id": ctx["b"]["id"]}, PD
        )

        element_a = validate_success(api.get_program_element(ctx["a"]["id"], PD))
        element_b = validate_success(api.get_program_element(ctx["b"]["id"], PD))

        assert element_a["predecessor_element_id"] is None
        assert element_b["predecessor_element_id"] == ctx["a"]["id"]
        program = read_program(ctx["program"]["id"])
        assert program["element_count"] == 2
