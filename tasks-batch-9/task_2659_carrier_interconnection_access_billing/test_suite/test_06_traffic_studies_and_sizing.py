"""Traffic studies: the blocking threshold, trunk sizing and the augment cascade."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import assert_pct, assert_trunk_group_statuses
from test_helpers.constants import (
    LATA_HOUSTON,
    POI_CLLI_HOUSTON,
)
from test_helpers.factories import measurement_payload
from test_helpers.fixtures import (
    latest_pending_order,
    read_agreement,
    read_trunk_group,
    record_measurement,
    setup_effective_agreement,
    setup_effective_agreement_with_in_service_trunks,
    setup_in_service_trunk_group,
)


def _orders_for(api, headers, trunk_group_id, status=None):
    """Every augment order raised against one trunk group, with its total count."""
    params = {"trunk_group_id": trunk_group_id}
    if status is not None:
        params["status"] = status
    return validate_paginated(api.list_augment_orders(headers, params=params))


def test_carrier_representative_may_post_a_traffic_measurement(api, planner_headers):
    """The counterparty records a 2.00% study that sizes trunks but orders nothing.

    PRD 3.4: "Capacity management is driven by **traffic studies**. Either a `NetworkPlanner` or the counterparty's `CarrierRepresentative` records a study against a trunk group, and a study may only be recorded while that trunk group's `service_status` is `IN_SERVICE`; a study against a trunk group in `REQUESTED`, `PROVISIONED`, `DISCONNECT_PENDING` or `DISCONNECTED` is refused with `ERR_INVALID_TRUNK_GROUP_STATE`."
    PRD 3.4: "Otherwise `blocking_pct` is the number of blocked calls multiplied by one hundred and divided by the number of offered calls, rounded half up to two decimal places."
    PRD 3.4: "If `blocking_pct` is **below** three percent there is no action: `requested_additional_trunks` is 0, no augment order is created, and the trunk group's `augment_status` does not move. The study's own `augment_triggered` flag is false."
    PRD 3.4: "The sizing load is the greater of two figures: the measured `busy_hour_ccs`, and the trunk group's committed `forecast_busy_hour_ccs` grown by fifteen percent — that is, multiplied by 1.15 and rounded half up to two decimal places. Dividing the sizing load by the per-trunk carrying capacity and rounding **up** to the next whole number gives `required_trunks`."

    Design: Corner/rbac/carrier_representative_may_post_a_traffic_measurement
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]

    response = api.create_traffic_measurement(
        trunk_group_id,
        measurement_payload(blocked_calls=200),
        state["rep_headers"],
    )
    measurement = validate_success(response, expected_status=201)

    assert_pct(measurement["blocking_pct"], 2.00, "blocking_pct")
    assert measurement["augment_triggered"] is False
    assert measurement["required_trunks_at_measurement"] == 68, (
        "the sizing load 2100.00 CCS over 31 CCS per two-way trunk rounds up to 68"
    )

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "NONE")
    assert trunk_group["open_augment_order_count"] == 0

    _, meta = _orders_for(api, planner_headers, trunk_group_id)
    assert meta["total_count"] == 0, "a sub-threshold study orders no capacity"


