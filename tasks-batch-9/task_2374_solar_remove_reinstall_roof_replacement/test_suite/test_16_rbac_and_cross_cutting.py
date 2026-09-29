"""Role access, optimistic concurrency, rollup reconciliation and read-your-writes.

Every test starts against an empty database with the logical clock reading
2026-08-01T00:00:00Z, and builds all of its preconditions from scratch.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    NON_EXISTENT_UUID,
    add_bin,
    add_circuit,
    add_finding,
    add_unit,
    add_window,
    api_client,
    create_core_parties,
    create_deck_finding_payload,
    create_inspection_payload,
    create_jurisdiction,
    create_party,
    create_permit,
    create_permit_application_payload,
    create_project,
    create_project_payload,
    create_sourcing_order_payload,
    create_work_window_payload,
    drive_finding,
    grade_unit,
    is_iso8601_timestamp,
    make_ahj_inspector_headers,
    make_roofing_contractor_headers,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    make_system_owner_headers,
    open_consent,
    refresh_project,
    remove_unit,
    set_clock,
    setup_deenergized_project,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_notice_payload,
)

EPOCH_INSTANT = "2026-08-01T00:00:00"

LEASE_SHAPE = {
    "site_address": "418 Mesquite Way, Tempe AZ",
    "system_dc_kw": 8.4,
    "baseline_daily_kwh": 41.75,
    "downtime_days_estimated": 6,
    "upgrade_budget_cents": 5000000,
}
HOST_OWNED_SHAPE = {
    "site_address": "77 Ocotillo Ln, Chandler AZ",
    "system_dc_kw": 6.0,
    "baseline_daily_kwh": 30.0,
    "downtime_days_estimated": 4,
    "upgrade_budget_cents": 2000000,
}
FLATROCK = {
    "name": "Flatrock AHJ",
    "code": "FLATROCK",
    "repermit_required_for_reinstall": False,
    "reinspection_required": True,
    "inspection_slots_per_day": 2,
    "backlog_days": 2,
    "permit_review_days": 7,
}


def _assert_instant(actual, expected_instant, field):
    """Compare a stamped instant against an expected UTC instant, ignoring millis."""
    assert actual is not None, f"{field} must be stamped, got null"
    assert is_iso8601_timestamp(actual), f"{field} is not an ISO 8601 UTC instant: {actual}"
    normalized = actual.replace("Z", "").split(".")[0]
    assert normalized == expected_instant, (
        f"{field} should be {expected_instant}Z, got {actual}"
    )


def _shape(base, **overrides):
    merged = dict(base)
    merged.update(overrides)
    return merged


def _setup_lease_project_with_hardware_and_paperwork():
    """A LEASE project in INTAKE with a circuit, an ON_ROOF panel, a finding,
    a DRAFT permit and a SCHEDULED roofing window for its own roofer."""
    parties = create_core_parties()
    roofer_b = create_party("ROOFER", name="Summit Roofing", contact_email="ops@summit.example")
    jurisdiction = create_jurisdiction(**FLATROCK)
    project = create_project(parties, ownership_model="LEASE", **_shape(LEASE_SHAPE))
    crew_id = parties["crew"]["id"]
    roofer_id = parties["roofer"]["id"]

    circuit = add_circuit(project["id"], circuit_label="A1", module_count=1, dc_kw=0.41)
    unit = add_unit(
        project["id"], circuit["id"], crew_id, serial_number="SN-0001", rated_watts=410
    )
    finding = add_finding(
        project["id"],
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=10.0,
        attachment_count_affected=0,
    )
    permit = create_permit(project["id"], jurisdiction["id"], scope="REINSTALL_ONLY")
    window = add_window(
        project["id"],
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-01T08:00:00Z",
    )
    return {
        "parties": parties,
        "roofer_b": roofer_b,
        "jurisdiction": jurisdiction,
        "project": project,
        "circuit": circuit,
        "unit": unit,
        "finding": finding,
        "permit": permit,
        "window": window,
    }


class TestRoleAccess:
    """The positive and negative halves of the role matrix."""

    def test_every_role_performs_at_least_one_of_its_own_declared_operations(self):
        """All six roles complete an operation their own role declares.

        PRD §2.1: "`ProjectCoordinator` owns the reference data (parties and
        jurisdictions), the project record, the consent requests, the circuit and bin
        registries, the permit paperwork and its inspection bookings, the crew calendar,
        replacement sourcing and receipt, the manufacturer warranty notice, the credit
        settlement, and the two test-driving capabilities."
        PRD §2.1: "`SolarContractor` alone energizes and de-energizes circuits, registers
        hardware, and drives removal, storage, condition grading and reinstall."
        PRD §2.1: "`RoofingContractor` alone records deck findings and drives their upgrade
        actions."
        PRD §2.1: "`SystemOwner` alone reviews non-exact sourcing orders."
        PRD §2.1: "`AHJInspector` alone decides permit applications and records inspection
        results, and only for its own jurisdiction."
        PRD §2.1: "Advancing a crew window's status is shared by `ProjectCoordinator`,
        `RoofingContractor` and `SolarContractor`."
        PRD §2.1: "Recording a consent decision is shared by `RoofingContractor`,
        `SolarOwner` and `SystemOwner`."
        PRD §2.1: "Where a role acts on a specific resource, the ownership comparison is
        concrete and its failure carries `ERR_PARTY_NOT_ON_PROJECT` (HTTP 403): a consent
        decision requires `X-User-ID` to equal the target consent record's `party_id`; a
        sourcing-order review requires `X-User-ID` to equal the project's
        `system_owner_party_id`; a crew-driven window status change requires `X-User-ID` to
        equal the window's `party_id`; and an `AHJInspector` deciding a permit or recording
        an inspection result requires `X-User-ID` to equal the governing permit
        application's `jurisdiction_id`."

        Design: Corner/rbac/corner_every_role_performs_at_least_one_of_its_own_declared_operations
        """
        set_clock(CLOCK_EPOCH)
        parties = create_core_parties()
        jurisdiction = create_jurisdiction(**FLATROCK)
        project = create_project(parties, ownership_model="LEASE", **_shape(LEASE_SHAPE))
        project_id = project["id"]
        roofer_id = parties["roofer"]["id"]
        owner_id = parties["owner"]["id"]
        sysowner_id = parties["sysowner"]["id"]
        crew_id = parties["crew"]["id"]
        crew_headers = make_solar_contractor_headers(crew_id)
        roofer_headers = make_roofing_contractor_headers(roofer_id)
        ahj_headers = make_ahj_inspector_headers(jurisdiction["id"])

        ap_roof = open_consent(project_id, roofer_id)
        ap_own = open_consent(project_id, owner_id)
        ap_sys = open_consent(project_id, sysowner_id)
        circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)
        storage_bin = add_bin(project_id, bin_label="BIN-1", capacity_slots=2)
        unit = add_unit(
            project_id, circuit["id"], crew_id, serial_number="SN-0001", rated_watts=410
        )

        # The three consenting roles each record their own decision.
        for approval, headers in (
            (ap_roof, roofer_headers),
            (ap_own, make_solar_owner_headers(owner_id)),
            (ap_sys, make_system_owner_headers(sysowner_id)),
        ):
            decided = validate_success(
                api_client.decide_party_approval(
                    approval["id"], {"decision": "APPROVE"}, headers
                ),
                200,
            )
            assert decided["status"] == "APPROVED", decided["status"]

        # The solar crew owns the whole hardware path.
        validate_success(
            api_client.set_circuit_energization(
                circuit["id"],
                {"action": "DE_ENERGIZE", "interlock_verified": True},
                crew_headers,
            ),
            200,
        )
        validate_success(api_client.remove_hardware_unit(unit["id"], crew_headers), 200)
        validate_success(
            api_client.grade_hardware_unit(
                unit["id"],
                {
                    "condition_grade": "DAMAGED",
                    "disposition": "RETAIN",
                    "damage_note": "backsheet delamination",
                },
                crew_headers,
            ),
            200,
        )
        validate_success(
            api_client.store_hardware_unit(
                unit["id"], {"storage_bin_id": storage_bin["id"]}, crew_headers
            ),
            200,
        )

        # The roofer records the deck finding.
        finding = validate_success(
            api_client.create_deck_finding(
                project_id,
                create_deck_finding_payload(
                    finding_type="FASTENER_PULLOUT",
                    severity="LOW",
                    affected_area_sqft=10.0,
                    attachment_count_affected=0,
                ),
                roofer_headers,
            ),
            201,
        )

        # The coordinator raises the order; the system owner reviews the non-exact part.
        pv1 = validate_success(api_client.get_project(project_id, COORD), 200)["version"]
        order = validate_success(
            api_client.create_sourcing_order(
                create_sourcing_order_payload(
                    project_id,
                    unit["id"],
                    pv1,
                    requested_model_code="MS-410",
                    offered_manufacturer="Meridian Solar",
                    offered_model_code="MS-415",
                    offered_rated_watts=420,
                    unit_cost_cents=25900,
                ),
                COORD,
            ),
            201,
        )
        assert order["match_class"] == "COMPATIBLE", order["match_class"]
        assert order["watt_delta_pct"] == pytest.approx(2.44, abs=0.01), (
            order["watt_delta_pct"]
        )
        assert order["tolerance_pct"] == pytest.approx(3.0, abs=0.01), order["tolerance_pct"]
        reviewed = validate_success(
            api_client.review_sourcing_order(
                order["id"],
                {
                    "decision": "APPROVE",
                    "review_note": "same manufacturer, within tolerance",
                },
                make_system_owner_headers(sysowner_id),
            ),
            200,
        )
        assert reviewed["status"] == "APPROVED", reviewed["status"]
        assert reviewed["review_note"] == "same manufacturer, within tolerance", (
            reviewed["review_note"]
        )

        # The coordinator files the paperwork; the AHJ decides it and stamps the result.
        permit = validate_success(
            api_client.create_permit_application(
                create_permit_application_payload(
                    project_id, jurisdiction["id"], scope="REINSTALL_ONLY"
                ),
                COORD,
            ),
            201,
        )
        validate_success(api_client.submit_permit_application(permit["id"], COORD), 200)
        inspection = validate_success(
            api_client.create_inspection(
                permit["id"],
                create_inspection_payload(
                    inspection_type="ROOF_DECK",
                    slot_date="2026-08-05",
                    window_start_utc="2026-08-05T15:00:00Z",
                    window_end_utc="2026-08-05T19:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        decided_permit = validate_success(
            api_client.decide_permit_application(
                permit["id"], {"decision": "APPROVE"}, ahj_headers
            ),
            200,
        )
        assert decided_permit["status"] == "APPROVED", decided_permit["status"]
        stamped = validate_success(
            api_client.record_inspection_result(
                inspection["id"],
                {"result": "PASS", "result_note": "deck fastening acceptable"},
                ahj_headers,
            ),
            200,
        )
        assert stamped["status"] == "PASSED", stamped["status"]
        _assert_instant(stamped["inspected_at"], EPOCH_INSTANT, "Inspection.inspected_at")

        # The shared window-status endpoint is driven by all three roles that declare it,
        # each acting on a window whose party_id is its own.
        w1 = validate_success(
            api_client.create_work_window(
                create_work_window_payload(
                    project_id,
                    crew_id,
                    trade="SOLAR_REINSTALL",
                    start_utc="2026-08-01T00:00:00Z",
                    end_utc="2026-08-01T08:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        started = validate_success(
            api_client.set_work_window_status(w1["id"], {"action": "START"}, COORD), 200
        )
        assert started["status"] == "IN_PROGRESS", started["status"]
        completed = validate_success(
            api_client.set_work_window_status(
                w1["id"], {"action": "COMPLETE"}, crew_headers
            ),
            200,
        )
        assert completed["status"] == "COMPLETED", completed["status"]

        w2 = validate_success(
            api_client.create_work_window(
                create_work_window_payload(
                    project_id,
                    roofer_id,
                    trade="ROOFING",
                    start_utc="2026-08-01T00:00:00Z",
                    end_utc="2026-08-01T08:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        w2_started = validate_success(
            api_client.set_work_window_status(w2["id"], {"action": "START"}, roofer_headers),
            200,
        )
        assert w2_started["status"] == "IN_PROGRESS", w2_started["status"]

        final_project = refresh_project(project_id)
        assert final_project["required_approval_party_count"] == 3, (
            final_project["required_approval_party_count"]
        )
        assert final_project["phase"] == "DECK_WORK", final_project["phase"]
        assert final_project["posture"] == "OPEN", final_project["posture"]

        circuit_after = validate_success(
            api_client.get_array_circuit(circuit["id"], COORD), 200
        )
        assert circuit_after["status"] == "ISOLATED", circuit_after["status"]
        unit_after = validate_success(api_client.get_hardware_unit(unit["id"], COORD), 200)
        assert unit_after["handling_status"] == "STORED", unit_after["handling_status"]
        assert unit_after["condition_grade"] == "DAMAGED", unit_after["condition_grade"]
        finding_after = validate_success(
            api_client.get_deck_finding(finding["id"], COORD), 200
        )
        assert finding_after["status"] == "OPEN", finding_after["status"]

    @pytest.mark.parametrize(
        "case",
        [
            "crew_creates_project",
            "roofer_removes_unit",
            "owner_waives_finding",
            "system_owner_decides_permit",
            "ahj_reviews_sourcing_order",
            "coordinator_deenergizes_circuit",
        ],
    )
    def test_no_role_can_reach_another_roles_exclusive_operation(self, case):
        """Holding some role never grants another role's exclusive endpoint.

        PRD §2.1: "If the headers are well formed but the declared role is not among the
        roles authorized for the endpoint being called, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.1: "`SolarContractor` alone energizes and de-energizes circuits, registers
        hardware, and drives removal, storage, condition grading and reinstall."
        PRD §2.1: "`RoofingContractor` alone records deck findings and drives their upgrade
        actions."
        PRD §2.1: "`SystemOwner` alone reviews non-exact sourcing orders."
        PRD §2.1: "`AHJInspector` alone decides permit applications and records inspection
        results, and only for its own jurisdiction."
        PRD §2.11: "When several rules could reject the same request, they are evaluated in
        a fixed order so that the returned `error_id` is deterministic."

        Design: Corner/rbac/corner_no_role_or_off_project_party_can_reach_another_roles_exclusive_operation
        """
        set_clock(CLOCK_EPOCH)
        ctx = _setup_lease_project_with_hardware_and_paperwork()
        parties = ctx["parties"]
        roofer_id = parties["roofer"]["id"]
        owner_id = parties["owner"]["id"]
        sysowner_id = parties["sysowner"]["id"]
        crew_id = parties["crew"]["id"]
        project_id = ctx["project"]["id"]

        if case == "crew_creates_project":
            response = api_client.create_project(
                create_project_payload(
                    roofer_party_id=roofer_id,
                    solar_owner_party_id=owner_id,
                    solar_contractor_party_id=crew_id,
                    ownership_model="HOST_OWNED",
                    **_shape(HOST_OWNED_SHAPE, site_address="9 Rogue Rd, Tempe AZ"),
                ),
                make_solar_contractor_headers(crew_id),
            )
        elif case == "roofer_removes_unit":
            response = api_client.remove_hardware_unit(
                ctx["unit"]["id"], make_roofing_contractor_headers(roofer_id)
            )
        elif case == "owner_waives_finding":
            response = api_client.upgrade_deck_finding(
                ctx["finding"]["id"],
                {"action": "WAIVE", "waiver_reason": "owner says it looks fine"},
                make_solar_owner_headers(owner_id),
            )
        elif case == "system_owner_decides_permit":
            response = api_client.decide_permit_application(
                ctx["permit"]["id"],
                {"decision": "APPROVE"},
                make_system_owner_headers(sysowner_id),
            )
        elif case == "ahj_reviews_sourcing_order":
            # The order id does not exist, yet the role check at priority 2 still wins.
            response = api_client.review_sourcing_order(
                NON_EXISTENT_UUID,
                {"decision": "APPROVE"},
                make_ahj_inspector_headers(ctx["jurisdiction"]["id"]),
            )
        else:
            response = api_client.set_circuit_energization(
                ctx["circuit"]["id"],
                {"action": "DE_ENERGIZE", "interlock_verified": True},
                COORD,
            )
        validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)

        projects, project_meta = validate_paginated(api_client.list_projects(COORD))
        assert project_meta["total_count"] == 1, project_meta
        assert projects[0]["id"] == project_id, projects

        unit_after = validate_success(
            api_client.get_hardware_unit(ctx["unit"]["id"], COORD), 200
        )
        assert unit_after["handling_status"] == "ON_ROOF", unit_after["handling_status"]
        finding_after = validate_success(
            api_client.get_deck_finding(ctx["finding"]["id"], COORD), 200
        )
        assert finding_after["status"] == "OPEN", finding_after["status"]
        permit_after = validate_success(
            api_client.get_permit_application(ctx["permit"]["id"], COORD), 200
        )
        assert permit_after["status"] == "DRAFT", permit_after["status"]
        circuit_after = validate_success(
            api_client.get_array_circuit(ctx["circuit"]["id"], COORD), 200
        )
        assert circuit_after["status"] == "ENERGIZED", circuit_after["status"]

    def test_an_off_project_party_cannot_drive_a_window_of_this_project(self):
        """The right role is not enough when the acting party owns no interval here.

        PRD §2.1: "Where a role acts on a specific resource, the ownership comparison is
        concrete and its failure carries `ERR_PARTY_NOT_ON_PROJECT` (HTTP 403): a consent
        decision requires `X-User-ID` to equal the target consent record's `party_id`; a
        sourcing-order review requires `X-User-ID` to equal the project's
        `system_owner_party_id`; a crew-driven window status change requires `X-User-ID` to
        equal the window's `party_id`; and an `AHJInspector` deciding a permit or recording
        an inspection result requires `X-User-ID` to equal the governing permit
        application's `jurisdiction_id`."

        Design: Corner/rbac/corner_no_role_or_off_project_party_can_reach_another_roles_exclusive_operation
        """
        set_clock(CLOCK_EPOCH)
        ctx = _setup_lease_project_with_hardware_and_paperwork()
        window = ctx["window"]

        refused = api_client.set_work_window_status(
            window["id"],
            {"action": "START"},
            make_roofing_contractor_headers(ctx["roofer_b"]["id"]),
        )
        validate_error(refused, "ERR_PARTY_NOT_ON_PROJECT", 403)

        window_after = validate_success(api_client.get_work_window(window["id"], COORD), 200)
        assert window_after["status"] == "SCHEDULED", window_after["status"]
        assert window_after.get("actual_start_utc") is None, (
            window_after.get("actual_start_utc")
        )

    def test_the_roofer_that_scoped_an_upgrade_may_not_sign_its_completion(self):
        """Completion is split from scoping by Party identity, not by role.

        PRD §3.6: "Segregation of duties is absolute here: the acting `X-User-ID` must
        differ from the finding's `scoped_by_party_id`, and a roofer attempting to sign off
        its own scope is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "**Completing** takes a finding from `UPGRADE_SCOPED` to
        `UPGRADE_COMPLETED`, stamps `completed_at`, and records the acting `X-User-ID` as
        `completed_by_party_id`."

        Design: Corner/rbac/corner_the_roofer_that_scoped_an_upgrade_may_not_sign_its_completion
        """
        set_clock(CLOCK_EPOCH)
        parties = create_core_parties()
        roofer_b = create_party(
            "ROOFER", name="Summit Roofing", contact_email="ops@summit.example"
        )
        roofer_id = parties["roofer"]["id"]
        project = create_project(
            parties, ownership_model="HOST_OWNED", **_shape(HOST_OWNED_SHAPE)
        )
        finding = add_finding(
            project["id"],
            roofer_id,
            finding_type="MOISTURE_INTRUSION",
            severity="MEDIUM",
            affected_area_sqft=80.0,
            attachment_count_affected=4,
        )
        drive_finding(finding["id"], roofer_id, "SCOPE")

        self_signed = api_client.upgrade_deck_finding(
            finding["id"], {"action": "COMPLETE"}, make_roofing_contractor_headers(roofer_id)
        )
        validate_error(self_signed, "ERR_SEGREGATION_OF_DUTIES", 403)

        completed = validate_success(
            api_client.upgrade_deck_finding(
                finding["id"],
                {"action": "COMPLETE"},
                make_roofing_contractor_headers(roofer_b["id"]),
            ),
            200,
        )
        assert completed["status"] == "UPGRADE_COMPLETED", completed["status"]
        assert completed["scoped_by_party_id"] == roofer_id, (
            completed["scoped_by_party_id"]
        )
        assert completed["completed_by_party_id"] == roofer_b["id"], (
            completed["completed_by_party_id"]
        )
        assert completed["upgrade_cost_cents"] == 106720, completed["upgrade_cost_cents"]
        _assert_instant(
            completed["completed_at"], EPOCH_INSTANT, "DeckFinding.completed_at"
        )

        project_after = refresh_project(project["id"])
        assert project_after["scoped_upgrade_cost_cents"] == 106720, (
            project_after["scoped_upgrade_cost_cents"]
        )
        assert project_after["phase"] == "INTAKE", (
            f"the DECK_WORK advance is a no-op from INTAKE, got {project_after['phase']}"
        )


class TestCrossCuttingLayers:
    """Optimistic concurrency and rollup reconciliation."""

    def test_stale_expected_project_version_on_a_sourcing_order_is_412_then_succeeds(self):
        """An unrelated write invalidates the version token a sourcing order carries.

        PRD §2.9: "If the supplied `expected_project_version` does not equal the project's
        current `version`, the create is rejected with `ERR_STALE_PROJECT_VERSION`
        (HTTP 412)."
        PRD §2.7: "A test-driving capability exists purely so that guard is reachable:
        given a `project_id` and a `released_delta_cents` amount, it adds that amount to
        `credit_released_cents` while leaving `credit_authorized_cents`,
        `credit_reserved_cents` and `credit_settled_cents` untouched, and increments the
        project's `version`."
        PRD §3.8: "An `EXACT` match is `APPROVED` outright."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_project_version_on_a_sourcing_order_is_412_then_succeeds_after_reread
        """
        set_clock(CLOCK_EPOCH)
        ctx = setup_deenergized_project(
            ownership_model="HOST_OWNED",
            circuit_count=1,
            unit_count=1,
            **_shape(HOST_OWNED_SHAPE),
        )
        project_id = ctx["project"]["id"]
        crew_id = ctx["parties"]["crew"]["id"]
        unit = ctx["units"][0]
        remove_unit(unit["id"], crew_id)
        grade_unit(unit["id"], crew_id, "DAMAGED", "RETAIN")

        pv1 = validate_success(api_client.get_project(project_id, COORD), 200)["version"]
        perturbed = validate_success(
            api_client.perturb_ledger(project_id, 0, COORD), 200
        )
        pv2 = perturbed["version"]
        assert pv2 == pv1 + 1, f"the perturbation must bump the version: {pv1} -> {pv2}"

        def order_body(version):
            return create_sourcing_order_payload(
                project_id,
                unit["id"],
                version,
                requested_model_code="MS-410",
                offered_manufacturer="Meridian Solar",
                offered_model_code="MS-410",
                offered_rated_watts=410,
                unit_cost_cents=24500,
            )

        stale = api_client.create_sourcing_order(order_body(pv1), COORD)
        validate_error(stale, "ERR_STALE_PROJECT_VERSION", 412)

        order = validate_success(
            api_client.create_sourcing_order(order_body(pv2), COORD), 201
        )
        assert order["match_class"] == "EXACT", order["match_class"]
        assert order["status"] == "APPROVED", order["status"]

        pv3 = validate_success(api_client.get_project(project_id, COORD), 200)["version"]
        assert pv3 == pv2 + 1, f"the accepted order must bump the version: {pv2} -> {pv3}"

        rows, meta = validate_paginated(
            api_client.list_sourcing_orders(COORD, params={"project_id": project_id})
        )
        assert meta["total_count"] == 1, (
            f"the refused call must persist nothing, got {meta['total_count']} orders"
        )
        assert len(rows) == 1 and rows[0]["id"] == order["id"], rows

    def test_stale_expected_project_version_on_a_warranty_notice_refile_is_412(self):
        """The notice is not written at all when its version token is stale.

        PRD §2.9: "Here too, a supplied `expected_project_version` that does not equal the
        project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP
        412), which prevents a notice being filed against an outdated view of the model of
        record."
        PRD §3.9: "Filing sets `warranty_notice_status` to `FILED`, stamps
        `warranty_notice_filed_at` with the current instant, records the case reference as
        `warranty_notice_reference`, increments the project's `version`, and recomputes
        posture."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_expected_project_version_on_a_warranty_notice_refile_is_412_then_succeeds
        """
        set_clock(CLOCK_EPOCH)
        parties = create_core_parties()
        project = create_project(parties, ownership_model="LEASE", **_shape(LEASE_SHAPE))
        project_id = project["id"]

        before = validate_success(api_client.get_project(project_id, COORD), 200)
        assert before["warranty_notice_status"] == "PENDING", (
            before["warranty_notice_status"]
        )
        pv1 = before["version"]

        pv2 = validate_success(api_client.perturb_ledger(project_id, 0, COORD), 200)[
            "version"
        ]
        assert pv2 == pv1 + 1, f"the perturbation must bump the version: {pv1} -> {pv2}"

        stale = api_client.file_warranty_notice(
            project_id,
            warranty_notice_payload(
                pv1, manufacturer="Meridian Solar", notice_reference="MSN-2026-0418"
            ),
            COORD,
        )
        validate_error(stale, "ERR_STALE_PROJECT_VERSION", 412)

        mid = validate_success(api_client.get_project(project_id, COORD), 200)
        assert mid["warranty_notice_status"] == "PENDING", (
            "the refused filing must leave the notice untouched, got "
            f"{mid['warranty_notice_status']}"
        )
        assert mid.get("warranty_notice_reference") is None, (
            mid.get("warranty_notice_reference")
        )
        assert mid.get("warranty_notice_filed_at") is None, (
            mid.get("warranty_notice_filed_at")
        )

        filed = validate_success(
            api_client.file_warranty_notice(
                project_id,
                warranty_notice_payload(
                    pv2, manufacturer="Meridian Solar", notice_reference="MSN-2026-0418"
                ),
                COORD,
            ),
            200,
        )
        assert filed["warranty_notice_status"] == "FILED", (
            filed["warranty_notice_status"]
        )
        assert filed["warranty_notice_reference"] == "MSN-2026-0418", (
            filed["warranty_notice_reference"]
        )
        _assert_instant(
            filed["warranty_notice_filed_at"],
            EPOCH_INSTANT,
            "ReroofProject.warranty_notice_filed_at",
        )
        assert filed["version"] == pv2 + 1, filed["version"]
        assert filed["phase"] == "INTAKE", filed["phase"]

    def test_rescoping_a_finding_zeroes_its_cost_and_the_project_rollup_recomputes(self):
        """The scoped-cost rollup falls on RESCOPE and rises again on re-SCOPE.

        PRD §3.6: "**Rescoping** is the revert edge, taking a finding from
        `UPGRADE_SCOPED` back to `OPEN`. It resets `upgrade_cost_cents` to zero and clears
        both `scoped_by_party_id` and `scoped_at`, then recomputes
        `scoped_upgrade_cost_cents`, `open_critical_finding_count` and posture."
        PRD §3.6: "The project's `scoped_upgrade_cost_cents` — the sum of
        `upgrade_cost_cents` over the project's findings whose `status` is `UPGRADE_SCOPED`
        or `UPGRADE_COMPLETED` — plus the newly computed cost for this finding must not
        exceed `upgrade_budget_cents`; when it would, the scope is refused with
        `ERR_UPGRADE_BUDGET_EXCEEDED` (HTTP 402)."
        PRD §3.6: "Separately, the attachment subtotal is rounded half up to whole cents
        and compared against a base floor of 50,000 cents, and the larger of those two
        becomes the effective floor."
        PRD §3.6: "The finding's `upgrade_cost_cents` is the larger of the capped figure
        and the effective floor."

        Design: Corner/cross_cutting_complexity_layers/corner_rescoping_a_finding_zeroes_its_cost_and_the_project_rollup_recomputes_both_ways
        """
        set_clock(CLOCK_EPOCH)
        parties = create_core_parties()
        roofer_id = parties["roofer"]["id"]
        project = create_project(
            parties, ownership_model="HOST_OWNED", **_shape(HOST_OWNED_SHAPE)
        )
        project_id = project["id"]
        f1 = add_finding(
            project_id,
            roofer_id,
            finding_type="MOISTURE_INTRUSION",
            severity="MEDIUM",
            affected_area_sqft=80.0,
            attachment_count_affected=4,
        )
        f2 = add_finding(
            project_id,
            roofer_id,
            finding_type="FASTENER_PULLOUT",
            severity="LOW",
            affected_area_sqft=10.0,
            attachment_count_affected=0,
        )
        roofer_headers = make_roofing_contractor_headers(roofer_id)

        scoped_f1 = validate_success(
            api_client.upgrade_deck_finding(f1["id"], {"action": "SCOPE"}, roofer_headers),
            200,
        )
        assert scoped_f1["upgrade_cost_cents"] == 106720, (
            scoped_f1["upgrade_cost_cents"]
        )
        scoped_f2 = validate_success(
            api_client.upgrade_deck_finding(f2["id"], {"action": "SCOPE"}, roofer_headers),
            200,
        )
        assert scoped_f2["upgrade_cost_cents"] == 50000, (
            f"the 50,000-cent floor must lift the raw 9,500, got "
            f"{scoped_f2['upgrade_cost_cents']}"
        )
        assert scoped_f2["status"] == "UPGRADE_SCOPED", scoped_f2["status"]

        rollup_both = refresh_project(project_id)["scoped_upgrade_cost_cents"]
        assert rollup_both == 156720, rollup_both

        rescoped = validate_success(
            api_client.upgrade_deck_finding(f1["id"], {"action": "RESCOPE"}, roofer_headers),
            200,
        )
        assert rescoped["status"] == "OPEN", rescoped["status"]
        assert rescoped["upgrade_cost_cents"] == 0, rescoped["upgrade_cost_cents"]
        assert rescoped.get("scoped_by_party_id") is None, (
            rescoped.get("scoped_by_party_id")
        )
        assert rescoped.get("scoped_at") is None, rescoped.get("scoped_at")

        rollup_after_rescope = refresh_project(project_id)["scoped_upgrade_cost_cents"]
        assert rollup_after_rescope == 50000, (
            f"the rollup must fall to the surviving finding, got {rollup_after_rescope}"
        )

        rescoped_again = validate_success(
            api_client.upgrade_deck_finding(f1["id"], {"action": "SCOPE"}, roofer_headers),
            200,
        )
        assert rescoped_again["upgrade_cost_cents"] == 106720, (
            rescoped_again["upgrade_cost_cents"]
        )
        assert rescoped_again["status"] == "UPGRADE_SCOPED", rescoped_again["status"]
        assert rescoped_again["scoped_by_party_id"] == roofer_id, (
            rescoped_again["scoped_by_party_id"]
        )
        _assert_instant(
            rescoped_again["scoped_at"], EPOCH_INSTANT, "DeckFinding.scoped_at"
        )

        project_after = refresh_project(project_id)
        assert project_after["scoped_upgrade_cost_cents"] == 156720, (
            project_after["scoped_upgrade_cost_cents"]
        )
        assert project_after["posture"] == "OPEN", project_after["posture"]
        assert project_after["open_critical_finding_count"] == 0, (
            project_after["open_critical_finding_count"]
        )

        f2_after = validate_success(api_client.get_deck_finding(f2["id"], COORD), 200)
        assert f2_after["upgrade_cost_cents"] == 50000, f2_after["upgrade_cost_cents"]
        assert f2_after["status"] == "UPGRADE_SCOPED", f2_after["status"]


def test_every_cascaded_change_is_visible_immediately_without_a_second_write():
    """One storage call publishes a four-level cascade in the same request.

    PRD §2.10: "Whenever a child row changes in a way that affects a derived project
    figure, the server recomputes that figure in the same request, refreshes the project's
    `updated_at` and increments its `version`."
    PRD §3.5: "On success the unit's `storage_bin_id` is written, `storage_position` is
    either the supplied value or the bin's `occupied_slots` plus one at that moment, and
    `storage_label` is composed as the bin's `bin_label` followed by a hyphen and the
    `storage_position`."
    PRD §3.5: "`handling_status` becomes `STORED`, `stored_at` is stamped, the target bin's
    `occupied_slots` is recomputed, and the project's `stored_unit_count` is recomputed."
    PRD §3.5: "That advance requires the project's `phase` to be `DEENERGIZED`,
    `registered_unit_count` to be at least 1, and the count of the project's units whose
    `handling_status` is neither `STORED` nor `SCRAPPED` to be zero — in other words, every
    registered unit is either safely in a bin or written off."

    Design: Corner/consistency_model/corner_every_cascaded_change_is_visible_immediately_without_a_second_write
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_deenergized_project(
        ownership_model="HOST_OWNED",
        circuit_count=1,
        unit_count=1,
        **_shape(HOST_OWNED_SHAPE),
    )
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    crew_headers = make_solar_contractor_headers(crew_id)
    unit = ctx["units"][0]
    storage_bin = add_bin(project_id, bin_label="BIN-1", capacity_slots=4)
    remove_unit(unit["id"], crew_id)

    write_response = validate_success(
        api_client.store_hardware_unit(
            unit["id"], {"storage_bin_id": storage_bin["id"]}, crew_headers
        ),
        200,
    )
    assert write_response["handling_status"] == "STORED", (
        write_response["handling_status"]
    )
    assert write_response["storage_label"] == "BIN-1-1", (
        f"the write response must already carry the derived label, got "
        f"{write_response.get('storage_label')}"
    )
    assert write_response["storage_position"] == 1, write_response["storage_position"]
    assert write_response["storage_bin_id"] == storage_bin["id"], (
        write_response["storage_bin_id"]
    )
    _assert_instant(write_response["stored_at"], EPOCH_INSTANT, "HardwareUnit.stored_at")

    bin_now = validate_success(
        api_client.get_storage_bin(storage_bin["id"], crew_headers), 200
    )
    assert bin_now["occupied_slots"] == 1, (
        f"bin occupancy must not lag the write, got {bin_now['occupied_slots']}"
    )

    project_now = validate_success(api_client.get_project(project_id, COORD), 200)
    assert project_now["stored_unit_count"] == 1, project_now["stored_unit_count"]
    assert project_now["phase"] == "DECK_WORK", (
        f"the phase bubble must fire in the same request, got {project_now['phase']}"
    )
    assert project_now["registered_unit_count"] == 1, (
        project_now["registered_unit_count"]
    )
    assert project_now["scrapped_unit_count"] == 0, project_now["scrapped_unit_count"]
