"""Referral creation, accept/reject, return-to-pcp cycle, complete,
expiry sweep.

PRD §3.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_referral,
    advance_clock_to,
    anchor_clock,
    bind_patient_to_pcp,
    create_both_role_provider,
    create_patient,
    create_pcp_provider,
    create_referral,
    create_referral_payload,
    create_specialist_provider,
    iso_anchor_offset,
    make_provider_headers,
    REFERRAL_EXPIRY_DAYS_ROUTINE,
    REFERRAL_EXPIRY_HOURS_URGENT,
    return_referral_to_pcp,
    run_sweep,
    setup_referral_for_cycle,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.5 ERR_REFERRER_NOT_PCP
# ===========================================================================
class TestReferrerNotPcp:

    def test_referrer_not_patients_pcp_rejected(self, api):
        """PRD §3.5: "The referring_provider_id must equal the
        patient's current pcp_provider_id at the moment of create.
        A mismatch is rejected with ERR_REFERRER_NOT_PCP."

        Claim: creating a referral where referring_provider_id is
        not the patient's PCP returns ERR_REFERRER_NOT_PCP.
        """
        anchor_clock()
        # Patient bound to PCP1.
        pcp1 = create_pcp_provider()
        pcp2 = create_pcp_provider()  # different, also a PCP
        specialist = create_specialist_provider()
        patient = create_patient()
        patient = bind_patient_to_pcp(patient["id"], pcp1["id"])
        # Build a COMPLETED encounter on PCP1 — PRD §3.5 requires
        # the referral's originating encounter to be COMPLETED.
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        from test_helpers import (
            schedule_encounter, checkin_encounter, advance_clock_to,
            add_cpt_line_item, complete_encounter,
            create_cpt_code_entry,
        )
        e = schedule_encounter(
            patient["id"], pcp1["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
            chief_complaint="Visit",
        )
        advance_clock_to(iso_anchor_offset(minutes=55))
        e = checkin_encounter(e["id"])
        cpt = create_cpt_code_entry(
            cpt_code="99205", list_price_cents=15000,
            allowed_price_cents=12000,
        )
        add_cpt_line_item(e["id"], cpt["cpt_code"], units=1)
        e = complete_encounter(e["id"], pcp1["id"])
        # Now create a referral with referring_provider_id=PCP2
        # (NOT the patient's PCP).
        res = api.create_referral(
            patient["id"],
            create_referral_payload(
                referring_provider_id=pcp2["id"],
                referred_to_provider_id=specialist["id"],
                encounter_id=e["id"],
                reason="Specialist eval",
            ),
            make_provider_headers(pcp2["id"]),
        )
        validate_error(res, "ERR_REFERRER_NOT_PCP")


# ===========================================================================
# §3.5 ERR_INVALID_SPECIALIST
# ===========================================================================
class TestInvalidSpecialist:

    def test_referred_to_equals_referring_rejected(self, api):
        """PRD §3.5: "The referred_to_provider_id must not equal the
        referring_provider_id, and the referred-to provider's
        role_type must be SPECIALIST_ONLY or BOTH. A violation on
        either condition yields ERR_INVALID_SPECIALIST."

        Claim: creating a referral where referred_to_provider_id ==
        referring_provider_id returns ERR_INVALID_SPECIALIST.
        """
        # The PCP is BOTH so the second condition would pass; first
        # condition (not-equal) is the one that fails.
        anchor_clock()
        pcp_both = create_both_role_provider()
        patient = create_patient()
        patient = bind_patient_to_pcp(patient["id"], pcp_both["id"])
        from test_helpers import (
            schedule_encounter, checkin_encounter, advance_clock_to,
            add_cpt_line_item, complete_encounter,
            create_cpt_code_entry,
        )
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        e = schedule_encounter(
            patient["id"], pcp_both["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
        )
        advance_clock_to(iso_anchor_offset(minutes=55))
        e = checkin_encounter(e["id"])
        cpt = create_cpt_code_entry(
            cpt_code="99203", list_price_cents=15000,
            allowed_price_cents=12000,
        )
        add_cpt_line_item(e["id"], cpt["cpt_code"], units=1)
        e = complete_encounter(e["id"], pcp_both["id"])
        # referred_to == referring → ERR_INVALID_SPECIALIST.
        res = api.create_referral(
            patient["id"],
            create_referral_payload(
                referring_provider_id=pcp_both["id"],
                referred_to_provider_id=pcp_both["id"],
                encounter_id=e["id"],
                reason="self",
            ),
            make_provider_headers(pcp_both["id"]),
        )
        validate_error(res, "ERR_INVALID_SPECIALIST")

    def test_referred_to_pcp_only_rejected(self, api):
        """PRD §3.5: "the referred-to provider's role_type must be
        SPECIALIST_ONLY or BOTH. A violation on either condition
        yields ERR_INVALID_SPECIALIST."

        Claim: creating a referral whose referred_to_provider has
        role_type=PCP_ONLY returns ERR_INVALID_SPECIALIST.
        """
        anchor_clock()
        pcp = create_pcp_provider()
        another_pcp_only = create_pcp_provider()  # role_type PCP_ONLY
        patient = create_patient()
        patient = bind_patient_to_pcp(patient["id"], pcp["id"])
        from test_helpers import (
            schedule_encounter, checkin_encounter, advance_clock_to,
            add_cpt_line_item, complete_encounter,
            create_cpt_code_entry,
        )
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        e = schedule_encounter(
            patient["id"], pcp["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
        )
        advance_clock_to(iso_anchor_offset(minutes=55))
        e = checkin_encounter(e["id"])
        cpt = create_cpt_code_entry(
            cpt_code="99204", list_price_cents=15000,
            allowed_price_cents=12000,
        )
        add_cpt_line_item(e["id"], cpt["cpt_code"], units=1)
        e = complete_encounter(e["id"], pcp["id"])
        res = api.create_referral(
            patient["id"],
            create_referral_payload(
                referring_provider_id=pcp["id"],
                referred_to_provider_id=another_pcp_only["id"],
                encounter_id=e["id"],
                reason="bad specialist",
            ),
            make_provider_headers(pcp["id"]),
        )
        validate_error(res, "ERR_INVALID_SPECIALIST")


# ===========================================================================
# §3.5 expires_at on referral create
# ===========================================================================
class TestReferralExpiresAt:

    def test_routine_referral_expires_30_days(self, api):
        """PRD §3.5: "The server computes expires_at at create: 72
        hours after created_at when priority is URGENT, and 30 days
        after created_at when priority is ROUTINE."

        Claim: a ROUTINE referral's expires_at is created_at + 30
        days.
        """
        setup = setup_referral_for_cycle()
        referral = setup["referral"]
        from test_helpers import parse_iso
        created = parse_iso(referral["created_at"])
        expires = parse_iso(referral["expires_at"])
        delta_days = (expires - created).total_seconds() / 86400.0
        assert delta_days == pytest.approx(
            REFERRAL_EXPIRY_DAYS_ROUTINE, abs=1e-3,
        ), (
            f"ROUTINE expires_at expected created_at+30d, got delta="
            f"{delta_days} days"
        )

    def test_urgent_referral_expires_72_hours(self, api):
        """PRD §3.5: "The server computes expires_at at create: 72
        hours after created_at when priority is URGENT, and 30 days
        after created_at when priority is ROUTINE."

        Claim: an URGENT referral's expires_at is created_at + 72
        hours.
        """
        # Build a setup analogous to setup_referral_for_cycle, but
        # with priority=URGENT.
        anchor_clock()
        pcp = create_pcp_provider()
        specialist = create_both_role_provider()
        patient = create_patient()
        patient = bind_patient_to_pcp(patient["id"], pcp["id"])
        from test_helpers import (
            schedule_encounter, checkin_encounter, advance_clock_to,
            add_cpt_line_item, complete_encounter,
            create_cpt_code_entry,
        )
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        e = schedule_encounter(
            patient["id"], pcp["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
        )
        advance_clock_to(iso_anchor_offset(minutes=55))
        e = checkin_encounter(e["id"])
        cpt = create_cpt_code_entry(
            cpt_code="99201", list_price_cents=10000,
            allowed_price_cents=8000,
        )
        add_cpt_line_item(e["id"], cpt["cpt_code"], units=1)
        e = complete_encounter(e["id"], pcp["id"])
        referral = create_referral(
            patient["id"],
            referring_provider_id=pcp["id"],
            referred_to_provider_id=specialist["id"],
            encounter_id=e["id"],
            reason="urgent",
            priority="URGENT",
        )
        from test_helpers import parse_iso
        created = parse_iso(referral["created_at"])
        expires = parse_iso(referral["expires_at"])
        delta_hours = (expires - created).total_seconds() / 3600.0
        assert delta_hours == pytest.approx(
            REFERRAL_EXPIRY_HOURS_URGENT, abs=1e-3,
        ), (
            f"URGENT expires_at expected created_at+72h, got delta="
            f"{delta_hours} hours"
        )


# ===========================================================================
# §3.5 ACCEPTED → PENDING cycle (cyclic state machine)
# ===========================================================================
class TestReferralCycle:

    # difficulty: non_linear_state_machine/referral_cyclic_accepted_to_pending
    def test_accept_then_return_to_pcp_back_to_pending(self, api):
        """PRD §3.5: "Returning to the PCP is a cyclic transition
        that moves the referral from ACCEPTED back to PENDING
        without changing expires_at, used when the specialist needs
        more input from the PCP before conducting their visit."

        Claim: accept → return-to-pcp cycles the referral from
        ACCEPTED back to PENDING with expires_at unchanged.
        """
        setup = setup_referral_for_cycle()
        specialist = setup["specialist"]
        referral = setup["referral"]
        original_expires_at = referral["expires_at"]
        # Accept.
        r2 = accept_referral(referral["id"], specialist["id"])
        assert r2["status"] == "ACCEPTED"
        # Return-to-pcp.
        r3 = return_referral_to_pcp(referral["id"], specialist["id"])
        assert r3["status"] == "PENDING"
        assert r3["expires_at"] == original_expires_at, (
            f"expires_at must be unchanged on return-to-pcp; "
            f"before={original_expires_at} after={r3['expires_at']}"
        )

    # difficulty: non_linear_state_machine/referral_cyclic_accepted_to_pending
    def test_accept_after_return_increments_version(self, api):
        """PRD §3.5: "Returning to the PCP is a cyclic transition
        that moves the referral from ACCEPTED back to PENDING
        without changing expires_at".

        PRD §2.4: "version (integer) — increments by exactly one on
        every successful mutation".

        Claim: a full accept → return → accept cycle leaves the
        referral in ACCEPTED with version >= the pre-accept version
        + 3 (one increment per mutation; PRD pins exactly-one-per-
        mutation).
        """
        setup = setup_referral_for_cycle()
        specialist = setup["specialist"]
        referral = setup["referral"]
        v0 = referral["version"]
        r2 = accept_referral(referral["id"], specialist["id"])
        assert r2["version"] == v0 + 1
        r3 = return_referral_to_pcp(referral["id"], specialist["id"])
        assert r3["version"] == v0 + 2
        r4 = accept_referral(referral["id"], specialist["id"])
        assert r4["status"] == "ACCEPTED"
        assert r4["version"] == v0 + 3


# ===========================================================================
# §3.5 PENDING → REJECTED / accept-after-rejection forbidden
# ===========================================================================
class TestReferralRejection:

    def test_reject_pending_referral_succeeds(self, api):
        """PRD §3.5: "Rejection moves the referral from PENDING to
        the terminal REJECTED state."

        Claim: reject from PENDING transitions to REJECTED.
        """
        setup = setup_referral_for_cycle()
        specialist = setup["specialist"]
        referral = setup["referral"]
        res = api.reject_referral(
            referral["id"], make_provider_headers(specialist["id"]),
        )
        r = validate_success(res)
        assert r["status"] == "REJECTED"

    def test_accept_rejected_returns_not_pending(self, api):
        """PRD §3.5: "The same error fires whenever an accept or
        reject is attempted against a referral that is no longer in
        PENDING."

        Claim: accept attempted on a REJECTED referral returns
        ERR_REFERRAL_NOT_PENDING.
        """
        setup = setup_referral_for_cycle()
        specialist = setup["specialist"]
        referral = setup["referral"]
        # First reject.
        api.reject_referral(
            referral["id"], make_provider_headers(specialist["id"]),
        )
        # Then try to accept.
        res = api.accept_referral(
            referral["id"], make_provider_headers(specialist["id"]),
        )
        validate_error(res, "ERR_REFERRAL_NOT_PENDING")


# ===========================================================================
# §3.5 PENDING expiry sweep
# ===========================================================================
class TestReferralExpirySweep:

    def test_sweep_expires_past_pending_referrals(self, api):
        """PRD §3.5: "The sweep operation transitions any PENDING
        referral whose current server time is at or after its
        expires_at into the terminal EXPIRED state."

        Claim: a PENDING ROUTINE referral whose 30-day expiry has
        passed becomes EXPIRED after the sweep.
        """
        setup = setup_referral_for_cycle()
        referral = setup["referral"]
        # Advance clock past expires_at + 1s.
        from datetime import timedelta
        from test_helpers import parse_iso, iso_utc
        expires_at = parse_iso(referral["expires_at"])
        advance_clock_to(iso_utc(expires_at + timedelta(seconds=1)))
        run_sweep()
        # GET as ClinicAdmin (allowed by PRD §4).
        get_res = api.get_referral(
            referral["id"], TEST_USERS["clinic_admin_headers"],
        )
        r = validate_success(get_res)
        assert r["status"] == "EXPIRED"
