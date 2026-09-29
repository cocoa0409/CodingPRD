"""Activation gates, withdrawal, the termination cascade and teardown completion."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_EFFECTIVE_DATE_NOT_REACHED,
    ERR_INVALID_AGREEMENT_STATE,
    ERR_INVALID_OFFER_STATE,
    ERR_INVALID_TRUNK_GROUP_STATE,
    ERR_NO_EFFECTIVE_RECIPROCAL_RATE,
)
from test_helpers.assertions import assert_rate, assert_trunk_group_statuses
from test_helpers.constants import (
    RECIPROCAL_RATE,
    T_2026_08_01,
    T_2026_10_01,
)
from test_helpers.factories import terminate_agreement_payload
from test_helpers.fixtures import (
    append_counter,
    append_proposal,
    latest_pending_order,
    read_agreement,
    read_augment_order,
    read_trunk_group,
    record_measurement,
    setup_draft_agreement,
    setup_effective_agreement,
    setup_effective_agreement_with_in_service_trunks,
    setup_executed_agreement,
    setup_requested_trunk_group,
    setup_second_carrier,
)


def test_agreement_activation_without_an_effective_reciprocal_rate_is_refused(
    api, manager_headers
):
    """With an empty rate book activation reports the missing reciprocal rate.

    PRD 3.2: "And a reciprocal compensation rate must be on file: there must exist a tariff filing whose `rate_element` is `LOCAL_RECIPROCAL_COMP`, whose `status` is `EFFECTIVE`, and whose half-open effective window covers the agreement's `effective_date` — that is, whose window starts at or before that instant and ends strictly after it."
    PRD 3.2: "Absent such a filing, activation is refused with `ERR_NO_EFFECTIVE_RECIPROCAL_RATE`."
    PRD 3.2: "The logical clock must have reached the agreement's `effective_date`; if it has not, activation is refused with `ERR_EFFECTIVE_DATE_NOT_REACHED`."

    Design: Corner/state_machines/agreement_activation_without_an_effective_reciprocal_rate_is_refused
    """
    state = setup_executed_agreement(api, ensure_local_rate=False)

    response = api.activate_agreement(state["agreement_id"], {}, manager_headers)
    validate_error(response, ERR_NO_EFFECTIVE_RECIPROCAL_RATE, expected_status=409)

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["status"] == "EXECUTED"
    assert_rate(
        agreement["reciprocal_rate_per_mou_usd"],
        RECIPROCAL_RATE,
        "reciprocal_rate_per_mou_usd",
    )
    assert agreement["executed_at"] == T_2026_08_01


def test_agreement_activation_before_its_effective_date_is_refused(api, manager_headers):
    """With the rate on file but the clock short of the effective date, the date gate wins.

    PRD 3.2: "The logical clock must have reached the agreement's `effective_date`; if it has not, activation is refused with `ERR_EFFECTIVE_DATE_NOT_REACHED`."
    PRD 2.5: "Before any request is made, the logical clock reads exactly `2026-08-01T00:00:00Z`; that is a mandatory startup default and the server never falls back to real time."
    PRD 2.7: "Temporal window checks follow — first the four that carry HTTP 422 (tariff window ordering, measurement period ordering, usage period ordering and closure, the dispute filing window, and the committed due date), then the three that carry HTTP 409 (agreement effective date reached, dispute SLA not yet expired, invoice due date reached)."

    Design: Corner/state_machines/agreement_activation_before_its_effective_date_is_refused
    """
    state = setup_executed_agreement(
        api,
        agreement_label="ICA-NORTHSTAR-2026-Q4",
        effective_date=T_2026_10_01,
    )
    assert state["local_filing"]["status"] == "EFFECTIVE"

    response = api.activate_agreement(state["agreement_id"], {}, manager_headers)
    validate_error(response, ERR_EFFECTIVE_DATE_NOT_REACHED, expected_status=409)

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["status"] == "EXECUTED"
    assert agreement["effective_date"] == T_2026_10_01


def test_agreement_withdrawal_from_countered_ends_the_negotiation(api, manager_headers):
    """Withdrawing a COUNTERED agreement withdraws only the standing offer.

    PRD 3.2: "An `InterconnectionManager` may withdraw an agreement sitting in either `PROPOSED` or `COUNTERED`, supplying a `withdrawal_reason`; the agreement moves to `WITHDRAWN`, the standing `OPEN` offer moves `OPEN → WITHDRAWN` with its `responded_at` stamped, and the agreement's `version` increments by 1."
    PRD 3.1: "Its `reciprocal_rate_per_mou_usd`, `term_months`, `poi_financial_responsibility`, `executed_at` and `terminated_at` are all null at this point, and `total_in_service_trunks` and `poi_augment_pending_count` are both 0."

    Design: Corner/state_machines/agreement_withdrawal_from_countered_ends_the_negotiation
    """
    state = setup_draft_agreement(api)
    first = append_proposal(api, state)
    second = append_counter(api, state, from_counterparty=True)
    countered = read_agreement(api, state["agreement_id"])
    assert countered["status"] == "COUNTERED"
    assert countered["version"] == 3
    assert countered["negotiation_round"] == 2

    response = api.withdraw_agreement(
        state["agreement_id"],
        {"withdrawal_reason": "Counterparty declined the point of interconnection terms"},
        manager_headers,
    )
    withdrawn = validate_success(response, expected_status=200)

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["version"] == 4
    assert withdrawn["negotiation_round"] == 2
    assert withdrawn["reciprocal_rate_per_mou_usd"] is None
    assert withdrawn["executed_at"] is None

    standing = validate_success(api.get_offer(second["id"], manager_headers))
    assert standing["status"] == "WITHDRAWN"
    assert standing["responded_at"] == T_2026_08_01

    earlier = validate_success(api.get_offer(first["id"], manager_headers))
    assert earlier["status"] == "SUPERSEDED", (
        "withdrawal must touch only the standing offer"
    )


def test_negotiation_and_trunk_state_conflicts_each_report_their_own_id(
    api, manager_headers, planner_headers
):
    """Re-activating, re-accepting and activating an unprovisioned group each conflict.

    PRD 3.2: "The agreement must be in `EXECUTED`; activation attempted from `DRAFT`, `PROPOSED`, `COUNTERED`, `EFFECTIVE`, `TERMINATED` or `WITHDRAWN` is refused with `ERR_INVALID_AGREEMENT_STATE`."
    PRD 3.2: "Both directions are specified identically: the accepted offer must belong to the agreement in question, must be in status `OPEN` — an attempt to accept an offer in `SUPERSEDED`, `ACCEPTED` or `WITHDRAWN` is refused with `ERR_INVALID_OFFER_STATE` — and the acting party must not be the offeror."
    PRD 3.3: "Activation moves the trunk group `PROVISIONED → IN_SERVICE`; a trunk group in `REQUESTED`, `IN_SERVICE`, `DISCONNECT_PENDING` or `DISCONNECTED` is refused with `ERR_INVALID_TRUNK_GROUP_STATE`."

    Design: Corner/errors/negotiation_and_trunk_state_conflicts_each_report_their_own_id
    """
    state = setup_effective_agreement(api)
    trunk_group = setup_requested_trunk_group(api, state["agreement_id"])

    already_effective = api.activate_agreement(
        state["agreement_id"], {}, manager_headers
    )
    validate_error(already_effective, ERR_INVALID_AGREEMENT_STATE, expected_status=409)

    # The offer-state conflict is exercised on a live negotiation, where the
    # agreement itself sits in PROPOSED — a status PRD 3.2 does not refuse — so
    # the only rule in play is the offer's own status.
    negotiating = setup_draft_agreement(
        api, carrier=setup_second_carrier(api), ensure_local_rate=False
    )
    superseded_offer = append_proposal(api, negotiating)
    append_counter(api, negotiating, from_counterparty=True)
    append_counter(api, negotiating, from_counterparty=False)
    assert read_agreement(api, negotiating["agreement_id"])["status"] == "PROPOSED"

    stale_offer = api.accept_offer(
        superseded_offer["id"], {}, negotiating["rep_headers"]
    )
    validate_error(stale_offer, ERR_INVALID_OFFER_STATE, expected_status=409)
    assert read_agreement(api, negotiating["agreement_id"])["status"] == "PROPOSED"

    never_provisioned = api.activate_trunk_group(trunk_group["id"], {}, planner_headers)
    validate_error(never_provisioned, ERR_INVALID_TRUNK_GROUP_STATE, expected_status=409)

    assert read_agreement(api, state["agreement_id"])["status"] == "EFFECTIVE"
    assert read_trunk_group(api, trunk_group["id"])["service_status"] == "REQUESTED"


def test_agreement_termination_cascades_to_trunk_groups_and_open_orders(
    api, manager_headers
):
    """Termination drives both trunk groups to DISCONNECT_PENDING and rejects the open order.

    PRD 3.2: "When it does proceed, the agreement moves `EFFECTIVE → TERMINATED`, which is terminal, its `terminated_at` is stamped from the logical clock and the teardown propagates downward in `created_at` ascending order over the agreement's trunk groups."
    PRD 3.2: "Every trunk group whose `service_status` is `REQUESTED`, `PROVISIONED` or `IN_SERVICE` moves to `DISCONNECT_PENDING`, and its `version` increments by 1; trunk groups already in `DISCONNECTED` are left untouched."
    PRD 3.2: "Each trunk group that moves then cancels its own open augment work: every child augment order in `PENDING` or `ACCEPTED` moves to `REJECTED` with its `rejection_reason` set to the literal `AGREEMENT_TERMINATED`, and its `version` increments by 1, while orders already in `REJECTED`, `COMPLETED` or `REVERSED` are left alone."
    PRD 3.2: "Each cancelled order decrements the agreement's `poi_augment_pending_count` by 1, and once every decrement has landed the agreement's `capacity_posture` is recomputed."
    PRD 3.2: "Because no trunk group remains `IN_SERVICE`, `total_in_service_trunks` recomputes to 0."

    Design: Corner/state_machines/agreement_termination_cascades_to_trunk_groups_and_open_orders
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    first_group = state["trunk_group"]
    second_group = setup_requested_trunk_group(
        api,
        state["agreement_id"],
        trunk_group_serial="TG-DLLS-OUT-002",
        direction="ONE_WAY_OUTBOUND",
    )
    assert second_group["service_status"] == "REQUESTED"

    record_measurement(api, first_group["id"])
    order = latest_pending_order(api, first_group["id"])
    assert order["requested_additional_trunks"] == 24

    response = api.terminate_agreement(
        state["agreement_id"], terminate_agreement_payload(), manager_headers
    )
    terminated = validate_success(response, expected_status=200)

    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_at"] == T_2026_08_01
    assert terminated["total_in_service_trunks"] == 0
    assert terminated["poi_augment_pending_count"] == 0

    torn_down = read_trunk_group(api, first_group["id"])
    # Only the service_status dimension is asserted here: PRD 2.10 states that
    # neither dimension implies anything about the other unless the document
    # says so, and PRD 3.2's teardown never names augment_status.
    assert torn_down["service_status"] == "DISCONNECT_PENDING"
    assert torn_down["provisioned_trunks"] == 48, (
        "teardown does not zero the physical trunks until the disconnect lands"
    )
    assert torn_down["open_augment_order_count"] == 0

    cascaded = read_trunk_group(api, second_group["id"])
    assert cascaded["service_status"] == "DISCONNECT_PENDING", (
        "a REQUESTED group cascades to DISCONNECT_PENDING as well"
    )

    cancelled = read_augment_order(api, order["id"])
    assert cancelled["status"] == "REJECTED"
    assert cancelled["rejection_reason"] == "AGREEMENT_TERMINATED"


