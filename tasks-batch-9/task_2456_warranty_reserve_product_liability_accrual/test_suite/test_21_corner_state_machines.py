"""State-machine coverage: valid walks, initial states, terminal lockdowns and guards.

PRD §2.9 rung 12: "The target row occupies a state from which the requested transition is
declared, which includes every cross-entity state precondition and every terminal-state
lockdown — guarding every state-transition endpoint — otherwise
`ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
"""

from test_helpers import (
    ACTUARY_HEADERS,
    ACTUARY_USER_ID,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    ERR_INVALID_STATE_TRANSITION,
    ERR_ROLLFORWARD_MISSING,
    RESERVE_CONTROLLER_USER_ID,
    WARRANTY_ANALYST_USER_ID,
    actuarial_decision,
    assert_rollforward_identity,
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
    create_service_contract,
    create_supplier,
    create_vintage,
    decide_field_action,
    generate_rollforward,
    lock_period,
    make_supplier_rep_headers,
    move_clock,
    open_review,
    patch_family,
    post_accrual,
    propose_accrual,
    read_accrual,
    read_family,
    read_field_action,
    read_liability_reserve,
    read_period,
    read_recovery,
    read_service_contract,
    read_supplier,
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


def _remedy_options(api, field_action_id):
    """The candidate options of one action, where `per_unit_expected_cents` is stored."""
    return validate_paginated(api.list_remedy_options(ENGINEER_HEADERS, field_action_id))


def test_a_period_walks_open_locked_review_and_closed(api):
    """The four-state calendar cycle runs end to end on an empty period.

    PRD §3.1: "Locking analysis moves it from `OPEN` to `ANALYSIS_LOCKED` ... stamps
    `locked_at` with the current logical-clock instant", "Opening actuarial review moves it
    from `ANALYSIS_LOCKED` to `ACTUARIAL_REVIEW`", and "Closing the period moves it from
    `ACTUARIAL_REVIEW` to `CLOSED`, stamps `closed_at` with the current logical-clock
    instant". PRD §3.1 also fixes the birth state — "a `reopen_count` of 0 ... and a null
    `locked_at` and `closed_at`" — and the disclosure counter: "`rollforward_generated` is
    true exactly when at least one rollforward snapshot names this period."

    Design: Corner/state_machines/corner_period_walks_open_locked_review_closed
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    assert period["status"] == "OPEN"
    assert period["locked_at"] is None
    assert period["closed_at"] is None

    locked = lock_period(api, period["id"])
    assert locked["status"] == "ANALYSIS_LOCKED"
    assert locked["locked_at"] is not None

    rollforward = generate_rollforward(api, period["id"])

    in_review = open_review(api, period["id"])
    assert in_review["status"] == "ACTUARIAL_REVIEW"

    closed = success_data(api.close_period(CONTROLLER_HEADERS, period["id"]))
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None
    assert closed["reopen_count"] == 0
    assert closed["rollforward_generated"] is True

    assert rollforward["beginning_balance_cents"] == 0
    assert rollforward["ending_balance_cents"] == 0
    assert_rollforward_identity(rollforward)


def test_closing_a_period_with_no_rollforward_snapshot_is_refused(api):
    """The disclosure snapshot is a hard precondition for the close.

    PRD §3.1: "The period's `rollforward_generated` flag must already be true, meaning at
    least one rollforward disclosure snapshot exists for the period; otherwise the close is
    refused with `ERR_ROLLFORWARD_MISSING`." PRD §2.9 rung 14 fixes the status: "The
    period's `rollforward_generated` is already true — guarding
    `POST /warranty/periods/{periodId}/close` — otherwise `ERR_ROLLFORWARD_MISSING`
    (HTTP 409)."

    Design: Corner/state_machines/corner_period_close_without_rollforward_returns_rollforward_missing
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    lock_period(api, period["id"])
    open_review(api, period["id"])

    response = api.close_period(CONTROLLER_HEADERS, period["id"])
    validate_error(response, ERR_ROLLFORWARD_MISSING, expected_status=409)

    unchanged = read_period(api, period["id"])
    assert unchanged["status"] == "ACTUARIAL_REVIEW"
    assert unchanged["closed_at"] is None
    assert unchanged["rollforward_generated"] is False


def test_reopening_analysis_returns_only_the_reviewed_reserve_to_draft(api):
    """The reopen cascade is conditional on each reserve's own state.

    PRD §3.1: "Reopening analysis moves the period from `ACTUARIAL_REVIEW` back to
    `ANALYSIS_LOCKED`, adds 1 to `reopen_count` ... Every product-liability reserve of that
    period sitting in `ACTUARY_REVIEWED` is returned to `DRAFT`, has 1 added to its
    `return_count`, and has its `reviewed_by_user_id` cleared to null. This cascade is
    conditional and narrow: reserves already in `BOOKED` are untouched, and reserves already
    in `DRAFT` are untouched."

    Design: Corner/state_machines/corner_reopen_returns_only_reviewed_liability_reserves_to_draft
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family_one = create_family(
        api,
        family_code="FAM-L1",
        name="Liability Family One",
        launch_date="2023-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=60000000,
    )
    create_vintage(
        api,
        family_one["id"],
        vintage_code="L1-MY2023",
        units_shipped=2000,
        ship_period_code="2023-Q1",
        warranty_expiry_date="2028-12-31",
    )
    family_two = create_family(
        api,
        family_code="FAM-L2",
        name="Liability Family Two",
        launch_date="2023-06-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=40000000,
    )
    reviewed_reserve = create_liability_reserve(
        api,
        period["id"],
        family_one["id"],
        reported_claim_count=40,
        asserted_case_reserve_cents=8000000,
        reporting_lag_months=6,
        severity_trend_bps=1000,
    )
    draft_reserve = create_liability_reserve(
        api,
        period["id"],
        family_two["id"],
        reported_claim_count=10,
        asserted_case_reserve_cents=1000000,
        reporting_lag_months=0,
        severity_trend_bps=0,
    )
    lock_period(api, period["id"])
    actuarial_decision(api, reviewed_reserve["id"], "REVIEWED")
    open_review(api, period["id"])

    reopened = success_data(api.reopen_analysis(CONTROLLER_HEADERS, period["id"]))
    assert reopened["status"] == "ANALYSIS_LOCKED"
    assert reopened["reopen_count"] == 1

    returned = read_liability_reserve(api, reviewed_reserve["id"])
    assert returned["status"] == "DRAFT"
    assert returned["reviewed_by_user_id"] is None
    assert returned["return_count"] == 1
    assert returned["lag_factor_bps"] == 6000
    assert returned["ibnr_claim_count"] == 24
    assert returned["ibnr_reserve_cents"] == 5280000
    assert returned["total_liability_reserve_cents"] == 13280000

    untouched = read_liability_reserve(api, draft_reserve["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["return_count"] == 0
    assert untouched["lag_factor_bps"] == 0
    assert untouched["ibnr_claim_count"] == 0
    assert untouched["ibnr_reserve_cents"] == 0
    assert untouched["total_liability_reserve_cents"] == 1000000


def test_reproposing_a_posted_accrual_is_refused(api):
    """`POSTED` is not a source state for the propose trigger.

    PRD §3.3: "Proposing it advances `DRAFT` to `PROPOSED`" — the only declared source
    state. PRD §2.9 rung 12: "The target row occupies a state from which the requested
    transition is declared ... otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/corner_propose_on_posted_accrual_returns_invalid_state
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api)
    family = create_family(
        api,
        family_code="FAM-P1",
        name="Posted Accrual Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=20000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="P1-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-P1-01",
        description="Posted platform valve leak",
        severity="FUNCTIONAL",
        cost_per_claim_cents=21000,
    )
    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
    )
    propose_accrual(api, accrual["id"])
    lock_period(api, period["id"])
    post_accrual(api, accrual["id"])

    response = api.propose_accrual(ANALYST_HEADERS, accrual["id"])
    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    unchanged = read_accrual(api, accrual["id"])
    assert unchanged["status"] == "POSTED"
    assert unchanged["revision_index"] == 0
    assert unchanged["proposed_by_user_id"] == WARRANTY_ANALYST_USER_ID
    assert unchanged["posted_by_user_id"] == RESERVE_CONTROLLER_USER_ID
    assert unchanged["accrued_amount_cents"] == 2910000
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 2910000


