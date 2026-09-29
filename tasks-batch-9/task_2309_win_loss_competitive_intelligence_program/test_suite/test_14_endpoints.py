"""
Endpoint surfaces: round trips, action endpoints, bulk sweeps, computed reads and
the declared shape, ordering and paging of the collection reads.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_adoption,
    assert_common_fields,
    assert_contains_id,
    assert_field,
    assert_fields,
    assert_frame_slots,
    assert_id_order,
    assert_money,
    assert_null,
    assert_pagination_meta,
    assert_ratio,
)
from test_helpers.fixtures import WinLossWorld

CLOCK = "2026-08-01T00:00:00.000Z"
GUIDE_TOPICS = ("EVALUATION_CRITERIA", "COMPETITOR_POSITIONING", "PRICING_PERCEPTION")


def _drawn_lost_deal(world: WinLossWorld, **frame_overrides) -> WinLossWorld:
    """One consented 300000.00 ENTERPRISE loss drawn from a sealed frame."""
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame(**frame_overrides)
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    return world


def _spaced_guide_coverage(
    world: WinLossWorld, interview_id: str = None, rating: int = 4
) -> List[Dict[str, Any]]:
    """The three pinned topics, each recorded ten minutes after the previous one."""
    recorded = []
    for index, question_key in enumerate(GUIDE_TOPICS):
        recorded.append(
            world.record_response(
                interview_id=interview_id,
                question_key=question_key,
                verbatim_text=f"Buyer commentary on {question_key}.",
                recorded_at=f"2026-08-10T14:{5 + index * 10:02d}:00.000Z",
                rating=rating,
            )
        )
    return recorded


def _published_card(world: WinLossWorld) -> Dict[str, Any]:
    """A PUBLISHED card resting on one APPROVED positioning claim."""
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.add_claim(
        [world.response_of("COMPETITOR_POSITIONING")["id"]],
        claim_text="Enterprise buyers rate our analytics depth against Northwind",
        claim_type="FEATURE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    return world.publish_battlecard()


def _fully_populated_program(
    world: WinLossWorld, acr_usd: float = 300000.00
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """One program carried end to end, returning its attribution and its gap."""
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor(tier="PRIMARY")
    world.create_two_analysts()
    root = world.create_reason("PRICE", "Price")
    leaf = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    world.create_deal(acr_usd=acr_usd, primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    _spaced_guide_coverage(world)
    gap_response = world.record_response(
        question_key="PRODUCT_GAP",
        verbatim_text="We could not export compliance evidence on a schedule.",
        recorded_at="2026-08-10T14:35:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    attribution = world.create_attribution(leaf["id"])
    world.ratify_attribution(attribution["id"])
    _published_card(world)
    world.assign(sales_rep_user_ref="rep-77")
    gap = world.create_gap(gap_response["id"], gap_summary="Compliance evidence export")
    return attribution, gap


# ---------------------------------------------------------------------------
# Round trips and action endpoints
# ---------------------------------------------------------------------------


def test_a_registered_competitor_reads_back_from_both_shapes(world):
    """The singular read and the program's reverse lookup agree on the same row.

    "A new competitor has `status` `ACTIVE`, all counters at 0 and `win_rate_vs` null."

    "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the
    `meta` object of the envelope."

    Design: Corner/endpoints/competitor_create_read_and_list_round_trip
    """
    world.set_clock(CLOCK)
    world.active_program()
    northwind = world.create_competitor(name="Northwind", tier="PRIMARY")
    world.create_competitor(name="Initech", tier="SECONDARY")

    stored = world.get_competitor(northwind["id"])

    assert_fields(
        stored,
        {
            "id": northwind["id"],
            "name": "Northwind",
            "tier": "PRIMARY",
            "status": "ACTIVE",
            "ratified_loss_count": 0,
            "published_battlecard_count": 0,
            "version": 1,
        },
    )
    assert_null(stored["win_rate_vs"], "win_rate_vs")
    assert_common_fields(stored, expected_version=1)
    items, meta = validate_paginated(
        world.api.list_program_competitors(world.program_id, world.enablement)
    )
    assert_pagination_meta(
        meta, expected_total=2, expected_limit=10, expected_offset=0, expected_has_more=False
    )
    assert [item["id"] for item in items].count(northwind["id"]) == 1, items


def test_repointing_a_deal_re_scores_its_open_gap_and_both_competitors(world):
    """The tier of the new competitor lowers the gap's pressure factor.

    "It recomputes `win_rate_vs` for both the outgoing and the incoming competitor,
    re-scores every product gap in `NEW` or `TRIAGED` whose linked deal set contains this
    deal, and increments the deal's `version`."

    "the sum is multiplied by a competitive pressure factor read off the tier of
    `derived_competitor_id` — 1.30 for `PRIMARY`, 1.10 for `SECONDARY`, 1.00 for
    `EMERGING` and 1.00 when there is no derived competitor"

    Design: Corner/endpoints/patch_deal_competitor_recomputes_the_linked_product_gap_pressure
    """
    _drawn_lost_deal(world)
    primary = world.competitor
    secondary = world.create_competitor(name="Initech", tier="SECONDARY")
    world.schedule_interview()
    _spaced_guide_coverage(world)
    gap_response = world.record_response(
        question_key="PRODUCT_GAP",
        verbatim_text="We could not export compliance evidence on a schedule.",
        recorded_at="2026-08-10T14:35:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    gap = world.create_gap(gap_response["id"], gap_summary="Compliance evidence export")

    body = validate_success(
        world.api.patch_deal(
            world.deal["id"],
            f.deal_patch_payload(primary_competitor_id=secondary["id"]),
            world.admin,
        ),
        200,
    )
    patched = body

    assert_field(patched, "primary_competitor_id", secondary["id"])
    assert_money(patched["acr_usd"], 300000.00, "acr_usd")
    assert_fields(patched, {"segment": "ENTERPRISE", "research_status": "INTERVIEWED"})
    rescored = world.get_gap(gap["id"])
    assert_fields(
        rescored,
        {
            "derived_competitor_id": secondary["id"],
            "linked_deal_count": 1,
            "roadmap_priority_band": "P3",
            "status": "NEW",
        },
    )
    assert_money(rescored["affected_acr_usd"], 0.00, "affected_acr_usd")
    assert_money(rescored["impact_score"], 4.40, "impact_score")
    assert_null(world.get_competitor(primary["id"])["win_rate_vs"], "win_rate_vs")
    assert_ratio(
        world.get_competitor(secondary["id"])["win_rate_vs"], 0.0000, "win_rate_vs"
    )


def test_archiving_a_competitor_is_not_a_delete(world):
    """The row stays addressable and stays in the program's registry.

    "Archiving flips `status` `ACTIVE → ARCHIVED` and increments `version`; from then on,
    sampling scores treat deals pointing at that competitor as contributing no competitor
    weight at all."

    Design: Corner/endpoints/archive_competitor_action_marks_it_archived
    """
    world.set_clock(CLOCK)
    world.active_program()
    competitor = world.create_competitor()

    body = validate_success(
        world.api.archive_competitor(competitor["id"], world.admin), 200
    )
    archived = body

    assert_fields(archived, {"status": "ARCHIVED", "version": 2})
    assert_field(world.get_competitor(competitor["id"]), "status", "ARCHIVED")
    items, meta = validate_paginated(
        world.api.list_program_competitors(world.program_id, world.admin)
    )
    assert_pagination_meta(meta, expected_total=1)
    assert_contains_id(items, competitor["id"])


def test_a_second_sweep_over_the_same_program_expires_nothing(world):
    """The already-expired row is skipped rather than re-expired or refused.

    "The sweep has **skip semantics, not rollback**: assignments that are not past due
    are left untouched and do not cause the call to fail."

    Design: Corner/endpoints/second_enablement_sweep_expires_nothing
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at="2026-08-01T10:05:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth ranked first",
        recorded_at="2026-08-01T10:10:00.000Z",
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price felt high for the tier",
        recorded_at="2026-08-01T10:15:00.000Z",
    )
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    _published_card(world)
    alpha = world.assign(sales_rep_user_ref="rep-alpha", due_at="2026-08-20T00:00:00.000Z")
    beta = world.assign(sales_rep_user_ref="rep-beta", due_at="2026-08-05T00:00:00.000Z")
    world.complete_assignment(
        quiz_score=90, assignment_id=alpha["id"], sales_rep_user_ref="rep-alpha"
    )
    world.set_clock("2026-08-06T00:00:00.000Z")
    first = validate_success(
        world.api.run_enablement_sweep(world.program_id, world.enablement), 200
    )
    assert first["expired_count"] == 1, first

    body = validate_success(
        world.api.run_enablement_sweep(world.program_id, world.enablement), 200
    )
    second = body

    assert second["expired_count"] == 0, second
    assert second["expired_assignment_ids"] == [], second["expired_assignment_ids"]
    assert_field(world.get_assignment(beta["id"]), "status", "EXPIRED")
    assert_field(world.get_assignment(alpha["id"]), "status", "TRAINED")
    assert_adoption(
        world.get_battlecard(), assigned_count=2, trained_count=1, adoption_rate=0.5000
    )


