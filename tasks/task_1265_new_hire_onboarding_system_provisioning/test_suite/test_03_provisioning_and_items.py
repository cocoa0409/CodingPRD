"""Provisioning order lifecycle, compound status, and SLA elapsed variants."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    setup_case_in_provisioning,
    fulfill_order,
    get_case_orders,
    get_case_trainings,
    get_case_checkins,
    get_summary,
    create_orientation_session_payload,
)

HR = TEST_USERS["hr_admin_headers"]
IT = TEST_USERS["it_provisioner_headers"]


def test_order_compound_status_bubbles_from_items(api):
    """PRD §3.5: "From then on the order's status is a compound derived from its
    items: it becomes `IN_PROGRESS` the moment the first item leaves `PENDING`;
    it becomes `ATTENTION_REQUIRED` whenever at least one item is `BLOCKED` while
    not all items are `DONE`; it returns from `ATTENTION_REQUIRED` to
    `IN_PROGRESS` once no item remains `BLOCKED` and not all items are `DONE`;
    and it reaches `FULFILLED` — from `SUBMITTED`, `IN_PROGRESS`, or
    `ATTENTION_REQUIRED` alike — the moment every item is `DONE`, stamping
    `fulfilled_at` and re-evaluating the case's day-one gate. Every entry into
    or exit from `ATTENTION_REQUIRED` recomputes the case's health score, since
    the attention term carries a 20-point penalty."

    Design: Corner/state_machines/order_compound_status_bubbles_from_items
    """
    ctx = setup_case_in_provisioning()
    case_id = ctx["case"]["id"]
    order = ctx["order"]
    i1, i2 = ctx["items"][0], ctx["items"][1]

    get_success_data(api.submit_provisioning_order(order["id"], HR))

    # First item start -> IN_PROGRESS.
    get_success_data(api.transition_provisioning_item(i1["id"], {"to": "IN_FULFILLMENT"}, IT))
    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["status"] == "IN_PROGRESS"

    # Block i1 -> ATTENTION_REQUIRED and case health drops to 80 (100 - 20).
    get_success_data(api.transition_provisioning_item(
        i1["id"], {"to": "BLOCKED", "blocked_reason": "stockout"}, IT))
    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["status"] == "ATTENTION_REQUIRED"
    summary = get_summary(case_id)
    assert summary["health_score"] == 80

    # Retry out of BLOCKED -> IN_PROGRESS; health restored to 100.
    get_success_data(api.transition_provisioning_item(i1["id"], {"to": "IN_FULFILLMENT"}, IT))
    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["status"] == "IN_PROGRESS"

    # Drive all items DONE -> FULFILLED; health returns to 100.
    get_success_data(api.transition_provisioning_item(i1["id"], {"to": "DONE"}, IT))
    get_success_data(api.transition_provisioning_item(i2["id"], {"to": "IN_FULFILLMENT"}, IT))
    get_success_data(api.transition_provisioning_item(i2["id"], {"to": "DONE"}, IT))
    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["status"] == "FULFILLED"
    summary = get_summary(case_id)
    assert summary["health_score"] == 100


def test_item_pending_to_done_direct_rejected(api):
    """PRD §3.5: "only four item transitions exist: `PENDING` to
    `IN_FULFILLMENT`, `IN_FULFILLMENT` to `DONE`, `IN_FULFILLMENT` to `BLOCKED`,
    and `BLOCKED` back to `IN_FULFILLMENT` — the retry cycle, which clears the
    item's `blocked_reason`. Any other from–to pair is rejected with
    `ERR_INVALID_ITEM_TRANSITION`."

    Design: Corner/state_machines/item_pending_to_done_direct_rejected
    """
    ctx = setup_case_in_provisioning()
    order = ctx["order"]
    i1 = ctx["items"][0]
    get_success_data(api.submit_provisioning_order(order["id"], HR))
    resp = api.transition_provisioning_item(i1["id"], {"to": "DONE"}, IT)
    validate_error(resp, ApiErrorId.ERR_INVALID_ITEM_TRANSITION)


def test_order_resubmit_and_item_transition_on_draft_rejected(api):
    """PRD §3.5: "An `HRAdmin` submits the order — only a `DRAFT` order can be
    submitted, otherwise `ERR_ORDER_NOT_DRAFT`"
    PRD §3.5: "The order must be in `SUBMITTED`, `IN_PROGRESS`, or
    `ATTENTION_REQUIRED` (`ERR_ORDER_NOT_ACTIVE`)"

    Design: Corner/state_machines/order_resubmit_and_item_transition_on_draft_rejected
    """
    ctx = setup_case_in_provisioning()
    order = ctx["order"]
    i1 = ctx["items"][0]

    # Item transition while order DRAFT -> ERR_ORDER_NOT_ACTIVE.
    resp = api.transition_provisioning_item(i1["id"], {"to": "IN_FULFILLMENT"}, IT)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACTIVE)

    # First submit succeeds; second -> ERR_ORDER_NOT_DRAFT.
    get_success_data(api.submit_provisioning_order(order["id"], HR))
    resp2 = api.submit_provisioning_order(order["id"], HR)
    validate_error(resp2, ApiErrorId.ERR_ORDER_NOT_DRAFT)


def test_provisioning_sla_calendar_vs_business_hours(api):
    """PRD §3.5: "The calendar variant, `elapsed_calendar_hours`, counts every
    hour in that interval; the business variant, `elapsed_business_hours`,
    counts only hours whose UTC weekday falls Monday through Friday — Saturday
    and Sunday hours are excluded, and holidays are not modelled. The breach
    flags compare strictly: `sla_breached_calendar` is true only when
    `elapsed_calendar_hours` is strictly greater than `sla_hours`, and
    `sla_breached_business` only when `elapsed_business_hours` is strictly
    greater"

    Friday 2026-05-08T10:00:00Z submit; read at Monday 2026-05-11T11:00:00Z.
    Calendar = 73.0h; business = 14h Fri + 11h Mon = 25.0h.

    Design: Difficulty/dual_variant_calc/provisioning_sla_calendar_vs_business_hours
    """
    ctx = setup_case_in_provisioning()
    order = ctx["order"]
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-08T10:00:00Z"}, HR))
    get_success_data(api.submit_provisioning_order(order["id"], HR))
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-11T11:00:00Z"}, HR))

    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["elapsed_calendar_hours"] == 73.0
    assert o["elapsed_business_hours"] == 25.0
    assert o["sla_breached_calendar"] is True
    assert o["sla_breached_business"] is False
    assert o["sla_hours"] == 48


def test_provisioning_sla_strictly_greater_boundary(api):
    """PRD §3.5: "an elapsed value exactly equal to `sla_hours` is not a breach
    under either variant."

    Second test under the same difficulty instance.

    Design: Difficulty/dual_variant_calc/provisioning_sla_calendar_vs_business_hours
    """
    ctx = setup_case_in_provisioning()
    order = ctx["order"]
    # Wednesday submit; read exactly 48 hours later (Friday).
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-06T10:00:00Z"}, HR))
    get_success_data(api.submit_provisioning_order(order["id"], HR))
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-08T10:00:00Z"}, HR))

    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["elapsed_calendar_hours"] == 48.0
    assert o["sla_breached_calendar"] is False
    # Interval is all weekdays -> business equals calendar here.
    assert o["elapsed_business_hours"] == 48.0
    assert o["sla_breached_business"] is False


def test_sla_exactly_48_hours_is_not_a_breach(api):
    """PRD §3.5: "an elapsed value exactly equal to `sla_hours` is not a breach
    under either variant."

    Design: Corner/calculations/sla_exactly_48_hours_is_not_a_breach
    """
    ctx = setup_case_in_provisioning()
    order = ctx["order"]
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-06T10:00:00Z"}, HR))
    get_success_data(api.submit_provisioning_order(order["id"], HR))
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-08T10:00:00Z"}, HR))
    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["elapsed_calendar_hours"] == 48.0
    assert o["sla_breached_calendar"] is False
    assert o["elapsed_business_hours"] == 48.0
    assert o["sla_breached_business"] is False
