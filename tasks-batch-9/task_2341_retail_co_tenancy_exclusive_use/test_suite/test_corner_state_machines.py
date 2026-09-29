"""State-machine behaviour of the co-tenancy administration API.

Covers declared initial states, transitions invoked from a state that does not
declare them, terminal-state lockdown, replayed transitions on settled records,
the two segregation-of-duties preconditions, and the side effects that the waive,
adjudicate, supersede and terminate transitions fire.
"""
from test_helpers import (
    ASSET_MANAGER_USER_ID,
    COMPLIANCE_ADJUDICATOR_USER_ID,
    COMPLIANCE_ENFORCER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    COMPLIANCE_REVIEWER_USER_ID,
    ERR_CERTIFICATE_STATE_INVALID,
    ERR_CONDITION_STATE_INVALID,
    ERR_DISPUTE_STATE_INVALID,
    ERR_ELECTION_STATE_INVALID,
    ERR_LEASE_STATE_INVALID,
    ERR_MEASUREMENT_STATE_INVALID,
    ERR_PLAN_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    add_clause,
    add_condition,
    add_radius_restriction,
    adjudicate_dispute,
    approve_election,
    assert_center_quantities,
    assert_cents,
    assert_lease_dimensions,
    assert_null,
    assert_pct,
    assert_unchanged,
    certify_measurement,
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
    fetch_dispute,
    fetch_election,
    fetch_lease,
    fetch_measurement,
    fetch_notice,
    fetch_plan,
    fetch_restriction,
    file_dispute,
    go_dark,
    is_iso8601_timestamp,
    issue_notice,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lease_administrator_headers,
    make_tenant_rep_headers,
    open_lease,
    plan_redevelopment,
    prepare_measurement,
    record_plan,
    request_certificate,
    set_clock,
    sign_certificate,
    supersede_measurement,
    terminate_lease,
    validate_error,
    waive_condition,
)

CLOCK = "2026-08-01T00:00:00Z"

# Northgate Crossing: 300000 total GLA, two anchors and three inline suites.
# suite, legal_name, notice_email, use code, national chain, GLA, parcel, rent
_SUITES = (
    (
        "A1",
        "Boxmart Retail Inc",
        "legal@boxmart.example",
        "DISCOUNT_DEPT",
        True,
        120000,
        "ANCHOR_BOX",
        6000000,
    ),
    (
        "A2",
        "Grocerway Foods LLC",
        "legal@grocerway.example",
        "GROCERY",
        True,
        100000,
        "ANCHOR_BOX",
        4000000,
    ),
    (
        "I1",
        "Bean Theory Coffee LLC",
        "legal@beantheory.example",
        "COFFEE",
        False,
        2000,
        "INLINE",
        1000000,
    ),
    (
        "I2",
        "Margin Books LLC",
        "legal@marginbooks.example",
        "BOOKS",
        False,
        3000,
        "INLINE",
        1200000,
    ),
    (
        "I3",
        "Pulse Fitness Group",
        "legal@pulsefitness.example",
        "FITNESS",
        True,
        30000,
        "INLINE",
        1500000,
    ),
)


def _build_leased_up_center(api):
    """Center with five leases taken all the way to ``OPEN``.

    Occupied GLA lands on 255000 of 300000, so ``open_occupancy_pct`` is 85.00
    and the center's posture is ``COMPLIANT`` (PRD 2.6).
    """
    set_clock(api, CLOCK)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    tenants = {}
    for suite, legal_name, email, use_code, chain, _gla, _parcel, _rent in _SUITES:
        tenants[suite] = create_tenant(
            api,
            legal_name=legal_name,
            notice_email=email,
            primary_use_code=use_code,
            is_national_chain=chain,
        )
    leases = {}
    for suite, _name, _email, use_code, _chain, gla, parcel, rent in _SUITES:
        leases[suite] = draft_lease(
            api,
            center["id"],
            tenants[suite]["id"],
            suite_code=suite,
            gla_sqft=gla,
            parcel_kind=parcel,
            primary_use_code=use_code,
            base_rent_monthly_cents=rent,
            commencement_date="2026-01-01",
            expiration_date="2036-12-31",
        )
    for suite in leases:
        execute_lease(api, leases[suite]["id"])
    for suite in leases:
        leases[suite] = open_lease(api, leases[suite]["id"])
    return center, tenants, leases


