"""Cargo damage claims: provisional share, segregation, fault-weighted final liability."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_damage_claim,
    decide_claim,
    make_adjuster_headers,
    make_foreman_headers,
    report_claim,
    setup_placed_gang,
    setup_working_gang,
    settle_claim,
    register_worker,
    validate_error,
    validate_success,
    api_client,
)

ADJUSTER = TEST_USERS["adjuster_headers"]
HOLDMAN_SPEC = {"full_name": "W One", "registration_number": "R001",
                "classification": "HOLDMAN", "registered_on": "2010-01-01",
                "base_hourly_rate_cents": 4000}


def get_claim(api, claim_id):
    from test_helpers import get_success_data
    return get_success_data(api_client.get_damage_claim(claim_id, ADJUSTER))


class TestClaimDualVariant:

    def _setup_reported_10m_claim(self):
        """WORKING gang (W1 checked in); claim of 10,000,000 cents reported by
        foreman W1."""
        ns = setup_working_gang(
            vessel_overrides={"vessel_name": "MV Claim", "voyage_number": "C-201",
                              "planned_moves": 100, "planned_tons": 50,
                              "credit_limit_cents": 500_000_000},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMAN_SPEC)])
        claim = report_claim(ns.gang["id"], ns.foreman_id,
                             cargo_ref="MSKU-123456",
                             damage_description="Crushed container corner post",
                             estimated_amount_cents=10_000_000)
        return ns, claim

    def test_claim_provisional_share_is_flat_half(self, api):
        """PRD §3.7: "a provisional exposure is computed immediately — `provisional_stevedore_share_cents` is one half of the estimated amount, rounded half up to integer cents, with no cap and no deductible at this stage."
        PRD §3.7: "The claim is born `REPORTED`; the acting foreman's `X-User-ID` is recorded as `reported_by_worker_id` and anchors the segregation rule"

        Design: Difficulty/dual_variant_calc/claim_provisional_5050_vs_fault_weighted
        """
        ns, claim = self._setup_reported_10m_claim()
        assert_damage_claim(claim)
        assert claim["status"] == "REPORTED"
        assert claim["provisional_stevedore_share_cents"] == 5_000_000, (
            "round_half_up(10000000 * 0.50)")
        assert claim["reported_by_worker_id"] == ns.foreman_id

    def test_claim_final_liability_is_fault_weighted(self, api):
        """PRD §3.7: "The final liability is computed in a pinned evaluation order: first the estimated amount is multiplied by the fault percentage and divided by one hundred, rounded half up to integer cents; then that figure is capped at 25,000,000 cents — a quarter-million dollars; then a deductible of 50,000 cents — five hundred dollars — is subtracted, with the result floored at zero."
        PRD §3.7: "the provisional share remains on the record as the historical estimate, superseded by the final figure."

        Design: Difficulty/dual_variant_calc/claim_provisional_5050_vs_fault_weighted
        """
        ns, claim = self._setup_reported_10m_claim()
        decided = validate_success(decide_claim(claim["id"], "ACCEPTED",
                                                adjuster_user_id="adj-1",
                                                fault_pct=60))
        assert decided["status"] == "ACCEPTED"
        assert decided["decided_by_user_id"] == "adj-1"

        settled = settle_claim(claim["id"], "adj-1")
        assert settled["status"] == "SETTLED"
        # max(0, min(round(10000000 * 60 / 100), 25000000) - 50000)
        assert settled["final_stevedore_liability_cents"] == 5_950_000
        assert settled["provisional_stevedore_share_cents"] == 5_000_000, (
            "provisional stays as the historical estimate")
        assert settled["provisional_stevedore_share_cents"] != \
            settled["final_stevedore_liability_cents"]


class TestClaimLiabilityClamps:

    def test_claim_liability_cap_and_deductible_floor(self, api):
        """PRD §3.7: "The final liability is computed in a pinned evaluation order: first the estimated amount is multiplied by the fault percentage and divided by one hundred, rounded half up to integer cents; then that figure is capped at 25,000,000 cents — a quarter-million dollars; then a deductible of 50,000 cents — five hundred dollars — is subtracted, with the result floored at zero."

        Design: Corner/calculations/claim_liability_cap_and_deductible_floor
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Clamp", "voyage_number": "C-208"})
        w1 = register_worker(**dict(HOLDMAN_SPEC))
        big = report_claim(ns.gang["id"], w1["id"], cargo_ref="BIG-1",
                           damage_description="Reefer unit destroyed",
                           estimated_amount_cents=100_000_000)
        small = report_claim(ns.gang["id"], w1["id"], cargo_ref="SML-1",
                             damage_description="Scratched paint",
                             estimated_amount_cents=100_000)
        validate_success(decide_claim(big["id"], "ACCEPTED",
                                      adjuster_user_id="adj-1", fault_pct=100))
        validate_success(decide_claim(small["id"], "ACCEPTED",
                                      adjuster_user_id="adj-1", fault_pct=30))

        big_settled = settle_claim(big["id"], "adj-1")
        # raw 100,000,000 -> capped at 25,000,000 -> minus 50,000 deductible
        assert big_settled["final_stevedore_liability_cents"] == 24_950_000

        small_settled = settle_claim(small["id"], "adj-1")
        # raw 30,000 -> minus 50,000 deductible -> floored at 0
        assert small_settled["final_stevedore_liability_cents"] == 0


