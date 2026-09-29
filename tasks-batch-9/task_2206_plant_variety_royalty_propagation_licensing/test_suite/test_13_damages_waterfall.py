"""Allocating an enforcement recovery across the three declared buckets."""

from test_helpers import (
    AUDITOR,
    OFFICER,
    ApiErrorId,
    assert_damages_waterfall_conservation,
    create_genetic_test_payload,
    create_propagator,
    create_variety,
    resolve_case_payload,
    sampled_case,
    validate_error,
    validate_success,
)


def _case_concluded_without_a_match(api, denomination, breeder_code, propagator_name,
                                    market_survey_ref, sampled_unit_count,
                                    match_confidence, lab_code, marker_panel):
    """A case carried to NO_MATCH, so no compliance penalty confuses the money."""
    variety = create_variety(
        api, denomination=denomination, species="Rubus idaeus",
        breeder_code=breeder_code, base_royalty_cents_per_plant=35,
        base_royalty_cents_per_acre=1200,
    )
    propagator = create_propagator(
        api, legal_name=propagator_name, home_territory_code="US-ID"
    )
    case = sampled_case(
        api, variety["id"], sampled_unit_count=sampled_unit_count,
        suspected_propagator_id=propagator["id"],
        market_survey_ref=market_survey_ref,
    )
    validate_success(
        api.create_genetic_test(
            case["id"],
            create_genetic_test_payload(
                match_confidence, lab_code=lab_code, marker_panel=marker_panel
            ),
            AUDITOR,
        ),
        201,
    )
    concluded = validate_success(api.conclude_testing(case["id"], AUDITOR))
    return {"variety": variety, "propagator": propagator,
            "propagator_id": propagator["id"], "case_id": case["id"],
            "case": concluded}


