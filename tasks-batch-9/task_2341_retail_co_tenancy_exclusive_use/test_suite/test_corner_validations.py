"""Validation-rule tests for co-tenancy conditions, exclusive-use enforcement,
remedy elections, estoppel acceptance and redevelopment recording.

Each test builds its own preconditions through the API and then exercises one
request-validation rule stated in the PRD.
"""
from test_helpers import (
    COMPLIANCE_ENFORCER_USER_ID,
    ERR_ABATEMENT_WINDOW_INVALID,
    ERR_CENTER_SCOPE_MISMATCH,
    ERR_CLAUSE_NOT_ACTIVE,
    ERR_CONDITION_KIND_INVALID,
    ERR_CURE_PERIOD_NOT_EXPIRED,
    ERR_LENDER_CONDITIONS_NOT_MET,
    ERR_MEASUREMENT_BASIS_MISMATCH,
    ERR_PROTECTED_RIGHTS_CONSENT_REQUIRED,
    ERR_RADIUS_WINDOW_INACTIVE,
    ERR_REMEDY_KIND_NOT_PERMITTED,
    ERR_SUITE_ALREADY_LEASED,
    add_clause,
    add_condition,
    add_radius_restriction,
    assert_cents,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_null,
    assert_pagination_meta,
    assert_pct,
    create_center,
    create_tenant,
    draft_lease,
    elect_remedy,
    execute_lease,
    factories,
    fetch_center,
    fetch_certificate,
    fetch_clause,
    fetch_condition,
    fetch_election,
    fetch_lease,
    fetch_notice,
    fetch_plan,
    get_success_data,
    go_dark,
    issue_notice,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lease_administrator_headers,
    make_lender_rep_headers,
    make_tenant_rep_headers,
    open_lease,
    plan_redevelopment,
    record_plan,
    report_radius_violation,
    request_certificate,
    set_clock,
    sign_certificate,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-01T00:00:00Z"

# Northgate Crossing: two anchor boxes and three inline suites, all opened, so
# occupied GLA is 255000 of 300000 and open_occupancy_pct is 85.00 (PRD §2.5).
NORTHGATE_LEASES = (
    ("A1", 120000, "ANCHOR_BOX", "DISCOUNT_DEPT", 6000000,
     "Boxmart Retail Inc", "legal@boxmart.example", True),
    ("A2", 100000, "ANCHOR_BOX", "GROCERY", 4000000,
     "Grocerway Foods LLC", "legal@grocerway.example", True),
    ("I1", 2000, "INLINE", "COFFEE", 1000000,
     "Bean Theory Coffee LLC", "legal@beantheory.example", False),
    ("I2", 3000, "INLINE", "BOOKS", 1200000,
     "Margin Books LLC", "legal@marginbooks.example", False),
    ("I3", 30000, "INLINE", "FITNESS", 1500000,
     "Pulse Fitness Group", "legal@pulsefitness.example", True),
)


def _build_northgate(api):
    """Register the center, draft all five leases, execute them, then open them."""
    set_clock(api, CLOCK)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    tenants = {}
    leases = {}
    for suite, gla, parcel_kind, use_code, rent, legal_name, email, chain in (
        NORTHGATE_LEASES
    ):
        tenants[suite] = create_tenant(
            api,
            legal_name=legal_name,
            notice_email=email,
            primary_use_code=use_code,
            is_national_chain=chain,
        )
        leases[suite] = draft_lease(
            api,
            center["id"],
            tenants[suite]["id"],
            suite_code=suite,
            gla_sqft=gla,
            parcel_kind=parcel_kind,
            primary_use_code=use_code,
            base_rent_monthly_cents=rent,
            commencement_date="2026-01-01",
            expiration_date="2036-12-31",
        )
    for suite in leases:
        execute_lease(api, leases[suite]["id"])
    for suite in leases:
        open_lease(api, leases[suite]["id"])
    return center["id"], tenants, leases


def _add_optical_tenant(api):
    return create_tenant(
        api,
        legal_name="Halcyon Optical LLC",
        notice_email="legal@halcyonoptical.example",
        primary_use_code="OPTICAL",
        is_national_chain=False,
    )


def _lease_version_as_tenant(api, lease_id, tenant_id):
    """Read the lease version the electing tenant will pin (PRD §2.8)."""
    res = api.get_lease(lease_id, make_tenant_rep_headers(tenant_id))
    return get_success_data(res, 200)["version"]


def _assert_instant(value, expected_prefix, label):
    """Instants are rendered in ISO-8601 UTC (PRD §2.4)."""
    assert value is not None, f"{label} should be stamped, got null"
    assert value.startswith(expected_prefix), f"{label} is {value}, expected {expected_prefix}"


def _total_count(res):
    rows, meta = validate_paginated(res)
    assert_pagination_meta(meta)
    return meta["total_count"], rows


# --------------------------------------------------------------------------
# Suite uniqueness
# --------------------------------------------------------------------------
def test_duplicate_suite_code_in_one_center_is_refused(api):
    """A second live lease for a suite code already leased in the center is refused.

    PRD: "Two leases of the same center may not share a `suite_code` unless one of them is `TERMINATED`; the collision answers `ERR_SUITE_ALREADY_LEASED`, and it is checked both when the lease is drafted and again when it is executed, because a competing lease may have been executed in between."

    Design: Corner/validations/duplicate_suite_code_in_one_center_returns_suite_already_leased
    """
    center_id, _tenants, _leases = _build_northgate(api)
    replacement = _add_optical_tenant(api)

    res = api.create_lease(
        center_id,
        factories.lease_payload(
            tenant_id=replacement["id"],
            suite_code="I1",
            gla_sqft=2000,
            parcel_kind="INLINE",
            primary_use_code="OPTICAL",
            base_rent_monthly_cents=500000,
            commencement_date="2026-09-01",
            expiration_date="2036-08-31",
        ),
        make_lease_administrator_headers(),
    )

    assert res.status_code == 409
    validate_error(res, ERR_SUITE_ALREADY_LEASED)
    assert_center_quantities(fetch_center(api, center_id), occupied_gla_sqft=255000)


def test_same_suite_code_in_a_different_center_is_accepted(api):
    """Suite uniqueness is scoped to one center, so the same code drafts elsewhere.

    PRD: "Suite uniqueness — a center may not hold two leases with the same `suite_code` unless the other one is `TERMINATED`."

    Design: Corner/validations/duplicate_suite_code_in_one_center_returns_suite_already_leased
    """
    center_id, _tenants, _leases = _build_northgate(api)
    other_center = create_center(
        api,
        name="Riverbend Commons",
        total_gla_sqft=250000,
        occupancy_grace_days=30,
    )
    replacement = _add_optical_tenant(api)

    lease = draft_lease(
        api,
        other_center["id"],
        replacement["id"],
        suite_code="I1",
        gla_sqft=2000,
        parcel_kind="INLINE",
        primary_use_code="OPTICAL",
        base_rent_monthly_cents=500000,
        commencement_date="2026-09-01",
        expiration_date="2036-08-31",
    )

    assert lease["suite_code"] == "I1"
    assert lease["center_id"] == other_center["id"]
    assert_lease_dimensions(lease, premises_status="DRAFT")
    assert_center_quantities(fetch_center(api, center_id), occupied_gla_sqft=255000)


# --------------------------------------------------------------------------
# Center scope of body foreign keys
# --------------------------------------------------------------------------
def test_anchor_requirement_naming_another_centers_lease_is_refused(api):
    """An anchor requirement may not name an anchor lease of a different center.

    PRD: "Center scope — every entity referenced by one request must sit inside the same shopping center: a condition's `anchor_lease_id`, an election's `condition_id`, a notice's `clause_id` and `violating_lease_id`, a certificate's `measurement_id`, and a plan's `pad_parcel_lease_id`."

    Design: Corner/validations/anchor_requirement_naming_another_centers_lease_returns_scope_mismatch
    """
    set_clock(api, CLOCK)
    alpha = create_center(
        api, name="Alpha Center", total_gla_sqft=300000, occupancy_grace_days=30
    )
    beta = create_center(
        api, name="Beta Center", total_gla_sqft=200000, occupancy_grace_days=30
    )
    alpha_tenant = create_tenant(
        api,
        legal_name="Alpha Anchor Inc",
        notice_email="legal@alphaanchor.example",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    beta_tenant = create_tenant(
        api,
        legal_name="Beta Anchor Inc",
        notice_email="legal@betaanchor.example",
        primary_use_code="GROCERY",
        is_national_chain=True,
    )
    alpha_lease = draft_lease(
        api,
        alpha["id"],
        alpha_tenant["id"],
        suite_code="A1",
        gla_sqft=210000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=8000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )
    beta_lease = draft_lease(
        api,
        beta["id"],
        beta_tenant["id"],
        suite_code="A1",
        gla_sqft=150000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="GROCERY",
        base_rent_monthly_cents=5000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )
    execute_lease(api, alpha_lease["id"])
    execute_lease(api, beta_lease["id"])
    open_lease(api, alpha_lease["id"])
    open_lease(api, beta_lease["id"])
    condition = add_condition(
        api,
        alpha_lease["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=50.0,
        required_anchor_count=1,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_ONLY",
        max_reduction_pct=25.0,
    )

    res = api.create_anchor_requirement(
        condition["id"],
        factories.anchor_requirement_payload(
            anchor_lease_id=beta_lease["id"],
            substitution_allowed=False,
            min_substitute_gla_sqft=0,
        ),
        make_lease_administrator_headers(),
    )

    assert res.status_code == 409
    validate_error(res, ERR_CENTER_SCOPE_MISMATCH)
    total, _rows = _total_count(
        api.list_anchor_requirements(
            make_lease_administrator_headers(), {"condition_id": condition["id"]}
        )
    )
    assert total == 0
    assert fetch_condition(api, condition["id"])["status"] == "SATISFIED"
    assert_pct(fetch_center(api, alpha["id"])["open_occupancy_pct"], 70.00)


# --------------------------------------------------------------------------
# Measurement-basis coherence
# --------------------------------------------------------------------------
def test_gla_condition_carrying_a_store_count_is_refused(api):
    """A GLA_PCT condition may not also carry required_open_store_count.

    PRD: "Exactly one threshold field is mandatory and the other must be omitted: a `GLA_PCT` condition requires `required_occupancy_pct` (greater than 0 and at most 100) and must not carry `required_open_store_count`; a `STORE_COUNT` condition requires `required_open_store_count` of at least 1 and must not carry `required_occupancy_pct`."

    Design: Corner/validations/gla_condition_carrying_a_store_count_returns_basis_mismatch
    """
    center_id, _tenants, leases = _build_northgate(api)

    res = api.create_condition(
        leases["I1"]["id"],
        factories.condition_payload(
            condition_kind="ONGOING",
            measurement_basis="GLA_PCT",
            required_occupancy_pct=81.67,
            required_open_store_count=3,
            required_anchor_count=2,
            grace_period_days=0,
            cure_period_days=30,
            remedy_type="RENT_REDUCTION_ONLY",
            max_reduction_pct=25.0,
        ),
        make_lease_administrator_headers(),
    )

    assert res.status_code == 422
    validate_error(res, ERR_MEASUREMENT_BASIS_MISMATCH)
    total, _rows = _total_count(
        api.list_conditions(
            make_lease_administrator_headers(), {"lease_id": leases["I1"]["id"]}
        )
    )
    assert total == 0
    assert_center_quantities(fetch_center(api, center_id), compliance_posture="COMPLIANT")


def test_store_count_condition_without_a_store_count_is_refused(api):
    """A STORE_COUNT condition that omits required_open_store_count is refused.

    PRD: "Measurement basis coherence — a `GLA_PCT` condition requires `required_occupancy_pct` and forbids `required_open_store_count`; a `STORE_COUNT` condition requires `required_open_store_count` with a value of at least 1 and forbids `required_occupancy_pct`."

    Design: Corner/validations/gla_condition_carrying_a_store_count_returns_basis_mismatch
    """
    center_id, _tenants, leases = _build_northgate(api)

    res = api.create_condition(
        leases["I1"]["id"],
        factories.condition_payload(
            condition_kind="ONGOING",
            measurement_basis="STORE_COUNT",
            required_occupancy_pct=None,
            required_anchor_count=2,
            grace_period_days=0,
            cure_period_days=30,
            remedy_type="RENT_REDUCTION_ONLY",
            max_reduction_pct=25.0,
        ),
        make_lease_administrator_headers(),
    )

    assert res.status_code == 422
    validate_error(res, ERR_MEASUREMENT_BASIS_MISMATCH)
    total, _rows = _total_count(
        api.list_conditions(
            make_lease_administrator_headers(), {"lease_id": leases["I1"]["id"]}
        )
    )
    assert total == 0
    assert_center_quantities(fetch_center(api, center_id), compliance_posture="COMPLIANT")


# --------------------------------------------------------------------------
# Condition kind against the premises lifecycle
# --------------------------------------------------------------------------
def test_opening_condition_on_an_open_lease_is_refused(api):
    """An OPENING condition may not be abstracted onto an already OPEN lease.

    PRD: "The two kinds attach at different points in the premises lifecycle, and abstracting one at the wrong point answers `ERR_CONDITION_KIND_INVALID`: an `OPENING` condition may not be added to a lease that is already `OPEN`, and an `ONGOING` condition may not be added to a lease still in `DRAFT`."

    Design: Corner/validations/opening_condition_on_an_open_lease_returns_condition_kind_invalid
    """
    _center_id, _tenants, leases = _build_northgate(api)

    res = api.create_condition(
        leases["I1"]["id"],
        factories.condition_payload(
            condition_kind="OPENING",
            measurement_basis="GLA_PCT",
            required_occupancy_pct=81.67,
            required_anchor_count=2,
            grace_period_days=0,
            cure_period_days=30,
            remedy_type="RENT_REDUCTION_ONLY",
            max_reduction_pct=25.0,
        ),
        make_lease_administrator_headers(),
    )

    assert res.status_code == 422
    validate_error(res, ERR_CONDITION_KIND_INVALID)
    assert_lease_dimensions(
        fetch_lease(api, leases["I1"]["id"]), premises_status="OPEN"
    )
    total, _rows = _total_count(
        api.list_conditions(
            make_lease_administrator_headers(), {"lease_id": leases["I1"]["id"]}
        )
    )
    assert total == 0


def test_ongoing_condition_on_a_draft_lease_is_refused(api):
    """An ONGOING condition may not be abstracted onto a lease still in DRAFT.

    PRD: "The two kinds attach at different points in the premises lifecycle, and abstracting one at the wrong point answers `ERR_CONDITION_KIND_INVALID`: an `OPENING` condition may not be added to a lease that is already `OPEN`, and an `ONGOING` condition may not be added to a lease still in `DRAFT`."

    Design: Corner/validations/opening_condition_on_an_open_lease_returns_condition_kind_invalid
    """
    center_id, _tenants, _leases = _build_northgate(api)
    optical = _add_optical_tenant(api)
    draft = draft_lease(
        api,
        center_id,
        optical["id"],
        suite_code="I8",
        gla_sqft=9000,
        parcel_kind="INLINE",
        primary_use_code="OPTICAL",
        base_rent_monthly_cents=500000,
        commencement_date="2026-10-01",
        expiration_date="2036-09-30",
    )

    res = api.create_condition(
        draft["id"],
        factories.condition_payload(
            condition_kind="ONGOING",
            measurement_basis="GLA_PCT",
            required_occupancy_pct=81.67,
            required_anchor_count=2,
            grace_period_days=0,
            cure_period_days=30,
            remedy_type="RENT_REDUCTION_ONLY",
            max_reduction_pct=25.0,
        ),
        make_lease_administrator_headers(),
    )

    assert res.status_code == 422
    validate_error(res, ERR_CONDITION_KIND_INVALID)
    assert_lease_dimensions(fetch_lease(api, draft["id"]), premises_status="DRAFT")
    total, _rows = _total_count(
        api.list_conditions(
            make_lease_administrator_headers(), {"lease_id": draft["id"]}
        )
    )
    assert total == 0


# --------------------------------------------------------------------------
# Clause enforceability
# --------------------------------------------------------------------------
def _northgate_with_suspended_clause(api):
    """Two clauses on suite I1, one of them suspended by a recorded plan."""
    center_id, tenants, leases = _build_northgate(api)
    coffee_clause = add_clause(
        api,
        leases["I1"]["id"],
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    smoothie_clause = add_clause(
        api,
        leases["I1"]["id"],
        protected_use_codes=["SMOOTHIES"],
        exclusivity_scope="PAD_EXCLUDED",
        gla_carve_out_sqft=500,
        incidental_sales_pct_cap=5.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    plan = plan_redevelopment(
        api, center_id, plan_kind="REDEMISE", removed_gla_sqft=45000
    )
    record_plan(api, plan["id"], consent_confirmed=True)
    return center_id, tenants, leases, coffee_clause, smoothie_clause, plan


def test_notice_citing_a_suspended_clause_is_refused(api):
    """A notice may not cite a clause suspended by a recorded redevelopment plan.

    PRD: "A cited clause whose `status` is anything other than `ACTIVE` — including a clause suspended by a recorded redevelopment plan — answers `ERR_CLAUSE_NOT_ACTIVE`."

    Design: Corner/validations/notice_citing_a_suspended_clause_returns_clause_not_active
    """
    (
        center_id,
        _tenants,
        leases,
        coffee_clause,
        smoothie_clause,
        plan,
    ) = _northgate_with_suspended_clause(api)

    res = api.create_notice(
        factories.notice_payload(
            violating_lease_id=leases["I3"]["id"],
            clause_id=coffee_clause["id"],
            notice_kind="EXCLUSIVE_USE",
            narrative="Espresso bar in the fitness premises.",
            cure_period_days=30,
        ),
        make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
    )

    assert res.status_code == 422
    validate_error(res, ERR_CLAUSE_NOT_ACTIVE)
    suspended = fetch_clause(api, coffee_clause["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspended_by_plan_id"] == plan["id"]
    assert fetch_clause(api, smoothie_clause["id"])["status"] == "ACTIVE"
    assert_center_quantities(
        fetch_center(api, center_id),
        total_gla_sqft=255000,
        protected_exclusive_count=1,
    )


def test_notice_citing_a_clause_the_plan_left_active_is_issued(api):
    """A clause the recorded plan did not suspend is still enforceable.

    PRD: "Clause enforceability — a notice may only cite an exclusive-use clause whose `status` is `ACTIVE`; a clause suspended by a recorded redevelopment plan cannot be enforced."

    Design: Corner/validations/notice_citing_a_suspended_clause_returns_clause_not_active
    """
    (
        _center_id,
        _tenants,
        leases,
        _coffee_clause,
        smoothie_clause,
        _plan,
    ) = _northgate_with_suspended_clause(api)

    notice = issue_notice(
        api,
        leases["I3"]["id"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=smoothie_clause["id"],
        narrative="Smoothie bar in the fitness premises.",
        cure_period_days=30,
    )

    assert notice["status"] == "ISSUED"
    assert notice["clause_id"] == smoothie_clause["id"]


# --------------------------------------------------------------------------
# Radius enforcement window
# --------------------------------------------------------------------------
def _northgate_with_radius_restrictions(api):
    center_id, tenants, leases = _build_northgate(api)
    late = add_radius_restriction(
        api,
        leases["I3"]["id"],
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="GROSS_SALES",
        recapture_pct=8.0,
        protected_baseline_cents=0,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
    )
    edge = add_radius_restriction(
        api,
        leases["I2"]["id"],
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="GROSS_SALES",
        recapture_pct=8.0,
        protected_baseline_cents=0,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
    )
    return center_id, tenants, leases, late, edge


def test_radius_report_after_the_window_closes_is_refused(api):
    """A radius report dated after the enforcement window closes is refused.

    PRD: "The restriction must be `ACTIVE` and its closed enforcement window must contain the current logical clock date, or the report answers `ERR_RADIUS_WINDOW_INACTIVE`."

    Design: Corner/validations/radius_report_outside_the_enforcement_window_returns_window_inactive
    """
    center_id, _tenants, _leases, late, edge = _northgate_with_radius_restrictions(api)
    set_clock(api, "2026-12-31T00:00:00Z")
    report_radius_violation(
        api,
        edge["id"],
        reported_offending_sales_cents=1000000,
        narrative="Satellite bookstore sales reported on the final window day.",
        cure_period_days=30,
    )
    set_clock(api, "2027-01-02T00:00:00Z")

    res = api.report_radius_violation(
        late["id"],
        factories.radius_violation_report_payload(
            reported_offending_sales_cents=1000000,
            narrative="Satellite studio sales reported after the window closed.",
            cure_period_days=30,
        ),
        make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
    )

    assert res.status_code == 409
    validate_error(res, ERR_RADIUS_WINDOW_INACTIVE)
    total, _rows = _total_count(
        api.list_notices(
            make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
            {"radius_restriction_id": late["id"]},
        )
    )
    assert total == 0
    assert_center_quantities(fetch_center(api, center_id), open_violation_count=1)


def test_radius_report_on_the_final_window_day_is_accepted(api):
    """The enforcement window is closed at both ends, so its last day still reports.

    PRD: "The restriction must be `ACTIVE` and its closed enforcement window must contain the current logical clock date, or the report answers `ERR_RADIUS_WINDOW_INACTIVE`."

    Design: Corner/validations/radius_report_outside_the_enforcement_window_returns_window_inactive
    """
    center_id, _tenants, _leases, _late, edge = _northgate_with_radius_restrictions(api)
    set_clock(api, "2026-12-31T00:00:00Z")

    notice = report_radius_violation(
        api,
        edge["id"],
        reported_offending_sales_cents=1000000,
        narrative="Satellite bookstore sales reported on the final window day.",
        cure_period_days=30,
    )

    assert notice["status"] == "ISSUED"
    assert_cents(notice["recapture_assessed_cents"], 80000, "recapture_assessed_cents")
    _assert_instant(notice["issued_at"], "2026-12-31T00:00:00", "issued_at")
    _assert_instant(notice["cure_deadline_at"], "2027-01-30T00:00:00", "cure_deadline_at")
    assert_center_quantities(fetch_center(api, center_id), open_violation_count=1)


# --------------------------------------------------------------------------
# Cure-period timing
# --------------------------------------------------------------------------
def test_escalating_before_the_cure_deadline_is_refused(api):
    """A notice cannot be escalated while its cure deadline is still in the future.

    PRD: "Attempting it before the cure deadline has passed answers `ERR_CURE_PERIOD_NOT_EXPIRED`."

    Design: Corner/validations/escalating_before_the_cure_deadline_returns_cure_period_not_expired
    """
    _center_id, _tenants, leases = _build_northgate(api)
    clause = add_clause(
        api,
        leases["I1"]["id"],
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    notice = issue_notice(
        api,
        leases["I3"]["id"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
    )
    set_clock(api, "2026-08-30T00:00:00Z")

    res = api.escalate_notice(
        notice["id"],
        None,
        make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
    )

    assert res.status_code == 409
    validate_error(res, ERR_CURE_PERIOD_NOT_EXPIRED)
    unchanged = fetch_notice(api, notice["id"])
    assert unchanged["status"] == "ISSUED"
    assert_null(unchanged["escalated_at"], "escalated_at")
    _assert_instant(unchanged["cure_deadline_at"], "2026-08-31T00:00:00", "cure_deadline_at")
    assert_lease_dimensions(
        fetch_lease(api, leases["I3"]["id"]), use_compliance_status="UNDER_NOTICE"
    )
    assert_lease_dimensions(fetch_lease(api, leases["I1"]["id"]), remedy_status="NONE")


def _northgate_with_breached_condition(api, cure_period_days, remedy_type):
    """A breached ONGOING condition on suite I1 after the fitness suite goes dark."""
    center_id, tenants, leases = _build_northgate(api)
    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=cure_period_days,
        remedy_type=remedy_type,
        max_reduction_pct=25.0,
    )
    go_dark(api, leases["I3"]["id"])
    return center_id, tenants, leases, condition


def test_termination_approval_before_the_condition_cure_period_is_refused(api):
    """A termination effective before the cure window elapses cannot be approved.

    PRD: "A scheduled termination whose effective date falls earlier than `breach_detected_at` plus `cure_period_days` is refused with `ERR_CURE_PERIOD_NOT_EXPIRED`."

    Design: Corner/validations/termination_approval_before_the_condition_cure_period_is_rejected
    """
    _center_id, tenants, leases, condition = _northgate_with_breached_condition(
        api, cure_period_days=120, remedy_type="TERMINATION_ONLY"
    )
    version = _lease_version_as_tenant(
        api, leases["I1"]["id"], tenants["I1"]["id"]
    )
    election = elect_remedy(
        api,
        leases["I1"]["id"],
        tenants["I1"]["id"],
        election_kind="TERMINATION",
        window_from_date="2026-08-01",
        window_through_date="2027-08-01",
        condition_id=condition["id"],
        expected_lease_version=version,
    )

    res = api.approve_election(election["id"], None, make_asset_manager_headers())

    assert res.status_code == 409
    validate_error(res, ERR_CURE_PERIOD_NOT_EXPIRED)
    unchanged = fetch_election(api, election["id"])
    assert unchanged["status"] == "ELECTED"
    assert unchanged["election_kind"] == "TERMINATION"
    still_breached = fetch_condition(api, condition["id"])
    assert still_breached["consecutive_breach_days"] == 0
    assert still_breached["cure_period_days"] == 120
    assert_lease_dimensions(
        fetch_lease(api, leases["I1"]["id"]),
        premises_status="OPEN",
        remedy_status="ELIGIBLE",
    )


# --------------------------------------------------------------------------
# Remedy kind and abatement window
# --------------------------------------------------------------------------
def test_rent_reduction_under_a_termination_only_condition_is_refused(api):
    """A TERMINATION_ONLY condition does not permit a rent-reduction election.

    PRD: "The condition's `remedy_type` constrains which kinds are permitted, and a mismatch answers `ERR_REMEDY_KIND_NOT_PERMITTED`: `RENT_REDUCTION_ONLY` permits only `RENT_REDUCTION`; `TERMINATION_ONLY` permits only `TERMINATION`; `RENT_REDUCTION_THEN_TERMINATION` permits both `RENT_REDUCTION` and `TERMINATION`; and `SUBSTITUTE_RENT` is permitted only for an election sourced from an escalated notice."

    Design: Corner/validations/rent_reduction_election_under_termination_only_remedy_is_rejected
    """
    _center_id, tenants, leases, condition = _northgate_with_breached_condition(
        api, cure_period_days=30, remedy_type="TERMINATION_ONLY"
    )
    version = _lease_version_as_tenant(api, leases["I1"]["id"], tenants["I1"]["id"])

    res = api.create_election(
        leases["I1"]["id"],
        factories.election_payload(
            election_kind="RENT_REDUCTION",
            condition_id=condition["id"],
            window_from_date="2026-08-01",
            window_through_date="2026-11-01",
            expected_lease_version=version,
        ),
        make_tenant_rep_headers(tenants["I1"]["id"]),
    )

    assert res.status_code == 422
    validate_error(res, ERR_REMEDY_KIND_NOT_PERMITTED)
    assert_lease_dimensions(
        fetch_lease(api, leases["I1"]["id"]),
        remedy_status="ELIGIBLE",
        effective_rent_monthly_cents=1000000,
    )
    total, _rows = _total_count(
        api.list_elections(
            make_lease_administrator_headers(), {"lease_id": leases["I1"]["id"]}
        )
    )
    assert total == 0
    assert fetch_condition(api, condition["id"])["status"] == "BREACHED"


def test_abatement_window_starting_after_it_ends_is_refused(api):
    """A rent-reduction window whose start follows its end is refused.

    PRD: "Its window must satisfy `window_from_date` strictly before `window_through_date`, and `window_from_date` must not precede the date of the condition's `breach_detected_at`; either failure answers `ERR_ABATEMENT_WINDOW_INVALID`."

    Design: Corner/validations/abatement_window_with_from_after_through_returns_window_invalid
    """
    _center_id, tenants, leases, condition = _northgate_with_breached_condition(
        api, cure_period_days=30, remedy_type="RENT_REDUCTION_THEN_TERMINATION"
    )
    version = _lease_version_as_tenant(api, leases["I1"]["id"], tenants["I1"]["id"])

    res = api.create_election(
        leases["I1"]["id"],
        factories.election_payload(
            election_kind="RENT_REDUCTION",
            condition_id=condition["id"],
            window_from_date="2026-11-01",
            window_through_date="2026-09-01",
            expected_lease_version=version,
        ),
        make_tenant_rep_headers(tenants["I1"]["id"]),
    )

    assert res.status_code == 422
    validate_error(res, ERR_ABATEMENT_WINDOW_INVALID)
    total, _rows = _total_count(
        api.list_elections(
            make_lease_administrator_headers(), {"lease_id": leases["I1"]["id"]}
        )
    )
    assert total == 0
    assert_lease_dimensions(
        fetch_lease(api, leases["I1"]["id"]),
        remedy_status="ELIGIBLE",
        effective_rent_monthly_cents=1000000,
    )


# --------------------------------------------------------------------------
# Protected-rights consent on recording
# --------------------------------------------------------------------------
def _northgate_with_consent_plan(api):
    """A REDEMISE plan over a center carrying two center-wide clauses."""
    center_id, tenants, leases = _build_northgate(api)
    for suite, use_code in (("I1", "COFFEE"), ("I2", "BOOKS")):
        add_clause(
            api,
            leases[suite]["id"],
            protected_use_codes=[use_code],
            exclusivity_scope="CENTER_WIDE",
            gla_carve_out_sqft=0,
            incidental_sales_pct_cap=0.0,
            effective_from_date="2026-01-01",
            effective_through_date="2036-12-31",
        )
    plan = plan_redevelopment(
        api, center_id, plan_kind="REDEMISE", removed_gla_sqft=45000
    )
    return center_id, tenants, leases, plan


def test_recording_a_consent_required_plan_without_consent_is_refused(api):
    """A plan that impacts protected rights cannot be recorded without consent.

    PRD: "It is refused while the center is `FROZEN`, and a plan whose `consent_required` is true may only be recorded with `consent_confirmed` true in the body — omitting it answers `ERR_PROTECTED_RIGHTS_CONSENT_REQUIRED`."

    Design: Corner/validations/recording_a_consent_required_plan_without_consent_is_rejected
    """
    center_id, _tenants, _leases, plan = _northgate_with_consent_plan(api)
    assert plan["consent_required"] is True
    assert plan["impacted_clause_count"] == 2
    assert plan["gla_after_sqft"] == 255000

    res = api.record_plan(
        plan["id"],
        factories.record_plan_payload(consent_confirmed=False),
        make_asset_manager_headers(),
    )

    assert res.status_code == 409
    validate_error(res, ERR_PROTECTED_RIGHTS_CONSENT_REQUIRED)
    unchanged = fetch_plan(api, plan["id"])
    assert unchanged["status"] == "CONSENT_PENDING"
    assert_null(unchanged["recorded_at"], "recorded_at")
    assert_center_quantities(fetch_center(api, center_id), total_gla_sqft=300000)


def test_recording_a_consent_confirmed_plan_shrinks_the_denominator(api):
    """Recording with consent removes GLA, leaves occupied GLA and lifts occupancy.

    PRD: "On success the plan becomes `RECORDED` with `recorded_at` stamped, and the center's `total_gla_sqft` is reduced by `removed_gla_sqft` while `occupied_gla_sqft` is left exactly where it was — so `open_occupancy_pct` is recomputed against a **smaller denominator**, which can cure a `GLA_PCT` condition without a single tenant opening a door."

    Design: Corner/validations/recording_a_consent_required_plan_without_consent_is_rejected
    """
    center_id, _tenants, _leases, plan = _northgate_with_consent_plan(api)
    refused = api.record_plan(
        plan["id"],
        factories.record_plan_payload(consent_confirmed=False),
        make_asset_manager_headers(),
    )
    validate_error(refused, ERR_PROTECTED_RIGHTS_CONSENT_REQUIRED)

    recorded = record_plan(api, plan["id"], consent_confirmed=True)

    assert recorded["status"] == "RECORDED"
    assert recorded["gla_after_sqft"] == 255000
    _assert_instant(recorded["recorded_at"], "2026-08-01T00:00:00", "recorded_at")
    assert_center_quantities(
        fetch_center(api, center_id),
        total_gla_sqft=255000,
        occupied_gla_sqft=255000,
        open_occupancy_pct=100.00,
        protected_exclusive_count=0,
        redevelopment_status="RECORDED",
    )


# --------------------------------------------------------------------------
# Estoppel lender conditions
# --------------------------------------------------------------------------
def test_accepting_a_signed_certificate_on_a_noticed_lease_is_refused(api):
    """A signed certificate whose lease drifted to UNDER_NOTICE cannot be accepted.

    PRD: "Accepting while `lender_conditions_met` is false answers `ERR_LENDER_CONDITIONS_NOT_MET` — typically a signed certificate whose lease has drifted to `UNDER_NOTICE` or `IN_VIOLATION`, or whose lease has a breached condition the certificate never disclosed."

    Design: Corner/validations/accepting_a_signed_certificate_on_a_noticed_lease_is_rejected
    """
    _center_id, tenants, leases = _build_northgate(api)
    clause = add_clause(
        api,
        leases["I1"]["id"],
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    issue_notice(
        api,
        leases["I3"]["id"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
    )
    certificate = request_certificate(
        api, leases["I3"]["id"], expedite_requested=False
    )
    sign_certificate(api, certificate["id"], tenants["I3"]["id"])

    res = api.accept_certificate(certificate["id"], None, make_lender_rep_headers())

    assert res.status_code == 422
    validate_error(res, ERR_LENDER_CONDITIONS_NOT_MET)
    unchanged = fetch_certificate(api, certificate["id"])
    assert unchanged["status"] == "TENANT_SIGNED"
    assert unchanged["lender_conditions_met"] is False
    assert unchanged["disclosed_cotenancy_breach"] is False
    assert_cents(unchanged["base_fee_cents"], 25000, "base_fee_cents")
    assert_cents(unchanged["total_fee_cents"], 25000, "total_fee_cents")
    assert_null(unchanged["accepted_at"], "accepted_at")
    assert_lease_dimensions(
        fetch_lease(api, leases["I3"]["id"]), use_compliance_status="UNDER_NOTICE"
    )


# --------------------------------------------------------------------------
# Condition creation that satisfies every rule
# --------------------------------------------------------------------------
def test_satisfied_condition_creation_is_evaluated_immediately(api):
    """A condition met by live occupancy is created SATISFIED with no breach stamp.

    PRD: "A condition is **evaluated immediately at creation** under the live strict engine, so its `status` is either `SATISFIED` or `BREACHED` the instant it exists — there is no pending or unevaluated state."

    Design: Corner/validations/satisfied_condition_creation_passes_every_rule
    """
    center_id, _tenants, leases = _build_northgate(api)

    res = api.create_condition(
        leases["I1"]["id"],
        factories.condition_payload(
            condition_kind="ONGOING",
            measurement_basis="GLA_PCT",
            required_occupancy_pct=81.67,
            required_anchor_count=2,
            grace_period_days=0,
            cure_period_days=30,
            remedy_type="RENT_REDUCTION_THEN_TERMINATION",
            max_reduction_pct=25.0,
        ),
        make_lease_administrator_headers(),
    )

    condition = get_success_data(res, 201)
    assert condition["status"] == "SATISFIED"
    assert_null(condition["breach_detected_at"], "breach_detected_at")
    assert_lease_dimensions(fetch_lease(api, leases["I1"]["id"]), remedy_status="NONE")
    assert_center_quantities(
        fetch_center(api, center_id),
        open_occupancy_pct=85.00,
        compliance_posture="COMPLIANT",
    )


# --------------------------------------------------------------------------
# Condition defaults
# --------------------------------------------------------------------------
def test_condition_defaults_applied_when_optional_thresholds_omitted(api):
    """Omitted optional condition inputs take their declared defaults.

    PRD: "`grace_period_days` defaults to 30 and is the number of days a breach must persist before the benefited lease becomes remedy-eligible — a value of 0 makes eligibility immediate at breach detection."

    Design: Corner/validations/condition_defaults_applied_when_optional_thresholds_omitted
    """
    _center_id, _tenants, leases = _build_northgate(api)

    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
    )

    assert condition["required_anchor_count"] == 0
    assert condition["grace_period_days"] == 30
    assert condition["cure_period_days"] == 120
    assert_pct(condition["max_reduction_pct"], 50, "max_reduction_pct")


def test_breach_under_a_non_zero_grace_window_does_not_make_the_lease_eligible(api):
    """A breach under the default grace window breaches without granting eligibility.

    PRD: "Hop 4, caused by hop 3 because a condition flipped, moves the benefited lease of each newly breached condition from `remedy_status` `NONE` to `ELIGIBLE` with `remedy_eligible_at` stamped — but only when that condition's `grace_period_days` is 0; a condition with a non-zero grace window waits for the sweep — and bumps that benefited lease's `version`, while the center's posture is re-derived to `BREACH` or `FROZEN`."

    Design: Corner/validations/condition_defaults_applied_when_optional_thresholds_omitted
    """
    center_id, _tenants, leases = _build_northgate(api)
    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
    )

    go_dark(api, leases["I3"]["id"])

    breached = fetch_condition(api, condition["id"])
    assert breached["status"] == "BREACHED"
    assert breached["consecutive_breach_days"] == 0
    benefited = fetch_lease(api, leases["I1"]["id"])
    assert_lease_dimensions(benefited, remedy_status="NONE")
    assert_null(benefited["remedy_eligible_at"], "remedy_eligible_at")
    assert_center_quantities(fetch_center(api, center_id), compliance_posture="BREACH")
