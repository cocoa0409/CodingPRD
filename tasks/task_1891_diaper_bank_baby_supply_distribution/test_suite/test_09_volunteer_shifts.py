"""Volunteer shift capacity boundary, the thirty-minute overlap buffer, withdrawal."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_volunteer_shift,
    create_shift,
    create_signup_payload,
    signup_volunteer,
    validate_error,
    validate_success,
)

VOLUNTEER_COORD = TEST_USERS["volunteer_coordinator_headers"]
VOLUNTEER = TEST_USERS["volunteer_headers"]


class TestShiftCapacityBoundary:
    def test_signup_reaching_capacity_fills_shift(self, api):
        """PRD §3.7: "Shift status is never set by hand: it is `OPEN` until the number of signups reaches `capacity`, at which point it becomes `FULL` — the equality boundary is what fills it — and it returns to `OPEN` the moment a withdrawal drops the count below capacity again."

        Design: Difficulty/boundary_precision_check/shift_capacity_exact_fill_boundary
        """
        shift = create_shift(title="Sorting", capacity=2)

        first = signup_volunteer(shift["id"], "v1@x.org", "V One")
        assert_volunteer_shift(first)
        assert first["signup_count"] == 1
        assert first["status"] == "OPEN", "Below capacity stays OPEN"

        second = signup_volunteer(shift["id"], "v2@x.org", "V Two")
        assert second["signup_count"] == 2
        assert second["status"] == "FULL", (
            "The signup that makes signup_count == capacity succeeds and fills the shift"
        )

    def test_signup_beyond_capacity_rejected(self, api):
        """PRD §3.7: "Three rules guard the append: the same `volunteer_email` may appear at most once on a given shift (`ERR_DUPLICATE_SIGNUP`); a `FULL` shift accepts no further signups (`ERR_SHIFT_FULL`); and a volunteer may not hold two near-simultaneous commitments — a signup is rejected with `ERR_SHIFT_OVERLAP` when the same `volunteer_email` already appears on another shift whose window, expanded by thirty minutes on both sides, intersects the target shift's window, while an exactly-thirty-minute gap between the two windows is allowed."

        Design: Difficulty/boundary_precision_check/shift_capacity_exact_fill_boundary
        """
        shift = create_shift(title="Sorting", capacity=2)
        signup_volunteer(shift["id"], "v1@x.org", "V One")
        filled = signup_volunteer(shift["id"], "v2@x.org", "V Two")
        assert filled["status"] == "FULL"
        assert [s["volunteer_email"] for s in filled["signups"]] == [
            "v1@x.org", "v2@x.org"]

        resp = api.signup_volunteer(
            shift["id"], create_signup_payload("v3@x.org", "V Three"), VOLUNTEER)
        validate_error(resp, ApiErrorId.ERR_SHIFT_FULL)


class TestShiftOverlapBuffer:
    def test_exactly_thirty_minute_gap_allowed(self, api):
        """PRD §3.7: "a signup is rejected with `ERR_SHIFT_OVERLAP` when the same `volunteer_email` already appears on another shift whose window, expanded by thirty minutes on both sides, intersects the target shift's window, while an exactly-thirty-minute gap between the two windows is allowed."

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_thirty_minute_buffer
        """
        first_shift = create_shift(
            title="S1", starts_at="2026-08-10T09:00:00Z",
            ends_at="2026-08-10T11:00:00Z", capacity=5)
        second_shift = create_shift(
            title="S2", starts_at="2026-08-10T11:30:00Z",
            ends_at="2026-08-10T13:00:00Z", capacity=5)

        signup_volunteer(first_shift["id"], "v@x.org", "V")
        # S1 buffered is [08:30, 11:30]; S2 starts at 11:30 — the
        # exactly-thirty-minute gap is allowed.
        second = signup_volunteer(second_shift["id"], "v@x.org", "V")
        assert second["signup_count"] == 1

    def test_twenty_nine_minute_gap_rejected(self, api):
        """PRD §3.7: "a signup is rejected with `ERR_SHIFT_OVERLAP` when the same `volunteer_email` already appears on another shift whose window, expanded by thirty minutes on both sides, intersects the target shift's window, while an exactly-thirty-minute gap between the two windows is allowed."

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_thirty_minute_buffer
        """
        first_shift = create_shift(
            title="S1", starts_at="2026-08-10T09:00:00Z",
            ends_at="2026-08-10T11:00:00Z", capacity=5)
        third_shift = create_shift(
            title="S3", starts_at="2026-08-10T11:29:00Z",
            ends_at="2026-08-10T12:30:00Z", capacity=5)

        signup_volunteer(first_shift["id"], "v@x.org", "V")
        # 11:29 falls inside S1's buffered window (ends 11:00 + 30 minutes).
        resp = api.signup_volunteer(
            third_shift["id"], create_signup_payload("v@x.org", "V"), VOLUNTEER)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestWithdrawal:
    def test_withdraw_restores_open_status(self, api):
        """PRD §3.7: "Shift status is never set by hand: it is `OPEN` until the number of signups reaches `capacity`, at which point it becomes `FULL` — the equality boundary is what fills it — and it returns to `OPEN` the moment a withdrawal drops the count below capacity again."
        PRD §3.7: "Withdrawal removes the matching `volunteer_email` entry."

        Design: Corner/endpoints/withdraw_restores_open_status
        """
        shift = create_shift(title="Restock", capacity=1)

        filled = signup_volunteer(shift["id"], "solo@x.org", "Solo")
        assert filled["status"] == "FULL"
        assert filled["signup_count"] == 1

        resp = api.withdraw_volunteer(shift["id"],
                                      {"volunteer_email": "solo@x.org"}, VOLUNTEER)
        reopened = validate_success(resp, 200)
        assert_volunteer_shift(reopened)
        assert reopened["status"] == "OPEN", "Dropping below capacity reopens the shift"
        assert reopened["signup_count"] == 0
        assert reopened["signups"] == []
