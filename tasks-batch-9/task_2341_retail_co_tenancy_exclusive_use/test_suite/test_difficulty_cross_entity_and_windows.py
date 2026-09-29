"""Cross-entity state dependencies and the three temporal-window conventions.

Covers the certified-measurement engine overruling the live strict engine on a
co-tenancy condition, estoppel acceptance gated on the estopped lease's version,
a parent notice gated by its child dispute, closed-closed radius enforcement
windows, half-open measurement windows, and the aggregate abatement cap over
overlapping abatement windows.
"""
from test_helpers import (
    ASSET_MANAGER_USER_ID,
    COMPLIANCE_ENFORCER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    COMPLIANCE_REVIEWER_USER_ID,
    DEFAULT_CLOCK_UTC,
    ERR_ABATEMENT_STACK_EXCEEDED,
    ERR_CERTIFICATE_STALE,
    ERR_DISPUTE_PENDING,
    ERR_MEASUREMENT_WINDOW_OVERLAP,
    ERR_NOTICE_STATE_INVALID,
    ERR_RADIUS_WINDOW_OVERLAP,
    LEASE_ADMIN_USER_ID,
    LENDER_REP_USER_ID,
    accept_certificate,
    add_anchor_requirement,
    add_clause,
    add_condition,
    add_radius_restriction,
    approve_election,
    assert_cents,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_null,
    assert_pct,
    build_center_with_leases,
    certify_measurement,
    elect_remedy,
    factories,
    fetch_center,
    fetch_certificate,
    fetch_condition,
    fetch_dispute,
    fetch_election,
    fetch_lease,
    fetch_measurement,
    fetch_notice,
    fetch_restriction,
    file_dispute,
    go_dark,
    issue_notice,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lease_administrator_headers,
    make_lender_rep_headers,
    prepare_measurement,
    request_certificate,
    sign_certificate,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# Shared scenario: a 300,000 sqft center whose five suites are all OPEN.
# Two anchor boxes (A1 120,000 and A2 100,000) plus three inline suites
# (I1 2,000, I2 3,000 and I3 30,000) put 255,000 sqft of the 300,000 sqft
# denominator to work, so the live strict occupancy is 85.00 (PRD §2.5).
# --------------------------------------------------------------------------
FIVE_SUITE_SPECS = [
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
]


def _five_suite_center(api):
    """Pin the clock at 2026-08-01 and stand the leased-up center up."""
    return build_center_with_leases(
        api,
        FIVE_SUITE_SPECS,
        total_gla_sqft=300000,
        occupancy_grace_days=30,
        center_name="Northgate Crossing",
        clock=DEFAULT_CLOCK_UTC,
    )


def _condition_on_i1(api, lease_id, max_reduction_pct=25.0):
    """An ONGOING GLA_PCT condition requiring 81.67 pct and two open anchors."""
    return add_condition(
        api,
        lease_id,
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=max_reduction_pct,
    )


# --------------------------------------------------------------------------
# A certified TRAILING_GRACE measurement cures what the live engine breached
# --------------------------------------------------------------------------
def _setup_trailing_grace_cure(api):
    """Breach the condition live, then prepare a trailing-grace measurement.

    Suite I3 goes dark on the clock date, so the live strict engine drops its
    30,000 sqft and reports 75.00 pct against the 81.67 pct requirement.  The
    draft measurement re-admits the freshly dark suite under the trailing-grace
    variant (PRD §2.5).
    """
    scenario = _five_suite_center(api)
    condition = _condition_on_i1(api, scenario.lease_id("I1"))
    go_dark(api, scenario.lease_id("I3"))
    measurement = prepare_measurement(
        api,
        scenario.center_id,
        variant="TRAILING_GRACE",
        window_from_date="2026-08-01",
        window_through_date="2026-09-01",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )
    return scenario, condition, measurement


def test_certifying_trailing_grace_measurement_cures_the_live_breached_condition(api):
    """Certification re-evaluates the condition on the certified figures and pins the row.

    PRD: "On success the `status` moves `DRAFT → CERTIFIED`, `certified_by_user_id` and `certified_at` are stamped, and every non-waived co-tenancy condition of the center is re-evaluated with the certified-measurement source using **this row's variant figures**, each evaluated condition having its `last_evaluated_measurement_id` pinned to this row."

    Design: Difficulty/cross_entity_state_dependency/certified_trailing_grace_measurement_cures_condition_live_engine_breached
    """
    scenario, condition, measurement = _setup_trailing_grace_cure(api)
    assert fetch_condition(api, condition["id"])["status"] == "BREACHED"

    certified = certify_measurement(
        api, measurement["id"], COMPLIANCE_REVIEWER_USER_ID
    )

    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == COMPLIANCE_REVIEWER_USER_ID
    assert certified["certified_at"] == "2026-08-01T00:00:00.000Z"

    cured = fetch_condition(api, condition["id"])
    assert cured["status"] == "CURED"
    assert_null(cured["breach_detected_at"], "breach_detected_at")
    assert cured["last_evaluated_measurement_id"] == measurement["id"]


def test_trailing_grace_measurement_readmits_the_freshly_dark_suite(api):
    """The trailing-grace figure counts the suite that went dark today at 85.00 pct.

    PRD: "Under the **`TRAILING_GRACE`** variant, a lease whose tenant's `status` is `BANKRUPT` never counts; a lease whose `premises_status` is `OPEN` always counts, whether its tenant is `ACTIVE` or `DEFAULTED`; and a lease whose `premises_status` is `DARK` with a non-null `dark_since` still counts provided the number of whole days from `dark_since` to the measurement instant is strictly less than the center's `occupancy_grace_days`."

    Design: Difficulty/cross_entity_state_dependency/certified_trailing_grace_measurement_cures_condition_live_engine_breached
    """
    _scenario, _condition, measurement = _setup_trailing_grace_cure(api)

    certified = certify_measurement(
        api, measurement["id"], COMPLIANCE_REVIEWER_USER_ID
    )

    # Zero whole days from dark_since to measured_at is strictly below the
    # center's 30-day grace window, so all 255,000 sqft still count.
    assert_pct(certified["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")


def test_certified_cure_releases_the_benefited_lease_and_re_derives_posture(api):
    """The cured condition drops the breach count to zero and unwinds eligibility.

    PRD: "`breached_condition_count` is then set to the number of conditions of the center left `BREACHED` after that evaluation, benefited leases move their `remedy_status` according to the condition transitions of §3.3, and posture is re-derived."

    Design: Difficulty/cross_entity_state_dependency/certified_trailing_grace_measurement_cures_condition_live_engine_breached
    """
    scenario, _condition, measurement = _setup_trailing_grace_cure(api)
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")), remedy_status="ELIGIBLE"
    )

    certified = certify_measurement(
        api, measurement["id"], COMPLIANCE_REVIEWER_USER_ID
    )

    assert certified["breached_condition_count"] == 0
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")),
        premises_status="OPEN",
        remedy_status="NONE",
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id), compliance_posture="COMPLIANT"
    )


