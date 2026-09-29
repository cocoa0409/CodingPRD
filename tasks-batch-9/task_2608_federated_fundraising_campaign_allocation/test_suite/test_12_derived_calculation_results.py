"""Derived figures on known inputs: per-line designation fees, the input set a
campaign aggregate admits, the declared scoring weights, the collection-ratio
rescale and the trimmed mean.

Every expected number below is written out in full so that a divergent
implementation is caught on the value rather than on the shape.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_is_null,
    assert_money,
    require_by,
    to_decimal,
)
from test_helpers.factories import designation_line, panel_score_payload, pledge_payload
from test_helpers.fixtures import (
    create_active_employer,
    create_good_standing_agency,
    create_open_campaign,
    create_open_cycle,
    create_pledge,
    create_submitted_request,
    file_score,
    remit,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_allocations_director_headers,
    make_panelist_headers,
)


def test_three_designation_lines_each_carry_their_own_rounded_fee():
    """PRD 3.3: "For each line, the raw fee is that line's `designated_amount`
    multiplied by the donor-designation processing rate of 7.25 percent; the line's
    `processing_fee` is that raw fee rounded half up to two decimal places, or 1.50 —
    the floor the organization charges to touch any designation at all — whichever is
    larger."

    Lines of 100.00, 40.00 and 25.00 produce 7.25, 2.90 and 1.81; the 1.50 floor can
    never bind here, because the smallest line the API will accept already earns 1.81.

    Design: Corner/calculations/pledge_designation_fee_allocation_correct_result_on_three_lines
    """
    admin = make_admin_headers()
    first_agency = create_good_standing_agency(
        legal_name="Maple Street Clinic",
        ein="610000001",
        primary_priority_area="HEALTH",
    )
    second_agency = create_good_standing_agency(
        legal_name="Harborview Literacy Trust",
        ein="610000002",
        primary_priority_area="EDUCATION",
    )
    employer = create_active_employer(legal_name="Kestrel Analytics", employee_count=150)
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )

    pledge = validate_success(
        api_client.create_pledge(
            campaign["id"],
            pledge_payload(
                donor_reference="F-001",
                giving_method="ONE_TIME_CHECK",
                gross_amount="500.00",
                designations=[
                    designation_line(first_agency["id"], "100.00"),
                    designation_line(second_agency["id"], "40.00"),
                    designation_line(first_agency["id"], "25.00"),
                ],
            ),
            admin,
        ),
        201,
    )

    assert_money(pledge["designated_amount_total"], "165.00", "designated_amount_total")
    assert_money(pledge["undesignated_amount"], "335.00", "undesignated_amount")
    assert_money(pledge["designation_fee_total"], "11.96", "designation_fee_total")
    assert_money(pledge["net_designated_total"], "153.04", "net_designated_total")

    lines, meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin, {"status": "ACTIVE"})
    )
    assert meta["total_count"] == 3
    expected = (
        (1, first_agency["id"], "100.00", "7.25", "92.75"),
        (2, second_agency["id"], "40.00", "2.90", "37.10"),
        (3, first_agency["id"], "25.00", "1.81", "23.19"),
    )
    for sequence, agency_id, designated, fee, net in expected:
        line = require_by(lines, "designation_sequence", sequence)
        assert line["agency_id"] == agency_id, f"line {sequence} points at the wrong agency"
        assert line["status"] == "ACTIVE"
        assert_money(line["designated_amount"], designated, f"line {sequence} designated_amount")
        assert_money(line["processing_fee"], fee, f"line {sequence} processing_fee")
        assert_money(line["net_designated_amount"], net, f"line {sequence} net")
        assert_money(
            line["collected_designated_amount"],
            "0.00",
            f"line {sequence} collected_designated_amount",
        )


def test_a_draft_pledge_contributes_nothing_to_the_campaign_aggregates():
    """PRD 3.2: "`confirmed_gross_total` is the sum of `gross_amount` over the
    campaign's pledges whose designation status is `CONFIRMED`, `AMENDED` or `LOCKED`."

    PRD 3.3: "Recording a pledge leaves it in `DRAFT`, which contributes to nothing."

    The draft pledge still computes its own designation figures, which is what makes the
    campaign-level exclusion visible rather than vacuous.

    Design: Corner/calculations/campaign_confirmed_gross_total_excludes_draft_pledges
    """
    admin = make_admin_headers()
    agency = create_good_standing_agency(
        legal_name="Prairie Star Housing",
        ein="610000003",
        primary_priority_area="BASIC_NEEDS",
    )
    employer = create_active_employer(legal_name="Halcyon Print Works", employee_count=210)
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    first = create_pledge(
        campaign["id"],
        donor_reference="I-001",
        giving_method="PAYROLL_DEDUCTION",
        gross_amount="600.00",
    )
    second = create_pledge(
        campaign["id"],
        donor_reference="I-002",
        giving_method="ONE_TIME_CHECK",
        gross_amount="400.00",
    )
    left_draft = create_pledge(
        campaign["id"],
        donor_reference="I-003",
        giving_method="CREDIT_CARD",
        gross_amount="250.00",
        designations=[designation_line(agency["id"], "100.00")],
    )

    validate_success(api_client.confirm_pledge(first["id"], admin))
    validate_success(api_client.confirm_pledge(second["id"], admin))

    reread_campaign = validate_success(api_client.get_campaign(campaign["id"], admin))
    assert_money(reread_campaign["confirmed_gross_total"], "1000.00", "confirmed_gross_total")
    assert_money(reread_campaign["designated_gross_total"], "0.00", "designated_gross_total")
    assert_money(reread_campaign["designation_fee_total"], "0.00", "designation_fee_total")
    assert_money(
        reread_campaign["undesignated_gross_total"], "1000.00", "undesignated_gross_total"
    )

    reread_draft = validate_success(api_client.get_pledge(left_draft["id"], admin))
    assert reread_draft["designation_status"] == "DRAFT"
    assert_money(reread_draft["designated_amount_total"], "100.00", "designated_amount_total")
    assert_money(reread_draft["designation_fee_total"], "7.25", "designation_fee_total")
    assert_money(reread_draft["undesignated_amount"], "150.00", "undesignated_amount")

    reread_agency = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(
        reread_agency["designated_passthrough_ytd"], "0.00", "designated_passthrough_ytd"
    )


def test_a_filed_score_blends_its_three_judgements_at_the_declared_weights():
    """PRD 3.7: "Each filed score immediately computes its own `weighted_score`: the
    priority alignment judgement weighted at 0.40, the outcome evidence judgement at
    0.35 and the capacity judgement at 0.25, summed and then rounded half up to two
    decimal places."

    PRD 3.7: "The first score filed against a request advances it `SUBMITTED →
    UNDER_PANEL_REVIEW` and re-derives `eligible_score_count`; filing also increments
    the volunteer's `submitted_score_count` and the seat's own `submitted_score_count`."

    Judgements of 90, 80 and 70 give 36.00 plus 28.00 plus 17.50, so 81.50 — a figure
    only the declared weight triple produces; an equal-thirds blend would give 80.00.

    Design: Corner/calculations/panel_score_weighted_blend_applies_declared_weight_constants
    """
    admin = make_admin_headers()
    agency = create_good_standing_agency(
        legal_name="Bluff City Mentors",
        ein="610000004",
        primary_priority_area="EDUCATION",
    )
    cycle, panelists = create_open_cycle(
        1,
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="250000.00",
        max_award_per_agency="80000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    panelist = panelists[0]
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="40000.00",
        priority_area="EDUCATION",
        narrative_summary="Peer mentoring for first-generation high-school students.",
    )

    score = validate_success(
        api_client.create_panel_score(
            request["id"],
            panel_score_payload(90, 80, 70),
            make_panelist_headers(panelist["id"]),
        ),
        201,
    )

    assert score["request_id"] == request["id"]
    assert score["panelist_id"] == panelist["id"]
    assert score["priority_alignment_score"] == 90
    assert score["outcome_evidence_score"] == 80
    assert score["capacity_score"] == 70
    assert_money(score["weighted_score"], "81.50", "weighted_score")
    assert score["weighted_score"] not in ("80.00", 80.00), (
        "80.00 is the unweighted average of the same three judgements"
    )
    assert score["eligible"] is True, "a filed score starts eligible"

    reread_request = validate_success(
        api_client.get_allocation_request(request["id"], admin)
    )
    assert reread_request["status"] == "UNDER_PANEL_REVIEW"
    assert reread_request["eligible_score_count"] == 1
    assert_is_null(reread_request["composite_score"], "composite_score before finalization")

    reread_panelist = validate_success(api_client.get_panelist(panelist["id"], admin))
    assert reread_panelist["submitted_score_count"] == 1

    seats, seat_meta = validate_paginated(
        api_client.list_cycle_panel_assignments(cycle["id"], admin)
    )
    assert seat_meta["total_count"] == 1
    seat = require_by(seats, "panelist_id", panelist["id"])
    assert seat["submitted_score_count"] == 1


def test_the_designated_line_is_rescaled_from_scratch_at_each_collection():
    """PRD 3.5: "Processing the pledge's `ACTIVE` lines in ascending
    `designation_sequence`, each line's `collected_designated_amount` becomes its
    `net_designated_amount` multiplied by the pledge's collection ratio —
    `collected_amount` divided by `gross_amount` — rounded half up to two decimal
    places."

    A 100.00 remittance against a 400.00 pledge scales the 278.25 net line to 69.56;
    the further 300.00 remittance rescales it to the whole 278.25 rather than adding a
    second increment on top of the first.

    Design: Corner/calculations/pledge_collected_designated_amount_scales_across_partial_and_full_collection
    """
    admin = make_admin_headers()
    agency = create_good_standing_agency(
        legal_name="Redwood Elder Services",
        ein="610000005",
        primary_priority_area="HEALTH",
    )
    employer = create_active_employer(legal_name="Vantage Logistics", employee_count=260)
    _, campaign = create_open_campaign(
        employer["id"],
        solicitation_start_date="2026-07-01",
        solicitation_end_date="2026-09-30",
    )
    pledge = create_pledge(
        campaign["id"],
        donor_reference="S-001",
        giving_method="ONE_TIME_CHECK",
        gross_amount="400.00",
        designations=[designation_line(agency["id"], "300.00")],
    )
    validate_success(api_client.confirm_pledge(pledge["id"], admin))

    remit(pledge["id"], "100.00")

    partial = validate_success(api_client.get_pledge(pledge["id"], admin))
    assert partial["collection_status"] == "PARTIAL"
    assert_money(partial["collected_amount"], "100.00", "collected_amount")
    assert_money(partial["uncollected_amount"], "300.00", "uncollected_amount")
    assert_money(partial["net_designated_total"], "278.25", "net_designated_total")

    lines, meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin, {"status": "ACTIVE"})
    )
    assert meta["total_count"] == 1
    assert_money(lines[0]["collected_designated_amount"], "69.56", "line collected at 25 percent")
    ledger = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(ledger["designated_passthrough_ytd"], "69.56", "designated_passthrough_ytd")

    remit(pledge["id"], "300.00")

    collected = validate_success(api_client.get_pledge(pledge["id"], admin))
    assert collected["collection_status"] == "COLLECTED"
    assert_money(collected["collected_amount"], "400.00", "collected_amount")
    assert_money(collected["uncollected_amount"], "0.00", "uncollected_amount")
    assert collected["designation_status"] == "CONFIRMED", "collecting never touches designations"

    final_lines, final_meta = validate_paginated(
        api_client.list_pledge_designations(pledge["id"], admin, {"status": "ACTIVE"})
    )
    assert final_meta["total_count"] == 1
    assert_money(
        final_lines[0]["collected_designated_amount"], "278.25", "line collected in full"
    )
    assert final_lines[0]["collected_designated_amount"] not in ("348.25", 348.25), (
        "adding a second increment onto 69.56 would overshoot the net line"
    )
    final_ledger = validate_success(api_client.get_agency(agency["id"], admin))
    assert_money(final_ledger["designated_passthrough_ytd"], "278.25", "designated_passthrough_ytd")


def test_five_eligible_scores_drop_exactly_one_high_and_one_low_row():
    """PRD 3.7: "When the pool holds five or more scores, a trimmed mean is used:
    exactly one row holding the highest `weighted_score` and exactly one row holding the
    lowest are dropped, with ties at either extreme broken by the earliest `created_at`
    and never by `id`, and each dropped row has its `eligible` flag flipped to false so
    the trim is visible afterwards."

    PRD 3.7: "The eligible pool is every score row filed against the request whose
    author holds a seat on that request's cycle with `conflict_declared` false, and its
    size is written to `eligible_score_count`."

    The five weighted values are 81.50, 80.00, 70.00, 60.00 and 100.00. Trimming the
    100.00 and the 60.00 leaves 231.50 over three survivors, so the base is 77.17; the
    plain mean of all five would be 78.30, and the request's BASIC_NEEDS area does not
    match the cycle's HEALTH focus, so the multiplier is 1.00 and the base survives
    into `composite_score` untouched.

    Design: Corner/calculations/panel_composite_trimmed_mean_drops_one_high_and_one_low_at_five_eligible_scores
    """
    admin = make_admin_headers()
    agency = create_good_standing_agency(
        legal_name="Union Gospel Pantry",
        ein="610000006",
        primary_priority_area="BASIC_NEEDS",
    )
    cycle, panelists = create_open_cycle(
        5,
        cycle_year=2026,
        focus_priority_area="HEALTH",
        opening_undesignated_pool="400000.00",
        max_award_per_agency="90000.00",
        request_window_start="2026-07-01",
        request_window_end="2026-10-01",
    )
    request = create_submitted_request(
        cycle["id"],
        agency["id"],
        requested_amount="60000.00",
        priority_area="BASIC_NEEDS",
        narrative_summary="Six-day-a-week pantry hours and a refrigerated delivery van.",
    )

    triples = ((90, 80, 70), (80, 80, 80), (70, 70, 70), (60, 60, 60), (100, 100, 100))
    expected_weighted = ("81.50", "80.00", "70.00", "60.00", "100.00")
    filed = []
    for panelist, triple, expected in zip(panelists, triples, expected_weighted):
        alignment, evidence, capacity = triple
        score = file_score(
            request["id"],
            panelist["id"],
            priority_alignment_score=alignment,
            outcome_evidence_score=evidence,
            capacity_score=capacity,
        )
        assert_money(score["weighted_score"], expected, "weighted_score at filing")
        filed.append((panelist, expected))

    finalized = validate_success(
        api_client.finalize_review(request["id"], make_allocations_director_headers())
    )

    assert_money(finalized["composite_score"], "77.17", "composite_score")
    assert finalized["composite_score"] not in ("78.30", 78.30), (
        "78.30 is the plain mean of all five scores, which the trim rules out"
    )
    assert finalized["status"] == "PANEL_APPROVED"
    assert finalized["eligible_score_count"] == 5, (
        "the pool size is written before the trim drops its two extremes"
    )
    assert_is_null(finalized["base_award"], "base_award before any award")

    scores, meta = validate_paginated(api_client.list_request_scores(request["id"], admin))
    assert meta["total_count"] == 5, "the trimmed rows stay on the record"
    trimmed = {"100.00", "60.00"}
    for panelist, expected in filed:
        score = require_by(scores, "panelist_id", panelist["id"])
        assert_money(score["weighted_score"], expected, "weighted_score after finalization")
        if expected in trimmed:
            assert score["eligible"] is False, (
                f"the {expected} row is an extreme and must be flipped ineligible"
            )
        else:
            assert score["eligible"] is True, f"the {expected} row survives the trim"

    dropped, dropped_meta = validate_paginated(
        api_client.list_request_scores(request["id"], admin, {"eligible": "false"})
    )
    assert dropped_meta["total_count"] == 2, "exactly one high and one low row are dropped"
    assert {to_decimal(row["weighted_score"]) for row in dropped} == {
        to_decimal("100.00"),
        to_decimal("60.00"),
    }
