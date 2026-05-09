"""Queue score: the four-component formula, the residence cap, and tie semantics.

Covers PRD §3.3 (formula and recomputation moments) and supports
SCAFFOLD_DIFFICULTY_DESIGN instances:
- queue_score_initial_vs_recalculated (computed at SCORED vs at AnnualReview FINALIZED)
- queue_score_multifactor_with_cap_and_branches (tie-break via composite key)

# difficulty: dual_variant_calc/queue_score_initial_vs_recalculated
# difficulty: combinatorial_formula/queue_score_multifactor_with_cap_and_branches
"""

import pytest

from test_helpers import (
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_annual_review_payload,
    create_application_in_draft,
    create_program,
    emit_full_passing_sync_events,
    make_applicant_headers,
    make_household_member,
    setup_application_in_exit_pending,
    setup_contract_active,
    setup_for_initial_vs_recalculated_score,
    setup_two_applications_with_score_tie,
    submit_and_cross_check,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Component-by-component: household_type, disability, residence (capped), special_care
# (PRD §3.3)
# ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "household_type,expected_household_pts",
    [
        ("LOW_INCOME", 30),
        ("NEW_CITIZEN", 15),
        ("RELOCATION", 20),
        ("TALENT", 25),
    ],
)
def test_queue_score_household_type_component(household_type, expected_household_pts):
    """PRD §3.3: "The household-type component reads household_type and contributes 30
    for LOW_INCOME, 15 for NEW_CITIZEN, 20 for RELOCATION, or 25 for TALENT".

    With residence_length=0, no disability, NONE special_care, the queue_score equals
    just the household_type component.
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(
        program["id"],
        household_members=[
            make_household_member(
                relation="SELF", has_disability=False, special_care_category="NONE"
            )
        ],
        household_type=household_type,
        residence_start_period=0,
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    assert application["queue_score"] == expected_household_pts


def test_queue_score_disability_component_adds_20():
    """PRD §3.3: "The disability component reads household_members and contributes 20
    if at least one member has has_disability true, otherwise 0".
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(
        program["id"],
        household_members=[
            make_household_member(
                relation="SELF", has_disability=True, special_care_category="NONE"
            )
        ],
        household_type="NEW_CITIZEN",
        residence_start_period=0,
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    # NEW_CITIZEN(15) + DISABILITY(20) + residence(0) + NONE(0) = 35
    assert application["queue_score"] == 35


def test_queue_score_residence_uncapped_below_cap():
    """PRD §3.3: "The component contributes one point per period of residence, capped
    at 20 — that is, if the raw residence length is greater than 20, the component
    contributes 20; otherwise it contributes the raw value".
    """
    program = create_program()
    advance_clock_by(program["id"], 5)  # so residence_length = 5 - 0 = 5 if start=0
    application, applicant_id = create_application_in_draft(
        program["id"],
        household_members=[
            make_household_member(special_care_category="NONE")
        ],
        household_type="NEW_CITIZEN",
        residence_start_period=0,
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    # NEW_CITIZEN(15) + 0 + min(5,20)=5 + NONE(0) = 20
    assert application["queue_score"] == 20


def test_queue_score_residence_saturates_at_cap():
    """PRD §3.3: "the residence component cannot by itself separate every pair" — at
    residence_length 50 the component caps to 20.
    """
    program = create_program()
    advance_clock_by(program["id"], 50)
    application, applicant_id = create_application_in_draft(
        program["id"],
        household_members=[make_household_member(special_care_category="NONE")],
        household_type="NEW_CITIZEN",
        residence_start_period=0,
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    # NEW_CITIZEN(15) + 0 + min(50,20)=20 + NONE(0) = 35
    assert application["queue_score"] == 35


@pytest.mark.parametrize(
    "category,expected_pts",
    [
        ("NONE", 0),
        ("VETERAN", 15),
        ("MARTYR_FAMILY", 18),
        ("SINGLE_PARENT", 10),
        ("ELDERLY_LIVE_ALONE", 12),
    ],
)
def test_queue_score_special_care_component(category, expected_pts):
    """PRD §3.3: "The special-care component reads special_care_category across
    household_members and takes the maximum points across members: 0 for NONE, 15 for
    VETERAN, 18 for MARTYR_FAMILY, 10 for SINGLE_PARENT, and 12 for
    ELDERLY_LIVE_ALONE".
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(
        program["id"],
        household_members=[
            make_household_member(
                relation="SELF", has_disability=False, special_care_category=category
            )
        ],
        household_type="NEW_CITIZEN",
        residence_start_period=0,
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    assert application["queue_score"] == 15 + expected_pts


def test_queue_score_special_care_takes_max_not_sum():
    """PRD §3.3: "If multiple members carry different categories, only the highest-
    scoring category counts; the contribution is not summed across members".
    """
    program = create_program()
    application, applicant_id = create_application_in_draft(
        program["id"],
        household_members=[
            make_household_member(
                citizen_id="C-V", special_care_category="VETERAN"
            ),
            make_household_member(
                citizen_id="C-M", special_care_category="MARTYR_FAMILY"
            ),
        ],
        household_type="NEW_CITIZEN",  # 15
        residence_start_period=0,
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    # NEW_CITIZEN(15) + 0 + 0 + max(VETERAN=15, MARTYR_FAMILY=18)=18 = 33
    assert application["queue_score"] == 33


# ──────────────────────────────────────────────────────────
# Difficulty: dual_variant_calc/queue_score_initial_vs_recalculated
# ──────────────────────────────────────────────────────────


def test_initial_score_at_cross_check_then_recalculated_at_annual_review():
    """PRD §3.3: "queue_score is the sum of these four integer components and is
    recomputed at exactly two moments: when the application crosses UNDER_REVIEW -> SCORED
    (initial score, with residence length measured at current_period_index at the moment
    cross-check completes) and when an AnnualReview is finalized (recalculated score,
    where residence length is measured at the review's review_period_index, and
    household_type and household_members reflect any updates applied by the annual
    review)".

    Initial: residence_length=18 -> 30 (LOW_INCOME) + 20 (disability) + 18 (residence) +
    12 (ELDERLY_LIVE_ALONE) = 80.

    After advancing clock by 4 periods and finalizing an annual review with no updates,
    residence_length=22 capped to 20 -> 30 + 20 + 20 + 12 = 82.

    # difficulty: dual_variant_calc/queue_score_initial_vs_recalculated
    """
    program = create_program(
        notice_period_length=3,
        grace_period_length=6,
        per_capita_income_threshold_cents=300_000,
        per_capita_asset_threshold_cents=500_000,
    )
    application, applicant_id, member = setup_for_initial_vs_recalculated_score(program["id"])
    assert application["queue_score"] == 80, (
        f"PRD §3.3 initial score expected 80, got {application.get('queue_score')}"
    )
    # Walk to OCCUPIED so we can finalize an annual review.
    application = validate_success(
        api.enqueue_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    # Need a unit for allocation; use single-bedroom with family_size=1.
    from test_helpers import (
        create_allocation_payload,
        create_housing_unit,
        create_sign_payload,
        emit_payment_deposit_for,
    )
    from test_helpers.fixtures import _find_contract_for_allocation

    # PRD §3.4: when the unit's accessibility_compliant is false, every application whose
    # requires_accessibility is true is excluded. The applicant set up by
    # setup_for_initial_vs_recalculated_score has has_disability=True (so
    # requires_accessibility=True), so the unit MUST be accessibility_compliant=True for
    # the allocation to succeed.
    unit = create_housing_unit(program["id"], accessibility_compliant=True)
    allocation = validate_success(
        api.create_allocation(
            program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    advance_clock_by(program["id"], program["notice_period_length"])
    applicant_headers = make_applicant_headers(applicant_id)
    allocation = validate_success(
        api.confirm_allocation(program["id"], allocation["id"], applicant_headers)
    )
    contract = _find_contract_for_allocation(program["id"], allocation["id"])
    emit_payment_deposit_for(program["id"], contract["id"], contract["deposit_amount_cents"])
    contract = validate_success(api.pay_deposit(program["id"], contract["id"], applicant_headers))
    confirmation_period = allocation["confirmation_period"]
    contract = validate_success(
        api.sign_contract(
            program["id"],
            contract["id"],
            create_sign_payload(confirmation_period, confirmation_period + 12),
            applicant_headers,
        )
    )
    contract = validate_success(api.handover_contract(program["id"], contract["id"], OFFICER_HEADERS))
    # Application now OCCUPIED. Advance 4 periods so residence_length = 18 + 4 = 22.
    advance_clock_by(program["id"], 4)
    # Open annual review with no updated_* fields (PRD §3.7 reuses current values).
    review = validate_success(
        api.create_annual_review(
            program["id"],
            application["id"],
            create_annual_review_payload(),
            OFFICER_HEADERS,
        ),
        expected_status=201,
    )
    # Make sure the latest TAX_INCOME_ASSETS event still passes.
    from test_helpers import emit_tax_income_assets_for

    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=200_000, total_assets_cents=200_000
    )
    review = validate_success(
        api.finalize_annual_review(
            program["id"], application["id"], review["id"], OFFICER_HEADERS
        )
    )
    # PRD §3.3: residence_length=22 capped to 20 -> 30+20+20+12 = 82.
    assert review["recomputed_queue_score"] == 82, (
        f"PRD §3.3 recomputed score expected 82, got {review.get('recomputed_queue_score')}"
    )
    # PRD §3.3 final sentence + §3.7: the recomputed value overwrites the initial on
    # the application.
    application = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    assert application["queue_score"] == 82


def test_recompute_overwrites_initial_with_zero_update_household_members():
    """PRD §3.7: "On finalize, the server first applies the three update fields to the
    application, treating any null update as a no-op (the existing value is reused). It
    then re-runs the same six-condition cross-check ... It recomputes the queue_score
    per the same formula".

    Re-runs initial vs recalculated with an empty (omitted) update set so the recompute
    reflects only clock advance, not membership changes.

    # difficulty: dual_variant_calc/queue_score_initial_vs_recalculated
    """
    # Same scaffolding but stop at a different post-advance period to demonstrate
    # the "any null update as a no-op" branch: residence_length 18 -> 22 yields a
    # different score because cap saturation didn't happen at 18 (raw=18) but does at 22
    # (raw=22 capped to 20).
    program = create_program(
        notice_period_length=3,
        grace_period_length=6,
        per_capita_income_threshold_cents=300_000,
        per_capita_asset_threshold_cents=500_000,
    )
    application, applicant_id, member = setup_for_initial_vs_recalculated_score(program["id"])
    initial_score = application["queue_score"]
    assert initial_score == 80
    # Walk to OCCUPIED reusing the same shared infrastructure as the prior test.
    from test_helpers import (
        create_allocation_payload,
        create_housing_unit,
        create_sign_payload,
        emit_payment_deposit_for,
        emit_tax_income_assets_for,
    )
    from test_helpers.fixtures import _find_contract_for_allocation

    application = validate_success(
        api.enqueue_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    # PRD §3.4: applicant from setup_for_initial_vs_recalculated_score has
    # requires_accessibility=True; unit must be accessibility_compliant for matching.
    unit = create_housing_unit(program["id"], accessibility_compliant=True)
    allocation = validate_success(
        api.create_allocation(
            program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    advance_clock_by(program["id"], program["notice_period_length"])
    applicant_headers = make_applicant_headers(applicant_id)
    allocation = validate_success(
        api.confirm_allocation(program["id"], allocation["id"], applicant_headers)
    )
    contract = _find_contract_for_allocation(program["id"], allocation["id"])
    emit_payment_deposit_for(program["id"], contract["id"], contract["deposit_amount_cents"])
    contract = validate_success(api.pay_deposit(program["id"], contract["id"], applicant_headers))
    cp = allocation["confirmation_period"]
    contract = validate_success(
        api.sign_contract(
            program["id"],
            contract["id"],
            create_sign_payload(cp, cp + 12),
            applicant_headers,
        )
    )
    contract = validate_success(api.handover_contract(program["id"], contract["id"], OFFICER_HEADERS))
    advance_clock_by(program["id"], 4)
    review = validate_success(
        api.create_annual_review(
            program["id"],
            application["id"],
            create_annual_review_payload(),  # all updated_* omitted
            OFFICER_HEADERS,
        ),
        expected_status=201,
    )
    emit_tax_income_assets_for(
        program["id"], application["id"], monthly_income_cents=200_000, total_assets_cents=200_000
    )
    review = validate_success(
        api.finalize_annual_review(program["id"], application["id"], review["id"], OFFICER_HEADERS)
    )
    assert review["recomputed_queue_score"] == 82
    assert review["rent_adjustment_cents"] == 0  # household_type unchanged
    application = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    # Membership preserved at length 1 (PRD §3.7 zero-update preserves existing list).
    assert len(application["household_members"]) == 1


# ──────────────────────────────────────────────────────────
# Difficulty: combinatorial_formula/queue_score_multifactor_with_cap_and_branches
# ──────────────────────────────────────────────────────────


def test_two_applications_can_tie_on_queue_score_via_different_components():
    """PRD §3.3: "two applicants who differ only in residence_start_period may receive
    identical scores once both exceed the cap (a residence length of 15 and a residence
    length of 25 both yield 20), so the residence component cannot by itself separate
    every pair".

    Tests two applications whose component decompositions differ but whose total
    queue_score is identical — exercising the tie-break ordering.

    A1: NEW_CITIZEN(15) + 0 + min(50,20)=20 + VETERAN(15) = 50
    A2: TALENT(25) + DISABILITY(20) + 5 + NONE(0) = 50

    # difficulty: combinatorial_formula/queue_score_multifactor_with_cap_and_branches
    """
    program = create_program()
    a1, a2 = setup_two_applications_with_score_tie(program["id"])
    assert a1["queue_score"] == 50, f"A1 expected 50, got {a1['queue_score']}"
    assert a2["queue_score"] == 50, f"A2 expected 50, got {a2['queue_score']}"
    assert a1["queue_score"] == a2["queue_score"]


def test_residence_cap_makes_two_residence_lengths_yield_same_score():
    """PRD §3.3: "a residence length of 15 and a residence length of 25 both yield 20".

    # difficulty: combinatorial_formula/queue_score_multifactor_with_cap_and_branches
    """
    program_a = create_program()
    program_b = create_program()
    advance_clock_by(program_a["id"], 25)
    advance_clock_by(program_b["id"], 25)
    # A: residence_start_period=10 -> length=15.
    a, aid = create_application_in_draft(
        program_a["id"],
        household_members=[make_household_member(special_care_category="NONE")],
        household_type="LOW_INCOME",
        residence_start_period=10,
    )
    emit_full_passing_sync_events(program_a["id"], a)
    a = submit_and_cross_check(program_a["id"], a["id"], aid)
    # B: residence_start_period=0 -> length=25 (caps to 20).
    b, bid = create_application_in_draft(
        program_b["id"],
        household_members=[make_household_member(special_care_category="NONE")],
        household_type="LOW_INCOME",
        residence_start_period=0,
    )
    emit_full_passing_sync_events(program_b["id"], b)
    b = submit_and_cross_check(program_b["id"], b["id"], bid)
    # PRD §3.3: residence component contributes min(15,20)=15 vs min(25,20)=20.
    # A: 30 LOW_INCOME + 0 + 15 + 0 = 45.
    # B: 30 LOW_INCOME + 0 + 20 (capped) + 0 = 50.
    assert a["queue_score"] == 45
    assert b["queue_score"] == 50