def test_a_new_field_action_starts_on_both_dimensions_at_once(api):
    """Approval and execution each begin at their own declared initial state.

    PRD §3.5: "A new action starts with `approval_state` of `DRAFT`, `execution_state` of
    `NOT_STARTED`, a null `selected_remedy_option_id`, a `specific_accrual_cents` of 0, an
    `executed_cost_cents` of 0, a null `approved_period_id`, and null `submitted_by_user_id`
    and `decided_by_user_id`." PRD §3.5 also derives the safety flag: "The system derives
    `is_safety_recall` as true exactly when `action_type` is `SAFETY_RECALL`".

    Design: Corner/state_machines/corner_field_action_created_in_draft_and_not_started
    """
    family = create_family(
        api,
        family_code="FAM-IS",
        name="Initial State Platform",
        launch_date="2024-05-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=11000,
        reserve_cap_cents=15000000,
    )

    action = create_field_action(
        api,
        family["id"],
        action_code="FA-IS-01",
        action_type="SAFETY_RECALL",
        affected_build_start_date="2025-03-01",
        affected_build_end_date="2025-04-30",
        affected_unit_count=800,
        regulatory_notice_filed=True,
    )

    assert action["approval_state"] == "DRAFT"
    assert action["execution_state"] == "NOT_STARTED"
    assert action["is_safety_recall"] is True
    assert action["regulatory_notice_filed"] is True
    assert action["selected_remedy_option_id"] is None
    assert action["specific_accrual_cents"] == 0
    assert action["executed_cost_cents"] == 0
    assert action["approved_period_id"] is None
    assert action["submitted_by_user_id"] is None
    assert action["decided_by_user_id"] is None
    assert action["version"] == 1


