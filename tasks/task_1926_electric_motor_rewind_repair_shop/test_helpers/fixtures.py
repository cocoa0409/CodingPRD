"""Composite setup helpers for multi-step test prerequisites (PRD §3).

The work-order pipeline is: intake (Technician) -> INCOMING test -> diagnose
-> quote issue (Estimator, OCC-guarded) -> send -> accept (Customer) ->
start-rewind (WindingTechnician) -> coil-data -> FINAL test -> release
(ServiceManager, issues invoice) -> deliver (OCC-guarded) -> close.

Segregation of duties (PRD §2.9) is threaded through the pipeline by using
distinct operator identities: the incoming test is recorded by "op-t", coil
data by "op-w", and the final test by "op-t2".

All setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_claim_approval_payload,
    create_clock_payload,
    create_coil_data_payload,
    create_core_loss_test_payload,
    create_customer_payload,
    create_deliver_payload,
    create_diagnosis_payload,
    create_final_test_payload,
    create_incoming_test_payload,
    create_loan_payload,
    create_motor_payload,
    create_payment_payload,
    create_pool_contract_payload,
    create_quote_issue_payload,
    create_shop_payload,
    create_warranty_claim_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_technician_headers, make_winding_technician_headers

ADMIN = TEST_USERS["shop_admin_headers"]
MANAGER = TEST_USERS["service_manager_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
TECH = TEST_USERS["technician_headers"]           # X-User-ID "op-t"
WINDING = TEST_USERS["winding_technician_headers"]  # X-User-ID "op-w"


# ─── Primitive steps ──────────────────────────────────

def create_shop(**overrides) -> dict:
    return get_success_data(api_client.create_shop(create_shop_payload(**overrides), ADMIN), 201)


def create_customer(shop_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_customer(shop_id, create_customer_payload(**overrides), MANAGER), 201
    )


def create_motor(shop_id, customer_id, **overrides) -> dict:
    serial = overrides.pop("serial_number", "M-1")
    return get_success_data(
        api_client.create_motor(
            shop_id, create_motor_payload(customer_id, serial, **overrides), MANAGER
        ),
        201,
    )


def create_pool_spare(shop_id, **overrides) -> dict:
    """Register a shop-maintained pool spare (custody starts IN_POOL, owner null)."""
    overrides.setdefault("is_pool_spare", True)
    owner = overrides.pop("owner_customer_id", None)  # PRD §3.1: null for pool spares
    serial = overrides.pop("serial_number", "P-1")
    return get_success_data(
        api_client.create_motor(
            shop_id, create_motor_payload(owner, serial, **overrides), MANAGER
        ),
        201,
    )


def intake_work_order(shop_id, customer_id, motor_id, priority="STANDARD") -> dict:
    return get_success_data(
        api_client.create_work_order(
            shop_id, create_work_order_payload(customer_id, motor_id, priority=priority), TECH
        ),
        201,
    )


def record_incoming_test(shop_id, wo_id, user_id="op-t", **overrides) -> dict:
    return get_success_data(
        api_client.record_test(
            shop_id, wo_id, create_incoming_test_payload(**overrides),
            make_technician_headers(user_id),
        ),
        201,
    )


def record_core_loss_test(shop_id, wo_id, measured_watts, user_id="op-t", **overrides) -> dict:
    return get_success_data(
        api_client.record_test(
            shop_id, wo_id, create_core_loss_test_payload(measured_watts, **overrides),
            make_technician_headers(user_id),
        ),
        201,
    )


def record_final_test(shop_id, wo_id, vibration_mm_s=2.0, user_id="op-t2", **overrides) -> dict:
    return get_success_data(
        api_client.record_test(
            shop_id, wo_id, create_final_test_payload(vibration_mm_s, **overrides),
            make_technician_headers(user_id),
        ),
        201,
    )


def diagnose_work_order(shop_id, wo_id, user_id="op-t", **overrides) -> dict:
    return get_success_data(
        api_client.diagnose_work_order(
            shop_id, wo_id, create_diagnosis_payload(**overrides),
            make_technician_headers(user_id),
        )
    )


def get_work_order(shop_id, wo_id) -> dict:
    return get_success_data(api_client.get_work_order(shop_id, wo_id, MANAGER))


def get_work_order_version(shop_id, wo_id) -> int:
    return get_work_order(shop_id, wo_id)["version"]


def issue_quote(shop_id, wo_id) -> dict:
    """Issue a quote against the work order's current version (OCC, PRD §2.10)."""
    version = get_work_order_version(shop_id, wo_id)
    return get_success_data(
        api_client.issue_quote(
            shop_id, wo_id, create_quote_issue_payload(version), ESTIMATOR
        ),
        201,
    )


