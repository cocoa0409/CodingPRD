"""Who may reach which meat-department operation, and under whose name.

All five PRD roles are opaque operator identities (§2.1): `X-User-ID` is never
compared to any entity's `id` and no operation performs an ownership check. The
recorded identifiers therefore gate exactly one thing — segregation of duties at
the cutting test's `APPROVE`/`REJECT` and the case failure's `RESOLVE`.
"""

import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    CLERK,
    CUTTER,
    CUTTER_2,
    MANAGER,
    MEAT_CUTTER_USER_ID,
    MEAT_MANAGER_USER_ID,
    PRICING_ANALYST_USER_ID,
    SERVICE_CLERK_USER_ID,
    FIXTURE_CLOCK,
    FIXTURE_DATE,
    add_case_plan_line,
    add_cutting_test_line,
    contain_case_failure,
    create_case_plan,
    create_cutting_test,
    create_department,
    create_pre_order,
    create_primal_purchase,
    create_retail_item,
    draft_reconciliation,
    fill_line,
    get_success_data,
    headers_without_auth,
    headers_without_role,
    headers_without_user_id,
    make_role_headers,
    markdown_payload,
    only_case_failure,
    post_reading,
    pre_order_payload,
    primal_purchase_payload,
    propose_price,
    publish_case_plan,
    read_case_failure,
    read_cutting_test,
    read_department,
    retail_item_payload,
    set_clock,
    submit_cutting_test,
    transition_payload,
    validate_error,
)