def test_a_second_decision_on_an_approved_field_action_is_refused(api):
    """`APPROVED` is terminal on the approval dimension.

    PRD §3.5: "the approval advances the action to `APPROVED`, which is terminal on the
    approval dimension". PRD §2.9 rung 12 covers "every terminal-state lockdown — guarding
    every state-transition endpoint — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)".
    PRD §3.5 pins the accrual the approval wrote: "the action's `specific_accrual_cents` is
    that stored, already-rounded `per_unit_expected_cents` multiplied by the action's
    `affected_unit_count`."

    Design: Corner/state_machines/corner_second_decision_on_approved_field_action_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-TL",
        name="Terminal Lock Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=30000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-TL-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
        affected_unit_count=1000,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-TL-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=2000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])
    approved = decide_field_action(api, action["id"], "APPROVED")
    assert approved["approval_state"] == "APPROVED"

    response = api.decide_field_action(CONTROLLER_HEADERS, action["id"], decision="REJECTED")
    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    unchanged = read_field_action(api, action["id"])
    assert unchanged["approval_state"] == "APPROVED"
    assert unchanged["approved_period_id"] == period["id"]
    assert unchanged["decided_by_user_id"] == RESERVE_CONTROLLER_USER_ID
    assert unchanged["specific_accrual_cents"] == 12000000

    options, _ = _remedy_options(api, action["id"])
    assert options[0]["per_unit_expected_cents"] == 12000

    family_now = read_family(api, family["id"])
    assert family_now["warranty_reserve_balance_cents"] == 12000000
    assert family_now["reserve_posture"] == "NORMAL"


def test_reselecting_a_remedy_loops_a_rejected_action_back_to_draft(api):
    """The rejected action re-enters `DRAFT` with its attribution cleared.

    PRD §3.5: "From `REJECTED` the action returns to `DRAFT` for re-work, and in that case
    `submitted_by_user_id` and `decided_by_user_id` are both cleared to null so that the
    segregation-of-duties comparison starts clean on the next round." The same paragraph
    adds that "A successful selection writes `selected_remedy_option_id`, recomputes the
    selected option's `per_unit_expected_cents` and the action's `specific_accrual_cents`,
    and advances the action's `version` by 1", restoring the figure the rejection had
    forced "back to 0".

    Design: Corner/state_machines/corner_rejected_field_action_loops_back_to_draft_on_reselect
    """
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-CY",
        name="Cyclic Platform",
        launch_date="2024-02-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=13000,
        reserve_cap_cents=40000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-CY-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-02-28",
        affected_unit_count=1500,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-CY-1",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=4000,
        labor_hours_centi=150,
        admin_cost_cents=600,
        expected_take_rate_bps=5000,
        is_engineering_approved=True,
    )
    selected = select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    assert selected["specific_accrual_cents"] == 14137500
    submit_field_action(api, action["id"])
    rejected = decide_field_action(api, action["id"], "REJECTED")
    assert rejected["approval_state"] == "REJECTED"
    assert rejected["specific_accrual_cents"] == 0

    looped = select_remedy(
        api,
        action["id"],
        remedy_option_id=option["id"],
        expected_field_action_version=rejected["version"],
    )

    assert looped["approval_state"] == "DRAFT"
    assert looped["submitted_by_user_id"] is None
    assert looped["decided_by_user_id"] is None
    assert looped["specific_accrual_cents"] == 14137500
    assert looped["version"] == rejected["version"] + 1

    options, _ = _remedy_options(api, action["id"])
    assert options[0]["per_unit_expected_cents"] == 9425


def test_booking_a_reserve_requires_its_period_in_actuarial_review(api):
    """The book transition carries a cross-entity state precondition.

    PRD §3.8: "Booking is a `ReserveController` capability. It advances `ACTUARY_REVIEWED`
    to `BOOKED`, which is terminal, and requires the scoping period to be precisely in
    `ACTUARIAL_REVIEW` — anything else answers `ERR_INVALID_STATE_TRANSITION`." PRD §3.8
    also pins the arithmetic: "`lag_factor_bps` translates reporting lag into an IBNR
    frequency uplift: multiply `reporting_lag_months` by 1200 basis points per month ... and
    take the lesser of that product and a hard ceiling of 6000 basis points."

    Design: Corner/state_machines/corner_liability_reserve_book_requires_period_in_actuarial_review
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-GT",
        name="Guarded Transition Platform",
        launch_date="2023-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=18000,
        reserve_cap_cents=30000000,
    )
    create_vintage(
        api,
        family["id"],
        vintage_code="GT-MY2023",
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
    actuarial_decision(api, reserve["id"], "REVIEWED")

    too_early = api.book_liability_reserve(CONTROLLER_HEADERS, reserve["id"])
    validate_error(too_early, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    still_reviewed = read_liability_reserve(api, reserve["id"])
    assert still_reviewed["status"] == "ACTUARY_REVIEWED"
    assert still_reviewed["reviewed_by_user_id"] == ACTUARY_USER_ID

    open_review(api, period["id"])
    booked = book_liability_reserve(api, reserve["id"])

    assert booked["status"] == "BOOKED"
    assert booked["reviewed_by_user_id"] == ACTUARY_USER_ID
    assert booked["return_count"] == 0
    assert booked["lag_factor_bps"] == 2400
    assert booked["ibnr_claim_count"] == 5
    assert booked["ibnr_reserve_cents"] == 500000
    assert booked["total_liability_reserve_cents"] == 2500000


def test_a_service_contract_auto_expires_when_the_clock_passes_its_term(api):
    """The `ACTIVE` to `EXPIRED` transition is driven by the logical clock alone.

    PRD §2.5: "any such contract whose recomputed `months_elapsed` has reached or passed its
    `term_months` auto-transitions from `ACTIVE` to `EXPIRED`." PRD §3.6 gives the curve:
    "1000 basis points when the elapsed fraction is 2500 basis points or less, 3000 basis
    points when it is 5000 or less, 6000 basis points when it is 7500 or less, and 10000
    basis points otherwise."

    Design: Corner/state_machines/corner_service_contract_auto_expires_when_clock_passes_term
    """
    family = create_family(
        api,
        family_code="FAM-SC",
        name="Service Contract Platform",
        launch_date="2024-01-01",
        base_warranty_months=12,
        standard_cost_per_claim_cents=9000,
        reserve_cap_cents=15000000,
    )
    contract = create_service_contract(
        api,
        family["id"],
        contract_number="SC-EXP-1",
        sold_date="2026-03-01",
        term_months=12,
        total_contract_price_cents=360000,
        recognition_method="CLAIMS_PATTERN",
    )

    assert contract["status"] == "ACTIVE"
    assert contract["months_elapsed"] == 5
    assert contract["recognized_revenue_cents"] == 108000
    assert contract["deferred_revenue_cents"] == 252000

    move_clock(api, "2027-04-01T00:00:00Z")

    expired = read_service_contract(api, contract["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["months_elapsed"] == 12
    assert expired["recognized_revenue_cents"] == 360000
    assert expired["deferred_revenue_cents"] == 0
    assert expired["refunded_revenue_cents"] == 0


def test_a_settled_recovery_refuses_the_supplier_response(api):
    """`SETTLED` is terminal, so the in-scope supplier still cannot respond.

    PRD §3.7: "Both outcomes are legal from `ASSERTED` and from `NEGOTIATION`, and both land
    in a terminal state from which nothing further is possible", and "Responding is the one
    operation a `SupplierRep` may perform, and it moves the claim from `ASSERTED` to
    `NEGOTIATION`." PRD §2.9 rung 12 lists "`SETTLED` and `WRITTEN_OFF` on a supplier
    recovery" among the terminal-state lockdowns answering `ERR_INVALID_STATE_TRANSITION`.

    Design: Corner/state_machines/corner_settled_recovery_blocks_supplier_response
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    supplier = create_supplier(
        api,
        supplier_code="SUP-TS",
        name="Terminal Supplier AB",
        credit_rating="AAA",
        annual_purchase_volume_cents=1000000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-TS",
        name="Terminal Supplier Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=20000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-TS-01",
        description="Sourced relay failure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier["id"],
    )
    recovery = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=4000000
    )
    asserted = success_data(api.assert_recovery(ANALYST_HEADERS, recovery["id"]))
    assert asserted["status"] == "ASSERTED"
    assert asserted["collectability_rating_at_valuation"] == "HIGH"
    assert asserted["recognized_recovery_cents"] == 3600000

    settled = success_data(
        api.close_recovery(
            CONTROLLER_HEADERS, recovery["id"], outcome="SETTLED", settled_amount_cents=3000000
        )
    )
    assert settled["status"] == "SETTLED"
    assert settled["settled_amount_cents"] == 3000000
    assert settled["recognized_recovery_cents"] == 3000000
    assert settled["settled_period_id"] == period["id"]

    response = api.respond_recovery(
        make_supplier_rep_headers(supplier["id"]),
        recovery["id"],
        response_note="We dispute the settled amount.",
    )
    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    unchanged = read_recovery(api, recovery["id"])
    assert unchanged["status"] == "SETTLED"
    assert unchanged["supplier_response_note"] is None

    supplier_now = read_supplier(api, supplier["id"])
    assert supplier_now["realization_bps"] == 10000
    assert supplier_now["collectability_rating"] == "HIGH"


def test_posting_a_second_accrual_supersedes_the_first(api):
    """Only the surviving accrual counts toward the family balance.

    PRD §3.3: "Every *other* accrual for the same period-and-cohort pair that was sitting in
    `POSTED` transitions to `SUPERSEDED`, which is terminal ... Because the superseded row's
    `accrued_amount_cents` thereby drops out of the posted-accrual filter while the new row's
    enters it, the family reserve balance moves by exactly the difference between the new and
    the old accrued amounts." PRD §3.3 also permits the second create: "note that a prior
    accrual in `POSTED` or `SUPERSEDED` does *not* block a new one".

    Design: Corner/state_machines/corner_posting_a_second_accrual_supersedes_the_first
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog_family = _analog_basis(api)
    family = create_family(
        api,
        family_code="FAM-SP",
        name="Supersede Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=20000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="SP-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-SP-01",
        description="Supersede platform seal leak",
        severity="FUNCTIONAL",
        cost_per_claim_cents=22000,
    )
    first = create_accrual(
        api, period["id"], vintage["id"], method="ANALOG_BLEND", elapsed_exposure_bps=2000
    )
    propose_accrual(api, first["id"])
    lock_period(api, period["id"])
    post_accrual(api, first["id"])

    assert read_accrual(api, first["id"])["status"] == "POSTED"
    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 2910000

    patch_family(api, family["id"], {"standard_cost_per_claim_cents": 40000})
    second = create_accrual(
        api, period["id"], vintage["id"], method="ANALOG_BLEND", elapsed_exposure_bps=2000
    )
    propose_accrual(api, second["id"])

    posted = post_accrual(api, second["id"])
    assert posted["status"] == "POSTED"
    assert posted["accrued_amount_cents"] == 3880000

    assert read_accrual(api, first["id"])["status"] == "SUPERSEDED"

    family_now = read_family(api, family["id"])
    assert family_now["warranty_reserve_balance_cents"] == 3880000
    assert family_now["reserve_posture"] == "NORMAL"
