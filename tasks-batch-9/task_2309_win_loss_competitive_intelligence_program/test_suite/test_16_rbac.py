"""
Who may act: each role on its own exclusive operations, the shared read surface,
the refusals that keep authorship and clearance apart, and the per-user duty checks.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_adoption,
    assert_field,
    assert_fields,
    assert_null,
    assert_pagination_meta,
)
from test_helpers.fixtures import WinLossWorld
from test_helpers.test_users import make_sales_rep_headers

CLOCK = "2026-08-01T00:00:00.000Z"


def _drawn_lost_deal(world: WinLossWorld) -> WinLossWorld:
    """One consented loss drawn from a sealed frame, all by the correct roles."""
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


def _interviewed_deal(world: WinLossWorld) -> WinLossWorld:
    """The drawn deal carried to `INTERVIEWED` with a PRODUCT_GAP verbatim on file."""
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.record_response(
        question_key="PRODUCT_GAP",
        verbatim_text="Scheduled evidence exports could not reach our own bucket.",
        recorded_at="2026-08-10T14:35:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    return world


def _card_in_legal_review(world: WinLossWorld) -> WinLossWorld:
    """A DRAFT card with one publishable FEATURE claim, submitted for clearance."""
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.add_claim(
        [world.response_of("COMPETITOR_POSITIONING")["id"]],
        claim_text="Enterprise buyers rate our analytics depth against Northwind",
        claim_type="FEATURE",
    )
    world.submit_legal()
    return world


def _published_card(world: WinLossWorld) -> WinLossWorld:
    """The cleared card distributed by the manager who owns publication."""
    _card_in_legal_review(world)
    world.decide_claim("APPROVE")
    world.publish_battlecard()
    return world


def _provisional_attribution(world: WinLossWorld, author=None):
    """A two-level taxonomy and one PROVISIONAL attribution on the interviewed deal."""
    root = world.create_reason("PRICE", "Price")
    leaf = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    attribution = world.create_attribution(leaf["id"], analyst=author)
    return attribution, leaf


# ---------------------------------------------------------------------------
# The exclusive operations, exercised by their own roles
# ---------------------------------------------------------------------------


def test_the_pipeline_runs_only_when_every_role_holds_its_own_leg(world):
    """Six roles in sequence: any mis-scoped list breaks the chain at that step.

    "A `LegalReviewer` is the sole authority over claim decisions and can neither author
    claims nor submit a card for review, so legal approval can never collapse into
    self-approval."

    "A `SalesRep` is purely a consumer of enablement content and records its own training
    attempts"

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations_end_to_end
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    _published_card(world)
    assignment = world.assign(
        sales_rep_user_ref="rep-77", due_at="2026-09-01T00:00:00.000Z"
    )
    gap = world.create_gap(world.response_of("PRODUCT_GAP")["id"])
    world.triage_gap("NEEDS_EVIDENCE", gap_id=gap["id"])

    completed = validate_success(
        world.api.complete_assignment(
            assignment["id"],
            f.assignment_complete_payload(80),
            make_sales_rep_headers("rep-77"),
        ),
        200,
    )

    assert_field(completed, "status", "TRAINED")
    assert_field(world.refresh_program(), "status", "ACTIVE")
    assert_field(world.get_deal(), "research_status", "INTERVIEWED")
    card = world.get_battlecard()
    assert_field(card, "status", "PUBLISHED")
    assert_adoption(card, assigned_count=1, trained_count=1, adoption_rate=1.0000)
    assert_field(world.get_claim(), "legal_status", "APPROVED")
    assert_field(world.get_gap(gap["id"]), "status", "TRIAGED")


