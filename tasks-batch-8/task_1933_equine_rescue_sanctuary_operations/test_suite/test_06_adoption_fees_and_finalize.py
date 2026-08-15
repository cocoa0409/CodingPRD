"""Adoption fee calculation variants and finalization gates."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    assert_same_instant,
    make_adopter_headers, make_sponsor_headers,
    intake_horse, get_horse, complete_medical_pass, clear_active_protocol,
    release_horse, set_clock, register_vet, register_adopter, register_sponsor,
    create_sponsorship, submit_application, start_review, pass_home_check,
    get_application, setup_released_horse, setup_application_home_check_passed,
    setup_approved_application, approve_and_pay, finalize_at,
)

OFFICER_2 = TEST_USERS["officer_2_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _setup_bonded_pair():
    """H2 (age 20, GREEN) and bonded H1 (age 8, TRAINED_RIDDEN), both ADOPTABLE."""
    vet_id = register_vet()
    h2 = intake_horse(name="H2", sex="GELDING", estimated_weight_lbs=800,
                      age_years=20, body_condition_score=5,
                      training_level="GREEN")
    complete_medical_pass(h2["id"], at="2026-08-14T12:00:00Z")
    clear_active_protocol(h2["id"], vet_id, at="2026-08-15T00:00:00Z")
    release_horse(h2["id"], "ADOPTABLE")
    # H1 intaken at logical 08-15: protocol start 08-15, earliest clear 08-29.
    h1 = intake_horse(name="H1", sex="MARE", estimated_weight_lbs=1000,
                      age_years=8, body_condition_score=5,
                      training_level="TRAINED_RIDDEN",
                      bonded_companion_id=h2["id"])
    complete_medical_pass(h1["id"], at="2026-08-27T12:00:00Z")
    clear_active_protocol(h1["id"], vet_id, at="2026-08-29T00:00:00Z")
    release_horse(h1["id"], "ADOPTABLE")
    return vet_id, h1, h2


def _pair_application_bundle():
    vet_id, h1, h2 = _setup_bonded_pair()
    adopter = register_adopter(full_name="Ad Pair", contact_email="ap@x.com")
    app = submit_application(adopter["id"], h1["id"],
                             pickup="2026-09-05T00:00:00Z", pair=True)
    start_review(app["id"])
    pass_home_check(app["id"], scheduled_date="2026-08-29T10:00:00Z")
    return {"vet_id": vet_id, "h1": h1, "h2": h2, "adopter": adopter,
            "application": get_application(app["id"])}


class TestPairFeeCombination:
    def test_pair_adoption_fee_combines_tiers(self):
        """PRD §3.4: "Step one computes a per-horse base from the horse's
        `age_years`: 95000 cents under 2 years of age, 85000 cents from 2 through
        14, 60000 cents from 15 through 19, and 35000 cents at 20 or older; then
        adjusts for `training_level` — add 15000 cents for `TRAINED_RIDDEN`,
        subtract 10000 for `GREEN`, subtract 20000 for `UNHANDLED`"
        PRD §3.4: "when `adopt_with_bonded_companion` is set, step one is computed
        separately for the primary horse and for the bonded companion, the two
        figures are summed, and the fee becomes seventy-five percent of that sum,
        rounded half up to integer cents."
        (fee(H1)=100000; fee(H2)=25000; 0.75*125000 = 93750)

        Design: Difficulty/combinatorial_formula/adoption_fee_tiered_pair_combination
        """
        bundle = _pair_application_bundle()
        approved = validate_success(api_client.approve_application(
            bundle["application"]["id"], OFFICER_2))
        assert approved["quoted_fee_cents"] == 93750
        assert approved["status"] == "APPROVED"

    def test_pair_approve_locks_only_primary_horse(self):
        """PRD §3.4: "Approval stamps `approved_at` at the logical now, snapshots
        `quoted_fee_cents` from the QUOTED variant of the fee calculation
        described below, and cascades onto the horse: `ADOPTABLE` →
        `ADOPTION_PENDING`, the horse's `active_application_id` set to the
        approved application, and the horse's `version` incremented."
        PRD §3.4: "when `adopt_with_bonded_companion` is set, the companion horse
        must be `ADOPTABLE` (`ERR_BONDED_PAIR_VIOLATION`)"

        Design: Difficulty/combinatorial_formula/adoption_fee_tiered_pair_combination
        """
        bundle = _pair_application_bundle()
        validate_success(api_client.approve_application(
            bundle["application"]["id"], OFFICER_2))
        h1 = get_horse(bundle["h1"]["id"])
        assert h1["status"] == "ADOPTION_PENDING"
        assert h1["active_application_id"] == bundle["application"]["id"]
        h2 = get_horse(bundle["h2"]["id"])
        assert h2["status"] == "ADOPTABLE", (
            "companion is not locked until finalization")


class TestQuotedVsFinalDivergence:
    def _setup_subsidized_approval(self):
        """Horse (age 8, TRAINED_RIDDEN -> 100000) with ACTIVE 20000 sponsorship;
        application APPROVED at quoted 90000 with 90000 paid."""
        bundle = setup_released_horse(
            "ADOPTABLE",
            {"name": "H", "age_years": 8, "body_condition_score": 5,
             "training_level": "TRAINED_RIDDEN", "estimated_weight_lbs": 1050})
        sponsor = register_sponsor(name="SP", contact_email="sp@x.com")
        sponsorship = create_sponsorship(sponsor["id"], bundle["horse"]["id"],
                                         20000, activate=True)
        adopter = register_adopter(full_name="Ad One", contact_email="a1@x.com")
        app = submit_application(adopter["id"], bundle["horse"]["id"])
        start_review(app["id"])
        pass_home_check(app["id"], scheduled_date="2026-08-15T10:00:00Z")
        approved = get_success_data(api_client.approve_application(
            app["id"], OFFICER_2))
        assert approved["quoted_fee_cents"] == 90000
        get_success_data(api_client.pay_application_fee(
            app["id"], {"amount_cents": 90000},
            make_adopter_headers(adopter["id"])))
        return {"horse": bundle["horse"], "vet_id": bundle["vet_id"],
                "adopter": adopter, "sponsor": sponsor,
                "sponsorship": sponsorship, "application": approved}

    def test_finalize_rejected_when_final_fee_exceeds_paid(self):
        """PRD §3.4: "The FINAL variant reruns at finalization and is written to
        `final_fee_cents`; a sponsor lapse or cancellation, or a companion status
        change between approval and finalization, legitimately changes the
        number."
        PRD §3.5: "The FINAL fee recomputed at that instant must equal the
        accumulated `fee_paid_cents` exactly — an underpaid or overpaid balance
        fails with `ERR_ADOPTION_FEE_UNPAID`."

        Design: Difficulty/dual_variant_calc/adoption_fee_quoted_vs_final_divergence
        """
        bundle = self._setup_subsidized_approval()
        get_success_data(api_client.cancel_sponsorship(
            bundle["sponsorship"]["id"], {}, DIRECTOR))
        set_clock("2026-08-18T00:00:00Z")
        resp = api_client.finalize_application(
            bundle["application"]["id"], OFFICER_2)
        validate_error(resp, ApiErrorId.ERR_ADOPTION_FEE_UNPAID, 422)

    def test_finalize_succeeds_after_fee_topup(self):
        """PRD §3.5: "A successful finalization stamps `final_fee_cents` with the
        FINAL recompute — which may differ from `quoted_fee_cents` — sets
        `finalized_at` to the logical now, moves the application `APPROVED` →
        `FINALIZED`, and fires the full adoption cascade on the horse."
        PRD §3.4: "when the primary horse's `ACTIVE` sponsorships sum
        `monthly_pledge_cents` to at least 19250 cents, the fee is reduced by ten
        percent — multiplied by 0.90 and rounded half up — and only the primary
        horse's sponsorships ever count here."

        Design: Difficulty/dual_variant_calc/adoption_fee_quoted_vs_final_divergence
        """
        bundle = self._setup_subsidized_approval()
        app_id = bundle["application"]["id"]
        get_success_data(api_client.cancel_sponsorship(
            bundle["sponsorship"]["id"], {}, DIRECTOR))
        set_clock("2026-08-18T00:00:00Z")
        api_client.finalize_application(app_id, OFFICER_2)  # rejected: 100000 != 90000
        get_success_data(api_client.pay_application_fee(
            app_id, {"amount_cents": 10000},
            make_adopter_headers(bundle["adopter"]["id"])))
        finalized = validate_success(api_client.finalize_application(
            app_id, OFFICER_2))
        assert finalized["status"] == "FINALIZED"
        assert finalized["final_fee_cents"] == 100000
        assert finalized["quoted_fee_cents"] == 90000, (
            "QUOTED snapshot stays frozen; FINAL diverges after sponsor cancel")


class TestCoolingOffBoundary:
    def test_finalize_at_exactly_72h_succeeds(self):
        """PRD §3.5: "At least 72 hours must have elapsed since `approved_at`,
        else `ERR_COOLING_OFF_ACTIVE`."

        Design: Difficulty/boundary_precision_check/cooling_off_exactly_72h_finalize
        """
        bundle = setup_approved_application(
            horse_overrides={"name": "H", "age_years": 6,
                             "body_condition_score": 5, "training_level": "GREEN"})
        assert bundle["application"]["quoted_fee_cents"] == 75000, (
            "85000 base (age 6) - 10000 GREEN; no subsidy, no pair")
        finalized = finalize_at(bundle, "2026-08-18T00:00:00Z")
        assert finalized["status"] == "FINALIZED"

    def test_finalize_stamps_finalized_at_boundary_instant(self):
        """PRD §3.5: "A successful finalization stamps `final_fee_cents` with the
        FINAL recompute — which may differ from `quoted_fee_cents` — sets
        `finalized_at` to the logical now, moves the application `APPROVED` →
        `FINALIZED`, and fires the full adoption cascade on the horse."

        Design: Difficulty/boundary_precision_check/cooling_off_exactly_72h_finalize
        """
        bundle = setup_approved_application(
            horse_overrides={"name": "H", "age_years": 6,
                             "body_condition_score": 5, "training_level": "GREEN"})
        finalized = finalize_at(bundle, "2026-08-18T00:00:00Z")
        assert_same_instant(finalized["finalized_at"], "2026-08-18T00:00:00Z")
        assert finalized["final_fee_cents"] == 75000


class TestFinalizePriorityPair:
    def _setup_approved_unpaid(self):
        bundle = setup_application_home_check_passed(
            horse_overrides={"name": "H", "sex": "GELDING", "age_years": 8})
        approved = get_success_data(api_client.approve_application(
            bundle["application"]["id"], OFFICER_2))
        bundle["application"] = approved
        return bundle

    def test_cooling_off_outranks_unpaid_fee(self):
        """PRD §2.7: "Evaluation stops at the first failing tier, so the error a
        caller receives is always the highest-priority failure their request would
        have produced."
        PRD §2.7: "17. **Cooling-off windows.** Adoption finalization and
        euthanasia execution must wait out their 72-hour cooling-off periods,
        subject to the emergency exception of §3.9; failure is
        `ERR_COOLING_OFF_ACTIVE` (HTTP 422)."
        PRD §2.7: "25. **Fiscal settlement.** The adoption fee must be exactly
        settled at finalization (`ERR_ADOPTION_FEE_UNPAID`)"

        Design: Difficulty/priority_pair_validation_conflict/finalize_temporal_vs_fiscal_priority
        """
        bundle = self._setup_approved_unpaid()
        set_clock("2026-08-15T01:00:00Z")  # 1h into the 72h window; fee unpaid
        resp = api_client.finalize_application(
            bundle["application"]["id"], OFFICER_2)
        validate_error(resp, ApiErrorId.ERR_COOLING_OFF_ACTIVE, 422)

    def test_application_unchanged_after_cooling_off_rejection(self):
        """PRD §3.5: "At least 72 hours must have elapsed since `approved_at`,
        else `ERR_COOLING_OFF_ACTIVE`."
        PRD §2.7: "Evaluation stops at the first failing tier, so the error a
        caller receives is always the highest-priority failure their request would
        have produced."

        Design: Difficulty/priority_pair_validation_conflict/finalize_temporal_vs_fiscal_priority
        """
        bundle = self._setup_approved_unpaid()
        set_clock("2026-08-15T01:00:00Z")
        api_client.finalize_application(bundle["application"]["id"], OFFICER_2)
        app = get_application(bundle["application"]["id"])
        assert app["status"] == "APPROVED"
        assert app["fee_paid_cents"] == 0


class TestSubsidyThreshold:
    def test_subsidy_threshold_19250_boundary(self):
        """PRD §3.4: "when the primary horse's `ACTIVE` sponsorships sum
        `monthly_pledge_cents` to at least 19250 cents, the fee is reduced by ten
        percent — multiplied by 0.90 and rounded half up — and only the primary
        horse's sponsorships ever count here."

        Design: Corner/calculations/subsidy_threshold_19250_boundary
        """
        vet_id = register_vet()
        h1 = intake_horse(name="H1", age_years=8, training_level="TRAINED_RIDDEN")
        h2 = intake_horse(name="H2", sex="GELDING", estimated_weight_lbs=1010,
                          age_years=8, training_level="TRAINED_RIDDEN")
        complete_medical_pass(h1["id"], at="2026-08-14T12:00:00Z")
        complete_medical_pass(h2["id"], at="2026-08-14T12:30:00Z")
        clear_active_protocol(h1["id"], vet_id)
        clear_active_protocol(h2["id"], vet_id)
        release_horse(h1["id"], "ADOPTABLE")
        release_horse(h2["id"], "ADOPTABLE")

        sponsor = register_sponsor(name="SP", contact_email="sp@x.com")
        create_sponsorship(sponsor["id"], h1["id"], 19250, activate=True)
        create_sponsorship(sponsor["id"], h2["id"], 19249, activate=True)

        adopter = register_adopter(full_name="Ad S", contact_email="as@x.com")
        app1 = submit_application(adopter["id"], h1["id"],
                                  pickup="2026-08-20T00:00:00Z")
        start_review(app1["id"])
        pass_home_check(app1["id"], scheduled_date="2026-08-15T10:00:00Z")
        app2 = submit_application(adopter["id"], h2["id"],
                                  pickup="2026-08-21T00:00:00Z")
        start_review(app2["id"])
        pass_home_check(app2["id"], scheduled_date="2026-08-15T11:00:00Z")

        approved1 = validate_success(api_client.approve_application(
            app1["id"], OFFICER_2))
        approved2 = validate_success(api_client.approve_application(
            app2["id"], OFFICER_2))
        assert approved1["quoted_fee_cents"] == 90000, (
            "19250 >= 19250: subsidy applies (100000 * 0.90)")
        assert approved2["quoted_fee_cents"] == 100000, (
            "19249 < 19250: no subsidy")


class TestFinalizeGates:
    def test_pickup_window_exceeded(self):
        """PRD §3.5: "The `proposed_pickup_date` must fall no more than 14 days
        after the finalization instant, else `ERR_PICKUP_WINDOW_EXCEEDED`."

        Design: Corner/validations/pickup_window_exceeded
        """
        bundle = setup_approved_application(
            horse_overrides={"name": "H", "age_years": 6},
            pickup="2026-09-10T00:00:00Z")
        set_clock("2026-08-18T00:00:00Z")  # 09-10 > 08-18 + 14d = 09-01
        resp = api_client.finalize_application(
            bundle["application"]["id"], OFFICER_2)
        validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_EXCEEDED, 422)

    def test_fee_amount_invalid_rejected(self):
        """PRD §3.4: "each payment's `amount_cents` must be a positive integer
        (`ERR_FEE_AMOUNT_INVALID`). Payments accumulate into `fee_paid_cents`."

        Design: Corner/validations/fee_amount_invalid_rejected
        """
        bundle = setup_application_home_check_passed(
            horse_overrides={"name": "H", "age_years": 6})
        approved = get_success_data(api_client.approve_application(
            bundle["application"]["id"], OFFICER_2))
        resp = api_client.pay_application_fee(
            approved["id"], {"amount_cents": -100},
            make_adopter_headers(bundle["adopter"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FEE_AMOUNT_INVALID, 422)
        assert get_application(approved["id"])["fee_paid_cents"] == 0