def test_certification_leaves_the_centers_own_live_strict_figures_alone(api):
    """The center keeps reporting 75.00 pct while the certified figure reads 85.00.

    PRD: "The **live strict engine** recomputes the center's own derived fields — `occupied_gla_sqft`, `open_occupancy_pct`, `operating_store_count`, `open_anchor_count`, `aggregate_effective_rent_cents`, `protected_exclusive_count`, and `open_violation_count` — always under the `SNAPSHOT_STRICT` variant and always at the current logical clock."

    Design: Difficulty/cross_entity_state_dependency/certified_trailing_grace_measurement_cures_condition_live_engine_breached
    """
    scenario, _condition, measurement = _setup_trailing_grace_cure(api)

    certify_measurement(api, measurement["id"], COMPLIANCE_REVIEWER_USER_ID)

    # The dark suite drops out of the strict numerator: 225,000 of 300,000.
    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        occupied_gla_sqft=225000,
        open_occupancy_pct=75.00,
    )


# --------------------------------------------------------------------------
# Estoppel acceptance turns on the estopped lease's version, not the row
# --------------------------------------------------------------------------
def _setup_two_signed_certificates(api):
    """Sign one certificate before the breach cascade and one after it.

    ``cert_old`` is requested and signed while occupancy is still 85.00 pct, so
    it discloses no breach.  Suite I3 then goes dark, which breaches the
    condition, lifts lease I1 to ``ELIGIBLE`` and bumps its version, driving
    ``cert_old`` to ``STALE`` (PRD §3.3).  ``cert_new`` is requested afterwards
    and therefore discloses the breach.
    """
    scenario = _five_suite_center(api)
    condition = _condition_on_i1(api, scenario.lease_id("I1"))
    cert_old = request_certificate(
        api,
        scenario.lease_id("I1"),
        expedite_requested=False,
        user_id=LENDER_REP_USER_ID,
    )
    sign_certificate(api, cert_old["id"], scenario.tenant_id("I1"))
    go_dark(api, scenario.lease_id("I3"))
    cert_new = request_certificate(
        api,
        scenario.lease_id("I1"),
        expedite_requested=False,
        user_id=LENDER_REP_USER_ID,
    )
    sign_certificate(api, cert_new["id"], scenario.tenant_id("I1"))
    return scenario, condition, cert_old, cert_new


