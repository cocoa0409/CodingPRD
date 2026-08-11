"""Validation-rule coverage: rate-sum, time-range, future-period.

Covers corner rate_sum_mismatch_returns_422 and
future_period_clearance_report_rejected.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    create_agreement_payload,
    create_clearance_report_payload,
    create_network_payload,
    create_station_group_payload,
    create_station_payload,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    make_station_group_owner_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import create_clearance_report


class TestRateSumMismatch:
    def test_agreement_rate_sum_not_one_rejected(self, api):
        """PRD §2.7: "Pairwise rate sums on an agreement or renewal offer
        must total exactly 1.0 within a tolerance of 1e-9, otherwise the
        write is rejected with `ERR_RATE_SUM_MISMATCH` (HTTP 422)."

        Design: Corner/validations/rate_sum_mismatch_returns_422
        """
        setup_clock("2026-05-01T00:00:00Z")
        admin = make_platform_admin_headers()
        nar = make_nar_headers()
        net = get_success_data(api_client.create_network(create_network_payload(), admin))
        grp = get_success_data(
            api_client.create_station_group(create_station_group_payload(), admin)
        )
        station = get_success_data(
            api_client.create_station(
                net["id"], create_station_payload(station_group_id=grp["id"]), nar
            )
        )
        resp = api_client.create_agreement(
            net["id"], station["id"],
            create_agreement_payload(
                reverse_comp_pct=0.40,
                retrans_share_pct=0.50,  # sum = 0.90 != 1.0
            ),
            nar,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_SUM_MISMATCH)


class TestFuturePeriodRejected:
    def test_clearance_report_file_in_future_period_rejected(self, api):
        """PRD §3.5: "the report's `period_index` must not exceed the
        network's `current_period_index`, otherwise the file is rejected
        with `ERR_FUTURE_PERIOD` (HTTP 422)."

        Design: Corner/validations/future_period_clearance_report_rejected
        """
        scenario = setup_basic_scenario()  # current_period_index = 0
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        report = create_clearance_report(
            nid, sid, sgo,
            period_index=5,  # > current_period_index = 0
            cleared_hours=90.0, preempted_hours=10.0,
        )
        resp = api_client.file_clearance_report(nid, sid, report["id"], sgo)
        validate_error(resp, ApiErrorId.ERR_FUTURE_PERIOD)
