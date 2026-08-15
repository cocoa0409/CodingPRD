"""No-show follow-up: grace boundary, strike threshold cascade, excuse compensation,
risk score variants."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_referral, accept_referral,
    create_booked_referral, cancel_appointment,
    mark_no_show, excuse_appointment,
    set_clock, get_referral, get_patient, get_appointment, get_specialist,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _bootstrap():
    set_clock("2026-08-01T00:00:00Z")
    plan = create_plan()
    specialist = create_specialist()
    create_participation(specialist["id"], plan["id"])
    provider = create_provider()
    patient = create_patient(plan["id"])
    return plan, specialist, provider, patient


def _book_three_plus_observer(specialist, provider, patient):
    """Book R1/R2/R3 at 10/12/14:00 on 2026-08-01; R4 stays ACCEPTED (observer)."""
    r1, a1 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                    "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z",
                                    diagnosis_code="I10")
    r2, a2 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                    "2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z",
                                    diagnosis_code="I11")
    r3, a3 = create_booked_referral(provider["id"], patient["id"], specialist["id"],
                                    "2026-08-01T14:00:00Z", "2026-08-01T15:00:00Z",
                                    diagnosis_code="I20")
    r4 = accept_referral(create_referral(provider["id"], patient["id"],
                                         diagnosis_code="I25")["id"])
    return (r1, a1), (r2, a2), (r3, a3), r4


class TestNoShowGraceBoundary:
    def test_before_grace_rejected(self, api):
        """PRD §3.6: "This is allowed from either `SCHEDULED` or `CONFIRMED`, but
        only once now has reached the scheduled start plus a 15-minute grace —
        attempting it earlier fails with `ERR_NO_SHOW_TOO_EARLY`, and the boundary is
        inclusive, so exactly start-plus-15-minutes is allowed."

        Design: Difficulty/boundary_precision_check/no_show_grace_inclusive_boundary
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z",
        )
        set_clock("2026-08-01T10:14:59Z")
        res = api.mark_no_show(appointment["id"], COORD)
        validate_error(res, ApiErrorId.ERR_NO_SHOW_TOO_EARLY, expected_status=422)
        assert get_appointment(appointment["id"])["status"] == "SCHEDULED"

    def test_exactly_at_grace_allowed(self, api):
        """PRD §3.6: "the boundary is inclusive, so exactly start-plus-15-minutes is
        allowed."
        PRD §3.6: "Marking no-show sets the appointment to `NO_SHOW` ... the
        patient's `no_show_strikes` increments by 1".

        Design: Difficulty/boundary_precision_check/no_show_grace_inclusive_boundary
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z",
        )
        set_clock("2026-08-01T10:14:59Z")
        validate_error(api.mark_no_show(appointment["id"], COORD),
                       ApiErrorId.ERR_NO_SHOW_TOO_EARLY, expected_status=422)

        set_clock("2026-08-01T10:15:00Z")
        marked = validate_success(api.mark_no_show(appointment["id"], COORD))
        assert marked["status"] == "NO_SHOW"
        assert get_patient(patient["id"])["no_show_strikes"] == 1


class TestStrikeThresholdCascade:
    def test_intermediate_strikes_below_threshold(self, api):
        """PRD §3.2: "The posture threshold is a strike limit of 3: when
        `no_show_strikes` rises to at least 3 the patient's `status` flips from
        `ACTIVE` to `OUTREACH_REQUIRED`".
        PRD §3.6: "if no sibling appointment of the referral remains in `SCHEDULED`
        or `CONFIRMED`, the referral falls back from `SCHEDULED` to `ACCEPTED`".

        Design: Difficulty/transitive_cascade/no_show_strike_threshold_cascade
        """
        plan, specialist, provider, patient = _bootstrap()
        (r1, a1), (r2, a2), (r3, a3), r4 = _book_three_plus_observer(
            specialist, provider, patient
        )
        set_clock("2026-08-01T10:15:00Z")
        mark_no_show(a1["id"])
        p1 = get_patient(patient["id"])
        assert p1["no_show_strikes"] == 1 and p1["status"] == "ACTIVE"
        assert get_referral(r1["id"])["status"] == "ACCEPTED", (
            "R1 reverts to ACCEPTED after its appointment went NO_SHOW"
        )

        set_clock("2026-08-01T12:15:00Z")
        mark_no_show(a2["id"])
        p2 = get_patient(patient["id"])
        assert p2["no_show_strikes"] == 2 and p2["status"] == "ACTIVE", (
            "Two strikes are still below the limit of 3"
        )

    def test_third_strike_flips_patient_and_escalates_referrals(self, api):
        """PRD §3.6: "Marking no-show ... fires a three-link patient cascade: first,
        the patient's `no_show_strikes` increments by 1; second, if the increment
        lifts the count to at least the strike limit of 3, the patient's `status`
        flips to `OUTREACH_REQUIRED`; third, on that flip, every referral of that
        patient currently in `ACCEPTED` or `SCHEDULED` has its `escalation_flag` set
        true."
        PRD §3.2: "The boundary is inclusive on the way up — exactly 3 strikes
        triggers outreach".

        Design: Difficulty/transitive_cascade/no_show_strike_threshold_cascade
        """
        plan, specialist, provider, patient = _bootstrap()
        (r1, a1), (r2, a2), (r3, a3), r4 = _book_three_plus_observer(
            specialist, provider, patient
        )
        set_clock("2026-08-01T10:15:00Z")
        mark_no_show(a1["id"])
        set_clock("2026-08-01T12:15:00Z")
        mark_no_show(a2["id"])
        set_clock("2026-08-01T14:15:00Z")
        mark_no_show(a3["id"])

        patient_after = get_patient(patient["id"])
        assert patient_after["no_show_strikes"] == 3
        assert patient_after["status"] == "OUTREACH_REQUIRED"
        assert get_referral(r4["id"])["escalation_flag"] is True, (
            "R4 was never touched by the trigger calls yet must be escalated (link 3)"
        )


class TestStrikeExcuseCompensation:
    def test_posture_flip_and_reversal(self, api):
        """PRD §3.6: "excusing a `NO_SHOW` appointment ... decrements the patient's
        `no_show_strikes` by 1, and when the count thereby falls below 3 while the
        patient is `OUTREACH_REQUIRED`, returns the patient to `ACTIVE` and clears
        `escalation_flag` on every referral of that patient where it had been set."

        Design: Difficulty/compensating_invariant/strike_excuse_compensation
        """
        plan, specialist, provider, patient = _bootstrap()
        (r1, a1), (r2, a2), (r3, a3), r4 = _book_three_plus_observer(
            specialist, provider, patient
        )
        set_clock("2026-08-01T10:15:00Z")
        mark_no_show(a1["id"])
        set_clock("2026-08-01T12:15:00Z")
        mark_no_show(a2["id"])
        set_clock("2026-08-01T14:15:00Z")
        mark_no_show(a3["id"])
        assert get_patient(patient["id"])["status"] == "OUTREACH_REQUIRED"
        assert get_referral(r4["id"])["escalation_flag"] is True

        excuse_appointment(a2["id"], reason="Transport verified")
        patient_after = get_patient(patient["id"])
        assert patient_after["no_show_strikes"] == 2
        assert patient_after["status"] == "ACTIVE"
        assert get_referral(r4["id"])["escalation_flag"] is False, (
            "Full compensation: escalation cleared when the patient returns to ACTIVE"
        )

    def test_strike_ledger_matches_no_show_count(self, api):
        """PRD §3.2: "The `no_show_strikes` counter is the count of that patient's
        appointments currently in `NO_SHOW` status — appointments later excused out
        of `NO_SHOW` stop counting."

        Design: Difficulty/compensating_invariant/strike_excuse_compensation
        """
        plan, specialist, provider, patient = _bootstrap()
        (r1, a1), (r2, a2), (r3, a3), r4 = _book_three_plus_observer(
            specialist, provider, patient
        )
        set_clock("2026-08-01T10:15:00Z")
        mark_no_show(a1["id"])
        set_clock("2026-08-01T12:15:00Z")
        mark_no_show(a2["id"])
        set_clock("2026-08-01T14:15:00Z")
        mark_no_show(a3["id"])
        excuse_appointment(a2["id"], reason="Transport verified")

        assert get_appointment(a1["id"])["status"] == "NO_SHOW"
        assert get_appointment(a2["id"])["status"] == "EXCUSED"
        assert get_appointment(a3["id"])["status"] == "NO_SHOW"
        assert get_patient(patient["id"])["no_show_strikes"] == 2, (
            "Ledger conserved: strikes == COUNT(appointments in NO_SHOW) — "
            "a1 and a3 remain NO_SHOW; a2 is EXCUSED"
        )


class TestStateBeatsTemporalOnNoShow:
    def _setup_cancelled_appointment(self, api):
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_booked_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
        )
        cancel_appointment(appointment["id"])
        # Before the grace window (start 10:00 + 15m = 10:15).
        set_clock("2026-08-02T10:05:00Z")
        return patient, appointment

    def test_state_error_wins_over_grace_error(self, api):
        """PRD §2.7: "Seventh, state preconditions of the invoked transition
        (priority 7 — `ERR_INVALID_STATE`, `ERR_NOT_CONFIRMED`,
        `ERR_AUTH_NOT_SATISFIED`). ... Eleventh, temporal rules (priority 11 — ...
        `ERR_NO_SHOW_TOO_EARLY` and `ERR_COMPLETE_TOO_EARLY` at 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_no_show
        """
        patient, appointment = self._setup_cancelled_appointment(api)
        res = api.mark_no_show(appointment["id"], COORD)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_rejected_mark_leaves_no_side_effects(self, api):
        """PRD §2.7: "Seventh, state preconditions of the invoked transition
        (priority 7 — `ERR_INVALID_STATE`, `ERR_NOT_CONFIRMED`,
        `ERR_AUTH_NOT_SATISFIED`)."
        PRD §3.6: "Marking no-show sets the appointment to `NO_SHOW`, decrements the
        specialist's `booked_appointments_count` by 1, and fires a three-link patient
        cascade: first, the patient's `no_show_strikes` increments by 1" — a rejected
        mark fires none of these.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_no_show
        """
        patient, appointment = self._setup_cancelled_appointment(api)
        validate_error(api.mark_no_show(appointment["id"], COORD),
                       ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_appointment(appointment["id"])["status"] == "CANCELLED"
        assert get_patient(patient["id"])["no_show_strikes"] == 0


class TestNoShowRiskVariants:
    def _setup_risk_scenario(self, api):
        """A1 marked NO_SHOW; A2/A3 left SCHEDULED and overdue by >= 24h at read."""
        plan, specialist, provider, patient = _bootstrap()
        (r1, a1), (r2, a2), (r3, a3), _r4 = _book_three_plus_observer(
            specialist, provider, patient
        )
        set_clock("2026-08-01T10:15:00Z")
        mark_no_show(a1["id"])
        set_clock("2026-08-03T00:00:00Z")
        return patient["id"]

    def test_confirmed_variant_counts_only_strikes(self, api):
        """PRD §3.2: "The confirmed-only variant, `no_show_risk_confirmed`, is the
        strike weight of 25 multiplied by the current strike count, capped at 100."

        Design: Difficulty/dual_variant_calc/no_show_risk_confirmed_vs_forward
        """
        patient_id = self._setup_risk_scenario(api)
        patient = get_patient(patient_id)
        assert patient["no_show_strikes"] == 1
        assert patient["no_show_risk_confirmed"] == 25
        assert patient["status"] == "ACTIVE", "One strike is below the limit of 3"

    def test_forward_variant_adds_overdue_weight(self, api):
        """PRD §3.2: "The forward-looking variant, `no_show_risk_forward`,
        additionally counts overdue unconfirmed appointments: any appointment of the
        patient still in `SCHEDULED` status whose scheduled start plus 24 hours is at
        or before now contributes a weight of 0.5 each, so the score is the strike
        weight of 25 multiplied by the sum of the strike count plus half the overdue
        count, again capped at 100."
        PRD §3.2: "the forward score exceeds the confirmed score whenever such
        appointments exist".

        Design: Difficulty/dual_variant_calc/no_show_risk_confirmed_vs_forward
        """
        patient_id = self._setup_risk_scenario(api)
        patient = get_patient(patient_id)
        # strikes 1, overdue-unconfirmed 2 -> 25 x (1 + 0.5 x 2) = 50.
        assert patient["no_show_risk_forward"] == 50
        assert patient["no_show_risk_forward"] > patient["no_show_risk_confirmed"]


class TestRiskScoreCeiling:
    def test_forward_score_capped_at_100(self, api):
        """PRD §3.2: "The confirmed-only variant, `no_show_risk_confirmed`, is the
        strike weight of 25 multiplied by the current strike count, capped at 100."
        PRD §3.2: "... contributes a weight of 0.5 each, so the score is the strike
        weight of 25 multiplied by the sum of the strike count plus half the overdue
        count, again capped at 100."

        Design: Corner/calculations/no_show_risk_forward_capped_at_100
        """
        plan, specialist, provider, patient = _bootstrap()
        appointments = []
        for i, hour in enumerate((10, 12, 14, 16, 18)):
            _r, a = create_booked_referral(
                provider["id"], patient["id"], specialist["id"],
                f"2026-08-01T{hour:02d}:00:00Z", f"2026-08-01T{hour + 1:02d}:00:00Z",
                diagnosis_code=f"I2{i}",
            )
            appointments.append(a)
        for a in appointments[:4]:
            hh = int(a["scheduled_start"][11:13])
            set_clock(f"2026-08-01T{hh:02d}:15:00Z")
            mark_no_show(a["id"])
        # Fifth appointment (18:00) left SCHEDULED; at 2026-08-03 it is overdue > 24h.
        set_clock("2026-08-03T00:00:00Z")

        patient_after = get_patient(patient["id"])
        assert patient_after["no_show_strikes"] == 4
        assert patient_after["no_show_risk_confirmed"] == 100, "25 x 4 = 100"
        assert patient_after["no_show_risk_forward"] == 100, (
            "25 x (4 + 0.5 x 1) = 112.5 pre-cap; the cap binds at 100"
        )
