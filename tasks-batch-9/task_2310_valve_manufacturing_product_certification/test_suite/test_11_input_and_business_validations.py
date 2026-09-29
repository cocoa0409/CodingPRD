"""Validations: code uniqueness, chemistry limits, credit limits and pagination shape.

Uniqueness here is scoped to the live statuses rather than absolute, chemistry limits are
per material grade, and the credit check measures the frozen quote rather than the subtotal.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ErrorId,
    HeatLotStatus,
    ModelStatus,
    OrderStatus,
    assert_created,
    factories,
    fixtures,
    make_product_engineer_headers,
    make_quality_manager_headers,
)


# ─── Code uniqueness is scoped to the live statuses ───


def test_01_a_second_live_design_may_not_claim_the_same_model_code(api):
    """The uniqueness check runs at submission, so the duplicate is created but cannot be
    put into review while the incumbent is still live.

    PRD §3.1: "Submitting for review moves `DRAFT → IN_REVIEW` and is the
    `ProductEngineer`'s prerogative; it requires that `base_break_torque_nm` and
    `bore_size_mm` are both greater than zero, and that no other design sharing the same
    `model_code` currently sits in `DRAFT`, `IN_REVIEW` or `RELEASED` — a collision is
    `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/corner_duplicate_model_code_among_live_models_rejected
    """
    incumbent = fixtures.create_model(api, model_code="BV-300-DUP")
    fixtures.submit_model_for_review(api, incumbent["id"])
    challenger = assert_created(
        api.create_valve_model(
            factories.valve_model_payload(
                "BV-300-DUP", "BALL", 300, "CF8M", 100, "METAL", 430.0
            ),
            make_product_engineer_headers(),
        )
    )
    assert challenger["status"] == ModelStatus.DRAFT

    response = api.valve_model_action(
        challenger["id"],
        factories.model_action_payload("SUBMIT_REVIEW"),
        make_product_engineer_headers(),
    )

    validate_error(response, ErrorId.DUPLICATE_CODE, 409)
    assert fixtures.read_model(api, incumbent["id"])["status"] == ModelStatus.IN_REVIEW
    assert fixtures.read_model(api, challenger["id"])["status"] == ModelStatus.DRAFT


def test_02_a_withdrawn_line_releases_its_code_for_reuse(api):
    """Once the incumbent has left the three live statuses the same code may be claimed
    again and taken all the way into review.

    PRD §3.1: "Code uniqueness is scoped to those three statuses precisely so that a
    withdrawn or superseded line can have its code reused." PRD §3.1: "Withdrawal is the other
    exit from `RELEASED`, also a `QualityManager` decision, moving `RELEASED → WITHDRAWN`."

    Design: Corner/validations/corner_model_code_reusable_after_withdrawal
    """
    incumbent = fixtures.create_released_model(api, model_code="BV-300-REUSE")
    withdrawn = fixtures.model_action(api, incumbent["id"], "WITHDRAW")
    assert withdrawn["status"] == ModelStatus.WITHDRAWN

    successor = assert_created(
        api.create_valve_model(
            factories.valve_model_payload(
                "BV-300-REUSE", "BALL", 300, "CF8M", 100, "METAL", 440.0
            ),
            make_product_engineer_headers(),
        )
    )
    submitted = fixtures.submit_model_for_review(api, successor["id"])

    assert successor["model_code"] == "BV-300-REUSE"
    assert float(successor["base_break_torque_nm"]) == 440.0
    assert submitted["status"] == ModelStatus.IN_REVIEW


# ─── Business limits on the material and the money ───


def test_03_a_lot_above_its_grade_s_carbon_ceiling_fails_verification(api):
    """A CF8M lot reported at 0.44 is over the 0.40 ceiling for that grade, so the chemistry
    gate refuses it and the lot stays unverified.

    PRD §3.2: "Verification is the chemistry gate: `carbon_equivalent_pct` must be at or
    below the ceiling for the lot's `material_grade` — 0.45 for `WCB`, 0.43 for `LCC`, 0.48 for
    `A105`, 0.40 for `CF8M`, 0.40 for `F316` — and `impact_energy_j` must be at or above the
    floor for that grade — 20 joules for `WCB`, 27 for `LCC`, 20 for `A105`, 34 for `CF8M`, 34
    for `F316`." PRD §3.2: "A successful verification records `verified_by_user_id` from
    `X-User-ID`."

    Design: Corner/validations/corner_lot_verify_blocked_by_out_of_spec_chemistry
    """
    foundry = fixtures.create_foundry(
        api, foundry_code="FDY-C11", name="Corner Chemistry Castings", country_code="IN"
    )
    lot = fixtures.create_heat_lot(
        api,
        foundry["id"],
        heat_number="H-C1101",
        material_grade="CF8M",
        mtr_document_ref="MTR-C1101",
        carbon_equivalent_pct=0.44,
        impact_energy_j=40,
    )

    response = api.heat_lot_disposition(
        lot["id"],
        factories.lot_disposition_payload("VERIFY"),
        make_quality_manager_headers(),
    )

    validate_error(response, ErrorId.MTR_CHEMISTRY_OUT_OF_SPEC, 422)
    unchanged = fixtures.read_lot(api, lot["id"])
    assert unchanged["status"] == HeatLotStatus.RECEIVED
    assert unchanged["verified_by_user_id"] is None
    assert fixtures.read_foundry(api, foundry["id"])["rejected_lot_count"] == 0


def test_04_release_to_production_measures_the_quote_against_the_credit_limit(api):
    """The gross quote after the volume discount is still above the customer's limit, so
    production is refused and the order stays approved.

    PRD §3.8: "It requires `spec_stale` to be false, otherwise `ERR_PINNED_SPEC_STALE` — an
    order pinned to a revision the design has since moved past cannot be released until it is
    re-approved — and it requires `gross_quoted_cents` to be at or below
    `customer_credit_limit_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)." PRD §3.8:
    "a pre-discount amount of 6,000,000 cents or more earns 0.06, an amount from 2,000,000 up
    to but not including 6,000,000 earns 0.03, and anything below 2,000,000 earns nothing."

    Design: Corner/validations/corner_order_release_blocked_when_gross_exceeds_credit_limit
    """
    model = fixtures.create_released_model(api, model_code="BV-300-CREDIT")
    order = fixtures.create_order(
        api,
        model["id"],
        order_code="ETO-C11",
        ordered_qty=4,
        unit_price_cents=1_500_000,
        customer_credit_limit_cents=5_000_000,
    )
    approved = fixtures.approve_order(api, order["id"])
    # Four valves at 1,500,000 make a 6,000,000 pre-discount amount, which takes the 0.06
    # tier and leaves a gross of 5,640,000 against a 5,000,000 limit.
    assert approved["gross_quoted_cents"] == 5_640_000

    response = api.engineered_order_lifecycle_action(
        order["id"],
        factories.lifecycle_action_payload("RELEASE_TO_PRODUCTION"),
        make_product_engineer_headers(),
    )

    validate_error(response, ErrorId.CREDIT_LIMIT_EXCEEDED, 402)
    assert fixtures.read_order(api, order["id"])["status"] == OrderStatus.APPROVED


# ─── Pagination shape ───


def test_05_a_limit_above_one_hundred_is_refused(api):
    """The limit ceiling is part of the request contract, so asking for five hundred rows
    is rejected rather than silently capped.

    PRD §2.3: "A `limit` outside the inclusive range from 1 to 100, a negative `offset`, or
    a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/corner_list_with_limit_above_hundred_rejected
    """
    fixtures.create_model(api, model_code="BV-300-PAGE")

    response = api.list_valve_models(make_quality_manager_headers(), params={"limit": 500})

    validate_error(response, ErrorId.INVALID_PAGINATION, 400)
