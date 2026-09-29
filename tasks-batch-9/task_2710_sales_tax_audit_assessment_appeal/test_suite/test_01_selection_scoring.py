"""Risk scoring, the selection walk and the quota identity."""
from test_helpers import (
    ApiErrorId,
    list_leads,
    load_information_return,
    read_industry_project,
    read_lead,
    read_taxpayer,
    register_taxpayer,
    rescore_screening,
    run_selection,
    create_industry_project,
    decline_lead,
    leads_by_rank,
    set_clock_date,
    validate_error,
    validate_success,
)
from test_helpers import api_client

GROCERY_NAICS = "445110"
INDUSTRY_ERROR_RATE_BP = 4_200

HARBOR = {
    "legal_name": "Harbor Foods LLC",
    "industry_naics_code": GROCERY_NAICS,
    "filing_frequency": "MONTHLY",
    "gross_receipts_annual_cents": 250_000_000,
    "delinquent_period_count": 2,
}
VANTAGE = {
    "legal_name": "Vantage Beverage Co",
    "industry_naics_code": GROCERY_NAICS,
    "filing_frequency": "MONTHLY",
    "gross_receipts_annual_cents": 1_000_000_000,
    "delinquent_period_count": 0,
    "prior_audit_error_rate_bp": 6_000,
}
SUMMIT = {
    "legal_name": "Summit Market Inc",
    "industry_naics_code": GROCERY_NAICS,
    "filing_frequency": "QUARTERLY",
    "gross_receipts_annual_cents": 100_000_000,
    "delinquent_period_count": 1,
}
PERIOD = {"period_start": "2026-01-01", "period_end": "2026-03-31"}


def _register_harbor_and_vantage():
    """Harbor: variance 2500, delinquency 5000. Vantage: variance 5000, none late."""
    set_clock_date("2026-08-01")
    harbor = register_taxpayer(**HARBOR)
    vantage = register_taxpayer(**VANTAGE)
    load_information_return(
        harbor["id"],
        source_type="FEDERAL_1099K",
        reported_amount_cents=120_000_000,
        matched_return_amount_cents=90_000_000,
        **PERIOD,
    )
    load_information_return(
        vantage["id"],
        source_type="MARKETPLACE_REPORT",
        reported_amount_cents=200_000_000,
        matched_return_amount_cents=100_000_000,
        **PERIOD,
    )
    return harbor, vantage


def test_triage_score_and_project_score_disagree_about_who_is_riskiest():
    """The two variants rank the same two permit holders in opposite orders.

    PRD 3.1: "The **screening variant** is a two-factor triage of a single
    holder, weighting variance 60 and delinquency 40; its result is stored in
    `screening_score` and nowhere else."
    PRD 3.1: "Because the two variants weight the same holder differently, they
    routinely disagree about the relative ordering of the same set of holders,
    and that is intended: triage and project selection are different questions."
    PRD 3.1: "`rank_position` is 1-based within the run, ordering by `risk_score`
    descending and breaking ties by the permit holder's `created_at` ascending."

    Design: Difficulty/dual_variant_calc/risk_score_screening_vs_full_flips_ranking
    """
    harbor, vantage = _register_harbor_and_vantage()
    project = create_industry_project(
        project_name="Grocery 2026",
        industry_naics_code=GROCERY_NAICS,
        industry_error_rate_bp=INDUSTRY_ERROR_RATE_BP,
        selection_mode="THRESHOLD",
        selection_threshold_score=0,
        selection_quota=4,
    )

    rescore_screening(harbor["id"])
    rescore_screening(vantage["id"])
    run_selection(project["id"])

    # Triage puts Harbor ahead of Vantage.
    assert read_taxpayer(harbor["id"])["screening_score"] == 350
    assert read_taxpayer(vantage["id"])["screening_score"] == 300

    harbor_lead = list_leads(
        industry_project_id=project["id"], taxpayer_id=harbor["id"]
    )[0]
    vantage_lead = list_leads(
        industry_project_id=project["id"], taxpayer_id=vantage["id"]
    )[0]

    # The project run puts Vantage ahead of Harbor, the opposite order.
    assert harbor_lead["risk_score"] == 314
    assert vantage_lead["risk_score"] == 349
    assert vantage_lead["rank_position"] == 1
    assert harbor_lead["rank_position"] == 2


