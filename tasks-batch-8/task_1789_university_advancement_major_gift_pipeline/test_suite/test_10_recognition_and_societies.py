"""Recognition scoring variants, society thresholds, and society configuration."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_prospect, create_payment, create_recognition_society,
    create_gift_payment_payload,
    setup_active_pledge, create_fundraiser, rate_prospect, assign_prospect,
    move_prospect, create_approved_proposal, create_executed_agreement,
    create_pledge_for, get_prospect,
)

RES = TEST_USERS["researcher_headers"]
DRO = TEST_USERS["dro_headers"]
FIN = TEST_USERS["finance_headers"]


class TestRecognitionVariantDivergence:
    """Queue A: dual_variant_calc / recognition_cash_only_vs_comprehensive_divergence."""

    def _setup(self):
        """Prospect A: 8000000 cash + ACTIVE pledge 5000000 + 2000000 soft credit
        from prospect B's split payment. BRONZE threshold 10000000."""
        create_recognition_society()
        f = create_fundraiser()
        pa = create_prospect(full_name="Donor A", contact_email="a@x.com")
        rate_prospect(pa["id"])
        assign_prospect(f["id"], pa["id"])
        move_prospect(pa["id"], f["id"], "CULTIVATION")

        # 8000000 outright cash (no pledge/fund/campaign).
        create_payment(pa["id"], 8000000, received_at="2026-08-10T00:00:00Z")

        # ACTIVE pledge 5000000 (1 installment, outstanding in full).
        prop = create_approved_proposal(pa["id"], f["id"], 5000000, proposal_type="PLEDGE",
                                        designation_purpose="Scholarships")
        agr = create_executed_agreement(prop, f["id"])
        create_pledge_for(agr["id"], f["id"], 5000000, installment_count=1,
                          frequency="ANNUAL", first_due_date="2026-12-01T00:00:00Z")

        # B's 4000000 payment split 50/50 gives A a 2000000 SOFT credit.
        pb = create_prospect(full_name="Donor B", contact_email="b@x.com")
        create_payment(
            pb["id"], 4000000, received_at="2026-08-12T00:00:00Z", payment_method="STOCK",
            splits=[
                {"prospect_id": pb["id"], "credit_type": "HARD", "split_pct": 50},
                {"prospect_id": pa["id"], "credit_type": "SOFT", "split_pct": 50},
            ],
        )
        return pa

    def test_cash_only_membership_below_threshold_while_comprehensive_projects(self, api):
        """PRD §3.9: "Membership uses cash only: a prospect's `member_level` is
        the highest society level whose `threshold_cash_cents` is at or below the
        cash-only total, with levels ranked `BRONZE` below `SILVER` below `GOLD`
        below `PLATINUM`, and null when the total clears no threshold; the
        `projected_level` applies the same rule to the comprehensive total, so a
        prospect can project higher than its membership."

        Design: Difficulty/dual_variant_calc/recognition_cash_only_vs_comprehensive_divergence
        """
        pa = self._setup()
        data = validate_success(api.get_recognition(pa["id"], DRO))
        assert data["cash_total_cents"] == 8000000
        assert data["member_level"] is None  # 8000000 < 10000000
        assert data["projected_level"] == "BRONZE"  # 15000000 >= 10000000
        assert data["member_level"] != data["projected_level"]

    def test_comprehensive_total_adds_pledge_outstanding_and_soft_credits(self, api):
        """PRD §3.9: "The **cash-only** total is exactly the prospect's
        `lifetime_given_cents`. The **comprehensive** total adds to that the
        `outstanding_cents` of the prospect's `ACTIVE` pledges plus the
        `amount_cents` of the prospect's non-reversed `SOFT` credit splits — the
        same figure reported as `soft_credit_cents` in the recognition read."

        Design: Difficulty/dual_variant_calc/recognition_cash_only_vs_comprehensive_divergence
        """
        pa = self._setup()
        data = validate_success(api.get_recognition(pa["id"], DRO))
        assert data["cash_total_cents"] == 8000000
        assert data["comprehensive_total_cents"] == 15000000  # 8000000 + 5000000 + 2000000
        assert data["soft_credit_cents"] == 2000000


class TestSocietyThresholdBoundary:
    def test_society_threshold_boundary_exact_qualification(self, api):
        """PRD §3.9: "Membership uses cash only: a prospect's `member_level` is
        the highest society level whose `threshold_cash_cents` is at or below the
        cash-only total."
        PRD §3.9: "The prospect's `recognition_society_id` holds the society
        corresponding to the member level."

        Design: Corner/calculations/society_threshold_boundary_exact_qualification
        """
        soc = create_recognition_society()
        px = create_prospect(full_name="Just Under", contact_email="ju@x.com")
        py = create_prospect(full_name="Exactly", contact_email="ex@x.com")
        create_payment(px["id"], 9999999)
        create_payment(py["id"], 10000000)

        data_x = validate_success(api.get_recognition(px["id"], DRO))
        assert data_x["member_level"] is None  # 9999999 < 10000000

        data_y = validate_success(api.get_recognition(py["id"], DRO))
        assert data_y["member_level"] == "BRONZE"  # 10000000 >= 10000000

        p_y = get_prospect(py["id"])
        assert p_y["recognition_society_id"] == soc["id"]

    def test_derived_field_reconciles_immediately_after_payment(self, api):
        """PRD §3.7: "The donor prospect's `lifetime_given_cents`,
        `outstanding_pledge_cents`, and recognition standing recompute, and the
        prospect's `version` advances by 1."
        PRD §3.9: "the totals recompute on every payment creation or reversal,
        pledge creation, approved write-off, or pledge cancellation touching the
        prospect."

        Design: Corner/cross_cutting_layers/derived_field_reconciles_immediately_after_payment
        """
        soc = create_recognition_society(threshold_cash_cents=100000)
        p = create_prospect()
        create_payment(p["id"], 250000, payment_method="CARD")

        data = get_prospect(p["id"])
        assert data["lifetime_given_cents"] == 250000  # visible in the very next read
        assert data["recognition_society_id"] == soc["id"]  # 250000 >= 100000


class TestSocietyConfiguration:
    def test_duplicate_society_level_rejected(self, api):
        """PRD §3.9: "a `level` of `BRONZE`, `SILVER`, `GOLD`, or `PLATINUM` —
        unique across all societies, so a duplicate level is rejected with
        `ERR_DUPLICATE_SOCIETY_LEVEL`."

        Design: Corner/validations/duplicate_society_level_rejected
        """
        create_recognition_society()
        resp = api.create_recognition_society(
            {"name": "Bronze Duplicate", "level": "BRONZE", "threshold_cash_cents": 20000000},
            DRO,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SOCIETY_LEVEL)
        rows, meta = validate_paginated(api.list_recognition_societies(DRO))
        assert len(rows) == 1 and meta["total_count"] == 1
