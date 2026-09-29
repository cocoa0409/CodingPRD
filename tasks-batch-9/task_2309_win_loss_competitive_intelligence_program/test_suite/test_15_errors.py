"""
Error reachability: every not-found code answers its own unresolved path variable,
and every action refuses the state it is not declared from.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ANALYST_NOT_FOUND,
    ERR_ASSIGNMENT_STATE_INVALID,
    ERR_ATTRIBUTION_STATE_INVALID,
    ERR_BATTLECARD_CLAIM_NOT_FOUND,
    ERR_BATTLECARD_NOT_FOUND,
    ERR_BUYER_CONTACT_NOT_FOUND,
    ERR_CLAIM_STATE_INVALID,
    ERR_DEAL_STATE_INVALID,
    ERR_ENABLEMENT_ASSIGNMENT_NOT_FOUND,
    ERR_FRAME_STATE_INVALID,
    ERR_INTERVIEW_NOT_FOUND,
    ERR_INTERVIEW_RESPONSE_NOT_FOUND,
    ERR_LOSS_ATTRIBUTION_NOT_FOUND,
    ERR_LOSS_REASON_NOT_FOUND,
    ERR_PRODUCT_GAP_NOT_FOUND,
    ERR_PRODUCT_GAP_STATE_INVALID,
    ERR_SAMPLING_FRAME_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_adoption,
    assert_field,
    assert_fields,
    assert_frame_slots,
    assert_null,
)
from test_helpers.fixtures import WinLossWorld
from test_helpers.test_users import make_sales_rep_headers

CLOCK = "2026-08-01T00:00:00.000Z"


def _drawn_lost_deal(world: WinLossWorld) -> WinLossWorld:
    """One consented 300000.00 ENTERPRISE loss drawn from a sealed frame."""
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    return world


def _completed_interview(world: WinLossWorld) -> WinLossWorld:
    """The drawn deal carried to `INTERVIEWED` through a fully covered interview."""
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    return world


# ---------------------------------------------------------------------------
# Unresolved path variables
# ---------------------------------------------------------------------------


def test_an_unissued_analyst_id_is_a_not_found(world):
    """A well-formed identifier that was never minted is an existence failure.

    "Each unresolvable variable maps to its own not-found code"

    Design: Corner/errors/analyst_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_analyst(NON_EXISTENT_UUID, world.admin),
        ERR_ANALYST_NOT_FOUND,
        404,
    )


def test_an_unissued_buyer_contact_id_is_a_not_found(world):
    """The flat contact read answers with the contact's own code.

    "Each unresolvable variable maps to its own not-found code"

    Design: Corner/errors/buyer_contact_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_buyer_contact(NON_EXISTENT_UUID, world.admin),
        ERR_BUYER_CONTACT_NOT_FOUND,
        404,
    )


def test_an_unissued_sampling_frame_id_is_a_not_found(world):
    """No frame exists at all, so the probe cannot collide with a real wave.

    "5. Every path variable resolves — the matching not-found code, on every operation
    with path variables."

    Design: Corner/errors/sampling_frame_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_sampling_frame(NON_EXISTENT_UUID, world.admin),
        ERR_SAMPLING_FRAME_NOT_FOUND,
        404,
    )


def test_an_unissued_interview_id_is_a_not_found(world):
    """The interview read reports the interview's own code.

    "Each unresolvable variable maps to its own not-found code"

    Design: Corner/errors/interview_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_interview(NON_EXISTENT_UUID, world.admin),
        ERR_INTERVIEW_NOT_FOUND,
        404,
    )


def test_an_unissued_interview_response_id_is_a_not_found(world):
    """Recorded evidence has its own not-found code, distinct from the interview's.

    "Each unresolvable variable maps to its own not-found code"

    Design: Corner/errors/interview_response_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_interview_response(NON_EXISTENT_UUID, world.admin),
        ERR_INTERVIEW_RESPONSE_NOT_FOUND,
        404,
    )


def test_an_unissued_loss_reason_id_is_a_not_found(world):
    """A taxonomy node that was never created is a 404, not an empty success.

    "5. Every path variable resolves — the matching not-found code, on every operation
    with path variables."

    Design: Corner/errors/loss_reason_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_loss_reason(NON_EXISTENT_UUID, world.admin),
        ERR_LOSS_REASON_NOT_FOUND,
        404,
    )


def test_an_unissued_loss_attribution_id_is_a_not_found(world):
    """The attribution read reports the attribution's own code.

    "Each unresolvable variable maps to its own not-found code"

    Design: Corner/errors/loss_attribution_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_loss_attribution(NON_EXISTENT_UUID, world.admin),
        ERR_LOSS_ATTRIBUTION_NOT_FOUND,
        404,
    )