def _coffee_clause(api, lease_id):
    """Center-wide COFFEE exclusive on the inline coffee suite."""
    return add_clause(
        api,
        lease_id,
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )


def test_drafted_lease_starts_on_all_three_initial_states(api):
    """A freshly drafted lease sits on DRAFT, NONE and CLEAR with every stamp null.

    PRD: "A drafted lease starts with `premises_status` at `DRAFT`, `remedy_status` at `NONE`, `use_compliance_status` at `CLEAR`, `effective_rent_monthly_cents` equal to `base_rent_monthly_cents`, `total_abated_cents` at 0, and `opened_at`, `dark_since`, and `remedy_eligible_at` all null."

    Design: Corner/state_machines/lease_initial_state_is_draft_with_no_remedy_or_violation
    """
    set_clock(api, CLOCK)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    tenant = create_tenant(
        api,
        legal_name="Halcyon Optical LLC",
        notice_email="legal@halcyonoptical.example",
        primary_use_code="OPTICAL",
        is_national_chain=False,
    )

    lease = draft_lease(
        api,
        center["id"],
        tenant["id"],
        suite_code="I9",
        gla_sqft=2200,
        parcel_kind="INLINE",
        primary_use_code="OPTICAL",
        base_rent_monthly_cents=500000,
        commencement_date="2026-09-01",
        expiration_date="2036-08-31",
    )

    assert_lease_dimensions(
        lease,
        premises_status="DRAFT",
        remedy_status="NONE",
        use_compliance_status="CLEAR",
        effective_rent_monthly_cents=500000,
        total_abated_cents=0,
    )
    assert_null(lease["opened_at"], "opened_at")
    assert_null(lease["dark_since"], "dark_since")
    assert_null(lease["remedy_eligible_at"], "remedy_eligible_at")


def test_drafted_lease_leaves_the_center_untouched(api):
    """Drafting a lease moves no center figure, so the store count stays at 0.

    PRD: "A `DRAFT` lease sits outside the occupancy population and moves no center field whatsoever."

    Design: Corner/state_machines/lease_initial_state_is_draft_with_no_remedy_or_violation
    """
    set_clock(api, CLOCK)
    center = create_center(
        api,
        name="Northgate Crossing",
        total_gla_sqft=300000,
        occupancy_grace_days=30,
    )
    tenant = create_tenant(
        api,
        legal_name="Halcyon Optical LLC",
        notice_email="legal@halcyonoptical.example",
        primary_use_code="OPTICAL",
        is_national_chain=False,
    )

    draft_lease(
        api,
        center["id"],
        tenant["id"],
        suite_code="I9",
        gla_sqft=2200,
        parcel_kind="INLINE",
        primary_use_code="OPTICAL",
        base_rent_monthly_cents=500000,
        commencement_date="2026-09-01",
        expiration_date="2036-08-31",
    )

    after = fetch_center(api, center["id"])
    assert_center_quantities(
        after,
        total_gla_sqft=300000,
        occupied_gla_sqft=0,
        open_occupancy_pct=0.0,
    )
    assert after["operating_store_count"] == 0, (
        f"operating_store_count moved to {after['operating_store_count']} for a DRAFT lease"
    )