class TestTheWaterfallFillsEnforcementBeforeTheBreederPool:
    """A recovery of 1000000 against costs of 150000, split three ways."""

    def _resolvable_case(self, api):
        return _case_concluded_without_a_match(
            api, "Cinder Bramble", "CB", "Cinder Ridge Nursery", "MS-2026-050",
            30, 0.4000, "GENLAB", "SSR-16",
        )

    def test_the_first_bucket_takes_the_documented_enforcement_cost(self, api):
        """The enforcement bucket fills before anything else and takes the smaller
        of the recovery and the cost, which here is the whole cost.

        PRD 3.9: "The first bucket, `enforcement_recovery_cents`, fills first and is the smaller of `recovered_damages_cents` and `enforcement_cost_cents` — enforcement cost is recovered before anything else, but never beyond what actually came in."

        Design: Corner/calculations/damages_waterfall_fills_the_enforcement_bucket_before_the_breeder_pool
        """
        setup = self._resolvable_case(api)
        assert setup["case"]["status"] == "NO_MATCH"

        resolved = validate_success(
            api.resolve_surveillance_case(
                setup["case_id"], resolve_case_payload(1000000, 150000), AUDITOR
            )
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["enforcement_recovery_cents"] == 150000

    def test_the_breeder_share_is_taken_on_the_gross_recovery(self, api):
        """Seventy percent of the gross 1000000 is 700000, which is smaller than
        the 850000 remainder, so the pool takes the target rather than the whole
        remainder, and the residue absorbs the difference exactly.

        PRD 3.9: "Note carefully that the 70 percent target is a share of the **gross** recovery, not of the remainder."

        Design: Corner/calculations/damages_waterfall_fills_the_enforcement_bucket_before_the_breeder_pool
        """
        setup = self._resolvable_case(api)

        resolved = validate_success(
            api.resolve_surveillance_case(
                setup["case_id"], resolve_case_payload(1000000, 150000), AUDITOR
            )
        )
        assert resolved["breeder_pool_cents"] == 700000
        assert resolved["propagator_credit_cents"] == 150000
        assert resolved["recovered_damages_cents"] == 1000000
        assert_damages_waterfall_conservation(resolved)

    def test_the_residue_credits_the_named_suspect_outside_the_royalty_ledger(self, api):
        """The third bucket lands on the named propagator's damages credit, which is
        kept away from the royalty ledger, and a no-match case carries no penalty
        so the compliance score is untouched.

        PRD 3.9: "When the case names a `suspected_propagator_id`, `propagator_credit_cents` is added to that propagator's `damages_credit_cents` and the propagator's `version` increments by 1; with no named suspect no credit is applied and no propagator is touched."

        Design: Corner/calculations/damages_waterfall_fills_the_enforcement_bucket_before_the_breeder_pool
        """
        setup = self._resolvable_case(api)

        validate_success(
            api.resolve_surveillance_case(
                setup["case_id"], resolve_case_payload(1000000, 150000), AUDITOR
            )
        )

        propagator = validate_success(api.get_propagator(setup["propagator_id"], OFFICER))
        assert propagator["damages_credit_cents"] == 150000
        assert propagator["royalty_payable_cents"] == 0
        assert propagator["royalty_settled_cents"] == 0
        assert propagator["compliance_score"] == 100


class TestTheWaterfallNeverGoesNegative:
    """Costs of 150000 against a recovery of only 100000."""

    def _resolvable_case(self, api):
        return _case_concluded_without_a_match(
            api, "Dovetail Bramble", "DB", "Dovetail Nursery", "MS-2026-051",
            12, 0.3000, "WESTLAB", "SNP-8",
        )

    def test_the_first_bucket_is_capped_by_what_actually_came_in(self, api):
        """The enforcement bucket cannot exceed the recovery, so it takes the whole
        100000 rather than the 150000 that was spent, and the two later buckets are
        zero rather than negative.

        PRD 3.9: "When enforcement costs exceed the recovery, the first bucket takes the entire recovery, the first remainder is 0, and the second and third buckets are both 0 — the enforcement cost is simply only partly recovered."

        Design: Corner/calculations/damages_waterfall_overflow_leaves_the_later_buckets_at_zero
        """
        setup = self._resolvable_case(api)

        resolved = validate_success(
            api.resolve_surveillance_case(
                setup["case_id"], resolve_case_payload(100000, 150000), AUDITOR
            )
        )
        assert resolved["enforcement_recovery_cents"] == 100000
        assert resolved["breeder_pool_cents"] == 0
        assert resolved["propagator_credit_cents"] == 0
        assert_damages_waterfall_conservation(resolved)

    def test_a_zero_residue_credits_nothing_to_the_named_suspect(self, api):
        """With nothing left in the third bucket the named propagator's damages
        credit stays empty, yet the case does name a suspect, so the credit limb
        still runs against that propagator and its `version` moves by exactly one.

        PRD 3.9: "When the case names a `suspected_propagator_id`, `propagator_credit_cents` is added to that propagator's `damages_credit_cents` and the propagator's `version` increments by 1; with no named suspect no credit is applied and no propagator is touched."

        Design: Corner/calculations/damages_waterfall_overflow_leaves_the_later_buckets_at_zero
        """
        setup = self._resolvable_case(api)
        before = validate_success(api.get_propagator(setup["propagator_id"], OFFICER))

        validate_success(
            api.resolve_surveillance_case(
                setup["case_id"], resolve_case_payload(100000, 150000), AUDITOR
            )
        )

        propagator = validate_success(api.get_propagator(setup["propagator_id"], OFFICER))
        assert propagator["damages_credit_cents"] == 0
        assert propagator["version"] == before["version"] + 1

    def test_a_resolved_case_cannot_be_resolved_again(self, api):
        """Resolution is the end of the case machine, so a second allocation over
        the same recovery is refused with the terminal code.

        PRD 3.9: "`RESOLVED` is the terminal state of the case machine."

        Design: Corner/calculations/damages_waterfall_overflow_leaves_the_later_buckets_at_zero
        """
        setup = self._resolvable_case(api)
        validate_success(
            api.resolve_surveillance_case(
                setup["case_id"], resolve_case_payload(100000, 150000), AUDITOR
            )
        )

        validate_error(
            api.resolve_surveillance_case(
                setup["case_id"], resolve_case_payload(100000, 150000), AUDITOR
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )
