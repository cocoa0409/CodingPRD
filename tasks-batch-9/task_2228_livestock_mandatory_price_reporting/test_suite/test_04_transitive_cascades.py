"""One write, and the consequences climb several entities away.

A material audit verdict un-publishes a market report four hops out, a single
penalty row suspends a registration and voids sibling filings three hops out,
and adopting a methodology docket withdraws exactly the reports of the category
it names.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.assertions import (
    assert_clock_stamp,
    assert_discrepancy_rates,
    assert_penalty_breakdown,
    assert_penalty_ledger,
    assert_report_dimensions,
    assert_window_ledger,
)
from test_helpers.types import (
    AggregationState,
    AuditCaseStatus,
    AuditFinding,
    DelinquencyTier,
    DisclosureState,
    MethodologyChangeStatus,
    PenaltyStatus,
    PublicationState,
    PurchaseTypeFilter,
    RegistrationStatus,
    ReportCategory,
    ReportingWindowStatus,
    SubmissionStatus,
    SuspendedReason,
    WeightingVariant,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}


def _published_window_under_audit(api):
    """Three accepted filings, a published report, and Alpha's filing in fieldwork."""
    scene = fx.three_reporter_cattle_window(api)
    report = fx.published_report(
        api,
        scene["window"]["id"],
        weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
    )
    assert_report_dimensions(
        report,
        AggregationState.COMPUTED.value,
        DisclosureState.CLEARED.value,
        PublicationState.PUBLISHED.value,
    )
    case = fx.fieldwork_case(api, scene["submissions"]["alpha"]["id"])
    return scene, report, case


def test_01_a_material_finding_reopens_the_filing_and_stales_the_report(api):
    """Hops one and two: the filing leaves the ledger and the aggregate goes stale.

    Thirty head short of 470 verified is a 6.38 percent head deviation, which
    reopens Alpha's filing with the audit-stamped reason, pulls its 500 head out
    of the window ledger and forces the published aggregate to stale.

    PRD §3.7: "The window ledger is then recomputed with this filing's head
    removed, every market report of the window sitting in `COMPUTED` is forced to
    `STALE`, any such report that was `PUBLISHED` is `WITHDRAWN`".

    Design: Difficulty/transitive_cascade/audit_material_finding_four_hop_chain
    """
    scene, report, case = _published_window_under_audit(api)

    finalized = fx.finalize_case(api, case["id"], 470, 1305315.00)

    assert finalized["status"] == AuditCaseStatus.DISCREPANCY.value, finalized
    assert_discrepancy_rates(finalized, 6.38, 0.00, AuditFinding.MATERIAL_HEAD.value)

    reopened = fx.read_submission(api, scene["submissions"]["alpha"]["id"])
    assert reopened["status"] == SubmissionStatus.UNDER_CORRECTION.value, reopened
    assert reopened["correction_reason"] == "AUDIT_MATERIAL_HEAD", reopened
    assert reopened["resubmission_count"] == 0, reopened

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=750,
        accepted_submission_count=2,
    )

    stale = fx.read_report(api, report["id"])
    assert_report_dimensions(
        stale,
        AggregationState.STALE.value,
        DisclosureState.UNREVIEWED.value,
    )
    assert stale["suppression_reason"] is None, stale


def test_02_the_same_verdict_withdraws_the_report_and_unpublishes_the_window(api):
    """Hops three and four: publication is withdrawn and the window drops back.

    Staleness withdraws the released report while keeping the instant it was
    released, the window falls out of published because nothing published
    remains on it, and the withdrawn report keeps its last computed price.

    PRD §3.7: "and a window left with no published report drops from `PUBLISHED`
    back to `LOCKED`."

    Design: Difficulty/transitive_cascade/audit_material_finding_four_hop_chain
    """
    scene, report, case = _published_window_under_audit(api)
    assert_clock_stamp(report["published_at"], k.WINDOW_PUBLICATION_RELEASE, "published_at")

    fx.finalize_case(api, case["id"], 470, 1305315.00)

    withdrawn = fx.read_report(api, report["id"])
    assert_report_dimensions(
        withdrawn,
        publication_state=PublicationState.WITHDRAWN.value,
    )
    assert_clock_stamp(
        withdrawn["published_at"], k.WINDOW_PUBLICATION_RELEASE, "published_at"
    )
    assert withdrawn["weighted_average_price_per_cwt"] == 285.61, (
        "staleness is a state, not a wipe of the last computed figures"
    )

    window = fx.read_window(api, scene["window"]["id"])
    assert window["status"] == ReportingWindowStatus.LOCKED.value, window


