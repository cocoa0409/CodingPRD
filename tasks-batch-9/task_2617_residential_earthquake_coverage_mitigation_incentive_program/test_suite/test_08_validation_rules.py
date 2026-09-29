"""Validation rules of the residential earthquake programme, exercised one rule at a time.

Each scenario below is built so that a single documented rule is the only thing
standing between the request and success: an inspection window that is empty,
mis-sized or already in the past; a second grant application on a dwelling that
already has an open one; a coverage sublimit that reaches above the Coverage A
dwelling limit; a quote read on the wrong side of its thirty-day life; a bind
attempted into a county the ground has just moved under; a fourth return for
information on an application whose review rounds are spent; and a fourth open
retrofit project handed to a contractor who may hold only three. Where the rule
has a boundary, the mirror-image acceptance is asserted as well, so that the
threshold is pinned from both sides rather than merely rejected from one.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    FIELD_INSPECTOR_HEADERS,
    GRANT_REVIEWER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import make_insurer_headers, make_policyholder_headers

BRACE_AND_BOLT_CYCLE = {"program_track": "BRACE_AND_BOLT"}
CRIPPLE_WALL_DWELLING = {
    "structure_type": "WOOD_FRAME_CRIPPLE_WALL",
    "year_built": 1972,
}


def _shift_days(instant: str, days: int) -> str:
    """The supplied instant moved by a whole number of days, still in UTC."""
    moment = datetime.fromisoformat(instant.replace("Z", "+00:00")) + timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_awaiting_inspection(api):
    """A cripple-wall retrofit project, funded and declared ready for its visit."""
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=dict(CRIPPLE_WALL_DWELLING))
    return fixtures.setup_project_awaiting_inspection(
        api, ctx=ctx, cycle_overrides=dict(BRACE_AND_BOLT_CYCLE)
    )


def test_01_inspection_window_that_is_empty_mis_sized_or_in_the_past_is_refused(api):
    """PRD §2.8: "Rung 13: every declared interval must be non-empty — a funding cycle's `opens_at` must be strictly before its `closes_at`, a take-up evaluation's `window_start` strictly before its `window_end`, and an inspection's `window_start` strictly before its `window_end` — otherwise `ERR_INVALID_WINDOW` (422)."

    PRD §2.8: "Rung 58: an inspection window's length must be at least 30 minutes and at most 240 minutes, both bounds inclusive, otherwise `ERR_INSPECTION_DURATION_INVALID` (422)."
    PRD §2.8: "Rung 59: an inspection's `window_start` must be at or after the current logical clock, otherwise `ERR_INSPECTION_IN_PAST` (422)."

    Design: Corner/validations/inspection_window_duration_and_past_start_are_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _project_awaiting_inspection(api)
    assert ctx["project"]["status"] == "AWAITING_INSPECTION", (
        "the project must be schedulable, so that only the window rules can fail"
    )
    project_id = ctx["project"]["id"]

    empty = api.create_inspection(
        factories.create_inspection_payload(
            project_id, "2026-08-05T09:00:00Z", "2026-08-05T09:00:00Z"
        ),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(empty, ApiErrorId.INVALID_WINDOW)

    too_short = api.create_inspection(
        factories.create_inspection_payload(
            project_id, "2026-08-05T09:00:00Z", "2026-08-05T09:20:00Z"
        ),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(too_short, ApiErrorId.INSPECTION_DURATION_INVALID)

    too_long = api.create_inspection(
        factories.create_inspection_payload(
            project_id, "2026-08-05T09:00:00Z", "2026-08-05T14:00:00Z"
        ),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(too_long, ApiErrorId.INSPECTION_DURATION_INVALID)

    in_the_past = api.create_inspection(
        factories.create_inspection_payload(
            project_id, "2026-07-20T09:00:00Z", "2026-07-20T11:00:00Z"
        ),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(in_the_past, ApiErrorId.INSPECTION_IN_PAST)

    booked = validate_success(
        api.list_inspections({"project_id": project_id}, PROGRAM_ADMIN_HEADERS)
    )
    assert booked == [], "every refused booking must have left the calendar empty"


def test_02_two_hour_future_inspection_window_is_booked_as_pending(api):
    """PRD §3.6: "The window is half-open — it includes `window_start` and excludes `window_end` — must be at least thirty and at most two hundred and forty minutes long, both bounds inclusive, and must begin at or after the current logical clock; a visit booked into the past is refused with `ERR_INSPECTION_IN_PAST`."

    PRD §3.6: "The new inspection opens with `result` at `PENDING`, `inspector_user_id` and `recorded_at` null, and `deficiency_note` an empty string."

    Design: Corner/validations/inspection_window_duration_and_past_start_are_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _project_awaiting_inspection(api)

    inspection = validate_success(
        api.create_inspection(
            factories.create_inspection_payload(
                ctx["project"]["id"], "2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z"
            ),
            FIELD_INSPECTOR_HEADERS,
        ),
        201,
    )
    assertions.assert_inspection_shape(inspection)
    assert inspection["result"] == "PENDING"
    assert inspection["contractor_id"] == ctx["contractor"]["id"], (
        "the visit takes its contractor from the project it verifies"
    )
    assert inspection["inspector_user_id"] is None
    assert inspection["recorded_at"] is None


def test_03_second_open_grant_on_one_dwelling_is_refused_until_the_first_is_withdrawn(api):
    """PRD §2.8: "Rung 54: at most one grant per `dwelling_id` may sit in a non-terminal status, meaning any of `SUBMITTED`, `UNDER_REVIEW`, `RETURNED_FOR_INFO`, `APPROVED` or `FUNDS_RESERVED`, otherwise `ERR_DUPLICATE_OPEN_GRANT` (409)."

    PRD §3.5: "The cycle must be `OPEN`, and only one grant per dwelling may sit in a non-terminal status, so a second concurrent application on the same structure is refused with `ERR_DUPLICATE_OPEN_GRANT`."
    PRD §3.5: "Withdrawing from any of the four pre-reservation statuses touches no ledger at all, because nothing was reserved."

    Design: Corner/validations/duplicate_open_grant_per_dwelling_is_rejected_until_the_first_is_withdrawn
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=dict(CRIPPLE_WALL_DWELLING))
    ctx = fixtures.setup_submitted_grant(
        api,
        ctx=ctx,
        cycle_overrides=dict(BRACE_AND_BOLT_CYCLE, total_pool_cents=1000000),
        project_cost_estimate_cents=200000,
    )
    assert ctx["grant"]["status"] == "SUBMITTED"
    holder_headers = make_policyholder_headers(ctx["policyholder"]["id"])

    def _second_application():
        return api.create_retrofit_grant(
            factories.create_retrofit_grant_payload(
                ctx["dwelling"]["id"],
                ctx["cycle"]["id"],
                income_tier="TIER_MID",
                project_cost_estimate_cents=100000,
                requested_scope="ANCHOR_BOLT_ONLY",
            ),
            holder_headers,
        )

    validate_error(_second_application(), ApiErrorId.DUPLICATE_OPEN_GRANT)

    withdrawn = validate_success(
        api.withdraw_grant(
            ctx["grant"]["id"],
            factories.reason_payload("The household deferred the work a season"),
            holder_headers,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    cycle = validate_success(api.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS))
    assert cycle["reserved_cents"] == 0, "a pre-reservation withdrawal commits nothing"
    assert cycle["uncommitted_cents"] == cycle["total_pool_cents"]
    assertions.assert_grant_pool_conserved(cycle)

    replacement = validate_success(_second_application(), 201)
    assert replacement["status"] == "SUBMITTED", (
        "the terminal first application no longer occupies the dwelling"
    )


def test_04_contents_sublimit_above_the_dwelling_limit_is_refused(api):
    """PRD §3.3: "Each sublimit must be strictly greater than zero and no larger than the named dwelling's `dwelling_limit_cents`; a sublimit above the dwelling limit is refused with `ERR_SUBLIMIT_EXCEEDS_LIMIT`."

    PRD §2.8: "Rung 74: `contents_sublimit_cents` and `loss_of_use_sublimit_cents` must each be no greater than the dwelling's `dwelling_limit_cents` at quote time, otherwise `ERR_SUBLIMIT_EXCEEDS_LIMIT` (422)."

    Design: Corner/validations/sublimits_above_the_dwelling_limit_are_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_accepted_offer(
        api, dwelling_overrides={"dwelling_limit_cents": 5000000}
    )

    refused = api.create_policy(
        factories.create_policy_payload(
            ctx["dwelling"]["id"],
            ctx["insurer"]["id"],
            ctx["offer"]["id"],
            contents_sublimit_cents=5000001,
            loss_of_use_sublimit_cents=400000,
        ),
        make_insurer_headers(ctx["insurer"]["id"]),
    )
    validate_error(refused, ApiErrorId.SUBLIMIT_EXCEEDS_LIMIT)

    dwelling = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert dwelling["dwelling_limit_cents"] == 5000000, "one cent over Coverage A is enough"
    quotes = validate_success(
        api.list_policies({"dwelling_id": ctx["dwelling"]["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert quotes == [], "the refused quote wrote no policy row"


def test_05_loss_of_use_sublimit_above_the_dwelling_limit_is_refused(api):
    """PRD §3.3: "Each sublimit must be strictly greater than zero and no larger than the named dwelling's `dwelling_limit_cents`; a sublimit above the dwelling limit is refused with `ERR_SUBLIMIT_EXCEEDS_LIMIT`."

    PRD §2.8: "Rung 74: `contents_sublimit_cents` and `loss_of_use_sublimit_cents` must each be no greater than the dwelling's `dwelling_limit_cents` at quote time, otherwise `ERR_SUBLIMIT_EXCEEDS_LIMIT` (422)."

    Design: Corner/validations/sublimits_above_the_dwelling_limit_are_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_accepted_offer(
        api, dwelling_overrides={"dwelling_limit_cents": 5000000}
    )

    refused = api.create_policy(
        factories.create_policy_payload(
            ctx["dwelling"]["id"],
            ctx["insurer"]["id"],
            ctx["offer"]["id"],
            contents_sublimit_cents=400000,
            loss_of_use_sublimit_cents=5000001,
        ),
        make_insurer_headers(ctx["insurer"]["id"]),
    )
    validate_error(refused, ApiErrorId.SUBLIMIT_EXCEEDS_LIMIT)

    quotes = validate_success(
        api.list_policies({"dwelling_id": ctx["dwelling"]["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert quotes == [], (
        "Coverage D is measured against the dwelling limit, not against the contents sublimit"
    )


def test_06_sublimits_equal_to_the_dwelling_limit_are_quoted(api):
    """PRD §3.3: "Each sublimit must be strictly greater than zero and no larger than the named dwelling's `dwelling_limit_cents`; a sublimit above the dwelling limit is refused with `ERR_SUBLIMIT_EXCEEDS_LIMIT`."

    PRD §2.8: "Rung 74: `contents_sublimit_cents` and `loss_of_use_sublimit_cents` must each be no greater than the dwelling's `dwelling_limit_cents` at quote time, otherwise `ERR_SUBLIMIT_EXCEEDS_LIMIT` (422)."

    Design: Corner/validations/sublimit_exactly_equal_to_the_dwelling_limit_passes
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_accepted_offer(
        api, dwelling_overrides={"dwelling_limit_cents": 5000000}
    )

    quote = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"],
                ctx["insurer"]["id"],
                ctx["offer"]["id"],
                contents_sublimit_cents=5000000,
                loss_of_use_sublimit_cents=5000000,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        ),
        201,
    )
    assertions.assert_policy_shape(quote)
    assert quote["lifecycle_status"] == "QUOTED"
    assert quote["contents_sublimit_cents"] == 5000000, "equality is inside the rule"
    assert quote["loss_of_use_sublimit_cents"] == 5000000
    assert quote["rated_dwelling_limit_cents"] == 5000000


def test_07_quote_still_inside_its_window_cannot_be_expired_administratively(api):
    """PRD §3.4: "**Administrative quote expiry** moves `QUOTED → QUOTE_EXPIRED`, terminal, and is requested by supplying an `action` of `EXPIRE_QUOTE`; it requires the clock to be strictly past `quote_expires_at`, and a quote that is still inside its window is protected by `ERR_QUOTE_STILL_VALID`."

    PRD §2.8: "Rung 64: the logical clock must be strictly after `quote_expires_at` for the quote to be expired administratively, otherwise `ERR_QUOTE_STILL_VALID` (409)."

    Design: Corner/validations/expired_quote_cannot_be_bound_and_a_live_quote_cannot_be_expired
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_quoted_policy(api)
    quote = ctx["policy"]
    assert quote["lifecycle_status"] == "QUOTED"

    fixtures.set_clock(api, _shift_days(quote["quote_expires_at"], -1))
    refused = api.policy_lifecycle_action(
        quote["id"],
        factories.lifecycle_action_payload("EXPIRE_QUOTE"),
        PROGRAM_ADMIN_HEADERS,
    )
    validate_error(refused, ApiErrorId.QUOTE_STILL_VALID)

    untouched = validate_success(api.get_policy(quote["id"], PROGRAM_ADMIN_HEADERS))
    assert untouched["lifecycle_status"] == "QUOTED", (
        "the refused expiry left the quote exactly where it was"
    )


def test_08_quote_past_its_expiry_cannot_be_bound_but_can_be_expired(api):
    """PRD §3.4: "It requires the policy to still be `QUOTED`, and it requires the logical clock to be at or before `quote_expires_at`; a stale quote is refused with `ERR_QUOTE_EXPIRED`."

    PRD §2.8: "Rung 63: the logical clock must not have passed `quote_expires_at` when the quote is bound, otherwise `ERR_QUOTE_EXPIRED` (409)."

    Design: Corner/validations/expired_quote_cannot_be_bound_and_a_live_quote_cannot_be_expired
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_quoted_policy(api)
    quote = ctx["policy"]

    fixtures.set_clock(api, _shift_days(quote["quote_expires_at"], 1))
    refused = api.bind_policy(
        quote["id"], None, make_insurer_headers(ctx["insurer"]["id"])
    )
    validate_error(refused, ApiErrorId.QUOTE_EXPIRED)

    expired = validate_success(
        api.policy_lifecycle_action(
            quote["id"],
            factories.lifecycle_action_payload("EXPIRE_QUOTE"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert expired["lifecycle_status"] == "QUOTE_EXPIRED", (
        "past the thirty-day window the administrative expiry is the only move left"
    )


def _accepted_offer_for(api, insurer, county_code):
    """An insurer, a policyholder in one county, its dwelling and an accepted offer."""
    holder = fixtures.create_policyholder(api, county_code=county_code)
    dwelling = fixtures.create_dwelling(api, holder["id"])
    return fixtures.setup_accepted_offer(
        api,
        parties={"insurer": insurer, "policyholder": holder, "dwelling": dwelling},
    )


def _quote_for(api, ctx):
    """A quote on the context's dwelling, written by the context's insurer."""
    return validate_success(
        api.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"], ctx["insurer"]["id"], ctx["offer"]["id"]
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        ),
        201,
    )


def test_09_binding_into_the_epicenter_county_is_refused_while_the_moratorium_runs(api):
    """PRD §3.4: "If any catastrophe event whose `status` is `DECLARED`, `LOSS_AGGREGATION`, `CAPACITY_EXHAUSTED` or `ASSESSMENT_LEVIED` has an `epicenter_county_code` equal to the `county_code` of the policy's policyholder, and the logical clock lies at or after that event's `occurred_at` and strictly before sixty days after `occurred_at`, the bind is refused with `ERR_BINDING_MORATORIUM`."

    Design: Corner/validations/binding_moratorium_blocks_the_event_county_until_the_sixtieth_day
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    struck = _accepted_offer_for(api, insurer, "06037")
    calm = _accepted_offer_for(api, insurer, "06073")

    declared = fixtures.setup_declared_event(
        api,
        epicenter_county_code="06037",
        occurred_at=constants.CLOCK_EPOCH,
        magnitude=6.1,
    )
    assert declared["event"]["status"] == "DECLARED"

    struck_quote = _quote_for(api, struck)
    calm_quote = _quote_for(api, calm)
    insurer_headers = make_insurer_headers(insurer["id"])

    refused = api.bind_policy(struck_quote["id"], None, insurer_headers)
    validate_error(refused, ApiErrorId.BINDING_MORATORIUM)

    elsewhere = validate_success(api.bind_policy(calm_quote["id"], None, insurer_headers))
    assert elsewhere["lifecycle_status"] == "ACTIVE", (
        "a county the earthquake did not touch keeps writing new coverage"
    )


def test_10_binding_into_the_epicenter_county_resumes_on_the_sixtieth_day(api):
    """PRD §3.4: "The window is half-open at the far end: exactly sixty days after the event, binding in that county resumes."

    PRD §3.4: "If any catastrophe event whose `status` is `DECLARED`, `LOSS_AGGREGATION`, `CAPACITY_EXHAUSTED` or `ASSESSMENT_LEVIED` has an `epicenter_county_code` equal to the `county_code` of the policy's policyholder, and the logical clock lies at or after that event's `occurred_at` and strictly before sixty days after `occurred_at`, the bind is refused with `ERR_BINDING_MORATORIUM`."

    Design: Corner/validations/binding_moratorium_blocks_the_event_county_until_the_sixtieth_day
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    struck = _accepted_offer_for(api, insurer, "06037")
    fixtures.setup_declared_event(
        api,
        epicenter_county_code="06037",
        occurred_at=constants.CLOCK_EPOCH,
        magnitude=6.1,
    )
    insurer_headers = make_insurer_headers(insurer["id"])

    last_blocked_day = _shift_days(constants.CLOCK_EPOCH, constants.MORATORIUM_DAYS - 1)
    fixtures.set_clock(api, last_blocked_day)
    quote = _quote_for(api, struck)
    assert quote["lifecycle_status"] == "QUOTED", (
        "the moratorium bars binding only; the struck county may still be quoted"
    )
    refused = api.bind_policy(quote["id"], None, insurer_headers)
    validate_error(refused, ApiErrorId.BINDING_MORATORIUM)

    resumption = _shift_days(constants.CLOCK_EPOCH, constants.MORATORIUM_DAYS)
    fixtures.set_clock(api, resumption)
    bound = validate_success(api.bind_policy(quote["id"], None, insurer_headers))
    assert bound["lifecycle_status"] == "ACTIVE"
    assert bound["effective_at"].startswith("2026-09-30T00:00:00"), (
        "cover incepts at the clock reading of the sixtieth day"
    )


def test_11_fourth_return_for_information_is_refused_when_review_rounds_are_spent(api):
    """PRD §3.5: "`RETURN` moves `UNDER_REVIEW → RETURNED_FOR_INFO` and writes the supplied `denial_reason` onto the grant; it is available only while `review_round` is strictly less than three, and the fourth attempt is refused with `ERR_GRANT_REVIEW_ROUNDS_EXHAUSTED`."

    PRD §2.8: "Rung 56: a grant's `review_round` must be strictly less than three for the reviewer to return it for more information again, otherwise `ERR_GRANT_REVIEW_ROUNDS_EXHAUSTED` (409)."
    PRD §3.5: "A `GrantReviewer` (or program staff) takes the application up, moving `SUBMITTED → UNDER_REVIEW` and raising `review_round` by one; that increment happens each time the application *enters* review, and the cycle must still be `OPEN` for it to happen at all."

    Design: Corner/validations/fourth_return_for_information_is_rejected_when_review_rounds_are_exhausted
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=dict(CRIPPLE_WALL_DWELLING))
    ctx = fixtures.setup_submitted_grant(
        api,
        ctx=ctx,
        cycle_overrides=dict(BRACE_AND_BOLT_CYCLE, total_pool_cents=1000000),
        project_cost_estimate_cents=200000,
    )
    grant_id = ctx["grant"]["id"]
    assert ctx["grant"]["review_round"] == 0
    holder_headers = make_policyholder_headers(ctx["policyholder"]["id"])
    requests_for_information = (
        "Send the engineer's plan set.",
        "The plan set is unsigned.",
        "The load path is still not shown.",
    )

    for expected_round, info_request in enumerate(requests_for_information, start=1):
        under_review = validate_success(
            api.begin_grant_review(grant_id, None, GRANT_REVIEWER_HEADERS)
        )
        assert under_review["review_round"] == expected_round, (
            "each entry into review consumes exactly one round"
        )
        returned = api.review_grant(
            grant_id,
            factories.review_grant_payload("RETURN", info_request=info_request),
            GRANT_REVIEWER_HEADERS,
        )
        if expected_round < constants.MAX_REVIEW_ROUNDS:
            assert validate_success(returned)["status"] == "RETURNED_FOR_INFO"
            validate_success(api.resubmit_grant(grant_id, None, holder_headers))
        else:
            validate_error(returned, ApiErrorId.GRANT_REVIEW_ROUNDS_EXHAUSTED)

    approved = validate_success(
        api.review_grant(
            grant_id, factories.review_grant_payload("APPROVE"), GRANT_REVIEWER_HEADERS
        )
    )
    assert approved["status"] == "APPROVED", (
        "the exhausted counter gates the return decision alone"
    )
    assert approved["review_round"] == constants.MAX_REVIEW_ROUNDS, (
        "the refused return consumed no further round"
    )


def test_12_fourth_open_retrofit_project_is_refused_until_one_is_abandoned(api):
    """PRD §2.8: "Rung 57: a contractor may hold at most three projects in `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED` at any time, otherwise `ERR_CONTRACTOR_PROJECT_CAP` (409)."

    PRD §3.6: "A contractor may hold at most three open projects at once; a fourth is refused with `ERR_CONTRACTOR_PROJECT_CAP`."
    PRD §3.6: "Program staff may abandon a project from any of `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED`, with an optional `reason`; abandonment lowers the contractor's `open_project_count` by one, leaves any still-pending inspection rows in place while removing their hold on the contractor's calendar, and pointedly does **not** release the grant's reserved money — the grant must be withdrawn separately for that."
    PRD §3.6: "The new project opens in `SCHEDULED`, copies `scope_code` from the grant's `requested_scope`, starts `inspection_attempts` at zero, leaves `started_at` and `verified_at` null, and raises the contractor's `open_project_count` by one."

    Design: Corner/validations/contractor_open_project_cap_rejects_the_fourth_project
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=2000000
    )
    contractor = fixtures.create_contractor(api, certified_scopes=["CRIPPLE_WALL_BRACING"])

    funded_grants = []
    for _ in range(4):
        household = fixtures.setup_bound_policy(
            api, dwelling_overrides=dict(CRIPPLE_WALL_DWELLING)
        )
        household = fixtures.setup_reserved_grant(
            api, ctx=household, cycle=cycle, project_cost_estimate_cents=200000
        )
        assert household["grant"]["status"] == "FUNDS_RESERVED"
        funded_grants.append(household["grant"])

    def _assign(grant):
        return api.create_retrofit_project(
            factories.create_retrofit_project_payload(grant["id"], contractor["id"]),
            PROGRAM_ADMIN_HEADERS,
        )

    projects = [validate_success(_assign(grant), 201) for grant in funded_grants[:3]]
    census = validate_success(api.get_contractor(contractor["id"], PROGRAM_ADMIN_HEADERS))
    assert census["open_project_count"] == constants.MAX_OPEN_PROJECTS_PER_CONTRACTOR

    validate_error(_assign(funded_grants[3]), ApiErrorId.CONTRACTOR_PROJECT_CAP)

    abandoned = validate_success(
        api.abandon_project(
            projects[1]["id"],
            factories.reason_payload("The household withdrew site access"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert abandoned["status"] == "ABANDONED"
    census = validate_success(api.get_contractor(contractor["id"], PROGRAM_ADMIN_HEADERS))
    assert census["open_project_count"] == constants.MAX_OPEN_PROJECTS_PER_CONTRACTOR - 1, (
        "the cap counts the open projects the contractor holds now, not the ones it ever held"
    )

    fourth = validate_success(_assign(funded_grants[3]), 201)
    assertions.assert_retrofit_project_shape(fourth)
    assert fourth["status"] == "SCHEDULED"
    assert fourth["scope_code"] == "CRIPPLE_WALL_BRACING", (
        "the project takes its scope from the grant that funds it"
    )
