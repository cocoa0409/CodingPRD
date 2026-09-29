"""Inclusive edges of the bearing preload window and the empty quote line set.

The AISI_304 acceptance window is closed at the top, and a package quote with no
lines at all must still roll its money up while refusing submission.
"""

from datetime import datetime

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import PLANT_MANAGER, make_technician_headers


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so two instants compare exactly."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestBearingPreloadUpperBoundIsInclusive:
    """AISI_304 accepts 18.00 through 32.00 inclusive."""

    def test_01_preload_at_the_upper_bound_is_accepted(self, api):
        """A bearing installation measuring exactly 32.00 micron on an AISI_304
        drum is accepted and advances the unit to BEARINGS_DONE.

        PRD: "For a drum of `AISI_304`, the measured `bearing_preload_micron` must fall between `18.00` and `32.00` inclusive."
        Design: Difficulty/boundary_precision_check/bearing_preload_upper_bound_inclusive_on_station_log
        """
        env = fx.make_floor_environment(api)
        build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
        fx.release_build(api, build["id"])
        fx.log_station_pass(
            api,
            build["id"],
            env["stations"]["drum"],
            env["technician"]["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T09:00:00Z",
        )

        payload = f.station_log_payload(
            env["stations"]["bearing"]["id"],
            "BEARING_INSTALL",
            "2026-08-01T11:00:00Z",
            "2026-08-01T12:00:00Z",
            "PASS",
            bearing_preload_micron=32.00,
        )
        log = validate_success(
            api.create_station_log(
                build["id"], payload, make_technician_headers(env["technician"]["id"])
            ),
            expected_status=201,
        )
        assert float(log["bearing_preload_micron"]) == pytest.approx(32.00, abs=0.01)
        assert _instant(log["occupation_to"]) == _instant("2026-08-01T12:15:00Z")
        assert log["labor_minutes"] == 60

        after = validate_success(
            api.get_build_order(build["id"], PLANT_MANAGER), expected_status=200
        )
        a.assert_build_state(after, "BEARINGS_DONE")
        assert after["station_pass_count"] == 2
        assert after["labor_minutes_total"] == 120

    def test_02_preload_one_hundredth_past_the_upper_bound_is_refused(self, api):
        """A measurement of 32.01 micron — one hundredth past the AISI_304 edge —
        is refused and leaves the unit waiting at DRUM_DONE.

        PRD: "A measurement outside the window selected by the model's `drum_alloy_grade`, or a bearing-installation log that omits the measurement entirely, or a non-bearing log that supplies one, is rejected with `ERR_PRELOAD_OUT_OF_SPEC`."
        Design: Difficulty/boundary_precision_check/bearing_preload_upper_bound_inclusive_on_station_log
        """
        env = fx.make_floor_environment(api)
        build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0002")
        fx.release_build(api, build["id"])
        fx.log_station_pass(
            api,
            build["id"],
            env["stations"]["drum"],
            env["technician"]["id"],
            "2026-08-01T10:00:00Z",
            "2026-08-01T11:00:00Z",
        )

        payload = f.station_log_payload(
            env["stations"]["bearing"]["id"],
            "BEARING_INSTALL",
            "2026-08-01T12:30:00Z",
            "2026-08-01T13:30:00Z",
            "PASS",
            bearing_preload_micron=32.01,
        )
        response = api.create_station_log(
            build["id"], payload, make_technician_headers(env["technician"]["id"])
        )
        validate_error(response, E.ERR_PRELOAD_OUT_OF_SPEC, expected_status=422)

        after = validate_success(
            api.get_build_order(build["id"], PLANT_MANAGER), expected_status=200
        )
        a.assert_build_state(after, "DRUM_DONE")
        assert after["station_pass_count"] == 1
        assert after["labor_minutes_total"] == 60

        rows, _ = validate_paginated(
            api.list_station_logs(PLANT_MANAGER, build_order_id=build["id"])
        )
        assert len(rows) == 1


class TestQuoteSubmissionNeedsAtLeastOneLine:
    """line_count 0 is the empty set, and the rollup over it still evaluates."""

    def test_01_submitting_a_quote_with_no_lines_is_refused(self, api):
        """An authorised distributor submitting a package quote that carries no
        machine lines at all is refused on the cardinality rule.

        PRD: "The quote has at least one line, that is, `line_count` is 1 or greater — otherwise `ERR_QUOTE_HAS_NO_LINES`, HTTP 422, on quote submission."
        Design: Difficulty/boundary_precision_check/submit_quote_with_zero_lines_empty_set
        """
        env = fx.make_authorized_distributor(api)
        quote = fx.make_quote(
            api, env, package_discount_pct=5.00, freight_cents=250000
        )

        response = api.submit_quote(quote["id"], env["headers"])
        validate_error(response, E.ERR_QUOTE_HAS_NO_LINES, expected_status=422)

        after = validate_success(
            api.get_quote(quote["id"], env["headers"]), expected_status=200
        )
        a.assert_quote_state(after, "DRAFT")
        assert after["line_count"] == 0

    def test_02_the_empty_line_set_still_rolls_up_to_freight_alone(self, api):
        """The refused submission leaves the empty rollup intact: no subtotal, no
        package discount, a total equal to freight and no financing figures.

        PRD: "An empty quote has `line_count` 0, `line_subtotal_cents` 0, `discount_cents` 0, and `total_cents` equal to `freight_cents`."
        Design: Difficulty/boundary_precision_check/submit_quote_with_zero_lines_empty_set
        """
        env = fx.make_authorized_distributor(api)
        quote = fx.make_quote(
            api, env, package_discount_pct=5.00, freight_cents=250000
        )

        response = api.submit_quote(quote["id"], env["headers"])
        validate_error(response, E.ERR_QUOTE_HAS_NO_LINES, expected_status=422)

        after = validate_success(
            api.get_quote(quote["id"], env["headers"]), expected_status=200
        )
        a.assert_cents(after["line_subtotal_cents"], 0)
        a.assert_cents(after["discount_cents"], 0)
        a.assert_cents(after["total_cents"], 250000)
        a.assert_cents(after["origination_fee_cents"], 0)
        assert after["provisional_apr_bp"] is None
        assert after["provisional_monthly_payment_cents"] is None
        a.assert_money_identity(after)

        rows, _ = validate_paginated(
            api.list_quote_lines(env["headers"], quote_id=quote["id"])
        )
        assert rows == []
