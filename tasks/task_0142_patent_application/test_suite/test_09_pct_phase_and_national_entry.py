"""PCT international phase, national entry, and PCT lapse.

Covers PRD §3.6 in full.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    PCT_NATIONAL_BASE_CENTS,
    PCT_NATIONAL_DEADLINE_MONTHS,
    advance_clock_to,
    assert_pct_phase,
    get_pct_phase,
    initiate_pct_phase,
    list_audit_events,
    make_applicant_headers,
    pay_fee,
    pay_pct_national_and_enter,
    pct_national_fee_cents,
    setup_filed_application,
    setup_granted_application,
    setup_pct_phase_filed,
    setup_under_examination,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# PCT initiation eligibility (PRD §3.6)
# ===========================================================================
class TestPCTInitiation:

    def test_initiate_pct_on_filed_utility_succeeds(self, api):
        """PRD §3.6: "PCT initiation is only permitted when the parent
        application's application_type is UTILITY and its status is one
        of FILED, UNDER_EXAMINATION, or OFFICE_ACTION_PENDING".
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        assert_pct_phase(pct)
        assert pct["status"] == "INTERNATIONAL"
        # Priority date copied from application.filed_at per PRD §3.6.
        assert pct["application_id"] == app["id"]

    def test_initiate_pct_on_design_rejected(self, api):
        """PRD §3.6: "design, provisional, allowed, or granted
        applications cannot be elevated to PCT, and any such attempt
        is rejected with ERR_PCT_INELIGIBLE."
        """
        a, app = setup_filed_application(application_type="DESIGN")
        res = api.initiate_pct_phase(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PCT_INELIGIBLE.value)

    def test_initiate_pct_on_provisional_rejected(self, api):
        """PRD §3.6: "design, provisional, allowed, or granted
        applications cannot be elevated to PCT".
        """
        a, app = setup_filed_application(application_type="PROVISIONAL")
        res = api.initiate_pct_phase(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PCT_INELIGIBLE.value)

    def test_initiate_pct_on_granted_utility_rejected(self, api):
        """PRD §3.6: "allowed, or granted applications cannot be
        elevated to PCT, and any such attempt is rejected with
        ERR_PCT_INELIGIBLE."
        """
        a, granted = setup_granted_application(application_type="UTILITY")
        res = api.initiate_pct_phase(granted["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PCT_INELIGIBLE.value)

    def test_initiate_pct_on_under_examination_succeeds(self, api):
        """PRD §3.6: "PCT initiation is only permitted when the parent
        application's application_type is UTILITY and its status is one
        of FILED, UNDER_EXAMINATION, or OFFICE_ACTION_PENDING".

        Claim: UNDER_EXAMINATION is a valid antecedent for PCT
        initiation.
        """
        a, app = setup_under_examination(application_type="UTILITY")
        res = api.initiate_pct_phase(app["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert data["status"] == "INTERNATIONAL"


# ===========================================================================
# PCT national_phase_deadline (PRD §3.6)
# ===========================================================================
class TestPCTNationalDeadline:

    def test_national_phase_deadline_is_priority_plus_30_months(self, api):
        """PRD §3.6: "The 30-month national-phase deadline is then
        computed forward: national_phase_deadline_at is priority_date
        plus 30 months."

        Claim: national_phase_deadline_at == priority_date + 30 calendar
        months for any newly-initiated PCTPhase.
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        priority = datetime.fromisoformat(pct["priority_date"].replace("Z", "+00:00"))
        deadline = datetime.fromisoformat(
            pct["national_phase_deadline_at"].replace("Z", "+00:00"),
        )
        # 30 calendar months ≈ priority + 30 months. Use month math.
        y = priority.year + (priority.month - 1 + 30) // 12
        m = (priority.month - 1 + 30) % 12 + 1
        expected = priority.replace(year=y, month=m)
        assert deadline == expected, (
            f"PRD §3.6: national_phase_deadline_at must be priority_date + 30 months. "
            f"priority={priority}, deadline={deadline}, expected={expected}"
        )


# ===========================================================================
# Enter national phase (PRD §3.6)
# ===========================================================================
class TestPCTEnterNational:

    def test_enter_national_succeeds_before_deadline(self, api):
        """PRD §3.6: "The transition requires that SystemClock.now is at
        or before national_phase_deadline_at and that a
        PCT_NATIONAL-category fee transaction exists at the expected
        national-entry amount for the applicant's entity_size."
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        # Advance well before deadline.
        advance_clock_to(DEFAULT_BASE_CLOCK + timedelta(days=300))
        result = pay_pct_national_and_enter(a, app, pct)
        assert result["status"] == "NATIONAL_ENTERED"
        assert result["national_entered_at"] is not None

    def test_enter_national_past_deadline_rejected(self, api):
        """PRD §3.6: "A national-entry attempt after the 30-month
        deadline is rejected with ERR_PCT_DEADLINE_PASSED."

        Per PRD §2.8 the clock-advance sweep flips the PCT row to
        LAPSED when the clock crosses national_phase_deadline_at. Under
        PRD §2.11 priority the state check (priority 6) runs before
        the PCT temporal check (priority 12), so a post-sweep call may
        reasonably return ERR_INVALID_STATE instead. Both readings are
        PRD-faithful; the test accepts either.
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        deadline = datetime.fromisoformat(
            pct["national_phase_deadline_at"].replace("Z", "+00:00"),
        )
        # 1 second past deadline — sweep lapses the PCT row.
        advance_clock_to(deadline + timedelta(seconds=1))
        # Pay the fee anyway; the temporal/state precondition wins.
        pay_fee(a, app, "PCT_NATIONAL", pct_national_fee_cents(a["entity_size"]))
        res = api.enter_national_phase(pct["id"], make_applicant_headers(a["id"]))
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_PCT_DEADLINE_PASSED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_enter_national_without_fee_rejected(self, api):
        """PRD §3.6: "The transition requires ... a PCT_NATIONAL-category
        fee transaction exists at the expected national-entry amount
        for the applicant's entity_size."
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        # Within deadline, no fee paid.
        advance_clock_to(DEFAULT_BASE_CLOCK + timedelta(days=300))
        res = api.enter_national_phase(pct["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)


# ===========================================================================
# PCT lapse cascade (PRD §3.6)
# ===========================================================================
class TestPCTLapse:

    def test_clock_past_deadline_lapses_pct_phase(self, api):
        """PRD §3.6: "When the clock advances past
        national_phase_deadline_at while the PCT row is still
        INTERNATIONAL, the deadline sweep deterministically flips its
        status to LAPSED and writes a PCT_LAPSED audit row; if the
        parent application later expires by the same sweep its status
        field becomes EXPIRED."
        """
        a, app, pct = setup_pct_phase_filed(entity_size="SMALL")
        deadline = datetime.fromisoformat(
            pct["national_phase_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline + timedelta(seconds=1))
        pct_after = get_pct_phase(pct["id"])
        assert pct_after["status"] == "LAPSED"
        # Audit row.
        events = list_audit_events(app["id"])
        actions = [e["action"] for e in events]
        assert "PCT_LAPSED" in actions, (
            "PRD §3.6: clock past deadline must write PCT_LAPSED audit"
        )


# ===========================================================================
# PCT fee math (PRD §3.6 + §2.7)
# ===========================================================================
class TestPCTFeeMath:

    @pytest.mark.parametrize(
        "entity_size,expected",
        [("LARGE", 51000), ("SMALL", 25500), ("MICRO", 12750)],
    )
    def test_pct_national_fee_matrix(self, entity_size, expected):
        """PRD §3.6: "The PCT national-entry base fee is 51000 cents at
        the large-entity rate; this base is multiplied by the
        applicant's entity multiplier from §2.7 and rounded half-up to
        integer cents in a single step."
        """
        assert pct_national_fee_cents(entity_size) == expected
