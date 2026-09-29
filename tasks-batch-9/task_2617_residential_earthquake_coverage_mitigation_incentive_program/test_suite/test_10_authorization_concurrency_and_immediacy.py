"""Identity, duty segregation, version pinning and read-after-write immediacy.

The residual earthquake program hands every operation to exactly one capacity:
the household attests its own retrofit and answers its own mandatory offer, the
admitted carrier alone binds the coverage it wrote, program staff alone declare
the earthquake and commit cycle money, the reviewer alone sets the award, the
certified contractor alone declares its work ready and the field inspector alone
records the verifying visit. This module walks those exclusive operations from
both sides: each role on its own operation, every role refused another role's
operation, malformed identity headers refused before anything else is looked at,
and the three entity-backed roles fenced inside their own principal's rows. It
then exercises the two shared ledgers that require the caller to pin the version
it last read - the funding cycle behind a reservation and the catastrophe event
behind a first notice of loss - the cumulative failed-inspection tally that puts
a contractor on probation, and the guarantee that every derived field a request
computes is already visible in the response that caused it.
"""
from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    FIELD_INSPECTOR_ALT_HEADERS,
    FIELD_INSPECTOR_HEADERS,
    GRANT_REVIEWER_HEADERS,
    PROGRAM_ADMIN_ALT_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import (
    CLAIM_ADJUSTER_ALT_USER_ID,
    CLAIM_ADJUSTER_USER_ID,
    FIELD_INSPECTOR_ALT_USER_ID,
    FIELD_INSPECTOR_USER_ID,
    GRANT_REVIEWER_USER_ID,
    PROGRAM_ADMIN_ALT_USER_ID,
    make_contractor_headers,
    make_headers_with_empty_user_id,
    make_headers_with_unknown_role,
    make_headers_without_role,
    make_headers_without_user_id,
    make_insurer_headers,
    make_policyholder_headers,
)

# A cripple-wall dwelling of pre-code vintage: the one structure the retrofit
# programme funds at its highest cap and the one the deepest discount is
# reserved for.
CRIPPLE_WALL_DWELLING = {
    "structure_type": "WOOD_FRAME_CRIPPLE_WALL",
    "year_built": 1957,
}
BRACE_AND_BOLT_CYCLE = {
    "program_track": "BRACE_AND_BOLT",
    "total_pool_cents": 1000000,
}
SMALL_AWARD_GRANT = {"project_cost_estimate_cents": 200000}


def test_01_policyholder_alone_attests_a_retrofit_and_answers_the_offer(api):
    """PRD §3.2: "The first is the owner's own attestation: a `Policyholder` self-declares a completed retrofit by supplying a `declared_scope`, which moves `retrofit_status` to `SELF_DECLARED` and writes `declared_scope` into `verified_retrofit_scope`."

    PRD §3.1: "The policyholder answers the offer, moving it `PENDING → ACCEPTED` or `PENDING → DECLINED`, by supplying a `response` of either `ACCEPT` or `DECLINE`; only the owner named on the offer may answer it."

    Design: Corner/rbac/policy_side_roles_each_perform_their_own_exclusive_operations
    """
    ctx = fixtures.setup_pending_offer(api, dwelling_overrides=CRIPPLE_WALL_DWELLING)
    household = make_policyholder_headers(ctx["policyholder"]["id"])

    dwelling = validate_success(
        api.declare_retrofit(
            ctx["dwelling"]["id"],
            factories.declare_retrofit_payload("CRIPPLE_WALL_BRACING"),
            household,
        )
    )
    assert dwelling["retrofit_status"] == "SELF_DECLARED"
    assert dwelling["verified_retrofit_scope"] == "CRIPPLE_WALL_BRACING"

    offer = validate_success(
        api.respond_to_offer(
            ctx["offer"]["id"], factories.respond_to_offer_payload("ACCEPT"), household
        )
    )
    assert offer["status"] == "ACCEPTED"
    assert offer["responded_at"] is not None


