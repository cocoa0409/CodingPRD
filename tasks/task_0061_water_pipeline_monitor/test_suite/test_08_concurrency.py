"""Concurrency and race-condition tests.

These tests use the framework's run_race / assert_exactly_one_succeeds /
validate_error_is_one_of helpers. Per the Silence-pattern rule, we only
pin a specific loser error_id where PRD prose explicitly names it.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId, CO, SUP, TA, TA_ALT, TE_ALT, TECH_USER_ID, USER_IDS,
    assert_exactly_one_succeeds, assert_race_outcome,
    build_user_headers,
    add_node, add_segment, approve_topology,
    create_and_activate_pressure_device, create_draft_topology,
    create_dma, create_network,
    get_latest_alert_for_device, get_network, iso_from_epoch_ms,
    post_reading_payload,
    run_race, submit_topology,
    setup_published_network_with_one_segment,
    setup_under_review_version,
    create_work_order_payload, assign_work_order_payload,
    validate_error, validate_error_is_one_of, validate_success,
)


class TestConcurrentApproveRace:
    """PRD §3.2: "When two TopologyApprover actors race to act on the
    same UNDER_REVIEW version — either both approving simultaneously,
    or one approving while another rejects — the system serializes on
    the version's status. Exactly one transition wins; the loser sees
    ERR_INVALID_STATE with HTTP 409 because the version is no longer in
    UNDER_REVIEW."
    """

    def test_two_approves_race_exactly_one_wins(self, api):
        """PRD §3.2: "Exactly one transition wins; the loser sees
        ERR_INVALID_STATE with HTTP 409 because the version is no longer
        in UNDER_REVIEW."

        Claim: two simultaneous approve requests — exactly one HTTP 200,
        loser has ERR_INVALID_STATE.
        """
        env = setup_under_review_version(api)
        net_id = env["network"]["id"]
        v_id = env["version"]["id"]

        results = run_race(
            lambda: api.approve_topology_version(net_id, v_id, TA),
            lambda: api.approve_topology_version(net_id, v_id, TA_ALT),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


class TestConcurrentSubmissionRace:
    """PRD §3.2: "When two engineers race to submit different drafts of
    the same network simultaneously, the system serializes the writes
    such that at most one ever lands in UNDER_REVIEW; the loser receives
    ERR_REVIEW_IN_PROGRESS and HTTP 409."
    """

    def test_two_submits_race_one_wins_other_review_in_progress(self, api):
        """PRD §3.2: "the loser receives ERR_REVIEW_IN_PROGRESS and HTTP 409."
        """
        from test_helpers import TE
        net = create_network(api)
        dma = create_dma(api, net["id"])
        # Build two drafts ready to submit.
        v1 = create_draft_topology(api, net["id"])
        n1f = add_node(api, net["id"], v1["id"], dma_id=dma["id"],
                       kind="JUNCTION")
        n1t = add_node(api, net["id"], v1["id"], dma_id=dma["id"],
                       kind="JUNCTION")
        add_segment(api, net["id"], v1["id"],
                    from_node_code=n1f["node_code"],
                    to_node_code=n1t["node_code"])

        v2 = create_draft_topology(api, net["id"],
                                   parent_version_id=v1["id"])
        n2f = add_node(api, net["id"], v2["id"], dma_id=dma["id"],
                       kind="JUNCTION")
        n2t = add_node(api, net["id"], v2["id"], dma_id=dma["id"],
                       kind="JUNCTION")
        add_segment(api, net["id"], v2["id"],
                    from_node_code=n2f["node_code"],
                    to_node_code=n2t["node_code"])

        results = run_race(
            lambda: api.submit_topology_version(net["id"], v1["id"], TE),
            lambda: api.submit_topology_version(net["id"], v2["id"],
                                                TE_ALT),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        # PRD §3.2 explicitly names ERR_REVIEW_IN_PROGRESS for the
        # second-submission loser.
        assert body["data"]["error_id"] == ApiErrorId.ERR_REVIEW_IN_PROGRESS.value


class TestConcurrentAlertAcknowledge:
    """PRD §3.6: "When two operators race to acknowledge the same OPEN
    alert simultaneously, the system serializes on the alert's status:
    the first writer wins, and the second receives ERR_INVALID_STATE
    with HTTP 409."
    """

    def test_two_acknowledges_one_wins(self, api):
        """PRD §3.6: "the second receives ERR_INVALID_STATE with HTTP 409."
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 480.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])

        from test_helpers import CO_ALT
        results = run_race(
            lambda: api.acknowledge_alert(net_id, alert["id"], CO),
            lambda: api.acknowledge_alert(net_id, alert["id"], CO_ALT),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


class TestConcurrentAssignWorkOrder:
    """PRD §3.8: "Two supervisors racing to assign the same NEW work
    order simultaneously serialize on the order's status: exactly one
    assignment succeeds, and the loser receives ERR_INVALID_STATE with
    HTTP 409."
    """

    def test_two_assigns_one_wins(self, api):
        """PRD §3.8: "exactly one assignment succeeds, and the loser
        receives ERR_INVALID_STATE with HTTP 409."
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        from test_helpers import SUP, create_work_order
        wo = create_work_order(api, net_id,
                               target_segment_code=base["segment"]["segment_code"])

        results = run_race(
            lambda: api.assign_work_order(
                net_id, wo["id"],
                assign_work_order_payload(TECH_USER_ID), SUP,
            ),
            lambda: api.assign_work_order(
                net_id, wo["id"],
                assign_work_order_payload("tech-different"),
                build_user_headers("sup-other", "MaintenanceSupervisor"),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


class TestConcurrentDuplicateReading:
    """PRD §3.4 idempotency under race."""

    def test_two_identical_idempotency_keys_at_most_one_created(self, api):
        """PRD §3.4: "When two clients submit identical (device_id,
        idempotency_key) pairs simultaneously, at most one Reading row
        is created; the duplicate request returns the original Reading
        with the same id as the first, the response carries HTTP 200
        ... and the response surfaces ERR_DUPLICATE_READING as the
        idempotency-replay signal."

        Claim: under a race on the same (device, idempotency_key),
        exactly one 201 and one 200 (with ERR_DUPLICATE_READING). Both
        responses reference the same Reading.id.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        key = "race-idem-key"

        results = run_race(
            lambda: api.post_reading(
                net_id, dev["id"],
                post_reading_payload(observed_at, 400.0, key), CO,
            ),
            lambda: api.post_reading(
                net_id, dev["id"],
                post_reading_payload(observed_at, 400.0, key), CO,
            ),
        )
        # PRD says "at most one Reading row is created" — both responses
        # are 2xx (one 201, one 200). The 200 one carries
        # ERR_DUPLICATE_READING.
        statuses = sorted(r.status_code for r in results)
        assert statuses == [200, 201], \
            f"Expected one 201 + one 200 idempotent replay, got {statuses}"
        # The 200 response should carry ERR_DUPLICATE_READING.
        idem = next(r for r in results if r.status_code == 200)
        idem_body = idem.json()
        assert idem_body["data"]["error_id"] == \
            ApiErrorId.ERR_DUPLICATE_READING.value
