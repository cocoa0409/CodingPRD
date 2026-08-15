"""Order amendment cycle and OCC guards on amendment / plan create
(PRD §3.2, §2.7)."""
from test_helpers import (
    TEST_USERS,
    create_order,
    create_plan,
    create_plant,
    create_product,
    create_store,
    confirm_order,
    make_store_receiver_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _confirmed_order_ctx():
    plant = create_plant()
    product_a = create_product(plant["id"])
    store = create_store(plant["id"])
    set_clock("2026-08-06T00:00:00Z")
    order = create_order(store["id"], product_a["id"], qty=100)
    confirmed = confirm_order(order["id"])
    return {"plant": plant, "product_a": product_a, "store": store, "order": confirmed}


class TestStoreOrderAmendmentCycle:
    def test_amendment_request_moves_to_pending(self, api):
        """PRD §3.2: "A successful request moves the order to
        `AMENDMENT_PENDING` with the requested lines parked in
        `pending_lines`."

        Design: Difficulty/non_linear_state_machine/store_order_amendment_cycle
        """
        ctx = _confirmed_order_ctx()
        order = ctx["order"]
        store = ctx["store"]
        product_a = ctx["product_a"]

        resp = api.request_amendment(
            order["id"],
            {"lines": [{"product_id": product_a["id"], "qty": 120}],
             "expected_store_order_version": order["version"]},
            make_store_receiver_headers(store["id"]),
        )
        pending = validate_success(resp, expected_status=200)
        assert pending["status"] == "AMENDMENT_PENDING"

    def test_accept_amendment_returns_to_confirmed_with_new_total(self, api):
        """PRD §3.2: "accepting the amendment moves the order back to
        `CONFIRMED` with `lines` replaced by `pending_lines`, `pending_lines`
        cleared to null, and `total_units` recomputed from the new lines."

        Design: Difficulty/non_linear_state_machine/store_order_amendment_cycle
        """
        ctx = _confirmed_order_ctx()
        order = ctx["order"]
        store = ctx["store"]
        product_a = ctx["product_a"]

        validate_success(
            api.request_amendment(
                order["id"],
                {"lines": [{"product_id": product_a["id"], "qty": 120}],
                 "expected_store_order_version": order["version"]},
                make_store_receiver_headers(store["id"]),
            )
        )
        accepted = validate_success(
            api.accept_amendment(order["id"], TEST_USERS["planner_headers"])
        )
        assert accepted["status"] == "CONFIRMED", (
            f"accept-amendment must loop back to CONFIRMED, got {accepted['status']}"
        )
        assert accepted["total_units"] == 120, (
            f"total_units must be recomputed to 120, got {accepted['total_units']}"
        )


class TestOccAmendment:
    def test_occ_amendment_returns_412_on_stale_version(self, api):
        """PRD §2.7: "Requesting an amendment to a store order requires the
        request body to carry `expected_store_order_version`, equal to the
        order's current `version` as last observed by the client. If the
        order's `version` has advanced since that observation — for example
        because a prior amendment was accepted or rejected — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_amendment_returns_412_on_stale_version
        """
        ctx = _confirmed_order_ctx()
        order = ctx["order"]
        store = ctx["store"]
        product_a = ctx["product_a"]

        # First amendment succeeds and bumps the version.
        first = validate_success(
            api.request_amendment(
                order["id"],
                {"lines": [{"product_id": product_a["id"], "qty": 110}],
                 "expected_store_order_version": order["version"]},
                make_store_receiver_headers(store["id"]),
            )
        )
        assert first["version"] == order["version"] + 1

        # Second amendment with the pre-first-amendment version is stale.
        resp = api.request_amendment(
            order["id"],
            {"lines": [{"product_id": product_a["id"], "qty": 130}],
             "expected_store_order_version": order["version"]},
            make_store_receiver_headers(store["id"]),
        )
        validate_error(resp, "ERR_STALE_VERSION", expected_status=412)


class TestOccPlanCreate:
    def test_occ_plan_create_supersede_and_stale(self, api):
        """PRD §2.7: "Creating a production plan requires the request body to
        carry `expected_plant_version`, equal to the plant's current
        `version`. Because creating a plan supersedes any existing draft for
        the same plant and bake date, a client whose view of the plant is
        stale would supersede blindly; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "If a `DRAFT` plan exists for that combination, the new plan
        is created normally and the old draft is superseded — its status
        moves from `DRAFT` to `SUPERSEDED` and its `version` increments."

        Design: Corner/cross_cutting_complexity_layers/occ_plan_create_supersede_and_stale
        """
        plant = create_plant()
        plan1 = create_plan(plant["id"], expected_plant_version=plant["version"])

        # Stale: reuse the original plant version after plan1 advanced it.
        resp = api.create_production_plan(
            {"plant_id": plant["id"], "bake_date": "2026-08-09",
             "expected_plant_version": plant["version"]},
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_STALE_VERSION", expected_status=412)

        # Fresh: read the plant version now and retry; the old DRAFT flips.
        plant_now = validate_success(
            api.get_plant(plant["id"], TEST_USERS["planner_headers"])
        )
        plan3 = validate_success(
            api.create_production_plan(
                {"plant_id": plant["id"], "bake_date": "2026-08-09",
                 "expected_plant_version": plant_now["version"]},
                TEST_USERS["planner_headers"],
            ),
            expected_status=201,
        )
        assert plan3["status"] == "DRAFT"
        plan1_after = validate_success(
            api.get_production_plan(plan1["id"], TEST_USERS["planner_headers"])
        )
        assert plan1_after["status"] == "SUPERSEDED", (
            f"old DRAFT must flip to SUPERSEDED, got {plan1_after['status']}"
        )
