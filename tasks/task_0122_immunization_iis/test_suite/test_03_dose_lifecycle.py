"""Dose lifecycle: schedule, administer, cancel, invalidate, and
the layered validation gate.

PRD §3.3 (dose lifecycle), §2.6 (validation priority cascade).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    TEST_USERS,
    administer_dose_payload,
    advance_clock_to,
    anchor_clock,
    assert_administered_dose,
    create_allergy,
    create_patient,
    iso_anchor_offset,
    iso_utc,
    parse_iso,
    re_get_dose,
    re_get_lot,
    schedule_dose,
    setup_administered_dose,
    setup_basic_scenario,
    setup_dose_for_age_boundary,
    setup_priority_pair_safety_vs_constraint,
    setup_priority_pair_state_vs_safety,
    setup_scheduled_dose,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 Schedule -> SCHEDULED
# ===========================================================================
class TestScheduleDose:
    """PRD §3.3 schedule semantics."""

    def test_schedule_creates_scheduled_dose_with_reported_at(self, api):
        """PRD §3.3: "This persists an AdministeredDose with dose_state
        set to SCHEDULED, mirrors patient_id from the URL, and stamps
        the moment the record was first POSTed as reported_at."

        Claim: a scheduled dose carries dose_state == 'SCHEDULED' and
        a non-null reported_at timestamp.
        """
        ctx = setup_basic_scenario()
        from test_helpers import schedule_dose_payload as _p
        res = api.schedule_dose(
            ctx["patient"]["id"],
            _p(
                vaccine_product_id=ctx["product"]["id"],
                lot_id=ctx["lot"]["id"],
                provider_organization_id=ctx["provider_org"]["id"],
                administering_clinician_id=PROVIDER_CLINICIAN_ID,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["dose_state"] == "SCHEDULED"
        assert data["patient_id"] == ctx["patient"]["id"]
        assert data.get("reported_at"), (
            "PRD §3.3: reported_at must be stamped at schedule time"
        )
        assert_administered_dose(data)

    def test_schedule_dose_under_suspended_provider_rejected(self, api):
        """PRD §3.3: "If the recording ProviderOrganization is in
        SUSPENDED status, the schedule request is rejected with
        ERR_PROVIDER_SUSPENDED."

        Claim: scheduling under SUSPENDED ProviderOrganization yields
        ERR_PROVIDER_SUSPENDED.
        """
        ctx = setup_basic_scenario()
        # Suspend the provider manually.
        api.suspend_provider_organization(
            ctx["provider_org"]["id"],
            TEST_USERS["public_health_officer_headers"],
        )
        from test_helpers import schedule_dose_payload as _p
        res = api.schedule_dose(
            ctx["patient"]["id"],
            _p(
                vaccine_product_id=ctx["product"]["id"],
                lot_id=ctx["lot"]["id"],
                provider_organization_id=ctx["provider_org"]["id"],
                administering_clinician_id=PROVIDER_CLINICIAN_ID,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_PROVIDER_SUSPENDED")


# ===========================================================================
# §3.3 Administer -> ADMINISTERED + side effects
# ===========================================================================
class TestAdministerDose:
    """PRD §3.3 administer transitions + side effects."""

    def test_administer_decrements_doses_on_hand(self, api):
        """PRD §3.3: "The lot's doses_on_hand is decremented by one."

        Claim: a successful administer decrements VaccineLot.doses_on_hand
        by exactly one.
        """
        ctx = setup_scheduled_dose(doses_on_hand=5)
        lot_before = re_get_lot(ctx["lot"]["id"])
        assert lot_before["doses_on_hand"] == 5
        from test_helpers import administer_dose
        administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            iso_anchor_offset(),
        )
        lot_after = re_get_lot(ctx["lot"]["id"])
        assert lot_after["doses_on_hand"] == 4, (
            f"PRD §3.3: doses_on_hand must decrement by 1 "
            f"(before=5, after={lot_after['doses_on_hand']})"
        )

    def test_administer_to_zero_auto_exhausts_lot(self, api):
        """PRD §3.3: "if the resulting value is zero the lot's status
        auto-transitions to EXHAUSTED."

        Claim: when administer drops doses_on_hand to 0,
        VaccineLot.status auto-transitions to 'EXHAUSTED'.
        """
        ctx = setup_scheduled_dose(doses_on_hand=1)
        from test_helpers import administer_dose
        administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            iso_anchor_offset(),
        )
        lot_after = re_get_lot(ctx["lot"]["id"])
        assert lot_after["doses_on_hand"] == 0
        assert lot_after["status"] == "EXHAUSTED", (
            f"PRD §3.3: lot must auto-transition to EXHAUSTED, "
            f"got {lot_after['status']!r}"
        )

    def test_administer_advances_state_to_administered(self, api):
        """PRD §3.3: "A scheduled dose may then be advanced to
        ADMINISTERED by a ProviderClinician."

        Claim: dose_state advances SCHEDULED -> ADMINISTERED.
        """
        ctx = setup_scheduled_dose()
        from test_helpers import administer_dose
        data = administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            iso_anchor_offset(),
        )
        assert data["dose_state"] == "ADMINISTERED"
        assert data.get("administered_at"), (
            "administered_at must be recorded on the dose"
        )

    def test_administer_does_not_overwrite_reported_at(self, api):
        """PRD §3.3: "that timestamp is later consumed by the
        compliance score and is not overwritten when the dose is
        subsequently administered."

        Claim: reported_at value present after schedule is preserved
        unchanged after administer.
        """
        ctx = setup_scheduled_dose()
        reported_at_before = ctx["dose"]["reported_at"]
        from test_helpers import administer_dose
        # Advance the clock between schedule and administer so a buggy
        # implementation that rewrote reported_at would visibly drift.
        from test_helpers import advance_clock_to as _adv
        later = iso_utc(parse_iso(reported_at_before) + timedelta(hours=2))
        _adv(later)
        data = administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"], later,
        )
        assert data["reported_at"] == reported_at_before, (
            f"PRD §3.3: reported_at must NOT be overwritten on administer "
            f"(before={reported_at_before!r}, after={data['reported_at']!r})"
        )


# ===========================================================================
# §3.3 / §2.6 Priority: state -> safety -> business_constraint
# Difficulty design: state_vs_business_safety_on_administer
# and business_safety_vs_business_constraint_on_administer
# ===========================================================================
class TestAdministerPriorityCascade:
    """PRD §2.6: layered gate order."""

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_administer
    def test_state_check_wins_over_allergy_check_on_recalled_lot(self, api):
        """PRD §2.6: "State checks ... are evaluated before
        business-safety rules so that a structurally impossible request
        fails fast."
        PRD §3.3: "The lot must be selectable for new administration -
        its status must equal AVAILABLE (a RECALLED lot yields
        ERR_LOT_RECALLED)."

        Claim: when BOTH lot is RECALLED AND patient has anaphylactic
        contraindication, ERR_LOT_RECALLED wins (state precedes
        business_safety).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_administer
        """
        ctx = setup_priority_pair_state_vs_safety()
        res = api.administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            administer_dose_payload(
                administered_at=ctx["administered_at"],
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_LOT_RECALLED")

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_administer
    # difficulty: cross_entity_state_dependency/dose_admin_depends_on_lot_status
    def test_recalled_lot_alone_returns_lot_recalled(self, api):
        """PRD §3.3: "a RECALLED lot yields ERR_LOT_RECALLED."

        Claim: a SCHEDULED dose on a RECALLED lot (without any allergy
        complication) yields ERR_LOT_RECALLED on /administer.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_administer
        # difficulty: cross_entity_state_dependency/dose_admin_depends_on_lot_status
        """
        ctx = setup_basic_scenario()
        dose = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
        )
        # Recall lot so it becomes RECALLED. (NOT EXPIRED, so dose
        # would be invalidated by cascade -- so we recall AFTER
        # scheduling and check that administering the still-SCHEDULED
        # dose now hits ERR_LOT_RECALLED. The recall cascade only
        # invalidates ADMINISTERED doses.)
        from test_helpers import recall_lot
        recall_lot(ctx["lot"]["id"], reason="MANUFACTURER_DEFECT")
        res = api.administer_dose(
            ctx["patient"]["id"], dose["id"],
            administer_dose_payload(
                administered_at=iso_anchor_offset(),
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_LOT_RECALLED")

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_administer
    def test_allergy_check_wins_over_age_check(self, api):
        """PRD §2.6: "Safety supersedes other business rules. For
        dose administration, the allergy contraindication check
        (ERR_ALLERGY_CONTRAINDICATION) is checked before age range,
        before catch-up interval, and before temporal sanity."

        Claim: when BOTH anaphylactic contraindication AND age below
        product.min_age_days apply, ERR_ALLERGY_CONTRAINDICATION wins.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_administer
        """
        ctx = setup_priority_pair_safety_vs_constraint()
        res = api.administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            administer_dose_payload(
                administered_at=ctx["administered_at"],
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_ALLERGY_CONTRAINDICATION")

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_administer
    def test_allergy_alone_returns_contraindication(self, api):
        """PRD §3.3: "The patient must have no AllergyRecord whose
        allergen_code appears in the product's contraindication_flags
        and whose severity is either SEVERE or ANAPHYLAXIS
        (ERR_ALLERGY_CONTRAINDICATION)."

        Claim: an anaphylactic egg-allergic patient receiving an
        EGG-flagged product (with otherwise valid age, lot, etc.)
        yields ERR_ALLERGY_CONTRAINDICATION.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_administer
        """
        ctx = setup_scheduled_dose(contraindication_flags=["EGG"])
        create_allergy(
            ctx["patient"]["id"], allergen_code="EGG",
            severity="ANAPHYLAXIS",
        )
        res = api.administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            administer_dose_payload(
                administered_at=iso_anchor_offset(),
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_ALLERGY_CONTRAINDICATION")


# ===========================================================================
# §3.3 Allergy severity gates - MILD/MODERATE do not block
# ===========================================================================
class TestAllergySeverityBoundary:

    @pytest.mark.parametrize("severity", ["MILD", "MODERATE"])
    def test_low_severity_does_not_block(self, api, severity):
        """PRD §3.4: "Lower severities do not block."
        PRD §3.3: "whose severity is either SEVERE or ANAPHYLAXIS
        (ERR_ALLERGY_CONTRAINDICATION). This safety gate sits above
        age, interval, and temporal checks..."

        Claim: an EGG allergy at MILD or MODERATE does NOT block
        administration of an EGG-flagged product.
        """
        ctx = setup_scheduled_dose(contraindication_flags=["EGG"])
        create_allergy(
            ctx["patient"]["id"], allergen_code="EGG", severity=severity,
        )
        from test_helpers import administer_dose
        data = administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            iso_anchor_offset(),
        )
        assert data["dose_state"] == "ADMINISTERED"

    @pytest.mark.parametrize("severity", ["SEVERE", "ANAPHYLAXIS"])
    def test_high_severity_blocks(self, api, severity):
        """PRD §3.3: "whose severity is either SEVERE or ANAPHYLAXIS
        (ERR_ALLERGY_CONTRAINDICATION)."

        Claim: SEVERE or ANAPHYLAXIS allergy DOES block admin.
        """
        ctx = setup_scheduled_dose(contraindication_flags=["EGG"])
        create_allergy(
            ctx["patient"]["id"], allergen_code="EGG", severity=severity,
        )
        res = api.administer_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            administer_dose_payload(
                administered_at=iso_anchor_offset(),
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_ALLERGY_CONTRAINDICATION")


# ===========================================================================
# §3.3 Age boundary precision (difficulty design instance)
# ===========================================================================
class TestAgeBoundary:
    """Difficulty design: age_min_inclusive_boundary_on_administer.
    PRD §3.3: "The patient's age in days at administered_at must lie
    within [min_age_days, max_age_days] inclusive ... exactly equal to
    min_age_days is allowed, one day short is rejected
    (ERR_AGE_OUT_OF_RANGE)."
    """

    # difficulty: boundary_precision_check/age_min_inclusive_boundary_on_administer
    def test_exactly_min_age_days_admin_accepted(self, api):
        """PRD §3.3: "exactly equal to min_age_days is allowed."

        Claim: patient aged exactly product.min_age_days days at
        administered_at -> /administer succeeds (200).

        # difficulty: boundary_precision_check/age_min_inclusive_boundary_on_administer
        """
        # P_old born 2026-01-01, product min_age=42 days, admin at
        # 2026-02-12 = 42 days exactly.
        ctx = setup_dose_for_age_boundary(
            product_min_age_days=42,
            patient_dob_old="2026-01-01",
            patient_dob_young="2026-01-02",
        )
        advance_clock_to("2026-02-12T00:00:00.000Z")
        res = api.administer_dose(
            ctx["patient_old"]["id"], ctx["dose_old"]["id"],
            administer_dose_payload(
                administered_at="2026-02-12T00:00:00.000Z",
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["dose_state"] == "ADMINISTERED"

    # difficulty: boundary_precision_check/age_min_inclusive_boundary_on_administer
    def test_min_age_minus_one_day_admin_rejected(self, api):
        """PRD §3.3: "one day short is rejected (ERR_AGE_OUT_OF_RANGE)."

        Claim: patient aged product.min_age_days - 1 at
        administered_at -> ERR_AGE_OUT_OF_RANGE.

        # difficulty: boundary_precision_check/age_min_inclusive_boundary_on_administer
        """
        ctx = setup_dose_for_age_boundary(
            product_min_age_days=42,
            patient_dob_old="2026-01-01",
            patient_dob_young="2026-01-02",
        )
        advance_clock_to("2026-02-12T00:00:00.000Z")
        res = api.administer_dose(
            ctx["patient_young"]["id"], ctx["dose_young"]["id"],
            administer_dose_payload(
                administered_at="2026-02-12T00:00:00.000Z",
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_AGE_OUT_OF_RANGE")


# ===========================================================================
# §3.3 Cancel
# ===========================================================================
class TestCancelDose:

    def test_cancel_scheduled_dose_advances_state(self, api):
        """PRD §3.3: "A scheduled dose can also be cancelled by the
        same ProviderClinician role, advancing dose_state from
        SCHEDULED to CANCELLED."

        Claim: /cancel on SCHEDULED dose -> dose_state == 'CANCELLED'.
        """
        ctx = setup_scheduled_dose()
        res = api.cancel_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res)
        assert data["dose_state"] == "CANCELLED"

    def test_cancel_administered_dose_rejected(self, api):
        """PRD §3.3: "Cancellation requires only that the dose is in
        SCHEDULED state."
        PRD §2.6 / §5: state-mismatch -> ERR_INVALID_STATE.

        Claim: cancelling an already-ADMINISTERED dose -> ERR_INVALID_STATE.
        """
        ctx = setup_administered_dose()
        res = api.cancel_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.3 Data-error invalidate
# ===========================================================================
class TestInvalidateDose:

    def test_invalidate_administered_dose_advances_state(self, api):
        """PRD §3.3: "An already-administered dose can be invalidated
        due to data error by a PublicHealthOfficer, supplying the
        reason DATA_ERROR. The dose's dose_state advances ADMINISTERED
        -> INVALIDATED."

        Claim: /invalidate with reason=DATA_ERROR yields dose_state ==
        'INVALIDATED' and invalidation_reason == 'DATA_ERROR'.
        """
        ctx = setup_administered_dose()
        from test_helpers import invalidate_dose as _inv
        data = _inv(ctx["patient"]["id"], ctx["dose"]["id"], "DATA_ERROR")
        assert data["dose_state"] == "INVALIDATED"
        assert data["invalidation_reason"] == "DATA_ERROR"

    def test_invalidate_scheduled_dose_rejected(self, api):
        """PRD §2.6 / §5: state mismatch -> ERR_INVALID_STATE.

        Claim: invalidating a SCHEDULED dose -> ERR_INVALID_STATE.
        """
        ctx = setup_scheduled_dose()
        res = api.invalidate_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
            {"reason": "DATA_ERROR"},
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    # difficulty: compensating_invariant/dose_inventory_conservation_under_data_error_invalidation
    def test_invalidate_restores_doses_on_hand(self, api):
        """PRD §3.3: "the lot's doses_on_hand is incremented by one
        (data-error invalidations always restore stock)."

        Claim: after data-error invalidate, the lot's doses_on_hand
        is one higher than just before the invalidation.

        # difficulty: compensating_invariant/dose_inventory_conservation_under_data_error_invalidation
        """
        ctx = setup_administered_dose(doses_on_hand=3)
        lot_after_admin = re_get_lot(ctx["lot"]["id"])
        assert lot_after_admin["doses_on_hand"] == 2
        from test_helpers import invalidate_dose as _inv
        _inv(ctx["patient"]["id"], ctx["dose"]["id"], "DATA_ERROR")
        lot_after_inv = re_get_lot(ctx["lot"]["id"])
        assert lot_after_inv["doses_on_hand"] == 3, (
            "PRD §3.3: data-error invalidate must restore doses_on_hand"
        )
