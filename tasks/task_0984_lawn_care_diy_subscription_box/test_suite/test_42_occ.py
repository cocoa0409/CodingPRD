"""Optimistic concurrency control: expected-version guards on plan activation
and subscription patch (PRD 2.7, 3.4, 3.5)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]
AGRONOMIST = th.TEST_USERS["agronomist_headers"]


def test_occ_plan_activation_stale_then_supersede(api):
    """PRD 2.7: "A plan-activation request must carry `expected_lawn_version` holding the client's last observed `version` of the lawn the plan belongs to. If the lawn's current `version` has advanced since the client read it — for example because another plan for the same lawn was just activated, which legitimately bumps the lawn version — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from activating against a lawn state it has not observed."
    PRD 3.4: "On activation the plan's `activated_at` is stamped from the logical clock, the lawn's previously `ACTIVE` plan — if one exists — flips to `SUPERSEDED`, and the newly activated plan records that predecessor in its `supersedes_plan_id` (null for a lawn's first activation)."

    Design: Corner/cross_cutting_layers/occ_plan_activation_stale_then_supersede
    """
    th.seed_catalog_products("FERT-01")
    customer = th.register_customer(email="x1@x.com", full_name="X One")
    headers = th.make_customer_headers(customer["id"])
    lawn = th.create_lawn(customer)
    kit = th.analyze_soil_test(customer, th.order_soil_test(customer, lawn))

    plan1 = th.create_draft_plan(
        lawn, kit, plan_lines=[th.plan_line("FERT-01", qty_units=1, target_month=4)]
    )
    th.submit_plan(plan1)
    plan2 = th.create_draft_plan(
        lawn, kit, plan_lines=[th.plan_line("FERT-01", qty_units=2, target_month=4)]
    )
    th.submit_plan(plan2)

    # plan1 activates against the version observed at lawn creation; the
    # activation legitimately bumps the lawn version.
    th.activate_plan(customer, lawn, plan1,
                     expected_lawn_version=lawn["version"])

    # plan2's view of the lawn is now stale.
    th.validate_error(
        api.activate_plan(plan2["id"],
                          {"expected_lawn_version": lawn["version"]}, headers),
        th.ApiErrorId.ERR_STALE_VERSION,
    )

    # Re-read the lawn and retry with the fresh version: succeeds, and the
    # previously ACTIVE plan1 flips to SUPERSEDED with the chain recorded.
    lawn_now = th.validate_success(api.get_lawn(lawn["id"], ADMIN))
    assert lawn_now["version"] == lawn["version"] + 1
    activated = th.validate_success(
        api.activate_plan(plan2["id"],
                          {"expected_lawn_version": lawn_now["version"]}, headers)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["supersedes_plan_id"] == plan1["id"]
    plan1_after = th.validate_success(api.get_plan(plan1["id"], AGRONOMIST))
    assert plan1_after["status"] == "SUPERSEDED"


def test_occ_subscription_patch_stale_version(api):
    """PRD 2.7: "A subscription-patch request must carry `expected_subscription_version` holding the client's last observed `version` of the target subscription. Because a pause/resume cycle or a payment-state cascade legitimately advances the subscription version, a patch whose `expected_subscription_version` does not match the subscription's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.5: "After creation the customer may patch `auto_ship`, `billing_cycle`, or `next_ship_date`. The patch carries the optimistic-concurrency guard on the subscription's own version — `expected_subscription_version`, per Section 2.7 — and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_subscription_patch_stale_version
    """
    ctx = th.setup_active_subscription(email="x2@x.com")
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]
    created_version = ctx["subscription"]["version"]

    # A pause cascade legitimately bumps the subscription version.
    th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "PAUSED"}, headers)
    )

    patch_payload = {"auto_ship": True, "next_ship_date": "2026-09-01T00:00:00Z"}
    th.validate_error(
        api.patch_subscription(
            sub_id,
            {**patch_payload, "expected_subscription_version": created_version},
            headers,
        ),
        th.ApiErrorId.ERR_STALE_VERSION,
    )

    sub_now = th.validate_success(api.get_subscription(sub_id, ADMIN))
    patched = th.validate_success(
        api.patch_subscription(
            sub_id,
            {**patch_payload,
             "expected_subscription_version": sub_now["version"]},
            headers,
        )
    )
    assert patched["auto_ship"] is True
    assert patched["version"] == sub_now["version"] + 1
