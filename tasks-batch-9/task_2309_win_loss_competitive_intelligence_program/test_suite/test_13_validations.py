"""
Refusals and their exact codes: identity, existence, structure, tenancy and
business preconditions, each probed where a neighbouring rule could answer instead.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ADOPTION_BELOW_THRESHOLD,
    ERR_ANALYST_CAPACITY_EXCEEDED,
    ERR_ANALYST_IDENTITY_INVALID,
    ERR_ANALYST_NOT_CERTIFIED,
    ERR_ASSIGNMENT_PAST_DUE,
    ERR_COMPETITOR_NOT_FOUND,
    ERR_CROSS_PROGRAM_REFERENCE,
    ERR_DEAL_OUTSIDE_FRAME_WINDOW,
    ERR_DUPLICATE_RESOURCE_KEY,
    ERR_EVIDENCE_SET_INVALID,
    ERR_GUIDE_COVERAGE_INCOMPLETE,
    ERR_INDEPENDENCE_VIOLATION,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_WINDOW,
    ERR_MISSING_AUTH_HEADERS,
    ERR_NO_ELIGIBLE_DEALS,
    ERR_PROGRAM_NOT_FOUND,
    ERR_REASON_DEPRECATED,
    ERR_REASON_NOT_LEAF,
    ERR_RESCHEDULE_LIMIT_REACHED,
    ERR_RESPONSE_NOT_PRODUCT_GAP,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STRATUM_QUOTA_EXHAUSTED,
    ERR_TAXONOMY_DEPTH_EXCEEDED,
    ERR_UNKNOWN_ROLE,
    ERR_VALUE_OUT_OF_RANGE,
    ERR_WEIGHT_SPLIT_INVALID,
)
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_fields,
    assert_frame_slots,
    assert_ledger,
    assert_money,
    assert_null,
    assert_pagination_meta,
    assert_ratio,
)
from test_helpers.constants import ROLE_PROGRAM_ADMIN
from test_helpers.fixtures import WinLossWorld
from test_helpers.test_users import (
    UNRESOLVABLE_ANALYST_USER_ID,
    make_headers,
    make_headers_without_user_id,
    make_research_analyst_headers,
    make_sales_rep_headers,
)

CLOCK = "2026-08-01T00:00:00.000Z"


def _program_with_analyst(world: WinLossWorld, **program_overrides) -> WinLossWorld:
    world.set_clock(CLOCK)
    world.active_program(**program_overrides)
    world.create_competitor()
    world.create_analyst()
    return world


def _drawn_lost_deal(
    world: WinLossWorld, analyst_overrides=None, frame_overrides=None, **program_overrides
) -> WinLossWorld:
    """A consented LOST deal drawn from a sealed frame of an active program."""
    world.set_clock(CLOCK)
    world.active_program(**program_overrides)
    world.create_competitor()
    world.create_analyst(**(analyst_overrides or {}))
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame(**(frame_overrides or {}))
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    return world


def _interviewed_deal(world: WinLossWorld) -> WinLossWorld:
    """The same deal carried through a fully covered, completed interview."""
    _drawn_lost_deal(world)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=3)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    return world


def _published_card_with_two_reps(
    world: WinLossWorld, due_at: str = "2026-09-30T00:00:00.000Z"
) -> WinLossWorld:
    """A PUBLISHED card carrying one approved claim and two field assignments."""
    _drawn_lost_deal(world)
    world.schedule_interview()
    positioning = world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at=CLOCK,
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth ranked first",
        recorded_at=CLOCK,
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price felt high for the tier",
        recorded_at=CLOCK,
    )
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.add_claim(
        [positioning["id"]],
        claim_text="Two enterprise buyers referenced our analytics depth",
        claim_type="FEATURE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    world.publish_battlecard()
    world.beta = world.assign(sales_rep_user_ref="rep-beta", due_at=due_at)
    world.gamma = world.assign(sales_rep_user_ref="rep-gamma", due_at=due_at)
    return world


# ---------------------------------------------------------------------------
# Identity and authorization
# ---------------------------------------------------------------------------


def test_a_request_missing_the_user_id_header_is_unauthenticated(world):
    """The role is fine and the body is valid, yet the call never reaches them.

    "If either header is absent the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    Design: Corner/validations/request_without_user_id_header_returns_4xx
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.create_program(
            f.program_payload(name="Q3 Win-Loss", fiscal_quarter="2026-Q3"),
            make_headers_without_user_id(ROLE_PROGRAM_ADMIN),
        ),
        ERR_MISSING_AUTH_HEADERS,
        401,
    )