def test_transition_actions_are_gated_per_action_not_per_endpoint(api):
    """A role on the cutting-test transitions endpoint may still be barred from an action, and a role off the endpoint list never gets that far — rung 2 outranks rung 6, and both outrank the state check at rung 8.

    "A caller whose role is listed for the endpoint but not for the specific
    action is rejected with `ERR_TRANSITION_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/transition_actions_are_gated_per_action_not_per_endpoint
    """
    set_clock(api, FIXTURE_CLOCK)
    department = create_department(api)
    steak = create_retail_item(api, department["id"])
    purchase = create_primal_purchase(api, department["id"])

    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )
    add_cutting_test_line(
        api, test["id"], 1, "RIBEYE_STEAK", "SALABLE_CUT", 62.0, 1450,
        retail_item_id=steak["id"],
    )
    add_cutting_test_line(
        api, test["id"], 2, "RIBEYE_TRIM_LEAN", "GRIND_TRIM", 18.5, 420, lean_pct=78.0
    )
    add_cutting_test_line(
        api, test["id"], 3, "RIBEYE_FAT_BONE", "FAT_BONE_LOSS", 18.0, 0
    )
    submitted = submit_cutting_test(api, test["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == MEAT_CUTTER_USER_ID
    submitted_version = submitted["version"]

    # A pricing operator is absent from the endpoint's role list altogether, so
    # the request never reaches the action screen (PRD §2.11 rung 2).
    off_the_list = api.transition_cutting_test(
        test["id"],
        transition_payload("APPROVE"),
        make_role_headers(PRICING_ANALYST_USER_ID, "PricingAnalyst"),
    )
    validate_error(off_the_list, "ERR_ROLE_NOT_PERMITTED", 403)

    # Missing credentials outrank every role question (PRD §2.11 rung 1).
    validate_error(
        api.transition_cutting_test(
            test["id"], transition_payload("APPROVE"), headers_without_user_id("MeatManager")
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.transition_cutting_test(
            test["id"], transition_payload("APPROVE"), headers_without_role(MEAT_MANAGER_USER_ID)
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.transition_cutting_test(
            test["id"], transition_payload("APPROVE"), headers_without_auth()
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    # A second cutter is on the endpoint's list but APPROVE belongs to the
    # manager, so the refusal is the action-level one (PRD §2.11 rung 6).
    approve_by_cutter = api.transition_cutting_test(
        test["id"], transition_payload("APPROVE"), CUTTER_2
    )
    validate_error(approve_by_cutter, "ERR_TRANSITION_ROLE_NOT_PERMITTED", 403)

    untouched = read_cutting_test(api, test["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["version"] == submitted_version

    rejected = get_success_data(
        api.transition_cutting_test(
            test["id"],
            transition_payload("REJECT", rejection_reason="trim weights do not match the bench sheet"),
            MANAGER,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["revision_count"] == 0
    rejected_version = rejected["version"]

    # REVISE belongs to the cutter, so the manager is refused at the action
    # screen even though the move itself is legal out of REJECTED.
    revise_by_manager = api.transition_cutting_test(
        test["id"], transition_payload("REVISE"), MANAGER
    )
    validate_error(revise_by_manager, "ERR_TRANSITION_ROLE_NOT_PERMITTED", 403)

    still_rejected = read_cutting_test(api, test["id"])
    assert still_rejected["status"] == "REJECTED"
    assert still_rejected["version"] == rejected_version

    revised = get_success_data(
        api.transition_cutting_test(test["id"], transition_payload("REVISE"), CUTTER), 200
    )
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert not revised["submitted_by_user_id"]


def test_segregation_of_duties_blocks_self_approval_and_self_resolution(api):
    """The operator who submitted a cutting test and reported a case failure cannot approve or resolve his own work, however his role header reads.

    "What the recorded identifiers *are* used for is segregation of duties: two
    named steps require that the acting operator differ from the operator who
    performed the prior step, and a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_blocks_self_approval_and_self_resolution
    """
    lone_operator_cutting = make_role_headers("u-77", "MeatCutter")
    lone_operator_managing = make_role_headers("u-77", "MeatManager")

    set_clock(api, FIXTURE_CLOCK)
    department = create_department(api)
    steak = create_retail_item(api, department["id"])
    purchase = create_primal_purchase(api, department["id"])

    test = create_cutting_test(
        api,
        purchase["id"],
        purchase["net_weight_lb"],
        purchase["version"],
        headers=lone_operator_cutting,
    )
    add_cutting_test_line(
        api, test["id"], 1, "RIBEYE_STEAK", "SALABLE_CUT", 62.0, 1450,
        retail_item_id=steak["id"], headers=lone_operator_cutting,
    )
    add_cutting_test_line(
        api, test["id"], 2, "RIBEYE_TRIM_LEAN", "GRIND_TRIM", 18.5, 420, lean_pct=78.0,
        headers=lone_operator_cutting,
    )
    add_cutting_test_line(
        api, test["id"], 3, "RIBEYE_FAT_BONE", "FAT_BONE_LOSS", 18.0, 0,
        headers=lone_operator_cutting,
    )
    submitted = submit_cutting_test(api, test["id"], headers=lone_operator_cutting)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "u-77"
    submitted_version = submitted["version"]

    # The same operator's two out-of-spec readings open the case failure, so he
    # is also its reporter of record.
    post_reading(api, department["id"], "CASE-A", 4.5, headers=lone_operator_cutting)
    post_reading(api, department["id"], "CASE-A", 4.6, headers=lone_operator_cutting)
    failure = only_case_failure(api)
    assert failure["status"] == "OPEN"
    assert failure["reported_by_user_id"] == "u-77"

    # Containment carries no segregation rule of its own.
    contained = contain_case_failure(
        api, failure["id"], note="product moved to the backup case", headers=CUTTER_2
    )
    assert contained["status"] == "CONTAINED"
    contained_version = contained["version"]
    post_reading(api, department["id"], "CASE-A", 4.0, headers=CUTTER_2)

    # The manager role header does not launder the identity underneath it.
    self_approval = api.transition_cutting_test(
        test["id"], transition_payload("APPROVE"), lone_operator_managing
    )
    validate_error(self_approval, "ERR_SEGREGATION_OF_DUTIES", 403)
    held_test = read_cutting_test(api, test["id"])
    assert held_test["status"] == "SUBMITTED"
    assert held_test["version"] == submitted_version

    approved = get_success_data(
        api.transition_cutting_test(test["id"], transition_payload("APPROVE"), MANAGER), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == MEAT_MANAGER_USER_ID

    self_resolution = api.transition_case_failure(
        failure["id"],
        transition_payload("RESOLVE", disposition="MARKDOWN"),
        lone_operator_managing,
    )
    validate_error(self_resolution, "ERR_SEGREGATION_OF_DUTIES", 403)
    held_failure = read_case_failure(api, failure["id"])
    assert held_failure["status"] == "CONTAINED"
    assert held_failure["version"] == contained_version

    resolved = get_success_data(
        api.transition_case_failure(
            failure["id"], transition_payload("RESOLVE", disposition="MARKDOWN"), MANAGER
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_by_user_id"] == MEAT_MANAGER_USER_ID
    assert resolved["disposition"] == "MARKDOWN"

    settled = read_department(api, department["id"])
    assert settled["open_case_failure_count"] == 0
    assert settled["contained_case_failure_count"] == 0
    assert settled["consecutive_out_of_spec_readings"] == 0
    assert settled["case_posture"] == "SALES_OPEN"


def test_shared_writes_accept_either_holder_of_the_operation(api):
    """Receiving, catalogue seeding, temperature readings and customer orders each admit two roles, and the row written is identical whichever holder writes it.

    "Receiving is where the cost enters the system, and either a `MeatCutter` or
    a `MeatManager` may record it."

    Design: Corner/rbac/shared_writes_accept_either_holder_of_the_operation
    """
    set_clock(api, FIXTURE_CLOCK)
    department = create_department(api)

    # Receiving under the cutter, then under the manager.
    ribeye_purchase = create_primal_purchase(api, department["id"])
    strip_purchase = get_success_data(
        api.create_primal_purchase(
            primal_purchase_payload(
                department["id"],
                primal_code="BEEF_STRIP_LOIN",
                product_class="WHOLE_MUSCLE",
                country_of_origin="CAN",
                gross_weight_lb=60.0,
                invoice_cost_cents=54000,
                freight_cost_cents=0,
                vendor_allowance_cents=0,
                receiving_shrink_lb=0.0,
                received_at="2026-08-05T06:30:00Z",
            ),
            MANAGER,
        ),
        201,
    )

    assert ribeye_purchase["net_weight_lb"] == pytest.approx(98.50, abs=0.01)
    assert ribeye_purchase["landed_cost_total_cents"] == 86000
    assert ribeye_purchase["landed_cost_per_lb_cents"] == pytest.approx(873.0964, abs=0.0001)
    assert ribeye_purchase["status"] == "RECEIVED"

    # 60.0 gross less no dock shrink, 54000 invoice with no freight and no
    # allowance: 54000 / 60.00 lands on an exact 900.0000 per usable pound.
    assert strip_purchase["net_weight_lb"] == pytest.approx(60.00, abs=0.01)
    assert strip_purchase["landed_cost_total_cents"] == 54000
    assert strip_purchase["landed_cost_per_lb_cents"] == pytest.approx(900.0000, abs=0.0001)
    assert strip_purchase["allocated_cost_cents"] == 0
    assert strip_purchase["unallocated_cost_cents"] == 54000
    assert strip_purchase["status"] == "RECEIVED"
    assert strip_purchase["version"] == 1

    # Catalogue seeding under the admin, then under the manager.
    ribeye_item = create_retail_item(api, department["id"])
    strip_item = get_success_data(
        api.create_retail_item(
            retail_item_payload(
                department["id"],
                item_code="STR01",
                subprimal_code="STRIP_STEAK",
                product_class="WHOLE_MUSCLE",
            ),
            MANAGER,
        ),
        201,
    )
    assert ribeye_item["price_status"] == "UNPRICED"
    assert strip_item["price_status"] == "UNPRICED"
    assert strip_item["cost_basis_source"] == "CUT_TEST_LINE"

    # Readings under the service clerk, then under the cutter.
    clerk_reading = post_reading(api, department["id"], "CASE-A", 3.8, headers=CLERK)
    cutter_reading = post_reading(api, department["id"], "CASE-B", 3.9, headers=CUTTER)
    assert clerk_reading["recorded_by_user_id"] == SERVICE_CLERK_USER_ID
    assert clerk_reading["out_of_spec"] is False
    assert cutter_reading["recorded_by_user_id"] == MEAT_CUTTER_USER_ID
    assert cutter_reading["out_of_spec"] is False

    propose_price(api, ribeye_item["id"], ribeye_purchase["id"])

    # Customer orders under the service clerk, then under the manager. Neither
    # order is quoted yet — the quote is pinned at confirmation, not intake.
    clerk_order = create_pre_order(
        api,
        department["id"],
        ribeye_item["id"],
        5.0,
        "2026-08-06T14:00:00Z",
        "2026-08-06T15:00:00Z",
    )
    manager_order = get_success_data(
        api.create_pre_order(
            pre_order_payload(
                department["id"],
                ribeye_item["id"],
                4.0,
                "2026-08-06T16:00:00Z",
                "2026-08-06T17:00:00Z",
                customer_name="T. Okafor",
                customer_phone="555-0101",
            ),
            MANAGER,
        ),
        201,
    )
    for order in (clerk_order, manager_order):
        assert order["status"] == "REQUESTED"
        assert order["quoted_price_per_lb_cents"] == 0
        assert order["pinned_retail_item_version"] == 0
        assert order["deposit_cents"] == 0
        assert order["amend_count"] == 0

    # A role outside the receiving list is stopped, and no credentials at all is
    # stopped one rung earlier still.
    validate_error(
        api.create_primal_purchase(primal_purchase_payload(department["id"]), ANALYST),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_primal_purchase(
            primal_purchase_payload(department["id"]), headers_without_auth()
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )


def test_peer_roles_cannot_reach_each_other_operations(api):
    """The pricing and service operators each own a write the other cannot issue, share the case-line read, and are each shut out of one read surface entirely.

    "If both headers are present but the named role is not authorized for the
    endpoint, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/peer_roles_cannot_reach_each_other_operations
    """
    set_clock(api, FIXTURE_CLOCK)
    department = create_department(api)
    steak = create_retail_item(api, department["id"])
    purchase = create_primal_purchase(api, department["id"])
    steak = propose_price(api, steak["id"], purchase["id"])
    assert steak["price_status"] == "PROPOSED"
    assert steak["active_price_per_lb_cents"] == 2149

    plan = create_case_plan(api, department["id"], FIXTURE_DATE)
    line = add_case_plan_line(api, plan["id"], steak["id"], 1, 4, 30.0)
    assert line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)
    publish_case_plan(api, plan["id"])
    fill_line(api, line["id"], 34.0)

    order = create_pre_order(
        api,
        department["id"],
        steak["id"],
        5.0,
        "2026-08-05T14:00:00Z",
        "2026-08-05T15:00:00Z",
    )
    period = draft_reconciliation(api, department["id"], FIXTURE_DATE, FIXTURE_DATE)

    # The markdown is the pricing operator's own write. The cost floor sits at
    # zero because no measured basis has been activated onto the item yet.
    marked_down = get_success_data(
        api.create_markdown(line["id"], markdown_payload(4.0, 1600), ANALYST),
        201,
    )
    assert marked_down["markdown_lb"] == pytest.approx(4.00, abs=0.01)
    assert marked_down["markdown_price_per_lb_cents"] == 1600
    assert marked_down["markdown_dollars_cents"] == 2196
    assert marked_down["line_status"] == "MARKED_DOWN"

    # Confirmation is the service operator's own write, and it pins the quote
    # off the item: 2149 a pound over 5.0 lb at a quarter deposit rate.
    confirmed = get_success_data(
        api.transition_pre_order(order["id"], transition_payload("CONFIRM"), CLERK), 200
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["quoted_price_per_lb_cents"] == 2149
    assert confirmed["deposit_cents"] == 2687

    # The case-line read is open to both peers.
    analyst_view = get_success_data(api.get_case_plan_line(line["id"], ANALYST), 200)
    clerk_view = get_success_data(api.get_case_plan_line(line["id"], CLERK), 200)
    assert analyst_view["markdown_lb"] == pytest.approx(4.00, abs=0.01)
    assert clerk_view["markdown_lb"] == pytest.approx(4.00, abs=0.01)

    # Neither peer can issue the other's write.
    validate_error(
        api.create_markdown(line["id"], markdown_payload(1.0, 1600), CLERK),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    second_order = create_pre_order(
        api,
        department["id"],
        steak["id"],
        2.0,
        "2026-08-05T18:00:00Z",
        "2026-08-05T19:00:00Z",
    )
    validate_error(
        api.transition_pre_order(second_order["id"], transition_payload("CONFIRM"), ANALYST),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    # The read surfaces are asymmetric: grind inputs are closed to both peers,
    # while the settlement row is closed to the cutter and the clerk.
    validate_error(api.list_grind_inputs(ANALYST), "ERR_ROLE_NOT_PERMITTED", 403)
    validate_error(api.list_grind_inputs(CLERK), "ERR_ROLE_NOT_PERMITTED", 403)
    validate_error(
        api.get_shrink_reconciliation(period["id"], CUTTER), "ERR_ROLE_NOT_PERMITTED", 403
    )
    validate_error(
        api.get_shrink_reconciliation(period["id"], CLERK), "ERR_ROLE_NOT_PERMITTED", 403
    )
    assert get_success_data(api.get_shrink_reconciliation(period["id"], ADMIN), 200)["id"] == period["id"]
