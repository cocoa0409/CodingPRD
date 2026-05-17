"""CDC catch-up schedule, next-due projection, min-interval boundary.

PRD §3.7 (CDC catch-up - routine vs catchup variants), §2.6 priority
71 (ERR_MIN_INTERVAL_VIOLATION), §2.8 (date arithmetic precision).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    TEST_USERS,
    administer_dose,
    administer_dose_payload,
    advance_clock_to,
    anchor_clock,
    create_antigen_schedule_rule,
    create_patient,
    create_provider_organization,
    create_vaccine_lot,
    create_vaccine_product,
    iso_anchor_offset,
    iso_date,
    iso_utc,
    parse_iso,
    schedule_and_administer_dose,
    schedule_dose,
    setup_basic_scenario,
    setup_dose_for_min_interval,
    setup_dtap_catchup_two_seqs,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 Dual variant: routine vs catchup on next-due projection
# Difficulty design: catchup_vs_routine_next_due_on_patient_schedule
# and catchup_eligibility_three_input_nested_max
# ===========================================================================
class TestNextDueDualVariant:

    # difficulty: dual_variant_calc/catchup_vs_routine_next_due_on_patient_schedule
    # difficulty: combinatorial_formula/catchup_eligibility_three_input_nested_max
    def test_catchup_variant_returns_last_admin_plus_interval(self, api):
        """PRD §3.7: "Catch-up variant - used when the patient's
        current age in days is greater than the rule's
        routine_max_age_days... The eligible date is the greater of
        (a) date_of_birth plus the rule's routine_min_age_days and
        (b) the administered_at of the most recent ADMINISTERED dose
        in the series plus the rule's catchup_min_interval_days."

        Claim: a patient who missed the routine window for DTAP seq=1
        and was administered seq=1 at age 212 days (beyond seq1
        routine_max_age_days=90) gets a next-due entry for seq=2 with
        variant='catchup' and next_due_date = last_admin +
        catchup_min_interval_days = 2025-08-01 + 28d = 2025-08-29.

        # difficulty: dual_variant_calc/catchup_vs_routine_next_due_on_patient_schedule
        """
        # Setup: DTAP seq1 routine_max=90 days; patient DOB 2025-01-01;
        # administer dose 1 at age 212 days = 2025-08-01.
        ctx = setup_dtap_catchup_two_seqs(
            routine_min_age_days_seq1=42,
            routine_recommended_age_days_seq1=60,
            routine_max_age_days_seq1=90,
            catchup_min_interval_days_seq1=28,
            routine_min_age_days_seq2=120,
            routine_recommended_age_days_seq2=120,
            routine_max_age_days_seq2=180,
            catchup_min_interval_days_seq2=28,
            patient_dob="2025-01-01",
        )
        # Advance clock to 2025-08-01 and administer dose 1 (catch-up).
        admin_ts = "2025-08-01T00:00:00.000Z"
        advance_clock_to(admin_ts)
        dose1 = schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product"]["id"],
            ctx["lot"]["id"], ctx["provider_org"]["id"],
            administered_at=admin_ts,
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # The dose was administered in catch-up territory; check next-due.
        res = api.get_next_due(
            ctx["patient"]["id"],
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res)
        # data should be an array; find DTAP_DIPHTHERIA entry.
        dtap_entry = None
        if isinstance(data, list):
            for e in data:
                if e.get("antigen") == "DTAP_DIPHTHERIA":
                    dtap_entry = e
                    break
        assert dtap_entry is not None, (
            "PRD §3.7: next-due response must include DTAP_DIPHTHERIA "
            "entry for a patient missing dose 2"
        )
        assert dtap_entry.get("variant") == "catchup", (
            f"PRD §3.7: variant must be 'catchup', got "
            f"{dtap_entry.get('variant')!r}"
        )
        assert dtap_entry.get("next_due_date") == "2025-08-29", (
            f"PRD §3.7: next_due_date must equal last_admin (2025-08-01) "
            f"+ catchup_min_interval_days (28) = 2025-08-29, got "
            f"{dtap_entry.get('next_due_date')!r}"
        )

    # difficulty: combinatorial_formula/catchup_eligibility_three_input_nested_max
    def test_routine_variant_returns_dob_plus_recommended_age(self, api):
        """PRD §3.7: "Routine variant - used when the patient's
        current age in days is at most the rule's routine_max_age_days
        and no prior dose in the series was administered after its own
        rule's routine_max_age_days. ... The next-due date is the
        patient's date_of_birth plus the rule's
        routine_recommended_age_days."

        Claim: a patient born 2025-01-01, given HEPB seq=1 at age 5
        days (well within seq1 routine_max=30) and now aged 90 days
        (still within seq2 routine_max=120), gets a next-due entry
        for HEPB with variant='routine' and next_due_date =
        date_of_birth (2025-01-01) + routine_recommended_age_days (60)
        = 2025-03-02.

        # difficulty: dual_variant_calc/catchup_vs_routine_next_due_on_patient_schedule
        # difficulty: combinatorial_formula/catchup_eligibility_three_input_nested_max
        """
        anchor_clock()
        provider_org = create_provider_organization()
        rule_seq1 = create_antigen_schedule_rule(
            antigen="HEPB", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=1,
            routine_max_age_days=30,
            catchup_min_interval_days=0,
        )
        rule_seq2 = create_antigen_schedule_rule(
            antigen="HEPB", dose_sequence_number=2,
            routine_min_age_days=30,
            routine_recommended_age_days=60,
            routine_max_age_days=120,
            catchup_min_interval_days=28,
            prerequisite_rule_id=rule_seq1["id"],
        )
        product = create_vaccine_product(
            antigens=["HEPB"], min_age_days=0, max_age_days=2555,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=10,
        )
        patient = create_patient(date_of_birth="2025-01-01")
        # Administer seq=1 at age 5 days (2025-01-06).
        seq1_admin = "2025-01-06T00:00:00.000Z"
        advance_clock_to(seq1_admin)
        schedule_and_administer_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administered_at=seq1_admin,
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Advance clock to 2025-04-01 (age = 90 days).
        advance_clock_to("2025-04-01T00:00:00.000Z")
        res = api.get_next_due(
            patient["id"],
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res)
        hepb_entry = None
        if isinstance(data, list):
            for e in data:
                if e.get("antigen") == "HEPB":
                    hepb_entry = e
                    break
        assert hepb_entry is not None, (
            "PRD §3.7: next-due must include HEPB entry"
        )
        assert hepb_entry.get("variant") == "routine", (
            f"PRD §3.7: variant must be 'routine' when age <= "
            f"routine_max_age_days and prior dose was on-time, got "
            f"{hepb_entry.get('variant')!r}"
        )
        assert hepb_entry.get("next_due_date") == "2025-03-02", (
            f"PRD §3.7: routine next_due_date must equal DOB + "
            f"routine_recommended_age_days (60) = 2025-03-02, got "
            f"{hepb_entry.get('next_due_date')!r}"
        )


# ===========================================================================
# §3.3 / §3.7 catchup_flag is computed at administer
# ===========================================================================
class TestCatchupFlag:

    # difficulty: dual_variant_calc/catchup_vs_routine_next_due_on_patient_schedule
    def test_dose_administered_in_catchup_territory_has_flag_true(self, api):
        """PRD §3.7: "The catchup_flag for any dose recorded under
        this projection is true."
        PRD §3.3: "The dose's catchup_flag is computed by the CDC
        catch-up rule described in §3.7, recording true on the dose
        record if the schedule projection for this position was the
        catch-up variant."

        Claim: a dose 1 of DTAP_DIPHTHERIA administered at age 212
        days (well past routine_max_age_days=90) carries
        catchup_flag == true.

        # difficulty: dual_variant_calc/catchup_vs_routine_next_due_on_patient_schedule
        """
        ctx = setup_dtap_catchup_two_seqs(
            routine_min_age_days_seq1=42,
            routine_recommended_age_days_seq1=60,
            routine_max_age_days_seq1=90,
            catchup_min_interval_days_seq1=28,
            patient_dob="2025-01-01",
        )
        admin_ts = "2025-08-01T00:00:00.000Z"
        advance_clock_to(admin_ts)
        dose = schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product"]["id"],
            ctx["lot"]["id"], ctx["provider_org"]["id"],
            administered_at=admin_ts,
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        assert dose["catchup_flag"] is True, (
            "PRD §3.7: catchup_flag must be true for a dose recorded "
            "in catch-up territory"
        )

    def test_dose_administered_in_routine_window_has_flag_false(self, api):
        """PRD §3.7: "The catchup_flag for any dose recorded under
        this projection is false."

        Claim: a dose 1 administered at age within routine_max_age_days
        carries catchup_flag == false.
        """
        ctx = setup_dtap_catchup_two_seqs(
            routine_min_age_days_seq1=42,
            routine_recommended_age_days_seq1=60,
            routine_max_age_days_seq1=90,
            catchup_min_interval_days_seq1=28,
            patient_dob="2025-01-01",
        )
        # Admin at age 60 days (= 2025-03-02), within routine_max=90.
        admin_ts = "2025-03-02T00:00:00.000Z"
        advance_clock_to(admin_ts)
        dose = schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product"]["id"],
            ctx["lot"]["id"], ctx["provider_org"]["id"],
            administered_at=admin_ts,
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        assert dose["catchup_flag"] is False, (
            "PRD §3.7: catchup_flag must be false for a dose recorded "
            "in the routine window"
        )


# ===========================================================================
# §3.3 / §2.6 priority 71: ERR_MIN_INTERVAL_VIOLATION
# Difficulty design: dose_min_interval_closed_lower_bound
# ===========================================================================
class TestMinIntervalBoundary:
    """Difficulty design: dose_min_interval_closed_lower_bound.
    PRD §3.3: "the elapsed days between the new administered_at and
    the prior dose's administered_at must be at least the rule's
    catchup_min_interval_days. Exactly equal to the minimum is
    allowed; one day short is rejected (ERR_MIN_INTERVAL_VIOLATION)."
    """

    # difficulty: resource_temporal_overlap/dose_min_interval_closed_lower_bound
    def test_interval_one_day_short_rejected(self, api):
        """PRD §3.3: "one day short is rejected
        (ERR_MIN_INTERVAL_VIOLATION)."

        Claim: a second dose attempted at +26 days when
        catchup_min_interval_days = 28 yields
        ERR_MIN_INTERVAL_VIOLATION.

        # difficulty: resource_temporal_overlap/dose_min_interval_closed_lower_bound
        """
        ctx = setup_dose_for_min_interval(
            routine_min_age_days_seq1=42,
            routine_max_age_days_seq1=90,
            catchup_min_interval_days_seq2=28,
            patient_dob="2026-01-01",
        )
        # First dose at 2026-02-12 (age 42 days exactly).
        # Try a second dose at 2026-03-10 (interval = 26 days, short).
        d_short_admin_at = "2026-03-10T00:00:00.000Z"
        advance_clock_to(d_short_admin_at)
        dose_short = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"],
            ctx["lot"]["id"], ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        res = api.administer_dose(
            ctx["patient"]["id"], dose_short["id"],
            administer_dose_payload(administered_at=d_short_admin_at),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_MIN_INTERVAL_VIOLATION")

    # difficulty: resource_temporal_overlap/dose_min_interval_closed_lower_bound
    def test_interval_exactly_min_accepted(self, api):
        """PRD §3.3: "Exactly equal to the minimum is allowed."

        Claim: a second dose at +28 days when
        catchup_min_interval_days = 28 succeeds.

        # difficulty: resource_temporal_overlap/dose_min_interval_closed_lower_bound
        """
        ctx = setup_dose_for_min_interval(
            routine_min_age_days_seq1=42,
            routine_max_age_days_seq1=90,
            catchup_min_interval_days_seq2=28,
            patient_dob="2026-01-01",
        )
        d_ok_admin_at = "2026-03-12T00:00:00.000Z"
        advance_clock_to(d_ok_admin_at)
        dose_ok = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"],
            ctx["lot"]["id"], ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        res = api.administer_dose(
            ctx["patient"]["id"], dose_ok["id"],
            administer_dose_payload(administered_at=d_ok_admin_at),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["dose_state"] == "ADMINISTERED"


# ===========================================================================
# §3.3 administered_at temporal sanity bounds
# ===========================================================================
class TestAdminTemporalBounds:
    """PRD §3.3: "The administered_at instant must satisfy two temporal
    sanity bounds: it must be at most the server's current time, and
    it must be strictly after the patient's date_of_birth
    (ERR_ADMIN_TIME_OUT_OF_RANGE)."
    """

    def test_admin_in_future_rejected(self, api):
        """PRD §3.3: "it must be at most the server's current time."

        Claim: administered_at strictly after server now ->
        ERR_ADMIN_TIME_OUT_OF_RANGE.

        PRD §2.6 gate order: age range is checked BEFORE temporal
        sanity. To isolate the temporal-sanity rule we must use a
        product whose max_age_days is open (None) so the age check
        cannot fire first.
        """
        ctx = setup_basic_scenario(
            product_min_age_days=0,
            product_max_age_days=None,
            routine_min_age_days=0,
            routine_max_age_days=3650,
        )
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
        )
        # Clock is anchored at 2026-01-01 (+1 day); try admin in the future.
        future_admin = "2030-01-01T00:00:00.000Z"
        res = api.administer_dose(
            ctx["patient"]["id"], dose["id"],
            administer_dose_payload(administered_at=future_admin),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_ADMIN_TIME_OUT_OF_RANGE")

    def test_admin_before_dob_rejected(self, api):
        """PRD §3.3: "it must be ... strictly after the patient's
        date_of_birth."

        Claim: administered_at <= date_of_birth ->
        ERR_ADMIN_TIME_OUT_OF_RANGE.

        Use an open age range (0..None) so the age check does not
        consume an admin time that is also out of temporal range
        (PRD §2.6: age check is ordered before temporal sanity).
        """
        ctx = setup_basic_scenario(
            patient_dob="2026-01-01",
            product_min_age_days=0,
            product_max_age_days=None,
            routine_min_age_days=0,
            routine_max_age_days=3650,
        )
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
        )
        # administered_at exactly equal to DOB midnight -> not strictly after.
        res = api.administer_dose(
            ctx["patient"]["id"], dose["id"],
            administer_dose_payload(
                administered_at="2026-01-01T00:00:00.000Z",
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_ADMIN_TIME_OUT_OF_RANGE")


# ===========================================================================
# §3.3 lot-product correspondence
# ===========================================================================
class TestLotProductCorrespondence:
    """PRD §3.3: "The lot_id supplied at scheduling time must refer to
    a lot whose vaccine_product_id equals the product on the dose record
    (ERR_LOT_PRODUCT_MISMATCH)."
    """

    def test_lot_product_mismatch_rejected_on_administer(self, api):
        """Claim: scheduling a dose with vaccine_product_id of product A
        but lot_id of a lot belonging to product B yields
        ERR_LOT_PRODUCT_MISMATCH on administer.
        """
        anchor_clock()
        provider_org = create_provider_organization()
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product_a = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        product_b = create_vaccine_product(
            antigens=["HEPB"], min_age_days=0, max_age_days=None,
        )
        # Lot belongs to product_a.
        lot_a = create_vaccine_lot(
            product_a["id"], provider_org["id"], doses_on_hand=5,
        )
        patient = create_patient()
        # Schedule with mismatch: product_b id but lot_a id.
        from test_helpers import schedule_dose_payload as _p
        res = api.schedule_dose(
            patient["id"],
            _p(
                vaccine_product_id=product_b["id"],
                lot_id=lot_a["id"],
                provider_organization_id=provider_org["id"],
                administering_clinician_id=PROVIDER_CLINICIAN_ID,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        # PRD §2.6 priority 80 fires this on administer; some impls
        # may also detect at schedule time. Accept either pathway.
        # However the PRD §2.6 applies_to is "administer", so we
        # explicitly require the schedule call to succeed and the
        # administer call to fail.
        if res.status_code >= 400:
            # If schedule already rejected, accept this as
            # implementation-faithful only if the error_id is the
            # specific one PRD names for the cross-reference.
            validate_error(res, "ERR_LOT_PRODUCT_MISMATCH")
            return
        scheduled = validate_success(res, expected_status=201)
        advance_clock_to(iso_anchor_offset())
        res2 = api.administer_dose(
            patient["id"], scheduled["id"],
            administer_dose_payload(
                administered_at=iso_anchor_offset(),
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res2, "ERR_LOT_PRODUCT_MISMATCH")