def test_an_undeclared_role_name_is_an_authentication_failure(world):
    """A syntactically fine role outside the six is 401, not 403.

    "A value outside that set is treated as an authentication failure rather than an
    authorization failure and returns `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/validations/request_with_unknown_role_header_returns_4xx
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.create_program(
            f.program_payload(name="Q3 Win-Loss", fiscal_quarter="2026-Q3"),
            make_headers("AuditorGeneral", "aud-1"),
        ),
        ERR_UNKNOWN_ROLE,
        401,
    )


def test_a_declared_role_off_the_authorized_list_is_forbidden(world):
    """A rep is a real role, so the refusal is authorization, not authentication.

    "A recognised role that is not on the target operation's authorized list is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403), and this check runs before any
    path variable is resolved, so an unauthorized caller never learns whether the
    resource in the URL exists."

    Design: Corner/validations/sales_rep_creating_a_program_returns_4xx
    """
    world.set_clock(CLOCK)

    validate_error(
        world.api.create_program(
            f.program_payload(name="Q3 Win-Loss", fiscal_quarter="2026-Q3"),
            make_sales_rep_headers("rep-77"),
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_an_unresolvable_analyst_identity_outranks_the_missing_frame(world):
    """Two rules break at once and the identity rule owns the answer.

    "4. An acting `ResearchAnalyst` resolves to an `ACTIVE` analyst —
    `ERR_ANALYST_IDENTITY_INVALID`, on every state-writing operation the role is
    authorized for."

    "5. Every path variable resolves — the matching not-found code, on every operation
    with path variables."

    Design: Corner/validations/analyst_identity_outranks_frame_existence_returns_4xx
    """
    _program_with_analyst(world)

    validate_error(
        world.api.seal_frame(
            NON_EXISTENT_UUID,
            make_research_analyst_headers(UNRESOLVABLE_ANALYST_USER_ID),
        ),
        ERR_ANALYST_IDENTITY_INVALID,
        403,
    )


def test_the_identity_gate_reads_the_analysts_live_status(world):
    """The same header that recorded one answer is refused after deactivation.

    "When `X-User-Role` is `ResearchAnalyst`, `X-User-ID` is the `id` of the acting
    `Analyst` record, and it must resolve to an `Analyst` whose `status` is `ACTIVE`;
    if it does not, the request fails with `ERR_ANALYST_IDENTITY_INVALID` (HTTP 403)."

    "Deactivation flips `status` `ACTIVE → INACTIVE` and increments `version`;
    already-scheduled interviews are untouched and may still be completed, but the
    analyst can no longer be given new ones."

    Design: Corner/validations/deactivated_analyst_cannot_record_an_interview_response
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Security depth mattered most",
        recorded_at="2026-08-01T10:00:00.000Z",
    )
    validate_success(
        world.api.deactivate_analyst(world.analyst["id"], world.admin), 200
    )

    validate_error(
        world.api.create_interview_response(
            world.interview["id"],
            f.interview_response_payload(
                question_key="PRICING_PERCEPTION",
                verbatim_text="List price felt high for the tier",
                recorded_at="2026-08-01T10:10:00.000Z",
            ),
            world.analyst_headers,
        ),
        ERR_ANALYST_IDENTITY_INVALID,
        403,
    )

    assert_field(world.get_analyst(), "status", "INACTIVE")
    items, meta = validate_paginated(
        world.api.list_interview_responses(world.interview["id"], world.admin)
    )
    assert_pagination_meta(meta, expected_total=1)
    assert len(items) == 1, items


# ---------------------------------------------------------------------------
# Existence, structure and numeric domain
# ---------------------------------------------------------------------------


def test_an_unknown_program_in_the_path_beats_any_state_question(world):
    """Existence is decided before the transition's own precondition.

    "5. Every path variable resolves — the matching not-found code, on every operation
    with path variables."

    Design: Corner/validations/activate_on_unknown_program_id_returns_program_not_found
    """
    world.set_clock(CLOCK)
    world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")

    validate_error(
        world.api.activate_program(NON_EXISTENT_UUID, world.admin),
        ERR_PROGRAM_NOT_FOUND,
        404,
    )

    untouched = world.refresh_program()
    assert_field(untouched, "status", "DRAFT")
    assert_field(untouched, "version", 1)