def test_an_unissued_battlecard_id_is_a_not_found(world):
    """The card read reports the card's own code.

    "Each unresolvable variable maps to its own not-found code"

    Design: Corner/errors/battlecard_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_battlecard(NON_EXISTENT_UUID, world.admin),
        ERR_BATTLECARD_NOT_FOUND,
        404,
    )


def test_an_unissued_claim_id_is_a_not_found(world):
    """A claim is addressed on its own flat path and answers with the claim's code.

    "a claim whose `battlecard_id` differs from the card in the path yields
    `ERR_BATTLECARD_CLAIM_NOT_FOUND`"

    Design: Corner/errors/battlecard_claim_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_battlecard_claim(NON_EXISTENT_UUID, world.admin),
        ERR_BATTLECARD_CLAIM_NOT_FOUND,
        404,
    )


def test_an_unissued_product_gap_id_is_a_not_found(world):
    """The roadmap-side read reports the gap's own code.

    "Each unresolvable variable maps to its own not-found code"

    Design: Corner/errors/product_gap_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_product_gap(NON_EXISTENT_UUID, world.admin),
        ERR_PRODUCT_GAP_NOT_FOUND,
        404,
    )


def test_an_unissued_enablement_assignment_id_is_a_not_found(world):
    """The assignment read reports the assignment's own code.

    "5. Every path variable resolves — the matching not-found code, on every operation
    with path variables."

    Design: Corner/errors/enablement_assignment_lookup_with_unused_uuid_not_found
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.get_enablement_assignment(NON_EXISTENT_UUID, world.admin),
        ERR_ENABLEMENT_ASSIGNMENT_NOT_FOUND,
        404,
    )


# ---------------------------------------------------------------------------
# Transitions that do not exist from the current state
# ---------------------------------------------------------------------------


def test_a_second_seal_does_not_re_seed_the_slots(world):
    """Seal is declared from `DRAFT` only, so a repeat is a state failure.

    "Sealing moves the frame `DRAFT → SEALED` and requires that the frame is currently
    `DRAFT`, that the owning program's `status` is `ACTIVE`, and that the three quotas
    sum to at least 1."

    Design: Corner/errors/sealing_an_already_sealed_frame_rejected
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_analyst()
    world.create_frame(quota_won=0, quota_lost=1, quota_no_decision=0)
    world.seal_frame()

    validate_error(
        world.api.seal_frame(world.frame["id"], world.analyst_headers),
        ERR_FRAME_STATE_INVALID,
        409,
    )

    frame = world.get_frame()
    assert_field(frame, "status", "SEALED")
    assert_frame_slots(frame, selected_lost=0, open_lost=1, coverage=0.0000)


def test_a_deal_that_was_never_drawn_cannot_be_handed_back(world):
    """Declining is a compensating transition and needs a selection to compensate.

    "Declining a selection moves the deal `SELECTED → DECLINED` and is permitted only
    while no interview on that deal is in `SCHEDULED` or `COMPLETED` and while the owning
    frame's `status` is `SEALED` or `SUSPENDED`"

    Design: Corner/errors/decline_selection_on_a_deal_that_was_never_drawn_rejected
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    deal = world.create_deal(primary_competitor_id=world.competitor["id"])

    validate_error(
        world.api.decline_selection(
            deal["id"],
            world.analyst_headers,
            f.decline_selection_payload(decline_note="buyer unreachable"),
        ),
        ERR_DEAL_STATE_INVALID,
        409,
    )

    stored = world.get_deal()
    assert_fields(stored, {"research_status": "NOT_SELECTED", "version": 1})
    assert_null(stored["sampling_frame_id"], "sampling_frame_id")


