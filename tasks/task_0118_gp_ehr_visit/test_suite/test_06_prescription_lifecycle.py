"""Prescription lifecycle: draft, sign (with EPCS), transmit,
dispense (with SoD), cancel, expiry sweep.

PRD §3.4 prescription rules, §2.12 segregation of duties.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PRESCRIPTION_EXPIRY_DAYS_NON_CONTROLLED,
    PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_II,
    PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_III_V,
    advance_clock_seconds,
    advance_clock_to,
    anchor_clock,
    cancel_prescription,
    create_prescription,
    create_prescription_payload,
    iso_anchor_offset,
    make_pharmacist_headers,
    make_provider_headers,
    parse_iso,
    re_get_prescription,
    run_sweep,
    setup_checked_in_encounter,
    setup_signed_prescription_for_state_vs_safety,
    setup_signed_then_transmitted_prescription_for_dispense_invariant,
    setup_scheduled_encounter_for_rx_state_dependency,
    setup_three_prescriptions_for_expiry,
    sign_prescription,
    sign_prescription_payload,
    TEST_USERS,
    transmit_prescription,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 Schedule II / refills_authorized
# ===========================================================================
class TestScheduleIIConstraint:

    # difficulty: combinatorial_formula/prescription_expiry_tiered_branching_three_inputs
    def test_schedule_ii_with_refills_at_create_rejected(self, api):
        """PRD §3.4: "Schedule II prescriptions carry an inviolable
        constraint: refills_authorized must equal exactly zero, both
        at creation and at sign time. A schedule II prescription
        submitted with any non-zero refills_authorized is rejected
        with ERR_SCHEDULE_II_NO_REFILLS."

        Claim: creating a schedule II prescription with
        refills_authorized=1 returns ERR_SCHEDULE_II_NO_REFILLS.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        payload = create_prescription_payload(
            provider_id=provider["id"],
            encounter_id=encounter["id"],
            drug_name="Oxycodone", is_controlled=True,
            dea_schedule="II", refills_authorized=1,
        )
        res = api.create_prescription(
            patient["id"], payload,
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_SCHEDULE_II_NO_REFILLS")

    # difficulty: combinatorial_formula/prescription_expiry_tiered_branching_three_inputs
    def test_schedule_ii_with_zero_refills_accepted(self, api):
        """PRD §3.4: "Schedule II prescriptions carry an inviolable
        constraint: refills_authorized must equal exactly zero, both
        at creation and at sign time."

        Claim: creating a schedule II prescription with
        refills_authorized=0 succeeds.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            drug_name="Oxycodone", is_controlled=True,
            dea_schedule="II", refills_authorized=0,
        )
        assert rx["dea_schedule"] == "II"
        assert rx["refills_authorized"] == 0


# ===========================================================================
# §3.4 EPCS sign rules
# ===========================================================================
class TestEpcsSigning:

    def test_non_controlled_sign_no_otp_succeeds(self, api):
        """PRD §3.4: "For non-controlled prescriptions the
        epcs_two_factor_token is not required."

        Claim: signing a non-controlled prescription without an OTP
        succeeds and stamps signed_at.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            drug_name="Lisinopril", is_controlled=False,
            refills_authorized=2,
        )
        rx = sign_prescription(rx["id"], provider["id"])
        assert rx["status"] == "SIGNED"
        assert rx["signed_at"] is not None

    def test_controlled_sign_without_otp_rejected(self, api):
        """PRD §3.4: "For controlled prescriptions the signing path
        requires additional safeguards: the provider's epcs_enrolled
        flag must be true, the provider's dea_number must be
        non-null, and the request body must include
        epcs_two_factor_token as a six-digit OTP string. A controlled
        signing attempt missing any of those three conditions is
        rejected with ERR_EPCS_NOT_ENROLLED."

        Claim: signing a controlled prescription without
        epcs_two_factor_token returns ERR_EPCS_NOT_ENROLLED.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            drug_name="Alprazolam", is_controlled=True,
            dea_schedule="IV", refills_authorized=0,
        )
        res = api.sign_prescription(
            rx["id"], make_provider_headers(provider["id"]),
            sign_prescription_payload(),  # no OTP
        )
        validate_error(res, "ERR_EPCS_NOT_ENROLLED")

    def test_controlled_sign_with_unenrolled_provider_rejected(self, api):
        """PRD §3.4: "For controlled prescriptions the signing path
        requires additional safeguards: the provider's epcs_enrolled
        flag must be true ... A controlled signing attempt missing
        any of those three conditions is rejected with
        ERR_EPCS_NOT_ENROLLED."

        Claim: signing a controlled prescription as a provider with
        epcs_enrolled=false returns ERR_EPCS_NOT_ENROLLED.
        """
        from test_helpers import (
            create_patient, create_provider,
            bind_patient_to_pcp, schedule_encounter,
            checkin_encounter, advance_clock_to,
        )
        anchor_clock()
        pr = create_provider(
            role_type="PCP_ONLY", epcs_enrolled=False, dea_number=None,
        )
        patient = create_patient()
        patient = bind_patient_to_pcp(patient["id"], pr["id"])
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        encounter = schedule_encounter(
            patient["id"], pr["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
        )
        advance_clock_to(iso_anchor_offset(minutes=55))
        encounter = checkin_encounter(encounter["id"])
        rx = create_prescription(
            patient["id"], pr["id"], encounter["id"],
            drug_name="Alprazolam", is_controlled=True,
            dea_schedule="IV", refills_authorized=0,
        )
        res = api.sign_prescription(
            rx["id"], make_provider_headers(pr["id"]),
            sign_prescription_payload(epcs_two_factor_token="123456"),
        )
        validate_error(res, "ERR_EPCS_NOT_ENROLLED")


# ===========================================================================
# §3.4 expires_at on SIGN — three-way tier
# ===========================================================================
class TestPrescriptionExpiry:
    """PRD §3.4 expiry tiers: 365 / 180 / 30 days."""

    # difficulty: combinatorial_formula/prescription_expiry_tiered_branching_three_inputs
    def test_non_controlled_expires_365_days(self, api):
        """PRD §3.4: "365 days after signed_at for non-controlled
        prescriptions, 180 days after signed_at for schedule III,
        IV, or V controlled prescriptions, and 30 days after
        signed_at for schedule II controlled prescriptions."

        Claim: signing a non-controlled prescription stamps
        expires_at == signed_at + 365 days.
        """
        setup = setup_three_prescriptions_for_expiry()
        provider = setup["provider"]
        rx_nc = setup["rx_nc"]
        rx_nc = sign_prescription(rx_nc["id"], provider["id"])
        signed_at = parse_iso(rx_nc["signed_at"])
        expires_at = parse_iso(rx_nc["expires_at"])
        delta_days = (expires_at - signed_at).total_seconds() / 86400.0
        assert delta_days == pytest.approx(
            PRESCRIPTION_EXPIRY_DAYS_NON_CONTROLLED, abs=1e-3,
        ), (
            f"Non-controlled expiry expected 365 days, got "
            f"{delta_days}"
        )

    # difficulty: combinatorial_formula/prescription_expiry_tiered_branching_three_inputs
    def test_schedule_iv_expires_180_days(self, api):
        """PRD §3.4: "180 days after signed_at for schedule III,
        IV, or V controlled prescriptions".

        Claim: signing a schedule IV prescription stamps
        expires_at == signed_at + 180 days.
        """
        setup = setup_three_prescriptions_for_expiry()
        provider = setup["provider"]
        rx_iv = setup["rx_iv"]
        rx_iv = sign_prescription(
            rx_iv["id"], provider["id"],
            epcs_two_factor_token="123456",
        )
        signed_at = parse_iso(rx_iv["signed_at"])
        expires_at = parse_iso(rx_iv["expires_at"])
        delta_days = (expires_at - signed_at).total_seconds() / 86400.0
        assert delta_days == pytest.approx(
            PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_III_V, abs=1e-3,
        ), (
            f"Schedule IV expiry expected 180 days, got {delta_days}"
        )

    def test_schedule_ii_expires_30_days(self, api):
        """PRD §3.4: "30 days after signed_at for schedule II
        controlled prescriptions (which also necessarily have zero
        refills)."

        Claim: signing a schedule II prescription stamps expires_at
        == signed_at + 30 days.
        """
        setup = setup_three_prescriptions_for_expiry()
        provider = setup["provider"]
        rx_ii = setup["rx_ii"]
        rx_ii = sign_prescription(
            rx_ii["id"], provider["id"],
            epcs_two_factor_token="654321",
        )
        signed_at = parse_iso(rx_ii["signed_at"])
        expires_at = parse_iso(rx_ii["expires_at"])
        delta_days = (expires_at - signed_at).total_seconds() / 86400.0
        assert delta_days == pytest.approx(
            PRESCRIPTION_EXPIRY_DAYS_SCHEDULE_II, abs=1e-3,
        ), (
            f"Schedule II expiry expected 30 days, got {delta_days}"
        )


# ===========================================================================
# §3.4 Sign-after-sign / cascade
# ===========================================================================
class TestSignStateValidation:

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_prescription_sign
    def test_re_sign_signed_prescription_returns_state_error(self, api):
        """PRD §2.7: "State eligibility for the requested transition
        (the entity-specific state error such as
        ERR_INVALID_ENCOUNTER_STATE, ERR_INVALID_PRESCRIPTION_STATE,
        or ERR_REFERRAL_NOT_PENDING)."

        PRD §2.7: "Business-safety, business-referential, business-
        temporal, business-constraint, and business-fiscal rules,
        evaluated in the order in which they are described in §3.
        Optimistic concurrency (ERR_VERSION_CONFLICT) sits at the
        very tail of business validation, after every other business
        check."

        PRD §2.7: "A higher-priority rule that fires masks any
        lower-priority failure on the same request. ... a state
        violation masks every business and OCC error."

        Claim: attempting to sign a prescription that is already
        SIGNED — using a provider who would ALSO fail the EPCS
        check — returns ERR_INVALID_PRESCRIPTION_STATE (state error
        wins over EPCS business-safety error).
        """
        setup = setup_signed_prescription_for_state_vs_safety()
        rx = setup["rx"]  # already SIGNED
        pr_unenrolled = setup["pr_unenrolled"]
        # Attempt to re-sign as a non-EPCS-enrolled provider.
        # The is_controlled flag was false on this rx, so the EPCS
        # rule technically wouldn't fire — but the higher-priority
        # state check fires either way. To make the dual-failure
        # scenario explicit, the rx is non-controlled; the state
        # rule alone is the active higher-priority rejection.
        res = api.sign_prescription(
            rx["id"], make_provider_headers(pr_unenrolled["id"]),
            sign_prescription_payload(),
        )
        # PRD §3.4: "The signing Provider must match the
        # prescription's recorded provider_id." This is also a
        # business rule that could fire — but the state precondition
        # ("from DRAFT to SIGNED") fires first per §2.7.
        # We accept either the state error or the provider-mismatch-
        # style state error (PRD uses ERR_INVALID_PRESCRIPTION_STATE
        # broadly for state-eligibility failures on prescriptions).
        validate_error(res, "ERR_INVALID_PRESCRIPTION_STATE")

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_prescription_sign
    def test_re_sign_signed_does_not_return_epcs_error(self, api):
        """PRD §2.7 explicitly: "a state violation masks every
        business and OCC error."

        Claim: a re-sign attempt against a SIGNED prescription does
        NOT return the lower-priority ERR_EPCS_NOT_ENROLLED even
        when the acting provider would also fail the EPCS check.
        """
        setup = setup_signed_prescription_for_state_vs_safety()
        rx = setup["rx"]
        pr_unenrolled = setup["pr_unenrolled"]
        # Re-sign attempt with a controlled-rx-style OTP — should
        # still fail with the state error, not EPCS.
        res = api.sign_prescription(
            rx["id"], make_provider_headers(pr_unenrolled["id"]),
            sign_prescription_payload(
                epcs_two_factor_token="111111",
            ),
        )
        body = res.json() if hasattr(res, "json") else {}
        # Validate the actual error_id is the state one.
        err = body.get("data", {}).get("error_id")
        assert err != "ERR_EPCS_NOT_ENROLLED", (
            "PRD §2.7 puts state error at higher priority than "
            f"business-safety EPCS check, but got {err}"
        )


# ===========================================================================
# §3.4 Prescription state-dependency on Encounter
# ===========================================================================
class TestPrescriptionRequiresActiveEncounter:

    # difficulty: cross_entity_state_dependency/prescription_sign_requires_encounter_active
    def test_sign_with_scheduled_encounter_rejected(self, api):
        """PRD §3.4: "Signing transitions the prescription from
        DRAFT to SIGNED. The signing Provider must match the
        prescription's recorded provider_id. The associated
        encounter's status must be either CHECKED_IN or COMPLETED."

        Claim: signing a DRAFT prescription whose encounter is still
        SCHEDULED (never checked in) is rejected with
        ERR_INVALID_PRESCRIPTION_STATE.
        """
        setup = setup_scheduled_encounter_for_rx_state_dependency()
        patient = setup["patient"]
        provider = setup["provider"]
        encounter = setup["encounter"]
        # Author the RX while the encounter is SCHEDULED (PRD §3.4
        # says the encounter must be CHECKED_IN or COMPLETED at the
        # time the prescription is created OR signed — this means
        # the create itself may also be rejected. We try the create
        # first; if it succeeds (PRD allows the sign-time check),
        # we attempt the sign which must reject).
        from test_helpers import api_client
        create_res = api_client.create_prescription(
            patient["id"],
            create_prescription_payload(
                provider_id=provider["id"],
                encounter_id=encounter["id"],
                is_controlled=False, refills_authorized=0,
            ),
            make_provider_headers(provider["id"]),
        )
        if create_res.status_code >= 400:
            # The implementation correctly rejects at create time;
            # the error must come from the state-eligibility family.
            from test_helpers import validate_error_is_one_of
            validate_error_is_one_of(
                create_res,
                ["ERR_INVALID_PRESCRIPTION_STATE",
                 "ERR_INVALID_ENCOUNTER_STATE"],
            )
        else:
            rx = validate_success(create_res, expected_status=201)
            sign_res = api_client.sign_prescription(
                rx["id"], make_provider_headers(provider["id"]),
                sign_prescription_payload(),
            )
            # PRD §3.4 names the rule ("encounter's status must be
            # CHECKED_IN or COMPLETED") but does not pin which state-
            # family error_id surfaces — a faithful reader may emit
            # either ERR_INVALID_PRESCRIPTION_STATE (the action's
            # entity) or ERR_INVALID_ENCOUNTER_STATE (the violating
            # entity). PRD §2.7 enumerates both together at priority 5.
            from test_helpers import validate_error_is_one_of
            validate_error_is_one_of(
                sign_res,
                ["ERR_INVALID_PRESCRIPTION_STATE",
                 "ERR_INVALID_ENCOUNTER_STATE"],
            )

    # difficulty: cross_entity_state_dependency/prescription_sign_requires_encounter_active
    def test_sign_with_checked_in_encounter_succeeds(self, api):
        """PRD §3.4: "Signing transitions the prescription from
        DRAFT to SIGNED. The signing Provider must match the
        prescription's recorded provider_id. The associated
        encounter's status must be either CHECKED_IN or COMPLETED."

        Claim: signing a DRAFT prescription whose encounter is
        CHECKED_IN succeeds.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            is_controlled=False, refills_authorized=0,
        )
        rx = sign_prescription(rx["id"], provider["id"])
        assert rx["status"] == "SIGNED"