def test_an_unknown_competitor_in_the_body_is_still_a_not_found(world):
    """A body foreign key that resolves to nothing is 404, not a conflict.

    "6. Every foreign key in the body or query string resolves — the matching not-found
    code, on competitor registration, deal import, analyst registration, frame
    definition, interview scheduling, taxonomy node creation, attribution authoring,
    battlecard creation, claim creation, product-gap intake, enablement distribution
    and filtered list reads."

    Design: Corner/validations/deal_creation_with_unknown_competitor_reference_returns_competitor_not_found
    """
    world.set_clock(CLOCK)
    world.active_program()

    validate_error(
        world.api.create_deal(
            f.deal_payload(world.program_id, primary_competitor_id=NON_EXISTENT_UUID),
            world.admin,
        ),
        ERR_COMPETITOR_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(world.api.list_deals(world.admin))
    assert_pagination_meta(meta, expected_total=0)


def test_a_page_size_of_zero_is_a_structural_failure(world):
    """Zero is outside the accepted band, so no silent fallback to the default.

    "A `limit` outside the inclusive range from 1 to 100, or a negative `offset`, is a
    structural failure and returns `ERR_INVALID_REQUEST`."

    Design: Corner/validations/deal_listing_with_limit_zero_rejected
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_deal()

    validate_error(
        world.api.list_deals(world.admin, {"program_id": world.program_id, "limit": 0}),
        ERR_INVALID_REQUEST,
        400,
    )

    items, meta = validate_paginated(
        world.api.list_deals(world.admin, {"program_id": world.program_id, "limit": 1})
    )
    assert len(items) == 1, items
    assert_pagination_meta(meta, expected_total=1, expected_limit=1, expected_has_more=False)


def test_a_rating_of_six_is_a_numeric_domain_failure(world):
    """The value is a well-typed integer, so the range rule answers, not the type rule.

    "a non-null `rating` must be an integer from 1 through 5 inclusive"

    Design: Corner/validations/interview_response_rating_above_five_rejected
    """
    _drawn_lost_deal(world)
    world.schedule_interview()

    validate_error(
        world.api.create_interview_response(
            world.interview["id"],
            f.interview_response_payload(
                question_key="EVALUATION_CRITERIA",
                verbatim_text="Security depth mattered most",
                recorded_at="2026-08-01T10:00:00.000Z",
                rating=6,
            ),
            world.analyst_headers,
        ),
        ERR_VALUE_OUT_OF_RANGE,
        422,
    )

    _, meta = validate_paginated(
        world.api.list_interview_responses(world.interview["id"], world.admin)
    )
    assert_pagination_meta(meta, expected_total=0)


def test_a_frame_window_of_zero_length_is_refused(world):
    """The interval comparison is strict, so one instant is not a window.

    "An interval whose start is not strictly before its end — a sampling frame where
    `window_start` is not before `window_end`, a scheduled interview where
    `scheduled_start_at` is not before `scheduled_end_at`, a completion where
    `actual_start_at` is not before `actual_end_at`, or an assignment whose `due_at` is
    not strictly after the `assigned_at` instant the server stamps — is rejected with
    `ERR_INVALID_TIME_WINDOW` (HTTP 422)."

    Design: Corner/validations/sampling_frame_with_zero_length_window_rejected
    """
    _program_with_analyst(world)

    validate_error(
        world.api.create_sampling_frame(
            f.sampling_frame_payload(
                world.program_id,
                label="Zero window",
                window_start="2026-04-01T00:00:00.000Z",
                window_end="2026-04-01T00:00:00.000Z",
                quota_won=0,
                quota_lost=1,
                quota_no_decision=0,
            ),
            world.analyst_headers,
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )

    _, meta = validate_paginated(
        world.api.list_program_sampling_frames(world.program_id, world.admin)
    )
    assert_pagination_meta(meta, expected_total=0)


# ---------------------------------------------------------------------------
# Tenancy and uniqueness
# ---------------------------------------------------------------------------


def test_an_analyst_from_another_program_is_a_tenancy_conflict(world):
    """The analyst exists and is active, so the answer is 409, not 404.

    "The `Program` is the tenancy boundary. A referenced row that exists but belongs to
    a different program than the operation's scope is a conflict, not a missing
    resource, and is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 409)."

    Design: Corner/validations/interview_with_analyst_from_another_program_returns_4xx
    """
    _drawn_lost_deal(world)
    deal = world.deal
    contact = world.contact
    world.create_program(name="Program B", fiscal_quarter="2026-Q4")
    world.activate_program()
    outsider = world.create_analyst(full_name="Ana Two", linked_user_ref="u-ana-2")

    validate_error(
        world.api.create_interview(
            f.interview_payload(deal["id"], contact["id"], outsider["id"]),
            make_research_analyst_headers(outsider["id"]),
        ),
        ERR_CROSS_PROGRAM_REFERENCE,
        409,
    )

    _, meta = validate_paginated(world.api.list_interviews(world.admin))
    assert_pagination_meta(meta, expected_total=0)
    assert_analyst_workload(world.get_analyst(outsider["id"]), 0, 0)


def test_a_crm_reference_is_unique_only_inside_its_own_program(world):
    """The same reference lives happily in the neighbouring program.

    "a deal's `crm_deal_ref` is unique within its program compared case-sensitively"

    Design: Corner/validations/second_deal_with_the_same_crm_reference_rejected
    """
    world.set_clock(CLOCK)
    world.active_program()
    program_a = world.program_id
    world.create_deal()
    world.create_program(name="Program B", fiscal_quarter="2026-Q4")
    world.activate_program()
    in_b = world.create_deal(
        crm_deal_ref="CRM-1001",
        outcome="WON",
        acr_usd=120000.00,
        close_date="2026-06-20T00:00:00.000Z",
        sales_rep_user_ref="rep-88",
    )

    validate_error(
        world.api.create_deal(
            f.deal_payload(
                program_a,
                crm_deal_ref="CRM-1001",
                outcome="NO_DECISION",
                acr_usd=90000.00,
                close_date="2026-06-30T00:00:00.000Z",
                segment="SMB",
                sales_rep_user_ref="rep-99",
            ),
            world.admin,
        ),
        ERR_DUPLICATE_RESOURCE_KEY,
        409,
    )

    _, meta = validate_paginated(world.api.list_deals(world.admin))
    assert_pagination_meta(meta, expected_total=2)
    assert_fields(
        world.get_deal(in_b["id"]), {"crm_deal_ref": "CRM-1001", "outcome": "WON"}
    )


# ---------------------------------------------------------------------------
# Scheduling preconditions
# ---------------------------------------------------------------------------


def test_a_lapsed_certificate_blocks_scheduling(world):
    """Certification is read against the clock, not against the interview date.

    "the current logical clock instant must be strictly earlier than that analyst's
    `certified_until`"

    Design: Corner/validations/scheduling_with_an_expired_analyst_certification_returns_4xx
    """
    _drawn_lost_deal(
        world, analyst_overrides={"certified_until": "2026-07-01T00:00:00.000Z"}
    )

    validate_error(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"], world.contact["id"], world.analyst["id"]
            ),
            world.analyst_headers,
        ),
        ERR_ANALYST_NOT_CERTIFIED,
        422,
    )

    _, meta = validate_paginated(world.api.list_interviews(world.admin))
    assert_pagination_meta(meta, expected_total=0)
    assert_deal_dimensions(world.get_deal(), research_status="SELECTED")
    assert_ledger(world.refresh_program(), 0.00, 0.00)


def test_a_certificate_lapsing_after_booking_time_still_permits_the_booking(world):
    """The rule is evaluated once, at booking, and the strict inequality holds.

    "17. Analyst certification — `ERR_ANALYST_NOT_CERTIFIED` (HTTP 422), on interview
    scheduling, rescheduling and completion."

    Design: Corner/validations/scheduling_one_day_before_certification_expiry_succeeds
    """
    _drawn_lost_deal(
        world, analyst_overrides={"certified_until": "2026-08-02T00:00:00.000Z"}
    )

    body = validate_success(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"], world.contact["id"], world.analyst["id"]
            ),
            world.analyst_headers,
        ),
        201,
    )
    interview = body

    assert_field(interview, "status", "SCHEDULED")
    assert_money(interview["incentive_provisional_usd"], 250.00, "provisional")
    assert_field(interview, "incentive_status", "COMMITTED")
    assert_field(interview, "guide_version_pinned", 1)
    assert_analyst_workload(world.get_analyst(), 1, 75)
    assert_ledger(world.refresh_program(), 250.00, 0.00, "OPEN")


def test_an_analyst_who_owns_the_deal_breaks_strict_independence(world):
    """Either half of the conjunction is enough, so the shared reference decides.

    "When the program's `independence_mode` is `STRICT`, the interviewing analyst must
    have `sales_org_member` false and must have a `linked_user_ref` different from the
    deal's `sales_rep_user_ref`; either condition failing yields
    `ERR_INDEPENDENCE_VIOLATION`."

    Design: Corner/validations/scheduling_an_analyst_who_owns_the_deal_as_sales_rep_returns_4xx
    """
    _drawn_lost_deal(world, analyst_overrides={"linked_user_ref": "rep-77"})

    validate_error(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"], world.contact["id"], world.analyst["id"]
            ),
            world.analyst_headers,
        ),
        ERR_INDEPENDENCE_VIOLATION,
        422,
    )

    _, meta = validate_paginated(world.api.list_interviews(world.admin))
    assert_pagination_meta(meta, expected_total=0)


def test_advisory_mode_skips_the_independence_rule_entirely(world):
    """The same conflicting data schedules, and the mode is the only record of it.

    "When `independence_mode` is `ADVISORY` the rule is skipped in its entirety and the
    interview proceeds, the mode value itself being the record that independence was not
    enforced."

    Design: Corner/validations/advisory_independence_mode_permits_a_sales_org_analyst_on_his_own_deal
    """
    world.set_clock(CLOCK)
    world.active_program(independence_mode="ADVISORY")
    world.create_competitor()
    world.create_analyst(linked_user_ref="rep-77", sales_org_member=True)
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(title_band="CHAMPION", incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)

    body = validate_success(
        world.api.create_interview(
            f.interview_payload(
                world.deal["id"], world.contact["id"], world.analyst["id"]
            ),
            world.analyst_headers,
        ),
        201,
    )
    interview = body

    assert_field(interview, "status", "SCHEDULED")
    assert_money(interview["incentive_provisional_usd"], 175.00, "provisional")
    program = world.refresh_program()
    assert_field(program, "independence_mode", "ADVISORY")
    assert_ledger(program, 175.00, 0.00)
    assert_deal_dimensions(world.get_deal(), research_status="SELECTED")


def test_two_individually_legal_bookings_can_still_exceed_the_cap(world):
    """The second slot conflicts with nothing but the collective workload cap.

    "The analyst's `open_interview_count` must be strictly less than the program's
    `max_open_interviews_per_analyst`, or the request fails with
    `ERR_ANALYST_CAPACITY_EXCEEDED` — each individual interview may be legal while the
    collective open workload is not."

    Design: Corner/validations/second_open_interview_for_a_capped_analyst_returns_4xx
    """
    world.set_clock(CLOCK)
    world.active_program(max_open_interviews_per_analyst=1)
    world.create_competitor()
    world.create_analyst()
    first = world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(deal_id=first["id"], incentive_eligibility="ELIGIBLE")
    second = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=250000.00,
        close_date="2026-06-16T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    other_contact = world.create_contact(
        deal_id=second["id"],
        email="buyer2@brava.test",
        full_name="Cal Dos",
        incentive_eligibility="ELIGIBLE",
    )
    world.record_consent("GRANTED", deal_id=second["id"], contact_id=other_contact["id"])
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    world.schedule_interview(deal_id=first["id"])

    validate_error(
        world.api.create_interview(
            f.interview_payload(
                second["id"],
                other_contact["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-12T14:00:00.000Z",
                scheduled_end_at="2026-08-12T15:00:00.000Z",
            ),
            world.analyst_headers,
        ),
        ERR_ANALYST_CAPACITY_EXCEEDED,
        409,
    )

    assert_analyst_workload(world.get_analyst(), 1, 75)
    _, meta = validate_paginated(world.api.list_interviews(world.admin))
    assert_pagination_meta(meta, expected_total=1)
    assert_ledger(world.refresh_program(), 250.00, 0.00)


# ---------------------------------------------------------------------------
# Draw preconditions
# ---------------------------------------------------------------------------


def test_a_full_stratum_refuses_a_further_draw(world):
    """Room, not eligibility, is what is missing, and the identity is preserved.

    "If the requested stratum's open slots are fewer than `requested_count`, the draw
    fails with `ERR_STRATUM_QUOTA_EXHAUSTED`; if slots remain but the eligibility filter
    leaves the pool empty, it fails with `ERR_NO_ELIGIBLE_DEALS`."

    Design: Corner/validations/draw_beyond_the_stratum_quota_returns_4xx
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    big = world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(deal_id=big["id"], incentive_eligibility="ELIGIBLE")
    small = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=100000.00,
        close_date="2026-06-16T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    world.consented_contact(
        deal_id=small["id"], email="buyer2@brava.test", full_name="Cal Dos"
    )
    world.create_frame(quota_won=0, quota_lost=1, quota_no_decision=0)
    world.seal_frame()
    world.draw("LOST", requested_count=1)

    validate_error(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("LOST", requested_count=1),
            world.analyst_headers,
        ),
        ERR_STRATUM_QUOTA_EXHAUSTED,
        409,
    )

    frame = world.get_frame()
    assert_frame_slots(frame, selected_lost=1, open_lost=0)
    assert_field(frame, "status", "SEALED")
    assert_field(world.get_deal(big["id"]), "research_status", "SELECTED")
    assert_field(world.get_deal(small["id"]), "research_status", "NOT_SELECTED")