def test_execute_on_an_already_open_lease_is_rejected(api):
    """Execute is declared only from DRAFT, so an OPEN lease refuses it and stays OPEN.

    PRD: "Declared transition — the addressed entity sits in a state from which the requested transition exists."

    Design: Corner/state_machines/execute_on_an_already_open_lease_is_rejected
    """
    center, _tenants, leases = _build_leased_up_center(api)
    before = fetch_lease(api, leases["I1"]["id"])

    res = api.execute_lease(
        leases["I1"]["id"], None, make_lease_administrator_headers()
    )

    validate_error(res, ERR_LEASE_STATE_INVALID)
    after = fetch_lease(api, leases["I1"]["id"])
    assert_lease_dimensions(after, premises_status="OPEN")
    assert_unchanged(before, after, ["opened_at"])
    assert_center_quantities(
        fetch_center(api, center["id"]), occupied_gla_sqft=255000
    )


def test_reopen_on_a_terminated_lease_is_rejected(api):
    """Reopen requires a DARK premises, so a TERMINATED lease is locked out of it.

    PRD: "A `LeaseAdministrator` or `TenantRep` moves the premises `DARK → OPEN` provided they are currently `DARK` and the tenant's `status` is not `BANKRUPT`."

    Design: Corner/state_machines/terminated_lease_rejects_reopen_and_stays_locked
    """
    _center, tenants, leases = _build_leased_up_center(api)
    terminate_lease(api, leases["I3"]["id"], termination_reason_code="SURRENDER")

    res = api.reopen_lease(
        leases["I3"]["id"], None, make_tenant_rep_headers(tenants["I3"]["id"])
    )

    validate_error(res, ERR_LEASE_STATE_INVALID)
    assert_lease_dimensions(
        fetch_lease(api, leases["I3"]["id"]), premises_status="TERMINATED"
    )


def test_terminated_lease_keeps_the_center_on_post_termination_figures(api):
    """A terminated lease is gone from the occupancy population for good.

    PRD: "`premises_status` becomes the terminal `TERMINATED`, `dark_since` is cleared to null, and the lease leaves the occupancy population entirely."

    Design: Corner/state_machines/terminated_lease_rejects_reopen_and_stays_locked
    """
    center, tenants, leases = _build_leased_up_center(api)
    terminate_lease(api, leases["I3"]["id"], termination_reason_code="SURRENDER")

    res = api.reopen_lease(
        leases["I3"]["id"], None, make_tenant_rep_headers(tenants["I3"]["id"])
    )
    validate_error(res, ERR_LEASE_STATE_INVALID)

    lease = fetch_lease(api, leases["I3"]["id"])
    assert_null(lease["dark_since"], "dark_since")
    # 255000 - 30000 of inline GLA leaves 225000 of 300000 open.
    assert_center_quantities(
        fetch_center(api, center["id"]),
        total_gla_sqft=300000,
        occupied_gla_sqft=225000,
        open_occupancy_pct=75.00,
        operating_store_count=2,
        aggregate_effective_rent_cents=12200000,
        compliance_posture="COMPLIANT",
    )


