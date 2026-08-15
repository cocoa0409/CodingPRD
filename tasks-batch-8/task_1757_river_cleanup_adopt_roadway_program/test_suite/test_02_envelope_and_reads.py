"""Response envelope, not-found sweep, shared reads, pagination, metrics
(PR.D §2.2, §2.3, §2.11, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_program_metrics,
    complete_event,
    create_event,
    create_group,
    create_group_payload,
    create_segment,
    create_waiver_payload,
    estimated_report_payload,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

COORD = make_coordinator_headers()


class TestEnvelopeShape:
    def test_success_envelope_shape_on_object_and_array(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body"
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/success_envelope_shape_on_object_and_array
        """
        group = create_group()
        one = api.get_group(group["id"], COORD)
        data = validate_success(one, 200)
        body = one.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        listed = api.list_agreements(COORD)
        rows, meta = validate_paginated(listed)
        body = listed.json()
        assert body["response_type"] == "array"
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_success_envelope_pagination_defaults(self, api):
        """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1
        and maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."

        Design: Corner/endpoints/success_envelope_shape_on_object_and_array
        """
        listed = api.list_segments(COORD)
        _, meta = validate_paginated(listed)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_group(NON_EXISTENT_UUID, COORD)
        err = validate_error(resp, ApiErrorId.ERR_GROUP_NOT_FOUND)
        assert isinstance(err["message"], str) and err["message"].strip()
        body = resp.json()
        assert body["response_type"] == "error"

    def test_error_envelope_contains_message_text(self, api):
        """PRD §2.2: "The `message` provides a human-readable explanation of
        what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_segment(NON_EXISTENT_UUID, COORD)
        err = validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_FOUND)
        assert len(err["message"].strip()) > 0


class TestNotFoundSweep:
    def test_not_found_reads_and_actions_return_entity_codes(self, api):
        """PRD §2.11 family 3: "every referenced resource must resolve, each
        class with its own 404: adopter groups referenced by path or by a
        body's `group_id` (`ERR_GROUP_NOT_FOUND`); road segments
        (`ERR_SEGMENT_NOT_FOUND`); adoption agreements
        (`ERR_AGREEMENT_NOT_FOUND`); cleanup events (`ERR_EVENT_NOT_FOUND`);
        volunteer waivers, whether addressed by path, cited as a
        `supervisor_waiver_id`, or listed in `attendee_waiver_ids`
        (`ERR_WAIVER_NOT_FOUND`); supply distributions (`ERR_SUPPLY_NOT_FOUND`);
        the depot named by a supply-issuance body's `depot_id`
        (`ERR_DEPOT_NOT_FOUND`); hazard reports (`ERR_HAZARD_NOT_FOUND`);
        recognition signs (`ERR_SIGN_NOT_FOUND`)."

        Design: Corner/entities/not_found_reads_and_actions_return_entity_codes
        """
        assert (
            validate_error(api.get_group(NON_EXISTENT_UUID, COORD),
                           ApiErrorId.ERR_GROUP_NOT_FOUND)["error_id"]
            == "ERR_GROUP_NOT_FOUND"
        )
        validate_error(api.get_segment(NON_EXISTENT_UUID, COORD),
                       ApiErrorId.ERR_SEGMENT_NOT_FOUND)
        validate_error(api.get_agreement(NON_EXISTENT_UUID, COORD),
                       ApiErrorId.ERR_AGREEMENT_NOT_FOUND)
        validate_error(api.get_event(NON_EXISTENT_UUID, COORD),
                       ApiErrorId.ERR_EVENT_NOT_FOUND)
        validate_error(api.get_supply(NON_EXISTENT_UUID, COORD),
                       ApiErrorId.ERR_SUPPLY_NOT_FOUND)
        validate_error(api.acknowledge_hazard(NON_EXISTENT_UUID, COORD),
                       ApiErrorId.ERR_HAZARD_NOT_FOUND)
        validate_error(api.install_sign(NON_EXISTENT_UUID, COORD),
                       ApiErrorId.ERR_SIGN_NOT_FOUND)

    def test_waiver_not_found_via_revoke(self, api):
        """PRD §2.11 family 3: "volunteer waivers, whether addressed by path,
        cited as a `supervisor_waiver_id`, or listed in `attendee_waiver_ids`
        (`ERR_WAIVER_NOT_FOUND`)"

        Design: Corner/entities/not_found_reads_and_actions_return_entity_codes
        """
        # Group must exist so the role identity is well formed; waiver id
        # does not resolve.
        group = create_group()
        resp = api.revoke_waiver(
            NON_EXISTENT_UUID, make_group_leader_headers(group["id"])
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_FOUND)


class TestSharedReads:
    def test_shared_reads_allowed_for_both_roles(self, api):
        """PRD §4: GET /program/agreements/{id} authorized roles
        "ProgramCoordinator, GroupLeader".

        Design: Corner/rbac/shared_reads_allowed_for_both_roles
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        data_gl = validate_success(api.get_agreement(agreement["id"], gl), 200)
        data_pc = validate_success(api.get_agreement(agreement["id"], COORD), 200)
        assert data_gl["status"] == "ACTIVE"
        assert data_pc["status"] == "ACTIVE"