def test_an_empty_candidate_pool_is_reported_apart_from_a_full_quota(world):
    """A slot is open in the won stratum but no won deal exists to fill it.

    "24. A non-empty eligible candidate pool — `ERR_NO_ELIGIBLE_DEALS` (HTTP 422), on
    sampling draws. This separates "no room left in the quota" (rule 23) from "room
    exists but nothing qualifies"."

    Design: Corner/validations/draw_of_a_stratum_with_no_eligible_deals_returns_4xx
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame(quota_won=1, quota_lost=0, quota_no_decision=0)
    world.seal_frame()

    validate_error(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("WON", requested_count=1),
            world.analyst_headers,
        ),
        ERR_NO_ELIGIBLE_DEALS,
        422,
    )

    assert_frame_slots(world.get_frame(), selected_won=0, open_won=1)
    deal = world.get_deal()
    assert_field(deal, "research_status", "NOT_SELECTED")
    assert_null(deal["sampling_frame_id"], "sampling_frame_id")


def test_a_pinned_deal_outside_the_window_is_never_substituted(world):
    """The named candidate must satisfy the window predicate like any other.

    "When a specific `deal_id` is pinned, that candidate must still satisfy every
    predicate — and a pinned deal whose `close_date` falls outside the half-open window
    is the way `ERR_DEAL_OUTSIDE_FRAME_WINDOW` is reached, with a deal closing exactly
    on `window_end` being out of frame and one closing exactly on `window_start` being
    in."

    Design: Corner/validations/targeted_draw_of_a_deal_outside_the_frame_window_returns_4xx
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    old = world.create_deal(
        close_date="2026-03-01T00:00:00.000Z",
        primary_competitor_id=world.competitor["id"],
    )
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame(quota_won=0, quota_lost=1, quota_no_decision=0)
    world.seal_frame()

    validate_error(
        world.api.draw_frame(
            world.frame["id"],
            f.draw_payload("LOST", deal_id=old["id"]),
            world.analyst_headers,
        ),
        ERR_DEAL_OUTSIDE_FRAME_WINDOW,
        422,
    )

    assert_field(world.get_deal(), "research_status", "NOT_SELECTED")
    assert_frame_slots(world.get_frame(), selected_lost=0, open_lost=1)