def test_a_pinned_draw_writes_the_association_on_both_sides(world):
    """Naming a deal selects exactly that deal and leaves the other candidate alone.

    "On success each drawn deal has its `sampling_frame_id` set to the frame, its
    `stratum` copied from its own `outcome`, and its `selection_rank_score` stored; the
    frame's selected count for that stratum increases by one per drawn deal and its open
    slots decrease by the same amount, `coverage_ratio` is recomputed, and both the
    frame's `version` and each drawn deal's `version` increment."

    "the batch of deals produced by a sampling draw — return `201 Created`"

    Design: Corner/endpoints/targeted_draw_links_the_named_deal_to_the_frame
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    enterprise = world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    smb = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=120000.00,
        close_date="2026-06-20T00:00:00.000Z",
        segment="SMB",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    world.consented_contact(
        deal_id=smb["id"],
        email="buyer2@brava.test",
        full_name="Cal Dos",
        incentive_eligibility="ELIGIBLE",
    )
    world.create_frame(quota_won=0, quota_lost=2, quota_no_decision=0)
    world.seal_frame()

    body = validate_success(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("LOST", deal_id=enterprise["id"]),
            world.analyst_headers,
        ),
        201,
    )
    drawn = body

    assert len(drawn) == 1, drawn
    assert_id_order(drawn, [enterprise["id"]])
    selected = world.get_deal(enterprise["id"])
    assert_fields(
        selected,
        {
            "sampling_frame_id": world.frame["id"],
            "stratum": "LOST",
            "research_status": "SELECTED",
        },
    )
    assert_ratio(selected["selection_rank_score"], 0.9956, "selection_rank_score")
    untouched = world.get_deal(smb["id"])
    assert_field(untouched, "research_status", "NOT_SELECTED")
    assert_null(untouched["sampling_frame_id"], "sampling_frame_id")
    assert_null(untouched["selection_rank_score"], "selection_rank_score")
    assert_frame_slots(
        world.get_frame(), selected_lost=1, open_lost=1, coverage=0.5000
    )


def test_closing_a_frame_freezes_its_counters_where_the_draw_left_them(world):
    """A closed wave keeps its audit trail: nothing is returned to the pool.

    "A `ResearchAnalyst` may close a frame from either `SEALED` or `SUSPENDED`, which
    freezes `coverage_ratio` at its current value and increments `version`"

    Design: Corner/endpoints/closing_a_sealed_frame_freezes_it_without_disturbing_its_counters
    """
    _drawn_lost_deal(world, quota_won=0, quota_lost=1, quota_no_decision=0)
    after_draw = world.get_frame()

    body = validate_success(
        world.api.close_frame(world.frame["id"], world.analyst_headers), 200
    )
    closed = body

    assert_field(closed, "status", "CLOSED")
    assert_frame_slots(closed, selected_lost=1, open_lost=0, coverage=1.0000)
    assert closed["version"] > after_draw["version"], (
        f"version must advance past {after_draw['version']}, got {closed['version']}"
    )
    retained = world.get_deal()
    assert_fields(
        retained,
        {"research_status": "SELECTED", "sampling_frame_id": world.frame["id"]},
    )


# ---------------------------------------------------------------------------
# Computed and conditional endpoints
# ---------------------------------------------------------------------------


def test_a_window_ending_before_the_close_date_reports_nothing(world):
    """The same attribution counts in one window and is invisible in the other.

    "The set is then narrowed to attributions whose deal has `outcome` `LOST` or
    `NO_DECISION` and whose deal's `close_date` is on or after `window_start` and
    strictly before `window_end`"

    "a segment whose total is zero is omitted from the response entirely"

    Design: Corner/endpoints/loss_trends_window_excludes_a_close_date_before_window_start
    """
    attribution, _ = _fully_populated_program(world)

    body = validate_success(
        world.api.get_loss_trends(
            world.program_id,
            world.admin,
            f.loss_trends_params(
                window_start="2026-01-01T00:00:00.000Z",
                window_end="2026-04-01T00:00:00.000Z",
            ),
        ),
        200,
    )
    empty = body

    assert_fields(empty, {"basis": "RATIFIED_ONLY", "attribution_count": 0})
    assert len(empty["segments"]) == 0, empty["segments"]
    covering = validate_success(
        world.api.get_loss_trends(
            world.program_id,
            world.admin,
            f.loss_trends_params(
                window_start="2026-04-01T00:00:00.000Z",
                window_end="2026-07-01T00:00:00.000Z",
            ),
        ),
        200,
    )
    assert_field(covering, "attribution_count", 1)
    assert_ratio(covering["segments"][0]["rows"][0]["share"], 1.0000, "share")
    stored = world.get_attribution(attribution["id"])
    assert_field(stored, "status", "RATIFIED")
    assert_money(stored["confidence_score"], 0.60, "confidence_score")


def test_a_gap_promotes_when_band_program_state_and_adoption_all_hold(world):
    """Fully trained field, ACTIVE program and a P1 band together open the gate.

    "Promotion moves the gap `ACCEPTED → PROMOTED` and records the external
    `roadmap_epic_ref`."

    "that competitor's most recently published card must have an `adoption_rate` of at
    least 0.6000, or the promotion is refused with `ERR_ADOPTION_BELOW_THRESHOLD`"

    Design: Corner/endpoints/promote_succeeds_when_band_program_state_and_adoption_all_hold
    """
    _, gap = _fully_populated_program(world, acr_usd=500000.00)
    second = world.assign(sales_rep_user_ref="rep-beta")
    world.complete_assignment(quiz_score=90, sales_rep_user_ref="rep-77")
    world.complete_assignment(
        quiz_score=90, assignment_id=second["id"], sales_rep_user_ref="rep-beta"
    )
    world.triage_gap("ACCEPT", gap_id=gap["id"])

    body = validate_success(
        world.api.promote_product_gap(
            gap["id"], f.promote_payload("EPIC-4412"), world.product
        ),
        200,
    )
    promoted = body

    assert_fields(
        promoted,
        {
            "status": "PROMOTED",
            "roadmap_epic_ref": "EPIC-4412",
            "roadmap_priority_band": "P1",
        },
    )
    assert_money(promoted["impact_score"], 57.20, "impact_score")
    assert_adoption(
        world.get_battlecard(), assigned_count=2, trained_count=2, adoption_rate=1.0000
    )
    items, meta = validate_paginated(world.api.list_product_gaps(world.admin))
    assert_pagination_meta(meta, expected_total=1)
    assert_field(items[0], "status", "PROMOTED")


# ---------------------------------------------------------------------------
# Collection reads
# ---------------------------------------------------------------------------


def test_nested_collection_reads_page_and_keep_their_declared_order(world):
    """Each nested read is scoped to its parent, ordered as declared and pageable.

    "both interview-response collections order by `recorded_at` ascending"

    "`limit` caps the number of rows returned; it defaults to 10, its minimum accepted
    value is 1 and its maximum is 100. `offset` is the number of rows to skip; it
    defaults to 0 and its minimum is 0."

    Design: Corner/endpoints/nested_collection_reads_filter_paginate_and_keep_their_declared_order
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    first_deal = world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    second_deal = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=120000.00,
        close_date="2026-06-20T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    second_contact = world.consented_contact(
        deal_id=second_deal["id"],
        email="buyer2@brava.test",
        full_name="Cal Dos",
        incentive_eligibility="ELIGIBLE",
    )
    world.create_frame(quota_won=0, quota_lost=2, quota_no_decision=0)
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    interview = world.schedule_interview(deal_id=first_deal["id"])
    covered = _spaced_guide_coverage(world, interview_id=interview["id"])
    other_interview = world.schedule_interview(
        deal_id=second_deal["id"],
        buyer_contact_id=second_contact["id"],
        scheduled_start_at="2026-08-12T14:00:00.000Z",
        scheduled_end_at="2026-08-12T15:00:00.000Z",
    )
    world.record_response(
        interview_id=other_interview["id"],
        question_key="PRODUCT_GAP",
        verbatim_text="Scheduled exports cannot target our own bucket.",
        recorded_at="2026-08-12T14:05:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        interview_id=interview["id"],
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    card = _published_card(world)
    assignment = world.assign(sales_rep_user_ref="rep-77")

    page, page_meta = validate_paginated(
        world.api.list_interview_responses(
            interview["id"], world.analyst_headers, {"limit": 2, "offset": 0}
        )
    )
    assert len(page) == 2, page
    assert_pagination_meta(
        page_meta,
        expected_total=3,
        expected_limit=2,
        expected_offset=0,
        expected_has_more=True,
    )
    assert_id_order(page, [covered[0]["id"], covered[1]["id"]])
    assert_field(page[0], "question_key", "EVALUATION_CRITERIA")
    _, flat_meta = validate_paginated(
        world.api.list_interview_responses_flat(world.admin)
    )
    assert_pagination_meta(flat_meta, expected_total=4)
    contacts, contact_meta = validate_paginated(
        world.api.list_deal_buyer_contacts(first_deal["id"], world.analyst_headers)
    )
    assert_pagination_meta(
        contact_meta, expected_total=1, expected_limit=10, expected_offset=0
    )
    assert_field(contacts[0], "consent_status", "GRANTED")
    claims, claim_meta = validate_paginated(
        world.api.list_claims(card["id"], world.legal)
    )
    assert_pagination_meta(
        claim_meta, expected_total=1, expected_limit=10, expected_has_more=False
    )
    assert_field(claims[0], "legal_status", "APPROVED")
    assignments, assignment_meta = validate_paginated(
        world.api.list_battlecard_assignments(card["id"], world.enablement)
    )
    assert_pagination_meta(
        assignment_meta, expected_total=1, expected_limit=10, expected_offset=0
    )
    assert_id_order(assignments, [assignment["id"]])
    assert_field(assignments[0], "sales_rep_user_ref", "rep-77")


def test_every_flat_collection_reports_its_own_populated_program(world):
    """One end-to-end program is read back through all fifteen top-level reads.

    "the flat buyer-contact collection exposes an `email` filter that matches
    case-insensitively precisely so that cross-deal view is observable"

    "`ratified_loss_count` is the number of deals naming it as primary competitor whose
    `outcome` is `LOST` or `NO_DECISION` and whose `attribution_status` is `RATIFIED`."

    Design: Corner/endpoints/flat_collection_reads_are_filterable_across_every_top_level_resource
    """
    attribution, gap = _fully_populated_program(world)

    _, analysts_meta = validate_paginated(
        world.api.list_program_analysts(world.program_id, world.admin)
    )
    assert_pagination_meta(analysts_meta, expected_total=2)
    frames, frames_meta = validate_paginated(
        world.api.list_program_sampling_frames(world.program_id, world.admin)
    )
    assert_pagination_meta(frames_meta, expected_total=1)
    assert_field(frames[0], "status", "SEALED")
    competitors, competitors_meta = validate_paginated(
        world.api.list_competitors(world.admin)
    )
    assert_pagination_meta(competitors_meta, expected_total=1)
    assert_id_order(competitors, [world.competitor["id"]])
    assert_field(competitors[0], "tier", "PRIMARY")
    assert_field(world.get_competitor(), "ratified_loss_count", 1)
    flat_analysts, flat_analysts_meta = validate_paginated(
        world.api.list_analysts(world.admin)
    )
    assert_pagination_meta(flat_analysts_meta, expected_total=2)
    for analyst in flat_analysts:
        assert_field(analyst, "employment_type", "INTERNAL")
    flat_frames, flat_frames_meta = validate_paginated(
        world.api.list_sampling_frames(world.admin)
    )
    assert_pagination_meta(flat_frames_meta, expected_total=1)
    assert_field(flat_frames[0], "selection_basis", "STRATIFIED_BY_SEGMENT")
    contacts, contacts_meta = validate_paginated(
        world.api.list_buyer_contacts(
            world.analyst_headers, {"email": "BUYER1@ACME.TEST"}
        )
    )
    assert_pagination_meta(contacts_meta, expected_total=1)
    assert_id_order(contacts, [world.contact["id"]])
    interviews, interviews_meta = validate_paginated(
        world.api.list_interviews(world.analyst_headers)
    )
    assert_pagination_meta(interviews_meta, expected_total=1)
    assert_field(interviews[0], "status", "COMPLETED")
    responses, responses_meta = validate_paginated(
        world.api.list_interview_responses_flat(world.product)
    )
    assert_pagination_meta(responses_meta, expected_total=4)
    assert_contains_id(responses, world.responses[-1]["id"])
    reasons, reasons_meta = validate_paginated(world.api.list_loss_reasons(world.admin))
    assert_pagination_meta(reasons_meta, expected_total=2)
    assert_field(reasons[0], "depth", 1)
    assert_fields(reasons[1], {"depth": 2, "is_leaf": True})
    attributions, attributions_meta = validate_paginated(
        world.api.list_loss_attributions(world.analyst_headers)
    )
    assert_pagination_meta(attributions_meta, expected_total=1)
    assert_id_order(attributions, [attribution["id"]])
    assert_field(attributions[0], "status", "RATIFIED")
    cards, cards_meta = validate_paginated(world.api.list_battlecards(world.enablement))
    assert_pagination_meta(cards_meta, expected_total=1)
    assert_id_order(cards, [world.battlecard["id"]])
    assert_field(cards[0], "status", "PUBLISHED")
    claims, claims_meta = validate_paginated(
        world.api.list_battlecard_claims(world.legal)
    )
    assert_pagination_meta(claims_meta, expected_total=1)
    assert_id_order(claims, [world.claim["id"]])
    assert_field(claims[0], "substantiation_level", "ANECDOTAL")
    assignments, assignments_meta = validate_paginated(
        world.api.list_enablement_assignments(world.enablement)
    )
    assert_pagination_meta(assignments_meta, expected_total=1)
    assert_fields(
        assignments[0], {"status": "ASSIGNED", "sales_rep_user_ref": "rep-77"}
    )
    gaps, gaps_meta = validate_paginated(world.api.list_product_gaps(world.product))
    assert_pagination_meta(gaps_meta, expected_total=1)
    assert_id_order(gaps, [gap["id"]])
    assert_money(gaps[0]["impact_score"], 36.40, "impact_score")
    assert_field(gaps[0], "roadmap_priority_band", "P2")
