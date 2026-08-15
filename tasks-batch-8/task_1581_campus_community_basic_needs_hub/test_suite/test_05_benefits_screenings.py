"""Benefits screenings: SNAP estimate step rounding, score gates, counselor
assignment selector, and the empty-pool rejection."""
from test_helpers import (
    ApiErrorId,
    create_active_client,
    create_coordinator,
    create_counselor,
    create_screening_payload,
    make_benefits_counselor_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client


def _snap_scenario():
    """Client with the pinned SNAP fixture assessment (hh=2, gross 150002,
    earned 77777, shelter 0, COST_BURDENED, food 3, one dependent) plus one
    counselor, and a SNAP screening ready to score."""
    _, coord = create_coordinator()
    _, couns = create_counselor()
    client, _, _ = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=2, monthly_income_cents=150002,
            earned_income_cents=77777, shelter_cost_cents=0,
            housing_status="COST_BURDENED", dependents_under_18=1,
            receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=3, consent_confidential=True,
        ),
        client_overrides={"alias_name": "fern", "contact_channel": "PHONE"},
    )
    screening = validate_success(
        api_client.create_screening(client["id"], create_screening_payload("SNAP"), couns), 201
    )
    return client, screening, couns


class TestSnapEstimatePinnedStepRounding:
    def test_snap_estimate_uses_pinned_per_step_rounding(self, api):
        """PRD §2.7: "the SNAP estimate rounds its earned deduction half-up to
        a whole cent, floors the half-of-adjusted-income divisor to a whole
        cent, and rounds the thirty-percent household share up to a whole
        cent, in that pinned order — computing unrounded intermediates and
        rounding only at the end is not permitted, because it yields different
        cents."
        PRD §3.4: "Step six takes thirty percent of net income, rounded up to
        a whole cent, as the household's expected share. Step seven subtracts
        that share from the maximum monthly allotment for the household size —
        29,200 cents for one person, 53,600 for two ... floored at zero."

        Design: Difficulty/combinatorial_formula/snap_estimate_pinned_step_rounding
        """
        _, screening, couns = _snap_scenario()
        scored = validate_success(
            api.score_screening(
                screening["id"],
                make_benefits_counselor_headers(screening["counselor_id"]),
            ),
            200,
        )
        # earned deduction 15555 (half-up on 77777*0.20); adjusted 114647;
        # net 114647; ceil(114647*0.30) == 34395; 53600 - 34395 == 19205.
        # Rounding the share half-up instead would yield 34394 -> 19206.
        assert scored["snap_estimate_cents"] == 19205

    def test_snap_score_and_band_from_weighted_blend(self, api):
        """PRD §3.4: "`SNAP` weighs income 0.6, food 0.3, housing 0.1 ...
        The raw score is the weighted blend, rounded half-up to an integer and
        clamped between 0 and 100 ... The resulting `score` lands in one of
        three bands with inclusive boundaries: 70 or higher is
        `LIKELY_ELIGIBLE`, 40 through 69 is `POSSIBLY_ELIGIBLE`, and below 40
        is `NOT_ELIGIBLE`; the band is recorded as `result_band`."

        Design: Difficulty/combinatorial_formula/snap_estimate_pinned_step_rounding
        """
        _, screening, couns = _snap_scenario()
        scored = validate_success(
            api.score_screening(
                screening["id"],
                make_benefits_counselor_headers(screening["counselor_id"]),
            ),
            200,
        )
        # ratio 0.8860 -> income_pts 55.7; food_pts 50; housing_pts 60;
        # 0.6*55.7 + 0.3*50 + 0.1*60 = 54.42 -> 54.
        assert scored["score"] == 54
        assert scored["result_band"] == "POSSIBLY_ELIGIBLE"


