"""Role coverage: route grants, supplier-portal scoping and the three segregation-of-duties pairs.

PRD §2.1: "If both headers are well-formed but the named role is not among the roles authorised
for the requested endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). These
two checks precede every other form of validation in the system."
"""

from test_helpers import (
    ACTUARY_HEADERS,
    ACTUARY_USER_ID,
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    ERR_FORBIDDEN_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUPPLIER_SCOPE_VIOLATION,
    RESERVE_CONTROLLER_USER_ID,
    actuarial_decision,
    assert_recovery,
    book_liability_reserve,
    create_accrual,
    create_failure_mode,
    create_family,
    create_field_action,
    create_liability_reserve,
    create_observation,
    create_period,
    create_recovery,
    create_remedy_option,
    create_supplier,
    create_vintage,
    decide_field_action,
    factories,
    fresh_user_id,
    generate_rollforward,
    lock_period,
    make_actuary_headers,
    make_quality_engineer_headers,
    make_reserve_controller_headers,
    make_supplier_rep_headers,
    make_warranty_analyst_headers,
    move_clock,
    open_review,
    post_accrual,
    propose_accrual,
    read_accrual,
    read_family,
    read_field_action,
    read_liability_reserve,
    read_recovery,
    select_remedy,
    submit_field_action,
    success_data,
    validate_error,
    validate_paginated,
)


def _analog_basis(api):
    """FAM-A: 300 observed claims on a 10000-unit cohort, the standard analogue basis."""
    analog_family = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog_family["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2029-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog_family["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )
    return analog_family


def _blend_family(api, analog_family_id, family_code, name):
    """A 3000-unit cohort priced at 30000 cents a claim against the analogue basis."""
    family = create_family(
        api,
        family_code=family_code,
        name=name,
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=20000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family_id,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code=f"{family_code}-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code=f"FM-{family_code}-01",
        description="Blend platform mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=30000,
    )
    return family, vintage


def test_the_authoring_analyst_is_refused_the_post_route_outright(api):
    """The role gate answers before the accrual's own state is even considered.

    PRD §4 grants `POST /warranty/accruals/{accrualId}/post` to `ReserveController` alone, and
    PRD §2.8 states the intent: "proposing an accrual is a `WarrantyAnalyst` capability while
    posting it is a `ReserveController` capability". PRD §2.9 rung 2 is "The acting role appears
    in the requested endpoint's authorised-role list — every endpoint — otherwise
    `ERR_FORBIDDEN_ROLE`", which outranks the state rung, so the still-`DRAFT` accrual never
    reports `ERR_INVALID_STATE_TRANSITION`.

    Design: Corner/rbac/corner_warranty_analyst_cannot_post_the_accrual_it_authored
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog = _analog_basis(api)
    family, vintage = _blend_family(api, analog["id"], "FAM-RB", "Role Boundary Platform")
    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
    )
    assert accrual["status"] == "DRAFT"

    validate_error(
        api.post_accrual(ANALYST_HEADERS, accrual["id"]),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    unchanged = read_accrual(api, accrual["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["posted_by_user_id"] is None
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 0


def test_the_quality_engineer_is_barred_from_the_calendar_and_the_disclosure(api):
    """A controller-only write and an analyst-visible read are both refused to the engineer.

    PRD §4 grants `POST /warranty/periods` to `ReserveController` and
    `GET /warranty/rollforwards/{rollforwardId}` to "ReserveController, WarrantyAnalyst,
    Actuary" — `QualityEngineer` appears in neither list, while `GET /warranty/field-actions`
    is granted to "QualityEngineer, ReserveController, WarrantyAnalyst, Actuary". PRD §2.1:
    "If both headers are well-formed but the named role is not among the roles authorised for
    the requested endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_quality_engineer_cannot_open_a_period_or_read_the_rollforward
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    lock_period(api, period["id"])
    rollforward = generate_rollforward(api, period["id"])

    validate_error(
        api.create_period(ENGINEER_HEADERS, "2026-Q4", "2026-10-01", "2026-12-31"),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.get_rollforward(ENGINEER_HEADERS, rollforward["id"]),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    analyst_view = success_data(api.get_rollforward(ANALYST_HEADERS, rollforward["id"]))
    assert analyst_view["id"] == rollforward["id"]

    _, meta = validate_paginated(api.list_field_actions(ENGINEER_HEADERS))
    assert meta["total_count"] == 0

    # The refused create persisted nothing, so the code is still free for its owner role.
    replacement = create_period(api, "2026-Q4", "2026-10-01", "2026-12-31")
    assert replacement["period_code"] == "2026-Q4"


def test_the_reviewing_actuary_is_refused_the_booking_route(api):
    """Booking belongs to the controller even when the actuary is the reviewer of record.

    PRD §3.8: "Booking is a `ReserveController` capability. It advances `ACTUARY_REVIEWED` to
    `BOOKED`, which is terminal, and requires the scoping period to be precisely in
    `ACTUARIAL_REVIEW`". PRD §2.8 adds that "reviewing a liability reserve is an `Actuary`
    capability while booking it is a `ReserveController` capability".

    Design: Corner/rbac/corner_actuary_cannot_book_the_reserve_it_reviewed
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-AB2",
        name="Actuary Boundary Platform",
        launch_date="2023-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=18000,
        reserve_cap_cents=30000000,
    )
    create_vintage(
        api,
        family["id"],
        vintage_code="AC-MY2023",
        units_shipped=1000,
        ship_period_code="2023-Q1",
        warranty_expiry_date="2028-12-31",
    )
    reserve = create_liability_reserve(
        api,
        period["id"],
        family["id"],
        reported_claim_count=20,
        asserted_case_reserve_cents=2000000,
        reporting_lag_months=2,
        severity_trend_bps=0,
    )
    lock_period(api, period["id"])
    reviewed = actuarial_decision(api, reserve["id"], "REVIEWED")
    assert reviewed["reviewed_by_user_id"] == ACTUARY_USER_ID
    open_review(api, period["id"])

    validate_error(
        api.book_liability_reserve(ACTUARY_HEADERS, reserve["id"]),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    assert read_liability_reserve(api, reserve["id"])["status"] == "ACTUARY_REVIEWED"

    booked = book_liability_reserve(api, reserve["id"])
    assert booked["status"] == "BOOKED"
    assert booked["reviewed_by_user_id"] == ACTUARY_USER_ID
    assert booked["total_liability_reserve_cents"] == 2500000


def test_the_platform_admin_holds_the_clock_and_nothing_else(api):
    """Its only grant is the clock route; even a plain read of a family is refused.

    PRD §2.1: "A `PlatformAdmin` is an operations account that controls the server's logical
    clock and holds no business authority over reserves whatsoever." PRD §4 grants
    `POST /warranty/_clock/set_current_utc` to `PlatformAdmin` and lists neither
    `POST /warranty/product-families` nor `GET /warranty/product-families/{familyId}` for it.

    Design: Corner/rbac/corner_platform_admin_cannot_touch_business_data
    """
    family = create_family(
        api,
        family_code="FAM-PA",
        name="Platform Admin Boundary",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )

    validate_error(
        api.create_product_family_raw(
            ADMIN_HEADERS,
            factories.family_payload(
                family_code="FAM-PA-2",
                name="Admin Authored Platform",
                launch_date="2024-01-01",
                base_warranty_months=24,
                standard_cost_per_claim_cents=12000,
                reserve_cap_cents=15000000,
            ),
        ),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.get_product_family(ADMIN_HEADERS, family["id"]),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )

    families, meta = validate_paginated(api.list_product_families(ANALYST_HEADERS))
    assert meta["total_count"] == 1
    assert families[0]["id"] == family["id"]

    move_clock(api, "2026-09-01T00:00:00Z")


def test_a_supplier_rep_is_confined_to_its_own_recovery_claims(api):
    """The portal scope answers before the not-found rung and forbids an unfiltered list.

    PRD §2.1: "a `SupplierRep` may act on a supplier recovery claim only when that claim's
    `supplier_id` equals the caller's `X-User-ID`, and when listing recovery claims the
    `supplier_id` filter must be supplied and must equal `X-User-ID`; any other read or write
    scope yields `ERR_SUPPLIER_SCOPE_VIOLATION` (HTTP 403)." PRD §2.9 places that check at rung
    3, ahead of rung 4's path-id resolution.

    Design: Corner/rbac/corner_supplier_rep_cannot_read_another_suppliers_recovery
    """
    supplier_x = create_supplier(
        api,
        supplier_code="SUP-X",
        name="Supplier X Components",
        credit_rating="AAA",
        annual_purchase_volume_cents=500000000,
        contractual_recovery_cap_bps=2000,
    )
    supplier_y = create_supplier(
        api,
        supplier_code="SUP-Y",
        name="Supplier Y Components",
        credit_rating="AAA",
        annual_purchase_volume_cents=500000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-SX",
        name="Supplier Scope Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=20000000,
    )
    mode_x = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-SX-X",
        description="X-sourced valve defect",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier_x["id"],
    )
    mode_y = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-SX-Y",
        description="Y-sourced valve defect",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier_y["id"],
    )
    recovery_x = create_recovery(
        api, supplier_x["id"], mode_x["id"], asserted_amount_cents=900000
    )
    recovery_y = create_recovery(
        api, supplier_y["id"], mode_y["id"], asserted_amount_cents=700000
    )

    rep_x = make_supplier_rep_headers(supplier_x["id"])

    validate_error(
        api.get_supplier_recovery(rep_x, recovery_y["id"]),
        ERR_SUPPLIER_SCOPE_VIOLATION,
        expected_status=403,
    )
    validate_error(
        api.list_supplier_recoveries(rep_x),
        ERR_SUPPLIER_SCOPE_VIOLATION,
        expected_status=403,
    )

    own, own_meta = validate_paginated(
        api.list_supplier_recoveries(rep_x, supplier_id=supplier_x["id"])
    )
    assert own_meta["total_count"] == 1
    assert [row["id"] for row in own] == [recovery_x["id"]]

    analyst_sibling = success_data(api.get_supplier_recovery(ANALYST_HEADERS, recovery_y["id"]))
    assert analyst_sibling["id"] == recovery_y["id"]
    _, analyst_meta = validate_paginated(api.list_supplier_recoveries(ANALYST_HEADERS))
    assert analyst_meta["total_count"] == 2


def test_a_supplier_rep_may_answer_the_claim_addressed_to_it(api):
    """The rep's single write lands, stores the note and leaves the valuation alone.

    PRD §3.7: "Responding is the one operation a `SupplierRep` may perform, and it moves the
    claim from `ASSERTED` to `NEGOTIATION`. The caller's `X-User-ID` must equal the claim's
    `supplier_id` ... The supplied `response_note` free text is stored as
    `supplier_response_note`, and `recognized_recovery_cents` is recomputed under the
    `EXPECTED_VALUE` variant." That variant weights a `HIGH` rating "at 9000 basis points",
    capped by the ceiling of "`annual_purchase_volume_cents` by its
    `contractual_recovery_cap_bps`, divide by 10000". PRD §4 grants the route to `SupplierRep`
    alone.

    Design: Corner/rbac/corner_supplier_rep_can_respond_to_its_own_asserted_recovery
    """
    supplier = create_supplier(
        api,
        supplier_code="SUP-OK",
        name="Cooperative Components",
        credit_rating="AAA",
        annual_purchase_volume_cents=500000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-OK",
        name="Cooperative Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=20000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-OK-01",
        description="Cooperative sensor defect",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier["id"],
    )
    recovery = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=1200000
    )
    assert_recovery(api, recovery["id"])

    note = "Acknowledged; root cause confirmed on lot 44."
    responded = success_data(
        api.respond_recovery(
            make_supplier_rep_headers(supplier["id"]), recovery["id"], response_note=note
        )
    )

    assert responded["status"] == "NEGOTIATION"
    assert responded["supplier_response_note"] == note
    assert responded["assert_count"] == 1
    assert responded["valuation_variant"] == "EXPECTED_VALUE"
    assert responded["collectability_rating_at_valuation"] == "HIGH"
    assert responded["recognized_recovery_cents"] == 1080000

    validate_error(
        api.respond_recovery(CONTROLLER_HEADERS, recovery["id"], response_note=note),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    assert read_recovery(api, recovery["id"])["supplier_response_note"] == note


def test_one_operator_cannot_both_propose_and_post_an_accrual(api):
    """Holding both hats does not buy the proposer a posting right.

    PRD §2.8: "Posting a warranty accrual is refused when the caller's `X-User-ID` equals the
    accrual's `proposed_by_user_id`", each such check "rejecting an equal comparison with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

    Design: Corner/rbac/corner_same_user_cannot_propose_and_post_one_accrual
    """
    dual_user = fresh_user_id()
    dual_analyst = make_warranty_analyst_headers(dual_user)
    dual_controller = make_reserve_controller_headers(dual_user)

    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog = _analog_basis(api)
    family, vintage = _blend_family(api, analog["id"], "FAM-SD", "Duties Platform")
    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
        headers=dual_analyst,
    )
    proposed = propose_accrual(api, accrual["id"], headers=dual_analyst)
    assert proposed["proposed_by_user_id"] == dual_user
    lock_period(api, period["id"])

    validate_error(
        api.post_accrual(dual_controller, accrual["id"]),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    blocked = read_accrual(api, accrual["id"])
    assert blocked["status"] == "PROPOSED"
    assert blocked["posted_by_user_id"] is None
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 0

    posted = post_accrual(api, accrual["id"])
    assert posted["status"] == "POSTED"
    assert posted["proposed_by_user_id"] == dual_user
    assert posted["posted_by_user_id"] == RESERVE_CONTROLLER_USER_ID
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 2910000


def test_one_operator_cannot_both_submit_and_decide_a_field_action(api):
    """Even a rejection is closed to the submitter of the campaign.

    PRD §2.8: "Deciding a field action — whether the decision is approval or rejection — is
    refused when the caller's `X-User-ID` equals the field action's `submitted_by_user_id`."
    PRD §3.5 prices the campaign: "multiply `labor_hours_centi` by the standard field labour
    rate of 9500 cents per hour ... divide by 100 ... Add `parts_cost_cents`, that per-unit
    labour cost, and `admin_cost_cents`", then "multiply the per-unit gross cost by
    `expected_take_rate_bps`, divide by 10000, and round to the nearest integer", and finally
    "the action's `specific_accrual_cents` is that stored, already-rounded
    `per_unit_expected_cents` multiplied by the action's `affected_unit_count`".

    Design: Corner/rbac/corner_same_user_cannot_submit_and_decide_one_field_action
    """
    both_user = fresh_user_id()
    both_engineer = make_quality_engineer_headers(both_user)
    both_controller = make_reserve_controller_headers(both_user)

    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-FSD",
        name="Field Duties Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-SD-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=500,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-SD-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api,
        action["id"],
        remedy_option_id=option["id"],
        expected_field_action_version=action["version"],
    )
    submitted = submit_field_action(api, action["id"], headers=both_engineer)
    assert submitted["submitted_by_user_id"] == both_user

    validate_error(
        api.decide_field_action(both_controller, action["id"], decision="REJECTED"),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    assert read_field_action(api, action["id"])["approval_state"] == "SUBMITTED"

    approved = decide_field_action(api, action["id"], "APPROVED")
    assert approved["approval_state"] == "APPROVED"
    assert approved["decided_by_user_id"] == RESERVE_CONTROLLER_USER_ID
    assert approved["approved_period_id"] == period["id"]
    assert approved["specific_accrual_cents"] == 5350000
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 5350000


def test_one_operator_cannot_both_review_and_book_a_liability_reserve(api):
    """The third pair keys on the reviewer recorded at the actuarial decision.

    PRD §2.8: "Booking a product-liability reserve is refused when the caller's `X-User-ID`
    equals the reserve's `reviewed_by_user_id`." PRD §3.8 says the `REVIEWED` decision "records
    the acting actuary's identifier as `reviewed_by_user_id`", and that booking "writes no
    figure of its own".

    Design: Corner/rbac/corner_same_user_cannot_review_and_book_one_liability_reserve
    """
    hats_user = fresh_user_id()
    hats_actuary = make_actuary_headers(hats_user)
    hats_controller = make_reserve_controller_headers(hats_user)

    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-HB",
        name="Two Hats Platform",
        launch_date="2023-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=18000,
        reserve_cap_cents=30000000,
    )
    create_vintage(
        api,
        family["id"],
        vintage_code="HB-MY2023",
        units_shipped=1000,
        ship_period_code="2023-Q1",
        warranty_expiry_date="2028-12-31",
    )
    reserve = create_liability_reserve(
        api,
        period["id"],
        family["id"],
        headers=hats_actuary,
        reported_claim_count=20,
        asserted_case_reserve_cents=2000000,
        reporting_lag_months=2,
        severity_trend_bps=0,
    )
    lock_period(api, period["id"])
    reviewed = actuarial_decision(api, reserve["id"], "REVIEWED", headers=hats_actuary)
    assert reviewed["reviewed_by_user_id"] == hats_user
    assert reviewed["total_liability_reserve_cents"] == 2500000
    open_review(api, period["id"])

    validate_error(
        api.book_liability_reserve(hats_controller, reserve["id"]),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    assert read_liability_reserve(api, reserve["id"])["status"] == "ACTUARY_REVIEWED"

    booked = book_liability_reserve(api, reserve["id"])
    assert booked["status"] == "BOOKED"
    assert booked["reviewed_by_user_id"] == hats_user
    assert booked["total_liability_reserve_cents"] == 2500000
