"""Dependent registration, the intake eligibility gates and caller-scope boundaries."""

import pytest
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_dependent,
    create_employee,
    create_provider,
    make_employee_user_headers,
    make_provider_manager_headers,
    reservation_payload,
    setup_enrolled_employee,
    validate_error,
    validate_paginated,
    validate_success,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
BENEFITS_ADMIN = TEST_USERS["benefits_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]


class TestDependentTraversal:
    def test_reservations_and_dependents_are_queryable_from_either_side(self, api):
        """The frozen dependent array is searchable, and dependents list per employee.

        PRD 3.4: "a `dependent_id` filter searches inside the frozen dependent
        array, and `employee_id`, `fulfillment_status`, `billing_status`,
        `care_date` and `market_code` narrow further".

        Design: Corner/entities/corner_reservation_dependent_many_to_many_queryable_from_both_sides
        """
        world = setup_enrolled_employee(api, dependent_count=2)
        d1, d2 = world["dependent_ids"]

        first = validate_success(
            api.create_reservation(
                reservation_payload(
                    world["employee"]["id"],
                    [d1, d2],
                    "2026-08-14T09:00:00Z",
                    "2026-08-14T15:00:00Z",
                ),
                CARE_COORDINATOR,
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_reservation(
                reservation_payload(
                    world["employee"]["id"],
                    [d1],
                    "2026-08-15T09:00:00Z",
                    "2026-08-15T15:00:00Z",
                ),
                CARE_COORDINATOR,
            ),
            expected_status=201,
        )
        assert first["fulfillment_status"] == "INTAKE"
        assert second["fulfillment_status"] == "INTAKE"

        rows, meta = validate_paginated(
            api.list_reservations(CARE_COORDINATOR, params={"dependent_id": d1})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}

        rows, meta = validate_paginated(
            api.list_reservations(CARE_COORDINATOR, params={"dependent_id": d2})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

        rows, meta = validate_paginated(
            api.list_dependents(world["employee"]["id"], BENEFITS_ADMIN, params={"status": "ACTIVE"})
        )
        assert meta["total_count"] == 2


class TestIntakeEligibilityGates:
    def test_child_only_plan_refuses_elder_and_inactive_dependents(self, api):
        """Dependent type and dependent status are both eligibility failures.

        PRD 3.4: "Then each dependent must have `status` `ACTIVE` and a
        `dependent_type` present in the plan's `eligible_dependent_types`".

        Design: Corner/validations/corner_adult_elder_dependent_rejected_by_child_only_plan
        """
        world = setup_enrolled_employee(
            api,
            dependent_count=0,
            plan_overrides={"eligible_dependent_types": ["CHILD"]},
        )
        employee_id = world["employee"]["id"]

        elder = create_dependent(
            api, employee_id, dependent_type="ADULT_ELDER", relationship="PARENT"
        )
        inactive_child = create_dependent(api, employee_id, status="INACTIVE")
        good_child = create_dependent(api, employee_id)

        window = ("2026-08-14T09:00:00Z", "2026-08-14T15:00:00Z")
        for dependent_ids in ([elder["id"]], [inactive_child["id"]], [good_child["id"], elder["id"]]):
            validate_error(
                api.create_reservation(
                    reservation_payload(employee_id, dependent_ids, *window), CARE_COORDINATOR
                ),
                ApiErrorId.ERR_DEPENDENT_NOT_ELIGIBLE.value,
            )

        accepted = validate_success(
            api.create_reservation(
                reservation_payload(employee_id, [good_child["id"]], *window), CARE_COORDINATOR
            ),
            expected_status=201,
        )
        assert accepted["fulfillment_status"] == "INTAKE"
        assert accepted["dependent_count"] == 1
        assert accepted["dependent_type_mix"] == "CHILD_ONLY"

        _, meta = validate_paginated(api.list_employee_reservations(employee_id, CARE_COORDINATOR))
        assert meta["total_count"] == 1

    def test_employer_extension_switch_gates_elder_care_even_on_a_permitting_plan(self, api):
        """The employer-level switch overrides plan-level type eligibility.

        PRD 3.4: "an `ADULT_ELDER` dependent additionally requires the employer's
        `adult_elder_extension_enabled` to be true — the adult and elder extension
        is an employer-level switch that overrides plan eligibility".

        Design: Corner/validations/corner_adult_elder_extension_flag_gates_elder_reservation
        """
        world = setup_enrolled_employee(
            api,
            dependent_count=0,
            employer_overrides={"adult_elder_extension_enabled": False},
            plan_overrides={"eligible_dependent_types": ["CHILD", "ADULT_ELDER"]},
        )
        employee_id = world["employee"]["id"]
        elder = create_dependent(
            api, employee_id, dependent_type="ADULT_ELDER", relationship="PARENT"
        )
        payload = reservation_payload(
            employee_id, [elder["id"]], "2026-08-14T09:00:00Z", "2026-08-14T15:00:00Z"
        )

        validate_error(
            api.create_reservation(payload, CARE_COORDINATOR),
            ApiErrorId.ERR_DEPENDENT_NOT_ELIGIBLE.value,
        )

        validate_success(
            api.patch_employer(
                world["employer"]["id"], {"adult_elder_extension_enabled": True}, BENEFITS_ADMIN
            )
        )

        accepted = validate_success(
            api.create_reservation(payload, CARE_COORDINATOR), expected_status=201
        )
        assert accepted["fulfillment_status"] == "INTAKE"
        assert accepted["dependent_type_mix"] == "ADULT_ELDER_ONLY"
        assert accepted["required_seats"] == 1

    def test_dependent_count_exactly_at_the_ceiling_is_accepted_and_one_more_is_not(self, api):
        """Exactly at the limit passes; a duplicated id fails request shape first.

        PRD 3.4: "Then the number of dependents named may not exceed the pinned
        plan's `max_dependents_per_reservation`; exactly at the limit is accepted,
        and beyond it returns `ERR_TOO_MANY_DEPENDENTS`."

        Design: Corner/validations/corner_exactly_three_dependents_pass_four_rejected
        """
        world = setup_enrolled_employee(
            api, dependent_count=4, plan_overrides={"max_dependents_per_reservation": 3}
        )
        employee_id = world["employee"]["id"]
        d1, d2, d3, d4 = world["dependent_ids"]
        window = ("2026-08-14T09:00:00Z", "2026-08-14T15:00:00Z")

        accepted = validate_success(
            api.create_reservation(
                reservation_payload(employee_id, [d1, d2, d3], *window), CARE_COORDINATOR
            ),
            expected_status=201,
        )
        assert accepted["dependent_count"] == 3
        assert accepted["required_seats"] == 3

        validate_error(
            api.create_reservation(
                reservation_payload(employee_id, [d1, d2, d3, d4], *window), CARE_COORDINATOR
            ),
            ApiErrorId.ERR_TOO_MANY_DEPENDENTS.value,
        )

        # A duplicated dependent breaks request shape, which is band 1, not band 10.
        validate_error(
            api.create_reservation(
                reservation_payload(employee_id, [d1, d1], *window), CARE_COORDINATOR
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        _, meta = validate_paginated(api.list_employee_reservations(employee_id, CARE_COORDINATOR))
        assert meta["total_count"] == 1

    def test_dependent_resolution_precedes_ownership_which_precedes_eligibility(self, api):
        """Not-found, not-owned and not-eligible fire in that band order.

        PRD 2.8 band 3: "Path identifiers resolve first, strictly left to right, so
        the outermost identifier in a nested path is the one whose absence is
        reported".

        Design: Corner/validations/corner_id_resolution_runs_before_ownership_then_eligibility
        """
        from test_helpers import NON_EXISTENT_UUID

        world = setup_enrolled_employee(api, dependent_count=0)
        employee_a = world["employee"]
        employee_b = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_other"
        )
        foreign_dependent = create_dependent(api, employee_b["id"])
        own_inactive = create_dependent(api, employee_a["id"], status="INACTIVE")
        window = ("2026-08-14T09:00:00Z", "2026-08-14T15:00:00Z")

        validate_error(
            api.create_reservation(
                reservation_payload(employee_a["id"], [NON_EXISTENT_UUID], *window),
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_DEPENDENT_NOT_FOUND.value,
        )
        validate_error(
            api.create_reservation(
                reservation_payload(employee_a["id"], [foreign_dependent["id"]], *window),
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_DEPENDENT_NOT_OWNED.value,
        )
        validate_error(
            api.create_reservation(
                reservation_payload(employee_a["id"], [own_inactive["id"]], *window),
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_DEPENDENT_NOT_ELIGIBLE.value,
        )

        validate_success(
            api.patch_dependent(own_inactive["id"], {"status": "ACTIVE"}, BENEFITS_ADMIN)
        )
        accepted = validate_success(
            api.create_reservation(
                reservation_payload(employee_a["id"], [own_inactive["id"]], *window),
                CARE_COORDINATOR,
            ),
            expected_status=201,
        )
        assert accepted["fulfillment_status"] == "INTAKE"

        _, meta_a = validate_paginated(
            api.list_employee_reservations(employee_a["id"], CARE_COORDINATOR)
        )
        _, meta_b = validate_paginated(
            api.list_employee_reservations(employee_b["id"], CARE_COORDINATOR)
        )
        assert meta_a["total_count"] == 1
        assert meta_b["total_count"] == 0


class TestCallerIdentityBoundaries:
    def test_all_three_intake_roles_derive_the_same_reservation(self, api):
        """The caller's role changes nothing about the derived reservation.

        PRD 3.4: "A reservation may be opened by a `care_coordinator`, a
        `benefits_admin`, or the employee themselves."

        Design: Corner/rbac/corner_shared_reservation_intake_accepted_for_all_three_peer_roles
        """
        world = setup_enrolled_employee(
            api,
            dependent_count=2,
            plan_overrides={"annual_use_limit_days": 10},
            user_id="u_ee_sh1",
        )
        employee_id = world["employee"]["id"]
        employee_headers = make_employee_user_headers("u_ee_sh1")
        d1, d2 = world["dependent_ids"]
        d3 = create_dependent(api, employee_id, headers=BENEFITS_ADMIN)["id"]

        by_coordinator = validate_success(
            api.create_reservation(
                reservation_payload(
                    employee_id, [d1], "2026-08-18T09:00:00Z", "2026-08-18T15:00:00Z"
                ),
                CARE_COORDINATOR,
            ),
            expected_status=201,
        )
        by_admin = validate_success(
            api.create_reservation(
                reservation_payload(
                    employee_id, [d2], "2026-08-19T09:00:00Z", "2026-08-19T15:00:00Z"
                ),
                BENEFITS_ADMIN,
            ),
            expected_status=201,
        )
        by_employee = validate_success(
            api.create_reservation(
                reservation_payload(
                    employee_id, [d3], "2026-08-20T09:00:00Z", "2026-08-20T15:00:00Z"
                ),
                employee_headers,
            ),
            expected_status=201,
        )

        assert len({by_coordinator["id"], by_admin["id"], by_employee["id"]}) == 3
        for reservation in (by_coordinator, by_admin, by_employee):
            assert reservation["fulfillment_status"] == "INTAKE"
            # Intake consumes no entitlement whatsoever.
            assert reservation["days_charged_provisional"] == pytest.approx(0, abs=0.01)
        assert by_coordinator["required_seats"] == 1
        assert by_employee["benefit_plan_id"] == world["plan"]["id"]

        entitlement = validate_success(api.get_entitlement(employee_id, employee_headers))
        assert entitlement["days_used"] == pytest.approx(0, abs=0.01)
        assert entitlement["days_reserved"] == pytest.approx(0, abs=0.01)
        assert entitlement["days_remaining"] == pytest.approx(10, abs=0.01)

    def test_scoped_roles_are_denied_outside_their_own_row_but_served_inside_it(self, api):
        """employee_user and provider_manager reach only their own records.

        PRD 2.8 band 2: "then an `employee_user` caller must be acting within its
        own employee record, which is enforced on exactly seven surfaces".

        Design: Corner/rbac/corner_employee_and_provider_scope_boundaries_return_forbidden_scope
        """
        world = setup_enrolled_employee(
            api,
            dependent_count=0,
            plan_overrides={"annual_use_limit_days": 6},
            user_id="u_ee_sc1",
        )
        employee_1 = world["employee"]
        employee_2 = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_sc2"
        )
        caller = make_employee_user_headers("u_ee_sc1")

        validate_error(
            api.get_entitlement(employee_2["id"], caller), ApiErrorId.ERR_FORBIDDEN_SCOPE.value
        )

        own = validate_success(api.get_entitlement(employee_1["id"], caller))
        assert own["days_limit"] == pytest.approx(6, abs=0.01)
        assert own["days_remaining"] == pytest.approx(6, abs=0.01)
        assert own["eligibility_status"] == "ELIGIBLE"

        validate_error(
            api.list_dependents(employee_2["id"], caller), ApiErrorId.ERR_FORBIDDEN_SCOPE.value
        )

        provider_a = create_provider(
            api, owner_user_id="u_pm_a", market_code="MKT-DEN", provider_name="Denver Center A"
        )
        provider_b = create_provider(
            api, owner_user_id="u_pm_b", market_code="MKT-DEN", provider_name="Denver Center B"
        )
        manager_a = make_provider_manager_headers("u_pm_a")
        block_payload = {
            "start_time_utc": "2026-08-25T08:00:00Z",
            "end_time_utc": "2026-08-25T18:00:00Z",
            "total_slots": 4,
        }

        validate_error(
            api.create_capacity_block(provider_b["id"], block_payload, manager_a),
            ApiErrorId.ERR_FORBIDDEN_SCOPE.value,
        )
        own_block = validate_success(
            api.create_capacity_block(provider_a["id"], block_payload, manager_a),
            expected_status=201,
        )
        assert own_block["provider_id"] == provider_a["id"]
        assert own_block["block_status"] == "OPEN"

        validate_error(
            api.create_credential(
                provider_b["id"],
                {
                    "credential_type": "LICENSE",
                    "issued_on": "2026-01-02",
                    "expires_on": "2027-06-30",
                    "verified_by": "u_pm_a",
                },
                manager_a,
            ),
            ApiErrorId.ERR_FORBIDDEN_SCOPE.value,
        )
        _, meta = validate_paginated(api.list_credentials(provider_b["id"], NETWORK_ADMIN))
        assert meta["total_count"] == 0
        assert validate_success(api.get_provider(provider_b["id"], NETWORK_ADMIN))[
            "network_status"
        ] == "PENDING"