def test_augment_at_the_poi_ceiling_blocks_instead_of_ordering(api, planner_headers):
    """A breach whose DS1 block would overrun the facility moves to AUGMENT_BLOCKED.

    PRD 3.4: "That quantity is then tested against the shared facility. Sum `provisioned_trunks` over the sibling trunk groups sharing the same agreement and `poi_clli_code` whose `service_status` is `PROVISIONED` or `IN_SERVICE`, add `requested_additional_trunks` over those same trunk groups' augment orders whose `status` is `PENDING` or `ACCEPTED`, and add the newly sized quantity."
    PRD 3.4: "If that total exceeds the agreement's `poi_facility_capacity_trunks`, the augment cannot be placed: `requested_additional_trunks` falls back to 0, no augment order is created, the trunk group's `augment_status` moves to `AUGMENT_BLOCKED`, and the agreement's `capacity_posture` is recomputed to `BLOCKED`."
    PRD 3.4: "In the grooming and blocked branches the trunk group's `latest_blocking_pct` and `required_trunks` are still updated and its `version` still increments; only the order creation and the pending-count movement are absent."
    PRD 3.4: "It is `BLOCKED` whenever any of the agreement's trunk groups has `augment_status` `AUGMENT_BLOCKED`; failing that, it is `CONSTRAINED` whenever `poi_augment_pending_count` is greater than zero; otherwise it is `NORMAL`."

    Design: Corner/state_machines/augment_at_the_poi_ceiling_blocks_instead_of_ordering
    """
    state = setup_effective_agreement_with_in_service_trunks(
        api, provisioned_trunks=48, capacity_trunks=48
    )
    trunk_group_id = state["trunk_group_id"]

    measurement = record_measurement(api, trunk_group_id)

    assert_pct(measurement["blocking_pct"], 3.00, "blocking_pct")
    assert measurement["required_trunks_at_measurement"] == 68
    assert measurement["augment_triggered"] is False, (
        "the 24-trunk block would take the point of interconnection to 72 against a ceiling of 48"
    )

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "AUGMENT_BLOCKED")
    assert trunk_group["open_augment_order_count"] == 0
    assert trunk_group["required_trunks"] == 68
    assert trunk_group["provisioned_trunks"] == 48

    _, meta = _orders_for(api, planner_headers, trunk_group_id)
    assert meta["total_count"] == 0

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["capacity_posture"] == "BLOCKED"
    assert agreement["poi_augment_pending_count"] == 0


def test_trunk_sizing_uses_the_direction_specific_carrying_capacity(api, planner_headers):
    """Two groups at one CCS load size to 68 two-way trunks and 78 one-way trunks.

    PRD 3.4: "**Sizing.** The per-trunk carrying capacity is chosen from the trunk group's `direction`: a trunk group whose `direction` is `TWO_WAY` carries **31** hundred-call-seconds of busy-hour load per trunk, while one whose `direction` is `ONE_WAY_OUTBOUND` or `ONE_WAY_INBOUND` carries **27** per trunk."
    PRD 3.4: "The sizing load is the greater of two figures: the measured `busy_hour_ccs`, and the trunk group's committed `forecast_busy_hour_ccs` grown by fifteen percent — that is, multiplied by 1.15 and rounded half up to two decimal places. Dividing the sizing load by the per-trunk carrying capacity and rounding **up** to the next whole number gives `required_trunks`."
    PRD 3.4: "If blocking breached the threshold and the shortfall is positive, the ordered quantity is the shortfall rounded **up** to a whole number of DS1s and then multiplied back out — that is, the shortfall divided by 24, rounded up to the next whole number, multiplied by 24."

    Design: Difficulty/combinatorial_formula/trunk_sizing_nested_max_with_direction_and_ds1_quantization
    """
    state = setup_effective_agreement(api)
    agreement_id = state["agreement_id"]
    two_way = setup_in_service_trunk_group(api, agreement_id, 48)
    one_way = setup_in_service_trunk_group(
        api,
        agreement_id,
        48,
        trunk_group_serial="TG-DLLS-OUT-002",
        direction="ONE_WAY_OUTBOUND",
    )

    record_measurement(api, two_way["id"])
    record_measurement(api, one_way["id"])

    sized_two_way = read_trunk_group(api, two_way["id"])
    assert_pct(sized_two_way["latest_blocking_pct"], 3.00, "latest_blocking_pct")
    assert sized_two_way["required_trunks"] == 68, (
        "the measured 2100.00 CCS beats the grown forecast 1380.00 and divides by 31"
    )
    assert_trunk_group_statuses(sized_two_way, "IN_SERVICE", "AUGMENT_ORDERED")
    assert sized_two_way["open_augment_order_count"] == 1

    sized_one_way = read_trunk_group(api, one_way["id"])
    assert sized_one_way["required_trunks"] == 78, (
        "the same 2100.00 CCS over 27 CCS per one-way trunk rounds up to 78"
    )
    assert_trunk_group_statuses(sized_one_way, "IN_SERVICE", "AUGMENT_ORDERED")

    two_way_order = latest_pending_order(api, two_way["id"])
    assert two_way_order["requested_additional_trunks"] == 24, (
        "a shortfall of 20 quantizes up to one DS1"
    )
    assert two_way_order["required_trunks_target"] == 68

    one_way_order = latest_pending_order(api, one_way["id"])
    assert one_way_order["requested_additional_trunks"] == 48, (
        "a shortfall of 30 quantizes up to two DS1 blocks"
    )
    assert one_way_order["required_trunks_target"] == 78

    agreement = read_agreement(api, agreement_id)
    assert agreement["poi_augment_pending_count"] == 2
    assert agreement["capacity_posture"] == "CONSTRAINED"