def send_quote(shop_id, wo_id, quote_id) -> dict:
    return get_success_data(api_client.send_quote(shop_id, wo_id, quote_id, ESTIMATOR))


def accept_quote(shop_id, wo_id, quote_id, customer_id) -> dict:
    return get_success_data(
        api_client.accept_quote(
            shop_id, wo_id, quote_id, make_customer_headers(customer_id)
        )
    )


def start_rewind(shop_id, wo_id, user_id="op-w") -> dict:
    return get_success_data(
        api_client.start_rewind(shop_id, wo_id, make_winding_technician_headers(user_id))
    )


def record_coil_data(shop_id, wo_id, user_id="op-w", **overrides) -> dict:
    return get_success_data(
        api_client.create_coil_data(
            shop_id, wo_id, create_coil_data_payload(**overrides),
            make_winding_technician_headers(user_id),
        ),
        201,
    )


def release_work_order(shop_id, wo_id) -> dict:
    return get_success_data(api_client.release_work_order(shop_id, wo_id, MANAGER))


def deliver_work_order(shop_id, wo_id) -> dict:
    version = get_work_order_version(shop_id, wo_id)
    return get_success_data(
        api_client.deliver_work_order(
            shop_id, wo_id, create_deliver_payload(version), MANAGER
        )
    )


def list_work_order_invoices(shop_id, wo_id) -> list:
    return get_success_data(api_client.list_invoices(shop_id, wo_id, MANAGER))


def get_single_invoice(shop_id, wo_id) -> dict:
    invoices = list_work_order_invoices(shop_id, wo_id)
    assert len(invoices) == 1, f"Expected exactly one invoice, got {len(invoices)}"
    return invoices[0]


def record_payment(shop_id, customer_id, payment_cents) -> dict:
    return get_success_data(
        api_client.record_payment(
            shop_id, customer_id, create_payment_payload(payment_cents), MANAGER
        )
    )


def get_customer(shop_id, customer_id) -> dict:
    return get_success_data(api_client.get_customer(shop_id, customer_id, MANAGER))


def create_pool_contract(shop_id, customer_id, slot_count=2) -> dict:
    return get_success_data(
        api_client.create_pool_contract(
            shop_id, create_pool_contract_payload(customer_id, slot_count), MANAGER
        ),
        201,
    )


def checkout_loan(shop_id, contract_id, work_order_id, spare_motor_id) -> dict:
    return get_success_data(
        api_client.checkout_loan(
            shop_id, contract_id, create_loan_payload(work_order_id, spare_motor_id), MANAGER
        ),
        201,
    )


def return_loan(shop_id, contract_id, loan_id) -> dict:
    return get_success_data(api_client.return_loan(shop_id, contract_id, loan_id, MANAGER))


def file_warranty_claim(shop_id, wo_id, customer_id, failure_mode="WINDING_SHORT") -> dict:
    return get_success_data(
        api_client.file_warranty_claim(
            shop_id, wo_id, create_warranty_claim_payload(failure_mode),
            make_customer_headers(customer_id),
        ),
        201,
    )


def start_review_claim(shop_id, claim_id) -> dict:
    return get_success_data(api_client.start_review_claim(shop_id, claim_id, MANAGER))


def approve_claim(shop_id, claim_id, remedy="PRORATED_CREDIT") -> dict:
    return get_success_data(
        api_client.approve_claim(
            shop_id, claim_id, create_claim_approval_payload(remedy), MANAGER
        )
    )


def deny_claim(shop_id, claim_id) -> dict:
    return get_success_data(api_client.deny_claim(shop_id, claim_id, MANAGER))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(create_clock_payload(to_iso8601), ADMIN))


# ─── Tier 1/2: base hierarchy ─────────────────────────

def setup_shop_customer_motor(shop_overrides=None, motor_overrides=None) -> dict:
    """Shop + customer + one customer-owned motor."""
    shop = create_shop(**(shop_overrides or {}))
    customer = create_customer(shop["id"])
    motor = create_motor(shop["id"], customer["id"], **(motor_overrides or {}))
    return {"shop": shop, "customer": customer, "motor": motor}


# ─── Tier 3: work-order lifecycle shortcuts ───────────

