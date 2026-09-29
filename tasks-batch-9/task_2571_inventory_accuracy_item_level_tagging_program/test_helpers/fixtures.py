"""
Composite fixtures.

The harness gives every test an empty database, so each of these functions
builds its preconditions from scratch using only endpoints the PRD declares.
Setup steps use the lenient `get_success_data` validator: a broken setup should
fail loudly as a setup error rather than masquerade as an assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    PERIOD_END,
    PERIOD_SALES_AT_COST_CENTS,
    PERIOD_START,
    WINDOW_END,
    WINDOW_START,
)
from .test_users import (
    ADMIN,
    ANALYST,
    CONTROLLER,
    SUPERVISOR,
    USER_ANALYST_1,
    make_counter_headers,
    make_store_ops_headers,
    make_vendor_rep_headers,
)


# ---------------------------------------------------------------------------
# Single-row creators
# ---------------------------------------------------------------------------
def create_category(api, payload=None, headers=ADMIN) -> dict:
    return get_success_data(
        api.create_category(payload or f.apparel_category_payload(), headers)
    )


def create_store(api, payload=None, headers=ADMIN) -> dict:
    return get_success_data(api.create_store(payload or f.store_payload(), headers))


def create_vendor(api, payload=None, headers=ADMIN) -> dict:
    return get_success_data(api.create_vendor(payload or f.vendor_payload(), headers))


def create_counter_firm(api, payload=None, headers=ADMIN) -> dict:
    return get_success_data(
        api.create_counter_firm(payload or f.counter_firm_payload(), headers)
    )


def create_item(api, payload, headers=ADMIN) -> dict:
    return get_success_data(api.create_item(payload, headers))


def create_position(api, store_id, item_id, baseline=100, reserved=0, headers=ADMIN) -> dict:
    return get_success_data(
        api.create_stock_position(
            f.stock_position_payload(
                store_id,
                item_id,
                baseline_on_hand_units=baseline,
                reserved_units=reserved,
            ),
            headers,
        )
    )


def create_shrink_period(
    api,
    store_id,
    period_start=PERIOD_START,
    period_end=PERIOD_END,
    sales_at_cost_cents=PERIOD_SALES_AT_COST_CENTS,
    headers=CONTROLLER,
) -> dict:
    return get_success_data(
        api.create_shrink_period(
            f.shrink_period_payload(
                store_id,
                period_start=period_start,
                period_end=period_end,
                sales_at_cost_cents=sales_at_cost_cents,
            ),
            headers,
        )
    )


def create_schedule(
    api,
    store_id,
    category_id,
    reader_mode="HANDHELD",
    first_due_date="2026-08-01",
    cadence_days=30,
    headers=ANALYST,
) -> dict:
    return get_success_data(
        api.create_count_schedule(
            f.count_schedule_payload(
                store_id,
                category_id,
                reader_mode=reader_mode,
                first_due_date=first_due_date,
                cadence_days=cadence_days,
            ),
            headers,
        )
    )


def create_task(
    api,
    schedule_id,
    reader_mode="HANDHELD",
    window_start=WINDOW_START,
    window_end=WINDOW_END,
    headers=ANALYST,
) -> dict:
    return get_success_data(
        api.create_count_task(
            f.count_task_payload(
                schedule_id,
                reader_mode=reader_mode,
                window_start=window_start,
                window_end=window_end,
            ),
            headers,
        )
    )


def start_task(api, task_id, headers=ANALYST) -> dict:
    return get_success_data(api.start_count_task(task_id, headers))


def add_line(api, task_id, item_id, counted_units, read_mode="HANDHELD", headers=ANALYST) -> dict:
    return get_success_data(
        api.create_count_line(
            task_id,
            f.count_line_payload(item_id, counted_units, read_mode_used=read_mode),
            headers,
        )
    )


def submit_task(api, task_id, headers=ANALYST) -> dict:
    return get_success_data(api.submit_count_task(task_id, headers))


def position_version(api, position_id, headers=ANALYST) -> int:
    return get_success_data(api.get_stock_position(position_id, headers))["version"]


def read_position(api, position_id, headers=ANALYST) -> dict:
    return get_success_data(api.get_stock_position(position_id, headers))


def read_task(api, task_id, headers=ANALYST) -> dict:
    return get_success_data(api.get_count_task(task_id, headers))


def read_investigation(api, investigation_id, headers=SUPERVISOR) -> dict:
    return get_success_data(api.get_investigation(investigation_id, headers))


def read_adjustment(api, adjustment_id, headers=SUPERVISOR) -> dict:
    return get_success_data(api.get_adjustment(adjustment_id, headers))


def read_attribution(api, shrink_period_id, headers=CONTROLLER) -> dict:
    return get_success_data(
        api.get_shrink_period_attribution(shrink_period_id, headers)
    )


def read_eligibility(api, store_id, headers=ANALYST) -> dict:
    return get_success_data(api.get_store_fulfillment_eligibility(store_id, headers))


def read_vendor(api, vendor_id, headers=CONTROLLER) -> dict:
    return get_success_data(api.get_vendor(vendor_id, headers))


def read_tag_batch(api, tag_batch_id, headers=SUPERVISOR) -> dict:
    return get_success_data(api.get_tag_batch(tag_batch_id, headers))


def read_schedule(api, schedule_id, headers=ANALYST) -> dict:
    return get_success_data(api.get_count_schedule(schedule_id, headers))


def read_physical_inventory(api, physical_inventory_id, headers=CONTROLLER) -> dict:
    return get_success_data(
        api.get_physical_inventory(physical_inventory_id, headers)
    )


def investigation_for_line(api, count_line_id, headers=SUPERVISOR) -> dict:
    """The submit step opens investigations; find the one for a given line."""
    body = get_success_data(
        api.list_investigations(headers, {"count_line_id": count_line_id})
    )
    assert isinstance(body, list) and body, (
        f"No investigation was opened for count line {count_line_id}"
    )
    return body[0]


# ---------------------------------------------------------------------------
# Investigation drivers
# ---------------------------------------------------------------------------
def drive_to_in_review(api, investigation_id, investigator_id=USER_ANALYST_1, headers=ANALYST) -> dict:
    return get_success_data(
        api.assign_investigation(
            investigation_id, f.assign_payload(investigator_id), headers
        )
    )


def drive_to_cause_proposed(
    api,
    investigation_id,
    root_cause="THEFT",
    investigator_id=USER_ANALYST_1,
    headers=ANALYST,
) -> dict:
    assigned = drive_to_in_review(api, investigation_id, investigator_id, headers)
    return get_success_data(
        api.propose_cause(
            investigation_id,
            f.propose_cause_payload(root_cause, assigned["version"]),
            headers,
        )
    )


def drive_to_cause_approved(
    api,
    investigation_id,
    root_cause="THEFT",
    investigator_id=USER_ANALYST_1,
    proposer_headers=ANALYST,
    approver_headers=SUPERVISOR,
) -> dict:
    drive_to_cause_proposed(
        api, investigation_id, root_cause, investigator_id, proposer_headers
    )
    return get_success_data(api.approve_cause(investigation_id, approver_headers))


def drive_to_closed(
    api,
    investigation_id,
    root_cause="THEFT",
    investigator_id=USER_ANALYST_1,
    proposer_headers=ANALYST,
    approver_headers=SUPERVISOR,
) -> dict:
    drive_to_cause_approved(
        api,
        investigation_id,
        root_cause,
        investigator_id,
        proposer_headers,
        approver_headers,
    )
    return get_success_data(api.close_investigation(investigation_id, approver_headers))


# ---------------------------------------------------------------------------
# Adjustment drivers
# ---------------------------------------------------------------------------
def create_adjustment(
    api,
    position_id,
    delta_units,
    reason_code="COUNT_VARIANCE",
    investigation_id=None,
    headers=ANALYST,
    expected_version=None,
) -> dict:
    version = (
        expected_version
        if expected_version is not None
        else position_version(api, position_id, headers)
    )
    payload = f.adjustment_payload(delta_units, version, reason_code=reason_code)
    if investigation_id is not None:
        payload["investigation_id"] = investigation_id
    return get_success_data(api.create_adjustment(position_id, payload, headers))


def post_adjustment(api, adjustment_id, headers=SUPERVISOR) -> dict:
    return get_success_data(api.post_adjustment(adjustment_id, headers))


# ---------------------------------------------------------------------------
# Composite worlds
# ---------------------------------------------------------------------------
def apparel_reference_world(api, store_payload=None, baseline=100) -> dict:
    """APPAREL category, one store, one vendor, item TEE-001 and its position."""
    category = create_category(api, f.apparel_category_payload())
    store = create_store(api, store_payload or f.store_payload())
    vendor = create_vendor(api)
    item = create_item(api, f.item_payload(category["id"], vendor["id"]))
    position = create_position(api, store["id"], item["id"], baseline=baseline)
    return {
        "category_id": category["id"],
        "store_id": store["id"],
        "vendor_id": vendor["id"],
        "item_id": item["id"],
        "position_id": position["id"],
        "category": category,
        "store": store,
        "vendor": vendor,
        "item": item,
        "position": position,
    }


def apparel_two_item_world(api, baseline_a=100, baseline_b=50) -> dict:
    """APPAREL with TEE-001 and TEE-002, both stocked at one store."""
    world = apparel_reference_world(api, baseline=baseline_a)
    item_b = create_item(
        api, f.tee2_item_payload(world["category_id"], world["vendor_id"])
    )
    position_b = create_position(
        api, world["store_id"], item_b["id"], baseline=baseline_b
    )
    world["item_b_id"] = item_b["id"]
    world["position_b_id"] = position_b["id"]
    world["item_b"] = item_b
    world["position_b"] = position_b
    return world


def home_reference_world(api, item_payload_builder=None, baseline=100) -> dict:
    """HOME category with a zero-uplift valuation, one store, one vendor, one item."""
    category = create_category(api, f.home_category_payload())
    store = create_store(api)
    vendor = create_vendor(api)
    builder = item_payload_builder or f.sofa_item_payload
    item = create_item(api, builder(category["id"], vendor["id"]))
    position = create_position(api, store["id"], item["id"], baseline=baseline)
    return {
        "category_id": category["id"],
        "store_id": store["id"],
        "vendor_id": vendor["id"],
        "item_id": item["id"],
        "position_id": position["id"],
        "category": category,
        "store": store,
        "vendor": vendor,
        "item": item,
        "position": position,
    }


def with_shrink_period(api, world, **kwargs) -> dict:
    period = create_shrink_period(api, world["store_id"], **kwargs)
    world["shrink_period_id"] = period["id"]
    world["shrink_period"] = period
    return world


def with_started_task(
    api,
    world,
    reader_mode="HANDHELD",
    first_due_date="2026-08-01",
    cadence_days=30,
    window_start=WINDOW_START,
    window_end=WINDOW_END,
) -> dict:
    schedule = create_schedule(
        api,
        world["store_id"],
        world["category_id"],
        reader_mode=reader_mode,
        first_due_date=first_due_date,
        cadence_days=cadence_days,
    )
    task = create_task(
        api,
        schedule["id"],
        reader_mode=reader_mode,
        window_start=window_start,
        window_end=window_end,
    )
    started = start_task(api, task["id"])
    world["schedule_id"] = schedule["id"]
    world["task_id"] = task["id"]
    world["schedule"] = schedule
    world["task"] = started
    return world


def counted_variance_world(api, counted_units=105, baseline=100) -> dict:
    """
    One APPAREL position counted out of tolerance and submitted, so exactly one
    OPEN investigation exists inside a covering OPEN shrink period.
    """
    world = apparel_reference_world(api, baseline=baseline)
    with_shrink_period(api, world)
    with_started_task(api, world)
    line = add_line(api, world["task_id"], world["item_id"], counted_units)
    submitted = submit_task(api, world["task_id"])
    investigation = investigation_for_line(api, line["id"])
    world["line_id"] = line["id"]
    world["line"] = line
    world["submitted_task"] = submitted
    world["investigation_id"] = investigation["id"]
    world["investigation"] = investigation
    return world


def closed_theft_world(api, counted_units=105, baseline=100) -> dict:
    """A counted variance whose investigation is driven all the way to CLOSED."""
    world = counted_variance_world(api, counted_units=counted_units, baseline=baseline)
    world["closed_investigation"] = drive_to_closed(
        api, world["investigation_id"], "THEFT"
    )
    return world


def cause_approved_world(api, root_cause="THEFT", counted_units=105, baseline=100) -> dict:
    """A counted variance parked in CAUSE_APPROVED, deliberately not closed."""
    world = counted_variance_world(api, counted_units=counted_units, baseline=baseline)
    world["approved_investigation"] = drive_to_cause_approved(
        api, world["investigation_id"], root_cause
    )
    return world


def vendor_shortage_world(api, counted_units=141, baseline=100) -> dict:
    """
    A HOME shortage of `counted_units - baseline` units at 5000 cents each,
    attributed to VENDOR_SHORTAGE and closed, inside an OPEN shrink period.
    """
    world = home_reference_world(api, baseline=baseline)
    with_shrink_period(api, world)
    with_started_task(api, world)
    line = add_line(api, world["task_id"], world["item_id"], counted_units)
    submit_task(api, world["task_id"])
    investigation = investigation_for_line(api, line["id"])
    world["line_id"] = line["id"]
    world["investigation_id"] = investigation["id"]
    world["closed_investigation"] = drive_to_closed(
        api, investigation["id"], "VENDOR_SHORTAGE"
    )
    return world


def chargeback_issued_world(api) -> dict:
    """A vendor whose ledger has already taken one chargeback out of one period."""
    world = vendor_shortage_world(api)
    world["chargeback"] = get_success_data(
        api.create_chargeback(
            world["vendor_id"], f.chargeback_payload(world["shrink_period_id"]), CONTROLLER
        )
    )
    return world


def encoded_tag_batch_world(api, quantity=1000, baseline=100) -> dict:
    """A vendor tag batch encoded and received at its destination store."""
    world = apparel_reference_world(api, baseline=baseline)
    vendor_headers = make_vendor_rep_headers(world["vendor_id"])
    store_headers = make_store_ops_headers(world["store_id"])
    batch = get_success_data(
        api.create_tag_batch(
            f.tag_batch_payload(
                world["vendor_id"],
                world["item_id"],
                world["store_id"],
                quantity_encoded=quantity,
            ),
            vendor_headers,
        )
    )
    encoded = get_success_data(
        api.encode_tag_batch(batch["id"], f.encode_payload(), vendor_headers)
    )
    received = get_success_data(api.receive_tag_batch(batch["id"], store_headers))
    world["batch_id"] = batch["id"]
    world["batch"] = batch
    world["encoded_batch"] = encoded
    world["received_batch"] = received
    world["vendor_headers"] = vendor_headers
    world["store_headers"] = store_headers
    return world


def failed_verification_world(api, sampled=50, readable=48) -> dict:
    """An encoded and received batch whose verification failed the read-rate gate."""
    world = encoded_tag_batch_world(api)
    world["failed_batch"] = get_success_data(
        api.verify_tag_batch(
            world["batch_id"],
            f.verify_payload(sampled_units=sampled, readable_units=readable),
            world["store_headers"],
        )
    )
    return world


def physical_inventory_world(
    api,
    baseline=100,
    scheduled_start_date="2026-09-10",
    scheduled_end_date="2026-09-12",
    recount_threshold_bps=150,
    with_period=True,
) -> dict:
    """A PLANNED physical inventory at a store with one APPAREL position."""
    world = apparel_reference_world(api, baseline=baseline)
    firm = create_counter_firm(api)
    if with_period:
        with_shrink_period(api, world)
    inventory = get_success_data(
        api.create_physical_inventory(
            f.physical_inventory_payload(
                world["store_id"],
                firm["id"],
                scheduled_start_date=scheduled_start_date,
                scheduled_end_date=scheduled_end_date,
                recount_threshold_bps=recount_threshold_bps,
            ),
            CONTROLLER,
        )
    )
    world["counter_firm_id"] = firm["id"]
    world["counter_firm"] = firm
    world["counter_headers"] = make_counter_headers(firm["id"])
    world["physical_inventory_id"] = inventory["id"]
    world["physical_inventory"] = inventory
    return world