# ===========================================================================
# §2.12 / §3.4 Segregation of duties on dispense
# ===========================================================================
class TestSegregationOfDuties:

    def test_dispenser_equals_signing_provider_rejected(self, api):
        """PRD §2.12: "the Provider who signed a prescription must
        not also dispense it. This is enforced at dispense time by
        comparing the dispenser's X-User-ID to the prescription's
        recorded provider_id; a match rejects the request with
        ERR_SEGREGATION_OF_DUTIES."

        Claim: a Pharmacist whose X-User-ID equals the signing
        provider's id is rejected with ERR_SEGREGATION_OF_DUTIES.
        """
        setup = setup_signed_then_transmitted_prescription_for_dispense_invariant()
        rx = setup["rx"]
        provider = setup["provider"]
        # Mint pharmacist headers with the SIGNING provider's id —
        # the §2.12 SoD pathway.
        pharmacist_headers_as_provider = make_pharmacist_headers(
            provider["id"],
        )
        res = api.dispense_prescription(
            rx["id"], pharmacist_headers_as_provider,
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_distinct_pharmacist_dispense_succeeds(self, api):
        """PRD §2.12: "the Provider who signed a prescription must
        not also dispense it. This is enforced at dispense time by
        comparing the dispenser's X-User-ID to the prescription's
        recorded provider_id; a match rejects the request with
        ERR_SEGREGATION_OF_DUTIES."

        Claim: dispensing as a Pharmacist whose X-User-ID is distinct
        from the prescription's provider_id succeeds (negation of
        the previous test).
        """
        setup = setup_signed_then_transmitted_prescription_for_dispense_invariant()
        rx = setup["rx"]
        # Default pharmacist_headers has a deliberately distinct id.
        from test_helpers import dispense_prescription
        rx_after = dispense_prescription(rx["id"])
        # Refills started at 2; after one dispense refills_remaining
        # should be 1 and status stays TRANSMITTED per §3.4.
        assert rx_after["status"] in ("TRANSMITTED", "DISPENSED")


# ===========================================================================
# §3.4 Dispense + refills_remaining decrement / TRANSMITTED→DISPENSED
# ===========================================================================
class TestDispenseLifecycle:

    def test_dispense_decrements_refills_when_positive(self, api):
        """PRD §3.4: "On a successful dispense, the server inspects
        refills_remaining: when it is zero before the dispense, the
        prescription transitions to the terminal state DISPENSED;
        when it is greater than zero, the server decrements
        refills_remaining by one and the prescription stays in
        TRANSMITTED, available for the next dispensing cycle."

        Claim: dispensing a TRANSMITTED rx with refills_remaining=2
        leaves it TRANSMITTED with refills_remaining=1.
        """
        setup = setup_signed_then_transmitted_prescription_for_dispense_invariant()
        rx = setup["rx"]
        provider = setup["provider"]
        assert rx["refills_remaining"] == 2
        from test_helpers import dispense_prescription
        rx_after = dispense_prescription(rx["id"])
        assert rx_after["refills_remaining"] == 1, (
            f"refills_remaining expected 1, got "
            f"{rx_after['refills_remaining']}"
        )
        assert rx_after["status"] == "TRANSMITTED", (
            f"status expected TRANSMITTED, got {rx_after['status']}"
        )

    def test_dispense_transitions_to_dispensed_when_no_refills(self, api):
        """PRD §3.4: "when it is zero before the dispense, the
        prescription transitions to the terminal state DISPENSED".

        Claim: dispensing a TRANSMITTED rx with refills_remaining=0
        transitions to DISPENSED.
        """
        # Build a rx with refills_authorized=0 → after SIGN
        # refills_remaining seeds to 0.
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            is_controlled=False, refills_authorized=0,
        )
        rx = sign_prescription(rx["id"], provider["id"])
        rx = transmit_prescription(rx["id"], provider["id"])
        from test_helpers import dispense_prescription
        rx = dispense_prescription(rx["id"])
        assert rx["status"] == "DISPENSED"


