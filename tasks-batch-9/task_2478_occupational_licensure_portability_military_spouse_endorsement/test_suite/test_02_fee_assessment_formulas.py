"""The six-step fee assessment: per-component waiver rounding, the expedite
surcharge that is keyed on the pre-surcharge subtotal, and the waiver tier the
resulting gross total selects."""

import pytest

from test_helpers import (
    APP_SUBMITTED,
    ENTRY_ASSESSMENT,
    ENTRY_WAIVER_CREDIT,
    MEMO_ASSESSMENT,
    MEMO_WAIVER_CREDIT,
    MILITARY_VETERAN,
    assert_application_fields,
    assert_ledger_signature,
    assert_memo,
)

LPC_PROFESSION = {
    "profession_code": "LPC",
    "title": "Licensed Professional Counselor",
    "required_scope_elements": ["INTAKE", "THERAPY"],
    "critical_scope_elements": [],
    "required_practice_hours": 3000,
    "requirement_hours_total": 150.0,
    "exam_waiver_min_score": 75.00,
    "jurisprudence_exam_required": True,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 75,
    "base_fee_cents": 12345,
    "endorsement_fee_cents": 6789,
    "exam_fee_cents": 3333,
    "jurisprudence_fee_cents": 2221,
    "permit_fee_cents": 4444,
    "expedite_surcharge_pct": 0.15,
}

LMT_PROFESSION = {
    "profession_code": "LMT",
    "title": "Licensed Massage Therapist",
    "required_scope_elements": ["INTAKE", "MANUAL"],
    "critical_scope_elements": [],
    "required_practice_hours": 500,
    "requirement_hours_total": 120.0,
    "exam_waiver_min_score": 80.00,
    "jurisprudence_exam_required": True,
    "universal_recognition_min_residency_months": 6,
    "standard_processing_days": 45,
    "base_fee_cents": 20000,
    "endorsement_fee_cents": 8000,
    "exam_fee_cents": 7000,
    "jurisprudence_fee_cents": 5000,
    "permit_fee_cents": 3000,
    "expedite_surcharge_pct": 0.15,
}


@pytest.fixture
def compact_waived_counsellor(setup):
    """An LPC file whose four odd-cent fee components meet a 0.50 compact waiver."""
    profession = setup.profession(**LPC_PROFESSION)
    setup.compact(
        profession["id"],
        partner_state="TX",
        fee_waiver_pct=0.50,
        exam_waiver_allowed=False,
        jurisprudence_waiver_allowed=False,
        expires_on="2027-12-31T00:00:00Z",
    )
    applicant = setup.applicant(full_name="Noor Haddad", state_code="TX", residency_months=18)
    credential = setup.credential(
        applicant["id"],
        issuing_state="NM",
        license_number="NM-51001",
        scope_elements=["INTAKE", "THERAPY"],
        practice_hours=3000,
        issued_at="2019-03-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    return {
        "prof_id": profession["id"],
        "ap_id": applicant["id"],
        "cred_id": credential["id"],
        "app_id": application["id"],
    }


@pytest.fixture
def two_veteran_masseurs(setup):
    """Two VETERAN applicants on one LMT fee schedule, differing only in `expedited`."""
    profession = setup.profession(**LMT_PROFESSION)
    arms = {}
    for key, name, expedited, license_number in (
        ("c", "Sasha Byrd", False, "NM-33001"),
        ("d", "Mira Osei", True, "NM-33002"),
    ):
        applicant = setup.applicant(
            full_name=name, state_code="TX", residency_months=12, military_status=MILITARY_VETERAN
        )
        credential = setup.credential(
            applicant["id"],
            issuing_state="NM",
            license_number=license_number,
            scope_elements=["INTAKE", "MANUAL"],
            practice_hours=500,
            issued_at="2021-01-04T00:00:00Z",
        )
        application = setup.application(
            applicant["id"], profession["id"], credential["id"], expedited=expedited
        )
        arms[key] = {
            "ap_id": applicant["id"],
            "app_id": application["id"],
        }
    return {"prof_id": profession["id"], **arms}