def test_02_insurer_alone_binds_while_program_staff_alone_declare_the_event(api):
    """PRD §3.4: "Binding is the exclusive privilege of the participating insurer and moves the coverage dimension `QUOTED → ACTIVE`."

    PRD §3.7: "Declaring the event moves `MONITORING → DECLARED` and is what opens claim intake."

    Design: Corner/rbac/policy_side_roles_each_perform_their_own_exclusive_operations
    """
    ctx = fixtures.setup_quoted_policy(api)

    policy = validate_success(
        api.bind_policy(
            ctx["policy"]["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        )
    )
    assert policy["lifecycle_status"] == "ACTIVE"
    assert policy["effective_at"] is not None

    fixtures.create_reinsurance_layer(api)
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    event = fixtures.create_catastrophe_event(api)
    declared = validate_success(api.declare_event(event["id"], None, PROGRAM_ADMIN_HEADERS))
    assert declared["status"] == "DECLARED"
    assert declared["version"] == event["version"] + 1


def test_03_claim_adjuster_alone_posts_the_provisional_adjustment(api):
    """PRD §3.8: "**The provisional pass**, posted by a `ClaimAdjuster`, moves the claim `FNOL_RECEIVED → PROVISIONAL_ADJUSTED` and requires the event to be `DECLARED`, `LOSS_AGGREGATION` or `CAPACITY_EXHAUSTED`."

    PRD §3.8: "The acting `X-User-ID` is recorded as `provisional_adjuster_user_id`, and `payment_status` is not touched, remaining `UNPAID`."

    Design: Corner/rbac/policy_side_roles_each_perform_their_own_exclusive_operations
    """
    ctx = fixtures.setup_event_with_policy(api)
    ctx = fixtures.setup_filed_claim(
        api,
        ctx=ctx,
        adjuster_headers=make_policyholder_headers(ctx["policyholder"]["id"]),
    )
    assert ctx["claim"]["adjustment_status"] == "FNOL_RECEIVED"

    claim = validate_success(
        api.adjust_claim_provisional(ctx["claim"]["id"], None, CLAIM_ADJUSTER_HEADERS)
    )
    assert claim["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert claim["provisional_adjuster_user_id"] == CLAIM_ADJUSTER_USER_ID
    assert claim["payable_cents"] == claim["provisional_payable_cents"]
    assert claim["payment_status"] == "UNPAID"


def test_04_reviewer_sets_the_award_and_program_staff_commit_the_cycle_money(api):
    """PRD §3.5: "A `GrantReviewer` (or program staff) takes the application up, moving `SUBMITTED → UNDER_REVIEW` and raising `review_round` by one; that increment happens each time the application *enters* review, and the cycle must still be `OPEN` for it to happen at all."

    PRD §3.5: "`APPROVE` moves `UNDER_REVIEW → APPROVED`, records the acting `X-User-ID` as `approved_by_user_id`, and computes the award into `approved_amount_cents`."

    PRD §3.5: "An approved award becomes a real charge against the pool only when program staff reserve it, moving `APPROVED → FUNDS_RESERVED`."

    Design: Corner/rbac/mitigation_side_roles_each_perform_their_own_exclusive_operations
    """
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING)
    cycle = fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE)
    ctx = fixtures.setup_submitted_grant(
        api, ctx=ctx, cycle=cycle, **SMALL_AWARD_GRANT
    )

    under_review = validate_success(
        api.begin_grant_review(ctx["grant"]["id"], None, GRANT_REVIEWER_HEADERS)
    )
    assert under_review["status"] == "UNDER_REVIEW"
    assert under_review["review_round"] == 1

    approved = validate_success(
        api.review_grant(
            ctx["grant"]["id"],
            factories.review_grant_payload("APPROVE"),
            GRANT_REVIEWER_HEADERS,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_amount_cents"] == 200000
    assert approved["approved_by_user_id"] == GRANT_REVIEWER_USER_ID

    pinned = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    reserved = validate_success(
        api.reserve_grant_funds(
            ctx["grant"]["id"],
            factories.reserve_funds_payload(pinned["version"]),
            PROGRAM_ADMIN_ALT_HEADERS,
        )
    )
    assert reserved["status"] == "FUNDS_RESERVED"
    assert reserved["reserved_by_user_id"] == PROGRAM_ADMIN_ALT_USER_ID

    after = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert after["reserved_cents"] == 200000
    assert after["version"] == pinned["version"] + 1
    assertions.assert_grant_pool_conserved(after)


def test_05_contractor_declares_the_work_ready_and_the_inspector_records_it(api):
    """PRD §3.6: "Declaring the work ready moves `IN_PROGRESS → AWAITING_INSPECTION` and is the contractor's exclusive act."

    PRD §3.6: "Every recorded outcome writes `inspector_user_id` from the acting header and `recorded_at` from the clock, and raises the project's `inspection_attempts` by one."

    Design: Corner/rbac/mitigation_side_roles_each_perform_their_own_exclusive_operations
    """
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING)
    cycle = fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE)
    ctx = fixtures.setup_project_in_progress(
        api, ctx=ctx, cycle=cycle, **SMALL_AWARD_GRANT
    )
    assert ctx["contractor"]["certification_status"] == "CERTIFIED"
    contractor = make_contractor_headers(ctx["contractor"]["id"])

    awaiting = validate_success(
        api.request_project_inspection(ctx["project"]["id"], None, contractor)
    )
    assert awaiting["status"] == "AWAITING_INSPECTION"

    inspection = validate_success(
        api.create_inspection(
            factories.create_inspection_payload(ctx["project"]["id"]),
            FIELD_INSPECTOR_HEADERS,
        ),
        201,
    )
    assert inspection["result"] == "PENDING"

    fixtures.set_clock(api, "2026-08-04T09:30:00Z")
    recorded = validate_success(
        api.record_inspection_result(
            inspection["id"],
            factories.record_result_payload("PASS"),
            FIELD_INSPECTOR_HEADERS,
        )
    )
    assert recorded["result"] == "PASS"
    assert recorded["inspector_user_id"] == FIELD_INSPECTOR_USER_ID
    assert recorded["recorded_at"] is not None

    project = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert project["inspection_attempts"] == 1


def test_06_program_staff_cannot_bind_coverage_on_a_carriers_behalf(api):
    """PRD §2.1: "When the named role is well-formed but is not among the roles authorised for the target operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §2.8: "Every check in the system therefore occupies a fixed rung on one ordered ladder, and **the rung with the lowest number wins**: the server evaluates the rungs in ascending numeric order and returns the first violation it finds, without evaluating any later rung."

    Design: Corner/rbac/every_role_is_denied_another_roles_exclusive_operation
    """
    refusal = validate_error(
        api.bind_policy(constants.NON_EXISTENT_ID, None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.UNAUTHORIZED,
    )
    assert refusal["error_id"] == ApiErrorId.UNAUTHORIZED.value
    assert refusal["message"].strip()


def test_07_each_role_is_refused_an_operation_reserved_for_another_role(api):
    """PRD §2.8: "Rung 2: the named role must appear in the target endpoint's authorised role list, otherwise `ERR_UNAUTHORIZED` (403); this too applies to every endpoint."

    PRD §2.8: "Rung 4: every identifier appearing in the path must resolve to an existing row, validated left to right, otherwise that resource kind's not-found code (404); this applies to every endpoint that carries a path identifier."

    Design: Corner/rbac/every_role_is_denied_another_roles_exclusive_operation
    """
    unallocated = constants.NON_EXISTENT_ID

    validate_error(
        api.review_grant(
            unallocated,
            factories.review_grant_payload("APPROVE"),
            make_insurer_headers(unallocated),
        ),
        ApiErrorId.UNAUTHORIZED,
    )
    validate_error(
        api.create_insurer(
            factories.create_insurer_payload(), make_policyholder_headers(unallocated)
        ),
        ApiErrorId.UNAUTHORIZED,
    )
    validate_error(
        api.record_inspection_result(
            unallocated, factories.record_result_payload("PASS"), GRANT_REVIEWER_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
    )
    validate_error(
        api.adjust_claim_provisional(unallocated, None, FIELD_INSPECTOR_HEADERS),
        ApiErrorId.UNAUTHORIZED,
    )
    validate_error(
        api.request_project_inspection(unallocated, None, CLAIM_ADJUSTER_HEADERS),
        ApiErrorId.UNAUTHORIZED,
    )
    validate_error(
        api.declare_event(unallocated, None, make_contractor_headers(unallocated)),
        ApiErrorId.UNAUTHORIZED,
    )

    rows, meta = validate_paginated(api.list_insurers(None, PROGRAM_ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_08_absent_or_undeclared_role_header_is_rejected_before_the_body(api):
    """PRD §2.1: "When `X-User-Role` is absent, or carries a string that is not one of the seven roles defined below, the request is rejected with `ERR_MISSING_ROLE` (HTTP 401)."

    PRD §2.8: "Rung 1: `X-User-Role` must be present and must name one of the seven declared roles, otherwise `ERR_MISSING_ROLE` (401); this applies to every endpoint."

    Design: Corner/rbac/missing_x_role_and_missing_x_user_id_headers_are_rejected
    """
    validate_error(
        api.create_insurer(
            factories.create_insurer_payload(name="Headerless Insurance"),
            make_headers_without_role("admin-1"),
        ),
        ApiErrorId.MISSING_ROLE,
    )
    validate_error(
        api.create_insurer(
            {"name": "Superuser Insurance"}, make_headers_with_unknown_role("admin-1")
        ),
        ApiErrorId.MISSING_ROLE,
    )

    rows, meta = validate_paginated(api.list_insurers(None, PROGRAM_ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_09_duty_segregated_operations_require_an_acting_identifier(api):
    """PRD §2.1: "Five operations additionally require `X-User-ID` to be present and non-empty, because they are the operations on which the program enforces separation of duties: recording a grant review decision, reserving cycle funds against an approved grant, recording an inspection result, posting a provisional claim adjustment, and finalizing a claim adjustment."

    PRD §2.1: "On those five, a missing `X-User-ID` is rejected with `ERR_MISSING_USER_ID` (HTTP 401)."

    Design: Corner/rbac/missing_x_role_and_missing_x_user_id_headers_are_rejected
    """
    unallocated = constants.NON_EXISTENT_ID

    validate_error(
        api.review_grant(
            unallocated,
            factories.review_grant_payload("APPROVE"),
            make_headers_without_user_id("GrantReviewer"),
        ),
        ApiErrorId.MISSING_USER_ID,
    )
    validate_error(
        api.reserve_grant_funds(
            unallocated,
            factories.reserve_funds_payload(1),
            make_headers_without_user_id("ProgramAdmin"),
        ),
        ApiErrorId.MISSING_USER_ID,
    )
    validate_error(
        api.record_inspection_result(
            unallocated,
            factories.record_result_payload("PASS"),
            make_headers_without_user_id("FieldInspector"),
        ),
        ApiErrorId.MISSING_USER_ID,
    )
    validate_error(
        api.adjust_claim_provisional(
            unallocated, None, make_headers_without_user_id("ClaimAdjuster")
        ),
        ApiErrorId.MISSING_USER_ID,
    )
    validate_error(
        api.finalize_claim_adjustment(
            unallocated, None, make_headers_without_user_id("ClaimAdjuster")
        ),
        ApiErrorId.MISSING_USER_ID,
    )
    validate_error(
        api.finalize_claim_adjustment(
            unallocated, None, make_headers_with_empty_user_id("ClaimAdjuster")
        ),
        ApiErrorId.MISSING_USER_ID,
    )


def test_10_a_policyholder_cannot_reach_another_households_dwelling_or_offer(api):
    """PRD §2.1: "A caller acting as `Policyholder` may read or act only on `Dwelling`, `Policy`, `MandatoryOffer`, `RetrofitGrant` and `Claim` rows that resolve to its own `policyholder_id`."

    PRD §3.1: "The policyholder answers the offer, moving it `PENDING → ACCEPTED` or `PENDING → DECLINED`, by supplying a `response` of either `ACCEPT` or `DECLINE`; only the owner named on the offer may answer it."

    PRD §2.8: "Rung 6 is the ownership rule of section 2.1, producing `ERR_NOT_RESOURCE_OWNER` (403) on every read and write performed by one of the three entity-backed roles."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_another_principals_rows
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    household = fixtures.setup_pending_offer(api)
    neighbour = fixtures.create_policyholder(api)
    neighbour_headers = make_policyholder_headers(neighbour["id"])

    validate_error(
        api.get_dwelling(household["dwelling"]["id"], neighbour_headers),
        ApiErrorId.NOT_RESOURCE_OWNER,
    )
    validate_error(
        api.respond_to_offer(
            household["offer"]["id"],
            factories.respond_to_offer_payload("ACCEPT"),
            neighbour_headers,
        ),
        ApiErrorId.NOT_RESOURCE_OWNER,
    )
    still_pending = validate_success(
        api.get_mandatory_offer(household["offer"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert still_pending["status"] == "PENDING"
    assert still_pending["responded_at"] is None

    answered = validate_success(
        api.respond_to_offer(
            household["offer"]["id"],
            factories.respond_to_offer_payload("ACCEPT"),
            make_policyholder_headers(household["policyholder"]["id"]),
        )
    )
    assert answered["status"] == "ACCEPTED"
    assert answered["responded_at"] is not None


def test_11_an_insurer_cannot_read_or_bind_a_rival_carriers_policy(api):
    """PRD §2.1: "A caller acting as `ParticipatingInsurer` may read or act only on rows that resolve to its own `insurer_id`."

    PRD §2.1: "Ownership is enforced uniformly for the three entity-backed roles and produces `ERR_NOT_RESOURCE_OWNER` (HTTP 403) when it fails."

    PRD §2.8: "Rung 6 is the ownership rule of section 2.1, producing `ERR_NOT_RESOURCE_OWNER` (403) on every read and write performed by one of the three entity-backed roles."

    PRD §3.4: "Binding is the exclusive privilege of the participating insurer and moves the coverage dimension `QUOTED → ACTIVE`."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_another_principals_rows
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_quoted_policy(api)
    rival = fixtures.create_insurer(api)
    rival_headers = make_insurer_headers(rival["id"])

    validate_error(
        api.get_policy(ctx["policy"]["id"], rival_headers),
        ApiErrorId.NOT_RESOURCE_OWNER,
    )
    validate_error(
        api.bind_policy(ctx["policy"]["id"], None, rival_headers),
        ApiErrorId.NOT_RESOURCE_OWNER,
    )
    unbound = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert unbound["lifecycle_status"] == "QUOTED"
    assert unbound["effective_at"] is None

    bound = validate_success(
        api.bind_policy(
            ctx["policy"]["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        )
    )
    assert bound["lifecycle_status"] == "ACTIVE"
    assert bound["insurer_id"] == ctx["insurer"]["id"]


def test_12_the_reviewer_who_released_the_award_cannot_certify_the_finished_work(api):
    """PRD §2.8: "rung 8, the `X-User-ID` recording an inspection result must differ from the `approved_by_user_id` of the grant funding the inspected project, otherwise `ERR_SOD_INSPECTOR_CONFLICT` (403)"

    PRD §3.6: "The acting `X-User-ID` must differ from the `approved_by_user_id` of the grant funding the project, so the reviewer who released public money cannot also certify that it bought something."

    Design: Corner/rbac/inspector_cannot_record_a_result_on_a_grant_it_approved
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_scheduled_inspection(
        api,
        ctx=fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING),
        cycle=fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE),
        reviewer_headers=build_user_headers(FIELD_INSPECTOR_USER_ID, "GrantReviewer"),
        reserver_headers=PROGRAM_ADMIN_ALT_HEADERS,
        **SMALL_AWARD_GRANT,
    )
    assert ctx["grant"]["approved_by_user_id"] == FIELD_INSPECTOR_USER_ID
    assert ctx["grant"]["status"] == "FUNDS_RESERVED"

    fixtures.set_clock(api, "2026-08-04T09:30:00Z")
    validate_error(
        api.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload("PASS"),
            FIELD_INSPECTOR_HEADERS,
        ),
        ApiErrorId.SOD_INSPECTOR_CONFLICT,
    )
    untouched = validate_success(
        api.get_inspection(ctx["inspection"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert untouched["result"] == "PENDING"
    assert untouched["inspector_user_id"] is None
    still_awaiting = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert still_awaiting["status"] == "AWAITING_INSPECTION"
    assert still_awaiting["inspection_attempts"] == 0

    recorded = validate_success(
        api.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload("PASS"),
            FIELD_INSPECTOR_ALT_HEADERS,
        )
    )
    assert recorded["result"] == "PASS"
    assert recorded["inspector_user_id"] == FIELD_INSPECTOR_ALT_USER_ID
    verified_grant = validate_success(
        api.get_retrofit_grant(ctx["grant"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert verified_grant["status"] == "VERIFIED_COMPLETE"


def test_13_the_final_settlement_must_be_signed_by_a_second_adjuster(api):
    """PRD §2.8: "rung 9, the `X-User-ID` finalizing an adjustment must differ from the claim's `provisional_adjuster_user_id`, otherwise `ERR_SOD_ADJUSTER_CONFLICT` (403)"

    PRD §3.8: "**The final pass** moves the claim `PROVISIONAL_ADJUSTED → FINAL_ADJUSTED` and must be signed by a different adjuster identity than the provisional one; the event must not be `CLOSED`, and it must not be `ASSESSMENT_LEVIED`."

    Design: Corner/rbac/finalize_adjustment_requires_a_second_adjuster_identity
    """
    ctx = fixtures.setup_provisionally_adjusted_claim(
        api,
        adjuster_headers=CLAIM_ADJUSTER_HEADERS,
        structural_damage_cents=6000000,
    )
    assert ctx["claim"]["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert ctx["claim"]["provisional_adjuster_user_id"] == CLAIM_ADJUSTER_USER_ID
    assert ctx["claim"]["deductible_applied_cents"] == 2000000
    assert ctx["claim"]["provisional_payable_cents"] == 4000000
    assert ctx["claim"]["payable_cents"] == 4000000

    validate_error(
        api.finalize_claim_adjustment(ctx["claim"]["id"], None, CLAIM_ADJUSTER_HEADERS),
        ApiErrorId.SOD_ADJUSTER_CONFLICT,
    )
    unchanged = validate_success(api.get_claim(ctx["claim"]["id"], PROGRAM_ADMIN_HEADERS))
    assert unchanged["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert unchanged["final_payable_cents"] == 0
    assert unchanged["payable_cents"] == 4000000

    finalized = validate_success(
        api.finalize_claim_adjustment(
            ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS
        )
    )
    assert finalized["adjustment_status"] == "FINAL_ADJUSTED"
    assert finalized["final_adjuster_user_id"] == CLAIM_ADJUSTER_ALT_USER_ID
    assert finalized["provisional_adjuster_user_id"] == CLAIM_ADJUSTER_USER_ID
    assert finalized["final_payable_cents"] == 4000000
    assert finalized["payable_cents"] == 4000000
    assertions.assert_settlement_parts_sum(finalized, 4000000)


def test_14_a_reservation_pinned_to_a_moved_cycle_balance_is_refused_then_replayed(api):
    """PRD §2.7: "The fund-reservation operation on an approved retrofit grant requires a non-optional `expected_grant_cycle_version` in its body, carrying the client's last observed `version` of the `GrantCycle` the grant applies against. If that number does not equal the funding cycle's current `version`, the request is rejected with `ERR_STALE_GRANT_CYCLE_VERSION` and HTTP status 412. Two different `APPROVED` grants may each legitimately draw from the same `OPEN` cycle while the pool still has room, so no state precondition excludes the second reviewer; the stale pinned version is the only signal that a reviewer is acting on a cycle balance that has already moved beneath them."

    PRD §3.5: "On success the ledger moves as a pair — `reserved_cents` rises by the award and `uncommitted_cents` is recomputed as `total_pool_cents` less `reserved_cents` less `disbursed_cents` — the cycle's `version` rises by one, and the dwelling's `grant_lifetime_count` rises by one."

    Design: Corner/cross_cutting_layers/stale_expected_grant_cycle_version_is_refused_then_accepted_after_a_reread
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE)
    first = fixtures.setup_approved_grant(
        api,
        ctx=fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING),
        cycle=cycle,
        **SMALL_AWARD_GRANT,
    )
    second = fixtures.setup_approved_grant(
        api,
        ctx=fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING),
        cycle=cycle,
        **SMALL_AWARD_GRANT,
    )
    assert first["grant"]["approved_amount_cents"] == 200000
    assert second["grant"]["approved_amount_cents"] == 200000

    before = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    stale_pin = before["version"]
    assert before["reserved_cents"] == 0
    assert before["uncommitted_cents"] == 1000000

    committed = validate_success(
        api.reserve_grant_funds(
            first["grant"]["id"],
            factories.reserve_funds_payload(stale_pin),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert committed["status"] == "FUNDS_RESERVED"

    validate_error(
        api.reserve_grant_funds(
            second["grant"]["id"],
            factories.reserve_funds_payload(stale_pin),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.STALE_GRANT_CYCLE_VERSION,
    )
    unmoved = validate_success(api.get_retrofit_grant(second["grant"]["id"], PROGRAM_ADMIN_HEADERS))
    assert unmoved["status"] == "APPROVED"
    assert unmoved["funded_from_bucket"] == "NONE"
    midway = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert midway["reserved_cents"] == 200000
    assert midway["uncommitted_cents"] == 800000
    assert midway["version"] == stale_pin + 1

    replayed = validate_success(
        api.reserve_grant_funds(
            second["grant"]["id"],
            factories.reserve_funds_payload(midway["version"]),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert replayed["status"] == "FUNDS_RESERVED"
    after = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert after["reserved_cents"] == 400000
    assert after["disbursed_cents"] == 0
    assert after["uncommitted_cents"] == 600000
    assert after["version"] == midway["version"] + 1
    assertions.assert_grant_pool_conserved(after)


def test_15_a_notice_of_loss_pinned_to_a_superseded_event_version_is_refused(api):
    """PRD §2.7: "First notice of loss requires a non-optional `expected_event_version` in its body, carrying the client's last observed `version` of the `CatastropheEvent` the loss is claimed against. A mismatch with the event's current `version` is rejected with `ERR_STALE_EVENT_VERSION` and HTTP status 412. Many claims may legitimately be filed against the same declared event, so a second filing is never blocked by a state precondition; the stale pinned version is what marks a filer whose picture of the event — including whether its capacity has already been exhausted by another adjuster's loss aggregation — predates the change."

    PRD §3.8: "The event's `claim_count` rises by one and its `version` rises by one."

    Design: Corner/cross_cutting_layers/stale_expected_event_version_is_refused_on_a_first_notice_of_loss
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    first = fixtures.setup_bound_policy(api)
    second = fixtures.setup_bound_policy(api)
    fixtures.create_reinsurance_layer(api)
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    event = validate_success(
        api.declare_event(
            fixtures.create_catastrophe_event(api)["id"], None, PROGRAM_ADMIN_HEADERS
        )
    )
    stale_pin = event["version"]
    assert event["status"] == "DECLARED"
    assert event["claim_count"] == 0

    accepted = validate_success(
        api.create_claim(
            factories.create_claim_payload(
                first["policy"]["id"], event["id"], stale_pin
            ),
            CLAIM_ADJUSTER_HEADERS,
        ),
        201,
    )
    assert accepted["adjustment_status"] == "FNOL_RECEIVED"

    validate_error(
        api.create_claim(
            factories.create_claim_payload(
                second["policy"]["id"], event["id"], stale_pin
            ),
            CLAIM_ADJUSTER_ALT_HEADERS,
        ),
        ApiErrorId.STALE_EVENT_VERSION,
    )
    midway = validate_success(
        api.get_catastrophe_event(event["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert midway["claim_count"] == 1
    assert midway["version"] == stale_pin + 1

    replayed = validate_success(
        api.create_claim(
            factories.create_claim_payload(
                second["policy"]["id"], event["id"], midway["version"]
            ),
            CLAIM_ADJUSTER_ALT_HEADERS,
        ),
        201,
    )
    assert replayed["adjustment_status"] == "FNOL_RECEIVED"
    assert replayed["payment_status"] == "UNPAID"
    after = validate_success(api.get_catastrophe_event(event["id"], PROGRAM_ADMIN_HEADERS))
    assert after["claim_count"] == 2
    assert after["version"] == midway["version"] + 1


def test_16_the_cumulative_failure_tally_puts_the_contractor_on_probation_at_three(api):
    """PRD §3.6: "A **failing** result is deliberately shallow. It sets `result` to `FAIL`, sends the project back `AWAITING_INSPECTION → REWORK_REQUIRED`, and raises the contractor's `failed_inspection_count` by one; when that incremented tally reaches three and the contractor is currently `CERTIFIED`, `certification_status` moves `CERTIFIED → PROBATION` in the same request."

    PRD §3.6: "Restoring a contractor to `CERTIFIED` deliberately does not reset `failed_inspection_count`: the tally is cumulative history, not a strike counter that clears on reinstatement."

    PRD §3.6: "Every recorded outcome writes `inspector_user_id` from the acting header and `recorded_at` from the clock, and raises the project's `inspection_attempts` by one."

    Design: Corner/cross_cutting_layers/cumulative_failed_inspection_counter_trips_probation_at_the_third_failure
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_scheduled_inspection(
        api,
        ctx=fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING),
        cycle=fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE),
        **SMALL_AWARD_GRANT,
    )
    contractor_id = ctx["contractor"]["id"]
    contractor_headers = make_contractor_headers(contractor_id)
    assert ctx["contractor"]["certification_status"] == "CERTIFIED"
    assert ctx["contractor"]["failed_inspection_count"] == 0

    fixtures.set_clock(api, "2026-08-04T09:30:00Z")
    failed = validate_success(
        api.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload("FAIL", deficiency_note="Sill plate unbolted"),
            FIELD_INSPECTOR_HEADERS,
        )
    )
    assert failed["result"] == "FAIL"
    assert failed["inspector_user_id"] == FIELD_INSPECTOR_USER_ID
    after_first = validate_success(api.get_contractor(contractor_id, PROGRAM_ADMIN_HEADERS))
    assert after_first["failed_inspection_count"] == 1
    assert after_first["certification_status"] == "CERTIFIED"
    reworking = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert reworking["status"] == "REWORK_REQUIRED"
    assert reworking["inspection_attempts"] == 1

    def fail_again(window_start, window_end, reading):
        restarted = validate_success(
            api.start_project_work(ctx["project"]["id"], None, contractor_headers)
        )
        assert restarted["status"] == "IN_PROGRESS"
        ready = validate_success(
            api.request_project_inspection(ctx["project"]["id"], None, contractor_headers)
        )
        assert ready["status"] == "AWAITING_INSPECTION"
        visit = validate_success(
            api.create_inspection(
                factories.create_inspection_payload(
                    ctx["project"]["id"], window_start, window_end
                ),
                FIELD_INSPECTOR_HEADERS,
            ),
            201,
        )
        assert visit["result"] == "PENDING"
        fixtures.set_clock(api, reading)
        outcome = validate_success(
            api.record_inspection_result(
                visit["id"], factories.record_result_payload("FAIL"), FIELD_INSPECTOR_HEADERS
            )
        )
        assert outcome["result"] == "FAIL"
        return validate_success(api.get_contractor(contractor_id, PROGRAM_ADMIN_HEADERS))

    after_second = fail_again(
        "2026-08-04T12:00:00Z", "2026-08-04T13:00:00Z", "2026-08-04T12:30:00Z"
    )
    assert after_second["failed_inspection_count"] == 2
    assert after_second["certification_status"] == "CERTIFIED"

    after_third = fail_again(
        "2026-08-04T15:00:00Z", "2026-08-04T16:00:00Z", "2026-08-04T15:30:00Z"
    )
    assert after_third["failed_inspection_count"] == 3
    assert after_third["certification_status"] == "PROBATION"

    restored = validate_success(
        api.set_contractor_certification(
            contractor_id, factories.certification_payload("CERTIFIED"), PROGRAM_ADMIN_HEADERS
        )
    )
    assert restored["certification_status"] == "CERTIFIED"
    assert restored["failed_inspection_count"] == 3

    after_fourth = fail_again(
        "2026-08-04T18:00:00Z", "2026-08-04T19:00:00Z", "2026-08-04T18:30:00Z"
    )
    assert after_fourth["failed_inspection_count"] == 4
    assert after_fourth["certification_status"] == "PROBATION"

    final_project = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert final_project["status"] == "REWORK_REQUIRED"
    assert final_project["inspection_attempts"] == 4
    untouched_dwelling = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert untouched_dwelling["retrofit_status"] == "NONE"
    assert untouched_dwelling["verified_retrofit_scope"] == "NONE"
    still_reserved = validate_success(
        api.get_retrofit_grant(ctx["grant"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert still_reserved["status"] == "FUNDS_RESERVED"


def test_17_derived_figures_are_already_present_in_the_response_that_computed_them(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    PRD §3.4: "On success, `effective_at` is set to the current clock, `expires_at` to three hundred and sixty-five days later, `rated_dwelling_limit_cents` is re-snapshotted from the dwelling's live limit, and the insurer's `policies_bound_count` rises by one."

    PRD §3.4: "Binding does **not** re-rate: `base_premium_cents` and `annual_premium_cents` are the numbers the quote produced under the `QUOTE_TIME` variant, and `rating_variant` stays `QUOTE_TIME`."

    PRD §3.6: "Hop one, on the inspection and the project: `result` becomes `PASS`, and the project advances `AWAITING_INSPECTION → VERIFIED` with `verified_at` stamped from the clock."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_quoted_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING)
    quote = ctx["policy"]
    assert quote["effective_at"] is None
    assert quote["expires_at"] is None

    bound = validate_success(
        api.bind_policy(quote["id"], None, make_insurer_headers(ctx["insurer"]["id"]))
    )
    assert bound["lifecycle_status"] == "ACTIVE"
    assert bound["effective_at"].startswith("2026-08-01T00:00:00")
    assert bound["expires_at"].startswith("2027-08-01T00:00:00")
    assert bound["rated_dwelling_limit_cents"] == 20000000
    assert bound["rating_variant"] == "QUOTE_TIME"
    assert bound["base_premium_cents"] == quote["base_premium_cents"]
    assert bound["annual_premium_cents"] == quote["annual_premium_cents"]
    assert bound["mitigation_status"] == "UNMITIGATED"
    bind_premium = bound["annual_premium_cents"]

    carrier = validate_success(api.get_insurer(ctx["insurer"]["id"], PROGRAM_ADMIN_HEADERS))
    assert carrier["policies_bound_count"] == 1

    ctx["policy"] = bound
    cycle = fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE)
    ctx = fixtures.setup_approved_grant(api, ctx=ctx, cycle=cycle, **SMALL_AWARD_GRANT)
    pinned = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    reserved = validate_success(
        api.reserve_grant_funds(
            ctx["grant"]["id"],
            factories.reserve_funds_payload(pinned["version"]),
            PROGRAM_ADMIN_ALT_HEADERS,
        )
    )
    assert reserved["status"] == "FUNDS_RESERVED"
    assert reserved["funded_from_bucket"] == "TIER_LOW"
    assert reserved["reserved_by_user_id"] == PROGRAM_ADMIN_ALT_USER_ID
    assert reserved["approved_by_user_id"] == GRANT_REVIEWER_USER_ID
    ctx["grant"] = reserved

    committed_cycle = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert committed_cycle["reserved_cents"] == 200000
    assert committed_cycle["uncommitted_cents"] == 800000
    pending_policy = validate_success(api.get_policy(bound["id"], PROGRAM_ADMIN_HEADERS))
    assert pending_policy["mitigation_status"] == "RETROFIT_PENDING"

    contractor = fixtures.create_contractor(api)
    project = validate_success(
        api.create_retrofit_project(
            factories.create_retrofit_project_payload(reserved["id"], contractor["id"]),
            make_contractor_headers(contractor["id"]),
        ),
        201,
    )
    assert project["scope_code"] == "CRIPPLE_WALL_BRACING"
    assert project["inspection_attempts"] == 0
    contractor_headers = make_contractor_headers(contractor["id"])
    validate_success(api.start_project_work(project["id"], None, contractor_headers))
    validate_success(api.request_project_inspection(project["id"], None, contractor_headers))
    visit = validate_success(
        api.create_inspection(
            factories.create_inspection_payload(project["id"]), FIELD_INSPECTOR_HEADERS
        ),
        201,
    )
    fixtures.set_clock(api, "2026-08-04T09:30:00Z")
    passed = validate_success(
        api.record_inspection_result(
            visit["id"], factories.record_result_payload("PASS"), FIELD_INSPECTOR_HEADERS
        )
    )
    assert passed["result"] == "PASS"
    assert passed["inspector_user_id"] == FIELD_INSPECTOR_USER_ID
    assert passed["recorded_at"].startswith("2026-08-04T09:30:00")

    verified_project = validate_success(
        api.get_retrofit_project(project["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert verified_project["status"] == "VERIFIED"
    assert verified_project["verified_at"].startswith("2026-08-04T09:30:00")
    assert verified_project["inspection_attempts"] == 1

    verified_dwelling = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert verified_dwelling["retrofit_status"] == "VERIFIED"
    assert verified_dwelling["verified_retrofit_scope"] == "CRIPPLE_WALL_BRACING"
    assert verified_dwelling["grant_lifetime_count"] == 1

    completed_grant = validate_success(
        api.get_retrofit_grant(reserved["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert completed_grant["status"] == "VERIFIED_COMPLETE"

    settled_cycle = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert settled_cycle["reserved_cents"] == 0
    assert settled_cycle["disbursed_cents"] == 200000
    assert settled_cycle["uncommitted_cents"] == 800000
    assertions.assert_grant_pool_conserved(settled_cycle)

    discounted = validate_success(api.get_policy(bound["id"], PROGRAM_ADMIN_HEADERS))
    assert discounted["mitigation_status"] == "DISCOUNT_APPLIED"
    assert discounted["mitigation_discount_cents"] > 0
    assert discounted["annual_premium_cents"] < bind_premium
    assert discounted["prorated_credit_cents"] > 0
    assertions.assert_premium_ledger_consistent(discounted)
