"""Plan / Drug / FormularyEntry / Member CRUD, invariants, and
generic field validations.

PRD §3.1 (Plan, Drug, FormularyEntry), §3.2 (Member), §2.8 rungs
15-16 (ERR_OOP_BELOW_DEDUCTIBLE, ERR_VALIDATION), §2.4 common fields.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_drug,
    assert_formulary_entry,
    assert_member,
    assert_plan,
    assert_version_incremented_by_one,
    create_drug,
    create_drug_payload,
    create_formulary_entry,
    create_formulary_entry_payload,
    create_member,
    create_member_payload,
    create_plan,
    create_plan_payload,
    patch_plan_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Plan
# ===========================================================================
class TestPlanCRUD:
    """PRD §3.1 Plan."""

    def test_create_plan_returns_resource(self, api, admin_headers):
        """PRD §3.1: "The plan carries a human-readable name together
        with the four economic parameters that drive every downstream
        calculation: an annual deductible_cents, an annual
        oop_max_cents (the member's out-of-pocket maximum), a member
        coinsurance_rate applied to non-deductible spend on higher-
        tier drugs, and a mail_order_discount_rate applied to the
        allowed charge whenever a claim is filed through the 90-day
        mail-order channel."

        Claim: create returns Plan with all four fields.
        """
        payload = create_plan_payload(
            name="Premium 5000",
            deductible_cents=50_000,
            oop_max_cents=200_000,
            coinsurance_rate=0.20,
            mail_order_discount_rate=0.85,
        )
        plan = validate_success(
            api.create_plan(payload, admin_headers), 201,
        )
        assert_plan(plan)
        assert plan["name"] == "Premium 5000"
        assert plan["deductible_cents"] == 50_000
        assert plan["oop_max_cents"] == 200_000
        assert plan["coinsurance_rate"] == pytest.approx(0.20)
        assert plan["mail_order_discount_rate"] == pytest.approx(0.85)

    def test_create_plan_defaults_mail_order_discount_rate(
        self, api, admin_headers,
    ):
        """PRD §3.1: "the mail_order_discount_rate defaults to 0.90
        when omitted from the creation payload."

        Claim: omitting mail_order_discount_rate yields 0.90.
        """
        payload = create_plan_payload(
            name="DefaultMOR", deductible_cents=10_000,
            oop_max_cents=20_000, coinsurance_rate=0.10,
            mail_order_discount_rate=None,
        )
        plan = validate_success(
            api.create_plan(payload, admin_headers), 201,
        )
        assert plan["mail_order_discount_rate"] == pytest.approx(0.90)

    def test_create_plan_oop_below_deductible_rejected(
        self, api, admin_headers,
    ):
        """PRD §3.1: "the out-of-pocket maximum must be at least as
        large as the deductible; an attempt to create or update a plan
        that violates this relationship is rejected with
        ERR_OOP_BELOW_DEDUCTIBLE."

        Claim: oop_max < deductible -> ERR_OOP_BELOW_DEDUCTIBLE (422).
        """
        payload = create_plan_payload(
            deductible_cents=100_000, oop_max_cents=50_000,
            coinsurance_rate=0.20,
        )
        res = api.create_plan(payload, admin_headers)
        validate_error(res, "ERR_OOP_BELOW_DEDUCTIBLE")

    def test_create_plan_oop_equal_deductible_accepted(
        self, api, admin_headers,
    ):
        """PRD §3.1: "the out-of-pocket maximum must be at least as
        large as the deductible".

        Claim: oop_max == deductible is accepted (>= boundary).
        """
        payload = create_plan_payload(
            deductible_cents=50_000, oop_max_cents=50_000,
            coinsurance_rate=0.20,
        )
        plan = validate_success(
            api.create_plan(payload, admin_headers), 201,
        )
        assert plan["deductible_cents"] == 50_000
        assert plan["oop_max_cents"] == 50_000

    @pytest.mark.parametrize("rate", [-0.01, 1.01, 2.0])
    def test_create_plan_coinsurance_out_of_band_rejected(
        self, api, admin_headers, rate,
    ):
        """PRD §2.8 rung 16: "on plan create, plan update, formulary-
        entry create, and formulary-entry update, the tier must lie
        in the 1-to-5 band and rate fields must lie in the 0-to-1
        band; otherwise ERR_VALIDATION (422)."

        Claim: coinsurance_rate outside [0,1] -> ERR_VALIDATION.
        """
        payload = create_plan_payload(coinsurance_rate=rate)
        res = api.create_plan(payload, admin_headers)
        validate_error(res, "ERR_VALIDATION")

    @pytest.mark.parametrize("rate", [-0.01, 0.0, 1.01])
    def test_create_plan_mail_order_rate_out_of_band_rejected(
        self, api, admin_headers, rate,
    ):
        """PRD §3.1: "mail_order_discount_rate strictly above 0 and
        at most 1."
        PRD §2.8 rung 16: "rate fields must lie in the 0-to-1 band;
        otherwise ERR_VALIDATION (422)."

        Claim: mail_order_discount_rate outside (0,1] -> ERR_VALIDATION.
        """
        payload = create_plan_payload(mail_order_discount_rate=rate)
        res = api.create_plan(payload, admin_headers)
        validate_error(res, "ERR_VALIDATION")

    def test_patch_plan_updates_and_increments_version(
        self, api, admin_headers,
    ):
        """PRD §2.4: "version — a non-negative integer that begins at
        the value chosen by the server on creation and increments by
        one on every mutation that changes any other field of the
        resource."
        PRD §4: PATCH /pbm/plans/{id} accepts version, deductible_cents,
        oop_max_cents, coinsurance_rate, mail_order_discount_rate.

        Claim: PATCH with matching version updates field and bumps
        version by 1.
        """
        plan = create_plan(deductible_cents=50_000, oop_max_cents=200_000,
                           coinsurance_rate=0.20)
        old_version = plan["version"]
        res = api.patch_plan(
            plan["id"],
            patch_plan_payload(
                deductible_cents=75_000, version=old_version,
            ),
            admin_headers,
        )
        updated = validate_success(res, 200)
        assert updated["deductible_cents"] == 75_000
        assert_version_incremented_by_one(
            updated["version"], old_version,
        )

    def test_patch_plan_stale_version_rejected(self, api, admin_headers):
        """PRD §2.6: "When version is supplied, the server compares it
        against the entity's current version; if the two do not match,
        the request is rejected with ERR_VERSION_CONFLICT and no side
        effects are produced."

        Claim: stale version -> ERR_VERSION_CONFLICT.
        """
        plan = create_plan()
        api.patch_plan(
            plan["id"],
            patch_plan_payload(
                deductible_cents=99, version=plan["version"],
            ),
            admin_headers,
        )
        # Now plan's version has incremented; old version is stale.
        res = api.patch_plan(
            plan["id"],
            patch_plan_payload(
                deductible_cents=88, version=plan["version"],
            ),
            admin_headers,
        )
        validate_error(res, "ERR_VERSION_CONFLICT")


# ===========================================================================
# Drug
# ===========================================================================
class TestDrugCRUD:
    """PRD §3.1 Drug."""

    def test_create_drug_returns_resource(self, api, admin_headers):
        """PRD §3.1: "Each Drug is created with an eleven-digit
        National Drug Code ndc … a generic_name, a brand_name, and a
        non-negative unit_allowed_cents".

        Claim: create returns Drug with all required fields.
        """
        payload = create_drug_payload(
            ndc="12345678901", generic_name="g", brand_name="b",
            unit_allowed_cents=500,
        )
        drug = validate_success(
            api.create_drug(payload, admin_headers), 201,
        )
        assert_drug(drug)
        assert drug["ndc"] == "12345678901"
        assert drug["unit_allowed_cents"] == 500
        assert drug["is_specialty"] is False
        assert drug["requires_prior_auth"] is False

    @pytest.mark.parametrize("bad_ndc", [
        "1234567890",       # 10 digits
        "123456789012",     # 12 digits
        "1234567890A",      # non-digit
        "",
    ])
    def test_invalid_ndc_format_rejected(
        self, api, admin_headers, bad_ndc,
    ):
        """PRD §3.1: ndc "must consist of exactly eleven digit
        characters".
        PRD §2.8 rung 16 / §5: "ERR_VALIDATION" covers "an invalid
        ndc format".

        Claim: invalid NDC -> ERR_VALIDATION.
        """
        payload = create_drug_payload(ndc=bad_ndc)
        res = api.create_drug(payload, admin_headers)
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# FormularyEntry
# ===========================================================================
class TestFormularyEntryCRUD:
    """PRD §3.1 FormularyEntry."""

    def test_create_formulary_entry_returns_resource(
        self, api, admin_headers,
    ):
        """PRD §3.1: "The bridge between plan and drug is the
        FormularyEntry, which is added by a PBMAdmin to record that a
        particular plan_id covers a particular drug_id at a particular
        tier."

        Claim: create returns FormularyEntry with plan_id, drug_id,
        tier, copay_cents.
        """
        plan = create_plan()
        drug = create_drug()
        payload = create_formulary_entry_payload(
            plan_id=plan["id"], drug_id=drug["id"],
            tier=2, copay_cents=1500,
        )
        entry = validate_success(
            api.create_formulary_entry(payload, admin_headers), 201,
        )
        assert_formulary_entry(entry)
        assert entry["plan_id"] == plan["id"]
        assert entry["drug_id"] == drug["id"]
        assert entry["tier"] == 2
        assert entry["copay_cents"] == 1500

    @pytest.mark.parametrize("bad_tier", [0, 6, -1, 100])
    def test_invalid_tier_rejected(
        self, api, admin_headers, bad_tier,
    ):
        """PRD §2.8 rung 16: "the tier must lie in the 1-to-5 band
        and rate fields must lie in the 0-to-1 band; otherwise
        ERR_VALIDATION (422)."

        Claim: tier outside 1..5 -> ERR_VALIDATION.
        """
        plan = create_plan()
        drug = create_drug()
        res = api.create_formulary_entry(
            create_formulary_entry_payload(
                plan_id=plan["id"], drug_id=drug["id"],
                tier=bad_tier, copay_cents=0,
            ),
            admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# Member
# ===========================================================================
class TestMemberCRUD:
    """PRD §3.2 Member."""

    def test_create_member_starts_active_ytd_zero(
        self, api, admin_headers,
    ):
        """PRD §3.2: "The system mints a fresh Member row whose
        enrollment_status begins at ACTIVE … and whose
        ytd_deductible_paid_cents and ytd_oop_paid_cents both begin
        at zero."

        Claim: created member has enrollment_status=ACTIVE,
        ytd_*=0.
        """
        plan = create_plan()
        m = validate_success(
            api.create_member(
                create_member_payload(plan_id=plan["id"]),
                admin_headers,
            ),
            201,
        )
        assert_member(m)
        assert m["enrollment_status"] == "ACTIVE"
        assert m["ytd_deductible_paid_cents"] == 0
        assert m["ytd_oop_paid_cents"] == 0

    def test_suspend_member_sets_status_suspended(
        self, api, admin_headers,
    ):
        """PRD §3.2: "A PBMAdmin may transition a member to SUSPENDED
        through a dedicated suspend action."
        PRD §2.4: "version … increments by one on every mutation".

        Claim: suspend transitions to SUSPENDED and bumps version.
        """
        plan = create_plan()
        member = create_member(plan_id=plan["id"])
        res = api.suspend_member(
            member["id"], {"version": member["version"]},
            admin_headers,
        )
        suspended = validate_success(res, 200)
        assert suspended["enrollment_status"] == "SUSPENDED"
        assert_version_incremented_by_one(
            suspended["version"], member["version"],
        )

    def test_suspend_member_stale_version_rejected(
        self, api, admin_headers,
    ):
        """PRD §2.6: "if the two do not match, the request is rejected
        with ERR_VERSION_CONFLICT and no side effects are produced."

        Claim: suspend with stale version -> ERR_VERSION_CONFLICT.

        Setup note: the member must remain in a state where suspend is
        a legal transition (i.e., ACTIVE) so that the §2.8 ladder
        actually reaches rung 17 (version envelope). Per PRD §2.9,
        adjudicating a claim "refreshes the Member entity … with the
        consequent updated_at and version bump on the member"; that
        gives us a version-bump path that leaves enrollment_status =
        ACTIVE, so the only ladder violation in the second request is
        the stale-version one and rung 17 fires deterministically.
        """
        from test_helpers import (
            setup_reference_data,
            setup_adjudicated_claim,
        )
        plan, drug, _fe, member = setup_reference_data()
        # Adjudicate a claim against this member to bump Member.version
        # (PRD §2.9). The member stays ACTIVE.
        setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        # Now suspend with the stale (pre-adjudicate) version. Member
        # is still ACTIVE, so rung 4 (state legality) is not violated;
        # only rung 17 (version envelope) is, and PRD §2.6 names the
        # error precisely.
        res = api.suspend_member(
            member["id"], {"version": member["version"]},
            admin_headers,
        )
        validate_error(res, "ERR_VERSION_CONFLICT")
