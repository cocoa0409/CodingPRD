"""Infusion claim adjudication: auth gating, referential/temporal checks, sourcing
rules, JW/waste compliance, and the dose-tolerance fork (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    approve_auth,
    assert_infusion_claim,
    create_claim_payload,
    create_drug,
    create_policy,
    create_provider,
    get_auth,
    list_claims_for_auth,
    make_provider_rep_headers,
    publish_rate,
    setup_approved_scenario,
    setup_drug_with_policy,
    submit_auth,
    submit_claim,
    TEST_USERS,
    validate_error,
    validate_success,
)

MPO = TEST_USERS["mpo_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]


class TestClaimGatedByAuthState:
    def test_claim_against_submitted_auth_rejected(self, api):
        """PRD §3.6: "The authorization must be `APPROVED` — anything else, including
        `SUSPENDED`, `EXPIRED`, or `EXHAUSTED`, fails with `ERR_AUTH_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/claim_gated_by_auth_state
        """
        backbone = setup_drug_with_policy(
            drug_overrides={"j_code": "J3200", "drug_name": "GateDrugA"}
        )
        provider = create_provider(name="Gate Provider A")
        auth = submit_auth(backbone["drug"]["id"], provider["id"], "MEM-13")
        rep = make_provider_rep_headers(provider["id"])

        resp = api.create_claim(
            create_claim_payload(
                auth["id"], backbone["drug"]["id"], backbone["drug"]["j_code"]
            ),
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED, 409)

    def test_identical_claim_succeeds_after_approval(self, api):
        """PRD §3.6: "Creation returns 201, but `SUBMITTED` is transient: adjudication
        runs synchronously inside the request, and the returned claim is already
        `APPROVED_FOR_PAYMENT` or `PENDED`".
        PRD §3.6: "the drug component — `billed_units` times the rate times one plus the
        total add-on — is rounded half-up to whole cents" (10 x 500 x 1.06 -> 5300).

        Design: Difficulty/cross_entity_state_dependency/claim_gated_by_auth_state
        """
        backbone = setup_drug_with_policy(
            drug_overrides={"j_code": "J3201", "drug_name": "GateDrugA2"}
        )
        provider = create_provider(name="Gate Provider A2")
        auth = submit_auth(backbone["drug"]["id"], provider["id"], "MEM-13B")
        approve_auth(auth["id"], 4)
        scenario = {
            **backbone,
            "provider": provider,
            "auth": get_auth(auth["id"]),
            "rep_headers": make_provider_rep_headers(provider["id"]),
        }
        claim = submit_claim(scenario, billed_units=10)
        assert_infusion_claim(claim)
        assert claim["status"] == "APPROVED_FOR_PAYMENT"
        assert claim["allowed_amount_cents"] == 5300
        assert claim["administered_mg"] == 100


class TestClaimDefaults:
    def test_omitted_waste_and_jw_default_to_zero(self, api):
        """PRD §3.6: "optionally `waste_units` (default zero) and `jw_modifier` (default
        false)". PRD §3.6: "`payable_waste_units` equals `waste_units` when the drug is
        single-dose and `jw_modifier` is set, and zero otherwise."
        Pricing (PRD §3.6): round(5 x 500 x 1.06) = 2650; member share round(2650 x 0.20)
        = 530.

        Design: Corner/entities/claim_create_omitted_optionals_default
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J4100", "drug_name": "DefaultDrug"},
            member_id="MEM-D1",
        )
        payload = create_claim_payload(
            scenario["auth"]["id"],
            scenario["drug"]["id"],
            scenario["drug"]["j_code"],
            billed_units=5,
            site_of_care="HOPD",
        )
        assert "waste_units" not in payload and "jw_modifier" not in payload
        claim = validate_success(
            api.create_claim(payload, scenario["rep_headers"]), 201
        )
        assert claim["waste_units"] == 0
        assert claim["jw_modifier"] is False
        assert claim["payable_waste_units"] == 0
        assert claim["allowed_amount_cents"] == 2650
        assert claim["member_cost_share_cents"] == 530


class TestReferentialCoherence:
    def _setup_two_drugs(self):
        d1 = setup_drug_with_policy(
            drug_overrides={"j_code": "J5500", "drug_name": "RefD1"}
        )
        d2 = create_drug(j_code="J5501", drug_name="RefD2")
        provider = create_provider(name="Ref Provider")
        auth = submit_auth(d1["drug"]["id"], provider["id"], "MEM-V1")
        approve_auth(auth["id"], 4)
        rep = make_provider_rep_headers(provider["id"])
        return d1, d2, provider, get_auth(auth["id"]), rep

    def test_claim_drug_differs_from_auth_rejected(self, api):
        """PRD §3.6: "The billed `drug_id` must equal the authorization's drug
        (`ERR_DRUG_AUTH_MISMATCH`)".

        Design: Corner/validations/claim_referential_mismatches
        """
        d1, d2, provider, auth, rep = self._setup_two_drugs()
        resp = api.create_claim(
            create_claim_payload(auth["id"], d2["id"], d2["j_code"], billed_units=10),
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_DRUG_AUTH_MISMATCH, 422)

    def test_claim_with_wrong_j_code_rejected(self, api):
        """PRD §3.6: "`j_code_billed` must equal the drug's catalog `j_code`
        (`ERR_JCODE_MISMATCH`)".

        Design: Corner/validations/claim_referential_mismatches
        """
        d1, _, provider, auth, rep = self._setup_two_drugs()
        resp = api.create_claim(
            create_claim_payload(
                auth["id"], d1["drug"]["id"], "J9999", billed_units=10
            ),
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_JCODE_MISMATCH, 422)


class TestServiceDateTemporalChecks:
    def _scenario(self):
        return setup_approved_scenario(
            drug_overrides={"j_code": "J5600", "drug_name": "TempDrug"},
            member_id="MEM-V2",
        )

    def test_service_before_validity_start_rejected(self, api):
        """PRD §3.6: "The `service_date` ... must fall inside the authorization's closed
        validity window from `validity_start` through `validity_end`
        (`ERR_SERVICE_DATE_OUT_OF_WINDOW`)."

        Design: Corner/validations/service_date_temporal_checks
        """
        scenario = self._scenario()
        assert scenario["auth"]["validity_start"] == "2026-08-01"
        resp = api.create_claim(
            create_claim_payload(
                scenario["auth"]["id"],
                scenario["drug"]["id"],
                scenario["drug"]["j_code"],
                service_date="2026-07-31",
            ),
            scenario["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_WINDOW, 422)

    def test_future_service_date_rejected(self, api):
        """PRD §3.6: "The `service_date` must not be later than the current clock date
        (`ERR_FUTURE_SERVICE_DATE`)". At the startup clock 2026-08-01 (PRD §2.4), a
        service date of 2026-08-02 lies inside the validity window but in the future.

        Design: Corner/validations/service_date_temporal_checks
        """
        scenario = self._scenario()
        resp = api.create_claim(
            create_claim_payload(
                scenario["auth"]["id"],
                scenario["drug"]["id"],
                scenario["drug"]["j_code"],
                service_date="2026-08-02",
            ),
            scenario["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FUTURE_SERVICE_DATE, 422)


class TestSourcingDecision:
    def test_sourcing_rule_enforced_in_both_directions(self, api):
        """PRD §3.6: "`BUY_AND_BILL_ONLY` requires `sourcing_path` `BUY_AND_BILL`,
        `SPECIALTY_PHARMACY_ONLY` forbids that path, and `EITHER` accepts both —
        violations fail with `ERR_SOURCING_VIOLATION`".

        Design: Corner/validations/sourcing_rule_both_directions
        """
        bb = setup_approved_scenario(
            drug_overrides={
                "j_code": "J5700",
                "drug_name": "BBDrug",
                "sourcing_rule": "BUY_AND_BILL_ONLY",
            },
            member_id="MEM-V3",
            max_administrations=6,
        )
        sp = setup_approved_scenario(
            drug_overrides={
                "j_code": "J5701",
                "drug_name": "SPDrug",
                "sourcing_rule": "SPECIALTY_PHARMACY_ONLY",
            },
            member_id="MEM-V4",
            max_administrations=6,
        )
        provider = bb["provider"]
        rep = make_provider_rep_headers(provider["id"])

        resp = api.create_claim(
            create_claim_payload(
                bb["auth"]["id"], bb["drug"]["id"], "J5700", sourcing_path="WHITE_BAG"
            ),
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_SOURCING_VIOLATION, 422)

        resp = api.create_claim(
            create_claim_payload(
                sp["auth"]["id"], sp["drug"]["id"], "J5701", sourcing_path="BUY_AND_BILL"
            ),
            sp["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SOURCING_VIOLATION, 422)

        ok = validate_success(
            api.create_claim(
                create_claim_payload(
                    sp["auth"]["id"], sp["drug"]["id"], "J5701", sourcing_path="WHITE_BAG"
                ),
                sp["rep_headers"],
            ),
            201,
        )
        assert ok["status"] == "APPROVED_FOR_PAYMENT"
        assert ok["allowed_amount_cents"] == 5300


class TestJwWasteCompliance:
    def test_jw_waste_compliance_trio(self, api):
        """PRD §3.6: "Reporting `waste_units` above zero without setting `jw_modifier`
        fails with `ERR_JW_MODIFIER_REQUIRED`. Setting `jw_modifier` while reporting zero
        `waste_units` fails with `ERR_JW_WITHOUT_WASTE`. Reporting waste on a drug whose
        `single_dose_vial` is false fails with `ERR_WASTE_NOT_PAYABLE_MULTIDOSE`."

        Design: Corner/validations/jw_waste_compliance_trio
        """
        sd = setup_approved_scenario(
            drug_overrides={"j_code": "J5800", "drug_name": "SDDrug"},
            member_id="MEM-V5",
            max_administrations=6,
        )
        md = setup_approved_scenario(
            drug_overrides={
                "j_code": "J5801",
                "drug_name": "MDDrug",
                "single_dose_vial": False,
            },
            member_id="MEM-V6",
            max_administrations=6,
        )
        rep = sd["rep_headers"]

        # waste > 0 without the JW modifier.
        resp = api.create_claim(
            create_claim_payload(
                sd["auth"]["id"], sd["drug"]["id"], "J5800",
                waste_units=2, jw_modifier=False,
            ),
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_JW_MODIFIER_REQUIRED, 422)

        # JW modifier set with zero waste.
        resp = api.create_claim(
            create_claim_payload(
                sd["auth"]["id"], sd["drug"]["id"], "J5800",
                waste_units=0, jw_modifier=True,
            ),
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_JW_WITHOUT_WASTE, 422)

        # Any waste on a multi-dose vial drug.
        resp = api.create_claim(
            create_claim_payload(
                md["auth"]["id"], md["drug"]["id"], "J5801",
                waste_units=2, jw_modifier=True,
            ),
            md["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WASTE_NOT_PAYABLE_MULTIDOSE, 422)


class TestWasteBoundary:
    def _scenario(self):
        return setup_approved_scenario(
            drug_overrides={"j_code": "J3000", "drug_name": "WasteDrug"},
            member_id="MEM-10",
        )

    def test_waste_equal_to_vial_capacity_rejected(self, api):
        """PRD §3.6: "because a whole vial or more can never be discarded as waste,
        `waste_units` must be strictly less than the number of billing units in one vial —
        `vial_size_mg` divided by `billing_unit_mg` — or the claim fails with
        `ERR_WASTE_EXCEEDS_VIAL`." Vial capacity here is 100 / 10 = 10 units.

        Design: Difficulty/boundary_precision_check/waste_units_strict_less_than_vial
        """
        scenario = self._scenario()
        resp = api.create_claim(
            create_claim_payload(
                scenario["auth"]["id"], scenario["drug"]["id"], "J3000",
                waste_units=10, jw_modifier=True,  # == capacity: rejected
            ),
            scenario["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WASTE_EXCEEDS_VIAL, 422)

    def test_waste_one_below_capacity_accepted(self, api):
        """PRD §3.6: "`waste_units` must be strictly less than the number of billing units
        in one vial". Pricing (PRD §3.6): per-component rounding —
        round(10 x 500 x 1.06) = 5300 plus round(9 x 500 x 1.06) = 4770 -> 10070.

        Design: Difficulty/boundary_precision_check/waste_units_strict_less_than_vial
        """
        scenario = self._scenario()
        claim = validate_success(
            api.create_claim(
                create_claim_payload(
                    scenario["auth"]["id"], scenario["drug"]["id"], "J3000",
                    waste_units=9, jw_modifier=True,  # capacity - 1: accepted
                ),
                scenario["rep_headers"],
            ),
            201,
        )
        assert claim["status"] == "APPROVED_FOR_PAYMENT"
        assert claim["payable_waste_units"] == 9
        assert claim["allowed_amount_cents"] == 10070


class TestDoseToleranceFork:
    def test_overage_beyond_tolerance_rejected_without_persisting(self, api):
        """PRD §3.6: "An overage beyond tolerance is rejected outright with
        `ERR_DOSE_EXCEEDS_APPROVED`: the boundary is exact, so a claim is rejected
        precisely when ten times the administered milligrams is greater than eleven times
        the approved milligrams, while equality still pends." 12 units = 120 mg vs
        approved 100 mg: 120 x 10 = 1200 > 100 x 11 = 1100.

        Design: Corner/validations/dose_overage_hard_error
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J5900", "drug_name": "OverDrug"},
            member_id="MEM-V7",
        )
        resp = api.create_claim(
            create_claim_payload(
                scenario["auth"]["id"], scenario["drug"]["id"], "J5900", billed_units=12
            ),
            scenario["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOSE_EXCEEDS_APPROVED, 422)

        # The rejected claim is not persisted, and no administration is debited.
        assert list_claims_for_auth(scenario["auth"]["id"]) == []
        assert get_auth(scenario["auth"]["id"])["administrations_used"] == 0


class TestAspRateExistence:
    def test_claim_without_any_effective_rate_rejected(self, api):
        """PRD §3.6: "The ASP rate resolves for the `service_date` per §3.3; if no
        schedule of the drug is effective yet, adjudication fails with `ERR_NO_ASP_RATE`."
        PRD §3.3: "The rate that prices any given service date is the `asp_rate_cents` of
        that drug's schedule with the greatest `effective_start` on or before the service
        date" — here the only schedule starts 2026-09-01, after the 2026-08-01 service
        date, so no rate exists.

        Design: Corner/validations/no_asp_rate_for_service_date
        """
        backbone = setup_drug_with_policy(
            drug_overrides={"j_code": "J6000", "drug_name": "NoRateDrug"},
            with_rate=False,
        )
        publish_rate(backbone["drug"]["id"], asp_rate_cents=500, effective_start="2026-09-01")
        provider = create_provider(name="NoRate Provider")
        auth = approve_auth(
            submit_auth(backbone["drug"]["id"], provider["id"], "MEM-V8")["id"], 4
        )
        resp = api.create_claim(
            create_claim_payload(auth["id"], backbone["drug"]["id"], "J6000"),
            make_provider_rep_headers(provider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ASP_RATE, 422)


class TestGateOrderingStateBeforeFiscal:
    def test_suspended_auth_claim_reports_state_error_not_fiscal(self, api):
        """PRD §2.8: "Every request is evaluated against an ordered pipeline, and an
        earlier failure masks later ones — the first failing stage determines the error
        returned." Cross-entity state gates ("a claim requires an `APPROVED`
        authorization") precede the fiscal gates, so a 250 mg claim (beyond the 110 mg
        tolerance of the approved 100 mg) against a SUSPENDED auth reports
        `ERR_AUTH_NOT_APPROVED`, not `ERR_DOSE_EXCEEDS_APPROVED`.

        Design: Difficulty/priority_pair_validation_conflict/claim_state_vs_fiscal_priority
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J2800", "drug_name": "PrioDrugA"},
            member_id="MEM-8",
        )
        suspended = validate_success(api.suspend_auth(scenario["auth"]["id"], MPO))
        assert suspended["status"] == "SUSPENDED"

        resp = api.create_claim(
            create_claim_payload(
                scenario["auth"]["id"], scenario["drug"]["id"], "J2800", billed_units=25
            ),
            scenario["rep_headers"],
        )
        # State gate (stage 8) masks the fiscal tolerance gate (stage 13).
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED, 409)

    def test_fiscal_tolerance_gate_fires_when_state_passes(self, api):
        """PRD §3.6: "These fiscal gates — rate existence and the tolerance boundary —
        guard both the initial adjudication and the medical override decision below.";
        "a claim is rejected precisely when ten times the administered milligrams is
        greater than eleven times the approved milligrams" (250 x 10 > 100 x 11).

        Design: Difficulty/priority_pair_validation_conflict/claim_state_vs_fiscal_priority
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J2801", "drug_name": "PrioDrugA2"},
            member_id="MEM-8B",
        )
        resp = api.create_claim(
            create_claim_payload(
                scenario["auth"]["id"], scenario["drug"]["id"], "J2801", billed_units=25
            ),
            scenario["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOSE_EXCEEDS_APPROVED, 422)
        assert get_auth(scenario["auth"]["id"])["administrations_used"] == 0
