"""Bad-debt write-off — 90-day boundary, balance gate, duplicate guard.

Covers PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_bad_debt_record,
    post_payment,
    re_get_encounter,
    setup_billed_with_balance,
    setup_resolved_encounter,
    setup_written_off_encounter,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.8 — 90-day inclusive boundary
# ===========================================================================
class TestNinetyDayBoundary:
    """PRD §3.8: "the boundary is inclusive, so a day count of exactly 90 passes and a day count of 89 does not.\""""

    def test_write_off_at_exactly_89_days_rejected(self, api):
        """PRD §3.8: "the boundary is inclusive, so a day count of exactly 90 passes and a day count of 89 does not."
        PRD §3.8: "Failing this gate produces `ERR_WRITE_OFF_TOO_EARLY`."

        Claim: with billed_at=2026-02-01T00:00:00Z and clock at
        2026-05-01T23:59:59Z (89 days, 23h59m59s elapsed; floor=89),
        write-off returns ERR_WRITE_OFF_TOO_EARLY.
        """
        # Anchor clock so billed_at is recorded at 2026-02-01.
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        # Move clock to 89 days 23h59m59s after billed_at.
        advance_clock_to("2026-05-01T23:59:59.999Z")
        res = api.write_off_encounter(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_WRITE_OFF_TOO_EARLY")
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "BILLED"

    def test_write_off_at_exactly_90_days_accepted(self, api):
        """PRD §3.8: "the boundary is inclusive, so a day count of exactly 90 passes and a day count of 89 does not."

        Claim: with billed_at=2026-02-01T00:00:00Z and clock at
        2026-05-02T00:00:00Z (exactly 90 days elapsed), write-off is
        accepted and the encounter becomes WRITTEN_OFF.
        """
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        advance_clock_to("2026-05-02T00:00:00.000Z")
        res = api.write_off_encounter(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_bad_debt_record(data)
        assert data["write_off_cents"] == 10_000
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "WRITTEN_OFF"
        assert refreshed["write_off_cents"] == 10_000


# ===========================================================================
# §3.8 — outstanding balance gate
# ===========================================================================
class TestOutstandingBalanceGate:
    """PRD §3.8: "the encounter's current outstanding balance (computed via the chronological payments walk in §3.7) must be strictly greater than zero"
    """

    def test_write_off_with_zero_balance_rejected(self, api):
        """PRD §3.8: "the encounter's current outstanding balance (computed via the chronological payments walk in §3.7) must be strictly greater than zero; an encounter that has already been paid off cannot be written off, and the attempt is rejected with `ERR_WRITE_OFF_NO_BALANCE`."

        Claim: with the encounter RESOLVED (balance = 0), write-off
        returns ERR_WRITE_OFF_NO_BALANCE. (Note: a RESOLVED encounter
        is also state-illegal for write-off; the PRD specifies
        ERR_WRITE_OFF_NO_BALANCE for the no-balance condition. Since
        the implementation may surface either the state guard or the
        balance gate first, accept either ERR_INVALID_STATE or
        ERR_WRITE_OFF_NO_BALANCE.)
        """
        from test_helpers import validate_error_is_one_of
        patient, policy, encounter = setup_resolved_encounter(
            patient_responsibility_cents=10_000,
        )
        res = api.write_off_encounter(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        # PRD §2.10 places state checks (priority 5) before fiscal
        # checks (priority 15); on a RESOLVED encounter, the state
        # guard fires first → ERR_INVALID_STATE.
        validate_error_is_one_of(
            res, ["ERR_INVALID_STATE", "ERR_WRITE_OFF_NO_BALANCE"],
        )


# ===========================================================================
# §3.8 — duplicate write-off
# ===========================================================================
class TestDuplicateWriteOff:
    """PRD §3.8: uniqueness on encounter_id of BadDebtRecord."""

    def test_second_write_off_attempt_rejected(self, api):
        """PRD §3.8: "no `BadDebtRecord` may already exist for the encounter; a second write-off submission is rejected with `ERR_DUPLICATE_WRITE_OFF` (uniqueness is enforced on the `encounter_id` of `BadDebtRecord`, and only one write-off attempt wins under contention)."

        Claim: the second write-off call on a WRITTEN_OFF encounter
        returns ERR_DUPLICATE_WRITE_OFF (or ERR_INVALID_STATE — PRD
        §2.10 places state checks above duplicate-write-off business
        checks; either ID is faithful for a once-written-off
        encounter).
        """
        from test_helpers import validate_error_is_one_of
        patient, policy, encounter = setup_written_off_encounter(
            patient_responsibility_cents=10_000,
        )
        assert encounter["status"] == "WRITTEN_OFF"
        res = api.write_off_encounter(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        validate_error_is_one_of(
            res, ["ERR_DUPLICATE_WRITE_OFF", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# §3.8 — Cascade: BadDebtRecord drives Encounter.write_off_cents
# ===========================================================================
class TestWriteOffCascade:
    """PRD §3.8: "The encounter's `write_off_cents` is set equal to the bad-debt record's `write_off_cents`"
    """

    def test_encounter_write_off_cents_equals_bad_debt_record(self, api):
        """PRD §3.8: "The encounter's `write_off_cents` is set equal to the bad-debt record's `write_off_cents`, and the encounter transitions from `BILLED` to `WRITTEN_OFF` — the second terminal status for an encounter."

        Claim: after write-off, the encounter's write_off_cents equals
        the bad-debt record's write_off_cents AND the encounter is
        WRITTEN_OFF.
        """
        advance_clock_to("2026-02-01T00:00:00.000Z")
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=7777,
        )
        advance_clock_to("2026-05-02T00:00:00.000Z")
        data = validate_success(
            api.write_off_encounter(
                encounter["id"], TEST_USERS["biller_headers"],
            ),
            expected_status=201,
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "WRITTEN_OFF"
        assert refreshed["write_off_cents"] == data["write_off_cents"]
        assert refreshed["write_off_cents"] == 7777
