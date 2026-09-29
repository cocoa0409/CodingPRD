"""Transition behaviour of the program's state machines.

The residual earthquake program advances coverage, public money and catastrophe
losses through named state machines whose legal moves, refused moves and
declared side effects are all part of the contract. The tests here drive one
trigger at a time against a row in a known state: a first notice of loss that
must open in the initial state of both of its parallel dimensions at once, a
monitoring tremor that only becomes declarable once it clears the magnitude
floor and its treaty year carries cover, a bind that must apply every declared
side effect in a single response, action endpoints that are deliberately not
idempotent, terminal rows that refuse every further trigger, the two claim
dimensions advancing on disjoint triggers, the conditional grant cascade behind
a cancellation, the three ledgers a fund reservation reconciles at once, and a
denial that writes off the payment dimension without a cent ever being paid.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    PROGRAM_ADMIN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import (
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    GRANT_REVIEWER_HEADERS,
    GRANT_REVIEWER_USER_ID,
    PROGRAM_ADMIN_ALT_HEADERS,
    PROGRAM_ADMIN_ALT_USER_ID,
    make_contractor_headers,
    make_insurer_headers,
)

CRIPPLE_WALL_DWELLING = {"structure_type": "WOOD_FRAME_CRIPPLE_WALL"}
BRACE_AND_BOLT_CYCLE = {"program_track": "BRACE_AND_BOLT", "total_pool_cents": 1000000}


def _instant(value: str) -> datetime:
    """Read a server-written UTC instant, whether or not it carries fractions."""
    assert value is not None, "expected an instant, found null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_01_first_notice_of_loss_opens_in_both_initial_states_at_once(api):
    """PRD §3.8: "The new claim opens with `adjustment_status` at `FNOL_RECEIVED`, `payment_status` at `UNPAID`, `reopen_count` at zero, `denial_reason` an empty string, and every settlement figure — `deductible_applied_cents`, `dwelling_part_cents`, `contents_part_cents`, `loss_of_use_part_cents`, `provisional_payable_cents`, `final_payable_cents`, `payable_cents` and `paid_cents` — at zero."

    PRD §3.8: "The event's `claim_count` rises by one and its `version` rises by one."

    PRD §3.7: "The gross is the event's `aggregate_incurred_cents`, which is the sum of `final_payable_cents` over exactly those of its claims whose `adjustment_status` is `FINAL_ADJUSTED` or `CLOSED`; claims still at `FNOL_RECEIVED` or `PROVISIONAL_ADJUSTED`, and claims that were `DENIED`, contribute nothing."

    PRD §2.4: "Every resource also carries a `created_at` timestamp, formatted as an ISO 8601 UTC instant with exactly three fractional-second digits."

    Design: Corner/state_machines/new_claim_starts_in_fnol_received_and_unpaid
    """
    ctx = fixtures.setup_event_with_policy(api)

    claim = validate_success(
        api.create_claim(
            factories.create_claim_payload(
                ctx["policy"]["id"],
                ctx["event"]["id"],
                ctx["event"]["version"],
                structural_damage_cents=10000000,
                cosmetic_damage_cents=0,
                contents_damage_cents=0,
                loss_of_use_cents=0,
            ),
            CLAIM_ADJUSTER_HEADERS,
        ),
        201,
    )

    assert claim["adjustment_status"] == "FNOL_RECEIVED"
    assert claim["payment_status"] == "UNPAID"
    assert claim["reopen_count"] == 0
    assert claim["denial_reason"] == ""
    for field in (
        "deductible_applied_cents",
        "dwelling_part_cents",
        "contents_part_cents",
        "loss_of_use_part_cents",
        "provisional_payable_cents",
        "final_payable_cents",
        "payable_cents",
        "paid_cents",
    ):
        assert claim[field] == 0, f"{field} should still be zero at notice"
    assert claim["version"] == 1

    event = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event["claim_count"] == 1
    assert event["version"] == ctx["event"]["version"] + 1
    assert event["aggregate_incurred_cents"] == 0
    assert event["status"] == "DECLARED"


def test_02_declaring_a_monitored_tremor_moves_it_to_declared(api):
    """PRD §3.7: "The event opens at `MONITORING` with every aggregate at zero — `aggregate_incurred_cents`, `retained_cents`, `ceded_total_cents`, `uncovered_cents`, `assessment_shortfall_cents`, `admin_loading_cents`, `assessment_total_cents` and `claim_count` — and with `version` at 1."

    PRD §3.7: "The record derives `treaty_year` as the calendar year of `occurred_at`, and that derived year is what selects the reinsurance tower the loss will run through."

    PRD §3.7: "Declaring the event moves `MONITORING → DECLARED` and is what opens claim intake."

    PRD §2.4: "Any operation that changes a row refreshes that row's `updated_at` and increments its `version`, including the cascaded mutations that a single request performs on rows other than its direct target."

    Design: Corner/state_machines/declare_moves_a_monitoring_event_to_declared
    """
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=1,
        attachment_point_cents=100000000,
        limit_cents=50000000,
        ceded_pct=0.90,
    )
    event = fixtures.create_catastrophe_event(
        api,
        magnitude=6.4,
        epicenter_county_code="06111",
        occurred_at="2026-09-05T00:00:00Z",
        retention_cents=100000000,
    )
    assert event["status"] == "MONITORING"
    assert event["version"] == 1
    assert event["treaty_year"] == 2026

    declared = validate_success(
        api.declare_event(event["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert declared["status"] == "DECLARED"
    assert declared["version"] == 2


def test_03_a_tremor_below_the_declaration_floor_cannot_be_declared(api):
    """PRD §3.7: "The `magnitude` must be at least 5.0, and a smaller tremor is refused with `ERR_MAGNITUDE_BELOW_DECLARATION_FLOOR`."

    PRD §2.8: "Rung 43: an event's `magnitude` must be at least 5.0 to be declared, otherwise `ERR_MAGNITUDE_BELOW_DECLARATION_FLOOR` (422)."

    Design: Corner/state_machines/declare_below_the_magnitude_floor_or_without_a_treaty_is_rejected
    """
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=1,
        attachment_point_cents=100000000,
        limit_cents=50000000,
        ceded_pct=0.90,
    )
    small = fixtures.create_catastrophe_event(
        api,
        magnitude=4.9,
        epicenter_county_code="06029",
        occurred_at="2026-09-04T00:00:00Z",
        retention_cents=100000000,
    )

    validate_error(
        api.declare_event(small["id"], None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.MAGNITUDE_BELOW_DECLARATION_FLOOR,
    )

    unchanged = validate_success(
        api.get_catastrophe_event(small["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert unchanged["status"] == "MONITORING"
    assert unchanged["version"] == 1


def test_04_a_treaty_year_without_active_cover_cannot_take_a_declaration(api):
    """PRD §3.7: "And the event's `treaty_year` must have at least one reinsurance layer whose `status` is `ACTIVE`, or the declaration is refused with `ERR_NO_REINSURANCE_PROGRAM` — the programme will not take losses onto a year for which it bought no cover."

    PRD §3.7: "A new layer opens `ACTIVE` with `ceded_cents` at zero."

    PRD §3.7: "Declaring the event moves `MONITORING → DECLARED` and is what opens claim intake."

    Design: Corner/state_machines/declare_below_the_magnitude_floor_or_without_a_treaty_is_rejected
    """
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    event = fixtures.create_catastrophe_event(
        api,
        magnitude=6.6,
        epicenter_county_code="06095",
        occurred_at="2026-09-05T00:00:00Z",
        retention_cents=100000000,
    )

    validate_error(
        api.declare_event(event["id"], None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.NO_REINSURANCE_PROGRAM,
    )
    still_monitoring = validate_success(
        api.get_catastrophe_event(event["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert still_monitoring["status"] == "MONITORING"
    assert still_monitoring["version"] == 1

    layer = fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=1,
        attachment_point_cents=100000000,
        limit_cents=50000000,
        ceded_pct=0.90,
    )
    assert layer["status"] == "ACTIVE"

    declared = validate_success(
        api.declare_event(event["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert declared["status"] == "DECLARED"


def test_05_binding_applies_every_declared_side_effect_in_one_response(api):
    """PRD §3.4: "Binding is the exclusive privilege of the participating insurer and moves the coverage dimension `QUOTED → ACTIVE`."

    PRD §3.4: "On success, `effective_at` is set to the current clock, `expires_at` to three hundred and sixty-five days later, `rated_dwelling_limit_cents` is re-snapshotted from the dwelling's live limit, and the insurer's `policies_bound_count` rises by one."

    PRD §3.4: "Binding does **not** re-rate: `base_premium_cents` and `annual_premium_cents` are the numbers the quote produced under the `QUOTE_TIME` variant, and `rating_variant` stays `QUOTE_TIME`."

    PRD §3.3: "The quote opens with `lifecycle_status` at `QUOTED`, `mitigation_status` at `UNMITIGATED`, `term_number` at 1, `mitigation_discount_cents` and `prorated_credit_cents` at zero, and both `effective_at` and `expires_at` null, since nothing is in force yet."

    Design: Corner/state_machines/bind_applies_every_declared_side_effect_in_one_response
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_quoted_policy(api)
    quote = ctx["policy"]
    assert quote["lifecycle_status"] == "QUOTED"
    assert quote["version"] == 1
    assert quote["effective_at"] is None
    assert quote["expires_at"] is None
    assert ctx["insurer"]["policies_bound_count"] == 0

    bound = validate_success(
        api.bind_policy(
            quote["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        )
    )

    assert bound["lifecycle_status"] == "ACTIVE"
    assert _instant(bound["effective_at"]) == _instant(constants.CLOCK_EPOCH)
    assert _instant(bound["expires_at"]) - _instant(bound["effective_at"]) == timedelta(
        days=constants.TERM_DAYS
    )
    assert bound["rated_dwelling_limit_cents"] == ctx["dwelling"]["dwelling_limit_cents"]
    assert bound["base_premium_cents"] == quote["base_premium_cents"]
    assert bound["annual_premium_cents"] == quote["annual_premium_cents"]
    assert bound["rating_variant"] == "QUOTE_TIME"
    assert bound["version"] == 2

    insurer = validate_success(
        api.get_insurer(ctx["insurer"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert insurer["policies_bound_count"] == 1


def test_06_a_second_bind_on_an_in_force_policy_is_refused(api):
    """PRD §2.8: "Rung 18: a policy's `lifecycle_status` must be `QUOTED` to be bound or to have its quote administratively expired, otherwise `ERR_POLICY_NOT_QUOTED` (409)."

    PRD §3.4: "It requires the policy to still be `QUOTED`, and it requires the logical clock to be at or before `quote_expires_at`; a stale quote is refused with `ERR_QUOTE_EXPIRED`."

    Design: Corner/state_machines/repeating_bind_and_repeating_begin_review_are_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api)
    assert ctx["policy"]["lifecycle_status"] == "ACTIVE"
    bound_version = ctx["policy"]["version"]

    validate_error(
        api.bind_policy(
            ctx["policy"]["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        ),
        ApiErrorId.POLICY_NOT_QUOTED,
    )

    policy = validate_success(
        api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert policy["lifecycle_status"] == "ACTIVE"
    assert policy["version"] == bound_version, "the refused retry must not touch the row"


def test_07_a_second_begin_review_does_not_open_another_review_round(api):
    """PRD §3.5: "A new application opens in `SUBMITTED` with `review_round` at zero, `approved_amount_cents` at zero, `funded_from_bucket` at `NONE` and `denial_reason` an empty string."

    PRD §3.5: "A `GrantReviewer` (or program staff) takes the application up, moving `SUBMITTED → UNDER_REVIEW` and raising `review_round` by one; that increment happens each time the application *enters* review, and the cycle must still be `OPEN` for it to happen at all."

    PRD §2.8: "Rung 22: a `RetrofitGrant` must be in the status its action requires — `SUBMITTED` to begin review, `UNDER_REVIEW` to record a review decision, `RETURNED_FOR_INFO` to resubmit, `APPROVED` to reserve funds, and any of `SUBMITTED`, `UNDER_REVIEW`, `RETURNED_FOR_INFO`, `APPROVED` or `FUNDS_RESERVED` to withdraw — otherwise `ERR_GRANT_INVALID_STATE` (409)."

    Design: Corner/state_machines/repeating_bind_and_repeating_begin_review_are_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING)
    ctx = fixtures.setup_submitted_grant(
        api,
        ctx=ctx,
        cycle_overrides=BRACE_AND_BOLT_CYCLE,
        project_cost_estimate_cents=250000,
    )
    assert ctx["grant"]["status"] == "SUBMITTED"
    assert ctx["grant"]["review_round"] == 0

    under_review = validate_success(
        api.begin_grant_review(ctx["grant"]["id"], None, GRANT_REVIEWER_HEADERS)
    )
    assert under_review["status"] == "UNDER_REVIEW"
    assert under_review["review_round"] == 1

    validate_error(
        api.begin_grant_review(ctx["grant"]["id"], None, GRANT_REVIEWER_HEADERS),
        ApiErrorId.GRANT_INVALID_STATE,
    )

    grant = validate_success(
        api.get_retrofit_grant(ctx["grant"]["id"], GRANT_REVIEWER_HEADERS)
    )
    assert grant["status"] == "UNDER_REVIEW"
    assert grant["review_round"] == 1, "the refused retry must not increment the round"


def test_08_finalizing_an_adjustment_is_unreachable_from_first_notice_of_loss(api):
    """PRD §2.8: "Rung 31: a `Claim` must be in the status its action requires — `FNOL_RECEIVED` to post the provisional adjustment or to deny, `PROVISIONAL_ADJUSTED` to finalize, `PROVISIONAL_ADJUSTED` or `FINAL_ADJUSTED` to record a payment, and `FINAL_ADJUSTED` to reopen — otherwise `ERR_CLAIM_INVALID_STATE` (409)."

    PRD §3.8: "**The final pass** moves the claim `PROVISIONAL_ADJUSTED → FINAL_ADJUSTED` and must be signed by a different adjuster identity than the provisional one; the event must not be `CLOSED`, and it must not be `ASSESSMENT_LEVIED`."

    Design: Corner/state_machines/triggers_absent_from_the_current_state_row_are_rejected
    """
    ctx = fixtures.setup_filed_claim(api, structural_damage_cents=9000000)
    assert ctx["claim"]["adjustment_status"] == "FNOL_RECEIVED"

    validate_error(
        api.finalize_claim_adjustment(
            ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS
        ),
        ApiErrorId.CLAIM_INVALID_STATE,
    )

    claim = validate_success(api.get_claim(ctx["claim"]["id"], CLAIM_ADJUSTER_HEADERS))
    assert claim["adjustment_status"] == "FNOL_RECEIVED"
    assert claim["final_payable_cents"] == 0
    assert claim["payable_cents"] == 0


def test_09_requesting_an_inspection_is_unreachable_from_a_scheduled_project(api):
    """PRD §2.8: "Rung 23: a `RetrofitProject` must be in the status its action requires — `SCHEDULED` or `REWORK_REQUIRED` to start work, `IN_PROGRESS` to request inspection, `AWAITING_INSPECTION` for an inspection to be booked against it, and any of `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED` to abandon — otherwise `ERR_PROJECT_INVALID_STATE` (409)."

    PRD §3.6: "Declaring the work ready moves `IN_PROGRESS → AWAITING_INSPECTION` and is the contractor's exclusive act."

    PRD §3.6: "The new project opens in `SCHEDULED`, copies `scope_code` from the grant's `requested_scope`, starts `inspection_attempts` at zero, leaves `started_at` and `verified_at` null, and raises the contractor's `open_project_count` by one."

    Design: Corner/state_machines/triggers_absent_from_the_current_state_row_are_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING)
    ctx = fixtures.setup_scheduled_project(
        api,
        ctx=ctx,
        cycle_overrides=BRACE_AND_BOLT_CYCLE,
        project_cost_estimate_cents=250000,
    )
    assert ctx["grant"]["status"] == "FUNDS_RESERVED"
    assert ctx["project"]["status"] == "SCHEDULED"
    assert ctx["project"]["started_at"] is None

    validate_error(
        api.request_project_inspection(
            ctx["project"]["id"],
            None,
            make_contractor_headers(ctx["contractor"]["id"]),
        ),
        ApiErrorId.PROJECT_INVALID_STATE,
    )

    project = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert project["status"] == "SCHEDULED"
    assert project["inspection_attempts"] == 0


def test_10_an_administratively_expired_offer_can_never_be_re_extended(api):
    """PRD §3.1: "The recorded offer opens in `PENDING` with `offer_round` set to 1, `offered_at` set to the current logical clock and `expires_at` set to sixty days after `offered_at`; `responded_at` stays null while the offer is unanswered, and the insurer's `offers_recorded_count` rises by one."

    PRD §3.1: "An unanswered offer can be retired administratively, moving `PENDING → EXPIRED`, but only once the clock has passed `expires_at`; attempting it earlier is refused with `ERR_OFFER_STILL_VALID`, and attempting it on an offer that has already been answered is refused with `ERR_OFFER_ALREADY_RESPONDED`."

    PRD §3.1: "Re-extension is available only to the insurer that owns the offer, and only from `DECLINED` or `ACCEPTED`: a `PENDING` or `EXPIRED` offer produces `ERR_OFFER_NOT_REOFFERABLE`."

    Design: Corner/state_machines/terminal_offer_and_terminal_policy_states_refuse_every_further_trigger
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_pending_offer(api)
    offer = ctx["offer"]
    assert offer["status"] == "PENDING"
    assert offer["offer_round"] == 1
    assert offer["responded_at"] is None
    assert _instant(offer["expires_at"]) - _instant(offer["offered_at"]) == timedelta(
        days=constants.OFFER_VALID_DAYS
    )

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    expired = validate_success(
        api.expire_offer(offer["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert expired["status"] == "EXPIRED"

    validate_error(
        api.reoffer(offer["id"], None, make_insurer_headers(ctx["insurer"]["id"])),
        ApiErrorId.OFFER_NOT_REOFFERABLE,
    )

    still_expired = validate_success(
        api.get_mandatory_offer(offer["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert still_expired["status"] == "EXPIRED"
    assert still_expired["offer_round"] == 1
    assert still_expired["responded_at"] is None


def test_11_a_cancelled_policy_refuses_a_second_cancellation_and_a_renewal(api):
    """PRD §3.4: "**Cancellation** moves `ACTIVE → CANCELLED`, which is terminal, and may be requested by the household that owns the policy, by the insurer that wrote it, or by program staff; where the caller is one of the two entity-backed roles, its `X-User-ID` must match the policy's `policyholder_id` or `insurer_id` respectively, and a mismatch is `ERR_NOT_RESOURCE_OWNER`."

    PRD §2.8: "Rung 19: a policy's `lifecycle_status` must be `ACTIVE` to be renewed, cancelled, lapsed, to have a mitigation discount revoked, or to have a claim filed against it, otherwise `ERR_POLICY_NOT_ACTIVE` (409)."

    Design: Corner/state_machines/terminal_offer_and_terminal_policy_states_refuse_every_further_trigger
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api)

    cancelled = validate_success(
        api.cancel_policy(
            ctx["policy"]["id"],
            factories.reason_payload("moved out of state"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert cancelled["lifecycle_status"] == "CANCELLED"
    terminal_version = cancelled["version"]

    validate_error(
        api.cancel_policy(ctx["policy"]["id"], None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.POLICY_NOT_ACTIVE,
    )
    validate_error(
        api.renew_policy(ctx["policy"]["id"], None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.POLICY_NOT_ACTIVE,
    )

    policy = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert policy["lifecycle_status"] == "CANCELLED"
    assert policy["term_number"] == 1
    assert policy["version"] == terminal_version


def test_12_the_payment_dimension_advances_without_moving_the_adjustment_dimension(api):
    """PRD §3.8: "They advance on disjoint triggers, and only two rules couple them at all: a claim cannot be closed until it is fully paid, and denial writes off the payment dimension."

    PRD §3.8: "Both adjustment passes begin from the same deductible, and it is computed from the term snapshot rather than the live dwelling: `deductible_applied_cents` is the policy's `rated_dwelling_limit_cents` multiplied by its `deductible_pct` and divided by one hundred, rounded half up to whole cents."

    PRD §3.8: "The acting `X-User-ID` is recorded as `provisional_adjuster_user_id`, and `payment_status` is not touched, remaining `UNPAID`."

    PRD §3.8: "On success `paid_cents` rises by the amount, and the payment dimension moves according to the arithmetic: `UNPAID → PARTIALLY_PAID` when the running total is still short of `payable_cents`, `UNPAID → PAID` when a single payment settles the whole payable exactly, and `PARTIALLY_PAID → PAID` when a later payment brings the total to exactly `payable_cents`."

    PRD §3.8: "`adjustment_status` is never changed by a payment."

    PRD §3.8: "`payment_status` is not changed by finalization."

    Design: Corner/state_machines/payment_dimension_advances_without_moving_the_adjustment_dimension
    """
    ctx = fixtures.setup_provisionally_adjusted_claim(
        api,
        structural_damage_cents=10000000,
        cosmetic_damage_cents=0,
        contents_damage_cents=0,
        loss_of_use_cents=0,
    )
    claim = ctx["claim"]
    assert claim["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert claim["payment_status"] == "UNPAID"
    assert claim["deductible_applied_cents"] == 2000000
    assert claim["provisional_payable_cents"] == 8000000
    assert claim["payable_cents"] == 8000000

    part_paid = validate_success(
        api.record_claim_payment(
            claim["id"], factories.record_payment_payload(3000000), PROGRAM_ADMIN_HEADERS
        )
    )
    assert part_paid["payment_status"] == "PARTIALLY_PAID"
    assert part_paid["paid_cents"] == 3000000
    assert part_paid["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert part_paid["payable_cents"] == 8000000

    finalized = validate_success(
        api.finalize_claim_adjustment(claim["id"], None, CLAIM_ADJUSTER_ALT_HEADERS)
    )
    assert finalized["adjustment_status"] == "FINAL_ADJUSTED"
    assert finalized["final_payable_cents"] == 8000000
    assert finalized["payable_cents"] == 8000000
    assert finalized["payment_status"] == "PARTIALLY_PAID"
    assert finalized["paid_cents"] == 3000000

    settled = validate_success(
        api.record_claim_payment(
            claim["id"], factories.record_payment_payload(5000000), PROGRAM_ADMIN_HEADERS
        )
    )
    assert settled["payment_status"] == "PAID"
    assert settled["paid_cents"] == 8000000
    assert settled["adjustment_status"] == "FINAL_ADJUSTED"


def test_13_cancellation_withdraws_pre_reservation_grants_and_spares_committed_ones(api):
    """PRD §3.4: "Both cancellation and lapse carry the same conditional grant cascade: every retrofit grant on the policy whose status is `SUBMITTED`, `UNDER_REVIEW`, `RETURNED_FOR_INFO` or `APPROVED` is moved to `WITHDRAWN`, because the coverage that made the dwelling grant-eligible is gone, while grants already in `FUNDS_RESERVED` or `VERIFIED_COMPLETE` are left exactly as they are, because their money is already committed and unwinding it is a separate, deliberate act."

    PRD §3.4: "Neither cancellation nor lapse changes `mitigation_status`."

    PRD §3.5: "Three figures keep the pool honest, and the third is the residual of the first two: `reserved_cents` is the sum of the awards on this cycle's grants currently in `FUNDS_RESERVED`, `disbursed_cents` is the sum of the awards on its grants in `VERIFIED_COMPLETE`, and `uncommitted_cents` is `total_pool_cents` less `reserved_cents` less `disbursed_cents`."

    PRD §3.5: "Withdrawing from any of the four pre-reservation statuses touches no ledger at all, because nothing was reserved."

    Design: Corner/state_machines/cancellation_withdraws_pre_reservation_grants_and_spares_reserved_ones
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE)

    approved_ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides=CRIPPLE_WALL_DWELLING
    )
    approved_ctx = fixtures.setup_approved_grant(
        api, ctx=approved_ctx, cycle=cycle, project_cost_estimate_cents=250000
    )
    reserved_ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides=CRIPPLE_WALL_DWELLING
    )
    reserved_ctx = fixtures.setup_reserved_grant(
        api, ctx=reserved_ctx, cycle=cycle, project_cost_estimate_cents=250000
    )

    assert approved_ctx["grant"]["status"] == "APPROVED"
    assert approved_ctx["grant"]["approved_amount_cents"] == 250000
    assert reserved_ctx["grant"]["status"] == "FUNDS_RESERVED"
    assert reserved_ctx["grant"]["funded_from_bucket"] == "TIER_LOW"

    cancelled_approved = validate_success(
        api.cancel_policy(
            approved_ctx["policy"]["id"],
            factories.reason_payload("moved out of state"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    cancelled_reserved = validate_success(
        api.cancel_policy(
            reserved_ctx["policy"]["id"],
            factories.reason_payload("moved out of state"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert cancelled_approved["lifecycle_status"] == "CANCELLED"
    assert cancelled_reserved["lifecycle_status"] == "CANCELLED"
    assert cancelled_approved["mitigation_status"] == "UNMITIGATED"
    assert cancelled_reserved["mitigation_status"] == "RETROFIT_PENDING"

    withdrawn = validate_success(
        api.get_retrofit_grant(approved_ctx["grant"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["funded_from_bucket"] == "NONE"

    spared = validate_success(
        api.get_retrofit_grant(reserved_ctx["grant"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert spared["status"] == "FUNDS_RESERVED"
    assert spared["funded_from_bucket"] == "TIER_LOW"
    assert spared["approved_amount_cents"] == 250000

    pool = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert pool["reserved_cents"] == 250000
    assert pool["disbursed_cents"] == 0
    assert pool["uncommitted_cents"] == 750000
    assertions.assert_grant_pool_conserved(pool)


def test_14_reserving_funds_reconciles_the_cycle_the_dwelling_and_the_policy(api):
    """PRD §3.5: "On success the ledger moves as a pair — `reserved_cents` rises by the award and `uncommitted_cents` is recomputed as `total_pool_cents` less `reserved_cents` less `disbursed_cents` — the cycle's `version` rises by one, and the dwelling's `grant_lifetime_count` rises by one."

    PRD §3.5: "The reservation also reaches across into the coverage side: the policy named by the grant, provided it is `ACTIVE` and its `mitigation_status` is still `UNMITIGATED`, advances `UNMITIGATED → RETROFIT_PENDING`, and the policy's own `version` rises accordingly."

    PRD §3.5: "It is also the operation guarded by segregation of duties: the acting `X-User-ID` must differ from the grant's `approved_by_user_id`, and the reserving identity is recorded as `reserved_by_user_id`."

    PRD §3.5: "Step one: if the applicant's own income tier's usage plus this award is no greater than that tier's cap, the award draws from the applicant's own tier and `funded_from_bucket` records it."

    PRD §3.5: "A new cycle opens with `status` `OPEN`, `reserved_cents` and `disbursed_cents` at zero, `uncommitted_cents` equal to `total_pool_cents`, and `version` at 1."

    PRD §3.2: "A new dwelling opens with `retrofit_status` at `NONE`, `verified_retrofit_scope` at `NONE` and `grant_lifetime_count` at zero."

    Design: Corner/state_machines/reserve_funds_syncs_the_cycle_ledger_and_the_dwelling_grant_counter
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api, dwelling_overrides=CRIPPLE_WALL_DWELLING)
    assert ctx["dwelling"]["grant_lifetime_count"] == 0
    assert ctx["policy"]["mitigation_status"] == "UNMITIGATED"

    cycle = fixtures.create_grant_cycle(api, **BRACE_AND_BOLT_CYCLE)
    assert cycle["status"] == "OPEN"
    assert cycle["reserved_cents"] == 0
    assert cycle["disbursed_cents"] == 0
    assert cycle["uncommitted_cents"] == cycle["total_pool_cents"]
    assert cycle["version"] == 1

    ctx = fixtures.setup_approved_grant(
        api, ctx=ctx, cycle=cycle, project_cost_estimate_cents=250000
    )
    assert ctx["grant"]["status"] == "APPROVED"
    assert ctx["grant"]["approved_amount_cents"] == 250000
    assert ctx["grant"]["approved_by_user_id"] == GRANT_REVIEWER_USER_ID

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

    pool = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert pool["reserved_cents"] == 250000
    assert pool["disbursed_cents"] == 0
    assert pool["uncommitted_cents"] == 750000
    assert pool["version"] == pinned["version"] + 1
    assertions.assert_grant_pool_conserved(pool)

    dwelling = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert dwelling["grant_lifetime_count"] == 1
    assert dwelling["retrofit_status"] == "NONE"
    assert dwelling["verified_retrofit_scope"] == "NONE"

    policy = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert policy["mitigation_status"] == "RETROFIT_PENDING"
    assert policy["mitigation_discount_cents"] == 0
    assert policy["version"] == ctx["policy"]["version"] + 1


def test_15_denial_zeroes_the_payable_and_writes_off_the_payment_dimension(api):
    """PRD §3.8: "**Denial** is available only at notice: a `ClaimAdjuster` supplies a mandatory `denial_reason` and the claim moves `FNOL_RECEIVED → DENIED`, which is terminal."

    PRD §3.8: "Denial zeroes both `payable_cents` and `provisional_payable_cents`, records the reason, and cascades across dimensions to move `payment_status` `UNPAID → WRITTEN_OFF`."

    PRD §3.8: "The event's `claim_count` is deliberately not decremented — the notice was received, whatever its outcome."

    PRD §3.7: "The gross is the event's `aggregate_incurred_cents`, which is the sum of `final_payable_cents` over exactly those of its claims whose `adjustment_status` is `FINAL_ADJUSTED` or `CLOSED`; claims still at `FNOL_RECEIVED` or `PROVISIONAL_ADJUSTED`, and claims that were `DENIED`, contribute nothing."

    Design: Corner/state_machines/deny_zeroes_the_payable_and_writes_off_the_payment_dimension
    """
    ctx = fixtures.setup_filed_claim(
        api,
        structural_damage_cents=4000000,
        cosmetic_damage_cents=500000,
        contents_damage_cents=200000,
        loss_of_use_cents=100000,
    )
    assert ctx["claim"]["adjustment_status"] == "FNOL_RECEIVED"
    assert ctx["claim"]["payment_status"] == "UNPAID"

    denied = validate_success(
        api.deny_claim(
            ctx["claim"]["id"],
            factories.deny_claim_payload("damage predates the event"),
            CLAIM_ADJUSTER_HEADERS,
        )
    )
    assert denied["adjustment_status"] == "DENIED"
    assert denied["payment_status"] == "WRITTEN_OFF"
    assert denied["payable_cents"] == 0
    assert denied["provisional_payable_cents"] == 0
    assert denied["paid_cents"] == 0
    assert denied["denial_reason"] == "damage predates the event"
    assert denied["structural_damage_cents"] == 4000000
    assert denied["cosmetic_damage_cents"] == 500000
    assert denied["contents_damage_cents"] == 200000
    assert denied["loss_of_use_cents"] == 100000

    event = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event["claim_count"] == 1
    assert event["aggregate_incurred_cents"] == 0
    assert event["status"] == "DECLARED"
