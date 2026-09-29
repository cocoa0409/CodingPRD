"""Cascades that reach several entities from a single request.

Revising a qualified grade restricts the products built on it, flips their
supply dimension and reopens their confirmed orders — four entities from one
call. A credit adjustment holds the account and parks its orders, and a second
adjustment must unwind every hop in the opposite direction.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_carbide_grade, assert_customer
from test_helpers.fixtures import APP, MET, PLAN
from prd_bench_local_runner.testing import validate_success


# ─── Revising a qualified grade: four hops ───────────────────────────────────

def test_grade_revision_restricts_the_product_and_flips_its_supply_dimension(api):
    """One revise call moves the grade, the product's release and its supply status.

    PRD §2.7: "2. Every tool product referencing that definition whose
    corresponding pinned revision is now lower than the new revision, and whose
    `release_status` is `RELEASED`, moves `RELEASED` → `RESTRICTED`."

    PRD §2.7: "3. Because those products became `RESTRICTED`, each one whose
    `supply_status` is `STOCKED` moves `STOCKED` → `MAKE_TO_ORDER`. Products
    already at `MAKE_TO_ORDER` or `UNAVAILABLE` are left alone."

    PRD §3.1: "Revising a blend recipe is permitted from either `PILOT` or
    `QUALIFIED`, and in both cases the grade lands back at `DRAFT`; the two
    declared moves are `QUALIFIED` → `DRAFT` and `PILOT` → `DRAFT`."

    Design: Difficulty/transitive_cascade/grade_revision_four_hop_cascade
    """
    state = fx.confirmed_order(api)

    response = api.revise_carbide_grade(
        state["grade"]["id"], f.revise_grade_payload(), MET
    )

    grade = validate_success(response)
    assert_carbide_grade(grade)
    assert grade["status"] == "DRAFT", (
        f"a revised grade lands back at DRAFT, got {grade['status']}"
    )
    assert grade["revision"] == 2, (
        f"the revision counter advances by 1, got {grade['revision']}"
    )
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["release_status"] == "RESTRICTED", (
        f"the released product is restricted by hop 2, got {product['release_status']}"
    )
    assert product["supply_status"] == "MAKE_TO_ORDER", (
        f"the stocked product falls to MAKE_TO_ORDER by hop 3, got {product['supply_status']}"
    )


def test_grade_revision_drags_the_confirmed_order_back_to_engineering_review(api):
    """The fourth hop reaches an order that was already confirmed.

    PRD §2.7: "4. Because that `supply_status` became `MAKE_TO_ORDER`, every
    tool order on such a product whose `status` is `CONFIRMED` moves
    `CONFIRMED` → `ENGINEERING_REVIEW` and has `requires_reconfirmation` set to
    true."

    PRD §3.1: "Revising from `QUALIFIED` runs the full four-hop restriction
    cascade of §2.7: released products on the grade become `RESTRICTED`, any of
    those that were `STOCKED` fall to `MAKE_TO_ORDER`, and their `CONFIRMED`
    orders return to `ENGINEERING_REVIEW` with `requires_reconfirmation` set to
    true, with a `version` increment on the grade and on every product and order
    the cascade touched."

    Design: Difficulty/transitive_cascade/grade_revision_four_hop_cascade
    """
    state = fx.confirmed_order(api)
    validate_success(
        api.revise_carbide_grade(state["grade"]["id"], f.revise_grade_payload(), MET)
    )

    order = validate_success(api.get_tool_order(state["order"]["id"], APP))

    assert order["status"] == "ENGINEERING_REVIEW", (
        f"the confirmed order is reopened by hop 4, got {order['status']}"
    )
    assert order["requires_reconfirmation"] is True, (
        f"the reopened order is flagged, got {order['requires_reconfirmation']}"
    )


def test_grade_revision_recomputes_lead_time_and_leaves_the_pin_and_dossier_alone(api):
    """Lead time is re-derived from the grade's new status; the pin and dossier stand.

    PRD §2.7: "Independently of the cascade, every product referencing the
    revised definition has `engineering_lead_time_days` and `expedite_eligible`
    recomputed, because both derive from the *current* status of the referenced
    grade, geometry and recipe."

    PRD §3.5: "The grade contributes nothing when the grade's `status` is
    `QUALIFIED` and 6 days otherwise."

    PRD §2.7: "A restricted product is not repaired by revising anything
    further. It is repaired by **repinning**, which captures the current
    revisions again and returns the product to `QUALIFICATION`, from which the
    quality authority may release it once more."

    PRD §3.7: "An approval moves the dossier `SUBMITTED` → `APPROVED`, which is
    terminal."

    Design: Difficulty/transitive_cascade/grade_revision_four_hop_cascade
    """
    state = fx.confirmed_order(api)
    validate_success(
        api.revise_carbide_grade(state["grade"]["id"], f.revise_grade_payload(), MET)
    )

    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )

    assert product["engineering_lead_time_days"] == 12, (
        "5 catalogue plus 4 PVD plus 6 unqualified-grade days is a raw 15, "
        f"less the 3-day shave, got {product['engineering_lead_time_days']}"
    )
    assert product["expedite_eligible"] is True, (
        f"a raw 15 days is still inside the 21-day window, got {product['expedite_eligible']}"
    )
    assert product["pinned_grade_revision"] == 1, (
        "the product still points at the superseded revision until it is "
        f"repinned, got {product['pinned_grade_revision']}"
    )
    assert dossier["status"] == "APPROVED", (
        f"an approved dossier is terminal and is never rewritten, got {dossier['status']}"
    )


# ─── A credit adjustment: three hops, and back again ─────────────────────────

def test_negative_credit_adjustment_holds_the_account_and_parks_its_order(api):
    """Driving the balance below zero holds the account and parks the submitted order.

    PRD §3.8: "If the resulting balance is below 0 while the account is
    `ACTIVE`, `account_status` moves `ACTIVE` → `CREDIT_HOLD`, and because the
    account went on hold, every order of that customer in `SUBMITTED` or
    `ENGINEERING_REVIEW` moves to `ON_HOLD` with `hold_reason` set to
    `CREDIT_HOLD`."

    PRD §3.8: "A credit adjustment is a `ProductionPlanner` act carrying a
    signed `delta_cents` and a `reason`, and it is the only way the balance may
    be driven negative."

    Design: Difficulty/transitive_cascade/credit_hold_three_hop_cascade
    """
    state = fx.submitted_order(api)

    response = api.create_credit_adjustment(
        state["customer"]["id"], f.credit_adjustment_payload(-60000), PLAN
    )

    customer = validate_success(response)
    assert_customer(customer)
    assert customer["regrind_credit_cents"] == -10000, (
        f"50000 less 60000 is -10000, got {customer['regrind_credit_cents']}"
    )
    assert customer["account_status"] == "CREDIT_HOLD", (
        f"a negative balance holds the account, got {customer['account_status']}"
    )
    order = validate_success(api.get_tool_order(state["order"]["id"], APP))
    assert order["status"] == "ON_HOLD", (
        f"the submitted order is parked by hop 3, got {order['status']}"
    )
    assert order["hold_reason"] == "CREDIT_HOLD", (
        f"the parked order records why, got {order['hold_reason']}"
    )


def test_positive_credit_adjustment_unwinds_all_three_hops(api):
    """Restoring the balance lifts the hold and resumes the order as SUBMITTED.

    PRD §3.8: "If instead the resulting balance is 0 or above while the account
    is at `CREDIT_HOLD`, the account moves `CREDIT_HOLD` → `ACTIVE`, and every
    order of that customer at `ON_HOLD` returns to `SUBMITTED` with
    `hold_reason` set back to null."

    PRD §3.8: "That resumption is uniform: an order that was in
    `ENGINEERING_REVIEW` when the hold landed resumes as `SUBMITTED`, not as
    `ENGINEERING_REVIEW`."

    Design: Difficulty/transitive_cascade/credit_hold_three_hop_cascade
    """
    state = fx.submitted_order(api)
    customer_id = state["customer"]["id"]
    validate_success(
        api.create_credit_adjustment(customer_id, f.credit_adjustment_payload(-60000), PLAN)
    )

    response = api.create_credit_adjustment(
        customer_id,
        f.credit_adjustment_payload(15000, reason="Chargeback reversed by the bank"),
        PLAN,
    )

    customer = validate_success(response)
    assert customer["regrind_credit_cents"] == 5000, (
        f"-10000 plus 15000 is 5000, got {customer['regrind_credit_cents']}"
    )
    assert customer["account_status"] == "ACTIVE", (
        f"a non-negative balance lifts the hold, got {customer['account_status']}"
    )
    order = validate_success(api.get_tool_order(state["order"]["id"], APP))
    assert order["status"] == "SUBMITTED", (
        f"the parked order resumes as SUBMITTED, got {order['status']}"
    )
    assert order["hold_reason"] is None, (
        f"the hold reason is cleared, got {order['hold_reason']}"
    )


def test_credit_hold_and_release_never_reprice_the_order(api):
    """The order's money is untouched across both directions of the cascade.

    PRD §3.8: "Both branches price the order, recompute the product's
    `open_order_units`, and advance both the order's `version` and the product's
    `version` by 1."

    PRD §3.8: "The customer's `version` advances by 1, as does the `version` of
    every order the cascade held or resumed."

    Design: Difficulty/transitive_cascade/credit_hold_three_hop_cascade
    """
    state = fx.submitted_order(api)
    customer_id = state["customer"]["id"]
    order_id = state["order"]["id"]

    validate_success(
        api.create_credit_adjustment(customer_id, f.credit_adjustment_payload(-60000), PLAN)
    )
    held = validate_success(api.get_tool_order(order_id, APP))
    validate_success(
        api.create_credit_adjustment(
            customer_id,
            f.credit_adjustment_payload(15000, reason="Chargeback reversed by the bank"),
            PLAN,
        )
    )
    resumed = validate_success(api.get_tool_order(order_id, APP))

    assert held["total_price_cents"] == 448500, (
        f"holding an order does not re-price it, got {held['total_price_cents']}"
    )
    assert resumed["total_price_cents"] == 448500, (
        f"resuming an order does not re-price it, got {resumed['total_price_cents']}"
    )
