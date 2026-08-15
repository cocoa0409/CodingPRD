"""Lessee/railcar registry creation rules, response envelope, pagination,
and domain 404 errors."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_lessee,
    assert_railcar,
    create_capital_pool_payload,
    create_lease_agreement_payload,
    create_lessee_payload,
    create_railcar_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
LEASE_ADMIN = TEST_USERS["lease_admin_headers"]
PLANNER = TEST_USERS["fleet_planner_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


class TestLesseeCreation:
    def test_lessee_creation_applies_defaults(self, api):
        """PRD §3.1: "The lessee enters life `ACTIVE` with an
        `outstanding_balance_cents` of zero."
        PRD §2.5: "Before any client sets it, the logical clock reads exactly
        2026-08-01T00:00:00Z."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation of the resource, including
        mutations driven by cascades and derived-field recomputation."

        Design: Corner/entities/lessee_creation_applies_defaults
        """
        resp = api.create_lessee(
            create_lessee_payload(
                company_name="New Lessee",
                credit_tier="TIER_B",
                credit_limit_cents=500000,
                security_deposit_cents=100000,
            ),
            LEASE_ADMIN,
        )
        lessee = validate_success(resp, 201)
        assert_lessee(lessee)
        assert lessee["status"] == "ACTIVE", "A new lessee enters life ACTIVE"
        assert lessee["outstanding_balance_cents"] == 0
        assert lessee["version"] == 1, "A new resource is at version 1"
        assert lessee["created_at"][:19] == "2026-08-01T00:00:00", (
            "created_at is stamped from the logical clock, whose default "
            "reading is 2026-08-01T00:00:00Z"
        )


class TestRailcarRegistry:
    def test_railcar_duplicate_mark_rejected(self, api):
        """PRD §3.2: "A `FleetPlanner` registers each car with its `car_mark`
        reporting mark (unique across the fleet — duplicates are rejected with
        `ERR_DUPLICATE_CAR_MARK`, 409), a `car_type` of `BOX`,
        `COVERED_HOPPER`, `GONDOLA`, `FLAT`, `TANK_GENERAL`, or
        `TANK_PRESSURE`, and a `built_year` between 1900 and 2100."

        Design: Corner/entities/railcar_duplicate_mark_rejected
        """
        first = get_success_data(
            api.create_railcar(
                create_railcar_payload(
                    car_mark="GATX1001", car_type="BOX", built_year=2018
                ),
                PLANNER,
            )
        )
        resp = api.create_railcar(
            create_railcar_payload(
                car_mark="GATX1001", car_type="GONDOLA", built_year=2020
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CAR_MARK)
        after = get_success_data(api.get_railcar(first["id"], PLANNER))
        assert after["car_type"] == "BOX", "First registration is untouched"
        assert after["built_year"] == 2018

    def test_railcar_missing_car_type_returns_validation(self, api):
        """PRD §2.6: "5. **Body shape** — required fields present, types
        correct, enum membership valid, numeric ranges respected; failure
        yields `ERR_VALIDATION` (400)."
        PRD §3.2 requires every new car to carry "a `car_type` of `BOX`,
        `COVERED_HOPPER`, `GONDOLA`, `FLAT`, `TANK_GENERAL`, or
        `TANK_PRESSURE`".

        Design: Corner/entities/railcar_missing_required_field_returns_validation
        """
        resp = api.create_railcar(
            {"car_mark": "GATX1002", "built_year": 2018}, PLANNER
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_railcar_get_unknown_id_returns_404(self, api):
        """PRD §2.6: "4. **Existence** — path identifiers resolve
        left-to-right; failure yields the domain-specific 404 naming the
        failing segment (`ERR_LESSEE_NOT_FOUND`, `ERR_RAILCAR_NOT_FOUND`,
        `ERR_LEASE_NOT_FOUND`, ...)."

        Design: Corner/entities/railcar_get_not_found_returns_404
        """
        resp = api.get_railcar(NON_EXISTENT_UUID, PLANNER)
        validate_error(resp, ApiErrorId.ERR_RAILCAR_NOT_FOUND)

    def test_railcar_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum accepted value of 1 and a
        maximum accepted value of 100. The `offset` parameter sets the number
        of items skipped and defaults to 0." and "The `meta` object of a list
        response carries the four pagination fields `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/railcar_list_pagination_envelope
        """
        for mark, year in (("GATX1101", 2018), ("GATX1102", 2019), ("GATX1103", 2020)):
            get_success_data(
                api.create_railcar(
                    create_railcar_payload(car_mark=mark, built_year=year), PLANNER
                )
            )
        page1, meta1 = validate_paginated(
            api.list_railcars(PLANNER, params={"limit": 2, "offset": 0})
        )
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api.list_railcars(PLANNER, params={"limit": 2, "offset": 2})
        )
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1

    def test_railcar_computed_age_ignores_client_input(self, api):
        """PRD §3.2: "`car_age_years` is the calendar year of the logical
        clock minus `built_year` — it drives the 50-year age gate of §2.10 and
        the betterment rule of §3.10."
        PRD §2.5: "Before any client sets it, the logical clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Corner/entities/railcar_computed_age_input_ignored
        """
        resp = api.create_railcar(
            {
                "car_mark": "GATX1104",
                "car_type": "BOX",
                "built_year": 2015,
                "car_age_years": 99,
            },
            PLANNER,
        )
        car = validate_success(resp, 201)
        assert_railcar(car)
        assert car["car_age_years"] == 11, (
            "2026 - 2015 = 11; the client-supplied 99 must be ignored because "
            "car_age_years is computed from built_year against the clock"
        )


class TestLeaseCreationValidation:
    def test_lease_create_invalid_lease_type_rejected(self, api):
        """PRD §2.6: "5. **Body shape** — required fields present, types
        correct, enum membership valid, numeric ranges respected; failure
        yields `ERR_VALIDATION` (400)."
        PRD §3.3: the caller supplies "`lease_type` (`FULL_SERVICE` or `NET`,
        which drives the maintenance responsibility split of §3.9)".

        Design: Corner/entities/lease_agreement_invalid_enum_rejected
        """
        lessee = get_success_data(
            api.create_lessee(
                create_lessee_payload(company_name="L", credit_limit_cents=1000000),
                LEASE_ADMIN,
            )
        )
        resp = api.create_lease_agreement(
            create_lease_agreement_payload(
                lessee_id=lessee["id"], lease_type="TRIPLE_NET"
            ),
            LEASE_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestDomainNotFound:
    def test_statement_get_unknown_id_returns_404(self, api):
        """PRD §2.6: "4. **Existence** — path identifiers resolve
        left-to-right; failure yields the domain-specific 404 naming the
        failing segment (`ERR_LESSEE_NOT_FOUND`, ..., `ERR_STATEMENT_NOT_FOUND`,
        ...)."

        Design: Corner/errors/statement_get_not_found_returns_error
        """
        resp = api.get_car_hire_statement(NON_EXISTENT_UUID, BILLING)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FOUND)

    def test_commitment_get_unknown_id_returns_404(self, api):
        """PRD §2.12: "a request with a valid pool but a commitment id that
        does not resolve within that pool fails with
        `ERR_COMMITMENT_NOT_FOUND` (404)."

        Design: Corner/errors/commitment_get_not_found_returns_error
        """
        pool = get_success_data(
            api.create_capital_pool(
                create_capital_pool_payload(
                    fiscal_year=2026, opening_balance_cents=100000
                ),
                ADMIN,
            )
        )
        resp = api.get_commitment(pool["id"], NON_EXISTENT_UUID, PLANNER)
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_FOUND)
