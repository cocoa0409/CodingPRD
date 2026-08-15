"""Customers, bottle-spec lifecycle, and the customer-suspend cascade."""
import re

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    assert_customer, assert_bottle_spec,
    create_customer_payload, create_bottle_spec_payload,
    create_customer, create_spec, submit_spec, begin_qualification,
    create_qualification_run, execute_run, submit_review, review_run,
    setup_qualified_spec, setup_qualified_plant,
    setup_scheduled_order, get_order, list_order_slots,
    api_client, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["plant_admin"]
ENGINEER = TEST_USERS["process_engineer"]


class TestCustomerDefaults:
    def test_customer_create_applies_defaults(self, api):
        """PRD §3.1: "The creator may also supply a `default_logistics_mode` of `WAREHOUSE` or `BLOW_ON_SITE`; when omitted it is `WAREHOUSE`". "A customer is born `ACTIVE`".
PRD §2.5: "The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is an ISO 8601 UTC value with three fractional digits recording creation."

Design: Corner/entities/customer_create_applies_defaults"""
        res = api.create_customer(create_customer_payload(), ADMIN)
        customer = validate_success(res, 201)
        assert_customer(customer)
        assert customer["default_logistics_mode"] == "WAREHOUSE", (
            f"omitted default_logistics_mode must default to WAREHOUSE, got "
            f"{customer['default_logistics_mode']}")
        assert customer["status"] == "ACTIVE"
        assert re.search(r"\.\d{3}(Z|[+-]\d{2}:\d{2})$", customer["created_at"]), (
            f"created_at must carry three fractional digits, got "
            f"{customer['created_at']}")


class TestCustomerSuspendCascade:
    def _setup_suspended_customer_with_scheduled_order(self, api):
        ctx = setup_qualified_plant()
        ctx["order"] = setup_scheduled_order(ctx)
        assert ctx["order"]["status"] == "SCHEDULED"
        res = api.suspend_customer(ctx["customer"]["id"], ADMIN)
        ctx["customer"] = validate_success(res, 200)
        return ctx

    def test_suspend_cancels_open_orders(self, api):
        """PRD §3.1: "Suspending a customer (`ACTIVE` → `SUSPENDED`) cancels every one of that customer's production orders still in `DRAFT`, `SCHEDULED`, `RELEASED`, or `HELD`".

Design: Difficulty/transitive_cascade/customer_suspend_cascades_orders_slots"""
        ctx = self._setup_suspended_customer_with_scheduled_order(api)
        assert ctx["customer"]["status"] == "SUSPENDED"
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "CANCELLED", (
            f"suspend must cancel the SCHEDULED order, got {order['status']}")

    def test_suspend_cancels_order_schedule_slots(self, api):
        """PRD §3.1: "every schedule slot those orders held in `CONFIRMED` or `IN_PROGRESS` is cancelled in the same gesture".

Design: Difficulty/transitive_cascade/customer_suspend_cascades_orders_slots"""
        ctx = self._setup_suspended_customer_with_scheduled_order(api)
        slots = list_order_slots(ctx["order"]["id"])
        assert len(slots) == 1
        assert slots[0]["status"] == "CANCELLED", (
            f"order cancellation must cancel its CONFIRMED slot, got "
            f"{slots[0]['status']}")