def test_project_run_records_the_full_variant_components_it_consumed():
    """Only the project run consumes industry, magnitude and the neutral prior.

    PRD 3.1: "The **full variant** is what a project scoring run uses, weighting
    variance 35, delinquency 20, industry 20, magnitude 15 and prior audit 10 —
    five weights that also sum to 100."
    PRD 3.1: "Each of these four is persisted on the permit holder as
    `info_variance_bp`, `delinquency_bp`, `magnitude_bp` and `prior_audit_bp`
    respectively."
    PRD 3.1: "A project run always writes `FULL`; the only other permitted value,
    `SCREENING`, labels the taxpayer-level screening score described earlier in
    this section and is never written to a lead."

    Design: Difficulty/dual_variant_calc/risk_score_screening_vs_full_flips_ranking
    """
    harbor, vantage = _register_harbor_and_vantage()
    project = create_industry_project(
        project_name="Grocery 2026",
        industry_naics_code=GROCERY_NAICS,
        industry_error_rate_bp=INDUSTRY_ERROR_RATE_BP,
        selection_mode="THRESHOLD",
        selection_threshold_score=0,
        selection_quota=4,
    )
    run_selection(project["id"])

    stored = read_taxpayer(harbor["id"])
    assert stored["info_variance_bp"] == 2_500
    assert stored["delinquency_bp"] == 5_000
    assert stored["magnitude_bp"] == 500
    assert stored["prior_audit_bp"] == 3_500

    harbor_lead = list_leads(
        industry_project_id=project["id"], taxpayer_id=harbor["id"]
    )[0]
    vantage_lead = list_leads(
        industry_project_id=project["id"], taxpayer_id=vantage["id"]
    )[0]
    assert harbor_lead["score_variant"] == "FULL"
    assert vantage_lead["score_variant"] == "FULL"

    breakdown = read_lead(harbor_lead["id"])["score_breakdown"]
    assert breakdown["info_variance_bp"] == 2_500
    assert breakdown["delinquency_bp"] == 5_000
    assert breakdown["industry_error_rate_bp"] == INDUSTRY_ERROR_RATE_BP
    assert breakdown["magnitude_bp"] == 500
    assert breakdown["prior_audit_bp"] == 3_500
    # 2500*35 + 5000*20 + 4200*20 + 500*15 + 3500*10, divided by 1,000 exactly once.
    assert breakdown["weighted_sum"] == 314_000
    assert harbor_lead["risk_score"] == 314


def _register_harbor_only():
    """Harbor Foods alone in the industry, scoring exactly 314 on the full variant."""
    set_clock_date("2026-08-01")
    harbor = register_taxpayer(**HARBOR)
    load_information_return(
        harbor["id"],
        source_type="FEDERAL_1099K",
        reported_amount_cents=120_000_000,
        matched_return_amount_cents=90_000_000,
        **PERIOD,
    )
    rescore_screening(harbor["id"])
    return harbor


def _cutoff_project(threshold):
    return create_industry_project(
        project_name=f"Grocery cutoff {threshold}",
        industry_naics_code=GROCERY_NAICS,
        industry_error_rate_bp=INDUSTRY_ERROR_RATE_BP,
        selection_mode="THRESHOLD",
        selection_threshold_score=threshold,
        selection_quota=5,
    )


def test_a_score_equal_to_the_cutoff_is_selected():
    """A permit holder scoring exactly the cutoff is inside the selection.

    PRD 3.1: "Under `THRESHOLD` it selects every lead whose `risk_score` is
    greater than or equal to `selection_threshold_score`; under `QUOTA` it selects
    the first `selection_quota` leads regardless of score; under `HYBRID` a lead
    must satisfy both conditions."

    Design: Difficulty/boundary_precision_check/selection_threshold_inclusive_at_the_cutoff_score
    """
    harbor = _register_harbor_only()
    assert read_taxpayer(harbor["id"])["screening_score"] == 350
    project = _cutoff_project(314)

    response = api_client.create_selection_run(
        project["id"], {"X-User-ID": "selection-analyst-1", "X-User-Role": "SelectionAnalyst"}
    )
    validate_success(response, 200)

    assert read_industry_project(project["id"])["selections_used"] == 1
    leads = list_leads(industry_project_id=project["id"])
    assert len(leads) == 1
    assert leads[0]["risk_score"] == 314
    assert leads[0]["score_variant"] == "FULL"
    assert leads[0]["rank_position"] == 1
    assert leads[0]["status"] == "SELECTED"


def test_a_run_that_selects_nobody_leaves_no_lead_behind():
    """One point above the score, the run is refused and writes nothing.

    PRD 3.1: "A `THRESHOLD` or `HYBRID` run that scored candidates but selected
    none of them, or that found no eligible holder at all, is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATES` and leaves no leads behind at all — the run is
    all-or-nothing."

    Design: Difficulty/boundary_precision_check/selection_threshold_inclusive_at_the_cutoff_score
    """
    _register_harbor_only()
    project = _cutoff_project(315)

    response = api_client.create_selection_run(
        project["id"], {"X-User-ID": "selection-analyst-1", "X-User-Role": "SelectionAnalyst"}
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_CANDIDATES.value, 422)

    assert list_leads(industry_project_id=project["id"]) == []
    assert read_industry_project(project["id"])["selections_used"] == 0


