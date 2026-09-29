"""Validation-ladder precedence collisions and inclusive/exclusive threshold boundaries.

The tests here cover two areas of the Retail Co-Tenancy & Exclusive Use
Administration API: the fixed order in which two simultaneously violated
validations are reported (PRD §2.9), and the exact comparators of the co-tenancy
basis test and the exclusive-use carve-out suppression test (PRD §3.2, §3.3).
"""
from test_helpers import (
    ERR_ABATEMENT_STACK_EXCEEDED,
    ERR_ABATEMENT_WINDOW_INVALID,
    ERR_CENTER_EXECUTION_FROZEN,
    ERR_EXCLUSIVE_USE_CONFLICT,
    ERR_REMEDY_KIND_NOT_PERMITTED,
    ERR_REMEDY_NOT_ELIGIBLE,
    add_anchor_requirement,
    add_clause,
    add_condition,
    approve_election,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_null,
    assert_pct,
    assert_screen_decision_shape,
    assert_version_unchanged,
    create_center,
    create_tenant,
    draft_lease,
    elect_remedy,
    execute_lease,
    factories,
    fetch_center,
    fetch_condition,
    fetch_election,
    fetch_lease,
    go_dark,
    make_asset_manager_headers,
    make_lease_administrator_headers,
    make_tenant_rep_headers,
    open_lease,
    reopen_lease,
    screen_use,
    set_clock,
    validate_error,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_REBREACH = "2026-09-15T00:00:00Z"

# suite, tenant legal name, notice email, use code, national chain, gla, parcel, rent
BASE_LEASE_SPECS = (
    ("A1", "Boxmart Retail Inc", "legal@boxmart.example", "DISCOUNT_DEPT", True,
     120000, "ANCHOR_BOX", 6000000),
    ("A2", "Grocerway Foods LLC", "legal@grocerway.example", "GROCERY", True,
     100000, "ANCHOR_BOX", 4000000),
    ("I1", "Bean Theory Coffee LLC", "legal@beantheory.example", "COFFEE", False,
     2000, "INLINE", 1000000),
    ("I2", "Margin Books LLC", "legal@marginbooks.example", "BOOKS", False,
     3000, "INLINE", 1200000),
    ("I3", "Pulse Fitness Group", "legal@pulsefitness.example", "FITNESS", True,
     30000, "INLINE", 1500000),
)


def _open_five_lease_center(api):
    """A 300,000 sqft center with 255,000 sqft open across five leases (85.00%)."""
    set_clock(api, CLOCK_START)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    leases = {}
    tenants = {}
    for suite, legal_name, email, use_code, chain, gla, parcel, rent in BASE_LEASE_SPECS:
        tenant = create_tenant(
            api,
            legal_name=legal_name,
            notice_email=email,
            primary_use_code=use_code,
            is_national_chain=chain,
        )
        lease = draft_lease(
            api,
            center["id"],
            tenant["id"],
            suite_code=suite,
            gla_sqft=gla,
            parcel_kind=parcel,
            primary_use_code=use_code,
            base_rent_monthly_cents=rent,
            commencement_date="2026-01-01",
            expiration_date="2036-12-31",
        )
        tenants[suite] = tenant
        leases[suite] = lease
    for suite in leases:
        execute_lease(api, leases[suite]["id"])
    for suite in leases:
        open_lease(api, leases[suite]["id"])
    return {"center_id": center["id"], "leases": leases, "tenants": tenants}


# --------------------------------------------------------------------------
# Frozen posture (rung 9) versus exclusive-use screening (rung 14) on execute
# --------------------------------------------------------------------------
def _setup_books_clause_and_books_candidate(api):
    """Five open leases, a BOOKS exclusive, two 81.67% conditions, a BOOKS draft."""
    world = _open_five_lease_center(api)
    world["clause"] = add_clause(
        api,
        world["leases"]["I2"]["id"],
        protected_use_codes=["BOOKS"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    for suite, key in (("I1", "condition_i1"), ("I2", "condition_i2")):
        world[key] = add_condition(
            api,
            world["leases"][suite]["id"],
            condition_kind="ONGOING",
            measurement_basis="GLA_PCT",
            required_occupancy_pct=81.67,
            required_anchor_count=2,
            grace_period_days=0,
            cure_period_days=30,
            remedy_type="RENT_REDUCTION_THEN_TERMINATION",
            max_reduction_pct=25.0,
        )
    candidate_tenant = create_tenant(
        api,
        legal_name="Chapter Two Books LLC",
        notice_email="legal@chaptertwo.example",
        primary_use_code="BOOKS",
        is_national_chain=False,
    )
    world["tenants"]["I4"] = candidate_tenant
    world["leases"]["I4"] = draft_lease(
        api,
        world["center_id"],
        candidate_tenant["id"],
        suite_code="I4",
        gla_sqft=4000,
        parcel_kind="INLINE",
        primary_use_code="BOOKS",
        base_rent_monthly_cents=900000,
        commencement_date="2026-09-01",
        expiration_date="2036-08-31",
    )
    return world


def test_frozen_center_outranks_exclusive_use_conflict_on_execute(api):
    """A frozen center refuses execution with the rung-9 error even though screening also conflicts.

    PRD: "When a lease execution targets a `FROZEN` center *and* the candidate use conflicts with an active exclusive-use clause, the answer is `ERR_CENTER_EXECUTION_FROZEN` (409), never `ERR_EXCLUSIVE_USE_CONFLICT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_exclusive_use_conflict_on_execute
    """
    world = _setup_books_clause_and_books_candidate(api)
    candidate_id = world["leases"]["I4"]["id"]

    # Suite I3 goes dark, dropping occupancy to 75.00% and breaching both
    # 81.67% conditions, which freezes the center (PRD §2.6).
    go_dark(api, world["leases"]["I3"]["id"])
    center_before = fetch_center(api, world["center_id"])
    assert_center_quantities(
        center_before,
        occupied_gla_sqft=225000,
        open_occupancy_pct=75.00,
        compliance_posture="FROZEN",
    )
    candidate_before = fetch_lease(api, candidate_id)

    res = api.execute_lease(candidate_id, None, make_lease_administrator_headers())
    validate_error(res, ERR_CENTER_EXECUTION_FROZEN)

    candidate_after = fetch_lease(api, candidate_id)
    assert_lease_dimensions(candidate_after, premises_status="DRAFT")
    assert_version_unchanged(candidate_before, candidate_after)
    center_after = fetch_center(api, world["center_id"])
    assert_center_quantities(
        center_after, open_occupancy_pct=75.00, compliance_posture="FROZEN"
    )


def test_exclusive_use_conflict_surfaces_once_the_center_is_not_frozen(api):
    """With the rung-9 frozen violation absent, the same execution reports the rung-14 screening conflict.

    PRD: "Exclusive-use screening — a lease may not be executed while screening returns a conflicting decision for its `primary_use_code`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_exclusive_use_conflict_on_execute
    """
    world = _setup_books_clause_and_books_candidate(api)
    candidate_id = world["leases"]["I4"]["id"]

    # No suite goes dark here, so occupancy stays at 85.00% and the center is
    # not frozen; only the BOOKS exclusive stands in the candidate's way.
    center_before = fetch_center(api, world["center_id"])
    assert_center_quantities(
        center_before, open_occupancy_pct=85.00, compliance_posture="COMPLIANT"
    )
    candidate_before = fetch_lease(api, candidate_id)

    res = api.execute_lease(candidate_id, None, make_lease_administrator_headers())
    validate_error(res, ERR_EXCLUSIVE_USE_CONFLICT)

    candidate_after = fetch_lease(api, candidate_id)
    assert_lease_dimensions(candidate_after, premises_status="DRAFT")
    assert_version_unchanged(candidate_before, candidate_after)
    assert_center_quantities(
        fetch_center(api, world["center_id"]), compliance_posture="COMPLIANT"
    )


# --------------------------------------------------------------------------
# Remedy eligibility (rung 11) versus permitted election kind (rung 16)
# --------------------------------------------------------------------------
def _setup_termination_only_condition(api):
    """Five open leases and one TERMINATION_ONLY condition benefiting suite I1."""
    world = _open_five_lease_center(api)
    world["condition"] = add_condition(
        api,
        world["leases"]["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="TERMINATION_ONLY",
        max_reduction_pct=25.0,
    )
    return world


def _post_rent_reduction_election(api, world):
    """Elect a RENT_REDUCTION against the TERMINATION_ONLY condition as I1's tenant."""
    lease = fetch_lease(api, world["leases"]["I1"]["id"])
    return api.create_election(
        lease["id"],
        factories.election_payload(
            election_kind="RENT_REDUCTION",
            window_from_date="2026-08-01",
            window_through_date="2026-11-01",
            condition_id=world["condition"]["id"],
            expected_lease_version=lease["version"],
        ),
        make_tenant_rep_headers(world["tenants"]["I1"]["id"]),
    )


def test_remedy_not_eligible_outranks_remedy_kind_not_permitted(api):
    """An impermissible kind elected on an ineligible lease reports the rung-11 eligibility error.

    PRD: "When an election's kind is not permitted by the condition *and* the lease is not yet eligible, the answer is `ERR_REMEDY_NOT_ELIGIBLE` (409), never `ERR_REMEDY_KIND_NOT_PERMITTED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/remedy_not_eligible_outranks_remedy_kind_not_permitted
    """
    world = _setup_termination_only_condition(api)

    # Everything is open at 85.00%, so the condition is SATISFIED and suite I1
    # has never reached remedy eligibility (PRD §3.3).
    assert fetch_condition(api, world["condition"]["id"])["status"] == "SATISFIED"
    lease_before = fetch_lease(api, world["leases"]["I1"]["id"])
    assert_lease_dimensions(lease_before, remedy_status="NONE")

    res = _post_rent_reduction_election(api, world)
    validate_error(res, ERR_REMEDY_NOT_ELIGIBLE)

    condition_after = fetch_condition(api, world["condition"]["id"])
    assert condition_after["status"] == "SATISFIED"
    lease_after = fetch_lease(api, world["leases"]["I1"]["id"])
    assert_lease_dimensions(
        lease_after, remedy_status="NONE", effective_rent_monthly_cents=1000000
    )
    assert_version_unchanged(lease_before, lease_after)


def test_remedy_kind_not_permitted_surfaces_once_the_lease_is_eligible(api):
    """With the rung-11 eligibility violation absent, the same election reports the rung-16 kind error.

    PRD: "The condition's `remedy_type` constrains which kinds are permitted, and a mismatch answers `ERR_REMEDY_KIND_NOT_PERMITTED`: `RENT_REDUCTION_ONLY` permits only `RENT_REDUCTION`; `TERMINATION_ONLY` permits only `TERMINATION`; `RENT_REDUCTION_THEN_TERMINATION` permits both `RENT_REDUCTION` and `TERMINATION`; and `SUBSTITUTE_RENT` is permitted only for an election sourced from an escalated notice."

    Design: Difficulty/priority_pair_validation_conflict/remedy_not_eligible_outranks_remedy_kind_not_permitted
    """
    world = _setup_termination_only_condition(api)

    # Suite I3 goes dark, dropping occupancy to 75.00%; the condition breaches
    # and its zero grace period makes suite I1 eligible in the same request.
    go_dark(api, world["leases"]["I3"]["id"])
    assert fetch_condition(api, world["condition"]["id"])["status"] == "BREACHED"
    lease_before = fetch_lease(api, world["leases"]["I1"]["id"])
    assert_lease_dimensions(lease_before, remedy_status="ELIGIBLE")

    res = _post_rent_reduction_election(api, world)
    validate_error(res, ERR_REMEDY_KIND_NOT_PERMITTED)

    lease_after = fetch_lease(api, world["leases"]["I1"]["id"])
    assert_lease_dimensions(
        lease_after, remedy_status="ELIGIBLE", effective_rent_monthly_cents=1000000
    )
    assert_version_unchanged(lease_before, lease_after)


# --------------------------------------------------------------------------
# Abatement window validity (rung 20) versus the stacking cap (rung 21)
# --------------------------------------------------------------------------
def _setup_active_reduction_on_dark_anchor(api):
    """A named-anchor condition breached by a dark anchor, with one approved reduction."""
    world = _open_five_lease_center(api)
    condition = add_condition(
        api,
        world["leases"]["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=90.0,
    )
    add_anchor_requirement(
        api,
        condition["id"],
        world["leases"]["A1"]["id"],
        substitution_allowed=False,
        min_substitute_gla_sqft=0,
    )
    # Anchor A1 goes dark: occupancy falls to 45.00%, the named anchor stops
    # counting open, and the condition breaches at 2026-08-01.
    go_dark(api, world["leases"]["A1"]["id"])
    first = elect_remedy(
        api,
        world["leases"]["I1"]["id"],
        world["tenants"]["I1"]["id"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-12-01",
        condition_id=condition["id"],
    )
    world["condition"] = condition
    world["first_election"] = approve_election(api, first["id"])
    return world


def _cure_then_rebreach(api, world):
    """Reopen the anchor to cure, advance the clock, and re-breach at 2026-09-15."""
    reopen_lease(api, world["leases"]["A1"]["id"])
    set_clock(api, CLOCK_REBREACH)
    go_dark(api, world["leases"]["A1"]["id"])


def test_abatement_window_invalid_outranks_abatement_stack_exceeded(api):
    """An approval whose window predates the fresh breach reports the rung-20 window error.

    PRD: "When an approval's window predates `breach_detected_at` *and* the aggregate reduction would exceed 100%, the answer is `ERR_ABATEMENT_WINDOW_INVALID` (422), never `ERR_ABATEMENT_STACK_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/abatement_window_invalid_outranks_abatement_stack_exceeded
    """
    world = _setup_active_reduction_on_dark_anchor(api)
    second = elect_remedy(
        api,
        world["leases"]["I1"]["id"],
        world["tenants"]["I1"]["id"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-09-01",
        window_through_date="2026-12-01",
        condition_id=world["condition"]["id"],
    )
    # The cure/re-breach cycle stamps a new breach episode at 2026-09-15, which
    # is later than the second election's window_from_date (PRD §3.3).
    _cure_then_rebreach(api, world)
    condition = fetch_condition(api, world["condition"]["id"])
    assert condition["status"] == "BREACHED"
    assert condition["breach_detected_at"].startswith("2026-09-15")

    res = api.approve_election(second["id"], None, make_asset_manager_headers())
    validate_error(res, ERR_ABATEMENT_WINDOW_INVALID)

    assert fetch_election(api, second["id"])["status"] == "ELECTED"
    first_after = fetch_election(api, world["first_election"]["id"])
    assert first_after["status"] == "REDUCTION_ACTIVE"
    assert_pct(first_after["reduction_pct"], 83.34, "reduction_pct")
    assert_lease_dimensions(
        fetch_lease(api, world["leases"]["I1"]["id"]),
        effective_rent_monthly_cents=166600,
    )


def test_abatement_stack_exceeded_surfaces_once_the_window_is_valid(api):
    """With the rung-20 window violation absent, the same approval reports the rung-21 stacking cap.

    PRD: "Abatement stacking cap — the summed `reduction_pct` across the lease's active reductions whose half-open windows overlap the approved election's window may not exceed 100.00."

    Design: Difficulty/priority_pair_validation_conflict/abatement_window_invalid_outranks_abatement_stack_exceeded
    """
    world = _setup_active_reduction_on_dark_anchor(api)
    _cure_then_rebreach(api, world)
    condition = fetch_condition(api, world["condition"]["id"])
    assert condition["breach_detected_at"].startswith("2026-09-15")

    # This election's window opens exactly on the new breach date, so the
    # window check passes and only the stacking cap is violated.
    second = elect_remedy(
        api,
        world["leases"]["I1"]["id"],
        world["tenants"]["I1"]["id"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-09-15",
        window_through_date="2026-12-01",
        condition_id=world["condition"]["id"],
    )
    assert_pct(second["reduction_pct"], 83.34, "reduction_pct")

    res = api.approve_election(second["id"], None, make_asset_manager_headers())
    validate_error(res, ERR_ABATEMENT_STACK_EXCEEDED)

    assert fetch_election(api, second["id"])["status"] == "ELECTED"
    assert (
        fetch_election(api, world["first_election"]["id"])["status"]
        == "REDUCTION_ACTIVE"
    )
    assert_lease_dimensions(
        fetch_lease(api, world["leases"]["I1"]["id"]),
        effective_rent_monthly_cents=166600,
    )


# --------------------------------------------------------------------------
# The basis test comparator at exactly the required percentage
# --------------------------------------------------------------------------
def _setup_paired_occupancy_thresholds(api):
    """Two conditions differing only by 0.01 in required_occupancy_pct."""
    world = _open_five_lease_center(api)
    world["condition_at"] = add_condition(
        api,
        world["leases"]["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=75.0,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    world["condition_above"] = add_condition(
        api,
        world["leases"]["I2"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=75.01,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    return world


def test_occupancy_exactly_equal_to_the_requirement_stays_satisfied(api):
    """A condition requiring exactly the measured 75.00% survives the drop unbreached.

    PRD: "A percentage exactly equal to the requirement is satisfied."

    Design: Difficulty/boundary_precision_check/occupancy_threshold_exactly_met_versus_one_hundredth_above
    """
    world = _setup_paired_occupancy_thresholds(api)

    go_dark(api, world["leases"]["I3"]["id"])

    center = fetch_center(api, world["center_id"])
    assert_center_quantities(
        center, occupied_gla_sqft=225000, open_occupancy_pct=75.00
    )
    condition = fetch_condition(api, world["condition_at"]["id"])
    assert condition["status"] == "SATISFIED"
    assert_null(condition["breach_detected_at"], "breach_detected_at")
    assert condition["consecutive_breach_days"] == 0
    assert_lease_dimensions(
        fetch_lease(api, world["leases"]["I1"]["id"]), remedy_status="NONE"
    )


def test_occupancy_one_hundredth_below_the_requirement_breaches(api):
    """A condition requiring 75.01% breaches on the same measured 75.00%.

    PRD: "First, the **basis test**: for a `GLA_PCT` condition, the controlling occupancy percentage must be greater than or equal to `required_occupancy_pct`; for a `STORE_COUNT` condition, the controlling non-anchor open-store count must be greater than or equal to `required_open_store_count`."

    Design: Difficulty/boundary_precision_check/occupancy_threshold_exactly_met_versus_one_hundredth_above
    """
    world = _setup_paired_occupancy_thresholds(api)

    go_dark(api, world["leases"]["I3"]["id"])

    center = fetch_center(api, world["center_id"])
    assert_center_quantities(
        center,
        occupied_gla_sqft=225000,
        open_occupancy_pct=75.00,
        compliance_posture="BREACH",
    )
    condition = fetch_condition(api, world["condition_above"]["id"])
    assert condition["status"] == "BREACHED"
    assert condition["breach_detected_at"].startswith("2026-08-01")
    assert_lease_dimensions(
        fetch_lease(api, world["leases"]["I2"]["id"]), remedy_status="ELIGIBLE"
    )


# --------------------------------------------------------------------------
# Carve-out suppression: inclusive on both the sqft and the percentage cap
# --------------------------------------------------------------------------
def _setup_carve_out_candidates(api):
    """A BOOKS exclusive carved out at 2,500 sqft / 12.0%, plus three draft candidates."""
    world = _open_five_lease_center(api)
    world["clause"] = add_clause(
        api,
        world["leases"]["I2"]["id"],
        protected_use_codes=["BOOKS"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=2500,
        incidental_sales_pct_cap=12.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    candidates = (
        ("I4", "Wren Gift Co", "legal@wrengift.example", "GIFTS", 2500, "BOOKS",
         ["BOOKS"], 12.0, 800000),
        ("I5", "Aster Gift Co", "legal@astergift.example", "GIFTS", 2501, "BOOKS",
         ["BOOKS"], 12.0, 800000),
        ("I6", "Paws Pet Supply LLC", "legal@pawspet.example", "PETS", 1800, "PETS",
         None, None, 700000),
    )
    for suite, legal_name, email, tenant_use, gla, use_code, incidental, pct, rent in candidates:
        tenant = create_tenant(
            api,
            legal_name=legal_name,
            notice_email=email,
            primary_use_code=tenant_use,
            is_national_chain=False,
        )
        world["tenants"][suite] = tenant
        world["leases"][suite] = draft_lease(
            api,
            world["center_id"],
            tenant["id"],
            suite_code=suite,
            gla_sqft=gla,
            parcel_kind="INLINE",
            primary_use_code=use_code,
            base_rent_monthly_cents=rent,
            commencement_date="2026-09-01",
            expiration_date="2036-08-31",
            incidental_use_codes=incidental,
            projected_incidental_sales_pct=pct,
        )
    return world


def test_carve_out_suppresses_the_clause_exactly_at_both_caps(api):
    """A candidate at exactly 2,500 sqft and exactly 12.0% incidental sales screens CLEAR.

    PRD: "Both comparisons are at-most comparisons, so a value exactly equal to the cap still qualifies for suppression."

    Design: Difficulty/boundary_precision_check/exclusive_use_carve_out_inclusive_gla_boundary_and_empty_pool
    """
    world = _setup_carve_out_candidates(api)

    decision = screen_use(api, world["leases"]["I4"]["id"])

    assert_screen_decision_shape(decision)
    assert decision["decision"] == "CLEAR"
    assert decision["screened_use_code"] == "BOOKS"
    assert decision["eligible_clause_count"] == 1
    assert decision["conflicting_clause_count"] == 0
    assert decision["carve_out_applied"] is True
    assert_null(decision["controlling_clause_id"], "controlling_clause_id")
    assert_lease_dimensions(
        fetch_lease(api, world["leases"]["I4"]["id"]), premises_status="DRAFT"
    )


def test_carve_out_one_sqft_past_the_cap_conflicts(api):
    """A candidate one square foot above the carve-out is no longer suppressed and conflicts.

    PRD: "Each eligible clause is then tested for **carve-out suppression**, and all three conditions must hold for the clause to be suppressed: the candidate's `primary_use_code` must appear in the candidate's own `incidental_use_codes` array, the candidate's `projected_incidental_sales_pct` must be at most the clause's `incidental_sales_pct_cap`, and the candidate's `gla_sqft` must be at most the clause's `gla_carve_out_sqft`."

    Design: Difficulty/boundary_precision_check/exclusive_use_carve_out_inclusive_gla_boundary_and_empty_pool
    """
    world = _setup_carve_out_candidates(api)

    decision = screen_use(api, world["leases"]["I5"]["id"])

    assert_screen_decision_shape(decision)
    assert decision["decision"] == "CONFLICT"
    assert decision["screened_use_code"] == "BOOKS"
    assert decision["eligible_clause_count"] == 1
    assert decision["conflicting_clause_count"] == 1
    assert decision["carve_out_applied"] is False
    assert decision["controlling_clause_id"] == world["clause"]["id"]
    assert_lease_dimensions(
        fetch_lease(api, world["leases"]["I5"]["id"]), premises_status="DRAFT"
    )


def test_unprotected_use_screens_clear_on_an_empty_eligible_pool(api):
    """A use no clause protects screens CLEAR with an empty eligible pool rather than erroring.

    PRD: "When there are no conflicts the `decision` is `CLEAR` and `controlling_clause_id` is null — this is also the fallback when the eligible pool was empty to begin with."

    Design: Difficulty/boundary_precision_check/exclusive_use_carve_out_inclusive_gla_boundary_and_empty_pool
    """
    world = _setup_carve_out_candidates(api)

    decision = screen_use(api, world["leases"]["I6"]["id"])

    assert_screen_decision_shape(decision)
    assert decision["decision"] == "CLEAR"
    assert decision["screened_use_code"] == "PETS"
    assert decision["eligible_clause_count"] == 0
    assert decision["conflicting_clause_count"] == 0
    assert decision["carve_out_applied"] is False
    assert_null(decision["controlling_clause_id"], "controlling_clause_id")