# ---------------------------------------------------------------------------
# Completion, taxonomy and attribution
# ---------------------------------------------------------------------------


def test_completion_needs_every_pinned_guide_topic(world):
    """Two of the three pinned topics leave the interview where it was.

    "the set of distinct `question_key` values recorded on the interview must be a
    superset of its own `required_question_keys_pinned` — measured against that pinned
    array, not the program's current guide — or the request is refused with
    `ERR_GUIDE_COVERAGE_INCOMPLETE`."

    Design: Corner/validations/completion_without_the_pinned_pricing_question_returns_4xx
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Security depth mattered most",
        recorded_at="2026-08-10T14:05:00.000Z",
    )
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at="2026-08-10T14:15:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")

    validate_error(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload(
                "2026-08-10T14:00:00.000Z", "2026-08-10T14:45:00.000Z"
            ),
            world.analyst_headers,
        ),
        ERR_GUIDE_COVERAGE_INCOMPLETE,
        422,
    )

    interview = world.get_interview()
    assert_fields(
        interview,
        {
            "status": "SCHEDULED",
            "coverage_complete": False,
            "incentive_status": "COMMITTED",
        },
    )
    assert_null(interview["incentive_final_usd"], "incentive_final_usd")
    assert_deal_dimensions(
        world.get_deal(), research_status="SELECTED", interview_coverage_count=0
    )
    assert_ledger(world.refresh_program(), 250.00, 0.00)


def test_an_interior_taxonomy_node_cannot_be_cited(world):
    """Having a child is what disqualifies the root, not its status or program.

    "Each cited reason must belong to the deal's program, must have `status` `ACTIVE` —
    otherwise `ERR_REASON_DEPRECATED` — and must have `is_leaf` true, since interior
    nodes exist only for roll-up and citing one yields `ERR_REASON_NOT_LEAF`."

    Design: Corner/validations/attribution_on_a_non_leaf_reason_returns_4xx
    """
    _interviewed_deal(world)
    root = world.create_reason("PRICE", "Price")
    world.create_reason("PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"])
    deal = world.get_deal()

    validate_error(
        world.api.create_loss_attribution(
            f.loss_attribution_payload(deal["id"], root["id"], deal["version"]),
            world.analyst_headers,
        ),
        ERR_REASON_NOT_LEAF,
        422,
    )

    _, meta = validate_paginated(world.api.list_loss_attributions(world.admin))
    assert_pagination_meta(meta, expected_total=0)
    assert_deal_dimensions(
        world.get_deal(),
        research_status="INTERVIEWED",
        attribution_status="UNATTRIBUTED",
    )
    assert_fields(
        world.get_reason(root["id"]),
        {"is_leaf": False, "ratified_attribution_count": 0},
    )


def test_a_deprecated_leaf_is_refused_with_its_own_code(world):
    """The leaf test passes first, so the status test owns the answer.

    "27. A cited loss reason is active — `ERR_REASON_DEPRECATED` (HTTP 422), on
    attribution authoring."

    Design: Corner/validations/attribution_on_a_deprecated_reason_returns_4xx
    """
    _interviewed_deal(world)
    root = world.create_reason("PRICE", "Price")
    leaf = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    validate_success(world.api.deprecate_loss_reason(leaf["id"], world.admin), 200)
    deal = world.get_deal()

    validate_error(
        world.api.create_loss_attribution(
            f.loss_attribution_payload(deal["id"], leaf["id"], deal["version"]),
            world.analyst_headers,
        ),
        ERR_REASON_DEPRECATED,
        422,
    )

    assert_fields(world.get_reason(leaf["id"]), {"status": "DEPRECATED", "is_leaf": True})
    _, meta = validate_paginated(world.api.list_loss_attributions(world.admin))
    assert_pagination_meta(meta, expected_total=0)
    assert_deal_dimensions(world.get_deal(), attribution_status="UNATTRIBUTED")


def test_a_lone_primary_weight_below_one_does_not_close_the_split(world):
    """The weight is inside its range yet the conservation rule still fails.

    "Weight conservation is strict: `weight_primary` lies between 0.50 and 1.00
    inclusive at two decimal places; it must equal exactly 1.00 when no secondary reason
    is supplied; when a secondary reason is supplied it must differ from the primary
    reason and the two weights must sum to exactly 1.00."

    Design: Corner/validations/attribution_weight_below_one_without_a_secondary_reason_rejected
    """
    _interviewed_deal(world)
    root = world.create_reason("PRICE", "Price")
    leaf = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    deal = world.get_deal()

    validate_error(
        world.api.create_loss_attribution(
            f.loss_attribution_payload(
                deal["id"], leaf["id"], deal["version"], weight_primary=0.60
            ),
            world.analyst_headers,
        ),
        ERR_WEIGHT_SPLIT_INVALID,
        422,
    )

    _, meta = validate_paginated(world.api.list_loss_attributions(world.admin))
    assert_pagination_meta(meta, expected_total=0)
    after = world.get_deal()
    assert_field(after, "attribution_status", "UNATTRIBUTED")
    assert_field(after, "version", deal["version"])


def test_a_gap_cannot_be_seeded_from_another_topic(world):
    """The response resolves and is in the program; only its topic is wrong.

    "The seeding response must have `question_key` `PRODUCT_GAP`; every other topic is
    evidence for battlecards instead, and citing one yields
    `ERR_RESPONSE_NOT_PRODUCT_GAP`."

    Design: Corner/validations/product_gap_sourced_from_a_non_product_gap_response_rejected
    """
    _interviewed_deal(world)
    evaluation = world.response_of("EVALUATION_CRITERIA")

    validate_error(
        world.api.create_product_gap(
            f.product_gap_payload(
                world.program_id, evaluation["id"], gap_summary="Mis-routed evidence"
            ),
            world.product,
        ),
        ERR_RESPONSE_NOT_PRODUCT_GAP,
        422,
    )

    _, meta = validate_paginated(world.api.list_product_gaps(world.admin))
    assert_pagination_meta(meta, expected_total=0)
    stored = validate_success(
        world.api.get_interview_response(evaluation["id"], world.admin), 200
    )
    assert_field(stored, "question_key", "EVALUATION_CRITERIA")


def test_a_fourth_taxonomy_level_is_refused(world):
    """Three levels are accepted, so only the fourth trips the ceiling.

    "`depth` is computed as 1 for a root node and otherwise as one more than the
    parent's `depth`, and it may never exceed 3 — a creation or re-parenting that would
    push it past three levels is refused with `ERR_TAXONOMY_DEPTH_EXCEEDED`."

    Design: Corner/validations/fourth_level_taxonomy_node_rejected
    """
    world.set_clock(CLOCK)
    world.active_program()
    root = world.create_reason("PRICE", "Price")
    middle = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    leaf = world.create_reason(
        "PRICE_DISCOUNT_FLOOR", "Discount floor", parent_reason_id=middle["id"]
    )

    validate_error(
        world.api.create_loss_reason(
            f.loss_reason_payload(
                world.program_id,
                code="PRICE_DISCOUNT_FLOOR_APAC",
                label="APAC floor exception",
                parent_reason_id=leaf["id"],
            ),
            world.admin,
        ),
        ERR_TAXONOMY_DEPTH_EXCEEDED,
        422,
    )

    assert_fields(world.get_reason(leaf["id"]), {"depth": 3, "is_leaf": True})
    _, meta = validate_paginated(world.api.list_loss_reasons(world.admin))
    assert_pagination_meta(meta, expected_total=3)


# ---------------------------------------------------------------------------
# Enablement, promotion, rescheduling and evidence
# ---------------------------------------------------------------------------


def test_one_second_past_the_deadline_refuses_the_attempt(world):
    """The deadline is inclusive on the left only, and the refusal expires nobody.

    "That deadline boundary is inclusive: an attempt landing exactly at `due_at`
    succeeds and one second later fails with `ERR_ASSIGNMENT_PAST_DUE`."

    Design: Corner/validations/assignment_completed_one_second_after_due_at_returns_4xx
    """
    _published_card_with_two_reps(world, due_at="2026-08-05T00:00:00.000Z")
    world.set_clock("2026-08-05T00:00:00.000Z")
    world.complete_assignment(
        quiz_score=95, assignment_id=world.beta["id"], sales_rep_user_ref="rep-beta"
    )
    world.set_clock("2026-08-05T00:00:01.000Z")

    validate_error(
        world.api.complete_assignment(
            world.gamma["id"],
            f.assignment_complete_payload(95),
            make_sales_rep_headers("rep-gamma"),
        ),
        ERR_ASSIGNMENT_PAST_DUE,
        409,
    )

    gamma = world.get_assignment(world.gamma["id"])
    assert_fields(gamma, {"status": "ASSIGNED", "attempt_count": 0})
    assert_null(gamma["quiz_score"], "quiz_score")
    beta = world.get_assignment(world.beta["id"])
    assert_field(beta, "status", "TRAINED")
    assert beta["completed_at"] == "2026-08-05T00:00:00.000Z", beta["completed_at"]
    card = world.get_battlecard()
    assert_fields(card, {"assigned_count": 2, "trained_count": 1})
    assert_ratio(card["adoption_rate"], 0.5000, "adoption_rate")


def test_promotion_waits_on_the_published_cards_adoption(world):
    """Every other promotion precondition holds; only the field gate is short.

    "One further gate closes the loop between enablement adoption and roadmap
    investment: when the gap's derived competitor has at least one published battlecard,
    that competitor's most recently published card must have an `adoption_rate` of at
    least 0.6000, or the promotion is refused with `ERR_ADOPTION_BELOW_THRESHOLD`."

    Design: Corner/validations/promote_while_adoption_is_below_the_gate_returns_4xx
    """
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor(tier="PRIMARY")
    world.create_two_analysts()
    reason = world.create_reason("PRICE", "Price")
    world.create_deal(acr_usd=500000.00, primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    gap_response = world.record_response(
        question_key="PRODUCT_GAP",
        verbatim_text="We could not export compliance evidence on a schedule.",
        recorded_at="2026-08-10T14:20:00.000Z",
    )
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    attribution = world.create_attribution(reason["id"])
    world.ratify_attribution(attribution["id"])
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.add_claim(
        [world.response_of("COMPETITOR_POSITIONING")["id"]],
        claim_text="Buyers rate our analytics depth against Northwind",
        claim_type="FEATURE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    world.publish_battlecard()
    trained = world.assign(sales_rep_user_ref="rep-alpha")
    world.assign(sales_rep_user_ref="rep-beta")
    world.complete_assignment(
        quiz_score=90, assignment_id=trained["id"], sales_rep_user_ref="rep-alpha"
    )
    gap = world.create_gap(gap_response["id"], gap_summary="Compliance evidence export")
    world.triage_gap("ACCEPT")

    validate_error(
        world.api.promote_product_gap(
            gap["id"], f.promote_payload("EPIC-4412"), world.product
        ),
        ERR_ADOPTION_BELOW_THRESHOLD,
        409,
    )

    stored = world.get_gap(gap["id"])
    assert_field(stored, "status", "ACCEPTED")
    assert_null(stored["roadmap_epic_ref"], "roadmap_epic_ref")
    assert_money(stored["affected_acr_usd"], 500000.00, "affected_acr_usd")
    assert_money(stored["impact_score"], 57.20, "impact_score")
    assert_field(stored, "roadmap_priority_band", "P1")
    card = world.get_battlecard()
    assert_ratio(card["adoption_rate"], 0.5000, "adoption_rate")
    assert_field(card, "status", "PUBLISHED")
    assert_field(world.refresh_program(), "status", "ACTIVE")


def test_the_third_rebooking_terminates_the_no_show_cycle(world):
    """Two reschedules are legal; the third leaves the interview in no-show.

    "The interview must be `NO_SHOW`, its `reschedule_count` must be strictly less than
    two — a third attempt is refused with `ERR_RESCHEDULE_LIMIT_REACHED`, which is what
    terminates the `SCHEDULED → NO_SHOW → SCHEDULED` cycle"

    Design: Corner/validations/third_reschedule_of_the_same_interview_returns_4xx
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    for start, end, grace in (
        ("2026-08-12T14:00:00.000Z", "2026-08-12T15:00:00.000Z", "2026-08-10T14:15:00.000Z"),
        ("2026-08-14T14:00:00.000Z", "2026-08-14T15:00:00.000Z", "2026-08-12T14:15:00.000Z"),
    ):
        world.set_clock(grace)
        world.no_show()
        validate_success(
            world.api.reschedule_interview(
                world.interview["id"],
                f.reschedule_payload(start, end),
                world.analyst_headers,
            ),
            200,
        )
    world.set_clock("2026-08-14T14:15:00.000Z")
    world.no_show()

    validate_error(
        world.api.reschedule_interview(
            world.interview["id"],
            f.reschedule_payload(
                "2026-08-17T14:00:00.000Z", "2026-08-17T15:00:00.000Z"
            ),
            world.analyst_headers,
        ),
        ERR_RESCHEDULE_LIMIT_REACHED,
        409,
    )

    interview = world.get_interview()
    assert_fields(interview, {"status": "NO_SHOW", "reschedule_count": 2})
    assert interview["scheduled_start_at"] == "2026-08-14T14:00:00.000Z", (
        interview["scheduled_start_at"]
    )
    assert_analyst_workload(world.get_analyst(), 0, 0)
    assert_ledger(world.refresh_program(), 0.00, 0.00)