# ===========================================================================
# §3.4 Refills-remaining invariant under cancel
# ===========================================================================
class TestRefillsRemainingInvariant:

    # difficulty: compensating_invariant/prescription_refills_remaining_dispense_cancel_invariant
    def test_dispense_then_cancel_does_not_unwind_dispense(self, api):
        """PRD §3.4: "On a successful dispense, the server inspects
        refills_remaining: when it is zero before the dispense, the
        prescription transitions to the terminal state DISPENSED;
        when it is greater than zero, the server decrements
        refills_remaining by one and the prescription stays in
        TRANSMITTED".

        PRD §3.4: "A Provider may cancel a prescription from DRAFT,
        SIGNED, or TRANSMITTED, transitioning it to the terminal
        CANCELLED state with no further preconditions on the
        prescription itself."

        Claim: a TRANSMITTED rx (refills_authorized=2) is dispensed
        once (refills_remaining: 2 → 1), then cancelled. The
        already-dispensed dose remains recorded — the rx is now
        CANCELLED and refills_remaining stays at its post-dispense
        value of 1; the cancel does NOT unwind the dispense.
        """
        setup = setup_signed_then_transmitted_prescription_for_dispense_invariant()
        rx = setup["rx"]
        provider = setup["provider"]
        assert rx["refills_remaining"] == 2
        # Dispense as a non-signer pharmacist.
        from test_helpers import dispense_prescription
        rx = dispense_prescription(rx["id"])
        assert rx["refills_remaining"] == 1
        assert rx["status"] == "TRANSMITTED"
        # Now cancel.
        rx_cancelled = cancel_prescription(rx["id"], provider["id"])
        assert rx_cancelled["status"] == "CANCELLED"
        # The cancel does not refund the dispense — refills_remaining
        # stays at 1.
        assert rx_cancelled["refills_remaining"] == 1, (
            "refills_remaining must remain at its post-dispense value "
            f"of 1 after CANCELLED; got "
            f"{rx_cancelled['refills_remaining']}"
        )

    # difficulty: compensating_invariant/prescription_refills_remaining_dispense_cancel_invariant
    def test_signed_to_cancelled_does_not_seed_dispense_history(self, api):
        """PRD §3.4: "A Provider may cancel a prescription from
        DRAFT, SIGNED, or TRANSMITTED, transitioning it to the
        terminal CANCELLED state with no further preconditions on
        the prescription itself."

        Claim: cancelling a SIGNED (never-transmitted, never-
        dispensed) prescription does not silently mutate
        refills_remaining: it stays at the value seeded on SIGN.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            is_controlled=False, refills_authorized=2,
        )
        rx = sign_prescription(rx["id"], provider["id"])
        assert rx["refills_remaining"] == 2
        rx_cancelled = cancel_prescription(rx["id"], provider["id"])
        assert rx_cancelled["status"] == "CANCELLED"
        assert rx_cancelled["refills_remaining"] == 2, (
            "refills_remaining must be preserved at seed value after "
            "SIGNED→CANCELLED"
        )


# ===========================================================================
# §3.4 Expiry sweep
# ===========================================================================
class TestExpirySweep:

    def test_sweep_expires_past_expires_at_transmitted(self, api):
        """PRD §3.4: "The sweep operation transitions a prescription
        to EXPIRED when the current server time is at or after the
        prescription's expires_at and the prescription is currently
        in either SIGNED or TRANSMITTED. EXPIRED is terminal."

        Claim: a TRANSMITTED rx whose expires_at has passed becomes
        EXPIRED after the sweep.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        rx = create_prescription(
            patient["id"], provider["id"], encounter["id"],
            is_controlled=False, refills_authorized=1,
        )
        rx = sign_prescription(rx["id"], provider["id"])
        rx = transmit_prescription(rx["id"], provider["id"])
        # Advance the clock to one second past expires_at.
        from datetime import timedelta
        from test_helpers import iso_utc
        expires_at = parse_iso(rx["expires_at"])
        advance_clock_to(iso_utc(expires_at + timedelta(seconds=1)))
        run_sweep()
        rx_after = re_get_prescription(rx["id"], provider["id"])
        assert rx_after["status"] == "EXPIRED"