def test_trunk_group_disconnect_completes_the_termination_teardown(
    api, manager_headers, planner_headers
):
    """Disconnecting a DISCONNECT_PENDING group zeroes its trunks and is terminal.

    PRD 3.3: "When a trunk group has been driven to `DISCONNECT_PENDING` by its agreement's termination, a `NetworkPlanner` completes the disconnection, moving it `DISCONNECT_PENDING → DISCONNECTED`, which is terminal."
    PRD 3.3: "On success `provisioned_trunks` is set to 0 and `version` increments by 1."
    PRD 3.3: "Note the asymmetry in the in-service accounting: the `IN_SERVICE → DISCONNECT_PENDING` edge is where the agreement's `total_in_service_trunks` decreases by the trunk group's `provisioned_trunks`, because that is the moment the trunks stop carrying traffic; the `REQUESTED → DISCONNECT_PENDING` and `PROVISIONED → DISCONNECT_PENDING` edges move no in-service total, because those trunk groups were never counted in it."
    PRD 2.7: "9. **State preconditions** — the target row is in a status from which the requested transition exists, yielding the entity-specific conflict codes catalogued in §3."

    Design: Corner/endpoints/trunk_group_disconnect_completes_the_termination_teardown
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]
    validate_success(
        api.terminate_agreement(
            state["agreement_id"], terminate_agreement_payload(), manager_headers
        ),
        expected_status=200,
    )
    assert read_trunk_group(api, trunk_group_id)["service_status"] == "DISCONNECT_PENDING"

    response = api.disconnect_trunk_group(trunk_group_id, {}, planner_headers)
    disconnected = validate_success(response, expected_status=200)

    assert_trunk_group_statuses(disconnected, "DISCONNECTED", "NONE")
    assert disconnected["provisioned_trunks"] == 0

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["status"] == "TERMINATED"
    assert agreement["total_in_service_trunks"] == 0

    again = api.disconnect_trunk_group(trunk_group_id, {}, planner_headers)
    validate_error(again, ERR_INVALID_TRUNK_GROUP_STATE, expected_status=409)
    assert read_trunk_group(api, trunk_group_id)["service_status"] == "DISCONNECTED"