def test_repeat_actions_on_settled_entities_are_rejected(api):
    """Replaying a consumed transition answers that family's own STATE_INVALID code.

    PRD: "Declared transition — the addressed entity sits in a state from which the requested transition exists."

    Design: Corner/state_machines/repeat_actions_on_settled_entities_are_rejected
    """
    center, tenants, leases = _build_leased_up_center(api)
    cond1 = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    cond2 = add_condition(
        api,
        leases["I2"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=50.0,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    # I3 dark drops occupancy to 75.00, which breaches the 81.67 condition.
    go_dark(api, leases["I3"]["id"])

    election = elect_remedy(
        api,
        leases["I1"]["id"],
        tenants["I1"]["id"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=cond1["id"],
    )
    approve_election(api, election["id"])

    clause = _coffee_clause(api, leases["I1"]["id"])
    notice = issue_notice(
        api,
        leases["I3"]["id"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute = file_dispute(
        api,
        notice["id"],
        tenants["I3"]["id"],
        grounds_code="NO_PROHIBITED_USE",
        narrative="Staff machine only.",
        cure_extension_days=0,
    )
    adjudicate_dispute(
        api, dispute["id"], "DENIED", user_id=COMPLIANCE_ADJUDICATOR_USER_ID
    )

    measurement = prepare_measurement(
        api,
        center["id"],
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-08-02",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )
    certify_measurement(
        api, measurement["id"], user_id=COMPLIANCE_REVIEWER_USER_ID
    )

    certificate = request_certificate(
        api, leases["I2"]["id"], expedite_requested=False
    )
    sign_certificate(api, certificate["id"], tenants["I2"]["id"])

    plan = plan_redevelopment(
        api, center["id"], plan_kind="EXPANSION", removed_gla_sqft=0
    )
    record_plan(api, plan["id"], consent_confirmed=True)
    waive_condition(api, cond2["id"], waiver_reason_code="LANDLORD_WAIVER")

    validate_error(
        api.approve_election(
            election["id"], None, make_asset_manager_headers(ASSET_MANAGER_USER_ID)
        ),
        ERR_ELECTION_STATE_INVALID,
    )
    validate_error(
        api.adjudicate_dispute(
            dispute["id"],
            factories.adjudicate_payload("DENIED"),
            make_compliance_officer_headers(COMPLIANCE_ADJUDICATOR_USER_ID),
        ),
        ERR_DISPUTE_STATE_INVALID,
    )
    validate_error(
        api.certify_measurement(
            measurement["id"],
            None,
            make_compliance_officer_headers(COMPLIANCE_REVIEWER_USER_ID),
        ),
        ERR_MEASUREMENT_STATE_INVALID,
    )
    validate_error(
        api.sign_certificate(
            certificate["id"], None, make_tenant_rep_headers(tenants["I2"]["id"])
        ),
        ERR_CERTIFICATE_STATE_INVALID,
    )
    validate_error(
        api.record_plan(
            plan["id"],
            factories.record_plan_payload(True),
            make_asset_manager_headers(ASSET_MANAGER_USER_ID),
        ),
        ERR_PLAN_STATE_INVALID,
    )
    validate_error(
        api.waive_condition(
            cond2["id"],
            factories.waive_payload("LANDLORD_WAIVER"),
            make_asset_manager_headers(ASSET_MANAGER_USER_ID),
        ),
        ERR_CONDITION_STATE_INVALID,
    )

    assert fetch_election(api, election["id"])["status"] == "REDUCTION_ACTIVE"
    assert fetch_dispute(api, dispute["id"])["status"] == "DENIED"
    settled_measurement = fetch_measurement(api, measurement["id"])
    assert settled_measurement["status"] == "CERTIFIED"
    assert settled_measurement["certified_by_user_id"] == COMPLIANCE_REVIEWER_USER_ID
    assert fetch_certificate(api, certificate["id"])["status"] == "TENANT_SIGNED"
    assert fetch_plan(api, plan["id"])["status"] == "RECORDED"
    assert fetch_condition(api, cond2["id"])["status"] == "WAIVED"


def test_waiving_a_breached_condition_drives_it_to_waived_and_clears_the_breach_marks(
    api,
):
    """Waiving a BREACHED condition lands on WAIVED with the breach marks cleared.

    PRD: "A waive is accepted from `SATISFIED`, `CURED`, or `BREACHED` and drives the condition to the terminal `WAIVED` with `breach_detected_at` cleared to null and `consecutive_breach_days` zeroed; from any other status it answers `ERR_CONDITION_STATE_INVALID`."

    Design: Corner/state_machines/waiving_a_breached_condition_releases_remedy_and_relaxes_posture
    """
    _center, tenants, leases = _build_leased_up_center(api)
    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=90.0,
    )
    # The 120000 sqft anchor going dark drops occupancy to 45.00 and breaches it.
    go_dark(api, leases["A1"]["id"])
    assert fetch_condition(api, condition["id"])["status"] == "BREACHED"
    elect_remedy(
        api,
        leases["I1"]["id"],
        tenants["I1"]["id"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition["id"],
    )

    waive_condition(api, condition["id"], waiver_reason_code="LANDLORD_WAIVER")

    waived = fetch_condition(api, condition["id"])
    assert waived["status"] == "WAIVED", (
        f"condition status is {waived['status']}, expected WAIVED"
    )
    assert_null(waived["breach_detected_at"], "breach_detected_at")
    assert waived["consecutive_breach_days"] == 0, (
        f"consecutive_breach_days is {waived['consecutive_breach_days']}, expected 0"
    )


def test_waiving_a_breached_condition_releases_the_lease_and_rescinds_the_election(api):
    """The waive returns the benefited lease to NONE and rescinds its pending election.

    PRD: "Waiving a breached condition additionally returns the benefited lease from `ELIGIBLE` to `NONE` when it was that lease's only breached condition, rescinds every election naming that condition that is still merely elected and reverses its reduction, and re-derives the center's posture — which is the mechanism by which a `FROZEN` center can fall back to `BREACH` or `COMPLIANT`."

    Design: Corner/state_machines/waiving_a_breached_condition_releases_remedy_and_relaxes_posture
    """
    center, tenants, leases = _build_leased_up_center(api)
    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=90.0,
    )
    go_dark(api, leases["A1"]["id"])
    election = elect_remedy(
        api,
        leases["I1"]["id"],
        tenants["I1"]["id"],
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition["id"],
    )

    waive_condition(api, condition["id"], waiver_reason_code="LANDLORD_WAIVER")

    assert fetch_election(api, election["id"])["status"] == "RESCINDED", (
        "an election naming the waived condition must be rescinded"
    )
    lease = fetch_lease(api, leases["I1"]["id"])
    assert_lease_dimensions(
        lease, remedy_status="NONE", effective_rent_monthly_cents=1000000
    )
    assert_null(lease["remedy_eligible_at"], "remedy_eligible_at")
    # Occupancy stays at 45.00 with the anchor dark, which holds the center FROZEN.
    after = fetch_center(api, center["id"])
    assert_center_quantities(
        after,
        open_occupancy_pct=45.00,
        compliance_posture="FROZEN",
        aggregate_effective_rent_cents=13700000,
    )


def test_measurement_certification_by_its_creator_is_rejected(api):
    """The officer who prepared a measurement may not certify it.

    PRD: "A `ComplianceOfficer` whose `X-User-ID` differs from the row's `created_by_user_id` certifies a `DRAFT` measurement; the same officer who prepared it is refused with `ERR_SEGREGATION_OF_DUTIES`, and certifying a row that is not `DRAFT` answers `ERR_MEASUREMENT_STATE_INVALID`."

    Design: Corner/state_machines/measurement_certification_by_its_creator_is_rejected
    """
    center, _tenants, _leases = _build_leased_up_center(api)
    measurement = prepare_measurement(
        api,
        center["id"],
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-08-02",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )

    res = api.certify_measurement(
        measurement["id"],
        None,
        make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
    )

    validate_error(res, ERR_SEGREGATION_OF_DUTIES)
    after = fetch_measurement(api, measurement["id"])
    assert after["status"] == "DRAFT", (
        f"measurement status is {after['status']}, expected DRAFT"
    )
    assert after["created_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert_null(after["certified_by_user_id"], "certified_by_user_id")
    assert_null(after["certified_at"], "certified_at")
    assert_pct(after["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")


def test_dispute_adjudication_by_the_notice_issuer_is_rejected(api):
    """The officer who issued the notice may not adjudicate its dispute.

    PRD: "A `ComplianceOfficer` whose `X-User-ID` differs from the notice's `issued_by_user_id` adjudicates a `PENDING` dispute by supplying an `outcome`; the notice's own issuer is refused with `ERR_SEGREGATION_OF_DUTIES`, and adjudicating a dispute already `UPHELD`, `DENIED`, or `WITHDRAWN` answers `ERR_DISPUTE_STATE_INVALID`."

    Design: Corner/state_machines/dispute_adjudication_by_the_notice_issuer_is_rejected
    """
    _center, tenants, leases = _build_leased_up_center(api)
    clause = _coffee_clause(api, leases["I1"]["id"])
    notice = issue_notice(
        api,
        leases["I3"]["id"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute = file_dispute(
        api,
        notice["id"],
        tenants["I3"]["id"],
        grounds_code="CLAUSE_EXPIRED",
        narrative="The clause lapsed in 2025.",
        cure_extension_days=0,
    )

    res = api.adjudicate_dispute(
        dispute["id"],
        factories.adjudicate_payload("UPHELD"),
        make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
    )

    validate_error(res, ERR_SEGREGATION_OF_DUTIES)
    after_dispute = fetch_dispute(api, dispute["id"])
    assert after_dispute["status"] == "PENDING", (
        f"dispute status is {after_dispute['status']}, expected PENDING"
    )
    assert_null(after_dispute["adjudicated_by_user_id"], "adjudicated_by_user_id")
    assert_null(after_dispute["adjudicated_at"], "adjudicated_at")
    after_notice = fetch_notice(api, notice["id"])
    assert after_notice["status"] == "DISPUTED", (
        f"notice status is {after_notice['status']}, expected DISPUTED"
    )
    assert after_notice["issued_by_user_id"] == COMPLIANCE_ENFORCER_USER_ID


def test_upheld_dispute_withdraws_the_notice(api):
    """Upholding a dispute settles it and withdraws the notice it attacked.

    PRD: "An **upheld** dispute moves to the terminal `UPHELD` and drives the notice `DISPUTED → WITHDRAWN` with every notice side effect reversed."

    Design: Corner/state_machines/upheld_dispute_withdraws_the_notice_and_clears_the_lease
    """
    _center, tenants, leases = _build_leased_up_center(api)
    clause = _coffee_clause(api, leases["I1"]["id"])
    notice = issue_notice(
        api,
        leases["I3"]["id"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute = file_dispute(
        api,
        notice["id"],
        tenants["I3"]["id"],
        grounds_code="NO_PROHIBITED_USE",
        narrative="No espresso is sold to the public.",
        cure_extension_days=0,
    )

    adjudicate_dispute(
        api, dispute["id"], "UPHELD", user_id=COMPLIANCE_ADJUDICATOR_USER_ID
    )

    after_dispute = fetch_dispute(api, dispute["id"])
    assert after_dispute["status"] == "UPHELD", (
        f"dispute status is {after_dispute['status']}, expected UPHELD"
    )
    assert after_dispute["adjudicated_by_user_id"] == COMPLIANCE_ADJUDICATOR_USER_ID
    assert is_iso8601_timestamp(after_dispute["adjudicated_at"]), (
        f"adjudicated_at is not ISO-8601: {after_dispute['adjudicated_at']}"
    )
    after_notice = fetch_notice(api, notice["id"])
    assert after_notice["status"] == "WITHDRAWN", (
        f"notice status is {after_notice['status']}, expected WITHDRAWN"
    )
    # The cure clock was never re-armed, so no restart is counted.
    assert after_notice["cure_restart_count"] == 0, (
        f"cure_restart_count is {after_notice['cure_restart_count']}, expected 0"
    )


def test_upheld_dispute_clears_the_lease_and_relaxes_posture(api):
    """Withdrawing the notice returns the lease to CLEAR and the center to COMPLIANT.

    PRD: "The violating lease's `use_compliance_status` is recomputed, `open_violation_count` decrements, and posture is re-derived."

    Design: Corner/state_machines/upheld_dispute_withdraws_the_notice_and_clears_the_lease
    """
    center, tenants, leases = _build_leased_up_center(api)
    clause = _coffee_clause(api, leases["I1"]["id"])
    notice = issue_notice(
        api,
        leases["I3"]["id"],
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute = file_dispute(
        api,
        notice["id"],
        tenants["I3"]["id"],
        grounds_code="NO_PROHIBITED_USE",
        narrative="No espresso is sold to the public.",
        cure_extension_days=0,
    )

    adjudicate_dispute(
        api, dispute["id"], "UPHELD", user_id=COMPLIANCE_ADJUDICATOR_USER_ID
    )

    assert_lease_dimensions(
        fetch_lease(api, leases["I3"]["id"]), use_compliance_status="CLEAR"
    )
    assert_center_quantities(
        fetch_center(api, center["id"]),
        open_violation_count=0,
        open_occupancy_pct=85.00,
        compliance_posture="COMPLIANT",
    )


def test_superseding_a_certified_measurement_returns_the_condition_to_the_live_engine(
    api,
):
    """Superseding unpins the condition and re-breaches it at the live figures.

    PRD: "The `status` moves to the terminal `SUPERSEDED`, every condition whose `last_evaluated_measurement_id` pointed at this row has that field cleared to null and is re-evaluated under the live strict engine — which can re-breach it immediately — and posture is re-derived."

    Design: Corner/state_machines/superseding_a_certified_measurement_returns_conditions_to_the_live_engine
    """
    center, _tenants, leases = _build_leased_up_center(api)
    condition = add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    # The live engine sees 75.00 once I3 is dark; a trailing-grace certification
    # still counts the suite and cures the condition.
    go_dark(api, leases["I3"]["id"])
    measurement = prepare_measurement(
        api,
        center["id"],
        variant="TRAILING_GRACE",
        window_from_date="2026-08-01",
        window_through_date="2026-09-01",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )
    certify_measurement(api, measurement["id"], user_id=COMPLIANCE_REVIEWER_USER_ID)

    supersede_measurement(
        api,
        measurement["id"],
        supersede_reason_code="FIGURES_RESTATED",
        user_id=COMPLIANCE_REVIEWER_USER_ID,
    )

    after_measurement = fetch_measurement(api, measurement["id"])
    assert after_measurement["status"] == "SUPERSEDED", (
        f"measurement status is {after_measurement['status']}, expected SUPERSEDED"
    )
    assert_pct(after_measurement["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")
    after_condition = fetch_condition(api, condition["id"])
    assert_null(
        after_condition["last_evaluated_measurement_id"],
        "last_evaluated_measurement_id",
    )
    assert after_condition["status"] == "BREACHED", (
        f"condition status is {after_condition['status']}, expected BREACHED"
    )
    assert is_iso8601_timestamp(after_condition["breach_detected_at"]), (
        f"breach_detected_at is not ISO-8601: {after_condition['breach_detected_at']}"
    )
    assert_center_quantities(
        fetch_center(api, center["id"]),
        open_occupancy_pct=75.00,
        compliance_posture="BREACH",
    )


def test_superseding_a_certified_measurement_returns_the_lease_to_eligible(api):
    """The re-breach at zero grace puts the benefited lease back on ELIGIBLE.

    PRD: "A lease reaches `ELIGIBLE` from `NONE` when a condition of that lease flips to breached with a zero grace period, when a sweep observes `consecutive_breach_days` at or above `grace_period_days`, or when a notice citing a clause of that lease is escalated; the lease must be in `EXECUTED`, `OPEN`, or `DARK` and must actually have a breached condition or an escalated notice against a clause it benefits from, and `remedy_eligible_at` is stamped while every estoppel certificate of the lease that is `REQUESTED` or `TENANT_SIGNED` flips to `STALE`."

    Design: Corner/state_machines/superseding_a_certified_measurement_returns_conditions_to_the_live_engine
    """
    center, _tenants, leases = _build_leased_up_center(api)
    add_condition(
        api,
        leases["I1"]["id"],
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    go_dark(api, leases["I3"]["id"])
    measurement = prepare_measurement(
        api,
        center["id"],
        variant="TRAILING_GRACE",
        window_from_date="2026-08-01",
        window_through_date="2026-09-01",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )
    certify_measurement(api, measurement["id"], user_id=COMPLIANCE_REVIEWER_USER_ID)

    supersede_measurement(
        api,
        measurement["id"],
        supersede_reason_code="FIGURES_RESTATED",
        user_id=COMPLIANCE_REVIEWER_USER_ID,
    )

    lease = fetch_lease(api, leases["I1"]["id"])
    assert_lease_dimensions(lease, remedy_status="ELIGIBLE")
    assert is_iso8601_timestamp(lease["remedy_eligible_at"]), (
        f"remedy_eligible_at is not ISO-8601: {lease['remedy_eligible_at']}"
    )


def test_terminating_a_lease_expires_its_clauses_and_restrictions(api):
    """Termination expires the lease's own clause and radius restriction only.

    PRD: "Every exclusive-use clause of that lease whose `status` is `ACTIVE` or `SUSPENDED` becomes `EXPIRED`, and every radius restriction of that lease whose `status` is `ACTIVE` becomes `EXPIRED`."

    Design: Corner/state_machines/terminating_a_lease_cascades_down_to_its_clauses_and_conditions
    """
    _center, _tenants, leases = _build_leased_up_center(api)
    coffee_clause = _coffee_clause(api, leases["I1"]["id"])
    fitness_clause = add_clause(
        api,
        leases["I3"]["id"],
        protected_use_codes=["FITNESS"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    restriction = add_radius_restriction(
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

    terminate_lease(
        api, leases["I3"]["id"], termination_reason_code="DEFAULT_TERMINATION"
    )

    assert_lease_dimensions(
        fetch_lease(api, leases["I3"]["id"]), premises_status="TERMINATED"
    )
    assert fetch_clause(api, fitness_clause["id"])["status"] == "EXPIRED", (
        "the terminated lease's own clause must expire"
    )
    assert fetch_clause(api, coffee_clause["id"])["status"] == "ACTIVE", (
        "another lease's clause must be left alone"
    )
    assert fetch_restriction(api, restriction["id"])["status"] == "EXPIRED", (
        "the terminated lease's radius restriction must expire"
    )


def test_terminating_a_lease_recomputes_the_center(api):
    """Termination re-runs the center's occupancy, rent and exclusive tallies.

    PRD: "The center then recomputes `occupied_gla_sqft`, `open_occupancy_pct`, `operating_store_count`, `open_anchor_count`, `aggregate_effective_rent_cents`, and `protected_exclusive_count`, re-evaluates every `ONGOING` condition of the center under the live strict engine — skipping the conditions of the terminated lease itself — and re-derives posture."

    Design: Corner/state_machines/terminating_a_lease_cascades_down_to_its_clauses_and_conditions
    """
    center, _tenants, leases = _build_leased_up_center(api)
    _coffee_clause(api, leases["I1"]["id"])
    add_clause(
        api,
        leases["I3"]["id"],
        protected_use_codes=["FITNESS"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    add_radius_restriction(
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
    before = fetch_center(api, center["id"])
    assert_center_quantities(before, protected_exclusive_count=2)

    terminate_lease(
        api, leases["I3"]["id"], termination_reason_code="DEFAULT_TERMINATION"
    )

    after = fetch_center(api, center["id"])
    assert_center_quantities(
        after,
        occupied_gla_sqft=225000,
        open_occupancy_pct=75.00,
        protected_exclusive_count=1,
    )
    # 13700000 less the terminated suite's 1500000 of contractual rent.
    assert_cents(
        after["aggregate_effective_rent_cents"],
        12200000,
        "aggregate_effective_rent_cents",
    )
