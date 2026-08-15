"""User-context headers and role-based access control denials (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    create_approved_food_safety_plan,
    create_crop_plan,
    create_customer,
    create_food_safety_plan,
    create_listed_variety,
    create_released_seed_lot,
    create_standing_order_payload,
    make_chef_headers,
    validate_error,
)
from test_helpers.fixtures import GROWER, OPS


class TestUserContextHeaders:
    def test_request_without_user_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act."
        PRD §2.1: "A request with missing or malformed headers is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_customers({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleDenials:
    def test_grower_cannot_approve_food_safety_plan(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "The `OpsManager` owns compliance and logistics — customer
        onboarding, food-safety plans, delivery routes and stops, credit
        adjudication, and the logical clock."

        Design: Corner/roles/grower_cannot_approve_food_safety_plan
        """
        plan = create_food_safety_plan()

        resp = api.approve_food_safety_plan(plan["id"], GROWER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_chef_cannot_sow_crop_plan(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "Broadly, the `Grower` owns grow operations — varieties,
        trials, seed lots, germination tests, crop plans, tray batches,
        sanitation logs, and surplus listings."

        Design: Corner/roles/chef_cannot_sow_crop_plan
        """
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Sage", crop_category="SPECIALTY_HERB",
                                        days_to_harvest=24,
                                        expected_yield_grams_per_tray=3000,
                                        listed_price_cents_per_kg=2600,
                                        min_order_grams=100)
        lot = create_released_seed_lot(variety["id"])
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)
        customer = create_customer(business_name="R7")

        resp = api.sow_crop_plan(
            plan["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan["version"]},
            make_chef_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_ops_manager_cannot_create_standing_order(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "The `Chef` owns ordering — standing orders, weekly line
        changes, confirmation, cancellation — and may report spoilage."

        Design: Corner/roles/ops_manager_cannot_create_standing_order
        """
        customer = create_customer(business_name="R8")

        resp = api.create_standing_order(
            create_standing_order_payload(customer["id"]), OPS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
