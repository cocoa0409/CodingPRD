"""ExemptionApplication lifecycle + exemption_stack calculation
(PRD §3.3).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_MILL_RATE,
    HOMESTEAD_CAP_DOLLARS,
    HOMESTEAD_PCT,
    SENIOR_FLAT,
    VETERAN_FLAT,
    add_days_iso,
    advance_clock_to,
    approve_exemption,
    assert_exemption_application,
    create_assessment,
    create_owner,
    create_property,
    create_tax_bill,
    get_assessment,
    issue_assessment,
    make_owner_headers,
    senior_eligible_dob,
    setup_finalized_assessment_via_clock,
    setup_owner_and_property,
    submit_exemption,
    validate_error,
    validate_success,
    young_dob,
)


# ===========================================================================
# Submit + simple lifecycle — PRD §3.3
# ===========================================================================
class TestSubmitExemption:

    def test_owner_submits_exemption_returns_submitted_status(self, api):
        """PRD §3.3: "An Owner files an ExemptionApplication by
        supplying exemption_type and effective_roll_year; the server
        captures owner_id from X-User-ID and property_id from the
        path. The application begins in SUBMITTED status."

        Claim: POST /properties/{id}/exemption_applications returns
        201 with status=SUBMITTED.
        """
        from test_helpers import submit_exemption_payload
        owner, prop = setup_owner_and_property()
        resp = api.submit_exemption_application(
            prop["id"],
            submit_exemption_payload(
                exemption_type="HOMESTEAD", effective_roll_year=2025,
            ),
            make_owner_headers(owner["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_exemption_application(data)
        assert data["status"] == "SUBMITTED"
        assert data["exemption_type"] == "HOMESTEAD"


# ===========================================================================
# Eligibility — PRD §3.3
# ===========================================================================
class TestExemptionEligibility:

    def test_senior_requires_age_at_least_65(self, api):
        """PRD §3.3: 'SENIOR requires that the Owner's age, computed
        from date_of_birth, is at least 65 (the system constant
        SENIOR_AGE) measured on January 1 of effective_roll_year.'

        Claim: approving SENIOR for an owner born well past 65 years
        before Jan 1 of effective_roll_year is rejected with
        ERR_EXEMPTION_INELIGIBLE.
        """
        owner = create_owner(date_of_birth=young_dob(2025))
        prop = create_property(owner=owner)
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="SENIOR", effective_roll_year=2025,
        )
        from test_helpers import api_client, TEST_USERS
        resp = api_client.approve_exemption_application(
            prop["id"], ex["id"], TEST_USERS["assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_INELIGIBLE.value)

    def test_veteran_requires_veteran_status_true(self, api):
        """PRD §3.3: 'VETERAN requires Owner.veteran_status to be
        true.'

        Claim: approving VETERAN for an owner with veteran_status=False
        (default) is rejected with ERR_EXEMPTION_INELIGIBLE.
        """
        owner = create_owner(veteran_status=False)
        prop = create_property(owner=owner)
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="VETERAN", effective_roll_year=2025,
        )
        from test_helpers import api_client, TEST_USERS
        resp = api_client.approve_exemption_application(
            prop["id"], ex["id"], TEST_USERS["assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_INELIGIBLE.value)

    def test_disability_requires_rating_at_least_50(self, api):
        """PRD §3.3: 'DISABILITY requires Owner.disability_rating to
        be at least 50 percent (the system constant
        DISABILITY_MIN_PCT).'

        Claim: approving DISABILITY for an owner with
        disability_rating=40 is rejected with ERR_EXEMPTION_INELIGIBLE.
        """
        owner = create_owner(disability_rating=40)
        prop = create_property(owner=owner)
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="DISABILITY", effective_roll_year=2025,
        )
        from test_helpers import api_client, TEST_USERS
        resp = api_client.approve_exemption_application(
            prop["id"], ex["id"], TEST_USERS["assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_INELIGIBLE.value)

    def test_disability_boundary_50_accepted(self, api):
        """PRD §3.3: 'DISABILITY requires Owner.disability_rating to
        be at least 50 percent (the system constant
        DISABILITY_MIN_PCT).'

        Claim: disability_rating exactly 50 satisfies the threshold
        and approval succeeds.
        """
        owner = create_owner(disability_rating=50)
        prop = create_property(owner=owner)
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="DISABILITY", effective_roll_year=2025,
        )
        approved = approve_exemption(
            property_id=prop["id"], exemption_application_id=ex["id"],
            version=ex["version"],
        )
        assert approved["status"] == "APPROVED"


# ===========================================================================
# Duplicates — PRD §3.3
# ===========================================================================
class TestExemptionDuplicate:

    def test_second_approved_of_same_type_rejected(self, api):
        """PRD §3.3: 'At most one APPROVED application of the same
        exemption_type may exist for the same (property_id,
        effective_roll_year); a second is rejected with
        ERR_EXEMPTION_DUPLICATE.'

        Claim: a second APPROVED application of the same exemption
        type for the same (property_id, effective_roll_year) is
        rejected.
        """
        owner = create_owner(date_of_birth=senior_eligible_dob(2025))
        prop = create_property(owner=owner)
        ex1 = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="SENIOR", effective_roll_year=2025,
        )
        approve_exemption(
            property_id=prop["id"],
            exemption_application_id=ex1["id"], version=ex1["version"],
        )
        ex2 = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="SENIOR", effective_roll_year=2025,
        )
        from test_helpers import api_client, TEST_USERS
        resp = api_client.approve_exemption_application(
            prop["id"], ex2["id"], TEST_USERS["assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_DUPLICATE.value)


# ===========================================================================
# Exemption stack and tax bill computation — PRD §3.3, §3.4
# ===========================================================================
class TestExemptionStackComputation:

    def _build_property_with_all_four_exemptions(
        self, *, capped_value: float, disability_rating: int = 80,
    ):
        """Helper: build a property + APPROVED HOMESTEAD/SENIOR/VETERAN/
        DISABILITY for the same roll year."""
        roll_year = 2025
        owner = create_owner(
            date_of_birth=senior_eligible_dob(roll_year),
            veteran_status=True,
            disability_rating=disability_rating,
        )
        prop = create_property(owner=owner, market_value=capped_value)
        draft = create_assessment(
            property_id=prop["id"], roll_year=roll_year,
            market_value_at_roll=capped_value,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        for et in ["HOMESTEAD", "SENIOR", "VETERAN", "DISABILITY"]:
            ex = submit_exemption(
                owner=owner, property_id=prop["id"],
                exemption_type=et, effective_roll_year=roll_year,
            )
            approve_exemption(
                property_id=prop["id"],
                exemption_application_id=ex["id"], version=ex["version"],
            )
        # Auto-FINALIZE the Assessment via clock advance.
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(
            add_days_iso(asmt["appeal_window_closes_at"], 1),
        )
        return owner, prop, roll_year

    def test_homestead_capped_at_75000_then_senior_veteran_disability_full(
        self, api,
    ):
        """PRD §3.3:
        - 'HOMESTEAD: the smaller of 20 percent of the residual base
          (the system constant HOMESTEAD_PCT is 0.20) and the
          absolute dollar cap of 75,000 (the system constant
          HOMESTEAD_CAP_DOLLARS), rounded half up to two decimal
          places.'
        - 'SENIOR: a flat 25,000 (the system constant SENIOR_FLAT).'
        - 'VETERAN: a flat 15,000 (the system constant VETERAN_FLAT).'
        - 'DISABILITY: if Owner.disability_rating is at least 70, the
          full 30,000 (the system constant DISABILITY_FULL); otherwise
          half of DISABILITY_FULL, i.e. 15,000, rounded half up to
          two decimal places.'

        Claim: at capped_value=510000 (so 20% = 102000 > 75000 cap),
        the resulting bill carries total_exemption_amount =
        75000 + 25000 + 15000 + 30000 = 145000.00 and taxable_value =
        365000.00 and base_tax_amount = 4562.50.

        # difficulty: combinatorial_formula/exemption_stack_tiered_priority_mode_a
        """
        owner, prop, roll_year = (
            self._build_property_with_all_four_exemptions(
                capped_value=510_000.00, disability_rating=80,
            )
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=roll_year,
            mill_rate=12.5,
        )
        # HOMESTEAD = min(0.20 * 510000, 75000) = min(102000, 75000)
        # = 75000.
        # SENIOR = 25000; VETERAN = 15000; DISABILITY (rating 80) =
        # 30000.
        # Total = 145000.
        assert bill["total_exemption_amount"] == pytest.approx(
            145_000.00, abs=0.01,
        )
        # taxable_value = 510000 - 145000 = 365000.
        assert bill["taxable_value"] == pytest.approx(
            365_000.00, abs=0.01,
        )
        # base_tax_amount = 365000 * 12.5 / 1000 = 4562.50.
        assert bill["base_tax_amount"] == pytest.approx(
            4_562.50, abs=0.01,
        )

    def test_disability_half_when_rating_below_70(self, api):
        """PRD §3.3: 'DISABILITY: if Owner.disability_rating is at
        least 70, the full 30,000 (the system constant
        DISABILITY_FULL); otherwise half of DISABILITY_FULL, i.e.
        15,000, rounded half up to two decimal places.'

        Claim: with disability_rating=60 (>=50 eligible, <70), the
        DISABILITY layer is 15000.00.

        # difficulty: combinatorial_formula/tax_bill_rounding_order_mode_b
        """
        owner, prop, roll_year = (
            self._build_property_with_all_four_exemptions(
                capped_value=333_333.00, disability_rating=60,
            )
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=roll_year,
            mill_rate=12.5,
        )
        # HOMESTEAD = min(round_half_up(0.20 * 333333, 2), 75000) =
        # min(66666.60, 75000) = 66666.60.
        # SENIOR = 25000.00; VETERAN = 15000.00; DISABILITY (rating
        # 60) = 15000.00.
        # Per-layer sum (PRD §3.3: 'Rounding is applied per-layer'):
        # 66666.60 + 25000.00 + 15000.00 + 15000.00 = 121666.60.
        assert bill["total_exemption_amount"] == pytest.approx(
            121_666.60, abs=0.01,
        )
        # PRD §3.4: 'taxable_value as capped_value minus
        # total_exemption_amount, rounded half up to two decimal
        # places, then floored at zero':
        # 333333 - 121666.60 = 211666.40.
        assert bill["taxable_value"] == pytest.approx(
            211_666.40, abs=0.01,
        )
        # base_tax = 211666.40 * 12.5 / 1000 = 2645.83 (round_half_up).
        assert bill["base_tax_amount"] == pytest.approx(
            2_645.83, abs=0.01,
        )

    def test_homestead_only_caps_at_20pct_when_below_75k(self, api):
        """PRD §3.3: 'HOMESTEAD: the smaller of 20 percent of the
        residual base (the system constant HOMESTEAD_PCT is 0.20) and
        the absolute dollar cap of 75,000 (the system constant
        HOMESTEAD_CAP_DOLLARS), rounded half up to two decimal
        places.'

        Claim: at capped_value=100000, HOMESTEAD = 0.20*100000 = 20000
        (the percentage path, not the cap).
        """
        owner = create_owner()  # HOMESTEAD requires owner == property.owner_id
        prop = create_property(owner=owner, market_value=100_000.00)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=100_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="HOMESTEAD", effective_roll_year=2025,
        )
        approve_exemption(
            property_id=prop["id"],
            exemption_application_id=ex["id"], version=ex["version"],
        )
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(
            add_days_iso(asmt["appeal_window_closes_at"], 1),
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        # HOMESTEAD = min(0.20 * 100000, 75000) = 20000.
        assert bill["total_exemption_amount"] == pytest.approx(
            20_000.00, abs=0.01,
        )

    def test_exemption_stack_floors_residual_at_zero(self, api):
        """PRD §3.3: 'Each computed layer amount is then floored at
        the current residual base (so a layer can never reduce the
        residual below zero)'. PRD §3.4: 'Compute taxable_value as
        capped_value minus total_exemption_amount, rounded half up to
        two decimal places, then floored at zero — so the taxable
        value never goes negative even if the exemption stack
        exceeds the capped value.'

        Claim: at very low capped_value the exemption stack saturates
        at the base; total_exemption_amount == capped_value and
        taxable_value == 0.
        """
        owner = create_owner(
            date_of_birth=senior_eligible_dob(2025),
            veteran_status=True, disability_rating=80,
        )
        prop = create_property(owner=owner, market_value=10_000.00)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=10_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        for et in ["HOMESTEAD", "SENIOR", "VETERAN", "DISABILITY"]:
            ex = submit_exemption(
                owner=owner, property_id=prop["id"],
                exemption_type=et, effective_roll_year=2025,
            )
            approve_exemption(
                property_id=prop["id"],
                exemption_application_id=ex["id"], version=ex["version"],
            )
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(
            add_days_iso(asmt["appeal_window_closes_at"], 1),
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        # The total_exemption_amount cannot exceed capped_value
        # (PRD §3.3 per-layer flooring), and taxable_value floors at
        # zero (PRD §3.4).
        assert bill["taxable_value"] >= 0.0
        assert bill["taxable_value"] == pytest.approx(0.00, abs=0.01)
        assert bill["base_tax_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# Revocation cascade — PRD §3.3
# ===========================================================================
class TestExemptionRevoke:

    def test_revoke_recomputes_taxbill_and_repartials_when_underpaid(self, api):
        """PRD §3.3: 'On revocation, the approved_amount no longer
        counts toward the exemption stack, and any TaxBill for the
        affected roll year is recomputed; if the recompute makes the
        bill underpaid relative to total payments already applied, its
        status becomes PARTIALLY_PAID and amount_due grows accordingly.'

        Claim: revoking an APPROVED SENIOR exemption recomputes the
        TaxBill so the exemption no longer reduces base_tax_amount.

        # difficulty: compensating_invariant/exemption_approve_revoke_taxable_invariant
        """
        from test_helpers import (
            get_tax_bill,
            issue_tax_bill,
            post_payment,
            revoke_exemption,
        )
        owner = create_owner(
            date_of_birth=senior_eligible_dob(2025),
        )
        prop = create_property(owner=owner, market_value=400_000.00)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="SENIOR", effective_roll_year=2025,
        )
        approved = approve_exemption(
            property_id=prop["id"],
            exemption_application_id=ex["id"], version=ex["version"],
        )
        # Finalize and issue bill: base = (400000-25000)*12.5/1000 =
        # 4687.50.
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(
            add_days_iso(asmt["appeal_window_closes_at"], 1),
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        # Issue the bill so it leaves PENDING.
        issued = issue_tax_bill(
            property_id=prop["id"], tax_bill_id=bill["id"],
        )
        assert issued["base_tax_amount"] == pytest.approx(
            4_687.50, abs=0.01,
        )
        # Owner pays 1000 → PARTIALLY_PAID, amount_due = 3687.50.
        post_payment(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], amount=1000.00,
        )
        # Revoke SENIOR (WITHDRAWN).
        revoke_exemption(
            property_id=prop["id"],
            exemption_application_id=ex["id"],
            revoked_reason="WITHDRAWN",
            version=approved["version"],
        )
        # Bill recomputed: base = 400000*12.5/1000 = 5000.00;
        # total_payments_applied = 1000 → amount_due = 4000.00.
        re_bill = get_tax_bill(prop["id"], bill["id"])
        assert re_bill["base_tax_amount"] == pytest.approx(
            5_000.00, abs=0.01,
        )
        assert re_bill["total_exemption_amount"] == pytest.approx(
            0.00, abs=0.01,
        )
        # amount_due grew from 3687.50 to 4000.00 (PRD §3.3:
        # 'amount_due grows accordingly').
        assert re_bill["amount_due"] == pytest.approx(4_000.00, abs=0.01)
        # PRD §3.3: 'its status becomes PARTIALLY_PAID'.
        assert re_bill["status"] == "PARTIALLY_PAID"

    def test_revoke_requires_revoked_reason(self, api):
        """PRD §3.3: 'Revocation (APPROVED → REVOKED) requires
        revoked_reason to be one of OWNERSHIP_CHANGE, INELIGIBLE, or
        WITHDRAWN.'

        Claim: omitting revoked_reason on /revoke is rejected (the
        PRD requires the field).
        """
        owner = create_owner(date_of_birth=senior_eligible_dob(2025))
        prop = create_property(owner=owner)
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="SENIOR", effective_roll_year=2025,
        )
        approved = approve_exemption(
            property_id=prop["id"], exemption_application_id=ex["id"],
            version=ex["version"],
        )
        from test_helpers import api_client, TEST_USERS
        # POST with empty body — revoked_reason absent.
        resp = api_client.revoke_exemption_application(
            prop["id"], ex["id"], {}, TEST_USERS["assessor_headers"],
        )
        assert resp.status_code >= 400, (
            f"Revoke without revoked_reason must be rejected; got "
            f"status {resp.status_code}"
        )


# ===========================================================================
# Conservation invariant — PRD §3.4
# ===========================================================================
class TestApproveRevokeConservationInvariant:

    def test_taxable_plus_exemption_equals_capped_across_approve_revoke(
        self, api,
    ):
        """PRD §3.4: 'Compute taxable_value as capped_value minus
        total_exemption_amount, rounded half up to two decimal places,
        then floored at zero — so the taxable value never goes
        negative even if the exemption stack exceeds the capped value.'

        Claim: across SENIOR approve→revoke, the invariant
        taxable_value + total_exemption_amount == capped_value
        (rounded to 2dp, modulo floor-at-zero) holds at every
        observed state.

        # difficulty: compensating_invariant/exemption_approve_revoke_taxable_invariant
        """
        from test_helpers import (
            get_tax_bill,
            revoke_exemption,
        )
        owner = create_owner(date_of_birth=senior_eligible_dob(2025))
        prop = create_property(owner=owner, market_value=400_000.00)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=400_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        # Finalize.
        asmt = get_assessment(prop["id"], draft["id"])
        advance_clock_to(
            add_days_iso(asmt["appeal_window_closes_at"], 1),
        )
        # Baseline: no exemption, bill PENDING.
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        capped = 400_000.00
        # Step 1 — no exemptions: taxable + exemption == capped.
        assert bill["taxable_value"] + bill["total_exemption_amount"] == \
            pytest.approx(capped, abs=0.01)
        # Step 2 — approve SENIOR.
        ex = submit_exemption(
            owner=owner, property_id=prop["id"],
            exemption_type="SENIOR", effective_roll_year=2025,
        )
        approved = approve_exemption(
            property_id=prop["id"], exemption_application_id=ex["id"],
            version=ex["version"],
        )
        b2 = get_tax_bill(prop["id"], bill["id"])
        assert b2["total_exemption_amount"] == pytest.approx(
            25_000.00, abs=0.01,
        )
        assert b2["taxable_value"] + b2["total_exemption_amount"] == \
            pytest.approx(capped, abs=0.01)
        # Step 3 — revoke.
        revoke_exemption(
            property_id=prop["id"], exemption_application_id=ex["id"],
            revoked_reason="WITHDRAWN",
            version=approved["version"],
        )
        b3 = get_tax_bill(prop["id"], bill["id"])
        assert b3["total_exemption_amount"] == pytest.approx(
            0.00, abs=0.01,
        )
        assert b3["taxable_value"] + b3["total_exemption_amount"] == \
            pytest.approx(capped, abs=0.01)
