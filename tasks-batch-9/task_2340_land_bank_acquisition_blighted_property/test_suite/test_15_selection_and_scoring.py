"""
Scores, ratios, rankings and candidate selection.

The blight priority score is carried at full precision and rounded once at the
end; a hearing's support ratio is kept to four decimal places; a demolition
prioritization run admits only parcels that satisfy every candidate condition
and ranks what is left by a pinned key order; and a buyer screening reports its
disqualifiers in a pinned sequence with a score derived from their count.
"""

from test_helpers import (
    ApiClient,
    assert_demolition_run,
    assert_eligibility_screening,
    assert_property,
    assert_reuse_hearing,
    assert_score,
    expected_admin_fee_cents,
    expected_demolition_estimate_cents,
    factories,
    fixtures,
    validate_success,
)
from test_helpers.test_users import DISP_1, INTAKE_1, INV_1

# A grade D structure on a 5,000 sqft lot: a 950,000-cent base, 310,000 cents of
# per-area charge and a 226,800-cent asbestos surcharge make a 1,486,800-cent
# subtotal, plus 96,642 cents of county overhead.
DEMOLITION_ESTIMATE_GRADE_D_5000_SQFT_CENTS = 1583442


def test_hearing_support_ratio_is_kept_to_four_decimal_places(api: ApiClient) -> None:
    """Five of seven comments in support is a non-terminating quotient that must be stored as exactly 0.7143.

    The hearing's `support_ratio` is the support count divided by the comment count, rounded half up to four decimal places, and is exactly zero when no comments were received.

    Design: Corner/calculations/hearing_support_ratio_kept_to_four_decimals
    """
    prop = fixtures.create_property(
        api,
        address="2020 Umbrella St",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    payload = factories.reuse_hearing_payload(
        hearing_at="2026-07-15T18:00:00Z",
        comment_count=7,
        support_count=5,
        summary="Neighbourhood favours a pocket park.",
    )

    hearing = validate_success(api.create_reuse_hearing(prop["id"], payload, DISP_1), 201)

    assert_reuse_hearing(hearing)
    # 5 / 7 = 0.714285..., taken half up at the fourth decimal place.
    assert hearing["support_ratio"] == 0.7143
    assert hearing["comment_count"] == 7
    assert hearing["support_count"] == 5
    assert hearing["hearing_at"].startswith("2026-07-15T18:00:00")
    assert "version" not in hearing


def test_run_candidates_exclude_prospect_clouded_and_sub_threshold_parcels(
    api: ApiClient,
) -> None:
    """Of four parcels in one ward only the acquired, clear-title parcel scoring 40.0 is a candidate: the registry-only parcel, the acquired parcel whose title is still clouded and the parcel scoring 8.0 never enter the run at all.

    The candidate set is explicit: a parcel qualifies when its `custody_status` is `ACQUIRED` or `LISTED`, its `title_status` is `CLEAR`, `structure_present` is true, its `current_blight_score` (refreshed with the live variant before ranking) is at least 40, it carries no maintenance order of type `DEMOLITION` in either `SCHEDULED` or `COMPLETED`, and — when a ward filter was supplied — its `situs_ward` equals that filter.

    Design: Corner/calculations/run_candidate_filter_excludes_prospect_clouded_and_low_score
    """
    acquisition_line = fixtures.create_acquisition_funding_source(
        api, name="Filter Acquisition Line"
    )
    operations_line = fixtures.create_funding_source(
        api,
        name="Filter Operations Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
    )

    # Grade D (30 points) plus 40 vacant months (10.0 points) is exactly 40.0.
    candidate = fixtures.demolition_candidate(
        api,
        acquisition_line["id"],
        address="2030 Vine St",
        situs_ward=7,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_condition_grade="D",
        vacancy_months=40,
    )
    registry_only = fixtures.create_property(
        api,
        address="2031 Vine St",
        situs_ward=7,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="F",
        vacancy_months=40,
    )
    still_clouded = fixtures.create_property(
        api,
        address="2032 Vine St",
        situs_ward=7,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="F",
        vacancy_months=40,
    )
    fixtures.acquire_property(
        api, still_clouded["id"], acquisition_line["id"], donor_name="Vine Street Trust"
    )
    # Grade B (8 points) with no vacancy: 8.0, far below the threshold.
    low_scoring = fixtures.demolition_candidate(
        api,
        acquisition_line["id"],
        address="2033 Vine St",
        situs_ward=7,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_condition_grade="B",
        vacancy_months=0,
    )

    payload = factories.demolition_run_payload(
        operations_line["id"],
        2000000,
        fixtures.funding_source_version(api, operations_line["id"]),
        situs_ward_filter=7,
    )
    run = validate_success(api.create_demolition_run(payload, INV_1), 201)

    assert_demolition_run(run)
    assert run["properties_selected_count"] == 1
    assert run["selected_property_ids"] == [candidate["id"]]
    # The three non-candidates never enter the ranking, so they are not skipped
    # either: skipping records only ranked parcels that did not fit.
    assert run["skipped_property_count"] == 0
    for excluded in (registry_only["id"], still_clouded["id"], low_scoring["id"]):
        assert excluded not in run["selected_property_ids"]
        assert excluded not in run["skipped_property_ids"]

    assert run["committed_subtotal_cents"] == DEMOLITION_ESTIMATE_GRADE_D_5000_SQFT_CENTS
    assert run["committed_subtotal_cents"] == expected_demolition_estimate_cents(
        5000, "D"
    )
    assert run["admin_fee_cents"] == 118758
    assert run["admin_fee_cents"] == expected_admin_fee_cents(1583442)
    assert run["total_committed_cents"] == 1702200

    assert_score(
        fixtures.read_property(api, candidate["id"])["current_blight_score"], 40.0
    )
    assert_score(
        fixtures.read_property(api, low_scoring["id"])["current_blight_score"], 8.0
    )
    assert fixtures.read_property(api, still_clouded["id"])["title_status"] == "CLOUDED"
    assert fixtures.read_property(api, registry_only["id"])["custody_status"] == (
        "PROSPECT"
    )


def test_run_candidate_admitted_at_exactly_the_score_threshold(api: ApiClient) -> None:
    """A parcel scoring exactly 40.0 is a candidate while an otherwise identical parcel one vacant month short, scoring 39.8, is not.

    The candidate set is explicit: a parcel qualifies when its `custody_status` is `ACQUIRED` or `LISTED`, its `title_status` is `CLEAR`, `structure_present` is true, its `current_blight_score` (refreshed with the live variant before ranking) is at least 40, it carries no maintenance order of type `DEMOLITION` in either `SCHEDULED` or `COMPLETED`, and — when a ward filter was supplied — its `situs_ward` equals that filter.

    Design: Corner/calculations/run_candidate_included_at_exact_score_threshold
    """
    acquisition_line = fixtures.create_acquisition_funding_source(
        api, name="Threshold Acquisition Line"
    )
    operations_line = fixtures.create_funding_source(
        api,
        name="Threshold Operations Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
    )
    # 30 + 40 x 0.25 = 40.0 exactly.
    at_threshold = fixtures.demolition_candidate(
        api,
        acquisition_line["id"],
        address="2040 Willow St",
        situs_ward=8,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_condition_grade="D",
        vacancy_months=40,
    )
    # 30 + 39 x 0.25 = 39.75, which the single terminal rounding takes to 39.8.
    below_threshold = fixtures.demolition_candidate(
        api,
        acquisition_line["id"],
        address="2041 Willow St",
        situs_ward=8,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_condition_grade="D",
        vacancy_months=39,
    )

    assert_score(
        fixtures.read_property(api, at_threshold["id"])["current_blight_score"], 40.0
    )
    assert_score(
        fixtures.read_property(api, below_threshold["id"])["current_blight_score"], 39.8
    )

    payload = factories.demolition_run_payload(
        operations_line["id"],
        2000000,
        fixtures.funding_source_version(api, operations_line["id"]),
        situs_ward_filter=8,
    )
    run = validate_success(api.create_demolition_run(payload, INV_1), 201)

    assert_demolition_run(run)
    # 2,000,000 / 1.075 floored to whole cents.
    assert run["provisional_cap_cents"] == 1860465
    assert run["properties_selected_count"] == 1
    assert run["selected_property_ids"] == [at_threshold["id"]]
    assert run["committed_subtotal_cents"] == DEMOLITION_ESTIMATE_GRADE_D_5000_SQFT_CENTS
    # A sub-threshold parcel never enters the ranked list, so it is not skipped.
    assert below_threshold["id"] not in run["skipped_property_ids"]
    assert run["skipped_property_count"] == 0


def test_blight_score_is_rescored_from_scratch_on_each_code_violation_report(
    api: ApiClient,
) -> None:
    """Each code-enforcement snapshot re-scores the parcel from its current counts rather than accumulating, so 1 complaint with 1 violation gives 13.3 and a later 6 complaints with 3 violations gives 26.8.

    The six terms are added at full precision, the sum is rounded half up to one decimal place, and the result is capped at 100 — the rounding and the cap are applied once, at the very end.

    Design: Corner/calculations/blight_score_rescored_when_code_violation_report_changes
    """
    payload = factories.property_payload(
        address="2080 Beech St",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="B",
        vacancy_months=3,
    )
    prop = validate_success(api.create_property(payload, INTAKE_1), 201)

    assert_property(prop)
    # A brand-new registry parcel carries no score until a recompute fires.
    assert_score(prop["current_blight_score"], 0)
    assert prop["intake_blight_score"] is None

    first = validate_success(
        api.post_code_violation_report(
            prop["id"],
            {"open_code_violation_count": 1, "nuisance_complaint_count": 1},
            INTAKE_1,
        )
    )
    # 8 (grade B) + 0.75 (3 vacant months) + 1.5 (1 complaint) + 3 (1 violation)
    # = 13.25 at full precision, rounded half up once to 13.3.
    assert_score(first["current_blight_score"], 13.3)

    second = validate_success(
        api.post_code_violation_report(
            prop["id"],
            {"open_code_violation_count": 3, "nuisance_complaint_count": 6},
            INTAKE_1,
        )
    )
    # 8 + 0.75 + 9 + 9 = 26.75, rounded half up once to 26.8.
    assert_score(second["current_blight_score"], 26.8)
    # The second snapshot overwrites the counts, it does not add to them.
    assert second["open_code_violation_count"] == 3
    assert second["nuisance_complaint_count"] == 6
    assert second["intake_blight_score"] is None


def test_run_ranking_tie_is_broken_by_the_earliest_created_at(api: ApiClient) -> None:
    """Two parcels tied on score and on lot area are ordered by registration date, so with room for only one demolition the parcel registered first is selected and the later one is skipped.

    Candidates are then ranked by `current_blight_score` from highest to lowest, ties broken by `lot_area_sqft` from largest to smallest, and remaining ties broken by `created_at` from oldest to newest; the record `id` is never a sort key.

    Design: Corner/calculations/run_ranking_tie_broken_by_earliest_created_at
    """
    acquisition_line = fixtures.create_acquisition_funding_source(
        api, name="Tiebreak Acquisition Line"
    )
    operations_line = fixtures.create_funding_source(
        api,
        name="Tiebreak Operations Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
    )

    first_registered = fixtures.create_property(
        api,
        address="2100 Dogwood Ct",
        situs_ward=9,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="D",
        vacancy_months=40,
    )
    # The second parcel is registered a logical day later, so the two carry
    # different created_at instants while every ranking key above it ties.
    fixtures.set_clock(api, "2026-08-02T00:00:00Z")
    later_registered = fixtures.create_property(
        api,
        address="2101 Dogwood Ct",
        situs_ward=9,
        lot_area_sqft=5000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="D",
        vacancy_months=40,
    )
    for parcel in (first_registered, later_registered):
        fixtures.acquire_property(
            api, parcel["id"], acquisition_line["id"], donor_name="Dogwood Trust"
        )
        fixtures.clear_title(api, parcel["id"])

    older = fixtures.read_property(api, first_registered["id"])
    newer = fixtures.read_property(api, later_registered["id"])
    assert older["created_at"] < newer["created_at"]
    assert_score(older["current_blight_score"], 40.0)
    assert_score(newer["current_blight_score"], 40.0)
    assert older["lot_area_sqft"] == newer["lot_area_sqft"]

    payload = factories.demolition_run_payload(
        operations_line["id"],
        1750000,
        fixtures.funding_source_version(api, operations_line["id"]),
        situs_ward_filter=9,
    )
    run = validate_success(api.create_demolition_run(payload, INV_1), 201)

    assert_demolition_run(run)
    # 1,750,000 / 1.075 floored is 1,627,906, which fits exactly one 1,583,442
    # demolition and leaves 44,464 cents - too little for the second.
    assert run["provisional_cap_cents"] == 1627906
    assert run["properties_selected_count"] == 1
    assert run["skipped_property_count"] == 1
    assert run["selected_property_ids"] == [first_registered["id"]]
    assert run["skipped_property_ids"] == [later_registered["id"]]
    assert run["committed_subtotal_cents"] == DEMOLITION_ESTIMATE_GRADE_D_5000_SQFT_CENTS
    assert run["admin_fee_cents"] == 118758
    assert run["total_committed_cents"] == 1702200


def test_screening_failure_lists_its_disqualifiers_in_the_pinned_order(
    api: ApiClient,
) -> None:
    """A buyer who becomes both tax-delinquent and a code violator after submitting is screened FAIL with the disqualifiers recorded as delinquent taxes before code violations and an eligibility score of 50.

    The `disqualifiers` array is appended to in exactly this order, and the order is part of the contract: `DELINQUENT_TAXES` when the delinquent-tax total is strictly greater than zero; `CODE_VIOLATIONS` when the open-violation total is at least 2;

    Design: Corner/calculations/screening_fail_lists_disqualifiers_in_pinned_order
    """
    acquisition_line = fixtures.create_acquisition_funding_source(
        api, name="Screening Acquisition Line"
    )
    for_sale = fixtures.create_property(
        api,
        address="2110 Elm Ct",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=100000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    owned_of_record = fixtures.create_property(
        api,
        address="2111 Elm Ct",
        situs_ward=3,
        lot_area_sqft=4000,
        assessed_value_cents=250000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=0,
    )
    buyer = fixtures.create_applicant(
        api,
        legal_name="Dana Okonkwo",
        applicant_type="INDIVIDUAL",
        contact_email="dana@example.com",
    )
    fixtures.set_owner_of_record(api, owned_of_record["id"], buyer["id"])

    fixtures.acquire_property(
        api, for_sale["id"], acquisition_line["id"], donor_name="Elm Court Estate"
    )
    fixtures.clear_title(api, for_sale["id"])
    fixtures.list_parcel(api, for_sale["id"])

    application = fixtures.draft_application(
        api,
        for_sale["id"],
        buyer["id"],
        program="HOMEOWNER_SALE",
        proposed_use="Owner-occupied single family",
        offer_price_cents=100000,
    )
    submitted = fixtures.submit_application(api, application["id"], buyer["id"])
    assert submitted["status"] == "SUBMITTED"
    # 0.55 x 100,000 = 55,000 is under the 100,000-cent homeowner floor.
    assert submitted["quoted_price_cents"] == 100000

    # The buyer's own parcel goes delinquent and picks up two open violations
    # only after the submission was accepted.
    fixtures.post_tax_roll(
        api, owned_of_record["id"], delinquent_tax_balance_cents=15000
    )
    fixtures.post_code_violations(
        api, owned_of_record["id"], open_code_violation_count=2
    )

    screening = validate_success(api.screen_application(application["id"], DISP_1), 201)

    assert_eligibility_screening(screening)
    assert screening["disqualifiers"] == ["DELINQUENT_TAXES", "CODE_VIOLATIONS"]
    # 100 reduced by 25 points for each of the two disqualifiers.
    assert screening["eligibility_score"] == 50
    assert screening["outcome"] == "FAIL"
    assert screening["sequence_no"] == 1
    assert screening["delinquent_tax_total_cents"] == 15000
    assert screening["open_code_violation_total"] == 2
    assert screening["recent_reverter_count"] == 0

    denied = fixtures.read_application(api, application["id"])
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "SCREENING_FAIL:DELINQUENT_TAXES"
    assert denied["screening_count"] == 1
    assert fixtures.read_applicant(api, buyer["id"])["eligibility_status"] == "BARRED"
