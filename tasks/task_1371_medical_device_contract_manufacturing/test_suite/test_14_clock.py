"""The logical clock: monotonicity and regression rejection."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    create_supplier,
    set_clock,
    validate_error,
    api_client,
)


class TestClockRegression:
    def test_clock_regression_rejected(self, api):
        """PRD section 2.5: "The clock is monotonic: an attempt to set it
        backwards — or to a value that is not a valid UTC ISO 8601 timestamp —
        is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400)." and "Every notion of
        "now" in the system ... reads from a single logical clock, never from
        wall-clock time."

        Design: Corner/endpoints/clock_regression_rejected
        """
        set_clock("2026-09-01T00:00:00Z")

        from test_helpers import admin

        resp = api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, admin())
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)

        # The rejected set must not move the clock: a new resource still stamps
        # from the logical clock at 2026-09-01 (PRD section 2.4 created_at).
        supplier = create_supplier("SUP-CR", "ClockRead Co")
        assert_instant_equal(
            supplier["created_at"], "2026-09-01T00:00:00Z", "created_at after rejected regression"
        )