def test_every_role_reads_the_published_card_identically(world):
    """The retrieval surface is shared, so no role sees a narrowed projection.

    "All six roles may read every retrieval operation and may set the logical clock."

    Design: Corner/rbac/every_role_can_read_the_published_battlecard
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    _published_card(world)
    card_id = world.battlecard["id"]

    readings = [
        validate_success(world.api.get_battlecard(card_id, headers), 200)
        for headers in (
            world.admin,
            world.analyst_headers,
            world.legal,
            world.enablement,
            world.product,
            world.rep,
        )
    ]

    reference = readings[0]
    for reading in readings:
        assert "error_id" not in reading, f"read leaked an error body: {reading}"
        assert_field(reading, "status", "PUBLISHED")
        assert reading["risk_index_final"] == reference["risk_index_final"], (
            "every role must see the same risk_index_final, got "
            f"{reading['risk_index_final']} vs {reference['risk_index_final']}"
        )


# ---------------------------------------------------------------------------
# A recognised role that is not on the operation's list
# ---------------------------------------------------------------------------


def test_a_sales_rep_cannot_import_a_deal(world):
    """The research corpus is closed to the sales side, which is the point of it.

    "the role is deliberately excluded from every research and authoring operation, which
    is what makes analyst independence from the sales team enforceable in the first place"

    Design: Corner/rbac/sales_rep_cannot_import_a_deal_returns_4xx
    """
    world.set_clock(CLOCK)
    world.active_program()

    validate_error(
        world.api.create_deal(
            f.deal_payload(world.program_id, crm_deal_ref="CRM-9001"), world.rep
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, meta = validate_paginated(world.api.list_deals(world.admin))
    assert_pagination_meta(meta, expected_total=0)


def test_an_enablement_manager_cannot_author_a_battlecard(world):
    """Distribution does not imply authorship, even downstream of it.

    "An `EnablementManager` publishes cleared cards, distributes them to the field and
    runs the adoption sweep, but cannot author or legally clear a card"

    Design: Corner/rbac/enablement_manager_cannot_author_a_battlecard_returns_4xx
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()

    validate_error(
        world.api.create_battlecard(
            f.battlecard_payload(world.competitor["id"]), world.enablement
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, meta = validate_paginated(world.api.list_battlecards(world.admin))
    assert_pagination_meta(meta, expected_total=0)


def test_the_claim_author_never_reaches_the_duty_check_on_a_decision(world):
    """The role gate answers first, so this is not a duty failure.

    "3. The role is on the operation's authorized list — `ERR_ROLE_NOT_PERMITTED`, on
    every operation."

    "A `LegalReviewer` is the sole authority over claim decisions"

    Design: Corner/rbac/research_analyst_cannot_decide_its_own_claim_returns_4xx
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    _card_in_legal_review(world)

    validate_error(
        world.api.legal_decision(
            world.battlecard["id"],
            world.claim["id"],
            f.legal_decision_payload("APPROVE"),
            world.analyst_headers,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assert_field(world.get_claim(), "legal_status", "PENDING")
    assert_field(world.get_battlecard(), "status", "LEGAL_REVIEW")


def test_the_author_cannot_publish_its_own_cleared_card(world):
    """Only the role gate stands between this APPROVED card and the field.

    "Publication belongs to the `EnablementManager` and moves a card `APPROVED →
    PUBLISHED`."

    Design: Corner/rbac/research_analyst_cannot_publish_an_approved_battlecard_returns_4xx
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    _card_in_legal_review(world)
    world.decide_claim("APPROVE")

    validate_error(
        world.api.publish_battlecard(world.battlecard["id"], world.analyst_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    card = world.get_battlecard()
    assert_field(card, "status", "APPROVED")
    assert_null(card["published_at"], "published_at")


def test_the_analyst_who_surfaced_a_gap_cannot_grade_it(world):
    """Roadmap triage sits on the other side of the wall from the research finding.

    "A `ProductManager` owns the roadmap side: product-gap intake, triage and promotion."

    Design: Corner/rbac/research_analyst_cannot_triage_a_product_gap_returns_4xx
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    gap = world.create_gap(world.response_of("PRODUCT_GAP")["id"])

    validate_error(
        world.api.triage_product_gap(
            gap["id"], f.triage_payload("ACCEPT"), world.analyst_headers
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assert_field(world.get_gap(gap["id"]), "status", "NEW")


def test_a_manager_cannot_sit_the_quiz_for_a_rep(world):
    """Adoption cannot be manufactured by the role that measures it.

    "3. The role is on the operation's authorized list — `ERR_ROLE_NOT_PERMITTED`, on
    every operation."

    "A `SalesRep` records a training attempt by supplying a `quiz_score`, an integer from
    0 through 100 inclusive."

    Design: Corner/rbac/enablement_manager_cannot_complete_a_reps_assignment_returns_4xx
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    _published_card(world)
    assignment = world.assign(
        sales_rep_user_ref="rep-77", due_at="2026-09-01T00:00:00.000Z"
    )

    validate_error(
        world.api.complete_assignment(
            assignment["id"], f.assignment_complete_payload(100), world.enablement
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assert_fields(
        world.get_assignment(assignment["id"]),
        {"status": "ASSIGNED", "attempt_count": 0},
    )
    assert_adoption(
        world.get_battlecard(), assigned_count=1, trained_count=0, adoption_rate=0.0000
    )


# ---------------------------------------------------------------------------
# Right role, wrong person
# ---------------------------------------------------------------------------


def test_the_author_of_an_attribution_cannot_ratify_it(world):
    """Role and identity both pass; four-eyes is enforced per user.

    "The acting `X-User-ID` may be neither the attribution's `authored_by_analyst_id` nor
    the `analyst_id` of any `COMPLETED` interview on that deal; either conflict yields
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_author_of_an_attribution_cannot_ratify_it_rejected
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    attribution, leaf = _provisional_attribution(world)

    validate_error(
        world.api.ratify_loss_attribution(attribution["id"], world.analyst_headers),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    stored = world.get_attribution(attribution["id"])
    assert_field(stored, "status", "PROVISIONAL")
    assert_null(stored["ratified_by_analyst_id"], "ratified_by_analyst_id")
    assert_field(world.get_reason(leaf["id"]), "ratified_attribution_count", 0)
    assert_field(world.get_deal(), "attribution_status", "PROVISIONAL")


def test_the_analyst_who_heard_the_buyer_cannot_ratify_the_attribution(world):
    """The second barred pairing: authorship is clean but the interviewer is not.

    "The acting `X-User-ID` may be neither the attribution's `authored_by_analyst_id` nor
    the `analyst_id` of any `COMPLETED` interview on that deal; either conflict yields
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_analyst_who_ran_the_interview_cannot_ratify_the_attribution_rejected
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_two_analysts()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    _interviewed_deal(world)
    attribution, leaf = _provisional_attribution(world, author=world.analyst2)

    validate_error(
        world.api.ratify_loss_attribution(attribution["id"], world.analyst_headers),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    stored = world.get_attribution(attribution["id"])
    assert_fields(
        stored,
        {"status": "PROVISIONAL", "authored_by_analyst_id": world.analyst2["id"]},
    )
    assert_field(world.get_reason(leaf["id"]), "ratified_attribution_count", 0)


def test_a_rep_cannot_complete_another_reps_assignment(world):
    """The role is the only one on this endpoint, so identity must decide.

    "it is compared to the plain string `sales_rep_user_ref` stored on the
    `EnablementAssignment` being acted on: a rep completing someone else's assignment is
    rejected with `ERR_SEGREGATION_OF_DUTIES`"

    Design: Corner/rbac/a_rep_cannot_complete_another_reps_assignment_rejected
    """
    _drawn_lost_deal(world)
    _interviewed_deal(world)
    _published_card(world)
    first = world.assign(
        sales_rep_user_ref="rep-77", due_at="2026-09-01T00:00:00.000Z"
    )
    second = world.assign(
        sales_rep_user_ref="rep-88", due_at="2026-09-01T00:00:00.000Z"
    )

    validate_error(
        world.api.complete_assignment(
            first["id"],
            f.assignment_complete_payload(95),
            make_sales_rep_headers("rep-88"),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    assert_fields(
        world.get_assignment(first["id"]),
        {"status": "ASSIGNED", "attempt_count": 0},
    )
    assert_field(world.get_assignment(second["id"]), "status", "ASSIGNED")
    assert_adoption(
        world.get_battlecard(), assigned_count=2, trained_count=0, adoption_rate=0.0000
    )