class TestClaimDecideGuards:

    def test_claim_second_decide_rejected(self, api):
        """PRD §3.7: "Adjudication belongs to the `ClaimsAdjuster`, acting on a `REPORTED` claim with a `decision` of `ACCEPTED` or `DENIED`."
        PRD §2.5: "The target entity's current state permits the requested operation. The generic failure is `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/claim_second_decide_rejected
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Idem", "voyage_number": "S-106"})
        w1 = register_worker(**dict(HOLDMAN_SPEC))
        claim = report_claim(ns.gang["id"], w1["id"], cargo_ref="MSKU-9",
                             damage_description="Dent",
                             estimated_amount_cents=200_000)
        validate_success(decide_claim(claim["id"], "ACCEPTED",
                                      adjuster_user_id="adj-1", fault_pct=40))

        second = decide_claim(claim["id"], "DENIED", adjuster_user_id="adj-2")
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

        after = get_claim(api, claim["id"])
        assert after["status"] == "ACCEPTED"
        assert after["fault_pct"] == 40

    def test_claim_decide_by_reporting_foreman_violates_segregation(self, api):
        """PRD §3.7: "The deciding adjuster's `X-User-ID` must differ from `reported_by_worker_id` — an adjuster may not adjudicate a claim they themselves reported — and a collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/validations/claim_decide_by_reporting_foreman_violates_segregation
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Sod1", "voyage_number": "V-301"})
        w1 = register_worker(**dict(HOLDMAN_SPEC))
        claim = report_claim(ns.gang["id"], w1["id"], cargo_ref="MSKU-1",
                             damage_description="Crushed door",
                             estimated_amount_cents=300_000)

        # ClaimsAdjuster role carrying the reporting worker's id.
        resp = api_client.decide_damage_claim(
            claim["id"], {"decision": "ACCEPTED", "fault_pct": 50},
            make_adjuster_headers(w1["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_claim(api, claim["id"])["status"] == "REPORTED"

    def test_fault_pct_outside_0_100_returns_400(self, api):
        """PRD §3.7: "And an `ACCEPTED` decision must carry a `fault_pct`, the stevedore's fault percentage as an integer from 0 to 100 inclusive; a missing or out-of-range value is rejected with `ERR_FAULT_PCT_OUT_OF_RANGE` (400). A `DENIED` decision needs no fault percentage."

        Design: Corner/validations/fault_pct_outside_0_100_returns_400
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Fault", "voyage_number": "V-309"})
        w1 = register_worker(**dict(HOLDMAN_SPEC))
        claim = report_claim(ns.gang["id"], w1["id"], cargo_ref="MSKU-2",
                             damage_description="Bent twistlock",
                             estimated_amount_cents=80_000)

        out_of_range = decide_claim(claim["id"], "ACCEPTED",
                                    adjuster_user_id="adj-1", fault_pct=101)
        validate_error(out_of_range, ApiErrorId.ERR_FAULT_PCT_OUT_OF_RANGE)

        missing = api_client.decide_damage_claim(
            claim["id"], {"decision": "ACCEPTED"}, ADJUSTER)
        validate_error(missing, ApiErrorId.ERR_FAULT_PCT_OUT_OF_RANGE)

        assert get_claim(api, claim["id"])["status"] == "REPORTED"
