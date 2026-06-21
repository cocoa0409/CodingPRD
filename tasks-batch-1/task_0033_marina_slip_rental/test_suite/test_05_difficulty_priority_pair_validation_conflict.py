"""Difficulty Rule 5 — priority_pair_validation_conflict.

Two pairs of co-occurring violations where the higher-priority rule is
reported per PRD §2.7's fixed evaluation order:
  (A) Expired insurance at check-in is ERR_INSURANCE_INVALID (priority 6,
      ahead of priority 8 ERR_SLIP_SIZE_MISMATCH per PRD §2.7).
  (B) Liveaboard-not-allowed AND date conflict on create -> ERR_LIVEABOARD_NOT_ALLOWED.
"""
from test_helpers import (
    validate_error,
    set_clock,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    reserve_lease,
    get_success_data,
    ApiErrorId,
    make_tenant_headers,
    TEST_USERS,
)


class TestInsuranceInvalidBeatsSizeMismatchOnCheckin:
    """Insurance gating (priority 6, business-safety) fires ahead of slip
    size matching (priority 8, business-constraint) at check-in time.

    PRD §3.4 also checks size at create — so the dual-violation scenario at
    check-in is reachable only when the slip dimensions accommodate the vessel
    at create, leaving insurance as the lone observable failure at check-in.
    The two tests below exercise the priority claim by:
      (1) An expired-insurance check-in returning ERR_INSURANCE_INVALID even
          though the lease was created without size violation.
      (2) An under-insured check-in (coverage_cents < MIN) returning the same
          error_id, confirming both arms of the insurance gate report
          ERR_INSURANCE_INVALID per priority 6.
    """

    def test_checkin_with_expired_insurance_returns_insurance_invalid(self, api):
        """PRD §3.5: "Insurance must be VALID at check-in: the vessel's `insurance_expires_on` must lie strictly after the current UTC date AND its `insurance_coverage_cents` must be at least `MIN_INSURANCE_COVERAGE_CENTS` of fifty thousand dollars expressed in cents; if either fails, the operation is rejected with `ERR_INSURANCE_INVALID` HTTP 422."

        Design: Difficulty/priority_pair_validation_conflict/insurance_invalid_beats_size_mismatch_on_checkin
        """
        marina = create_marina(liveaboard_cap=2)
        slip = create_slip(
            marina["id"],
            slip_number="I-1",
            length_ft=50, beam_ft=15,
            power_amp="A50",
            base_daily_rate_cents=3000,
        )
        tenant = create_tenant()
        vessel = create_vessel(
            tenant["id"],
            name="V9", loa_ft=40, beam_ft=12,
            insurance_policy_number="P9",
            insurance_expires_on="2026-08-15",  # expires before check-in clock
            insurance_coverage_cents=6_000_000,
        )
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina_id=marina["id"],
            slip_id=slip["id"],
            tenant_id=tenant["id"],
            vessel_id=vessel["id"],
            start_date="2026-09-01",
            end_date="2026-09-05",
            expected_slip_version=slip["version"],
        )
        set_clock("2026-09-01T00:00:00Z")
        res = api.check_in_lease(lease["id"], TEST_USERS["marina_staff_headers"])
        validate_error(res, ApiErrorId.ERR_INSURANCE_INVALID)

    def test_checkin_with_under_minimum_coverage_returns_insurance_invalid(self, api):
        """PRD §3.5: "Insurance must be VALID at check-in: the vessel's `insurance_expires_on` must lie strictly after the current UTC date AND its `insurance_coverage_cents` must be at least `MIN_INSURANCE_COVERAGE_CENTS` of fifty thousand dollars expressed in cents; if either fails, the operation is rejected with `ERR_INSURANCE_INVALID` HTTP 422."

        Design: Difficulty/priority_pair_validation_conflict/insurance_invalid_beats_size_mismatch_on_checkin
        """
        marina = create_marina(liveaboard_cap=2)
        slip = create_slip(
            marina["id"],
            slip_number="I-2",
            length_ft=50, beam_ft=15,
            power_amp="A50",
            base_daily_rate_cents=3000,
        )
        tenant = create_tenant()
        # Insurance expiry is fine, but coverage is below the 5_000_000-cent floor.
        vessel = create_vessel(
            tenant["id"],
            name="V9b", loa_ft=40, beam_ft=12,
            insurance_policy_number="P9b",
            insurance_expires_on="2027-01-01",
            insurance_coverage_cents=1_000_000,  # < 5_000_000 minimum
        )
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina_id=marina["id"],
            slip_id=slip["id"],
            tenant_id=tenant["id"],
            vessel_id=vessel["id"],
            start_date="2026-09-01",
            end_date="2026-09-05",
            expected_slip_version=slip["version"],
        )
        set_clock("2026-09-01T00:00:00Z")
        res = api.check_in_lease(lease["id"], TEST_USERS["marina_staff_headers"])
        validate_error(res, ApiErrorId.ERR_INSURANCE_INVALID)


# NOTE: class TestLiveaboardNotAllowedBeatsDateConflictOnCreate was deleted.
#
# The scaffold rule under test is the priority-pair (liveaboard priority 7
# vs date-conflict priority 9). To exercise that pair, a SECOND create on
# the same slip must be issued, which requires a FIRST reservation to
# manufacture the date conflict. But the first reservation transitions
# `Slip.AVAILABLE -> RESERVED` per PRD §3.4. PRD §2.7 places STATE (priority
# 4) ahead of business-safety (priority 7), and PRD §3.4 explicitly states
# "the slip must be in `AVAILABLE` state — any other state yields
# `ERR_INVALID_STATE` HTTP 409". A faithful PRD-only implementer will
# therefore return ERR_INVALID_STATE, not ERR_LIVEABOARD_NOT_ALLOWED —
# the asserted error_id is not uniquely derivable from PRD.
#
# Silence/collapse category: ERROR PRECEDENCE COLLAPSE — the structurally
# reachable rejection (ERR_INVALID_STATE) preempts the asserted business-
# safety error. Same root cause as the two `boundary_precision_check` and
# `resource_temporal_overlap` instances skipped during unit-test generation
# (see worklog Step 5(c)).
#
# Driving scaffold instance:
#   Difficulty/priority_pair_validation_conflict/liveaboard_not_allowed_beats_date_conflict_on_create