def _firm_on_the_tier_boundary(api):
    """Two plants, two penalties standing at 16 points, and two in-flight filings."""
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-101B",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
                "boxed_beef_volume_lbs_prior_year": 0,
                "forward_commitment_cap_head": 500,
            },
        ],
        legal_name="Alpha Packing",
    )
    entity_id = firm["entity"]["id"]
    plant_a, plant_b = firm["plants"]

    earlier = fx.assess_non_registration_penalties(api, entity_id, 2)
    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        assessed_penalty_cents=2815000,
        outstanding_penalty_cents=2815000,
        delinquency_points=16,
    )

    window = fx.create_standard_window(api)
    submitted = fx.submitted_filing(
        api,
        entity_id,
        plant_a["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=500,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    draft = fx.draft_filing(api, entity_id, plant_b["id"], window["id"])

    return {
        "firm": firm,
        "window": window,
        "earlier": earlier,
        "submitted": submitted,
        "draft": draft,
    }


def test_03_one_more_penalty_row_crosses_the_tier_and_suspends_the_licence(api):
    """Hops one and two: the point total crosses, and the registration follows.

    The third row is assessed while the firm still reads at the middle tier, so
    it books eight undoubled points that lift the total from 16 to 24 -- and the
    crossing suspends the governing registration for the delinquency breach
    without disturbing the number it was issued.

    PRD §3.8: "A governing registration in `ACTIVE` status moves `ACTIVE →
    SUSPENDED` with `suspended_reason` set to `DELINQUENCY_TIER_BREACH` — this
    happens only on the crossing".

    Design: Difficulty/transitive_cascade/penalty_tier_breach_three_hop_chain
    """
    scene = _firm_on_the_tier_boundary(api)
    entity_id = scene["firm"]["entity"]["id"]
    issued_number = scene["firm"]["registration"]["registration_number"]

    third = fx.assess_non_registration_penalties(api, entity_id, 1)[0]

    assert_penalty_breakdown(
        third,
        repeat_index=2,
        repeat_multiplier=2.00,
        volume_factor=1.126,
        suspension_surcharge=1.00,
        assessed_amount_cents=2000000,
        points=8,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_1.value,
    )

    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        assessed_penalty_cents=4815000,
        paid_penalty_cents=0,
        waived_penalty_cents=0,
        outstanding_penalty_cents=4815000,
        delinquency_points=24,
    )

    registration = fx.read_registration(api, scene["firm"]["registration"]["id"])
    assert registration["status"] == RegistrationStatus.SUSPENDED.value, registration
    assert (
        registration["suspended_reason"]
        == SuspendedReason.DELINQUENCY_TIER_BREACH.value
    ), registration
    assert registration["registration_number"] == issued_number, registration


def test_04_the_suspension_fans_out_over_the_firms_in_flight_filings(api):
    """Hop three: both unfinished filings are voided, and no ledger moves.

    The suspension voids the draft and the submitted filing alike, the window
    ledger stays empty because neither head was ever counted in it, and the two
    earlier penalty rows are left exactly as assessed.

    PRD §3.8: "Either transition then voids the firm's in-flight filings: every
    submission of the firm's plants in `DRAFT` or `SUBMITTED` status becomes
    `VOIDED`, with no window ledger movement."

    Design: Difficulty/transitive_cascade/penalty_tier_breach_three_hop_chain
    """
    scene = _firm_on_the_tier_boundary(api)

    fx.assess_non_registration_penalties(api, scene["firm"]["entity"]["id"], 1)

    for key in ("submitted", "draft"):
        voided = fx.read_submission(api, scene[key]["id"])
        assert voided["status"] == SubmissionStatus.VOIDED.value, voided

    assert_window_ledger(
        fx.read_window(api, scene["window"]["id"]),
        total_head_reported=0,
        accepted_submission_count=0,
    )

    for penalty, amount in zip(scene["earlier"], (1126000, 1689000)):
        untouched = fx.read_penalty(api, penalty["id"])
        assert untouched["assessed_amount_cents"] == amount, untouched
        assert untouched["status"] == PenaltyStatus.ASSESSED.value, untouched


def _published_report_and_closed_docket(api):
    """A published LIVE_STEER_HEIFER report, a LIVE_COW_BULL control, and a docket."""
    scene = fx.three_reporter_cattle_window(api)
    window_id = scene["window"]["id"]

    affected = fx.reviewed_report(
        api,
        window_id,
        category=ReportCategory.LIVE_STEER_HEIFER.value,
        weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
    )
    control = fx.computed_report(
        api,
        window_id,
        category=ReportCategory.LIVE_COW_BULL.value,
        weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
        purchase_type_filter=PurchaseTypeFilter.NEGOTIATED_ONLY.value,
    )

    docket = fx.open_docket(api)
    fx.add_comment(
        api,
        docket["id"],
        commenter_reference="TRADE-ASSOC-1",
        comment_text="Weight weighting better reflects carcass value.",
    )

    fx.lock_window(api, window_id, at=k.WINDOW_PUBLICATION_RELEASE)
    affected = validate_success(
        api.publish_market_report(affected["id"], u.MARKET_ANALYST)
    )

    fx.set_clock(api, "2026-09-05T00:00:00Z")
    closed = get_success_data(
        api.close_comment_period(docket["id"], u.PROGRAM_ADMIN)
    )
    assert closed["status"] == MethodologyChangeStatus.COMMENT_CLOSED.value, closed

    return {
        "window": scene["window"],
        "affected": affected,
        "control": control,
        "docket": docket,
    }


def test_05_adoption_reweights_the_category_and_withdraws_its_published_report(api):
    """Rewriting the weighting stales the aggregate, which unwinds publication.

    Adoption issues the industry notice, rewrites the one matching report to the
    proposed weighting and counts it as restated -- and because the rewrite
    makes the aggregate stale, disclosure resets, the release is withdrawn and
    the window drops back out of published.

    PRD §3.9: "Each such report that was sitting in `COMPUTED` aggregation is
    forced to `STALE`, which as always drives its `disclosure_state` back to
    `UNREVIEWED`, clears its `suppression_reason`, withdraws it if it was
    `PUBLISHED`".

    Design: Difficulty/transitive_cascade/methodology_adoption_restatement_chain
    """
    scene = _published_report_and_closed_docket(api)

    adopted = validate_success(
        api.adopt_methodology_change(scene["docket"]["id"], u.PROGRAM_ADMIN)
    )

    assert adopted["status"] == MethodologyChangeStatus.ADOPTED.value, adopted
    assert_clock_stamp(
        adopted["industry_notice_issued_at"],
        "2026-09-05T00:00:00Z",
        "industry_notice_issued_at",
    )
    assert adopted["restated_report_count"] == 1, adopted

    restated = fx.read_report(api, scene["affected"]["id"])
    assert restated["weighting_variant"] == WeightingVariant.WEIGHT_WEIGHTED.value
    assert_report_dimensions(
        restated,
        AggregationState.STALE.value,
        DisclosureState.UNREVIEWED.value,
        PublicationState.WITHDRAWN.value,
    )
    assert restated["weighted_average_price_per_cwt"] == 285.61, (
        "adoption reweights and stales, but it does not recompute"
    )

    window = fx.read_window(api, scene["window"]["id"])
    assert window["status"] == ReportingWindowStatus.LOCKED.value, window


def test_06_a_report_in_another_category_of_the_same_window_is_untouched(api):
    """The fan-out is scoped to the category the docket names.

    The cow-and-bull report shares the window with the restated one, and none of
    its three dimensions or its weighting moves when the steer-and-heifer
    methodology is adopted.

    PRD §3.9: "then walks every market report whose `category` equals the
    docket's `affected_category` and whose `publication_state` is anything other
    than `WITHDRAWN`, replacing each one's `weighting_variant` with the docket's
    `proposed_weighting_variant`."

    Design: Difficulty/transitive_cascade/methodology_adoption_restatement_chain
    """
    scene = _published_report_and_closed_docket(api)

    validate_success(
        api.adopt_methodology_change(scene["docket"]["id"], u.PROGRAM_ADMIN)
    )

    control = fx.read_report(api, scene["control"]["id"])
    assert control["category"] == ReportCategory.LIVE_COW_BULL.value, control
    assert control["weighting_variant"] == WeightingVariant.HEAD_WEIGHTED.value, control
    assert_report_dimensions(
        control,
        AggregationState.COMPUTED.value,
        DisclosureState.UNREVIEWED.value,
        PublicationState.UNPUBLISHED.value,
    )
