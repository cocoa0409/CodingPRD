"""Plan drafting and review: revision cycle, activation guards, sku
resolvability (PRD 3.4)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]
AGRONOMIST = th.TEST_USERS["agronomist_headers"]


def _setup_analyzed_lawn(api, email, seed_skus=("FERT-01",)):
    th.seed_catalog_products(*seed_skus)
    customer = th.register_customer(email=email)
    lawn = th.create_lawn(customer)
    kit = th.analyze_soil_test(customer, th.order_soil_test(customer, lawn))
    return customer, lawn, kit


def test_plan_revision_cycle(api):
    """PRD 3.4: "When supplied, new lines replace the old ones and `provisional_value_cents` is recomputed. Editing a plan that was `PENDING_REVIEW` sends it back to `DRAFT`, so the `DRAFT` to `PENDING_REVIEW` to `DRAFT` revision loop is an allowed cycle that can repeat as often as needed."

    Design: Corner/state_machines/plan_revision_cycle
    """
    _, lawn, kit = _setup_analyzed_lawn(api, email="s4@x.com")
    plan = th.create_draft_plan(
        lawn, kit, plan_lines=[th.plan_line("FERT-01", qty_units=1, target_month=4)]
    )
    assert plan["provisional_value_cents"] == 1200
    th.submit_plan(plan)

    edited = th.validate_success(
        api.patch_plan(
            plan["id"],
            {"plan_lines": [th.plan_line("FERT-01", qty_units=2, target_month=4)]},
            AGRONOMIST,
        )
    )
    assert edited["status"] == "DRAFT", "editing PENDING_REVIEW cycles back to DRAFT"
    assert edited["provisional_value_cents"] == 2400, (
        "provisional value recomputed from the replacement lines (2 x 1200)"
    )


def test_plan_activate_from_draft_rejected(api):
    """PRD 3.4: "Activating requires the plan to be `PENDING_REVIEW`, otherwise `ERR_PLAN_NOT_ACTIVATABLE` (HTTP 409); requires the acting customer to own the plan's lawn (`ERR_OWNERSHIP_MISMATCH`); requires the plan's soil test to be `ANALYZED` (`ERR_SOIL_TEST_NOT_ANALYZED`); requires the lawn to be `ACTIVE` (`ERR_LAWN_ARCHIVED`); and carries the optimistic-concurrency guard on the lawn's version described in Section 2.7 — a stale `expected_lawn_version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/state_machines/plan_activate_from_draft_rejected
    """
    customer, lawn, kit = _setup_analyzed_lawn(api, email="s5@x.com")
    plan = th.create_draft_plan(
        lawn, kit, plan_lines=[th.plan_line("FERT-01", qty_units=1, target_month=4)]
    )
    # Never submitted for review: still DRAFT even with a correct version.
    th.validate_error(
        api.activate_plan(
            plan["id"], {"expected_lawn_version": lawn["version"]},
            th.make_customer_headers(customer["id"]),
        ),
        th.ApiErrorId.ERR_PLAN_NOT_ACTIVATABLE,
    )
    fetched = th.validate_success(api.get_plan(plan["id"], AGRONOMIST))
    assert fetched["status"] == "DRAFT"


def test_plan_submit_review_twice_rejected(api):
    """PRD 3.4: "An Agronomist submits a `DRAFT` plan for review, moving it to `PENDING_REVIEW`; the plan must be `DRAFT`, otherwise `ERR_PLAN_NOT_DRAFT` (HTTP 409)."

    Design: Corner/state_machines/plan_submit_review_twice_rejected
    """
    _, lawn, kit = _setup_analyzed_lawn(api, email="x6@x.com")
    plan = th.create_draft_plan(
        lawn, kit, plan_lines=[th.plan_line("FERT-01", qty_units=1, target_month=4)]
    )
    th.submit_plan(plan)
    th.validate_error(
        api.submit_plan_review(plan["id"], AGRONOMIST),
        th.ApiErrorId.ERR_PLAN_NOT_DRAFT,
    )


def test_plan_line_unknown_sku_rejected(api):
    """PRD 3.4: "Every sku in the lines must resolve to an existing catalog product (`ERR_PRODUCT_NOT_FOUND`) that is active (`ERR_PRODUCT_INACTIVE`)."

    Design: Corner/validations/plan_line_unknown_sku_rejected
    """
    _, lawn, kit = _setup_analyzed_lawn(api, email="x8@x.com")
    th.validate_error(
        api.create_plan(
            th.plan_payload(
                lawn["id"], kit["id"],
                plan_lines=[th.plan_line("NOPE-01", qty_units=1, target_month=4)],
            ),
            AGRONOMIST,
        ),
        th.ApiErrorId.ERR_PRODUCT_NOT_FOUND,
    )


def test_inactive_product_rejected_in_plan(api):
    """PRD 3.1: "A product's `active` flag defaults to true; an inactive product cannot appear in new plan lines or new boxes, and any attempt to reference one there is rejected with `ERR_PRODUCT_INACTIVE` (HTTP 409)."

    Design: Corner/validations/inactive_product_rejected_in_plan
    """
    th.get_success_data(
        api.create_catalog_product(
            th.catalog_product_payload(
                sku="OLD-01", name="Retired", category="FERTILIZER",
                list_price_cents=100, tier_t1_cents=100, tier_t2_cents=100,
                tier_t3_cents=100, conflicting_categories=[], active=False,
            ),
            ADMIN,
        )
    )
    customer = th.register_customer(email="v11@x.com")
    lawn = th.create_lawn(customer)
    kit = th.analyze_soil_test(customer, th.order_soil_test(customer, lawn))
    th.validate_error(
        api.create_plan(
            th.plan_payload(
                lawn["id"], kit["id"],
                plan_lines=[th.plan_line("OLD-01", qty_units=1, target_month=4)],
            ),
            AGRONOMIST,
        ),
        th.ApiErrorId.ERR_PRODUCT_INACTIVE,
    )


def test_plan_create_requires_analyzed_soil(api):
    """PRD 3.4: "Plan creation takes the `lawn_id`, the `soil_test_id` — which must reference an `ANALYZED` kit, otherwise `ERR_SOIL_TEST_NOT_ANALYZED` (HTTP 409) — the `season_year` the plan covers, and `plan_lines`, an array of entries each naming a `product_sku`, a `qty_units` count, and a `target_month`."

    Design: Corner/validations/plan_create_requires_analyzed_soil
    """
    th.seed_catalog_products("FERT-01")
    customer = th.register_customer(email="v5@x.com")
    lawn = th.create_lawn(customer)
    kit = th.order_soil_test(customer, lawn)  # still KIT_SHIPPED
    th.validate_error(
        api.create_plan(
            th.plan_payload(
                lawn["id"], kit["id"],
                plan_lines=[th.plan_line("FERT-01", qty_units=1, target_month=4)],
            ),
            AGRONOMIST,
        ),
        th.ApiErrorId.ERR_SOIL_TEST_NOT_ANALYZED,
    )


def test_subscription_requires_active_plan(api):
    """PRD 3.5: "A subscription begins when a customer starts one on an `ACTIVE` plan belonging to their own lawn. Creation takes `customer_id`, `plan_id` — the plan must be `ACTIVE`, otherwise `ERR_PLAN_NOT_ACTIVE_FOR_SUBSCRIPTION` (HTTP 409) — and a `billing_cycle` of `MONTHLY` or `ANNUAL`."

    Design: Corner/validations/subscription_requires_active_plan
    """
    customer, lawn, kit = _setup_analyzed_lawn(api, email="v6@x.com")
    plan = th.create_draft_plan(
        lawn, kit, plan_lines=[th.plan_line("FERT-01", qty_units=1, target_month=4)]
    )
    th.submit_plan(plan)  # PENDING_REVIEW, never activated
    th.validate_error(
        api.create_subscription(
            th.subscription_payload(customer["id"], plan["id"],
                                    billing_cycle="MONTHLY", auto_ship=False),
            th.make_customer_headers(customer["id"]),
        ),
        th.ApiErrorId.ERR_PLAN_NOT_ACTIVE_FOR_SUBSCRIPTION,
    )