def test_trunk_sizing_takes_the_grown_forecast_when_it_beats_the_measurement(
    api, planner_headers
):
    """A 1000.00 CCS study still sizes to the 1380.00 grown forecast and orders one DS1.

    PRD 3.4: "The sizing load is the greater of two figures: the measured `busy_hour_ccs`, and the trunk group's committed `forecast_busy_hour_ccs` grown by fifteen percent — that is, multiplied by 1.15 and rounded half up to two decimal places. Dividing the sizing load by the per-trunk carrying capacity and rounding **up** to the next whole number gives `required_trunks`."
    PRD 3.4: "The shortfall is `required_trunks` minus the trunk group's current `provisioned_trunks`."
    PRD 3.4: "Because a `PENDING` order now exists, the third hop increments the agreement's `poi_augment_pending_count` by 1 and recomputes `capacity_posture` to `CONSTRAINED`."

    Design: Difficulty/combinatorial_formula/trunk_sizing_nested_max_with_direction_and_ds1_quantization
    """
    state = setup_effective_agreement(api)
    agreement_id = state["agreement_id"]
    dallas_two_way = setup_in_service_trunk_group(api, agreement_id, 48)
    dallas_one_way = setup_in_service_trunk_group(
        api,
        agreement_id,
        48,
        trunk_group_serial="TG-DLLS-OUT-002",
        direction="ONE_WAY_OUTBOUND",
    )
    houston = setup_in_service_trunk_group(
        api,
        agreement_id,
        24,
        trunk_group_serial="TG-HSTN-TWOWAY-003",
        poi_clli_code=POI_CLLI_HOUSTON,
        lata_code=LATA_HOUSTON,
    )

    record_measurement(api, dallas_two_way["id"])
    record_measurement(api, dallas_one_way["id"])
    houston_measurement = record_measurement(
        api, houston["id"], busy_hour_ccs=1000.00
    )

    assert_pct(houston_measurement["blocking_pct"], 3.00, "blocking_pct")
    assert houston_measurement["required_trunks_at_measurement"] == 45, (
        "1200.00 grown by 1.15 gives 1380.00, which over 31 CCS per trunk rounds up to 45"
    )
    assert houston_measurement["augment_triggered"] is True

    sized = read_trunk_group(api, houston["id"])
    assert sized["required_trunks"] == 45
    assert_trunk_group_statuses(sized, "IN_SERVICE", "AUGMENT_ORDERED")

    order = latest_pending_order(api, houston["id"])
    assert order["requested_additional_trunks"] == 24, (
        "a shortfall of 21 quantizes up to one DS1"
    )
    assert order["required_trunks_target"] == 45

    agreement = read_agreement(api, agreement_id)
    assert agreement["poi_augment_pending_count"] == 3
    assert agreement["capacity_posture"] == "CONSTRAINED"