def setup_work_order_intake(priority="STANDARD", motor_overrides=None, shop_overrides=None) -> dict:
    """Shop + customer + motor + work order in INTAKE."""
    bundle = setup_shop_customer_motor(shop_overrides, motor_overrides)
    bundle["work_order"] = intake_work_order(
        bundle["shop"]["id"], bundle["customer"]["id"], bundle["motor"]["id"], priority
    )
    return bundle


def setup_incoming_tested_work_order(priority="STANDARD", motor_overrides=None) -> dict:
    """Work order in INCOMING_TEST (incoming test recorded by op-t)."""
    bundle = setup_work_order_intake(priority, motor_overrides)
    bundle["incoming_test"] = record_incoming_test(
        bundle["shop"]["id"], bundle["work_order"]["id"]
    )
    return bundle


def setup_diagnosed_work_order(
    priority="STANDARD",
    rewind_hours=5,
    materials_cents=10000,
    replacement_cost_cents=999999,
    failure_diagnosis="winding short",
    core_loss_watts=None,
    motor_overrides=None,
) -> dict:
    """Work order in DIAGNOSED. Optionally records a CORE_LOSS test first."""
    bundle = setup_work_order_intake(priority, motor_overrides)
    shop_id = bundle["shop"]["id"]
    wo_id = bundle["work_order"]["id"]
    bundle["incoming_test"] = record_incoming_test(shop_id, wo_id)
    if core_loss_watts is not None:
        bundle["core_loss_test"] = record_core_loss_test(shop_id, wo_id, core_loss_watts)
    bundle["work_order"] = diagnose_work_order(
        shop_id,
        wo_id,
        failure_diagnosis=failure_diagnosis,
        rewind_hours=rewind_hours,
        materials_cents=materials_cents,
        replacement_cost_cents=replacement_cost_cents,
    )
    return bundle


def setup_quoted_work_order(**kwargs) -> dict:
    """Work order in QUOTED with a fresh ISSUED quote."""
    bundle = setup_diagnosed_work_order(**kwargs)
    bundle["quote"] = issue_quote(bundle["shop"]["id"], bundle["work_order"]["id"])
    bundle["work_order"] = get_work_order(bundle["shop"]["id"], bundle["work_order"]["id"])
    return bundle


def setup_awaiting_approval(**kwargs) -> dict:
    """Work order in AWAITING_APPROVAL with the quote sent to the customer."""
    bundle = setup_quoted_work_order(**kwargs)
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    send_quote(shop_id, wo_id, bundle["quote"]["id"])
    bundle["work_order"] = get_work_order(shop_id, wo_id)
    return bundle


def setup_approved_work_order(**kwargs) -> dict:
    """Work order in APPROVED (quote accepted by the customer)."""
    bundle = setup_awaiting_approval(**kwargs)
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    bundle["quote"] = accept_quote(
        shop_id, wo_id, bundle["quote"]["id"], bundle["customer"]["id"]
    )
    bundle["work_order"] = get_work_order(shop_id, wo_id)
    return bundle


def setup_balancing_work_order(**kwargs) -> dict:
    """Work order in BALANCING (coil data recorded by op-w)."""
    bundle = setup_approved_work_order(**kwargs)
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    start_rewind(shop_id, wo_id)
    bundle["coil_data"] = record_coil_data(shop_id, wo_id)
    bundle["work_order"] = get_work_order(shop_id, wo_id)
    return bundle


def setup_final_test_work_order(vibration_mm_s=2.0, **kwargs) -> dict:
    """Work order in FINAL_TEST after a final test recorded by op-t2."""
    bundle = setup_balancing_work_order(**kwargs)
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    bundle["final_test"] = record_final_test(shop_id, wo_id, vibration_mm_s)
    bundle["work_order"] = get_work_order(shop_id, wo_id)
    return bundle


def setup_released_work_order(**kwargs) -> dict:
    """Work order in READY_FOR_PICKUP with its invoice issued OPEN."""
    bundle = setup_final_test_work_order(**kwargs)
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    bundle["work_order"] = release_work_order(shop_id, wo_id)
    bundle["invoice"] = get_single_invoice(shop_id, wo_id)
    return bundle


def setup_delivered_work_order(**kwargs) -> dict:
    """Work order in DELIVERED."""
    bundle = setup_released_work_order(**kwargs)
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    bundle["work_order"] = deliver_work_order(shop_id, wo_id)
    return bundle
