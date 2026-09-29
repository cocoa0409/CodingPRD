"""Optimistic concurrency on the two quoting creations, and immediate consistency.

Two creations quote a parent row the client has already read, and each states the
version it quoted. Both guards sit at the same rung of the ladder, above the
business gates behind them, so a client with a superseded row learns that its
quote is out of date before it learns that the product was pulled or that the
account went on hold. And because both creations mutate the very row they quoted,
a token that has just succeeded is already spent.

The rest of the file pins the consistency model: every derived figure is visible
in the response of the request that wrote it, with no read-after-write lag.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_units_conserved,
    assert_credit_conserved,
    assert_customer,
    assert_no_row_with_code,
    assert_powder_blend_batch,
    assert_qualification_dossier,
    assert_recondition_job,
    assert_tool_order,
    assert_tool_product,
)
from test_helpers.constants import INDEPENDENT_APPROVER
from test_helpers.fixtures import (
    APP,
    APPROVER,
    GEO,
    MET,
    OPERATOR_ONE,
    OPERATOR_TWO,
    PLAN,
    SUBMITTER,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

BUYING_ACCOUNT = {
    "customer_code": "CU-C",
    "name": "Nu Machining",
    "tier": "STANDARD",
    "regrind_credit_cents": 0,
}
REGRIND_ACCOUNT = {
    "customer_code": "CU-D",
    "name": "Xi Regrind",
    "tier": "STANDARD",
}


# ─── The product version an order quotes ─────────────────────────────────────

def test_a_supply_move_invalidates_the_quote_the_client_was_holding(api):
    """The posture change bumps the row, and the held token no longer matches.

    PRD §2.10: "Creating a tool order requires `expected_product_version` as a
    non-optional field of the request body, carrying the client's last observed
    `version` of the referenced `ToolProduct`. If that value does not equal the
    product's current `version`, the creation is rejected with
    `ERR_STALE_PRODUCT_VERSION` and HTTP 412."

    PRD §3.5: "Every supply move advances the product's `version` by 1, and none
    of them touches `release_status`."

    Design: Corner/cross_cutting_complexity_layers/order_create_pins_the_quoted_product_version
    """
    state = fx.released_product_with_customer(
        api, coated=False, customer_overrides=BUYING_ACCOUNT
    )
    product_id = state["product"]["id"]
    quoted = fx.current_product_version(api, product_id)

    moved = validate_success(
        api.set_product_supply_status(
            product_id, f.set_supply_status_payload("MAKE_TO_ORDER"), PLAN
        )
    )
    response = api.create_tool_order(
        f.tool_order_payload(state["customer"]["id"], product_id, quoted), APP
    )

    assert moved["supply_status"] == "MAKE_TO_ORDER", (
        f"a stocked catalogue insert may fall back to order-only, got {moved['supply_status']}"
    )
    assert moved["release_status"] == "RELEASED", (
        f"the supply move does not touch the release dimension, got {moved['release_status']}"
    )
    assert moved["version"] == quoted + 1, (
        f"the supply move advances the version once, got {moved['version']} against {quoted}"
    )
    validate_error(response, ApiErrorId.ERR_STALE_PRODUCT_VERSION, 412)
    rows, meta = validate_paginated(api.list_tool_orders(APP))
    assert meta["total_count"] == 0, (
        f"the refused quote created no order, got {meta['total_count']}"
    )
    assert_no_row_with_code(rows, "order_code", "SO-1")


def test_the_token_that_just_bought_one_order_is_stale_for_the_next(api):
    """Creation pins the product row, so the same version cannot be quoted twice.

    PRD §3.8: "The order opens at `status` `DRAFT` with `requires_reconfirmation`
    false, and the product's `version` advances by 1 because the quoted product
    row is now pinned by an order."

    PRD §2.10: "Note that raising a second order against the same product is
    entirely legitimate in its own right, which is exactly why this conflict is
    settled by a version comparison rather than by a state precondition."

    Design: Corner/cross_cutting_complexity_layers/order_create_pins_the_quoted_product_version
    """
    state = fx.released_product_with_customer(
        api, coated=False, customer_overrides=BUYING_ACCOUNT
    )
    product_id = state["product"]["id"]
    customer_id = state["customer"]["id"]
    quoted = fx.current_product_version(api, product_id)

    first = validate_success(
        api.create_tool_order(
            f.tool_order_payload(customer_id, product_id, quoted), APP
        ),
        201,
    )
    repeat = api.create_tool_order(
        f.tool_order_payload(customer_id, product_id, quoted, order_code="SO-2"), APP
    )

    assert_tool_order(first)
    assert first["status"] == "DRAFT", (
        f"an order opens unpriced in draft, got {first['status']}"
    )
    assert first["requires_reconfirmation"] is False, (
        f"nothing has pushed the order back yet, got {first['requires_reconfirmation']}"
    )
    assert first["order_class"] == "CATALOG", (
        f"the class is copied from the product, got {first['order_class']}"
    )
    product = validate_success(api.get_tool_product(product_id, APP))
    assert product["version"] == quoted + 1, (
        "the creation itself pinned the product row and advanced it once, got "
        f"{product['version']} against {quoted}"
    )
    validate_error(repeat, ApiErrorId.ERR_STALE_PRODUCT_VERSION, 412)
    rows, meta = validate_paginated(api.list_tool_orders(APP))
    assert meta["total_count"] == 1, (
        f"only the first order survives, got {meta['total_count']}"
    )
    assert_no_row_with_code(rows, "order_code", "SO-2")


def test_the_stale_token_is_reported_before_the_product_is_found_unorderable(api):
    """Priority 10 answers first; only a fresh token reaches the priority-17 gate.

    PRD §2.11: "10. **Parent version currency.** → `ERR_STALE_PRODUCT_VERSION`
    on order creation and `ERR_STALE_CUSTOMER_VERSION` on reconditioning-job
    intake, per §2.10."

    PRD §2.11: "17. **Product orderable.** → `ERR_PRODUCT_NOT_ORDERABLE`, on
    order creation, order submission and order confirmation."

    PRD §3.8: "The product must be orderable — an order against a product whose
    `release_status` is `RESTRICTED` or `WITHDRAWN`, or whose `supply_status` is
    `UNAVAILABLE`, is rejected with `ERR_PRODUCT_NOT_ORDERABLE`"

    Design: Corner/cross_cutting_complexity_layers/order_create_pins_the_quoted_product_version
    """
    state = fx.released_product_with_customer(
        api, coated=False, customer_overrides=BUYING_ACCOUNT
    )
    product_id = state["product"]["id"]
    customer_id = state["customer"]["id"]
    quoted = fx.current_product_version(api, product_id)

    pulled = validate_success(
        api.set_product_supply_status(
            product_id, f.set_supply_status_payload("UNAVAILABLE"), PLAN
        )
    )
    assert pulled["supply_status"] == "UNAVAILABLE", (
        f"the insert has been pulled from supply, got {pulled['supply_status']}"
    )
    assert pulled["release_status"] == "RELEASED", (
        f"the release dimension is untouched, got {pulled['release_status']}"
    )

    stale = api.create_tool_order(
        f.tool_order_payload(customer_id, product_id, quoted, order_code="SO-3"), APP
    )
    fresh = api.create_tool_order(
        f.tool_order_payload(
            customer_id,
            product_id,
            fx.current_product_version(api, product_id),
            order_code="SO-3",
        ),
        APP,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_PRODUCT_VERSION, 412)
    validate_error(fresh, ApiErrorId.ERR_PRODUCT_NOT_ORDERABLE, 409)
    _rows, meta = validate_paginated(api.list_tool_orders(APP))
    assert meta["total_count"] == 0, (
        f"neither attempt created an order, got {meta['total_count']}"
    )


# ─── The customer ledger version an intake quotes ────────────────────────────

def _regrindable_tools_and_a_prepaid_account(api) -> dict:
    """An end mill CU-D may send in, with 50000 cents of prepaid credit."""
    state = fx.endmill_product(api)
    state["customer"] = fx.customer(api, **REGRIND_ACCOUNT)
    return state


def test_a_credit_top_up_invalidates_the_ledger_token(api):
    """The adjustment moves the ledger, so the balance the client read is gone.

    PRD §2.10: "Creating a reconditioning job requires `expected_customer_version`
    as a non-optional field of the request body, carrying the client's last
    observed `version` of the referenced `Customer`. If that value does not equal
    the customer's current `version`, the creation is rejected with
    `ERR_STALE_CUSTOMER_VERSION` and HTTP 412."

    PRD §3.8: "The adjustment applies `delta_cents` to `regrind_credit_cents`, and
    then a three-hop cascade may follow in either direction."

    Design: Corner/cross_cutting_complexity_layers/job_create_pins_the_customer_ledger_version
    """
    state = _regrindable_tools_and_a_prepaid_account(api)
    customer_id = state["customer"]["id"]
    quoted = state["customer"]["version"]

    topped_up = validate_success(
        api.create_credit_adjustment(
            customer_id, f.credit_adjustment_payload(10000), PLAN
        )
    )
    response = api.create_recondition_job(
        f.recondition_job_payload(customer_id, state["product"]["id"], quoted), PLAN
    )

    assert_customer(topped_up)
    assert topped_up["regrind_credit_cents"] == 60000, (
        f"50000 cents topped up by 10000 is 60000, got {topped_up['regrind_credit_cents']}"
    )
    assert topped_up["account_status"] == "ACTIVE", (
        f"a positive balance leaves the account active, got {topped_up['account_status']}"
    )
    assert topped_up["version"] == quoted + 1, (
        f"the adjustment advances the customer version once, got {topped_up['version']}"
    )
    validate_error(response, ApiErrorId.ERR_STALE_CUSTOMER_VERSION, 412)
    _rows, meta = validate_paginated(api.list_recondition_jobs(PLAN))
    assert meta["total_count"] == 0, (
        f"the refused intake opened no job, got {meta['total_count']}"
    )
    customer = validate_success(api.get_customer(customer_id, PLAN))
    assert customer["reserved_credit_cents"] == 0, (
        f"nothing was reserved out of the ledger, got {customer['reserved_credit_cents']}"
    )
    assert_credit_conserved(customer, 60000)


def test_the_intake_bumps_the_ledger_so_its_own_token_expires(api):
    """The reservation written by the first intake invalidates the same token.

    PRD §3.9: "On success the job opens at `status` `RECEIVED`, `regrind_pass_no`
    is set to the length of the `predecessor_job_id` chain plus one,
    `reserved_credit_cents` is set to `units_received` multiplied by 1850, the
    customer's `regrind_credit_cents` is reduced by that reservation while
    `reserved_credit_cents` rises by it, and the customer's `version` advances by
    1."

    Design: Corner/cross_cutting_complexity_layers/job_create_pins_the_customer_ledger_version
    """
    state = _regrindable_tools_and_a_prepaid_account(api)
    customer_id = state["customer"]["id"]
    product_id = state["product"]["id"]
    validate_success(
        api.create_credit_adjustment(
            customer_id, f.credit_adjustment_payload(10000), PLAN
        )
    )
    quoted = fx.current_customer_version(api, customer_id)

    first = validate_success(
        api.create_recondition_job(
            f.recondition_job_payload(customer_id, product_id, quoted), PLAN
        ),
        201,
    )
    repeat = api.create_recondition_job(
        f.recondition_job_payload(customer_id, product_id, quoted, job_code="RJ-2"),
        PLAN,
    )

    assert_recondition_job(first)
    assert first["status"] == "RECEIVED", (
        f"the intake opens the job at received, got {first['status']}"
    )
    assert first["reserved_credit_cents"] == 18500, (
        f"10 tools at 1850 cents each reserve 18500, got {first['reserved_credit_cents']}"
    )
    assert first["regrind_pass_no"] == 1, (
        f"an intake with no predecessor is the first pass, got {first['regrind_pass_no']}"
    )
    validate_error(repeat, ApiErrorId.ERR_STALE_CUSTOMER_VERSION, 412)
    customer = validate_success(api.get_customer(customer_id, PLAN))
    assert customer["regrind_credit_cents"] == 41500, (
        f"60000 less the 18500 reservation is 41500, got {customer['regrind_credit_cents']}"
    )
    assert customer["reserved_credit_cents"] == 18500, (
        f"the single open job holds the reservation, got {customer['reserved_credit_cents']}"
    )
    assert_credit_conserved(customer, 60000)
    rows, meta = validate_paginated(api.list_recondition_jobs(PLAN))
    assert meta["total_count"] == 1, (
        f"only the first intake opened a job, got {meta['total_count']}"
    )
    assert_no_row_with_code(rows, "job_code", "RJ-2")


def test_version_staleness_is_reported_before_insolvency(api):
    """The overdrawn account is reported only once the token is current.

    PRD §2.11: "42. **Customer account orderable.** → `ERR_CUSTOMER_CREDIT_HOLD`
    (HTTP 402) when the account is on credit hold and `ERR_CUSTOMER_CLOSED` (HTTP
    409) when it is closed, on order submission and reconditioning-job intake."

    PRD §3.8: "If the resulting balance is below 0 while the account is `ACTIVE`,
    `account_status` moves `ACTIVE` → `CREDIT_HOLD`, and because the account went
    on hold, every order of that customer in `SUBMITTED` or `ENGINEERING_REVIEW`
    moves to `ON_HOLD` with `hold_reason` set to `CREDIT_HOLD`."

    Design: Corner/cross_cutting_complexity_layers/job_create_pins_the_customer_ledger_version
    """
    state = _regrindable_tools_and_a_prepaid_account(api)
    customer_id = state["customer"]["id"]
    product_id = state["product"]["id"]
    validate_success(
        api.create_credit_adjustment(
            customer_id, f.credit_adjustment_payload(10000), PLAN
        )
    )
    quoted = fx.current_customer_version(api, customer_id)
    validate_success(
        api.create_recondition_job(
            f.recondition_job_payload(customer_id, product_id, quoted), PLAN
        ),
        201,
    )

    overdrawn = validate_success(
        api.create_credit_adjustment(
            customer_id, f.credit_adjustment_payload(-60000), PLAN
        )
    )
    stale = api.create_recondition_job(
        f.recondition_job_payload(customer_id, product_id, quoted, job_code="RJ-3"),
        PLAN,
    )
    fresh = api.create_recondition_job(
        f.recondition_job_payload(
            customer_id,
            product_id,
            fx.current_customer_version(api, customer_id),
            job_code="RJ-3",
        ),
        PLAN,
    )

    assert overdrawn["regrind_credit_cents"] == -18500, (
        f"41500 less 60000 is -18500, got {overdrawn['regrind_credit_cents']}"
    )
    assert overdrawn["account_status"] == "CREDIT_HOLD", (
        f"a negative balance puts the account on hold, got {overdrawn['account_status']}"
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CUSTOMER_VERSION, 412)
    validate_error(fresh, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD, 402)
    rows, meta = validate_paginated(api.list_recondition_jobs(PLAN))
    assert meta["total_count"] == 1, (
        f"neither refused intake opened a job, got {meta['total_count']}"
    )
    assert [row["job_code"] for row in rows] == ["RJ-1"], (
        f"only the prepaid first intake stands, got {[r['job_code'] for r in rows]}"
    )


# ─── Every derived figure is in the writing response ─────────────────────────

def test_the_sintering_response_already_carries_its_qc_verdict(api):
    """Yield, verdict and remaining units need no follow-up read to be seen.

    PRD §3.1: "First, `yield_pct` is computed as 100 multiplied by
    `sintered_units` divided by `pressed_units`, rounded half up to two decimal
    places."

    PRD §3.1: "Moving a grade from `DRAFT` to `PILOT` requires the grade to be at
    `DRAFT` and requires at least one blend batch on that grade to be
    simultaneously at `stage` `SINTERED`, at `qc_status` `PASSED`, and pinned to
    the grade's *current* `revision`."

    PRD §3.5: "Those four contributions are summed into a raw lead time, and here
    the evaluation order is pinned and matters: `expedite_eligible` is decided on
    the **raw** total, being true when the raw total is at most 21 days, and is
    never revisited afterwards. Only if the product is expedite eligible is 3 days
    shaved off the raw total."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response
    """
    grade = fx.carbide_grade(api)
    batch = validate_success(
        api.create_powder_blend_batch(f.powder_blend_batch_payload(grade["id"]), MET),
        201,
    )
    validate_success(api.press_powder_blend_batch(batch["id"], f.press_payload(), MET))
    geometry = fx.released_geometry(api)

    sintered = validate_success(
        api.sinter_powder_blend_batch(batch["id"], f.sinter_payload(), MET)
    )
    piloted = validate_success(api.start_grade_pilot(grade["id"], MET))
    product = validate_success(
        api.create_tool_product(
            f.tool_product_payload(grade["id"], geometry["id"]), GEO
        ),
        201,
    )

    assert_powder_blend_batch(sintered)
    assert sintered["yield_pct"] == 90.00, (
        f"180 good units out of 200 pressed is 90.00 %, got {sintered['yield_pct']}"
    )
    assert sintered["qc_status"] == "PASSED", (
        "density 14.35, a hardness deviation of 20 and a 90.00 % yield all clear "
        f"their thresholds, got {sintered['qc_status']}"
    )
    assert sintered["stage"] == "SINTERED", (
        f"the same request advanced the stage dimension, got {sintered['stage']}"
    )
    assert sintered["remaining_units"] == 180, (
        f"remaining units open at the sintered count, got {sintered['remaining_units']}"
    )
    assert_batch_units_conserved(sintered)
    assert piloted["status"] == "PILOT", (
        f"the passed batch is the evidence the pilot needs, got {piloted['status']}"
    )
    assert_tool_product(product)
    assert product["engineering_lead_time_days"] == 8, (
        "5 catalogue days plus 6 for an unqualified grade is a raw 11, and the "
        f"3-day expedite shave leaves 8, got {product['engineering_lead_time_days']}"
    )
    assert product["expedite_eligible"] is True, (
        f"a raw 11 days is well inside the 21-day limit, got {product['expedite_eligible']}"
    )
    assert product["tool_life_index"] is None, (
        f"no trial evidence exists yet, got {product['tool_life_index']}"
    )
    assert product["qualified_workpiece_groups"] == [], (
        f"no material has been qualified yet, got {product['qualified_workpiece_groups']}"
    )


def test_each_trial_completion_returns_the_dossier_s_recomputed_score(api):
    """The rating is in the completing response and the score in the read behind it.

    PRD §3.6: "The dossier opens at `status` `OPEN` with `completed_trial_count`
    and `passed_trial_count` at 0 and `composite_score` null."

    PRD §3.6: "For each such trial, taken in ascending `created_at` order, a life
    ratio is formed as `rated_life_min` divided by the class's required life,
    capped at 2.0; a finish ratio is formed as the class's maximum roughness
    divided by `measured_surface_ra_um`, also capped at 2.0; and a per-trial
    subscore is 0.6 multiplied by the life ratio plus 0.4 multiplied by the finish
    ratio, **rounded half up to two decimal places at that point**."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response
    """
    state = fx.product_in_qualification(api, coated=False)
    batch_id = state["batch"]["id"]

    opened = validate_success(
        api.create_qualification_dossier(
            f.dossier_payload(state["product"]["id"]), SUBMITTER
        ),
        201,
    )
    assert_qualification_dossier(opened)
    assert opened["composite_score"] is None, (
        f"an empty dossier has no score to average, got {opened['composite_score']}"
    )
    assert opened["completed_trial_count"] == 0, (
        f"no trial has been closed out, got {opened['completed_trial_count']}"
    )

    trial_one = validate_success(
        api.create_machining_trial(
            f.trial_payload(opened["id"], batch_id), OPERATOR_ONE
        ),
        201,
    )
    rated_one = validate_success(
        api.complete_machining_trial(
            trial_one["id"], f.complete_trial_payload(), OPERATOR_ONE
        )
    )
    after_one = validate_success(
        api.get_qualification_dossier(opened["id"], APP)
    )
    trial_two = validate_success(
        api.create_machining_trial(
            f.second_trial_payload(opened["id"], batch_id), OPERATOR_TWO
        ),
        201,
    )
    rated_two = validate_success(
        api.complete_machining_trial(
            trial_two["id"], f.complete_second_trial_payload(), OPERATOR_TWO
        )
    )
    submitted = validate_success(
        api.submit_qualification_dossier(opened["id"], SUBMITTER)
    )

    assert rated_one["rated_life_min"] == 20.0, (
        f"18 plus 6 times 10 over 30 is 20.0 minutes, got {rated_one['rated_life_min']}"
    )
    assert rated_one["verdict"] == "PASS", (
        "20.0 minutes at Ra 1.20 clears the MEDIUM class on both counts, got "
        f"{rated_one['verdict']}"
    )
    assert after_one["composite_score"] == 1.20, (
        "0.6 times 20.0 over 18.0 plus 0.4 times 1.6 over 1.20 is 1.20, visible "
        f"at once, got {after_one['composite_score']}"
    )
    assert after_one["completed_trial_count"] == 1, (
        f"one trial has been closed out, got {after_one['completed_trial_count']}"
    )
    assert after_one["passed_trial_count"] == 1, (
        f"that trial passed, got {after_one['passed_trial_count']}"
    )
    assert rated_two["rated_life_min"] == 23.3, (
        "16 plus 8 times 50 over 55 is 23.3 minutes, got "
        f"{rated_two['rated_life_min']}"
    )
    assert submitted["composite_score"] == 1.20, (
        f"the mean of two 1.20 subscores is 1.20, got {submitted['composite_score']}"
    )
    assert submitted["status"] == "SUBMITTED", (
        f"the folder is closed to new trials, got {submitted['status']}"
    )


def test_the_approval_and_the_reads_behind_it_agree_immediately(api):
    """A GET issued straight after the decision already shows every consequence.

    PRD §3.7: "`tool_life_index` becomes the unweighted mean of those trials'
    `rated_life_min` values — the sum divided by the trial count, not weighted by
    `units_consumed` — rounded half up to one decimal place, and is null when no
    such trial exists. `qualified_workpiece_groups` becomes the distinct
    `workpiece_group` values of those trials, sorted ascending by the alphabetical
    spelling of the enum value."

    PRD §3.7: "Approval does **not** release the product: it stays in
    `QUALIFICATION` and still requires the explicit release described in §3.5. It
    does, however, complete the grade's own qualification: if the product's grade
    is at `PILOT`, the grade moves `PILOT` → `QUALIFIED` in the same request."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response
    """
    state = fx.submitted_dossier(api, coated=False)

    decided = validate_success(
        api.approve_qualification_dossier(
            state["dossier"]["id"], f.approve_dossier_payload(), APPROVER
        )
    )
    product = validate_success(api.get_tool_product(state["product"]["id"], APPROVER))
    grade = validate_success(api.get_carbide_grade(state["grade"]["id"], MET))

    assert decided["status"] == "APPROVED", (
        f"the decision is recorded on the dossier itself, got {decided['status']}"
    )
    assert decided["decided_by_user_id"] == INDEPENDENT_APPROVER, (
        f"the deciding identity is captured, got {decided['decided_by_user_id']}"
    )
    assert product["tool_life_index"] == 21.7, (
        "the mean of 20.0 and 23.3 is 21.65, which rounds half up to 21.7, got "
        f"{product['tool_life_index']}"
    )
    assert product["qualified_workpiece_groups"] == ["M", "P"], (
        f"the two passed groups sort alphabetically, got {product['qualified_workpiece_groups']}"
    )
    assert product["release_status"] == "QUALIFICATION", (
        f"approval is not release, got {product['release_status']}"
    )
    assert grade["status"] == "QUALIFIED", (
        f"the same request promoted the pilot grade, got {grade['status']}"
    )
    assert grade["qualified_product_count"] == 0, (
        "the counter follows the product's release, which has not happened, got "
        f"{grade['qualified_product_count']}"
    )