def test_blocking_of_two_point_nine_nine_percent_orders_nothing(api, planner_headers):
    """A 2.99% study sizes the shortfall but holds the augment back.

    PRD 3.4: "The engineering threshold is **three percent**, and the comparison is inclusive: a `blocking_pct` of exactly 3.00 is a breach, while 2.99 is not."
    PRD 3.4: "If `blocking_pct` is **below** three percent there is no action: `requested_additional_trunks` is 0, no augment order is created, and the trunk group's `augment_status` does not move. The study's own `augment_triggered` flag is false."
    PRD 3.4: "In the grooming and blocked branches the trunk group's `latest_blocking_pct` and `required_trunks` are still updated and its `version` still increments; only the order creation and the pending-count movement are absent."

    Design: Difficulty/boundary_precision_check/blocking_pct_exactly_three_percent_triggers_augment
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]

    inert = record_measurement(
        api,
        trunk_group_id,
        measurement_period_start="2026-06-01T00:00:00.000Z",
        measurement_period_end="2026-06-30T00:00:00.000Z",
        blocked_calls=299,
    )

    assert_pct(inert["blocking_pct"], 2.99, "blocking_pct")
    assert inert["augment_triggered"] is False
    assert inert["required_trunks_at_measurement"] == 68, (
        "the shortfall existed; only the threshold held the order back"
    )

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "NONE")
    assert trunk_group["required_trunks"] == 68
    assert trunk_group["open_augment_order_count"] == 0

    _, meta = _orders_for(api, planner_headers, trunk_group_id)
    assert meta["total_count"] == 0

    assert read_agreement(api, state["agreement_id"])["poi_augment_pending_count"] == 0


def test_blocking_of_exactly_three_percent_triggers_the_augment(api, planner_headers):
    """The 3.00% study breaches where 2.99% did not, and only it raises the order.

    PRD 3.4: "The engineering threshold is **three percent**, and the comparison is inclusive: a `blocking_pct` of exactly 3.00 is a breach, while 2.99 is not."
    PRD 3.4: "In the first hop the new study row sets the trunk group's `latest_blocking_pct` and `required_trunks` from the calculation, snapshots the same computed figures onto itself as `blocking_pct` and `required_trunks_at_measurement` so that later studies never rewrite history, and moves `augment_status` to `AUGMENT_ORDERED` with `augment_triggered` true."
    PRD 3.4: "Because `augment_status` became `AUGMENT_ORDERED`, the second hop creates an augment order in status `PENDING`, carrying `trunk_group_id` pointing at the measured trunk group, `triggering_measurement_id` pointing at the new study, `requested_additional_trunks` and `required_trunks_target` from the same calculation, `committed_due_date`, `install_window_start`, `install_window_end`, `installed_trunks`, `rejection_reason` and `reversed_at` all null, and increments the trunk group's `open_augment_order_count` by 1."

    Design: Difficulty/boundary_precision_check/blocking_pct_exactly_three_percent_triggers_augment
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]

    inert = record_measurement(
        api,
        trunk_group_id,
        measurement_period_start="2026-06-01T00:00:00.000Z",
        measurement_period_end="2026-06-30T00:00:00.000Z",
        blocked_calls=299,
    )
    breach = record_measurement(api, trunk_group_id)

    assert_pct(inert["blocking_pct"], 2.99, "blocking_pct")
    assert inert["augment_triggered"] is False
    assert_pct(breach["blocking_pct"], 3.00, "blocking_pct")
    assert breach["augment_triggered"] is True
    assert breach["required_trunks_at_measurement"] == 68, (
        "the breaching study sizes identically to the inert one"
    )

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "AUGMENT_ORDERED")
    assert trunk_group["open_augment_order_count"] == 1

    rows, meta = _orders_for(api, planner_headers, trunk_group_id)
    assert meta["total_count"] == 1, "only the breaching study raised an order"
    assert rows[0]["triggering_measurement_id"] == breach["id"]

    assert read_agreement(api, state["agreement_id"])["poi_augment_pending_count"] == 1


def test_measurement_cascade_writes_the_trunk_group_and_the_new_order(
    api, planner_headers
):
    """Hops one and two: the study sizes the group and mints a PENDING order.

    PRD 3.4: "The augment-ordered branch is a **three-hop transitive cascade**, and each hop is caused by the previous hop's mutation rather than by the request."
    PRD 3.4: "In the first hop the new study row sets the trunk group's `latest_blocking_pct` and `required_trunks` from the calculation, snapshots the same computed figures onto itself as `blocking_pct` and `required_trunks_at_measurement` so that later studies never rewrite history, and moves `augment_status` to `AUGMENT_ORDERED` with `augment_triggered` true."
    PRD 3.4: "Because `augment_status` became `AUGMENT_ORDERED`, the second hop creates an augment order in status `PENDING`, carrying `trunk_group_id` pointing at the measured trunk group, `triggering_measurement_id` pointing at the new study, `requested_additional_trunks` and `required_trunks_target` from the same calculation, `committed_due_date`, `install_window_start`, `install_window_end`, `installed_trunks`, `rejection_reason` and `reversed_at` all null, and increments the trunk group's `open_augment_order_count` by 1."

    Design: Difficulty/transitive_cascade/measurement_cascade_trunk_group_to_order_to_agreement_posture
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]

    measurement = record_measurement(api, trunk_group_id)

    assert_pct(measurement["blocking_pct"], 3.00, "blocking_pct")
    assert measurement["required_trunks_at_measurement"] == 68
    assert measurement["augment_triggered"] is True

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert_pct(trunk_group["latest_blocking_pct"], 3.00, "latest_blocking_pct")
    assert trunk_group["required_trunks"] == 68
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "AUGMENT_ORDERED")
    assert trunk_group["open_augment_order_count"] == 1

    order = latest_pending_order(api, trunk_group_id)
    assert order["status"] == "PENDING"
    assert order["trunk_group_id"] == trunk_group_id
    assert order["triggering_measurement_id"] == measurement["id"]
    assert order["requested_additional_trunks"] == 24
    assert order["required_trunks_target"] == 68
    assert order["committed_due_date"] is None
    assert order["install_window_start"] is None
    assert order["install_window_end"] is None
    assert order["installed_trunks"] is None
    assert order["rejection_reason"] is None
    assert order["reversed_at"] is None


def test_measurement_cascade_reaches_the_agreement_posture(api, planner_headers):
    """Hop three: the new PENDING order constrains the agreement without adding trunks.

    PRD 3.4: "Because a `PENDING` order now exists, the third hop increments the agreement's `poi_augment_pending_count` by 1 and recomputes `capacity_posture` to `CONSTRAINED`."
    PRD 3.4: "The agreement's `capacity_posture` is a derived summary with a fixed precedence. It is `BLOCKED` whenever any of the agreement's trunk groups has `augment_status` `AUGMENT_BLOCKED`; failing that, it is `CONSTRAINED` whenever `poi_augment_pending_count` is greater than zero; otherwise it is `NORMAL`."
    PRD 3.4: "The trunk group's `version` increments by 1 across the whole operation, and the agreement's `version` increments by 1 whenever the posture changed."

    Design: Difficulty/transitive_cascade/measurement_cascade_trunk_group_to_order_to_agreement_posture
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    before = read_agreement(api, state["agreement_id"])
    assert before["capacity_posture"] == "NORMAL"
    assert before["poi_augment_pending_count"] == 0

    record_measurement(api, state["trunk_group_id"])

    after = read_agreement(api, state["agreement_id"])
    assert after["poi_augment_pending_count"] == 1
    assert after["capacity_posture"] == "CONSTRAINED"
    assert after["total_in_service_trunks"] == 48, (
        "no trunks are installed by the order yet"
    )
    assert after["version"] == before["version"] + 1
