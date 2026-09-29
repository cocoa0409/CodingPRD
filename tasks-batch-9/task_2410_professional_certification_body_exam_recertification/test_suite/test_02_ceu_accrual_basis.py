"""The two continuing-education accrual windows, pinned per cycle."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    ELIGIBILITY_REVIEWER_3_ID,
    make_eligibility_reviewer_headers,
)

REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_3_ID)

CARRYOVER_PROGRAM = {"name": "Certified Practitioner X", "credential_code": "CPX",
                     "ceu_credit_accrual_basis": "CARRYOVER_ALLOWED"}
STRICT_PROGRAM = {"name": "Certified Practitioner Y", "credential_code": "CPY",
                  "ceu_credit_accrual_basis": "STRICT_CYCLE"}
SECOND_CREDENTIAL = {
    "candidate_overrides": {"email": "cand.b@example.com", "full_name": "Cand B"},
    "form_overrides": {"form_code": "CPY-F1"},
    "session_overrides": {"room_code": "R2"},
}

# Twenty-six days before the cycle opens on 2026-08-10, so inside a
# ninety-day look-back window and outside a strict one.
EARLY_ACTIVITY = {"activity_date": "2026-07-15T00:00:00Z", "category": "LIVE_INSTRUCTION",
                  "provider": "State Institute", "contact_hours": 12}


class TestCarryoverAllowedLookBack:
    """A claim dated before the cycle opened, under the extended window."""

    def test_look_back_window_accepts_the_claim_and_awards_one_credit_per_hour(self, api):
        """Under CARRYOVER_ALLOWED the window starts 90 days before ``starts_on``,
        so a claim dated 26 days early is accepted, and 12 LIVE_INSTRUCTION hours
        are recorded at once as 12.00 credits that do not yet count.

        PRD §3.11: "Under `CARRYOVER_ALLOWED`, the window is extended backwards by
        a 90-day look-back, so it runs from 90 days before `starts_on` through
        `ends_on` inclusive".

        PRD §3.11: "an hour of `LIVE_INSTRUCTION` is worth 1.0 credits".

        PRD §3.11: "A new claim has its `cycle_id` set to the cycle it was claimed
        against, `status` `SUBMITTED`, `counted` false, `credits_counted` 0.00".

        Design: Difficulty/dual_variant_calc/ceu_credit_accrual_carryover_lookback_counts_where_strict_cycle_bars_the_same_activity
        """
        state = fx.pipeline_through_certificant(api, program_overrides=CARRYOVER_PROGRAM)
        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["accrual_basis_snapshot"] == "CARRYOVER_ALLOWED"

        activity = validate_success(api.claim_ceu_activity(
            state.cycle_id, f.claim_ceu_payload(**EARLY_ACTIVITY), state.owner_headers), 201)

        assert activity["cycle_id"] == state.cycle_id
        assert activity["status"] == "SUBMITTED"
        assert activity["counted"] is False
        assert float(activity["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert float(activity["credits_counted"]) == pytest.approx(0.00, abs=0.01)
        assert fx.read_cycle(api, state.cycle_id)["credits_applied"] == pytest.approx(
            0.00, abs=0.01)

    def test_approval_counts_the_early_claim_and_carries_the_cycle_over_the_line(self, api):
        """Approval sets ``counted``, which re-runs accrual: the counted award
        becomes ``credits_counted``, the cycle's applied total reaches its pinned
        requirement, and the cycle bubbles to SATISFIED with the certificant's
        mirror following.

        PRD §3.11: "An `APPROVE` requires the activity to be `SUBMITTED`, moves it
        `SUBMITTED → APPROVED`, and sets `counted` to true."

        PRD §3.11: "A `CEU`-path cycle is `SATISFIED` exactly when its
        `credits_applied` is greater than or equal to its `required_credits`, with
        exact equality satisfying".

        PRD §3.10: "`ceu_credits_applied` mirrors the `credits_applied` of the
        certificant's cycle whose `status` is `OPEN` or `SATISFIED`".

        Design: Difficulty/dual_variant_calc/ceu_credit_accrual_carryover_lookback_counts_where_strict_cycle_bars_the_same_activity
        """
        state = fx.pipeline_through_certificant(api, program_overrides=CARRYOVER_PROGRAM)
        claimed = validate_success(api.claim_ceu_activity(
            state.cycle_id, f.claim_ceu_payload(**EARLY_ACTIVITY), state.owner_headers), 201)

        reviewed = validate_success(api.review_ceu_activity(
            claimed["id"], f.review_ceu_payload("APPROVE"), REVIEWER), 200)

        assert reviewed["status"] == "APPROVED"
        assert reviewed["counted"] is True
        assert float(reviewed["credits_counted"]) == pytest.approx(12.00, abs=0.01)
        assert reviewed["reviewer_user_id"] == ELIGIBILITY_REVIEWER_3_ID

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["required_credits"] == pytest.approx(12, abs=0.01)
        assert float(cycle["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert cycle["status"] == "SATISFIED"

        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(12.00, abs=0.01)


class TestStrictCycleWindow:
    """The same claim against a strictly windowed cycle."""

    def test_strict_cycle_refuses_a_claim_dated_before_the_cycle_opened(self, api):
        """Under STRICT_CYCLE the window starts at ``starts_on``, so the identical
        activity date is refused outright at submission time.

        PRD §3.11: "Under `STRICT_CYCLE`, the accrual window runs from the cycle's
        `starts_on` to its `ends_on` with both ends inclusive".

        PRD §3.11: "an activity dated 90 days before `starts_on` counts under
        `CARRYOVER_ALLOWED` and is rejected at submission time with
        `ERR_ACTIVITY_OUTSIDE_CYCLE` under `STRICT_CYCLE`."

        Design: Difficulty/dual_variant_calc/ceu_credit_accrual_carryover_lookback_counts_where_strict_cycle_bars_the_same_activity
        """
        state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["accrual_basis_snapshot"] == "STRICT_CYCLE"

        refused = api.claim_ceu_activity(
            state.cycle_id, f.claim_ceu_payload(**EARLY_ACTIVITY), state.owner_headers)

        validate_error(refused, ApiErrorId.ERR_ACTIVITY_OUTSIDE_CYCLE.value, 422)

        unchanged = fx.read_cycle(api, state.cycle_id)
        assert float(unchanged["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert unchanged["status"] == "OPEN"
        assert fx.read_activities_of(api, state.cycle_id) == []

        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(0.00, abs=0.01)


class TestAccrualBasisIsPinnedPerCycle:
    """Two credentials minted the same day disagree only about their window."""

    def test_each_first_cycle_pins_its_own_programme_basis_and_window(self, api):
        """The two cycles open on the same day with the same twelve-month span and
        ninety-day grace, and differ only in the basis each pinned at creation.

        PRD §3.11: "its `ends_on` is `starts_on` advanced by the program's
        `cycle_length_months`, and its `grace_ends_on` is `ends_on` advanced by the
        program's `recert_grace_days`".

        PRD §3.11: "`accrual_basis_snapshot` pins the program's
        `ceu_credit_accrual_basis` as either `STRICT_CYCLE` or `CARRYOVER_ALLOWED`."

        PRD §3.10: "its `certificate_number` is minted as described below".

        Design: Difficulty/dual_variant_calc/ceu_credit_accrual_carryover_lookback_counts_where_strict_cycle_bars_the_same_activity
        """
        carryover = fx.pipeline_through_certificant(api, program_overrides=CARRYOVER_PROGRAM)
        # The first chain left the clock at its session's ``starts_at``; rewind it
        # so the second chain's seat claim is not refused on a closed session.
        fx.reset_clock(api)
        strict = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM,
                                                **SECOND_CREDENTIAL)

        carryover_cycle = fx.read_cycle(api, carryover.cycle_id)
        strict_cycle = fx.read_cycle(api, strict.cycle_id)

        assert carryover_cycle["accrual_basis_snapshot"] == "CARRYOVER_ALLOWED"
        assert strict_cycle["accrual_basis_snapshot"] == "STRICT_CYCLE"

        for cycle in (carryover_cycle, strict_cycle):
            assert cycle["cycle_number"] == 1
            assert cycle["path"] == "CEU"
            assert str(cycle["starts_on"]).startswith("2026-08-10")
            assert str(cycle["ends_on"]).startswith("2027-08-10")
            assert str(cycle["grace_ends_on"]).startswith("2027-11-08")
            assert float(cycle["carryover_credits_in"]) == pytest.approx(0.00, abs=0.01)

        assert carryover.certificate_number == "CPX-2026-00001"
        assert strict.certificate_number == "CPY-2026-00001"
