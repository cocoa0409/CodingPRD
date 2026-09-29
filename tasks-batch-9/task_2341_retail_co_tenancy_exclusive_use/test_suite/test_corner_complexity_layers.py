"""Cross-cutting layers: version pinning, center versioning, sweep-driven grace
thresholds, derived-counter reconciliation, filtered listing under mutation, the
abatement ledger at consummation, and immediate read-after-write visibility.
"""
from test_helpers import (
    COMPLIANCE_ENFORCER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    COMPLIANCE_SWEEPER_USER_ID,
    DEFAULT_CLOCK_UTC,
    ERR_STALE_CENTER_VERSION,
    ERR_STALE_LEASE_VERSION,
    add_clause,
    add_condition,
    approve_election,
    assert_cents,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_pagination_meta,
    assert_pct,
    assert_sweep_report_shape,
    assert_version_unchanged,
    build_center_with_leases,
    consummate_election,
    create_center,
    create_tenant,
    cure_notice,
    draft_lease,
    elect_remedy,
    execute_lease,
    factories,
    fetch_center,
    fetch_condition,
    fetch_lease,
    fetch_notice,
    get_success_data,
    go_dark,
    ids_of,
    issue_notice,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lender_rep_headers,
    make_tenant_rep_headers,
    open_lease,
    prepare_measurement,
    run_sweep,
    set_clock,
    validate_error,
    validate_paginated,
    withdraw_notice,
)

# The five-lease center used by most of the scenarios below: 300000 sqft of total
# area, two open anchor boxes and three open inline suites, so 255000 sqft is
# counted open and `open_occupancy_pct` sits at 85.00 (PRD §2.5).
FIVE_LEASE_SPECS = (
    {
        "suite_code": "A1",
        "gla_sqft": 120000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "DISCOUNT_DEPT",
        "base_rent_monthly_cents": 6000000,
        "commencement_date": "2026-01-01",
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Boxmart Retail Inc",
        "is_national_chain": True,
    },
    {
        "suite_code": "A2",
        "gla_sqft": 100000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "GROCERY",
        "base_rent_monthly_cents": 4000000,
        "commencement_date": "2026-01-01",
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Grocerway Foods LLC",
        "is_national_chain": True,
    },
    {
        "suite_code": "I1",
        "gla_sqft": 2000,
        "parcel_kind": "INLINE",
        "primary_use_code": "COFFEE",
        "base_rent_monthly_cents": 1000000,
        "commencement_date": "2026-01-01",
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Bean Theory Coffee LLC",
        "is_national_chain": False,
    },
    {
        "suite_code": "I2",
        "gla_sqft": 3000,
        "parcel_kind": "INLINE",
        "primary_use_code": "BOOKS",
        "base_rent_monthly_cents": 1200000,
        "commencement_date": "2026-01-01",
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Margin Books LLC",
        "is_national_chain": False,
    },
    {
        "suite_code": "I3",
        "gla_sqft": 30000,
        "parcel_kind": "INLINE",
        "primary_use_code": "FITNESS",
        "base_rent_monthly_cents": 1500000,
        "commencement_date": "2026-01-01",
        "expiration_date": "2036-12-31",
        "tenant_legal_name": "Pulse Fitness Group",
        "is_national_chain": True,
    },
)


def _five_lease_center(api):
    """Stand up the 300000 sqft center with its five open suites."""
    return build_center_with_leases(
        api,
        [dict(spec) for spec in FIVE_LEASE_SPECS],
        total_gla_sqft=300000,
        occupancy_grace_days=30,
        center_name="Northgate Crossing",
        clock=DEFAULT_CLOCK_UTC,
    )


def _add_i1_condition(api, scenario, grace_period_days, cure_period_days):
    """A GLA_PCT condition on suite I1 requiring 81.67 pct and two open anchors."""
    return add_condition(
        api,
        scenario.lease_id("I1"),
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=grace_period_days,
        cure_period_days=cure_period_days,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )


def _assert_stamped_at(value, expected_prefix, label):
    """A stamped instant carries the logical clock instant it was taken at."""
    assert value is not None, f"{label} should be stamped, got null"
    assert str(value).startswith(expected_prefix), (
        f"{label} is {value!r}, expected an instant at {expected_prefix}"
    )


