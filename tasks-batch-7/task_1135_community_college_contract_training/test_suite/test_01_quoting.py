"""Quoting: dual-variant pricing, combinatorial rush/floor interaction, floor."""
from test_helpers import (
    validate_success,
    create_employer,
    create_approved_assessment,
    create_agreement,
    create_venue_for_mode,
    api_client,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _quote(agreement_id):
    return validate_success(api_client.quote_training_agreement(agreement_id, COORD))


class TestQuotePricingVariants:
    def test_per_participant_total_n20_on_site(self, api):
        """PRD §3.2: "Under `PER_PARTICIPANT`, tuition is tiered and marginal:
        each of the first ten estimated participants costs 45,000 cents of
        tuition, each of the next fifteen — participants eleven through
        twenty-five — costs 40,000 cents, and every estimated participant
        beyond the twenty-fifth costs 35,000 cents. Materials then add 7,500
        cents per estimated participant, and the per-participant base is the
        sum of the tiered tuition and the materials."
        PRD §3.2: "An `ON_SITE` agreement adds a flat surcharge of 25,000
        cents."

        Design: Difficulty/dual_variant_calc/quote_pricing_per_participant_vs_flat_cohort
        """
        emp = create_employer(legal_name="Acme Mfg", industry_code="332710",
                              contact_email="hr@acme.example")
        na = create_approved_assessment(
            emp["id"],
            curriculum_modules=[{"code": "CNC-1", "hours": 10,
                                 "required_credential_codes": ["CNC"]}],
        )
        a1 = create_agreement(
            emp["id"], na["id"],
            pricing_model="PER_PARTICIPANT", delivery_mode="ON_SITE",
            est_participant_count=20, est_delivery_hours=10,
            target_start_date="2026-07-01T00:00:00Z", max_cohorts=3,
        )
        q1 = _quote(a1["id"])
        # tuition 450000+400000; materials 150000; surcharge 25000
        assert q1["quoted_total_cents"] == 1025000, (
            f"PER_PARTICIPANT n=20 ON_SITE: expected 1025000, got {q1['quoted_total_cents']}"
        )

    def test_flat_cohort_total_n20_on_site_differs(self, api):
        """PRD §3.2: "Under `FLAT_COHORT`, the base is instead a flat 480,000
        cents that covers up to twelve participants, plus 38,000 cents for
        each estimated participant beyond the twelfth. Identical inputs
        produce different totals under the two models."
        PRD §3.2: "An `ON_SITE` agreement adds a flat surcharge of 25,000
        cents."

        Design: Difficulty/dual_variant_calc/quote_pricing_per_participant_vs_flat_cohort
        """
        emp = create_employer(legal_name="Acme Mfg", industry_code="332710",
                              contact_email="hr@acme.example")
        na = create_approved_assessment(
            emp["id"],
            curriculum_modules=[{"code": "CNC-1", "hours": 10,
                                 "required_credential_codes": ["CNC"]}],
        )
        a2 = create_agreement(
            emp["id"], na["id"],
            pricing_model="FLAT_COHORT", delivery_mode="ON_SITE",
            est_participant_count=20, est_delivery_hours=10,
            target_start_date="2026-07-01T00:00:00Z", max_cohorts=3,
        )
        q2 = _quote(a2["id"])
        # 480000 flat + 8*38000 overage + 25000 surcharge
        assert q2["quoted_total_cents"] == 809000, (
            f"FLAT_COHORT n=20 ON_SITE: expected 809000, got {q2['quoted_total_cents']}"
        )


class TestQuoteCombinatorial:
    def test_tiered_campus_venue_rush_combination(self, api):
        """PRD §3.2: "An `ON_CAMPUS` agreement instead adds the product of
        `est_delivery_hours` and the `hourly_cost_cents` of the campus venue
        referenced through `campus_venue_id`; when no campus venue was
        referenced, that term is zero. When fewer than fourteen days separate
        the quote date from the `target_start_date`, a rush uplift applies:
        the mode-adjusted base is increased by ten percent, with the product
        rounded half up to whole cents — the quote's only rounding step."
        PRD §3.2: "the quote is forward-looking and reads no cohort or session
        rows — in a pinned evaluation order: tuition and materials first, then
        the delivery-mode adjustment, then the rush uplift with its single
        rounding, then the floor."

        Design: Difficulty/combinatorial_formula/quote_pricing_mode_a_tiered_rush_floor_interaction
        """
        emp = create_employer(legal_name="Gamma LLC", industry_code="541612",
                              contact_email="ld@gamma.example")
        na = create_approved_assessment(
            emp["id"],
            curriculum_modules=[{"code": "LEAD-1", "hours": 12,
                                 "required_credential_codes": []}],
        )
        ven = create_venue_for_mode("ON_CAMPUS", name="Main Lab", capacity=40,
                                    hourly_cost_cents=5000)
        agr = create_agreement(
            emp["id"], na["id"],
            pricing_model="PER_PARTICIPANT", delivery_mode="ON_CAMPUS",
            est_participant_count=30, est_delivery_hours=12,
            target_start_date="2026-05-10T00:00:00Z", max_cohorts=4,
            campus_venue_id=ven["id"],
        )
        q = _quote(agr["id"])
        # tuition 450000+600000+175000 = 1225000; materials 225000;
        # venue 12*5000 = 60000; subtotal 1510000; rush x1.10 -> 1661000
        assert q["quoted_total_cents"] == 1661000, (
            f"expected 1661000, got {q['quoted_total_cents']}"
        )

    def test_rush_uplift_applies_single_rounding_over_mode_adjusted_base(self, api):
        """PRD §3.2: "When fewer than fourteen days separate the quote date
        from the `target_start_date`, a rush uplift applies: the mode-adjusted
        base is increased by ten percent, with the product rounded half up to
        whole cents — the quote's only rounding step."

        Design: Difficulty/combinatorial_formula/quote_pricing_mode_a_tiered_rush_floor_interaction
        """
        emp = create_employer(legal_name="Gamma Rush", industry_code="541613",
                              contact_email="rush@gamma.example")
        na = create_approved_assessment(emp["id"])
        # FLAT_COHORT n=2 ON_SITE: base 480000 + 25000 = 505000;
        # rush x1.10 -> 555500; above floor. Target 2026-05-10 is 9 days out.
        agr = create_agreement(
            emp["id"], na["id"],
            pricing_model="FLAT_COHORT", delivery_mode="ON_SITE",
            est_participant_count=2, est_delivery_hours=12,
            target_start_date="2026-05-10T00:00:00Z", max_cohorts=1,
        )
        q = _quote(agr["id"])
        assert q["quoted_total_cents"] == 555500, (
            f"expected rush-adjusted 555500, got {q['quoted_total_cents']}"
        )


class TestQuoteFloor:
    def test_min_contract_floor_applies(self, api):
        """PRD §3.2: "Finally, the floor applies: `quoted_total_cents` is the
        greater of the rush-adjusted base and 150,000 cents."

        Design: Corner/calculations/quote_floor_min_contract_applies
        """
        emp = create_employer(legal_name="FloorCo", industry_code="111194",
                              contact_email="hr@floor.example")
        na = create_approved_assessment(emp["id"])
        agr = create_agreement(
            emp["id"], na["id"],
            pricing_model="PER_PARTICIPANT", delivery_mode="ON_SITE",
            est_participant_count=2, est_delivery_hours=2,
            target_start_date="2026-07-01T00:00:00Z", max_cohorts=1,
        )
        q = _quote(agr["id"])
        # raw 90000 tuition + 15000 materials + 25000 surcharge = 130000 < 150000
        assert q["quoted_total_cents"] == 150000, (
            f"floor: expected 150000, got {q['quoted_total_cents']}"
        )
