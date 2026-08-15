"""Deployment scheduling: notice gate, date rules, observer caps, temporal
overlap, vessel turnaround, OCC on the notice version, the sea-day ledger,
and the operator-standing gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_notice,
    assert_notice_day_invariant,
    create_deployment_for_notice,
    create_deployment_payload,
    get_notice_for_vessel,
    make_coverage_plan,
    make_fishery,
    make_observer,
    make_operator,
    make_vessel,
    make_vessel_operator_headers,
    publish_plan,
    run_selection,
    setup_delinquent_operator_scenario,
    setup_notice_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_two_vessel_notices(api, projected_fleet_effort_days=200):
    """One fishery/operator/observer (LEAD) + two ACTIVE vessels, plan
    published, run executed, both notices ACCEPTED."""
    fishery = make_fishery()
    operator = make_operator()
    observer = make_observer()
    v1 = make_vessel(operator, fishery)
    v2 = make_vessel(operator, fishery)
    plan = make_coverage_plan(
        fishery,
        projected_fleet_effort_days=projected_fleet_effort_days,
        projected_em_effort_days=0,
    )
    publish_plan(plan["id"])
    run_selection(plan["id"])
    n1 = get_notice_for_vessel(plan["id"], v1["id"])
    n2 = get_notice_for_vessel(plan["id"], v2["id"])
    accept_notice(n1["id"], operator["id"])
    accept_notice(n2["id"], operator["id"])
    return fishery, operator, observer, v1, v2, plan, n1, n2


def _setup_three_vessel_notices(api):
    fishery = make_fishery()
    operator = make_operator()
    observer = make_observer()
    vessels = [make_vessel(operator, fishery) for _ in range(3)]
    plan = make_coverage_plan(
        fishery, projected_fleet_effort_days=300, projected_em_effort_days=0
    )
    publish_plan(plan["id"])
    run_selection(plan["id"], notice_response_deadline="2026-08-25T00:00:00Z")
    notices = []
    for vessel in vessels:
        notice = get_notice_for_vessel(plan["id"], vessel["id"])
        accept_notice(notice["id"], operator["id"])
        notices.append(notice)
    return fishery, operator, observer, vessels, plan, notices


class TestDeploymentCreateGates:
    def test_create_against_issued_notice_rejected(self, api, coordinator_headers):
        """PRD §3.4: "The notice must be `ACCEPTED` — anything else yields
        `ERR_NOTICE_NOT_ACCEPTED`."

        Design: Corner/validations/deployment_create_against_non_accepted_notice_rejected
        """
        bundle = setup_notice_scenario(accept=False)
        notice = bundle["notice"]
        payload = create_deployment_payload(
            selection_notice_id=notice["id"],
            observer_id=bundle["observer"]["id"],
            scheduled_departure_date="2026-09-10T00:00:00Z",
            scheduled_return_date="2026-09-15T00:00:00Z",
            expected_selection_notice_version=notice["version"],
        )
        resp = api.create_deployment(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_ACCEPTED, 409)
        rows, _ = validate_paginated(
            api.list_deployments(
                coordinator_headers, params={"selection_notice_id": notice["id"]}
            )
        )
        assert rows == [], "no Deployment row may be created"

    def test_return_before_departure_rejected(self, api, coordinator_headers):
        """PRD §3.4: "The return date must fall after the departure, else
        `ERR_DATE_RANGE_INVALID`, and the resulting `planned_sea_days` — the
        inclusive calendar-day count from departure through return — must not
        exceed 45 days, else `ERR_DEPLOYMENT_TOO_LONG`."

        Design: Corner/errors/err_date_range_invalid_return_before_departure
        """
        bundle = setup_notice_scenario()
        notice = bundle["notice"]
        payload = create_deployment_payload(
            selection_notice_id=notice["id"],
            observer_id=bundle["observer"]["id"],
            scheduled_departure_date="2026-09-19T00:00:00Z",
            scheduled_return_date="2026-09-10T00:00:00Z",
            expected_selection_notice_version=notice["version"],
        )
        resp = api.create_deployment(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DATE_RANGE_INVALID, 422)
        rows, _ = validate_paginated(
            api.list_deployments(
                coordinator_headers, params={"selection_notice_id": notice["id"]}
            )
        )
        assert rows == []

    def test_deployment_over_45_days_rejected(self, api, coordinator_headers):
        """PRD §3.4: "The return date must fall after the departure, else
        `ERR_DATE_RANGE_INVALID`, and the resulting `planned_sea_days` — the
        inclusive calendar-day count from departure through return — must not
        exceed 45 days, else `ERR_DEPLOYMENT_TOO_LONG`." PRD §2.11: "Incoming
        writes are checked in a fixed priority order so that a request with
        several problems always surfaces the same error. Lower numbers win:"

        Design: Corner/errors/err_deployment_too_long_over_45_days
        """
        bundle = setup_notice_scenario()
        notice = bundle["notice"]
        # 2026-09-10 .. 2026-10-25 inclusive is 46 planned days (> 45).
        payload = create_deployment_payload(
            selection_notice_id=notice["id"],
            observer_id=bundle["observer"]["id"],
            scheduled_departure_date="2026-09-10T00:00:00Z",
            scheduled_return_date="2026-10-25T00:00:00Z",
            expected_selection_notice_version=notice["version"],
        )
        resp = api.create_deployment(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_TOO_LONG, 422)


class TestObserverTemporalOverlap:
    def test_touching_dates_count_as_overlap(self, api, coordinator_headers):
        """PRD §3.4: "The observer must hold no other deployment in
        `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, or `AT_SEA` whose closed
        departure-to-return interval intersects the new one — touching dates
        count as overlap — else `ERR_OBSERVER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/observer_closed_interval_touching_dates_overlap
        """
        fishery, operator, observer, v1, v2, plan, n1, n2 = _setup_two_vessel_notices(api)
        create_deployment_for_notice(
            n1["id"], observer["id"], "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z"
        )
        # The new interval [2026-09-19, 2026-09-25] touches the existing
        # [2026-09-10, 2026-09-19] at exactly 2026-09-19.
        notice2 = validate_success(api.get_selection_notice(n2["id"], coordinator_headers))
        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=n2["id"],
                observer_id=observer["id"],
                scheduled_departure_date="2026-09-19T00:00:00Z",
                scheduled_return_date="2026-09-25T00:00:00Z",
                expected_selection_notice_version=notice2["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OBSERVER_OVERLAP, 409)
        rows, _ = validate_paginated(
            api.list_deployments(
                coordinator_headers, params={"selection_notice_id": n2["id"]}
            )
        )
        assert rows == [], "no second Deployment row may be created"

    def test_partial_intersection_also_overlaps(self, api, coordinator_headers):
        """PRD §3.4: "The observer must hold no other deployment in
        `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, or `AT_SEA` whose closed
        departure-to-return interval intersects the new one — touching dates
        count as overlap — else `ERR_OBSERVER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/observer_closed_interval_touching_dates_overlap
        """
        fishery, operator, observer, v1, v2, plan, n1, n2 = _setup_two_vessel_notices(api)
        create_deployment_for_notice(
            n1["id"], observer["id"], "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z"
        )
        # The new interval starts inside the existing one.
        notice2 = validate_success(api.get_selection_notice(n2["id"], coordinator_headers))
        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=n2["id"],
                observer_id=observer["id"],
                scheduled_departure_date="2026-09-15T00:00:00Z",
                scheduled_return_date="2026-09-22T00:00:00Z",
                expected_selection_notice_version=notice2["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OBSERVER_OVERLAP, 409)


class TestVesselTurnaround:
    def test_zero_gap_day_rejected(self, api, coordinator_headers):
        """PRD §3.4: "And the vessel must enjoy at least one full in-port
        calendar day between any such existing deployment's return and the new
        departure — formally, the day gap from the existing return to the new
        departure, minus one, must be at least one — else
        `ERR_VESSEL_TURNAROUND_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/vessel_turnaround_requires_full_in_port_day
        """
        bundle = setup_notice_scenario()
        obs2 = make_observer()
        notice = bundle["notice"]
        create_deployment_for_notice(
            notice["id"], bundle["observer"]["id"],
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        fresh = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        # Existing return 2026-09-19 -> new departure 2026-09-20 leaves a gap
        # of (1) - 1 == 0 full in-port days: violation.
        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=obs2["id"],
                scheduled_departure_date="2026-09-20T00:00:00Z",
                scheduled_return_date="2026-09-24T00:00:00Z",
                expected_selection_notice_version=fresh["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VESSEL_TURNAROUND_VIOLATION, 409)

    def test_one_full_gap_day_allowed(self, api, coordinator_headers):
        """PRD §3.4: "And the vessel must enjoy at least one full in-port
        calendar day between any such existing deployment's return and the new
        departure — formally, the day gap from the existing return to the new
        departure, minus one, must be at least one — else
        `ERR_VESSEL_TURNAROUND_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/vessel_turnaround_requires_full_in_port_day
        """
        bundle = setup_notice_scenario()
        obs2 = make_observer()
        notice = bundle["notice"]
        create_deployment_for_notice(
            notice["id"], bundle["observer"]["id"],
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        fresh = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        # Departure 2026-09-21 leaves (2) - 1 == 1 full in-port day: allowed.
        created = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=obs2["id"],
                scheduled_departure_date="2026-09-21T00:00:00Z",
                scheduled_return_date="2026-09-25T00:00:00Z",
                expected_selection_notice_version=fresh["version"],
            ),
            coordinator_headers,
        )
        deployment = validate_success(created, 201)
        assert deployment["planned_sea_days"] == 5
        notice = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        assert notice["reserved_sea_days"] == 15
        assert notice["remaining_sea_days"] == 15
        assert_notice_day_invariant(notice)


class TestObserverCaps:
    def test_consecutive_cap_equality_allowed(self, api, coordinator_headers):
        """PRD §3.4: "The consecutive cap rejects the write with
        `ERR_OBSERVER_CONSECUTIVE_CAP_EXCEEDED` when `planned_sea_days` exceeds
        the observer's `max_consecutive_sea_days` — landing exactly on the cap
        is allowed."

        Design: Corner/calculations/observer_consecutive_cap_equality_allowed
        """
        fishery = make_fishery()
        operator = make_operator()
        trainee = make_observer(certification_level="TRAINEE")
        v1 = make_vessel(operator, fishery)
        v2 = make_vessel(operator, fishery)
        plan = make_coverage_plan(
            fishery, projected_fleet_effort_days=200, projected_em_effort_days=0
        )
        publish_plan(plan["id"])
        run_selection(plan["id"])
        n1 = get_notice_for_vessel(plan["id"], v1["id"])
        n2 = get_notice_for_vessel(plan["id"], v2["id"])
        accept_notice(n1["id"], operator["id"])
        accept_notice(n2["id"], operator["id"])

        # 2026-09-10 .. 2026-09-29 is exactly 20 days == the TRAINEE cap.
        ok = create_deployment_for_notice(
            n1["id"], trainee["id"], "2026-09-10T00:00:00Z", "2026-09-29T00:00:00Z"
        )
        assert ok["planned_sea_days"] == 20
        assert ok["status"] == "SCHEDULED"

        # 2026-10-10 .. 2026-10-30 is 21 days > 20: rejected.
        fresh2 = validate_success(api.get_selection_notice(n2["id"], coordinator_headers))
        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=n2["id"],
                observer_id=trainee["id"],
                scheduled_departure_date="2026-10-10T00:00:00Z",
                scheduled_return_date="2026-10-30T00:00:00Z",
                expected_selection_notice_version=fresh2["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OBSERVER_CONSECUTIVE_CAP_EXCEEDED, 422)

    def test_commitment_cap_90_exactly_allowed(self, api, coordinator_headers):
        """PRD §3.4: "The commitment cap sums the planned days of the
        observer's other deployments in `SCHEDULED`, `SAFETY_HOLD`,
        `READY_TO_DEPLOY`, or `AT_SEA` and rejects with
        `ERR_OBSERVER_COMMITMENT_CAP_EXCEEDED` when that sum plus the new
        `planned_sea_days` would exceed 90 days — again, equality is allowed."

        Design: Difficulty/boundary_precision_check/observer_commitment_cap_90_allowed_91_rejected
        """
        fishery, operator, observer, vessels, plan, notices = _setup_three_vessel_notices(api)
        create_deployment_for_notice(
            notices[0]["id"], observer["id"],
            "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z",
        )
        create_deployment_for_notice(
            notices[1]["id"], observer["id"],
            "2026-10-02T00:00:00Z", "2026-10-31T00:00:00Z",
        )
        # S == 60 committed; +30 lands exactly on the cap of 90: allowed.
        created = create_deployment_for_notice(
            notices[2]["id"], observer["id"],
            "2026-11-02T00:00:00Z", "2026-12-01T00:00:00Z",
        )
        assert created["planned_sea_days"] == 30
        assert created["status"] == "SCHEDULED"
        rows, meta = validate_paginated(
            api.list_deployments(
                coordinator_headers, params={"observer_id": observer["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 3

    def test_commitment_cap_91_rejected(self, api, coordinator_headers):
        """PRD §3.4: "The commitment cap sums the planned days of the
        observer's other deployments in `SCHEDULED`, `SAFETY_HOLD`,
        `READY_TO_DEPLOY`, or `AT_SEA` and rejects with
        `ERR_OBSERVER_COMMITMENT_CAP_EXCEEDED` when that sum plus the new
        `planned_sea_days` would exceed 90 days — again, equality is allowed."

        Design: Difficulty/boundary_precision_check/observer_commitment_cap_90_allowed_91_rejected
        """
        fishery, operator, observer, vessels, plan, notices = _setup_three_vessel_notices(api)
        create_deployment_for_notice(
            notices[0]["id"], observer["id"],
            "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z",
        )
        create_deployment_for_notice(
            notices[1]["id"], observer["id"],
            "2026-10-02T00:00:00Z", "2026-10-31T00:00:00Z",
        )
        # S == 60; +31 would reach 91 > 90: rejected.
        fresh3 = validate_success(
            api.get_selection_notice(notices[2]["id"], coordinator_headers)
        )
        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notices[2]["id"],
                observer_id=observer["id"],
                scheduled_departure_date="2026-11-02T00:00:00Z",
                scheduled_return_date="2026-12-02T00:00:00Z",
                expected_selection_notice_version=fresh3["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OBSERVER_COMMITMENT_CAP_EXCEEDED, 422)
        rows, _ = validate_paginated(
            api.list_deployments(
                coordinator_headers, params={"selection_notice_id": notices[2]["id"]}
            )
        )
        assert rows == []


class TestDeploymentNoticeOCC:
    def test_stale_notice_version_rejected(self, api, coordinator_headers):
        """PRD §2.8: "Creating a deployment requires
        `expected_selection_notice_version`, carrying the client's
        last-observed `version` of the parent selection notice. If the value
        does not match the notice's current `version` — because another writer
        has since created, rescheduled, or cancelled a deployment against that
        notice and moved its sea-day allocation — the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from scheduling
        against an allocation it has not observed."

        Design: Corner/cross_cutting_layers/occ_deployment_create_stale_notice_version
        """
        bundle = setup_notice_scenario(with_debriefer=False)
        obs2 = make_observer()
        notice = bundle["notice"]
        stale_version = notice["version"]
        # First write against the current version succeeds and bumps it.
        first = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=bundle["observer"]["id"],
                scheduled_departure_date="2026-09-10T00:00:00Z",
                scheduled_return_date="2026-09-15T00:00:00Z",
                expected_selection_notice_version=stale_version,
            ),
            coordinator_headers,
        )
        validate_success(first, 201)
        # Replaying the same stale version is rejected.
        stale = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=obs2["id"],
                scheduled_departure_date="2026-09-17T00:00:00Z",
                scheduled_return_date="2026-09-20T00:00:00Z",
                expected_selection_notice_version=stale_version,
            ),
            coordinator_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        # The same payload with the freshly read version succeeds.
        fresh = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        retried = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=obs2["id"],
                scheduled_departure_date="2026-09-17T00:00:00Z",
                scheduled_return_date="2026-09-20T00:00:00Z",
                expected_selection_notice_version=fresh["version"],
            ),
            coordinator_headers,
        )
        second = validate_success(retried, 201)
        assert second["planned_sea_days"] == 4
        notice = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        assert notice["reserved_sea_days"] == 10
        assert notice["remaining_sea_days"] == 20
        assert_notice_day_invariant(notice)


class TestNoticeSeaDayLedger:
    def test_create_moves_days_to_reserved(self, api, coordinator_headers):
        """PRD §2.9: "Each selection notice is a small ledger of sea days, and
        one invariant holds after every mutation: `allocated_sea_days` always
        equals the sum of `remaining_sea_days`, `reserved_sea_days`, and
        `consumed_sea_days`." and "Creating a deployment moves its
        `planned_sea_days` from `remaining_sea_days` into `reserved_sea_days`,
        and the planned days may not exceed the remainder (else
        `ERR_SEA_DAY_ALLOCATION_EXCEEDED`)."

        Design: Difficulty/compensating_invariant/notice_sea_day_invariant_create_then_cancel
        """
        bundle = setup_notice_scenario()
        notice = bundle["notice"]
        deployment = create_deployment_for_notice(
            notice["id"], bundle["observer"]["id"],
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        assert deployment["status"] == "SCHEDULED"
        after = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        assert after["remaining_sea_days"] == 20
        assert after["reserved_sea_days"] == 10
        assert after["consumed_sea_days"] == 0
        assert_notice_day_invariant(after)

    def test_cancel_restores_days_with_zero_drift(self, api, coordinator_headers):
        """PRD §2.9: "Cancelling a deployment releases its reservation
        wholesale: `reserved_sea_days` drops by `planned_sea_days` and
        `remaining_sea_days` rises by the same." and "Each selection notice is
        a small ledger of sea
        days, and one invariant holds after every mutation: `allocated_sea_days`
        always equals the sum of `remaining_sea_days`, `reserved_sea_days`, and
        `consumed_sea_days`."

        Design: Difficulty/compensating_invariant/notice_sea_day_invariant_create_then_cancel
        """
        bundle = setup_notice_scenario()
        notice = bundle["notice"]
        deployment = create_deployment_for_notice(
            notice["id"], bundle["observer"]["id"],
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        cancelled = validate_success(
            api.cancel_deployment(deployment["id"], {}, coordinator_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"
        restored = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        assert restored["allocated_sea_days"] == 30
        assert restored["remaining_sea_days"] == 30
        assert restored["reserved_sea_days"] == 0
        assert restored["consumed_sea_days"] == 0
        assert_notice_day_invariant(restored)


class TestOperatorStandingGate:
    def test_create_rejected_while_operator_delinquent(self, api, coordinator_headers):
        """PRD §3.4: "The vessel must be `ACTIVE` (`ERR_VESSEL_NOT_ACTIVE`),
        must still fish in `HUMAN_OBSERVER` mode (`ERR_VESSEL_NOT_HUMAN_MODE`),
        and its operator must stand at `GOOD` (`ERR_OPERATOR_DELINQUENT`)."

        Design: Difficulty/cross_entity_state_dependency/deployment_create_gated_on_operator_payment_standing
        """
        bundle = setup_delinquent_operator_scenario(reactivate_vessel=True)
        operator = validate_success(
            api.get_vessel_operator(bundle["operator"]["id"], coordinator_headers)
        )
        assert operator["payment_standing"] == "DELINQUENT"
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert notice["status"] == "ACCEPTED"
        assert notice["remaining_sea_days"] == 20

        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=bundle["observer"]["id"],
                scheduled_departure_date="2026-11-10T00:00:00Z",
                scheduled_return_date="2026-11-19T00:00:00Z",
                expected_selection_notice_version=notice["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_DELINQUENT, 409)
        rows, _ = validate_paginated(
            api.list_deployments(
                coordinator_headers, params={"selection_notice_id": notice["id"]}
            )
        )
        assert [row["id"] for row in rows] == [bundle["deployment"]["id"]]

    def test_create_allowed_after_standing_restored(self, api, coordinator_headers):
        """PRD §2.10: "when a payment or waiver leaves an operator with no
        `OVERDUE` invoices, `payment_standing` returns to `GOOD`, but the
        suspended vessels stay `SUSPENDED` until an administrator reactivates
        each one manually." PRD §3.4: "its operator must stand at `GOOD`
        (`ERR_OPERATOR_DELINQUENT`)."

        Design: Difficulty/cross_entity_state_dependency/deployment_create_gated_on_operator_payment_standing
        """
        bundle = setup_delinquent_operator_scenario()
        invoice = validate_success(api.get_invoice(bundle["invoice"]["id"], coordinator_headers))
        assert invoice["status"] == "OVERDUE"
        outstanding = invoice["amount_outstanding_cents"]
        assert outstanding > 0
        paid = validate_success(
            api.create_payment(
                invoice["id"],
                {"amount_cents": outstanding},
                make_vessel_operator_headers(bundle["operator"]["id"]),
            ),
            201,
        )
        assert paid["status"] == "PAID"
        operator = validate_success(
            api.get_vessel_operator(bundle["operator"]["id"], coordinator_headers)
        )
        assert operator["payment_standing"] == "GOOD"
        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["status"] == "SUSPENDED", "vessels stay SUSPENDED until manual reactivation"

        validate_success(
            api.patch_vessel(
                bundle["vessel"]["id"], {"status": "ACTIVE"},
                TEST_USERS["program_admin_headers"],
            )
        )
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        created = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=bundle["observer"]["id"],
                scheduled_departure_date="2026-11-10T00:00:00Z",
                scheduled_return_date="2026-11-19T00:00:00Z",
                expected_selection_notice_version=notice["version"],
            ),
            coordinator_headers,
        )
        deployment = validate_success(created, 201)
        assert deployment["status"] == "SCHEDULED"


class TestDelinquencyBeatsAllocationPriority:
    def test_referential_error_wins_over_fiscal_error(self, api, coordinator_headers):
        """PRD §2.11: "Incoming writes are checked in a fixed priority order so
        that a request with several problems always surfaces the same error.
        Lower numbers win:" with "9. **Cross-entity referential state** —
        fishery, vessel, observer, operator, and enrollment statuses plus
        registry uniqueness (`ERR_FISHERY_NOT_ACTIVE`, `ERR_VESSEL_NOT_ACTIVE`,
        `ERR_VESSEL_NOT_HUMAN_MODE`, `ERR_VESSEL_NOT_EM_MODE`,
        `ERR_OBSERVER_NOT_AVAILABLE`, `ERR_OPERATOR_DELINQUENT`,
        `ERR_EM_ENROLLMENT_NOT_ACTIVE`, `ERR_EM_ENROLLMENT_OPEN_EXISTS`,
        `ERR_UNIQUE_CONSTRAINT`)." outranking "11. **Fiscal and allocation
        rules** — sea-day allocation, payment bounds, adjustment floors
        (`ERR_SEA_DAY_ALLOCATION_EXCEEDED`, `ERR_PAYMENT_NOT_POSITIVE`,
        `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_ADJUSTMENT_WOULD_UNDERFLOW`)."

        Design: Difficulty/priority_pair_validation_conflict/deployment_create_referential_delinquency_beats_fiscal_allocation_error
        """
        bundle = setup_delinquent_operator_scenario(reactivate_vessel=True)
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert notice["remaining_sea_days"] == 20
        # 2026-11-01 .. 2026-11-25 is 25 planned days > 20 remaining: this
        # request violates BOTH the delinquency gate and the allocation cap.
        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=bundle["observer"]["id"],
                scheduled_departure_date="2026-11-01T00:00:00Z",
                scheduled_return_date="2026-11-25T00:00:00Z",
                expected_selection_notice_version=notice["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_DELINQUENT, 409)

    def test_referential_error_fires_without_fiscal_violation(self, api, coordinator_headers):
        """PRD §3.4: "its operator must stand at `GOOD`
        (`ERR_OPERATOR_DELINQUENT`)." PRD §2.11: "Incoming writes are checked in
        a fixed priority order so that a request with several problems always
        surfaces the same error. Lower numbers win:"

        Design: Difficulty/priority_pair_validation_conflict/deployment_create_referential_delinquency_beats_fiscal_allocation_error
        """
        bundle = setup_delinquent_operator_scenario(reactivate_vessel=True)
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        # 2026-11-01 .. 2026-11-15 is 15 planned days <= 20 remaining: only the
        # delinquency gate is violated, isolating the referential error.
        resp = api.create_deployment(
            create_deployment_payload(
                selection_notice_id=notice["id"],
                observer_id=bundle["observer"]["id"],
                scheduled_departure_date="2026-11-01T00:00:00Z",
                scheduled_return_date="2026-11-15T00:00:00Z",
                expected_selection_notice_version=notice["version"],
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_DELINQUENT, 409)
