"""Driver roster: pagination, filters, termination cascade, reinstatement
gating, and version cascades."""
from test_helpers import (
    ApiErrorId,
    assert_driver,
    create_test_payload,
    get_coaching,
    get_driver,
    make_carrier,
    make_carrier_with_driver,
    make_category,
    make_coaching,
    make_driver,
    make_inspection,
    make_manager_headers,
    make_mro_headers,
    make_violation,
    set_clock,
    setup_suspended_by_positive_test,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDriverListing:
    def test_driver_list_pagination_defaults(self, api, manager_headers):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items to skip and defaults to 0." and "The `meta` object
        of list responses carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/driver_list_pagination_defaults
        """
        carrier = make_carrier(dot_number="DOT-2003", fleet_size=20)
        for day in range(1, 13):
            make_driver(
                carrier["id"],
                cdl_number=f"CDL-P{day:02d}",
                full_name=f"Driver {day:02d}",
                hire_date=f"2025-01-{day:02d}T00:00:00Z",
            )

        page1, meta1 = validate_paginated(api.list_drivers(manager_headers))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_drivers(manager_headers, params={"limit": 5, "offset": 10})
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_list_filters_combine(self, api, manager_headers):
        """PRD §3.2: "The driver list can be filtered by `carrier_id`,
        `employment_status`, and `risk_tier`."

        Design: Corner/endpoints/list_filters_combine
        """
        carrier_a = make_carrier(dot_number="DOT-2404A", legal_name="Filter A")
        carrier_b = make_carrier(dot_number="DOT-2404B", legal_name="Filter B")
        d1 = make_driver(carrier_a["id"], cdl_number="CDL-2404A", full_name="Cam Ine")
        d2 = make_driver(carrier_a["id"], cdl_number="CDL-2404B", full_name="Don Ine")
        d3 = make_driver(carrier_b["id"], cdl_number="CDL-2404C", full_name="Ede Ine")
        validate_success(api.terminate_driver(d2["id"], manager_headers), 200)

        data, meta = validate_paginated(
            api.list_drivers(manager_headers, params={"carrier_id": carrier_a["id"]})
        )
        assert {d["id"] for d in data} == {d1["id"], d2["id"]}
        assert meta["total_count"] == 2

        data, _ = validate_paginated(
            api.list_drivers(
                manager_headers,
                params={"carrier_id": carrier_a["id"], "employment_status": "ACTIVE"},
            )
        )
        assert [d["id"] for d in data] == [d1["id"]]

        data, _ = validate_paginated(
            api.list_drivers(manager_headers, params={"employment_status": "TERMINATED"})
        )
        assert [d["id"] for d in data] == [d2["id"]]

        data, _ = validate_paginated(
            api.list_drivers(manager_headers, params={"carrier_id": carrier_b["id"]})
        )
        assert [d["id"] for d in data] == [d3["id"]]


class TestDriverLifecycle:
    def test_driver_terminate_cascades_coaching_cancel(self, api, manager_headers):
        """PRD §3.2: "Termination moves a driver from `ACTIVE` or `SUSPENDED` to
        terminal `TERMINATED`, cancels every coaching assignment of the driver
        still in `ASSIGNED`, `IN_PROGRESS`, `OVERDUE`, or `ESCALATED`, and
        increments the driver's `version`; a driver who is already `TERMINATED`
        cannot be terminated again and the attempt is rejected with
        `ERR_DRIVER_NOT_ACTIVE`."

        Design: Corner/state_machines/driver_terminate_cascades_coaching_cancel
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2106"}
        )
        coaching = make_coaching(
            driver["id"], coaching_type="VERBAL_WARNING",
            due_date="2026-12-01T00:00:00Z",
        )
        assert coaching["status"] == "ASSIGNED"

        terminated = validate_success(api.terminate_driver(driver["id"], manager_headers), 200)
        assert_driver(terminated)
        assert terminated["employment_status"] == "TERMINATED"
        assert get_coaching(coaching["id"])["status"] == "CANCELLED"

        again = api.terminate_driver(driver["id"], manager_headers)
        validate_error(again, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)

    def test_reinstate_active_driver_rejected(self, api, manager_headers):
        """PRD §3.2: "it is rejected with `ERR_DRIVER_NOT_SUSPENDED` when the
        driver is not `SUSPENDED`, and with `ERR_REINSTATE_REQUIREMENTS_UNMET`
        while any suspension hold remains."
        PRD §3.6: "the exceptions are `RETURN_TO_DUTY` and `FOLLOW_UP`, which
        require the driver to be `SUSPENDED` and are rejected with
        `ERR_DRIVER_NOT_SUSPENDED` otherwise."

        Design: Corner/validations/reinstate_active_driver_rejected
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2320"}
        )
        assert driver["employment_status"] == "ACTIVE"

        reinstate = api.reinstate_driver(driver["id"], manager_headers)
        validate_error(reinstate, ApiErrorId.ERR_DRIVER_NOT_SUSPENDED)

        rtd = api.create_test(
            create_test_payload(
                driver["id"], test_type="RETURN_TO_DUTY", substance="DRUG",
                collected_at="2026-07-01T00:00:00Z",
            ),
            manager_headers,
        )
        validate_error(rtd, ApiErrorId.ERR_DRIVER_NOT_SUSPENDED)

    def test_version_increments_on_cascaded_mutation(self, api, manager_headers):
        """PRD §2.4: "`version` (integer): starts at 1 at creation and
        increments by one on every mutation of the resource, including mutations
        caused by cascades from operations on other resources."
        PRD §3.3: "Recording a violation also recomputes the parent inspection's
        `total_weighted_points` — the sum of `weighted_points` over its
        violations in `ACTIVE` or `CHALLENGED` status, with `REMOVED` always
        excluded — and the cited driver's `risk_score`; when that recomputation
        changes the driver's `risk_tier`, the carrier's `QUOTED` premium models
        go `STALE` (§2.8)."

        Design: Corner/complexity_layers/version_increments_on_cascaded_mutation
        """
        carrier = make_carrier(dot_number="DOT-2603")
        category = make_category(category_code="UNSAFE_DRIVING", display_name="UD")
        driver = make_driver(carrier["id"], cdl_number="CDL-2603", full_name="Liv Ite")
        assert driver["version"] == 1
        inspection = make_inspection(carrier["id"], driver["id"], state_code="SC")

        make_violation(
            inspection["id"], category["id"], violation_code="392.2", severity_weight=4
        )
        after = get_driver(driver["id"])
        assert after["version"] == 2, (
            "cascaded risk_score recompute is a mutation and bumps Driver.version"
        )
        assert after["risk_score"] == 12, "4 severity x time-weight 3 = 12"
        assert after["risk_tier"] == "MEDIUM"


class TestReinstateAfterVerifiedPositive:
    def test_reinstate_blocked_while_positive_hold_stands(
        self, api, manager_headers
    ):
        """PRD §3.2: "A driver carries a suspension hold under either of two
        conditions: (a) any coaching assignment of the driver is in `ESCALATED`
        status, or (b) there exists an `MRO_VERIFIED` test of the driver with
        `mro_verdict` `VERIFIED_POSITIVE` or `VERIFIED_REFUSAL` for which no
        later `MRO_VERIFIED` `RETURN_TO_DUTY` test exists with `mro_verdict`
        `VERIFIED_NEGATIVE` and a `collected_at` strictly after the positive or
        refusal test's `verified_at`."
        PRD §3.2: "Reinstatement — manual or automatic — succeeds only when the
        hold count is zero." ... "with `ERR_REINSTATE_REQUIREMENTS_UNMET` while
        any suspension hold remains."
        PRD §3.6: "When a test is verified `VERIFIED_POSITIVE` or
        `VERIFIED_REFUSAL` and the driver is `ACTIVE`, the driver is immediately
        suspended and the driver's `version` increments; from that moment a
        suspension hold (§3.2) stands until a verified negative return-to-duty
        test clears it."

        Design: Difficulty/cross_entity_state_dependency/reinstate_requires_verified_rtd_negative
        """
        env = setup_suspended_by_positive_test()
        driver = env["driver"]
        assert driver["employment_status"] == "SUSPENDED", (
            "verified positive cascades ACTIVE -> SUSPENDED"
        )

        resp = api.reinstate_driver(driver["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_REINSTATE_REQUIREMENTS_UNMET)
        assert get_driver(driver["id"])["employment_status"] == "SUSPENDED"

    def test_reinstate_succeeds_after_verified_rtd_negative(
        self, api, manager_headers
    ):
        """PRD §3.2: "Reinstatement — manual or automatic — succeeds only when
        the hold count is zero." The verified-positive hold of §3.2(b) stands
        while "no later `MRO_VERIFIED` `RETURN_TO_DUTY` test exists with
        `mro_verdict` `VERIFIED_NEGATIVE` and a `collected_at` strictly after
        the positive or refusal test's `verified_at`."
        PRD §3.6: "the exceptions are `RETURN_TO_DUTY` and `FOLLOW_UP`, which
        require the driver to be `SUSPENDED` and are rejected with
        `ERR_DRIVER_NOT_SUSPENDED` otherwise."

        Design: Difficulty/cross_entity_state_dependency/reinstate_requires_verified_rtd_negative
        """
        env = setup_suspended_by_positive_test()
        driver = env["driver"]

        # RETURN_TO_DUTY collection is allowed on the SUSPENDED driver.
        set_clock("2026-08-03T00:00:00Z")
        rtd = api.create_test(
            create_test_payload(
                driver["id"], test_type="RETURN_TO_DUTY", substance="DRUG",
                collected_at="2026-08-02T00:00:00Z",
            ),
            # recorded by the same operator id as the positive test's recorder
            # is fine here; verification uses a distinct MRO id (SoD §2.10).
            make_manager_headers("sm-1"),
        )
        rtd_data = validate_success(rtd, 201)
        validate_success(
            api.report_lab_result(rtd_data["id"], {"lab_result": "NEGATIVE"}, manager_headers),
            200,
        )
        validate_success(
            api.verify_test(
                rtd_data["id"], {"verdict": "VERIFIED_NEGATIVE"}, make_mro_headers("mro-1")
            ),
            200,
        )

        reinstated = validate_success(api.reinstate_driver(driver["id"], manager_headers), 200)
        assert reinstated["employment_status"] == "ACTIVE"
