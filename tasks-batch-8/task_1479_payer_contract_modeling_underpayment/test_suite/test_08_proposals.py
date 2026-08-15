"""Renegotiation proposals: OCC create, volume modeling, negotiation cycle,
acceptance cascade (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_claim_line,
    create_accept_proposal_payload,
    create_amendment,
    create_contract_proposal_payload,
    create_proposal,
    create_test_claim,
    get_contract,
    get_proposal,
    make_finance_director_headers,
    price_claim,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CA, CM


class TestProposalModelingVariants:
    """SAME_STORE vs MIX_SHIFTED on identical inputs (PRD §3.8)."""

    def _setup_modeled_proposal(self, api):
        """CASE_RATE 500000 contract with one trailing priced claim (T=1);
        proposal at 550000 with a projected mix of 4 units."""
        ctx = setup_active_contract(
            service_category="OUTPATIENT_SURGERY",
            rate_model="CASE_RATE",
            base_rate_cents=500000,
            contract_overrides={"contract_code": "PM-2026"},
        )
        claim = create_test_claim(
            ctx["payer"]["id"],
            claim_number="CL-PM1",
            service_category="OUTPATIENT_SURGERY",
            admission_date="2026-06-03",
            discharge_date="2026-06-03",
            total_billed_charges_cents=700000,
        )
        add_claim_line(
            claim["id"], revenue_code="0360", service_date="2026-06-03",
            charge_cents=700000,
        )
        price_claim(claim["id"])
        proposal = create_proposal(
            ctx["contract"]["id"],
            ctx["contract_version"],
            projected_volume_mix=[
                {"service_category": "OUTPATIENT_SURGERY", "annual_units": 4}
            ],
        )
        modeled = validate_success(api.run_proposal_model(proposal["id"], CA))
        ctx["proposal"] = modeled
        return ctx

    def test_same_store_variant_isolates_pure_rate_effect(self, api):
        """PRD §3.8: "The same-store variant holds volume at trailing actuals
        on both sides to isolate the pure rate effect:
        `baseline_same_store_cents` sums trailing units times current unit
        rates across categories, the modeled figure sums trailing units times
        proposed unit rates, and `delta_same_store_cents` is the modeled
        figure minus the baseline."

        Design: Difficulty/dual_variant_calc/proposal_same_store_vs_mix_shifted_diverge
        """
        ctx = self._setup_modeled_proposal(api)
        proposal = ctx["proposal"]
        assert proposal["status"] == "MODELED"
        # T=1 trailing case: baseline 1 x 500000; delta 1 x (550000-500000).
        assert proposal["baseline_same_store_cents"] == 500000
        assert proposal["delta_same_store_cents"] == 50000

    def test_mix_shifted_variant_applies_projected_volume(self, api):
        """PRD §3.8: "The mix-shifted variant applies the projected volume mix
        on both sides, conflating rate and mix effects:
        `baseline_mix_shifted_cents` sums mix volumes times current unit
        rates, its modeled counterpart sums mix volumes times proposed unit
        rates, and `delta_mix_shifted_cents` is that modeled figure minus its
        baseline." and "The two variants run on identical inputs and are
        always both stored; they diverge exactly when the projected mix
        differs from trailing actuals."

        Design: Difficulty/dual_variant_calc/proposal_same_store_vs_mix_shifted_diverge
        """
        ctx = self._setup_modeled_proposal(api)
        proposal = ctx["proposal"]
        # mix=4: baseline 4 x 500000 = 2000000; delta 4 x 50000 = 200000.
        assert proposal["baseline_mix_shifted_cents"] == 2000000
        assert proposal["delta_mix_shifted_cents"] == 200000
        assert proposal["delta_same_store_cents"] != proposal[
            "delta_mix_shifted_cents"
        ]
        # run_model pins the contract version it was modeled against.
        contract = get_contract(ctx["contract"]["id"])
        assert proposal["modeled_contract_version"] == contract["version"]


class TestProposalNegotiationCycle:
    """SUBMITTED -> COUNTERED -> SUBMITTED loop counts rounds (PRD §3.8)."""

    def _setup_modeled(self, api):
        ctx = setup_active_contract(
            service_category="OUTPATIENT_SURGERY",
            rate_model="CASE_RATE",
            base_rate_cents=500000,
            contract_overrides={"contract_code": "NG-2026"},
        )
        proposal = create_proposal(ctx["contract"]["id"], ctx["contract_version"])
        ctx["proposal"] = validate_success(api.run_proposal_model(proposal["id"], CA))
        return ctx

    def test_first_submit_enters_submitted_at_round_one(self, api):
        """PRD §3.8: "A successful create opens the proposal in `DRAFT` with
        `round_number` 1" and "Recording a payer counter-offer, another
        manager act, moves a `SUBMITTED` proposal to `COUNTERED`."

        Design: Difficulty/non_linear_state_machine/proposal_countered_resubmit_cycle_increments_round
        """
        ctx = self._setup_modeled(api)
        submitted = validate_success(api.submit_proposal(ctx["proposal"]["id"], CM))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["round_number"] == 1
        countered = validate_success(
            api.record_proposal_counter(ctx["proposal"]["id"], CM)
        )
        assert countered["status"] == "COUNTERED"

    def test_resubmit_after_counter_increments_round(self, api):
        """PRD §3.8: "Submission by a `ContractManager` — from `MODELED`, and
        again from `COUNTERED` on resubmission — requires the contract to be
        `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the proposal fresh
        (`ERR_PROPOSAL_STALE`); resubmission from `COUNTERED` also increments
        `round_number`."

        Design: Difficulty/non_linear_state_machine/proposal_countered_resubmit_cycle_increments_round
        """
        ctx = self._setup_modeled(api)
        validate_success(api.submit_proposal(ctx["proposal"]["id"], CM))
        validate_success(api.record_proposal_counter(ctx["proposal"]["id"], CM))
        resubmitted = validate_success(api.submit_proposal(ctx["proposal"]["id"], CM))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["round_number"] == 2


class TestProposalGuardsAndSupersede:
    def test_proposal_stale_on_submit(self, api):
        """PRD §3.8: "`is_stale` is true whenever a proposal in `MODELED`,
        `SUBMITTED`, or `COUNTERED` was modeled against a contract `version`
        that no longer matches the contract's current `version`." and
        submission requires "the proposal fresh (`ERR_PROPOSAL_STALE`)".

        Design: Corner/errors/err_proposal_stale_on_submit
        """
        ctx = setup_active_contract(
            service_category="OUTPATIENT_SURGERY",
            rate_model="CASE_RATE",
            base_rate_cents=500000,
            contract_overrides={"contract_code": "ST-2026"},
        )
        proposal = create_proposal(ctx["contract"]["id"], ctx["contract_version"])
        validate_success(api.run_proposal_model(proposal["id"], CA))
        # Any contract version bump after run_model makes the model stale.
        cv2 = get_contract(ctx["contract"]["id"])["version"]
        create_amendment(
            ctx["contract"]["id"],
            cv2,
            effective_date="2026-09-01",
            term_overrides=[
                {"service_category": "OUTPATIENT_SURGERY", "base_rate_cents": 510000}
            ],
        )
        resp = api.submit_proposal(proposal["id"], CM)
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_STALE.value)
        proposal_after = get_proposal(proposal["id"])
        assert proposal_after["status"] == "MODELED"
        assert proposal_after["is_stale"] is True

    def test_proposal_create_stale_version_rejected(self, api):
        """PRD §2.7: "Two creation endpoints guard their parent contract with
        optimistic concurrency: creating a rate amendment, and creating a
        renegotiation proposal." and "If that value does not equal the
        contract's current `version` — for example because another writer
        advanced the contract since the client last read it — the request is
        rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/xc_proposal_create_stale_version_rejected
        """
        ctx = setup_active_contract(
            service_category="OUTPATIENT_SURGERY",
            rate_model="CASE_RATE",
            base_rate_cents=500000,
            contract_overrides={"contract_code": "OP-2026"},
        )
        stale_version = ctx["contract_version"]
        p1 = create_proposal(ctx["contract"]["id"], stale_version)
        assert p1["status"] == "DRAFT"
        resp = api.create_contract_proposal(
            create_contract_proposal_payload(
                ctx["contract"]["id"],
                stale_version,
                proposed_terms=[
                    {
                        "service_category": "OUTPATIENT_SURGERY",
                        "rate_model": "CASE_RATE",
                        "base_rate_cents": 560000,
                    }
                ],
                projected_volume_mix=[
                    {"service_category": "OUTPATIENT_SURGERY", "annual_units": 3}
                ],
            ),
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)
        # A failed create must not withdraw the still-open proposal.
        assert get_proposal(p1["id"])["status"] == "DRAFT"

    def test_new_proposal_withdraws_prior_open(self, api):
        """PRD §3.8: "A successful create opens the proposal in `DRAFT` with
        `round_number` 1, withdraws the contract's prior open proposal — any
        predecessor still `DRAFT`, `MODELED`, `SUBMITTED`, or `COUNTERED`
        moves to `WITHDRAWN` with a version bump — and increments the
        contract's `version`, which is precisely why the guard exists."

        Design: Corner/endpoints/ep_new_proposal_withdraws_prior_open
        """
        ctx = setup_active_contract(
            service_category="OUTPATIENT_SURGERY",
            rate_model="CASE_RATE",
            base_rate_cents=500000,
            contract_overrides={"contract_code": "NP-2026"},
        )
        p1 = create_proposal(ctx["contract"]["id"], ctx["contract_version"])
        cv2 = get_contract(ctx["contract"]["id"])["version"]
        p2 = create_proposal(
            ctx["contract"]["id"],
            cv2,
            proposed_terms=[
                {
                    "service_category": "OUTPATIENT_SURGERY",
                    "rate_model": "CASE_RATE",
                    "base_rate_cents": 560000,
                }
            ],
            projected_volume_mix=[
                {"service_category": "OUTPATIENT_SURGERY", "annual_units": 3}
            ],
        )
        assert p2["status"] == "DRAFT"
        assert get_proposal(p1["id"])["status"] == "WITHDRAWN"


class TestProposalAcceptance:
    def test_accept_proposal_materializes_successor_contract(self, api):
        """PRD §3.8: acceptance "is the moment the deal becomes real: the
        system materializes the successor contract in `DRAFT`, taking
        `contract_code` from the supplied `successor_contract_code`, its
        window from `successor_effective_date` and
        `successor_expiration_date`, chaining `prior_contract_id` to the
        current contract, copying the current contract's
        `underpayment_threshold_cents`, `underpayment_threshold_bp`, and
        `volume_tiers`, and minting one contract term per `proposed_terms`
        entry."

        Design: Corner/endpoints/ep_accept_proposal_materializes_successor_contract
        """
        ctx = setup_active_contract(
            service_category="OUTPATIENT_SURGERY",
            rate_model="CASE_RATE",
            base_rate_cents=500000,
            contract_overrides={"contract_code": "AP-2026"},
        )
        proposal = create_proposal(ctx["contract"]["id"], ctx["contract_version"])
        validate_success(api.run_proposal_model(proposal["id"], CA))
        validate_success(api.submit_proposal(proposal["id"], CM))
        accepted = validate_success(
            api.accept_proposal(
                proposal["id"],
                create_accept_proposal_payload(
                    successor_contract_code="AP-2027",
                    successor_effective_date="2027-01-01",
                    successor_expiration_date="2027-12-31",
                ),
                make_finance_director_headers("fd-1"),
            )
        )
        assert accepted["status"] == "ACCEPTED"

        successors, _meta = validate_paginated(
            api.list_payer_contracts(
                make_finance_director_headers("fd-1"),
                params={"prior_contract_id": ctx["contract"]["id"]},
            )
        )
        assert len(successors) == 1
        successor = successors[0]
        assert successor["status"] == "DRAFT"
        assert successor["contract_code"] == "AP-2027"
        assert successor["effective_date"] == "2027-01-01"
        assert successor["expiration_date"] == "2027-12-31"

        terms, _meta2 = validate_paginated(
            api.list_contract_terms(
                make_finance_director_headers("fd-1"),
                params={"contract_id": successor["id"]},
            )
        )
        assert len(terms) == 1
        assert terms[0]["service_category"] == "OUTPATIENT_SURGERY"
        assert terms[0]["rate_model"] == "CASE_RATE"
        assert terms[0]["base_rate_cents"] == 550000