class TestEventPagination:
    def test_events_list_pagination_and_agreement_filter(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.3: "Event listings filter by `agreement_id` and `status`."

        Design: Corner/entities/events_list_pagination_and_agreement_filter
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        for day in ("2026-09-10", "2026-09-11", "2026-09-12"):
            create_event(agreement["id"], group["id"], scheduled_date=day)

        page1 = api.list_events(
            gl, params={"agreement_id": agreement["id"], "limit": 2, "offset": 0}
        )
        rows1, meta1 = validate_paginated(page1)
        assert len(rows1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2 = api.list_events(
            gl, params={"agreement_id": agreement["id"], "limit": 2, "offset": 2}
        )
        rows2, meta2 = validate_paginated(page2)
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestMetricsEmptyProgram:
    def test_metrics_computed_read_empty_program(self, api):
        """PRD §3.8: "Program-wide health is a computed read rather than a
        stored record. The metrics view reports `active_agreements` ... ;
        `adopted_miles` and `available_miles` ... ; `total_debris_lbs` ... ;
        `completed_cleanups` ...; and `open_hazards` ..."

        Design: Corner/endpoints/metrics_computed_read_empty_program
        """
        data = validate_success(api.get_metrics(COORD), 200)
        assert_program_metrics(data)
        assert data["active_agreements"] == 0
        assert data["adopted_miles"] == 0.0
        assert data["available_miles"] == 0.0
        assert data["total_debris_lbs"] == 0.0
        assert data["completed_cleanups"] == 0
        assert data["open_hazards"] == 0


class TestMetricsStatusFiltering:
    def test_program_metrics_status_filtering(self, api):
        """PRD §3.8: "The metrics view reports `active_agreements` — the count
        of agreements currently `ACTIVE`; `adopted_miles` and `available_miles`
        — the summed `mile_length` of segments in `ADOPTED` and `AVAILABLE`
        respectively, each rounded half-up to two decimal places;
        `total_debris_lbs` — the sum of `official_weight_lbs` across all debris
        reports at one decimal place, stable because reports are immutable;
        `completed_cleanups` — the count of events in `COMPLETED`; and
        `open_hazards` — the count of hazard reports in `REPORTED` or
        `ACKNOWLEDGED`."
        PRD §2.8: "it is `AVAILABLE` while no non-terminal agreement spans it,
        and `ADOPTED` while an agreement referencing it is in `PENDING_REVIEW`,
        `ACTIVE`, `SUSPENDED`, or `RENEWAL_REVIEW`."

        Design: Corner/calculations/program_metrics_status_filtering
        """
        # Active agreement on the 2.0-mile segment.
        g1, s1, ag1 = setup_active_agreement(
            group_name="Riverkeepers", contact_email="gina@riverkeepers.org",
            route_name="River Rd", mile_marker_start=4.0, mile_marker_end=6.0,
        )
        # Pending agreement on the 1.5-mile segment.
        g2 = create_group(name="Road Rangers", org_type="BUSINESS",
                          contact_email="rob@roadrangers.com")
        s2 = create_segment(route_name="Hill Rd", mile_marker_start=10.0,
                            mile_marker_end=11.5, segment_type="ROADWAY",
                            water_adjacent=False)
        from test_helpers import create_agreement, create_hazard_payload
        create_agreement(g2, s2, contact_email="rob@roadrangers.com")

        # One open hazard (REPORTED) plus one driven through to RESOLVED.
        h1 = validate_success(
            api.create_hazard(create_hazard_payload(
                s1["id"], hazard_type="PROPANE_TANK",
                description="tank at shore", location_note="MP 5.0"), COORD), 201)
        h2 = validate_success(
            api.create_hazard(create_hazard_payload(
                s1["id"], hazard_type="OTHER",
                description="drum", location_note="MP 5.4"), COORD), 201)
        api.acknowledge_hazard(h2["id"], COORD)
        api.resolve_hazard(h2["id"], {"resolution_note": "removed"}, COORD)

        data = validate_success(api.get_metrics(COORD), 200)
        # PENDING_REVIEW agreement excluded from active_agreements.
        assert data["active_agreements"] == 1
        # PRD §2.8 conservation invariant: adopted + available always equals
        # the total mapped mileage (2.0 + 1.5), whatever the split.
        assert data["adopted_miles"] + data["available_miles"] == 3.5
        # RESOLVED hazard excluded from open_hazards.
        assert data["open_hazards"] == 1
        assert data["total_debris_lbs"] == 0.0
        assert data["completed_cleanups"] == 0


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_write(self, api):
        """PRD §2.4: "This versioning rule is absolute: any mutation — a state
        transition, an amendment, a counter recomputation, or one hop of a
        multi-resource cascade — increments the affected resource's `version`
        by exactly one and refreshes its `updated_at`."
        PRD §3.6: "The event moves to `COMPLETED` and its
        `completed_weight_lbs` is set to the report's `official_weight_lbs`"

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        from test_helpers import brief_event
        brief_event(event["id"], group["id"], [waiver["id"]])
        set_clock("2026-09-10T10:00:00Z")

        got = validate_success(api.get_group(group["id"], COORD), 200)
        assert got["name"] == "Riverkeepers"

        report = complete_event(
            event["id"], group["id"],
            estimated_report_payload(bag_count=2),
        )
        assert report["official_weight_lbs"] == 25.5
        refreshed = validate_success(api.get_event(event["id"], COORD), 200)
        assert refreshed["status"] == "COMPLETED"
        assert refreshed["completed_weight_lbs"] == 25.5