def test_screening_score_zero_gates_and_housing_ceiling(api):
    """PRD §3.4: "Three gates override the blend: a `CHILDCARE` screening for
    a household with zero `dependents_under_18` scores 0 outright; a `SNAP`
    screening for a client whose `receives_snap` is already true scores 0 —
    there is nothing to screen; and a `HOUSING` screening for a `STABLE`
    household is capped at the smaller of 39 and the raw score."

    Design: Corner/calculations/screening_score_zero_gates_and_housing_ceiling
    """
    _, coord = create_coordinator()
    _, couns = create_counselor()
    client_k, _, _ = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=2, monthly_income_cents=100000,
            housing_status="COST_BURDENED", dependents_under_18=0,
            receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=3, consent_confidential=True,
        ),
        client_overrides={"alias_name": "k"},
    )
    client_l, _, _ = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=1, monthly_income_cents=0,
            housing_status="STABLE", dependents_under_18=0,
            receives_snap=True, receives_childcare_subsidy=False,
            food_insecurity_score=6, consent_confidential=True,
        ),
        client_overrides={"alias_name": "l"},
    )
    sk = validate_success(
        api.create_screening(client_k["id"], create_screening_payload("CHILDCARE"), couns),
        201,
    )
    sl = validate_success(
        api.create_screening(client_l["id"], create_screening_payload("HOUSING"), couns),
        201,
    )
    scored_k = validate_success(
        api.score_screening(sk["id"], make_benefits_counselor_headers(sk["counselor_id"])),
        200,
    )
    scored_l = validate_success(
        api.score_screening(sl["id"], make_benefits_counselor_headers(sl["counselor_id"])),
        200,
    )
    assert scored_k["score"] == 0, "zero dependents gates CHILDCARE to 0"
    assert scored_k["result_band"] == "NOT_ELIGIBLE"
    # HOUSING on STABLE: raw 0.4*100 + 0.1*100 + 0.5*0 = 50 -> capped to 39.
    assert scored_l["score"] == 39, "raw 50 clamped by the STABLE ceiling"
    assert scored_l["result_band"] == "NOT_ELIGIBLE", (
        "39 is one point below the POSSIBLY_ELIGIBLE floor of 40"
    )


def test_counselor_assignment_least_loaded_with_created_at_tiebreak(api):
    """PRD §3.4: "Among candidates, the one with the lowest `active_case_load`
    is chosen, ties broken by the earliest `created_at`; the selection is a
    deterministic total order with no random tie-breaking. The chosen
    counselor's id lands in the screening's `counselor_id`, and assignment
    immediately increments that counselor's `active_case_load`, which counts
    the counselor's screenings in `STARTED`, `SCREENED`,
    `APPLICATION_ASSISTED`, or `SUBMITTED` status."

    Design: Corner/calculations/counselor_assignment_least_loaded_with_created_at_tiebreak
    """
    _, coord = create_coordinator()
    couns_a, _ = create_counselor(email="a@hub.test", full_name="A First")
    couns_b, _ = create_counselor(email="b@hub.test", full_name="B Second")
    client, _, _ = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=1, monthly_income_cents=80000, housing_status="STABLE",
            dependents_under_18=0, receives_snap=False,
            receives_childcare_subsidy=False, food_insecurity_score=2,
            consent_confidential=True,
        ),
        client_overrides={"alias_name": "m"},
    )
    s1 = validate_success(
        api.create_screening(client["id"], create_screening_payload("SNAP"), coord), 201
    )
    s2 = validate_success(
        api.create_screening(client["id"], create_screening_payload("HOUSING"), coord), 201
    )
    s3 = validate_success(
        api.create_screening(client["id"], create_screening_payload("CHILDCARE"), coord),
        201,
    )
    assert s1["counselor_id"] == couns_a["id"], "tie at load 0 -> earliest created_at"
    assert s2["counselor_id"] == couns_b["id"], "A loaded 1, B still 0"
    assert s3["counselor_id"] == couns_a["id"], "tie at load 1 -> earliest created_at again"


def test_screening_create_without_any_counselor_rejected(api):
    """PRD §3.4: "the candidate pool is all `ACTIVE` staff members whose
    `staff_role` is `BENEFITS_COUNSELOR`, and an empty pool rejects the
    creation with `ERR_NO_COUNSELOR_AVAILABLE`."

    Design: Corner/calculations/screening_create_without_any_counselor_rejected
    """
    _, coord = create_coordinator()
    client, _, _ = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=1, monthly_income_cents=80000, housing_status="STABLE",
            dependents_under_18=0, receives_snap=False,
            receives_childcare_subsidy=False, food_insecurity_score=2,
            consent_confidential=True,
        ),
        client_overrides={"alias_name": "np"},
    )
    res = api.create_screening(client["id"], create_screening_payload("SNAP"), coord)
    validate_error(res, ApiErrorId.ERR_NO_COUNSELOR_AVAILABLE, expected_status=409)