def test_measurement_create_with_pre_cascade_center_version_is_refused(api):
    """A measurement pinned to a center version observed before the go-dark cascade is refused with 412.

    PRD: "If that value does not equal the center's current `version`, the request is rejected with `ERR_STALE_CENTER_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_center_version_on_measurement_create_returns_412
    """
    scenario = _five_lease_center(api)
    stale_version = fetch_center(api, scenario.center_id)["version"]

    # Driving suite I3 dark moves the center's occupancy figures (PRD §3.3).
    go_dark(api, scenario.lease_id("I3"))
    center_before = fetch_center(api, scenario.center_id)

    response = api.create_measurement(
        scenario.center_id,
        factories.measurement_payload(
            variant="SNAPSHOT_STRICT",
            window_from_date="2026-07-01",
            window_through_date="2026-08-02",
            expected_center_version=stale_version,
        ),
        make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
    )
    validate_error(response, ERR_STALE_CENTER_VERSION, 412)

    # A refused request mutates nothing (PRD §2.8).
    assert_version_unchanged(center_before, fetch_center(api, scenario.center_id))
    _, meta = validate_paginated(
        api.list_measurements(
            make_compliance_officer_headers(), {"center_id": scenario.center_id}
        )
    )
    assert_pagination_meta(meta, expected_total=0)


def test_measurement_create_retried_with_the_current_center_version_succeeds(api):
    """The identical measurement body is accepted once the freshly read center version is pinned.

    PRD: "From that population an engine derives: the counted gross leasable area as the sum of `gla_sqft` over counted leases; a GLA occupancy percentage equal to the counted area divided by the total area, multiplied by 100, and rounded half up to two decimal places; a non-anchor open-store count as the number of counted leases whose `is_anchor` is false; an anchor count as the number of counted leases whose `is_anchor` is true; a total counted-lease count; and an excluded count equal to the population size minus the counted size."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_center_version_on_measurement_create_returns_412
    """
    scenario = _five_lease_center(api)
    stale_version = fetch_center(api, scenario.center_id)["version"]
    go_dark(api, scenario.lease_id("I3"))

    stale_attempt = api.create_measurement(
        scenario.center_id,
        factories.measurement_payload(
            variant="SNAPSHOT_STRICT",
            window_from_date="2026-07-01",
            window_through_date="2026-08-02",
            expected_center_version=stale_version,
        ),
        make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
    )
    validate_error(stale_attempt, ERR_STALE_CENTER_VERSION, 412)

    fresh_version = fetch_center(api, scenario.center_id)["version"]
    measurement = prepare_measurement(
        api,
        scenario.center_id,
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-08-02",
        expected_center_version=fresh_version,
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )

    assert measurement["status"] == "DRAFT", measurement
    # Under SNAPSHOT_STRICT the dark suite drops out: 225000 of 300000 sqft.
    assert measurement["occupied_gla_sqft"] == 225000, measurement
    assert_pct(measurement["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")

    _, meta = validate_paginated(
        api.list_measurements(
            make_compliance_officer_headers(), {"center_id": scenario.center_id}
        )
    )
    assert_pagination_meta(meta, expected_total=1)


def test_election_create_with_a_stale_lease_version_is_refused(api):
    """An election pinned one version behind the lease's current version is refused with 412.

    PRD: "If that value does not equal the lease's current `version`, the request is rejected with `ERR_STALE_LEASE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_lease_version_on_election_create_returns_412
    """
    scenario = _five_lease_center(api)
    condition = _add_i1_condition(api, scenario, grace_period_days=0, cure_period_days=30)
    go_dark(api, scenario.lease_id("I3"))

    lease_before = fetch_lease(api, scenario.lease_id("I1"))

    response = api.create_election(
        scenario.lease_id("I1"),
        factories.election_payload(
            election_kind="RENT_REDUCTION",
            window_from_date="2026-08-01",
            window_through_date="2026-11-01",
            condition_id=condition["id"],
            expected_lease_version=lease_before["version"] - 1,
        ),
        make_tenant_rep_headers(scenario.tenant_id("I1")),
    )
    validate_error(response, ERR_STALE_LEASE_VERSION, 412)

    # A refused request mutates nothing (PRD §2.8).
    assert_version_unchanged(lease_before, fetch_lease(api, scenario.lease_id("I1")))
    _, meta = validate_paginated(
        api.list_elections(
            make_asset_manager_headers(), {"lease_id": scenario.lease_id("I1")}
        )
    )
    assert_pagination_meta(meta, expected_total=0)


def test_election_create_with_the_observed_lease_version_pins_its_pricing(api):
    """The election accepted on the observed lease version is ELECTED and moves no rent yet.

    PRD: "A new election is created in `ELECTED` with `elected_at` stamped and `abated_to_date_cents` at 0, and an election in that status **does not yet change effective rent at all**."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_lease_version_on_election_create_returns_412
    """
    scenario = _five_lease_center(api)
    condition = _add_i1_condition(api, scenario, grace_period_days=0, cure_period_days=30)
    go_dark(api, scenario.lease_id("I3"))

    lease_version = fetch_lease(api, scenario.lease_id("I1"))["version"]

    stale_attempt = api.create_election(
        scenario.lease_id("I1"),
        factories.election_payload(
            election_kind="RENT_REDUCTION",
            window_from_date="2026-08-01",
            window_through_date="2026-11-01",
            condition_id=condition["id"],
            expected_lease_version=lease_version - 1,
        ),
        make_tenant_rep_headers(scenario.tenant_id("I1")),
    )
    validate_error(stale_attempt, ERR_STALE_LEASE_VERSION, 412)

    election = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition["id"],
        expected_lease_version=lease_version,
    )

    assert election["status"] == "ELECTED", election
    # Shortfall 81.67 - 75.00 = 6.67 points, tier 1.5, so 10.01 after rounding.
    assert_pct(election["reduction_pct"], 10.01, "reduction_pct")
    assert_cents(election["reduced_rent_monthly_cents"], 899900, "reduced_rent_monthly_cents")
    assert_cents(election["abated_to_date_cents"], 0, "abated_to_date_cents")

    lease = fetch_lease(api, scenario.lease_id("I1"))
    assert_lease_dimensions(lease, effective_rent_monthly_cents=1000000)

    _, meta = validate_paginated(
        api.list_elections(
            make_asset_manager_headers(), {"lease_id": scenario.lease_id("I1")}
        )
    )
    assert_pagination_meta(meta, expected_total=1)


def test_center_version_increments_on_the_write_that_moves_its_derived_figures(api):
    """Opening the store, which moves the center's derived figures, bumps the center version by one.

    PRD: "Every record touched along the way has its `updated_at` refreshed and its `version` incremented; the center's `version` is incremented by every operation that changes any center-derived figure or posture."

    Design: Corner/cross_cutting_complexity_layers/center_version_increments_on_every_write
    """
    set_clock(api, DEFAULT_CLOCK_UTC)
    center = create_center(
        api, name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
    )
    tenant = create_tenant(
        api,
        legal_name="Boxmart Retail Inc",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    lease = draft_lease(
        api,
        center["id"],
        tenant["id"],
        suite_code="A1",
        gla_sqft=210000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=8000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )

    version_before = fetch_center(api, center["id"])["version"]
    execute_lease(api, lease["id"])
    version_after_execute = fetch_center(api, center["id"])["version"]

    open_lease(api, lease["id"])
    version_after_open = fetch_center(api, center["id"])["version"]

    assert version_after_open == version_after_execute + 1, (
        f"center version moved from {version_after_execute} to {version_after_open} "
        "on the open, which changes occupied_gla_sqft"
    )
    assert version_after_open > version_before, (
        f"center version {version_after_open} did not advance past {version_before}"
    )


def test_opening_the_only_anchor_settles_the_center_at_exactly_seventy_pct(api):
    """A center whose sole open lease fills exactly 70.00 pct of the area stays COMPLIANT.

    PRD: "Comparisons use the stored two-decimal percentage without re-rounding, and both occupancy tests are strictly-less-than: exactly 50.00 is not `FROZEN`, and exactly 70.00 is not `WATCH`."

    Design: Corner/cross_cutting_complexity_layers/center_version_increments_on_every_write
    """
    set_clock(api, DEFAULT_CLOCK_UTC)
    center = create_center(
        api, name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
    )
    tenant = create_tenant(
        api,
        legal_name="Boxmart Retail Inc",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    lease = draft_lease(
        api,
        center["id"],
        tenant["id"],
        suite_code="A1",
        gla_sqft=210000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=8000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )

    execute_lease(api, lease["id"])
    opened = open_lease(api, lease["id"])

    assert_lease_dimensions(opened, premises_status="OPEN")
    _assert_stamped_at(opened["opened_at"], "2026-08-01T00:00:00", "opened_at")

    assert_center_quantities(
        fetch_center(api, center["id"]),
        occupied_gla_sqft=210000,
        open_occupancy_pct=70.00,
        open_anchor_count=1,
        aggregate_effective_rent_cents=8000000,
        compliance_posture="COMPLIANT",
    )


def test_sweep_one_day_short_of_the_grace_window_confers_no_eligibility(api):
    """A sweep on breach day 29 advances the counter but leaves the benefited lease at NONE.

    PRD: "A condition that is already breached and still failing takes a self-transition on each later evaluation and on each compliance sweep: `consecutive_breach_days` is set to the number of whole days from `breach_detected_at` to the evaluation instant, `breach_detected_at` itself is left untouched, and the benefited lease moves from `NONE` to `ELIGIBLE` once `consecutive_breach_days` reaches or exceeds `grace_period_days`."

    Design: Corner/cross_cutting_complexity_layers/grace_period_threshold_reached_only_by_a_sweep_on_the_boundary_day
    """
    scenario = _five_lease_center(api)
    condition = _add_i1_condition(api, scenario, grace_period_days=30, cure_period_days=120)
    go_dark(api, scenario.lease_id("I3"))

    set_clock(api, "2026-08-30T00:00:00Z")
    report = run_sweep(api, scenario.center_id, user_id=COMPLIANCE_SWEEPER_USER_ID)
    assert_sweep_report_shape(report)

    assert report["newly_eligible_lease_count"] == 0, report
    assert report["breached_condition_count"] == 1, report

    stored = fetch_condition(api, condition["id"])
    assert stored["status"] == "BREACHED", stored
    assert stored["consecutive_breach_days"] == 29, stored
    _assert_stamped_at(
        stored["breach_detected_at"], "2026-08-01T00:00:00", "breach_detected_at"
    )

    lease = fetch_lease(api, scenario.lease_id("I1"))
    assert_lease_dimensions(lease, remedy_status="NONE")
    assert lease["remedy_eligible_at"] is None, lease


def test_sweep_on_the_grace_boundary_day_lifts_the_lease_to_eligible(api):
    """The sweep on breach day 30 reaches the inclusive grace boundary and confers eligibility.

    PRD: "Every lease whose breached condition has reached the point where `consecutive_breach_days` is greater than or equal to that condition's grace requirement moves `remedy_status` from `NONE` to `ELIGIBLE`."

    Design: Corner/cross_cutting_complexity_layers/grace_period_threshold_reached_only_by_a_sweep_on_the_boundary_day
    """
    scenario = _five_lease_center(api)
    condition = _add_i1_condition(api, scenario, grace_period_days=30, cure_period_days=120)
    go_dark(api, scenario.lease_id("I3"))

    set_clock(api, "2026-08-30T00:00:00Z")
    run_sweep(api, scenario.center_id, user_id=COMPLIANCE_SWEEPER_USER_ID)

    set_clock(api, "2026-08-31T00:00:00Z")
    report = run_sweep(api, scenario.center_id, user_id=COMPLIANCE_SWEEPER_USER_ID)

    assert report["newly_eligible_lease_count"] == 1, report
    assert report["compliance_posture"] == "BREACH", report

    stored = fetch_condition(api, condition["id"])
    assert stored["consecutive_breach_days"] == 30, stored
    _assert_stamped_at(
        stored["breach_detected_at"], "2026-08-01T00:00:00", "breach_detected_at"
    )

    lease = fetch_lease(api, scenario.lease_id("I1"))
    assert_lease_dimensions(lease, remedy_status="ELIGIBLE")
    _assert_stamped_at(
        lease["remedy_eligible_at"], "2026-08-31T00:00:00", "remedy_eligible_at"
    )

    center = fetch_center(api, scenario.center_id)
    _assert_stamped_at(center["last_sweep_at"], "2026-08-31T00:00:00", "last_sweep_at")
    assert_center_quantities(center, open_occupancy_pct=75.00)


def test_withdrawing_one_of_two_notices_decrements_the_violation_counter_once(api):
    """Withdrawing one of two notices against a lease drops open_violation_count from 2 to 1.

    PRD: "Withdrawal is accepted from `ISSUED` or `ESCALATED`, drives the notice to the terminal `WITHDRAWN`, and — when the notice had escalated — is the compensating action that reverses the entire hop chain: `escalated_at` returns to null, the violating lease's `use_compliance_status` moves from `IN_VIOLATION` back to `CLEAR`, or to `UNDER_NOTICE` when another issued notice against that lease remains; the benefited lease of the cited clause returns from `ELIGIBLE` to `NONE` when this notice was its only escalation source and no condition of that lease is `BREACHED`; the center's `open_violation_count` decrements; and posture is re-derived."

    Design: Corner/cross_cutting_complexity_layers/notice_counters_reconcile_after_withdrawal_of_one_of_two_notices
    """
    scenario = _five_lease_center(api)
    coffee_clause = add_clause(
        api,
        scenario.lease_id("I1"),
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["BOOKS"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )

    first_notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    # A PROHIBITED_USE notice cites the center's prohibited-use list, so it
    # carries no clause (PRD §3.6).
    second_notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="PROHIBITED_USE",
        narrative="Retail book wall in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id), open_violation_count=2
    )

    withdrawn = withdraw_notice(
        api,
        first_notice["id"],
        withdrawal_reason_code="ISSUED_IN_ERROR",
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )

    assert withdrawn["status"] == "WITHDRAWN", withdrawn
    assert fetch_notice(api, second_notice["id"])["status"] == "ISSUED"
    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        open_violation_count=1,
        open_occupancy_pct=85.00,
    )


def test_partial_withdrawal_keeps_the_lease_under_notice_and_the_center_on_watch(api):
    """The still-issued second notice keeps the lease UNDER_NOTICE, so posture stays WATCH.

    PRD: "A third derived field, `use_compliance_status`, tracks enforcement rather than either dimension: it reads `CLEAR` when no notice against the lease is `ISSUED`, `DISPUTED`, or `ESCALATED`; `UNDER_NOTICE` when at least one is `ISSUED` or `DISPUTED`; and `IN_VIOLATION` when at least one is `ESCALATED`."

    Design: Corner/cross_cutting_complexity_layers/notice_counters_reconcile_after_withdrawal_of_one_of_two_notices
    """
    scenario = _five_lease_center(api)
    coffee_clause = add_clause(
        api,
        scenario.lease_id("I1"),
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["BOOKS"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )

    first_notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="PROHIBITED_USE",
        narrative="Retail book wall in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )

    withdraw_notice(
        api,
        first_notice["id"],
        withdrawal_reason_code="ISSUED_IN_ERROR",
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )

    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I3")), use_compliance_status="UNDER_NOTICE"
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id), compliance_posture="WATCH"
    )


def test_status_filtered_notice_page_repartitions_after_a_cure(api):
    """Curing one of three ISSUED notices moves the filtered total from 3 to 2 and clears has_more.

    PRD: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the filters before pagination is applied and `has_more` indicates whether records remain beyond the current page."

    Design: Corner/cross_cutting_complexity_layers/notice_list_filter_and_offset_stay_consistent_under_mutation
    """
    scenario = _five_lease_center(api)
    coffee_clause = add_clause(
        api,
        scenario.lease_id("I1"),
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    add_clause(
        api,
        scenario.lease_id("I2"),
        protected_use_codes=["BOOKS"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )
    add_clause(
        api,
        scenario.lease_id("I3"),
        protected_use_codes=["FITNESS"],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )

    cured_notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    # PROHIBITED_USE notices carry no clause id (PRD §3.6).
    issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="PROHIBITED_USE",
        narrative="Retail book wall in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    issue_notice(
        api,
        scenario.lease_id("I2"),
        notice_kind="PROHIBITED_USE",
        narrative="Yoga studio inside the bookstore.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )

    first_page, first_meta = validate_paginated(
        api.list_notices(
            make_asset_manager_headers(),
            {"status": "ISSUED", "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2, first_page
    assert_pagination_meta(
        first_meta,
        expected_total=3,
        expected_limit=2,
        expected_offset=0,
        expected_has_more=True,
    )

    cure_notice(
        api,
        cured_notice["id"],
        cure_evidence_code="USE_DISCONTINUED",
        user_id=COMPLIANCE_ENFORCER_USER_ID,
        as_role="ComplianceOfficer",
    )

    second_page, second_meta = validate_paginated(
        api.list_notices(
            make_asset_manager_headers(),
            {"status": "ISSUED", "limit": 2, "offset": 0},
        )
    )
    assert len(second_page) == 2, second_page
    assert_pagination_meta(
        second_meta,
        expected_total=2,
        expected_limit=2,
        expected_offset=0,
        expected_has_more=False,
    )
    assert cured_notice["id"] not in ids_of(second_page), second_page

    _, lease_meta = validate_paginated(
        api.list_notices(
            make_asset_manager_headers(),
            {"violating_lease_id": scenario.lease_id("I3"), "status": "ISSUED"},
        )
    )
    assert_pagination_meta(lease_meta, expected_total=1)

    assert fetch_notice(api, cured_notice["id"])["status"] == "CURED"
    assert_center_quantities(
        fetch_center(api, scenario.center_id), open_violation_count=2
    )


def test_consummation_freezes_the_abatement_ledger_at_its_earned_value(api):
    """Consummating a closed reduction window freezes the per-election accrual and the lease total.

    PRD: "An active reduction may be consummated once its `window_through_date` is on or before the current date; `abated_to_date_cents` freezes at its final value and keeps contributing to `total_abated_cents`, `effective_rent_monthly_cents` is recomputed because the window no longer covers today, and the lease's `remedy_status` falls to `ELIGIBLE` when a breached condition remains or to `NONE` otherwise."

    Design: Corner/cross_cutting_complexity_layers/abatement_ledger_reconciles_after_consummation
    """
    scenario = _five_lease_center(api)
    condition = _add_i1_condition(api, scenario, grace_period_days=0, cure_period_days=30)
    go_dark(api, scenario.lease_id("I3"))

    election = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-10-20",
        condition_id=condition["id"],
    )
    approve_election(api, election["id"])

    set_clock(api, "2026-11-01T00:00:00Z")
    consummated = consummate_election(api, election["id"])

    assert consummated["status"] == "CONSUMMATED", consummated
    assert_pct(consummated["reduction_pct"], 10.01, "reduction_pct")
    # 80 whole days / 30 = 2.6667 months on 100100 cents a month.
    assert_cents(consummated["abated_to_date_cents"], 266937, "abated_to_date_cents")
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")), total_abated_cents=266937
    )


def test_consummation_returns_effective_and_aggregate_rent_to_the_unabated_figures(api):
    """Once the window no longer covers today the lease and center rents return to unabated.

    PRD: "The center's `aggregate_effective_rent_cents` is then the sum of `effective_rent_monthly_cents` over the leases of that center whose `premises_status` is `OPEN` or `DARK`."

    Design: Corner/cross_cutting_complexity_layers/abatement_ledger_reconciles_after_consummation
    """
    scenario = _five_lease_center(api)
    condition = _add_i1_condition(api, scenario, grace_period_days=0, cure_period_days=30)
    go_dark(api, scenario.lease_id("I3"))

    election = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-10-20",
        condition_id=condition["id"],
    )
    approve_election(api, election["id"])

    set_clock(api, "2026-11-01T00:00:00Z")
    consummate_election(api, election["id"])

    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")),
        remedy_status="ELIGIBLE",
        effective_rent_monthly_cents=1000000,
    )
    assert fetch_condition(api, condition["id"])["status"] == "BREACHED"
    # 6000000 + 4000000 + 1000000 + 1200000 + 1500000 over the OPEN and DARK leases.
    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        aggregate_effective_rent_cents=13700000,
    )


def test_go_dark_cascade_is_fully_visible_without_any_further_write(api):
    """The go-dark response and the reads that follow it already show the whole cascade.

    PRD: "Where §3 numbers the hops of a cascade, the numbering is normative: the whole chain completes within the request, and a partially applied chain is not an acceptable outcome."

    Design: Corner/consistency_model/derived_center_fields_are_visible_in_the_same_request
    """
    scenario = _five_lease_center(api)
    condition = _add_i1_condition(api, scenario, grace_period_days=0, cure_period_days=30)

    darkened = go_dark(api, scenario.lease_id("I3"))

    assert_lease_dimensions(darkened, premises_status="DARK")
    _assert_stamped_at(darkened["dark_since"], "2026-08-01T00:00:00", "dark_since")

    center = get_success_data(
        api.get_center(scenario.center_id, make_lender_rep_headers()), 200
    )
    assert_center_quantities(
        center,
        occupied_gla_sqft=225000,
        open_occupancy_pct=75.00,
        compliance_posture="BREACH",
    )

    stored_condition = get_success_data(
        api.get_condition(condition["id"], make_lender_rep_headers()), 200
    )
    assert stored_condition["status"] == "BREACHED", stored_condition

    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")), remedy_status="ELIGIBLE"
    )