def test_certificate_that_discloses_the_breach_is_accepted_by_the_lender(api):
    """A disclosed co-tenancy breach does not block acceptance of the signed row.

    PRD: "That last clause is the point of the whole instrument: a breach does **not** block acceptance once the certificate discloses it — only an **undisclosed** breach does."

    Design: Difficulty/cross_entity_state_dependency/estoppel_acceptance_gated_on_pinned_lease_version_of_another_entity
    """
    _scenario, _condition, _cert_old, cert_new = _setup_two_signed_certificates(api)

    accepted = accept_certificate(api, cert_new["id"], LENDER_REP_USER_ID)

    assert accepted["status"] == "LENDER_ACCEPTED"
    assert accepted["lender_conditions_met"] is True
    assert accepted["disclosed_cotenancy_breach"] is True


def test_certificate_requested_after_the_breach_carries_the_breach_disclosure_fee(api):
    """Disclosing the breach adds 15,000 cents to the 25,000 cent base subtotal.

    PRD: "First, the pre-surcharge subtotal is 25,000 cents of base fee, plus 5,000 cents for each disclosed exclusive-use clause, plus a further 15,000 cents when `disclosed_cotenancy_breach` is true."

    Design: Difficulty/cross_entity_state_dependency/estoppel_acceptance_gated_on_pinned_lease_version_of_another_entity
    """
    _scenario, _condition, _cert_old, cert_new = _setup_two_signed_certificates(api)

    row = fetch_certificate(api, cert_new["id"])

    assert row["disclosed_cotenancy_breach"] is True
    assert row["disclosed_exclusive_count"] == 0
    assert_cents(row["base_fee_cents"], 40000, "base_fee_cents")
    # Nothing was expedited, so the surcharge is zero and the total is the subtotal.
    assert_cents(row["total_fee_cents"], 40000, "total_fee_cents")


def test_stale_certificate_pinned_to_the_superseded_lease_version_cannot_be_accepted(api):
    """The certificate signed before the cascade is refused and mutates nothing.

    PRD: "Nor can it be accepted; accepting a stale row is likewise refused with `ERR_CERTIFICATE_STALE` and mutates nothing, and only an explicit rejection moves a stale row onward."

    Design: Difficulty/cross_entity_state_dependency/estoppel_acceptance_gated_on_pinned_lease_version_of_another_entity
    """
    _scenario, _condition, cert_old, _cert_new = _setup_two_signed_certificates(api)

    response = api.accept_certificate(
        cert_old["id"], None, make_lender_rep_headers(LENDER_REP_USER_ID)
    )
    validate_error(response, ERR_CERTIFICATE_STALE, 409)

    row = fetch_certificate(api, cert_old["id"])
    assert row["status"] == "STALE"
    assert row["lender_conditions_met"] is False
    assert row["disclosed_cotenancy_breach"] is False
    assert_cents(row["base_fee_cents"], 25000, "base_fee_cents")