def test_evidence_from_outside_the_cards_program_is_refused(world):
    """The response exists, so the evidence set — not the lookup — is what fails.

    "an array that is empty after deduplication, or one citing a response from outside
    the card's program, is refused with `ERR_EVIDENCE_SET_INVALID`"

    Design: Corner/validations/claim_evidence_from_another_programs_interview_rejected
    """
    _drawn_lost_deal(world)
    home_analyst = world.analyst
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    card = world.battlecard
    world.schedule_interview()
    world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at="2026-08-10T14:10:00.000Z",
    )
    world.create_program(name="Program B", fiscal_quarter="2026-Q4")
    world.activate_program()
    other_competitor = world.create_competitor(name="Brava")
    outsider = world.create_analyst(full_name="Ana Two", linked_user_ref="u-ana-2")
    other_deal = world.create_deal(
        crm_deal_ref="CRM-2001", primary_competitor_id=other_competitor["id"]
    )
    other_contact = world.create_contact(
        deal_id=other_deal["id"], email="buyer9@brava.test", full_name="Dee Nine"
    )
    world.record_consent(
        "GRANTED", deal_id=other_deal["id"], contact_id=other_contact["id"]
    )
    other_frame = world.create_frame(label="Program B Frame")
    world.seal_frame(other_frame["id"])
    world.draw("LOST", frame_id=other_frame["id"], requested_count=1)
    other_interview = world.schedule_interview(
        deal_id=other_deal["id"], buyer_contact_id=other_contact["id"], analyst=outsider
    )
    foreign_response = world.record_response(
        interview_id=other_interview["id"],
        analyst=outsider,
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Brava buyers wanted deeper migration tooling",
        recorded_at="2026-08-10T14:10:00.000Z",
    )

    validate_error(
        world.api.create_claim(
            card["id"],
            f.claim_payload(
                [foreign_response["id"]],
                claim_text="Buyers prefer our migration tooling",
                claim_type="FEATURE",
            ),
            make_research_analyst_headers(home_analyst["id"]),
        ),
        ERR_EVIDENCE_SET_INVALID,
        422,
    )

    _, meta = validate_paginated(world.api.list_claims(card["id"], world.admin))
    assert_pagination_meta(meta, expected_total=0)
    stored_card = world.get_battlecard(card["id"])
    assert_fields(stored_card, {"status": "DRAFT", "approved_claim_count": 0})
    assert_money(stored_card["risk_index_pre"], 0.00, "risk_index_pre")