def _hybrid_project_over_three_holders():
    """Three scored holders under one HYBRID project of quota 2, cutoff 172."""
    set_clock_date("2026-08-01")
    vantage = register_taxpayer(**VANTAGE)
    load_information_return(
        vantage["id"],
        source_type="MARKETPLACE_REPORT",
        reported_amount_cents=200_000_000,
        matched_return_amount_cents=100_000_000,
        **PERIOD,
    )
    harbor = register_taxpayer(**HARBOR)
    load_information_return(
        harbor["id"],
        source_type="FEDERAL_1099K",
        reported_amount_cents=120_000_000,
        matched_return_amount_cents=90_000_000,
        **PERIOD,
    )
    summit = register_taxpayer(**SUMMIT)
    project = create_industry_project(
        project_name="Grocery quota identity",
        industry_naics_code=GROCERY_NAICS,
        industry_error_rate_bp=INDUSTRY_ERROR_RATE_BP,
        selection_mode="HYBRID",
        selection_threshold_score=172,
        selection_quota=2,
    )
    run_selection(project["id"])
    ranked = leads_by_rank(list_leads(industry_project_id=project["id"]))
    return {
        "project": project,
        "vantage": vantage,
        "harbor": harbor,
        "summit": summit,
        "ranked": ranked,
    }


def test_declining_a_selected_lead_promotes_the_waitlist_in_the_same_step():
    """The released slot is re-consumed at once, so the quota identity never breaks.

    PRD 3.1: "Declining a `SELECTED` lead decrements `selections_used` and
    increments `selections_remaining`, then immediately promotes the
    highest-ranked remaining `SCORED` lead of the same project — highest
    `risk_score`, ties broken by the permit holder's `created_at` ascending —
    provided that lead's `risk_score` still meets `selection_threshold_score`; the
    promoted lead moves `SCORED → SELECTED` with `promoted_from_scored` set to
    true, and the promotion re-consumes the released slot so that the quota
    identity holds at every intermediate step."
    PRD 2.11: "For any industry project, `selection_quota` always equals
    `selections_used` plus `selections_remaining`."

    Design: Difficulty/compensating_invariant/lead_decline_promotion_preserves_the_quota_identity
    """
    ctx = _hybrid_project_over_three_holders()
    harbor_lead, summit_lead = ctx["ranked"][1], ctx["ranked"][2]
    assert harbor_lead["risk_score"] == 314
    assert summit_lead["risk_score"] == 172

    decline_lead(harbor_lead["id"], decline_reason="Already under federal examination.")

    assert read_lead(harbor_lead["id"])["status"] == "DECLINED"
    promoted = read_lead(summit_lead["id"])
    assert promoted["status"] == "SELECTED"
    assert promoted["promoted_from_scored"] is True

    project = read_industry_project(ctx["project"]["id"])
    assert project["selections_used"] == 2
    assert project["selections_remaining"] == 0
    assert (
        project["selection_quota"]
        == project["selections_used"] + project["selections_remaining"]
    )
    assert read_taxpayer(ctx["vantage"]["id"])["open_audit_count"] == 0
    assert read_taxpayer(ctx["summit"]["id"])["open_audit_count"] == 0


def test_a_qualifying_lead_beyond_the_quota_waits_rather_than_being_rejected():
    """The third qualifying holder stays SCORED, and the cutoff records rank two.

    PRD 3.1: "A lead the walk does not select moves `SCORED → NOT_SELECTED` when
    its `risk_score` is below `selection_threshold_score`, and otherwise stays in
    `SCORED` as a waitlist entry — a qualifying lead that arrives at the point
    where `selections_remaining` has reached zero is waitlisted, not rejected."
    PRD 3.1: "When the walk finishes, the project records `scored_lead_count`,
    sets `last_run_at` to the run's clock instant, and sets `last_cutoff_score` to
    the `risk_score` of the lowest-ranked lead the run moved to `SELECTED`, or to
    `selection_threshold_score` when the run selected nobody."

    Design: Difficulty/compensating_invariant/lead_decline_promotion_preserves_the_quota_identity
    """
    ctx = _hybrid_project_over_three_holders()
    vantage_lead, harbor_lead, summit_lead = ctx["ranked"]

    assert vantage_lead["rank_position"] == 1
    assert vantage_lead["status"] == "SELECTED"
    assert harbor_lead["rank_position"] == 2
    assert harbor_lead["status"] == "SELECTED"
    assert summit_lead["rank_position"] == 3
    assert summit_lead["status"] == "SCORED"

    project = read_industry_project(ctx["project"]["id"])
    assert project["scored_lead_count"] == 3
    assert project["selections_used"] == 2
    assert project["selections_remaining"] == 0
    assert project["last_cutoff_score"] == 314