# --------------------------------------------------------------------------
# A pending dispute on the child blocks the cure of the parent notice
# --------------------------------------------------------------------------
def _setup_disputed_notice(api):
    """Notice suite I3 for the COFFEE exclusive of suite I1, then have it disputed."""
    scenario = _five_suite_center(api)
    clause = add_clause(
        api,
        scenario.lease_id("I1"),
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar operating inside the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute = file_dispute(
        api,
        notice["id"],
        scenario.tenant_id("I3"),
        grounds_code="NO_PROHIBITED_USE",
        narrative="No espresso is sold; the machine serves staff only.",
        cure_extension_days=0,
    )
    return scenario, clause, notice, dispute


def test_curing_a_disputed_notice_answers_the_specific_pending_dispute_error(api):
    """The child dispute, not the notice's own from-state, names the refusal.

    PRD: "Curing a notice that is `CURED` or `WITHDRAWN` answers `ERR_NOTICE_STATE_INVALID`, while curing one that is `DISPUTED` answers the more specific `ERR_DISPUTE_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/notice_cure_blocked_by_pending_dispute_on_child_entity
    """
    _scenario, _clause, notice, _dispute = _setup_disputed_notice(api)

    response = api.cure_notice(
        notice["id"],
        factories.cure_payload("USE_DISCONTINUED"),
        make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
    )

    body = validate_error(response, ERR_DISPUTE_PENDING, 409)
    assert body["error_id"] != ERR_NOTICE_STATE_INVALID


def test_refused_cure_leaves_the_notice_its_dispute_and_the_center_untouched(api):
    """The suspended cure clock stays frozen where the dispute left it.

    PRD: "The dispute is created `PENDING` with `filed_by_tenant_id` copied from `X-User-ID`, `adjudicated_by_user_id` null, and `adjudicated_at` null; the parent notice moves `ISSUED → DISPUTED`, its `use_compliance_status` contribution becomes `UNDER_NOTICE`, and its cure clock is suspended — `cure_deadline_at` is frozen where it stands, so escalation is blocked until adjudication."

    Design: Difficulty/cross_entity_state_dependency/notice_cure_blocked_by_pending_dispute_on_child_entity
    """
    scenario, _clause, notice, dispute = _setup_disputed_notice(api)

    api.cure_notice(
        notice["id"],
        factories.cure_payload("USE_DISCONTINUED"),
        make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
    )

    after = fetch_notice(api, notice["id"])
    assert after["status"] == "DISPUTED"
    assert after["cure_restart_count"] == 0
    # Issued at 2026-08-01 with a 30-day cure period, and frozen there.
    assert after["cure_deadline_at"] == "2026-08-31T00:00:00.000Z"
    assert fetch_dispute(api, dispute["id"])["status"] == "PENDING"
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I3")), use_compliance_status="UNDER_NOTICE"
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id), open_violation_count=1
    )


# --------------------------------------------------------------------------
# Radius enforcement windows are closed-closed
# --------------------------------------------------------------------------
def _setup_radius_restriction(api):
    """One ACTIVE restriction on suite I3 over the closed 2026 calendar year."""
    scenario = _five_suite_center(api)
    restriction = add_radius_restriction(
        api,
        scenario.lease_id("I3"),
        radius_miles=3.0,
        measured_from="CENTER_BOUNDARY",
        recapture_basis="GROSS_SALES",
        recapture_pct=8.0,
        protected_baseline_cents=0,
        window_from_date="2026-01-01",
        window_through_date="2026-12-31",
    )
    return scenario, restriction


