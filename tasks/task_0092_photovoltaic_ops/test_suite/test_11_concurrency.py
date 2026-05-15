"""Concurrency races — exactly one winner per scenario (PRD §2.11)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    api_client,
    create_alarm_payload,
    create_manual_defect,
    create_spare_part,
    create_station,
    create_supplier,
    create_work_order_payload,
    ingest_alarm,
    issue_invoice_payload,
    make_om_engineer_headers,
    register_alarm_code_map,
    revenue_adjust_payload,
    run_race,
    setup_acknowledged_alarm,
    setup_confirmed_settlement,
    setup_station_with_inverters,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
)


class TestAlarmAckRace:
    """PRD §2.11: "(1) Two operators acknowledging the same OPEN
    alarm simultaneously: exactly one transition OPEN → ACKNOWLEDGED
    lands on first-writer-wins; the loser receives
    ERR_ALARM_ALREADY_ACKED."
    """

    def test_two_operators_ack_same_alarm(self, api):
        """PRD §2.11: "exactly one transition OPEN → ACKNOWLEDGED
        lands on first-writer-wins; the loser receives
        ERR_ALARM_ALREADY_ACKED."

        Claim: two concurrent ack calls on the same OPEN alarm result
        in exactly one success and one ERR_ALARM_ALREADY_ACKED.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        register_alarm_code_map(severity="MAJOR")
        alarm = ingest_alarm(invs[0]["id"])
        op_a = make_om_engineer_headers("op-A")
        op_b = make_om_engineer_headers("op-B")
        results = run_race(
            lambda: api_client.ack_alarm(alarm["id"], op_a),
            lambda: api_client.ack_alarm(alarm["id"], op_b),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser's error_id is named in PRD §2.11.
        failure = outcome["failures"][0]
        body = failure.json()
        assert body["data"]["error_id"] == \
            ApiErrorId.ERR_ALARM_ALREADY_ACKED.value


class TestSparePartRace:
    """PRD §2.11: "(2) Two work orders requisitioning the same spare
    part where the combined quantity would exceed available stock ...
    exactly one work-order creation succeeds, and the loser receives
    ERR_SPARE_PART_INSUFFICIENT."
    """

    def test_two_dispatches_compete_for_last_units(self, api):
        """PRD §2.11: "the reservation step is atomic, exactly one
        work-order creation succeeds, and the loser receives
        ERR_SPARE_PART_INSUFFICIENT."

        Claim: stock=3, both dispatches request 2 each (total=4 >
        available 3) → exactly one succeeds; loser =
        ERR_SPARE_PART_INSUFFICIENT.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=2)
        supplier = create_supplier()
        part = create_spare_part(stock_on_hand=3)
        d_a = create_manual_defect(
            station_id=station["id"], subject_type="INVERTER",
            subject_id=invs[0]["id"], severity="MINOR",
        )
        d_b = create_manual_defect(
            station_id=station["id"], subject_type="INVERTER",
            subject_id=invs[1]["id"], severity="MINOR",
        )
        payload_a = create_work_order_payload(
            assigned_supplier_id=supplier["id"],
            spare_part_lines=[{"part_id": part["id"], "quantity": 2}],
        )
        payload_b = create_work_order_payload(
            assigned_supplier_id=supplier["id"],
            spare_part_lines=[{"part_id": part["id"], "quantity": 2}],
        )
        om_headers = TEST_USERS["om_engineer_headers"]
        results = run_race(
            lambda: api_client.create_work_order(d_a["id"], payload_a, om_headers),
            lambda: api_client.create_work_order(d_b["id"], payload_b, om_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        failure = outcome["failures"][0]
        body = failure.json()
        assert body["data"]["error_id"] == \
            ApiErrorId.ERR_SPARE_PART_INSUFFICIENT.value


class TestSettlementInvoiceVsAdjustRace:
    """PRD §2.11: "(5) Two simultaneous moves out of a CONFIRMED
    settlement period — one issuing an invoice and one initiating a
    revenue adjustment: exactly one wins on first-writer-wins of
    state, and the loser receives ERR_INVALID_STATE."
    """

    def test_invoice_vs_revenue_adjust_race(self, api):
        """PRD §2.11: "exactly one wins on first-writer-wins of
        state, and the loser receives ERR_INVALID_STATE."

        Claim: concurrent issue-invoice and revenue-adjust on the
        same CONFIRMED period — exactly one succeeds; the loser
        receives ERR_INVALID_STATE.
        """
        result = setup_confirmed_settlement(
            feed_in_tariff_cny_per_kwh=0.5000,
            on_grid_kwh=200.000,
            grid_company_confirmed_kwh=200.000,
            investor_shares=[("OnlyInv", 10000)],
        )
        period = result["period"]
        finance_headers = TEST_USERS["finance_officer_headers"]
        results = run_race(
            lambda: api_client.issue_invoice(
                period["id"], issue_invoice_payload(invoice_no="INV-RACE"),
                finance_headers,
            ),
            lambda: api_client.revenue_adjust(
                period["id"], revenue_adjust_payload(reason="race"),
                finance_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        failure = outcome["failures"][0]
        body = failure.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value
