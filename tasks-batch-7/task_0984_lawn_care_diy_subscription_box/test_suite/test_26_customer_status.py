"""Customer account state machine: suspend, reinstate, churn guards (PRD 3.2)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_suspend_suspended_customer_rejected(api):
    """PRD 3.2: "Suspending moves a customer from `ACTIVE` to `SUSPENDED` and requires the customer to be `ACTIVE`, otherwise `ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS` (HTTP 409)."

    Design: Corner/state_machines/suspend_suspended_customer_rejected
    """
    customer = th.register_customer(email="x5@x.com", full_name="X Five")
    th.get_success_data(
        api.set_customer_status(customer["id"], {"to_status": "SUSPENDED"}, ADMIN)
    )
    th.validate_error(
        api.set_customer_status(customer["id"], {"to_status": "SUSPENDED"}, ADMIN),
        th.ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS,
    )


def test_reinstate_active_customer_rejected(api):
    """PRD 3.2: "Reinstating moves a customer from `SUSPENDED` back to `ACTIVE` and requires the customer to be `SUSPENDED`, otherwise `ERR_CUSTOMER_NOT_SUSPENDED` (HTTP 409)."

    Design: Corner/validations/reinstate_active_customer_rejected
    """
    customer = th.register_customer(email="v18@x.com", full_name="V Eighteen")
    th.validate_error(
        api.set_customer_status(customer["id"], {"to_status": "ACTIVE"}, ADMIN),
        th.ApiErrorId.ERR_CUSTOMER_NOT_SUSPENDED,
    )


def test_churn_blocked_by_open_subscription(api):
    """PRD 3.2: "Churn moves a customer from `ACTIVE` to the terminal `CHURNED` state and requires both that the customer be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS`) and that every one of the customer's subscriptions already be `CANCELLED`, otherwise `ERR_SUBSCRIPTIONS_STILL_OPEN` (HTTP 409)."

    Design: Corner/validations/churn_blocked_by_open_subscription
    """
    ctx = th.setup_active_subscription(email="v17@x.com")
    th.validate_error(
        api.set_customer_status(ctx["customer"]["id"], {"to_status": "CHURNED"}, ADMIN),
        th.ApiErrorId.ERR_SUBSCRIPTIONS_STILL_OPEN,
    )


def test_suspended_customer_blocked_from_lawn_create(api):
    """PRD 3.2: "While a customer is `SUSPENDED`, creates on their behalf are blocked with `ERR_CUSTOMER_SUSPENDED` (HTTP 409)."
    PRD 3.3: "The owning customer must be `ACTIVE`; attempting to create a lawn for a suspended customer is rejected with `ERR_CUSTOMER_SUSPENDED`."

    Design: Corner/validations/suspended_customer_blocked_from_lawn_create
    """
    customer = th.register_customer(email="v16@x.com")
    th.get_success_data(
        api.set_customer_status(customer["id"], {"to_status": "SUSPENDED"}, ADMIN)
    )
    th.validate_error(
        api.create_lawn(
            th.lawn_payload(customer["id"]),
            th.make_customer_headers(customer["id"]),
        ),
        th.ApiErrorId.ERR_CUSTOMER_SUSPENDED,
    )