def test_radius_window_starting_on_the_prior_through_date_collides(api):
    """A second window whose from-date is the first window's through-date is refused.

    PRD: "Windows for one lease are closed-closed and may not share even a single day: two restrictions collide when the first's from-date is on or before the second's through-date and the second's from-date is on or before the first's through-date, so **touching endpoints do collide**, and the collision answers `ERR_RADIUS_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_touching_endpoint_collides
    """
    scenario, restriction = _setup_radius_restriction(api)

    response = api.create_radius_restriction(
        scenario.lease_id("I3"),
        factories.radius_restriction_payload(
            radius_miles=5.0,
            measured_from="PREMISES_CENTROID",
            recapture_basis="GROSS_SALES",
            recapture_pct=6.0,
            protected_baseline_cents=0,
            window_from_date="2026-12-31",
            window_through_date="2027-06-30",
        ),
        make_lease_administrator_headers(LEASE_ADMIN_USER_ID),
    )
    validate_error(response, ERR_RADIUS_WINDOW_OVERLAP, 409)

    incumbent = fetch_restriction(api, restriction["id"])
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["window_through_date"] == "2026-12-31"


def test_radius_window_starting_the_day_after_the_prior_through_date_is_accepted(api):
    """Shifting the from-date to 2027-01-01 clears the closed-closed collision test.

    PRD: "Windows for one lease are closed-closed and may not share even a single day: two restrictions collide when the first's from-date is on or before the second's through-date and the second's from-date is on or before the first's through-date, so **touching endpoints do collide**, and the collision answers `ERR_RADIUS_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/radius_window_closed_interval_touching_endpoint_collides
    """
    scenario, restriction = _setup_radius_restriction(api)

    response = api.create_radius_restriction(
        scenario.lease_id("I3"),
        factories.radius_restriction_payload(
            radius_miles=5.0,
            measured_from="PREMISES_CENTROID",
            recapture_basis="GROSS_SALES",
            recapture_pct=6.0,
            protected_baseline_cents=0,
            window_from_date="2027-01-01",
            window_through_date="2027-06-30",
        ),
        make_lease_administrator_headers(LEASE_ADMIN_USER_ID),
    )
    created = validate_success(response, 201)

    assert created["window_from_date"] == "2027-01-01"
    assert created["status"] == "ACTIVE"
    assert fetch_restriction(api, restriction["id"])["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Measurement windows are half-open, so adjacency is legal
# --------------------------------------------------------------------------
def _setup_first_measurement(api):
    """A draft strict measurement over the half-open window 2026-06-01..2026-07-01."""
    scenario = _five_suite_center(api)
    measurement = prepare_measurement(
        api,
        scenario.center_id,
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-06-01",
        window_through_date="2026-07-01",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )
    return scenario, measurement


def test_measurement_window_straddling_an_existing_window_is_refused(api):
    """An interior overlap against a non-superseded measurement is rejected.

    PRD: "Measurement windows for one center are half-open, so a new window may begin exactly on an existing window's through-date; any interior overlap against a non-superseded measurement of the same center answers `ERR_MEASUREMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/measurement_window_half_open_adjacency_is_permitted
    """
    scenario, measurement = _setup_first_measurement(api)
    center_version = fetch_center(api, scenario.center_id)["version"]

    response = api.create_measurement(
        scenario.center_id,
        factories.measurement_payload(
            variant="SNAPSHOT_STRICT",
            window_from_date="2026-06-15",
            window_through_date="2026-07-15",
            expected_center_version=center_version,
        ),
        make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
    )
    validate_error(response, ERR_MEASUREMENT_WINDOW_OVERLAP, 409)

    # No row was created, so nothing superseded the incumbent draft.
    assert fetch_measurement(api, measurement["id"])["status"] == "DRAFT"


def test_measurement_window_starting_on_the_prior_through_date_is_permitted(api):
    """A window beginning exactly on 2026-07-01 is accepted as a draft row.

    PRD: "Measurement windows for one center are half-open, so a new window may begin exactly on an existing window's through-date; any interior overlap against a non-superseded measurement of the same center answers `ERR_MEASUREMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/measurement_window_half_open_adjacency_is_permitted
    """
    scenario, _measurement = _setup_first_measurement(api)
    center_version = fetch_center(api, scenario.center_id)["version"]

    response = api.create_measurement(
        scenario.center_id,
        factories.measurement_payload(
            variant="SNAPSHOT_STRICT",
            window_from_date="2026-07-01",
            window_through_date="2026-08-02",
            expected_center_version=center_version,
        ),
        make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
    )
    adjacent = validate_success(response, 201)

    assert adjacent["window_from_date"] == "2026-07-01"
    assert adjacent["window_through_date"] == "2026-08-02"
    assert adjacent["status"] == "DRAFT"
    # All five suites are open, so the strict snapshot is 255,000 of 300,000.
    assert_pct(adjacent["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")


# --------------------------------------------------------------------------
# Overlapping abatement windows may stack only up to 100.00 points
# --------------------------------------------------------------------------
def _setup_overlapping_elections(api):
    """One active 83.34 pct reduction plus a second election over an overlap.

    Anchor A1 is named by the condition and then goes dark, which drops live
    occupancy to 45.00 pct, breaches the condition and — through the anchor
    adder — prices each election at 83.34 pct (PRD §3.5).
    """
    scenario = _five_suite_center(api)
    condition = _condition_on_i1(api, scenario.lease_id("I1"), max_reduction_pct=90.0)
    add_anchor_requirement(
        api,
        condition["id"],
        scenario.lease_id("A1"),
        substitution_allowed=False,
        min_substitute_gla_sqft=0,
    )
    go_dark(api, scenario.lease_id("A1"))
    first = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        condition_id=condition["id"],
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
    )
    first = approve_election(api, first["id"], ASSET_MANAGER_USER_ID)
    second = elect_remedy(
        api,
        scenario.lease_id("I1"),
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        condition_id=condition["id"],
        window_from_date="2026-09-01",
        window_through_date="2026-12-01",
    )
    return scenario, condition, first, second


def test_approving_the_overlapping_second_reduction_exceeds_the_stacking_cap(api):
    """Two 83.34 pct reductions covering the same dates sum past 100 and are refused.

    PRD: "The window must lie within the lease's `commencement_date` through `expiration_date` term, and for every date the half-open window covers, the sum of `reduction_pct` over the lease's already-active reductions covering that date plus this election's own `reduction_pct` must be at most 100 — exceeding it answers `ERR_ABATEMENT_STACK_EXCEEDED`, and the window check of rung 20 is evaluated ahead of it."

    Design: Difficulty/resource_temporal_overlap/overlapping_abatement_windows_exceed_aggregate_reduction_cap
    """
    _scenario, _condition, _first, second = _setup_overlapping_elections(api)

    response = api.approve_election(
        second["id"], None, make_asset_manager_headers(ASSET_MANAGER_USER_ID)
    )
    validate_error(response, ERR_ABATEMENT_STACK_EXCEEDED, 422)

    still_elected = fetch_election(api, second["id"])
    assert still_elected["status"] == "ELECTED"
    assert_pct(still_elected["reduction_pct"], 83.34, "reduction_pct")


def test_refused_stacking_leaves_effective_rent_on_the_single_active_reduction(api):
    """Effective rent stays at the sum-then-round result of the one live reduction.

    PRD: "Take the reductions that are currently active and currently in window, add their `reduction_pct` values together into a single total percentage, subtract that total from 100, multiply the lease's `base_rent_monthly_cents` by the result, divide by 100, and round to whole cents exactly once at the end."

    Design: Difficulty/resource_temporal_overlap/overlapping_abatement_windows_exceed_aggregate_reduction_cap
    """
    scenario, _condition, first, second = _setup_overlapping_elections(api)

    api.approve_election(
        second["id"], None, make_asset_manager_headers(ASSET_MANAGER_USER_ID)
    )

    active = fetch_election(api, first["id"])
    assert active["status"] == "REDUCTION_ACTIVE"
    assert_pct(active["reduction_pct"], 83.34, "reduction_pct")
    # 1,000,000 cents times 16.66 percent, rounded once at the end.
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")),
        remedy_status="REMEDY_ACTIVE",
        effective_rent_monthly_cents=166600,
    )
