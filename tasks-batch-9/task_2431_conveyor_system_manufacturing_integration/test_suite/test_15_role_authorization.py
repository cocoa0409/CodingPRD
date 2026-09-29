"""Role authorization, customer binding and the two-person acceptance rule."""

from test_helpers import (
    CUSTOMER_REP,
    DESIGN_ENGINEER,
    PROJECT_DIRECTOR,
    SHOP_SUPERVISOR,
    SITE_MANAGER,
    ApiErrorId,
    assert_acceptance_certificate,
    assert_project,
    create_acceptance_certificate_payload,
    create_simulation_payload,
    make_completed_cutover,
    make_customer_rep_headers,
    make_fat_passed_lot,
    make_project,
    make_project_director_headers,
    make_scheduled_window,
    make_simulated_design,
    make_site_manager_headers,
    make_staging_bay,
    make_submitted_change_order,
    read_change_order,
    read_project,
    record_ramp,
    review_decision_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheTwoIntegratorDesksAreNotAHierarchy:
    """Each desk owns its own act, and neither may perform the other's."""

    def test_the_engineer_may_not_freeze_the_design(self, api):
        """Every freeze precondition is satisfied and the role alone refuses it.

        PRD §3.4: "The design freeze is the contractual hand-off from engineering to
        manufacturing, and only a `ProjectDirector` may perform it."

        Design: Corner/rbac/design_freeze_and_simulation_are_refused_across_the_two_integrator_desks
        """
        design = make_simulated_design(api)
        project_id = design["project"]["id"]
        assert design["simulation"]["effective_throughput_cph"] == 1330

        response = api.design_freeze(project_id, DESIGN_ENGINEER)
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        after = read_project(api, project_id)
        assert after["delivery_status"] == "DESIGN"
        assert after["design_frozen_at"] is None

    def test_the_director_may_not_run_a_simulation(self, api):
        """The refused run leaves the single degraded run standing as the only history.

        PRD §3.3: "Simulation is the heart of the concept-design phase, and only a
        `DesignEngineer` may run one."

        Design: Corner/rbac/design_freeze_and_simulation_are_refused_across_the_two_integrator_desks
        """
        design = make_simulated_design(api)
        project_id = design["project"]["id"]

        response = api.run_simulation(
            project_id, create_simulation_payload("DETERMINISTIC_STEADY_STATE"), PROJECT_DIRECTOR
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        runs, meta = validate_paginated(api.list_simulation_runs(project_id, DESIGN_ENGINEER))
        assert meta["total_count"] == 1
        assert runs[0]["id"] == design["simulation"]["id"]
        assert runs[0]["method"] == "DEGRADED_AVAILABILITY"
        assert runs[0]["status"] == "COMPLETE"
        assert runs[0]["effective_throughput_cph"] == 1330

    def test_the_same_fixture_freezes_for_the_director(self, api):
        """The two refusals wrote nothing, so the authorised call still succeeds.

        PRD §2.1: "If the headers are well-formed but the declared role is not among the
        roles authorized for the endpoint being called (see the authorization column of the
        endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
        403)."

        Design: Corner/rbac/design_freeze_and_simulation_are_refused_across_the_two_integrator_desks
        """
        design = make_simulated_design(api)
        project_id = design["project"]["id"]
        api.design_freeze(project_id, DESIGN_ENGINEER)
        api.run_simulation(
            project_id, create_simulation_payload("DETERMINISTIC_STEADY_STATE"), PROJECT_DIRECTOR
        )

        frozen = validate_success(api.design_freeze(project_id, PROJECT_DIRECTOR))
        assert frozen["delivery_status"] == "DESIGN_FROZEN"
        assert frozen["design_frozen_at"] is not None


class TestTheRoleGateRunsAheadOfTheStateGate:
    """A wrong-role call on a hopeless project reports the role, not the state."""

    def test_a_site_manager_may_not_issue_a_certificate(self, api):
        """The project is in DESIGN and unready, yet the answer is still 403 on the role.

        PRD §2.12: "2. **Role authorization** — the acting role appears in the endpoint's
        authorized list, otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every
        endpoint."

        Design: Corner/rbac/site_manager_is_refused_certificate_issuance_before_any_state_check_runs
        """
        project = make_project(api, facility_code="DC-ATL-31")

        response = api.create_acceptance_certificate(
            create_acceptance_certificate_payload(project["id"]), SITE_MANAGER
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

        after = read_project(api, project["id"])
        assert after["delivery_status"] == "DESIGN"
        assert after["acceptance_ready"] is False
        assert after["version"] == 1
        _, meta = validate_paginated(
            api.list_acceptance_certificates(project["id"], PROJECT_DIRECTOR)
        )
        assert meta["total_count"] == 0


class TestTheProjectReadIsSharedByEveryRole:
    """Reading is universal; the customer binding constrains writes only."""

    def test_all_five_roles_read_the_identical_ledgers(self, api):
        """One row, five callers, one representation.

        PRD §3.1: "Any operator of any of the five roles may read a project back, which
        returns both status dimensions together with the contract ledger, the share ledger
        and the spares ledger in one object."

        Design: Corner/rbac/every_role_can_read_the_project_through_the_shared_get
        """
        project = make_project(api, facility_code="DC-ATL-32")

        for headers in (
            PROJECT_DIRECTOR,
            DESIGN_ENGINEER,
            SHOP_SUPERVISOR,
            SITE_MANAGER,
            CUSTOMER_REP,
        ):
            seen = validate_success(api.get_project(project["id"], headers))
            assert_project(seen)
            assert seen["contract_value_cents"] == 243_600_000
            assert seen["escalation_fee_cents"] == 3_600_000
            assert seen["legacy_share_bps"] == 10000
            assert seen["delivery_status"] == "DESIGN"
            assert seen["commercial_status"] == "CLEAN"
            assert seen["version"] == 1

    def test_an_unbound_customer_rep_may_still_read(self, api):
        """cust-rep-99 is nobody's representative here and the read is still 200.

        PRD §2.12: "3. **Customer ownership** — when the acting role is `CustomerRep`,
        `X-User-ID` equals the `customer_rep_user_id` of the project reached through the
        target resource, otherwise `ERR_NOT_PROJECT_CUSTOMER` (403). Applies to exactly two
        operations: recording a change-order decision, and filing a performance dispute."

        Design: Corner/rbac/every_role_can_read_the_project_through_the_shared_get
        """
        project = make_project(api, facility_code="DC-ATL-32")
        assert project["customer_rep_user_id"] == CUSTOMER_REP["X-User-ID"]

        seen = validate_success(
            api.get_project(project["id"], make_customer_rep_headers("cust-rep-99"))
        )
        assert seen["id"] == project["id"]
        assert seen["contract_value_cents"] == 243_600_000
        assert seen["version"] == 1


class TestOnlyTheBoundRepDecidesAChangeOrder:
    """Correct role, wrong operator: the ownership band fires before the version pin."""

    def test_an_unbound_rep_is_refused_the_decision(self, api):
        """The version pin is correct, so the failure can only be the binding.

        PRD §3.8: "The acting rep's `X-User-ID` must equal the governing project's
        `customer_rep_user_id`, otherwise the request is rejected with
        `ERR_NOT_PROJECT_CUSTOMER`."

        Design: Corner/rbac/only_the_bound_customer_rep_can_record_a_change_order_decision
        """
        project = make_project(api, facility_code="DC-ATL-33")
        change_order = make_submitted_change_order(
            api,
            project["id"],
            title="Spare parts uplift",
            scope_delta_cph=0,
            price_delta_cents=10_000_000,
            schedule_delta_days=0,
        )
        pinned = read_project(api, project["id"])["version"]

        response = api.review_change_order(
            change_order["id"],
            review_decision_payload("APPROVE", pinned),
            make_customer_rep_headers("cust-rep-99"),
        )
        validate_error(response, ApiErrorId.ERR_NOT_PROJECT_CUSTOMER.value)

        assert read_change_order(api, change_order["id"])["status"] == "SUBMITTED"
        after = read_project(api, project["id"])
        assert after["version"] == pinned
        assert after["contract_value_cents"] == 243_600_000

    def test_the_bound_rep_approves_the_identical_request(self, api):
        """Same order, same pinned version, and the repricing now runs.

        PRD §3.8: "First the contract is repriced: the subtotal becomes
        `contract_base_cents` plus the sum of `price_delta_cents` over every change order of
        the project whose `status` is `APPROVED`, **including the order being approved in
        this very request**; the escalation tier is re-selected on that pre-fee subtotal
        exactly as in §3.1; `escalation_fee_cents` and `contract_value_cents` are
        refreshed."

        Design: Corner/rbac/only_the_bound_customer_rep_can_record_a_change_order_decision
        """
        project = make_project(api, facility_code="DC-ATL-33")
        change_order = make_submitted_change_order(
            api,
            project["id"],
            title="Spare parts uplift",
            scope_delta_cph=0,
            price_delta_cents=10_000_000,
            schedule_delta_days=0,
        )
        pinned = read_project(api, project["id"])["version"]
        api.review_change_order(
            change_order["id"],
            review_decision_payload("APPROVE", pinned),
            make_customer_rep_headers("cust-rep-99"),
        )

        decided = validate_success(
            api.review_change_order(
                change_order["id"], review_decision_payload("APPROVE", pinned), CUSTOMER_REP
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["reviewed_by_user_id"] == CUSTOMER_REP["X-User-ID"]

        after = read_project(api, project["id"])
        assert after["escalation_fee_cents"] == 3_750_000
        assert after["contract_value_cents"] == 253_750_000
        assert after["commercial_status"] == "CLEAN"
        assert after["delivery_status"] == "DESIGN"


class TestSegregationBindsOnlyTheFullRateRecorder:
    """Recording the lower levels does not disqualify an issuer."""

    def test_the_recorder_of_the_lower_steps_may_still_issue(self, api):
        """op-201 held the 50 and 75 demonstrations; op-202 held the full-rate one.

        PRD §2.1: "the check is on the raw `X-User-ID` string rather than on the role, and
        it fires whenever the issuing `X-User-ID` equals the `recorded_by_user_id` stored on
        that passing full-rate step."

        Design: Corner/rbac/segregation_of_duties_binds_only_the_recorder_of_the_final_ramp_step
        """
        state = make_completed_cutover(
            api,
            state=make_scheduled_window(
                api,
                state=make_fat_passed_lot(
                    api,
                    bay=make_staging_bay(api, bay_code="BAY-34", concurrent_capacity=1),
                    segment_codes=["IB-01", "TR-02"],
                    lot_code="LOT-3400",
                    measured_cph=1313,
                    defect_count=0,
                ),
            ),
        )
        project_id = state["project"]["id"]
        lower_desk = make_site_manager_headers("op-201")
        full_rate_desk = make_site_manager_headers("op-202")
        record_ramp(api, project_id, 50, 700, 30, headers=lower_desk)
        record_ramp(api, project_id, 75, 1000, 60, headers=lower_desk)
        full_rate = record_ramp(api, project_id, 100, 1260, 120, headers=full_rate_desk)
        assert full_rate["recorded_by_user_id"] == "op-202"
        assert full_rate["verdict"] == "PASS"

        certificate = validate_success(
            api.create_acceptance_certificate(
                create_acceptance_certificate_payload(project_id),
                make_project_director_headers("op-201"),
            ),
            expected_status=201,
        )
        assert_acceptance_certificate(certificate)
        assert certificate["issued_by_user_id"] == "op-201"
        assert certificate["accepted_throughput_cph"] == 1260
        assert certificate["retention_amount_cents"] == 12_180_000
        assert certificate["retention_release_cents"] == 0
        assert certificate["status"] == "ISSUED"

        after = read_project(api, project_id)
        assert after["delivery_status"] == "ACCEPTED"
        assert after["commercial_status"] == "CLEAN"