class TestBottleSpecCreation:
    def test_bottle_spec_starts_in_draft(self, api):
        """PRD §3.2: "Every spec is born in `DRAFT` with `content_revision` set to 1, `qualified_revision` and `rejected_revision` null".

Design: Corner/state_machines/bottle_spec_starts_in_draft"""
        customer = create_customer()
        res = api.create_bottle_spec(
            create_bottle_spec_payload(customer["id"], label_type="NONE"),
            ENGINEER)
        spec = validate_success(res, 201)
        assert_bottle_spec(spec)
        assert spec["status"] == "DRAFT"
        assert spec["content_revision"] == 1
        assert spec["qualified_revision"] is None

    def test_bottle_spec_missing_required_field_rejected(self, api):
        """PRD §2.9: "Third is request shape: all required fields present, no unknown fields, every enum value inside its declared set" — "violations are `ERR_INVALID_REQUEST` (HTTP 400)".

Design: Corner/entities/bottle_spec_missing_required_field_returns_invalid_request"""
        customer = create_customer()
        payload = create_bottle_spec_payload(customer["id"], label_type="NONE")
        del payload["target_weight_g"]
        res = api.create_bottle_spec(payload, ENGINEER)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        # nothing is persisted for the rejected create
        specs = get_success_data(
            api.list_customer_bottle_specs(customer["id"], ENGINEER))
        assert specs == [], f"rejected create must not persist a spec, got {specs}"

    def test_bottle_spec_create_with_server_id_rejected(self, api):
        """PRD §2.5: "Clients never supply `id`, `created_at`, `updated_at`, or `version`; they observe them."
PRD §2.9: "all required fields present, no unknown fields, every enum value inside its declared set" — "violations are `ERR_INVALID_REQUEST` (HTTP 400)".

Design: Corner/entities/bottle_spec_create_with_server_id_returns_invalid_request"""
        customer = create_customer()
        payload = create_bottle_spec_payload(customer["id"], label_type="NONE")
        payload["id"] = NON_EXISTENT_UUID
        res = api.create_bottle_spec(payload, ENGINEER)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestBottleSpecTransitions:
    def test_submit_from_qualified_rejected(self, api):
        """PRD §3.2: "Submission moves a spec from `DRAFT` to `SUBMITTED`, and likewise from `REVISION_REQUESTED` back to `SUBMITTED`".
PRD §2.9: "a transition that is simply not defined for the resource's current state is rejected with `ERR_INVALID_STATE` (HTTP 409)".

Design: Corner/state_machines/submit_from_qualified_returns_invalid_state"""
        _, spec = setup_qualified_spec()
        assert spec["status"] == "QUALIFIED"
        res = api.submit_bottle_spec(spec["id"], ENGINEER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_retire_then_submit_rejected_already_terminal(self, api):
        """PRD §3.2: "`RETIRED` is terminal."
PRD §2.9: "a resource already in a terminal state rejects any further transition with `ERR_ALREADY_TERMINAL` (HTTP 409)".

Design: Corner/state_machines/retire_then_submit_returns_already_terminal"""
        customer = create_customer()
        spec = create_spec(customer["id"], label_type="NONE")
        retired = validate_success(api.retire_bottle_spec(spec["id"], ENGINEER), 200)
        assert retired["status"] == "RETIRED"
        res = api.submit_bottle_spec(spec["id"], ENGINEER)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestSpecRevisionLoop:
    def _setup_rejected_spec(self, api):
        """Drive a spec into REVISION_REQUESTED via a round-1 REJECT."""
        customer = create_customer()
        spec = create_spec(customer["id"])
        submit_spec(spec["id"])
        begin = begin_qualification(spec["id"])
        qrun = create_qualification_run(spec["id"], begin["version"])
        execute_run(qrun["id"])
        submit_review(qrun["id"])
        review_run(qrun["id"], "REJECT", customer["id"],
                   review_note="weight too high")
        spec = get_success_data(api.get_bottle_spec(spec["id"], ENGINEER))
        assert spec["status"] == "REVISION_REQUESTED"
        return customer, spec, qrun

    def test_resubmit_without_content_edit_rejected(self, api):
        """PRD §3.2: "the spec's `content_revision` must have advanced beyond the `rejected_revision` pinned when the spec entered `REVISION_REQUESTED`, and an unchanged resubmission is refused with `ERR_SPEC_UNCHANGED_SINCE_REJECTION`."

Design: Difficulty/non_linear_state_machine/spec_revision_loop_requalification"""
        _, spec, _ = self._setup_rejected_spec(api)
        assert spec["content_revision"] == spec["rejected_revision"]
        res = api.submit_bottle_spec(spec["id"], ENGINEER)
        validate_error(res, ApiErrorId.ERR_SPEC_UNCHANGED_SINCE_REJECTION)

    def test_revision_loop_requalifies_after_content_edit(self, api):
        """PRD §3.2: "`REJECT` moves the run to `REJECTED` and pushes the spec from `IN_QUALIFICATION` to `REVISION_REQUESTED`, pinning `rejected_revision` to the current `content_revision`." "A successful `APPROVE` moves the run to `APPROVED`, the spec from `IN_QUALIFICATION` to `QUALIFIED`, and writes the spec's `qualified_revision` as the pinned revision."

Design: Difficulty/non_linear_state_machine/spec_revision_loop_requalification"""
        customer, spec, _ = self._setup_rejected_spec(api)
        edited = validate_success(
            api.patch_bottle_spec(spec["id"], {"target_weight_g": 23}, ENGINEER),
            200)
        assert edited["content_revision"] == 2
        submit_spec(spec["id"])
        begin = begin_qualification(spec["id"])
        qrun2 = create_qualification_run(spec["id"], begin["version"])
        execute_run(qrun2["id"], measured_mean_weight_g=23.1)
        submit_review(qrun2["id"])
        review_run(qrun2["id"], "APPROVE", customer["id"])
        spec_after = get_success_data(api.get_bottle_spec(spec["id"], ENGINEER))
        assert spec_after["status"] == "QUALIFIED"
        assert spec_after["content_revision"] == 2
        assert spec_after["qualified_revision"] == 2
        assert spec_after["qualification_round"] == 2
        qrun2_after = get_success_data(
            api.get_qualification_run(qrun2["id"], ENGINEER))
        assert qrun2_after["spec_revision_pinned"] == 2
        assert qrun2_after["status"] == "APPROVED"