class TestPerComponentWaiverRounding:
    def test_each_component_is_rounded_before_the_waiver_credits_are_summed(
        self, compact_waived_counsellor, setup
    ):
        """PRD §3.4: "Each of the five money figures — base component, endorsement
        component, examination component, jurisprudence component and expedite
        surcharge — is multiplied by `statutory_waiver_pct` and rounded half up to a
        whole cent **individually**, and the five rounded results are then added
        together. Summing first and rounding once is a different answer and is not
        permitted."

        Design: Difficulty/combinatorial_formula/fee_waiver_per_component_rounding_beats_sum_then_round
        """
        env = compact_waived_counsellor
        setup.submit(env["app_id"], env["ap_id"])

        application = setup.read_application(env["app_id"])
        assert_application_fields(
            application, gross_total_cents=24688, statutory_waiver_pct=0.50
        )
        assert application["fee_balance_cents"] == 12342, (
            "6173 + 3395 + 1667 + 1111 = 12346 of waiver credit; summing the raw halves "
            "and rounding once would have produced 12344"
        )

    def test_the_two_pinned_ledger_entries_carry_the_gross_and_the_waiver_credit(
        self, compact_waived_counsellor, setup
    ):
        """PRD §3.4: "Two ledger entries are then appended, in a pinned order: first
        an `ASSESSMENT` entry whose `amount_cents` is the positive
        `gross_total_cents` and whose `memo` is `submit assessment`, then a
        `WAIVER_CREDIT` entry whose `amount_cents` is the negative of the waiver
        credit and whose `memo` is `statutory waiver credit`."

        Design: Difficulty/combinatorial_formula/fee_waiver_per_component_rounding_beats_sum_then_round
        """
        env = compact_waived_counsellor
        setup.submit(env["app_id"], env["ap_id"])

        ledger = setup.read_ledger(env["app_id"])
        assert_ledger_signature(
            ledger, [(ENTRY_ASSESSMENT, 24688), (ENTRY_WAIVER_CREDIT, -12346)]
        )
        assert_memo(ledger[0], MEMO_ASSESSMENT)
        assert_memo(ledger[1], MEMO_WAIVER_CREDIT)

    def test_a_civilian_resident_of_a_partner_state_takes_the_compacts_fraction(
        self, compact_waived_counsellor, setup
    ):
        """PRD §3.4: "Otherwise, if an unexpired reciprocal agreement exists for this
        profession whose `partner_state` equals the applicant's `state_code` —
        unexpired meaning the logical clock is at or before its `expires_on` — then
        `statutory_waiver_pct` takes that compact's `fee_waiver_pct`."

        Design: Difficulty/combinatorial_formula/fee_waiver_per_component_rounding_beats_sum_then_round
        """
        env = compact_waived_counsellor
        setup.submit(env["app_id"], env["ap_id"])

        application = setup.read_application(env["app_id"])
        assert_application_fields(
            application,
            status=APP_SUBMITTED,
            submitted_at="2026-08-01T00:00:00Z",
            review_deadline_at="2026-10-15T00:00:00Z",
            statutory_waiver_pct=0.50,
        )


class TestExpediteSurchargeFlipsTheWaiverTier:
    def test_the_surcharge_pushes_the_gross_above_the_military_full_waiver_cap(
        self, two_veteran_masseurs, setup
    ):
        """PRD §3.4: "If the pathway is `MILITARY_SPOUSE_EXPEDITED`, or the
        applicant's `military_status` is `SERVICE_MEMBER`, `MILITARY_SPOUSE` or
        `VETERAN`, then `statutory_waiver_pct` is 1.00 when `gross_total_cents` is at
        most the military full-waiver cap of 40000 cents, and 0.50 when it is above
        that cap."

        Design: Difficulty/combinatorial_formula/expedite_surcharge_flips_military_waiver_cap_tier
        """
        env = two_veteran_masseurs
        setup.submit(env["c"]["app_id"], env["c"]["ap_id"])
        setup.submit(env["d"]["app_id"], env["d"]["ap_id"])

        plain = setup.read_application(env["c"]["app_id"])
        expedited = setup.read_application(env["d"]["app_id"])

        assert_application_fields(
            plain, gross_total_cents=40000, statutory_waiver_pct=1.00, fee_balance_cents=0
        )
        assert_application_fields(
            expedited, gross_total_cents=46000, statutory_waiver_pct=0.50, fee_balance_cents=23000
        )

    def test_the_surcharge_is_keyed_on_the_pre_waiver_subtotal_not_on_any_net_figure(
        self, two_veteran_masseurs, setup
    ):
        """PRD §3.4: "When `expedited` is true, the surcharge is the gross subtotal
        multiplied by the profession's `expedite_surcharge_pct`, rounded half up to a
        whole cent; when `expedited` is false the surcharge is zero."

        Design: Difficulty/combinatorial_formula/expedite_surcharge_flips_military_waiver_cap_tier
        """
        env = two_veteran_masseurs
        setup.submit(env["c"]["app_id"], env["c"]["ap_id"])
        setup.submit(env["d"]["app_id"], env["d"]["ap_id"])

        plain_ledger = setup.read_ledger(env["c"]["app_id"])
        expedited_ledger = setup.read_ledger(env["d"]["app_id"])

        assert_ledger_signature(
            plain_ledger, [(ENTRY_ASSESSMENT, 40000), (ENTRY_WAIVER_CREDIT, -40000)]
        )
        assert_ledger_signature(
            expedited_ledger, [(ENTRY_ASSESSMENT, 46000), (ENTRY_WAIVER_CREDIT, -23000)]
        )

    def test_buying_expedited_processing_shortens_the_review_deadline_to_thirty_days(
        self, two_veteran_masseurs, setup
    ):
        """PRD §3.4: "Its `review_deadline_at` is derived by choosing a processing
        allowance and adding it to `submitted_at` as whole days: the allowance is the
        expedite allowance of 30 days whenever `expedited` is true **or** the pathway
        is `MILITARY_SPOUSE_EXPEDITED`, and otherwise it is the profession's
        published `standard_processing_days`."

        Design: Difficulty/combinatorial_formula/expedite_surcharge_flips_military_waiver_cap_tier
        """
        env = two_veteran_masseurs
        setup.submit(env["c"]["app_id"], env["c"]["ap_id"])
        setup.submit(env["d"]["app_id"], env["d"]["ap_id"])

        plain = setup.read_application(env["c"]["app_id"])
        expedited = setup.read_application(env["d"]["app_id"])

        assert_application_fields(plain, review_deadline_at="2026-09-15T00:00:00Z")
        assert_application_fields(expedited, review_deadline_at="2026-08-31T00:00:00Z")