def test_a_second_ratification_does_not_double_count_the_reason(world):
    """Ratify is declared from `PROVISIONAL` only, so the ledger runs once.

    "A second `ResearchAnalyst` ratifies, moving the attribution `PROVISIONAL →
    RATIFIED` — and a ratification attempted on an attribution that is `RATIFIED` or
    `SUPERSEDED` is refused with `ERR_ATTRIBUTION_STATE_INVALID`."

    Design: Corner/errors/ratifying_an_already_ratified_attribution_rejected
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_two_analysts()
    root = world.create_reason("PRICE", "Price")
    leaf = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    _completed_interview(world)
    attribution = world.create_attribution(leaf["id"])
    world.ratify_attribution(attribution["id"])

    validate_error(
        world.api.ratify_loss_attribution(
            attribution["id"], world.headers_for(world.analyst2)
        ),
        ERR_ATTRIBUTION_STATE_INVALID,
        409,
    )

    assert_field(world.get_attribution(attribution["id"]), "status", "RATIFIED")
    assert_field(world.get_reason(leaf["id"]), "ratified_attribution_count", 1)
    assert_field(world.get_deal(), "attribution_status", "RATIFIED")


def test_an_approved_claim_refuses_a_second_decision(world):
    """The card is still in review, so only the claim's own state can be at fault.

    "a claim whose current `legal_status` does not admit the requested decision is
    refused with `ERR_CLAIM_STATE_INVALID` — `REJECTED` is terminal for a claim, and a
    `CONDITIONAL` claim accepts only a subsequent `APPROVE`"

    Design: Corner/errors/second_legal_decision_on_an_already_approved_claim_rejected
    """
    _drawn_lost_deal(world)
    _completed_interview(world)
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    first = world.add_claim(
        [world.response_of("COMPETITOR_POSITIONING")["id"]],
        claim_text="Buyers weigh security depth above price at parity scope",
        claim_type="REFERENCE",
    )
    second = world.add_claim(
        [world.response_of("PRICING_PERCEPTION")["id"]],
        claim_text="Buyers read our list price as fair for the tier",
        claim_type="REFERENCE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE", claim_id=first["id"])

    validate_error(
        world.api.legal_decision(
            world.battlecard["id"],
            first["id"],
            f.legal_decision_payload("APPROVE"),
            world.legal,
        ),
        ERR_CLAIM_STATE_INVALID,
        409,
    )

    assert_field(world.get_claim(first["id"]), "legal_status", "APPROVED")
    assert_field(world.get_claim(second["id"]), "legal_status", "PENDING")
    assert_field(world.get_battlecard(), "status", "LEGAL_REVIEW")


def test_state_outranks_the_priority_band_on_promotion(world):
    """The gap is both in the wrong state and in the wrong band; state answers.

    "The gap must be `ACCEPTED`, its `roadmap_priority_band` must be `P0` or `P1`, and
    the owning program's `status` must be `ACTIVE`."

    "13. The entity is in a state from which the requested transition exists"

    Design: Corner/errors/promoting_a_gap_still_in_new_rejected
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
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

    validate_error(
        world.api.promote_product_gap(
            gap["id"], f.promote_payload("EPIC-9001"), world.product
        ),
        ERR_PRODUCT_GAP_STATE_INVALID,
        409,
    )

    stored = world.get_gap(gap["id"])
    assert_fields(stored, {"status": "NEW", "roadmap_priority_band": "P3"})
    assert_null(stored["roadmap_epic_ref"], "roadmap_epic_ref")


def test_a_trained_assignment_refuses_a_replayed_pass(world):
    """A second passing attempt cannot inflate the card's adoption.

    "The assignment must be `ASSIGNED` or `FAILED` — a `TRAINED` or `EXPIRED` assignment
    refuses further attempts with `ERR_ASSIGNMENT_STATE_INVALID`"

    Design: Corner/errors/completing_an_already_trained_assignment_rejected
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
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.add_claim(
        [world.response_of("COMPETITOR_POSITIONING")["id"]],
        claim_text="Enterprise buyers rate our analytics depth against Northwind",
        claim_type="FEATURE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    world.publish_battlecard()
    assignment = world.assign(
        sales_rep_user_ref="rep-77", due_at="2026-09-01T00:00:00.000Z"
    )
    world.complete_assignment(
        quiz_score=80, assignment_id=assignment["id"], sales_rep_user_ref="rep-77"
    )

    validate_error(
        world.api.complete_assignment(
            assignment["id"],
            f.assignment_complete_payload(92),
            make_sales_rep_headers("rep-77"),
        ),
        ERR_ASSIGNMENT_STATE_INVALID,
        409,
    )

    stored = world.get_assignment(assignment["id"])
    assert_fields(
        stored, {"status": "TRAINED", "attempt_count": 1, "quiz_score": 80}
    )
    assert_adoption(
        world.get_battlecard(), assigned_count=1, trained_count=1, adoption_rate=1.0000
    )
