"""RBAC enforcement, OCC stale-version guards, fee-item lifecycle, purchases."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId,
    create_school_year_payload, create_optional_purchase_item_payload,
    create_waiver_program_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_account_with_assessment, setup_account_enrolled,
    setup_account_with_collections_case, advance_case_to_bucket3,
    current_account_version, pay_and_settle,
    make_bookkeeper_headers, make_family_headers, make_superintendent_headers,
)

BK = make_bookkeeper_headers()


class TestRbac:
    def test_missing_auth_header_rejected(self):
        """PRD §2.1: "A request whose headers are missing or malformed is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)"

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api_client.list_students(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_family_member_cannot_create_school_year(self, family_headers):
        """PRD §2.1: "a request whose role is not permitted on the target endpoint
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: `POST /school-years` is authorized for Bookkeeper only.

        Design: Corner/rbac/family_member_cannot_create_school_year
        """
        resp = api_client.create_school_year(create_school_year_payload(), family_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_writeoff_role_segregation_both_directions(self):
        """PRD §2.1: "The `Superintendent` is the district superintendent, who
        co-approves large write-offs and is otherwise read-only."
        PRD §4: `POST .../write-off` is authorized for Bookkeeper;
        `POST .../approve-writeoff` is authorized for Superintendent.

        Design: Corner/rbac/writeoff_role_segregation_both_directions
        """
        env = setup_account_with_collections_case(assessed_amount_cents=200000)
        advance_case_to_bucket3(env, "2026-09-11")
        case_id = env["case"]["id"]
        account_id = env["account"]["id"]
        # Superintendent cannot execute the write-off itself
        resp1 = api_client.write_off_case(account_id, case_id, {"amount_cents": 200000},
                                          make_superintendent_headers())
        validate_error(resp1, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        # Bookkeeper cannot record the co-approval
        resp2 = api_client.approve_writeoff(account_id, case_id,
                                            {"approved_writeoff_cents": 200000},
                                            make_bookkeeper_headers())
        validate_error(resp2, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_superintendent_approve_then_bookkeeper_writeoff_succeeds(self):
        """PRD §3.8: "When the requested amount_cents exceeds the year's
        writeoff_max_cents, the case's approved_writeoff_cents must cover the
        requested amount — that coverage is the `Superintendent`'s co-approval,
        recorded by supplying approved_writeoff_cents"
        PRD §3.8: "Executing the write-off sets the case's written_off_cents to
        the amount and moves the case to `WRITTEN_OFF`."
        PRD §3.8: "The account's posture becomes `WRITTEN_OFF` and the family
        balance recomputes; every assessment still `DELINQUENT` or `ASSESSED`
        under the case moves to `VOID`, its obligation zeroed through the
        write-off ledger so the reconciliation invariant holds."

        Design: Corner/rbac/superintendent_approve_then_bookkeeper_writeoff_succeeds
        """
        env = setup_account_with_collections_case(assessed_amount_cents=200000)
        advance_case_to_bucket3(env, "2026-09-11")
        case_id = env["case"]["id"]
        account_id = env["account"]["id"]
        approved = get_success_data(api_client.approve_writeoff(
            account_id, case_id, {"approved_writeoff_cents": 200000},
            make_superintendent_headers()))
        assert approved["approved_writeoff_cents"] == 200000
        case = get_success_data(api_client.write_off_case(
            account_id, case_id, {"amount_cents": 200000},
            make_bookkeeper_headers("bk-1")))
        assert case["status"] == "WRITTEN_OFF"
        account = get_success_data(api_client.get_student_account(account_id, BK))
        assert account["posture"] == "WRITTEN_OFF"
        assert account["balance_cents"] == 0, (
            "delinquent assessment voided by the write-off")

    def test_family_member_cannot_void_payment(self, family_headers):
        """PRD §3.5: "A `Bookkeeper` may void a `PENDING` payment (`VOIDED`)"
        PRD §2.1: "a request whose role is not permitted on the target endpoint
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/family_member_cannot_void_payment
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        payment = get_success_data(api_client.create_payment(
            env["account"]["id"], {"amount_cents": 3000, "method": "CARD",
                                   "idempotency_key": "k1"}, family_headers))
        resp = api_client.void_payment(env["account"]["id"], payment["id"], family_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_family_member_can_settle_payment(self, family_headers):
        """PRD §3.5: "Settlement is the gateway callback, performed by a
        `FamilyMember` supplying an outcome."

        Design: Corner/rbac/family_member_cannot_void_payment
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 3000, "method": "CARD",
                         "idempotency_key": "k1"}, family_headers))
        resp = api_client.settle_payment(account_id, payment["id"],
                                         {"outcome": "SUCCEEDED"}, family_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "SUCCEEDED"


class TestOcc:
    def test_occ_stale_version_on_plan_create(self):
        """PRD §2.9: "**Creating a payment plan** (`POST
        /student-accounts/{id}/payment-plans`) requires expected_account_version,
        matched against the owning student account's current version." and "if
        that value does not equal the parent entity's current `version` at the
        moment the write executes, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and no mutation occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_plan_create
        """
        env = setup_account_with_assessment(assessed_amount_cents=6000)
        account_id = env["account"]["id"]
        a_v1 = current_account_version(account_id)
        # A second assessment bumps the account version after the client read it
        get_success_data(api_client.create_fee_assessment(
            account_id, {"fee_item_id": env["fee_item"]["id"],
                         "assessed_amount_cents": 1000}, BK))
        resp = api_client.create_payment_plan(
            account_id, {"installment_count": 2, "first_due_date": "2026-09-05",
                         "interval_days": 30, "expected_account_version": a_v1}, BK)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Replaying with the fresh version succeeds
        a_v2 = current_account_version(account_id)
        resp2 = api_client.create_payment_plan(
            account_id, {"installment_count": 2, "first_due_date": "2026-09-05",
                         "interval_days": 30, "expected_account_version": a_v2}, BK)
        data = validate_success(resp2, 201)
        assert data["status"] == "ACTIVE"

    def test_occ_stale_version_on_waiver_approve(self):
        """PRD §2.9: "**Approving a waiver application** (`POST
        /student-accounts/{id}/waiver-applications/{applicationId}/approve`)
        requires expected_account_version, matched against the owning account's
        current version — the stacking base may have changed under the reviewer."
        and "the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no
        mutation occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_waiver_approve
        """
        env = setup_open_year()
        student, account = add_student_with_account(env["year"]["id"])
        program = get_success_data(api_client.create_waiver_program(
            env["year"]["id"], create_waiver_program_payload(), BK))
        app = get_success_data(api_client.create_waiver_application(
            account["id"], {"waiver_program_id": program["id"]},
            make_family_headers("fam-1")))
        a_v1 = current_account_version(account["id"])
        # Bump the account version after the reviewer read it
        env2 = setup_year_with_fee  # noqa: F841 — not needed; fee item created below
        fee = get_success_data(api_client.create_fee_catalog_item(
            env["year"]["id"],
            {"name": "F1", "amount_cents": 1000, "department_id": env["department"]["id"],
             "waiverable": True, "refundable": True}, BK))
        get_success_data(api_client.create_fee_assessment(
            account["id"], {"fee_item_id": fee["id"], "assessed_amount_cents": 1000}, BK))
        resp = api_client.approve_waiver_application(
            account["id"], app["id"], {"expected_account_version": a_v1},
            make_bookkeeper_headers("bk-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        app_now = get_success_data(api_client.get_waiver_application(
            account["id"], app["id"], BK))
        assert app_now["status"] == "PENDING"

    def test_occ_stale_version_on_year_close(self, bookkeeper_headers):
        """PRD §2.9: "**Closing a school year** (`POST /school-years/{id}/close`)
        requires expected_year_version, matched against the year's current
        version — a new collections case or payment plan may have appeared since
        the closer verified the close preconditions."
        and "the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no
        mutation occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_year_close
        """
        year = get_success_data(api_client.create_school_year(
            create_school_year_payload(), bookkeeper_headers))
        y_v1 = year["version"]
        get_success_data(api_client.create_department(
            year["id"], {"code": "SCI", "name": "Science"}, bookkeeper_headers))
        get_success_data(api_client.open_school_year(year["id"], bookkeeper_headers))
        resp = api_client.close_school_year(
            year["id"], {"expected_year_version": y_v1}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        y_v2 = get_success_data(api_client.get_school_year(year["id"], bookkeeper_headers))["version"]
        closed = get_success_data(api_client.close_school_year(
            year["id"], {"expected_year_version": y_v2}, bookkeeper_headers))
        assert closed["status"] == "CLOSED"


class TestFeeItemLifecycle:
    def test_fee_item_retire_in_use_rejected(self, bookkeeper_headers):
        """PRD §3.1: "retiring moves an item `ACTIVE` → `RETIRED` and blocks new
        assessments against it, but only when no assessment referencing the item
        is in `ASSESSED`, `PARTIALLY_PAID`, `PAYMENT_PLAN`, or `DELINQUENT`
        status — assessments that are `PAID`, `REFUNDED`, `WAIVED`, or `VOID` do
        not block retirement."
        PRD §3.1: "A retire attempt against an in-use item is rejected with
        `ERR_FEE_ITEM_IN_USE` (HTTP 409)."

        Design: Corner/state_machines/fee_item_retire_in_use_rejected
        """
        env = setup_account_enrolled(fee_amount=1000)
        resp = api_client.retire_fee_catalog_item(
            env["year"]["id"], env["fee_item"]["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_FEE_ITEM_IN_USE)
        item = get_success_data(api_client.get_fee_catalog_item(
            env["year"]["id"], env["fee_item"]["id"], bookkeeper_headers))
        assert item["status"] == "ACTIVE"

    def test_fee_item_retire_success_then_assessment_blocked(self, bookkeeper_headers):
        """PRD §3.1: "retiring moves an item `ACTIVE` → `RETIRED` and blocks new
        assessments against it"
        PRD §2.10: "The target resource must be in the from-state its state machine
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/fee_item_retire_success_then_assessment_blocked
        """
        env = setup_year_with_fee(fee_amount=1000)
        student, account = add_student_with_account(env["year"]["id"])
        resp = api_client.retire_fee_catalog_item(
            env["year"]["id"], env["fee_item"]["id"], bookkeeper_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "RETIRED"
        resp2 = api_client.create_fee_assessment(
            account["id"], {"fee_item_id": env["fee_item"]["id"],
                            "assessed_amount_cents": 1000}, bookkeeper_headers)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestPurchaseInventory:
    def test_purchase_sold_out_rejected(self):
        """PRD §3.5: "the item's sold_count must be below its inventory_cap, else
        `ERR_ITEM_SOLD_OUT` (HTTP 409)."
        PRD §3.1: "an inventory_cap of at least 1 unit sellable per school year"

        Design: Corner/validations/purchase_sold_out_rejected
        """
        env = setup_open_year()
        item = get_success_data(api_client.create_optional_purchase_item(
            env["year"]["id"],
            create_optional_purchase_item_payload(
                name="Parking Pass", amount_cents=2000,
                department_id=env["department"]["id"], inventory_cap=1), BK))
        s1, a1 = add_student_with_account(env["year"]["id"], external_ref="S-1",
                                          family_id="fam-a", full_name="Ada")
        s2, a2 = add_student_with_account(env["year"]["id"], external_ref="S-2",
                                          family_id="fam-b", full_name="Ben",
                                          grade_level=11)
        first = get_success_data(api_client.create_purchase(
            a1["id"], {"item_id": item["id"], "method": "CARD"}, make_family_headers()))
        assert first["status"] == "COMPLETED", "first purchase fills the single slot"
        resp = api_client.create_purchase(
            a2["id"], {"item_id": item["id"], "method": "CARD"}, make_family_headers())
        validate_error(resp, ApiErrorId.ERR_ITEM_SOLD_OUT)

    def test_purchase_charges_atomically_completed(self):
        """PRD §3.5: "The purchase charges atomically at creation: the Purchase
        row is created directly in `COMPLETED` status with amount_cents pinned
        from the item's price at purchase time, a `DISTRIBUTION_CREDIT` ledger
        entry lands on the item's department, and sold_count increments by 1."
        PRD §2.11: "purchases are not fee assessments and never enter
        assessed_cents, paid_cents, or balance_cents"

        Design: Corner/validations/purchase_sold_out_rejected
        """
        env = setup_open_year()
        item = get_success_data(api_client.create_optional_purchase_item(
            env["year"]["id"],
            create_optional_purchase_item_payload(
                amount_cents=2000, department_id=env["department"]["id"],
                inventory_cap=5), BK))
        student, account = add_student_with_account(env["year"]["id"])
        purchase = get_success_data(api_client.create_purchase(
            account["id"], {"item_id": item["id"], "method": "CARD"},
            make_family_headers()))
        assert purchase["status"] == "COMPLETED"
        assert purchase["amount_cents"] == 2000
        account_now = get_success_data(api_client.get_student_account(account["id"], BK))
        assert account_now["assessed_cents"] == 0
        assert account_now["paid_cents"] == 0
        assert account_now["balance_cents"] == 0, (
            "Purchase money never enters the fee ledger")
