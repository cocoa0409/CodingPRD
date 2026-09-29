"""Computed reads, the amendment PATCH, sub-resource listings, list filters and
action-endpoint path resolution."""

from test_helpers import (
    CONTRACT_ADMIN,
    DESIGN_ENGINEER,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    QUALITY_ENGINEER,
    USER_REVIEWER_1,
    assert_pagination_defaults,
    begin_review,
    create_component,
    create_drawing,
    create_order,
    create_supplier,
    disposition,
    set_clock,
    submit_drawing,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

_CLOCK = "2026-03-02T08:00:00Z"


def _order(api, order_number):
    return create_order(
        api,
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )


def test_the_posture_read_derives_the_rejected_submittal_reason(api):
    """PRD 2.6: "`SUBMITTAL_REJECTED` applies when the order carries at least one
    submittal drawing in status `REVISE_AND_RESUBMIT` and no submittal drawing in
    status `APPROVED` or `APPROVED_AS_NOTED`."

    Design: Corner/endpoints/order_posture_read_reports_submittal_rejected_reason_code
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-E1")
    drawing = create_drawing(api, order["id"], drawing_set_code="DS-100")
    submit_drawing(api, drawing["id"])
    begin_review(api, drawing["id"])
    disposition(
        api,
        drawing["id"],
        "REVISE_AND_RESUBMIT",
        USER_REVIEWER_1,
        notes_count=4,
        as_noted_changes_bill_of_material=False,
    )

    posture = validate_success(api.get_order_posture(order["id"], MATERIALS_PLANNER))
    assert posture["production_posture"] == "RESTRICTED"
    assert posture["posture_reason_codes"] == ["SUBMITTAL_REJECTED"]
    assert posture["engineering_status"] == "SUBMITTAL_IN_REVIEW"
    assert posture["fulfillment_status"] == "PLANNING"

    rejected = validate_success(api.get_submittal_drawing(drawing["id"], PLANT_ADMIN))
    assert rejected["status"] == "REVISE_AND_RESUBMIT"
    assert rejected["notes_count"] == 4


def test_the_money_identity_collapses_to_the_contract_on_a_fresh_order(api):
    """PRD 3.1: the financial-summary read returns "`contract_value_cents`,
    `escalation_accepted_total_cents`, `warranty_credit_total_cents`,
    `net_contract_value_cents` and `billed_to_date_cents` together."

    Design: Corner/endpoints/financial_summary_read_on_untouched_order_reports_zero_escalation_and_zero_billing
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-E2")

    summary = validate_success(
        api.get_order_financial_summary(order["id"], CONTRACT_ADMIN)
    )
    assert summary["contract_value_cents"] == 4000000
    assert summary["escalation_accepted_total_cents"] == 0
    assert summary["warranty_credit_total_cents"] == 0
    assert summary["net_contract_value_cents"] == 4000000
    assert summary["billed_to_date_cents"] == 0


def test_amending_the_commercial_header_re_derives_the_net_value_in_place(api):
    """PRD 3.1: "Commercial header amendment is a `ContractAdmin` or `PlantAdmin`
    privilege and accepts an optional `customer_name`, `contract_value_cents`,
    `promised_ship_at` and `owning_sales_user_id`; amending re-derives
    `net_contract_value_cents` and increments the order's `version`."

    Design: Corner/endpoints/patch_engineered_order_updates_contract_value_and_recomputes_net_value
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-E3")

    amended = validate_success(
        api.patch_engineered_order(
            order["id"],
            {
                "customer_name": "Riverbend Utility District 4",
                "contract_value_cents": 4500000,
            },
            CONTRACT_ADMIN,
        )
    )
    assert amended["customer_name"] == "Riverbend Utility District 4"
    assert amended["contract_value_cents"] == 4500000
    assert amended["net_contract_value_cents"] == 4500000
    assert amended["order_number"] == "ORD-CORNER-E3"
    assert amended["engineering_status"] == "ENG_OPEN"
    assert amended["fulfillment_status"] == "PLANNING"


def test_a_childless_sub_resource_answers_with_a_page_not_a_not_found(api):
    """PRD 2.3: "List responses carry `response_type` of `"array"` and populate all
    four pagination fields in `meta`"; `limit` "defaults to 10 when omitted" and
    `offset` "defaults to 0".

    Design: Corner/endpoints/order_submittal_drawings_subresource_on_fresh_order_returns_empty_array
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-E4")

    response = api.list_order_submittal_drawings(order["id"], DESIGN_ENGINEER)
    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "array"
    assert body["data"] == []
    assert_pagination_defaults(body["meta"], 0)


def test_the_status_filter_partitions_the_global_drawing_list(api):
    """PRD 2.3: "`total_count` is the number of rows matching the filter before
    pagination is applied"; PRD 3.2: drawings can be listed "globally with optional
    filters on `engineered_order_id`, `supersedes_drawing_id`, `status` and
    `revision_round`".

    Design: Corner/endpoints/submittal_drawing_status_filter_excludes_non_matching_rows
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-E5")
    drawing = create_drawing(api, order["id"], drawing_set_code="DS-100")
    submit_drawing(api, drawing["id"])

    empty = api.list_submittal_drawings(
        DESIGN_ENGINEER, {"engineered_order_id": order["id"], "status": "DRAFT"}
    ).json()
    assert empty["data"] == []
    assert empty["meta"]["total_count"] == 0

    matching = api.list_submittal_drawings(
        DESIGN_ENGINEER, {"engineered_order_id": order["id"], "status": "SUBMITTED"}
    ).json()
    assert matching["meta"]["total_count"] == 1
    assert matching["data"][0]["id"] == drawing["id"]
    assert matching["data"][0]["status"] == "SUBMITTED"
    assert matching["data"][0]["revision_round"] == 1


def test_an_action_endpoint_resolves_its_path_id_before_any_rule(api):
    """PRD 2.5: "a submittal drawing, `ERR_DRAWING_NOT_FOUND`... All twenty are
    HTTP 404"; PRD 2.11 evaluates "existence resolution (7–26)" before "state
    preconditions (34–41)".

    Design: Corner/endpoints/submit_action_on_unknown_drawing_id_returns_drawing_not_found
    """
    set_clock(api, _CLOCK)

    response = api.submit_drawing(NON_EXISTENT_UUID, {}, DESIGN_ENGINEER)
    validate_error(response, ApiErrorId.DRAWING_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"


def test_releasing_a_quarantine_that_was_never_imposed_is_not_a_no_op(api):
    """PRD 2.11: "a row whose current status is not a legal source for the
    requested transition yields `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"; PRD 3.4:
    "A `QualityEngineer` may lift the quarantine, moving the component
    `QUARANTINED → ACTIVE` and clearing `quarantine_reason`".

    Design: Corner/endpoints/release_quarantine_on_active_component_returns_invalid_state_transition
    """
    set_clock(api, _CLOCK)
    supplier = create_supplier(
        api,
        supplier_code="SUP-E7-01",
        legal_name="Copperline Windings AG",
        region="NA",
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="PN-E7-01",
        category="VACUUM_INTERRUPTER",
        lead_time_days=60,
        quantity_on_hand=4,
        allocation_policy="PREEMPTIBLE",
    )
    assert component["status"] == "ACTIVE"

    validate_error(
        api.release_component_quarantine(component["id"], {}, QUALITY_ENGINEER),
        ApiErrorId.INVALID_STATE_TRANSITION,
        409,
    )
    unchanged = validate_success(
        api.get_long_lead_component(component["id"], QUALITY_ENGINEER)
    )
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["quarantine_reason"] is None
