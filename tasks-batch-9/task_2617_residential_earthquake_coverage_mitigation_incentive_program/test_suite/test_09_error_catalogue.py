"""Every refusal in the residual earthquake programme's error catalogue must be
reachable and must name itself.

The programme answers a failed request with exactly one machine-readable error
identifier, chosen by the priority ladder, so a caller can tell a missing row
from an unowned one, a duplicate offer from a stale quote, a bucket that is full
from a pool that is exhausted, and a contractor working outside its certified
scopes from one whose certification has simply run out. The tests below walk the
mandatory-offer and quote path, the retrofit funding pool, the contractor and
inspection chain, the catastrophe event and claim life, the post-event assessment
and the reinsurance tower, and drive each documented refusal on its own, with the
surrounding preconditions satisfied so that only the rule under test can fail.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, PROGRAM_ADMIN_HEADERS, constants, factories, fixtures
from test_helpers.test_users import (
    CLAIM_ADJUSTER_HEADERS,
    FIELD_INSPECTOR_HEADERS,
    PROGRAM_ADMIN_ALT_HEADERS,
    make_contractor_headers,
    make_insurer_headers,
    make_policyholder_headers,
)

# A dwelling the retrofit programme actually funds: cripple-wall construction of
# pre-code vintage, which is what carries a non-zero scope cost cap.
RETROFITTABLE_DWELLING = {
    "structure_type": "WOOD_FRAME_CRIPPLE_WALL",
    "year_built": 1968,
}
# The one funding track used by every grant scenario below, so that no two cycles
# in a single scenario can collide on the same track's application window.
BRACE_AND_BOLT = {"program_track": "BRACE_AND_BOLT"}
# The instant the booked verification visit opens, so a test can move the clock
# onto it before an outcome is reported.
VISIT_WINDOW_START = "2026-08-04T09:00:00Z"


def _cover_on_a_retrofittable_dwelling(api):
    """An in-force policy over a dwelling the grant programme funds."""
    return fixtures.setup_bound_policy(
        api, dwelling_overrides=dict(RETROFITTABLE_DWELLING)
    )


def _event_at_capacity_exhausted(api, market_share_pct, spare_cover=False):
    """One large finalised loss that outruns retention and the single layer.

    A 300,000,000-cent dwelling limit at a five per cent deductible carries a
    15,000,000-cent deductible, so a 250,000,000-cent structural loss finalises
    at 235,000,000. Against a 100,000,000-cent retention and one layer attaching
    at 100,000,000 for 50,000,000 at ninety per cent, 45,000,000 is ceded and
    90,000,000 is left uncovered, which drives the event to CAPACITY_EXHAUSTED.

    A second, untouched cover over another dwelling may be bound alongside it, so
    that a first notice of loss can still be attempted after the levy without
    running into the epicenter county's binding moratorium.
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api, market_share_pct=market_share_pct)
    parties = fixtures.setup_parties(
        api,
        insurer=insurer,
        dwelling_overrides={
            "county_hazard_tier": "TIER_1",
            "soil_class": "ROCK",
            "structure_type": "WOOD_FRAME_SLAB",
            "year_built": 2006,
            "dwelling_limit_cents": 300000000,
        },
    )
    ctx = fixtures.setup_bound_policy(
        api,
        parties=parties,
        deductible_pct=5,
        contents_sublimit_cents=1000000,
        loss_of_use_sublimit_cents=500000,
    )
    spare = fixtures.setup_bound_policy(api) if spare_cover else None
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    ctx.update(
        fixtures.setup_declared_event(
            api,
            layer_overrides={"limit_cents": 50000000, "ceded_pct": 0.90},
            retention_cents=100000000,
        )
    )
    ctx = fixtures.setup_finally_adjusted_claim(
        api, ctx=ctx, structural_damage_cents=250000000
    )
    ctx["event"] = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert ctx["claim"]["final_payable_cents"] == 235000000
    assert ctx["event"]["ceded_total_cents"] == 45000000
    assert ctx["event"]["uncovered_cents"] == 90000000
    assert ctx["event"]["status"] == "CAPACITY_EXHAUSTED"
    ctx["spare_policy"] = spare["policy"] if spare is not None else None
    return ctx


def test_01_every_path_identifier_answers_with_its_own_resource_not_found(api):
    """PRD §2.4: "Because the topology is flat, most paths carry a single identifier, and a request naming a row that does not exist is rejected with the 404 belonging to that resource kind — `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_DWELLING_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_GRANT_CYCLE_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_LAYER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or `ERR_ALLOCATION_NOT_FOUND`, each with HTTP status 404."

    Design: Corner/errors/every_remaining_path_id_not_found_error_is_triggerable
    """
    present = fixtures.create_insurer(api, name="Present Insurance")

    probes = [
        (api.get_insurer, ApiErrorId.INSURER_NOT_FOUND),
        (api.get_mandatory_offer, ApiErrorId.OFFER_NOT_FOUND),
        (api.get_policy, ApiErrorId.POLICY_NOT_FOUND),
        (api.get_grant_cycle, ApiErrorId.GRANT_CYCLE_NOT_FOUND),
        (api.get_retrofit_grant, ApiErrorId.GRANT_NOT_FOUND),
        (api.get_contractor, ApiErrorId.CONTRACTOR_NOT_FOUND),
        (api.get_retrofit_project, ApiErrorId.PROJECT_NOT_FOUND),
        (api.get_inspection, ApiErrorId.INSPECTION_NOT_FOUND),
        (api.get_catastrophe_event, ApiErrorId.EVENT_NOT_FOUND),
        (api.get_reinsurance_layer, ApiErrorId.LAYER_NOT_FOUND),
        (api.get_claim, ApiErrorId.CLAIM_NOT_FOUND),
        (api.get_assessment_allocation, ApiErrorId.ALLOCATION_NOT_FOUND),
    ]
    for read_one, expected_error in probes:
        response = read_one(constants.NON_EXISTENT_ID, PROGRAM_ADMIN_HEADERS)
        validate_error(response, expected_error)

    # The same route shape resolves for a real identifier, so each refusal above
    # was about the identifier and not about the collection.
    found = validate_success(api.get_insurer(present["id"], PROGRAM_ADMIN_HEADERS))
    assert found["name"] == "Present Insurance"


def test_02_second_pending_offer_on_the_same_insurer_and_dwelling_is_refused(api):
    """PRD §3.1: "Only one offer per insurer-and-dwelling pair may be `PENDING` at a time; a second attempt collides with `ERR_DUPLICATE_PENDING_OFFER`."

    Design: Corner/errors/offer_and_quote_uniqueness_and_expiry_errors_are_each_triggerable
    """
    ctx = fixtures.setup_pending_offer(api)
    assert ctx["offer"]["status"] == "PENDING"

    response = api.create_mandatory_offer(
        factories.create_mandatory_offer_payload(
            ctx["insurer"]["id"], ctx["policyholder"]["id"], ctx["dwelling"]["id"]
        ),
        make_insurer_headers(ctx["insurer"]["id"]),
    )
    validate_error(response, ApiErrorId.DUPLICATE_PENDING_OFFER)


def test_03_administrative_offer_expiry_before_the_window_passes_is_refused(api):
    """PRD §3.1: "An unanswered offer can be retired administratively, moving `PENDING → EXPIRED`, but only once the clock has passed `expires_at`; attempting it earlier is refused with `ERR_OFFER_STILL_VALID`, and attempting it on an offer that has already been answered is refused with `ERR_OFFER_ALREADY_RESPONDED`."

    Design: Corner/errors/offer_and_quote_uniqueness_and_expiry_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_pending_offer(api)

    response = api.expire_offer(ctx["offer"]["id"], None, PROGRAM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.OFFER_STILL_VALID)


def test_04_answering_an_already_answered_offer_is_refused(api):
    """PRD §2.8: "Rung 16: a `MandatoryOffer` must be `PENDING` to be responded to or administratively expired, otherwise `ERR_OFFER_ALREADY_RESPONDED` (409)."

    Design: Corner/errors/offer_and_quote_uniqueness_and_expiry_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_accepted_offer(api)
    assert ctx["offer"]["status"] == "ACCEPTED"

    response = api.respond_to_offer(
        ctx["offer"]["id"],
        factories.respond_to_offer_payload("DECLINE"),
        make_policyholder_headers(ctx["policyholder"]["id"]),
    )
    validate_error(response, ApiErrorId.OFFER_ALREADY_RESPONDED)


def test_05_answering_after_the_offer_window_has_passed_is_refused(api):
    """PRD §3.1: "The answer stamps `responded_at` with the clock reading, and the answer must arrive while the clock is still at or before `expires_at` — one instant later and the response is refused with `ERR_OFFER_EXPIRED`."

    Design: Corner/errors/offer_and_quote_uniqueness_and_expiry_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_pending_offer(api)
    # The offer was recorded at the epoch, so its sixty-day window closes on
    # 2026-09-30; the clock now stands a day beyond it.
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")

    response = api.respond_to_offer(
        ctx["offer"]["id"],
        factories.respond_to_offer_payload("ACCEPT"),
        make_policyholder_headers(ctx["policyholder"]["id"]),
    )
    validate_error(response, ApiErrorId.OFFER_EXPIRED)


def test_06_second_live_quote_on_the_same_dwelling_is_refused(api):
    """PRD §3.3: "A quote cannot be produced through a `SANCTIONED` or `WITHDRAWN` insurer, the offer named in `accepted_offer_id` must be in `ACCEPTED` with its own `insurer_id` and `dwelling_id` matching the policy's, and at most one policy per dwelling may sit in `ACTIVE` or `QUOTED` — a second live quote on the same structure collides with `ERR_DUPLICATE_ACTIVE_POLICY`."

    Design: Corner/errors/offer_and_quote_uniqueness_and_expiry_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_quoted_policy(api)
    assert ctx["policy"]["lifecycle_status"] == "QUOTED"

    response = api.create_policy(
        factories.create_policy_payload(
            ctx["dwelling"]["id"],
            ctx["insurer"]["id"],
            ctx["offer"]["id"],
            deductible_pct=15,
        ),
        make_insurer_headers(ctx["insurer"]["id"]),
    )
    validate_error(response, ApiErrorId.DUPLICATE_ACTIVE_POLICY)


def test_07_new_offer_through_a_withdrawn_insurer_is_refused(api):
    """PRD §2.8: "Rung 36: the insurer's `status` must be `ACTIVE` to write *new* business through it — recording an offer, quoting and binding — while a `WITHDRAWN` insurer may still renew its in-force book and remains assessable, otherwise `ERR_INSURER_WITHDRAWN` (409)."

    Design: Corner/errors/offer_and_quote_uniqueness_and_expiry_errors_are_each_triggerable
    """
    parties = fixtures.setup_parties(api)
    withdrawn = validate_success(
        api.insurer_compliance_action(
            parties["insurer"]["id"],
            factories.compliance_action_payload("WITHDRAW"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["compliance_status"] == "COMPLIANT"

    response = api.create_mandatory_offer(
        factories.create_mandatory_offer_payload(
            parties["insurer"]["id"],
            parties["policyholder"]["id"],
            parties["dwelling"]["id"],
        ),
        make_insurer_headers(parties["insurer"]["id"]),
    )
    validate_error(response, ApiErrorId.INSURER_WITHDRAWN)


def test_08_project_on_a_merely_approved_grant_is_refused(api):
    """PRD §3.6: "The grant must be in `FUNDS_RESERVED` — work cannot start on money that is only approved, and an attempt against a merely `APPROVED` grant is refused with `ERR_GRANT_FUNDS_NOT_RESERVED`."

    Design: Corner/errors/grant_cycle_pool_and_project_gate_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _cover_on_a_retrofittable_dwelling(api)
    ctx = fixtures.setup_approved_grant(api, ctx=ctx, cycle_overrides=dict(BRACE_AND_BOLT))
    assert ctx["grant"]["status"] == "APPROVED"
    contractor = fixtures.create_contractor(api, certified_scopes=["CRIPPLE_WALL_BRACING"])

    response = api.create_retrofit_project(
        factories.create_retrofit_project_payload(ctx["grant"]["id"], contractor["id"]),
        make_contractor_headers(contractor["id"]),
    )
    validate_error(response, ApiErrorId.GRANT_FUNDS_NOT_RESERVED)


def test_09_reservation_past_the_pool_ceiling_is_refused_after_a_bucket_is_resolved(api):
    """PRD §3.5: "Step three is the hard ceiling, and it is checked **after** a bucket has been resolved, which is exactly why a bucket with room can still fail: if `reserved_cents` plus `disbursed_cents` plus this award exceeds `total_pool_cents`, the reservation is refused with `ERR_GRANT_CYCLE_POOL_EXHAUSTED`."

    Design: Corner/errors/grant_cycle_pool_and_project_gate_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(api, total_pool_cents=400000, **BRACE_AND_BOLT)

    # 240,000 fills the whole of the low-income bucket, whose cap is sixty per
    # cent of a 400,000-cent pool.
    low = fixtures.setup_reserved_grant(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle=cycle,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=240000,
    )
    assert low["grant"]["approved_amount_cents"] == 240000
    assert low["grant"]["funded_from_bucket"] == "TIER_LOW"

    # Three quarters of 200,000 is 150,000, which fits the mid bucket's cap of
    # 160,000 and takes the pool's committed total to 390,000.
    mid = fixtures.setup_reserved_grant(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle=cycle,
        income_tier="TIER_MID",
        project_cost_estimate_cents=200000,
    )
    assert mid["grant"]["approved_amount_cents"] == 150000
    assert mid["cycle"]["reserved_cents"] == 390000
    assert mid["cycle"]["uncommitted_cents"] == 10000

    # A 15,000-cent award overflows the low bucket and falls back to the shared
    # bucket, which has ample room — and only then meets the pool ceiling.
    third = fixtures.setup_approved_grant(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle=cycle,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=15000,
    )
    assert third["grant"]["approved_amount_cents"] == 15000
    current = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))

    response = api.reserve_grant_funds(
        third["grant"]["id"],
        factories.reserve_funds_payload(current["version"]),
        PROGRAM_ADMIN_ALT_HEADERS,
    )
    validate_error(response, ApiErrorId.GRANT_CYCLE_POOL_EXHAUSTED)


def test_10_reservation_out_of_a_closed_funding_cycle_is_refused(api):
    """PRD §2.8: "Rung 21: a `GrantCycle` must be `OPEN` both to accept a new grant application and to have funds reserved from it, otherwise `ERR_GRANT_CYCLE_CLOSED` (409)."

    Design: Corner/errors/grant_cycle_pool_and_project_gate_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _cover_on_a_retrofittable_dwelling(api)
    ctx = fixtures.setup_approved_grant(api, ctx=ctx, cycle_overrides=dict(BRACE_AND_BOLT))
    closed = validate_success(
        api.close_grant_cycle(ctx["cycle"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert closed["status"] == "CLOSED"

    response = api.reserve_grant_funds(
        ctx["grant"]["id"],
        factories.reserve_funds_payload(closed["version"]),
        PROGRAM_ADMIN_ALT_HEADERS,
    )
    validate_error(response, ApiErrorId.GRANT_CYCLE_CLOSED)


def test_11_application_into_a_closed_funding_cycle_is_refused(api):
    """PRD §2.8: "Rung 21: a `GrantCycle` must be `OPEN` both to accept a new grant application and to have funds reserved from it, otherwise `ERR_GRANT_CYCLE_CLOSED` (409)."

    Design: Corner/errors/grant_cycle_pool_and_project_gate_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _cover_on_a_retrofittable_dwelling(api)
    cycle = fixtures.create_grant_cycle(api, **BRACE_AND_BOLT)
    closed = validate_success(
        api.close_grant_cycle(cycle["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert closed["status"] == "CLOSED"

    payload = factories.create_retrofit_grant_payload(ctx["dwelling"]["id"], cycle["id"])
    payload["policy_id"] = ctx["policy"]["id"]
    response = api.create_retrofit_grant(
        payload, make_policyholder_headers(ctx["policyholder"]["id"])
    )
    validate_error(response, ApiErrorId.GRANT_CYCLE_CLOSED)


def test_12_passing_a_visit_outside_the_contractors_certified_scopes_is_refused(api):
    """PRD §3.6: "A passing result additionally requires the project's `scope_code` to appear among the inspecting contractor's `certified_scopes`; work outside a contractor's certified scopes cannot be verified, and the attempt is refused with `ERR_RETROFIT_SCOPE_MISMATCH`."

    Design: Corner/errors/contractor_certification_and_scope_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_scheduled_inspection(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle_overrides=dict(BRACE_AND_BOLT),
        contractor_scopes=["ANCHOR_BOLT_ONLY"],
    )
    assert ctx["project"]["scope_code"] == "CRIPPLE_WALL_BRACING"
    assert ctx["contractor"]["certified_scopes"] == ["ANCHOR_BOLT_ONLY"]
    fixtures.set_clock(api, VISIT_WINDOW_START)

    response = api.record_inspection_result(
        ctx["inspection"]["id"],
        factories.record_result_payload("PASS"),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.RETROFIT_SCOPE_MISMATCH)


def test_13_suspending_a_contractor_that_is_already_suspended_is_refused(api):
    """PRD §2.8: "Rung 41: an administratively requested `certification_status` must be reachable from the current one — `SUSPENDED` only from `CERTIFIED`, and `CERTIFIED` only from `PROBATION` or `SUSPENDED`, with `PROBATION` never settable by this operation because only the failed-inspection cascade sets it — otherwise `ERR_CONTRACTOR_INVALID_CERTIFICATION_TRANSITION` (409)."

    Design: Corner/errors/contractor_certification_and_scope_errors_are_each_triggerable
    """
    contractor = fixtures.create_contractor(api)
    assert contractor["certification_status"] == "CERTIFIED"
    suspended = validate_success(
        api.set_contractor_certification(
            contractor["id"],
            factories.certification_payload("SUSPENDED"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert suspended["certification_status"] == "SUSPENDED"

    # Suspension is reachable from CERTIFIED alone, so a second one has nowhere
    # to come from.
    response = api.set_contractor_certification(
        contractor["id"],
        factories.certification_payload("SUSPENDED"),
        PROGRAM_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.CONTRACTOR_INVALID_CERTIFICATION_TRANSITION)


def test_14_assigning_work_to_a_contractor_whose_certification_has_run_out_is_refused(api):
    """PRD §2.8: "Rung 40: the contractor's `certification_expires_at` must be strictly later than the current logical clock, both when a project is created and when an inspection is booked, otherwise `ERR_CONTRACTOR_CERTIFICATION_EXPIRED` (409)."

    Design: Corner/errors/contractor_certification_and_scope_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_reserved_grant(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle_overrides=dict(BRACE_AND_BOLT),
    )
    contractor = fixtures.create_contractor(
        api,
        certified_scopes=["CRIPPLE_WALL_BRACING"],
        certification_expires_at="2026-08-15T00:00:00Z",
    )
    assert contractor["certification_status"] == "CERTIFIED"
    # The certification lapsed a fortnight before the clock now stands.
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    response = api.create_retrofit_project(
        factories.create_retrofit_project_payload(ctx["grant"]["id"], contractor["id"]),
        make_contractor_headers(contractor["id"]),
    )
    validate_error(response, ApiErrorId.CONTRACTOR_CERTIFICATION_EXPIRED)


def test_15_booking_a_visit_naming_a_contractor_the_project_does_not_have_is_refused(api):
    """PRD §3.6: "The project must be in `AWAITING_INSPECTION`, and the inspection's `contractor_id` is copied from the project rather than taken from the caller; a caller-supplied `contractor_id` that disagrees with the project's is refused with `ERR_INSPECTION_PROJECT_MISMATCH`."

    Design: Corner/errors/inspection_sequencing_and_retrofit_lock_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_project_awaiting_inspection(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle_overrides=dict(BRACE_AND_BOLT),
    )
    assert ctx["project"]["status"] == "AWAITING_INSPECTION"
    someone_else = fixtures.create_contractor(api)

    payload = factories.create_inspection_payload(ctx["project"]["id"])
    payload["contractor_id"] = someone_else["id"]
    response = api.create_inspection(payload, FIELD_INSPECTOR_HEADERS)
    validate_error(response, ApiErrorId.INSPECTION_PROJECT_MISMATCH)


def test_16_reporting_on_a_visit_that_has_not_started_is_refused(api):
    """PRD §3.6: "The inspection must still be `PENDING`, the project must be in `AWAITING_INSPECTION`, and the logical clock must have reached `window_start` — reporting on a visit that has not started is refused with `ERR_INSPECTION_WINDOW_NOT_REACHED`."

    Design: Corner/errors/inspection_sequencing_and_retrofit_lock_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_scheduled_inspection(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle_overrides=dict(BRACE_AND_BOLT),
    )
    assert ctx["inspection"]["result"] == "PENDING"
    # The clock still stands three days before the window opens.

    response = api.record_inspection_result(
        ctx["inspection"]["id"],
        factories.record_result_payload("PASS"),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.INSPECTION_WINDOW_NOT_REACHED)


def test_17_recording_a_second_outcome_on_one_visit_is_refused(api):
    """PRD §2.8: "Rung 24: an `Inspection` must still have `result` equal to `PENDING` for an outcome to be recorded on it, otherwise `ERR_INSPECTION_ALREADY_RECORDED` (409)."

    Design: Corner/errors/inspection_sequencing_and_retrofit_lock_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_scheduled_inspection(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle_overrides=dict(BRACE_AND_BOLT),
    )
    fixtures.set_clock(api, VISIT_WINDOW_START)
    # A partial outcome leaves the project awaiting inspection, so nothing but the
    # inspection's own recorded outcome stands in the way of a second report.
    ctx = fixtures.record_inspection(api, ctx, result="PARTIAL")
    assert ctx["inspection"]["result"] == "PARTIAL"
    assert ctx["project"]["status"] == "AWAITING_INSPECTION"

    response = api.record_inspection_result(
        ctx["inspection"]["id"],
        factories.record_result_payload("PARTIAL"),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.INSPECTION_ALREADY_RECORDED)


def test_18_self_attesting_over_an_inspected_retrofit_is_refused(api):
    """PRD §3.2: "Self-attestation is refused with `ERR_RETROFIT_ALREADY_VERIFIED` once `retrofit_status` has reached `VERIFIED`, because a physical inspection outranks a homeowner's word and can never be overwritten by one."

    Design: Corner/errors/inspection_sequencing_and_retrofit_lock_errors_are_each_triggerable
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_scheduled_inspection(
        api,
        ctx=_cover_on_a_retrofittable_dwelling(api),
        cycle_overrides=dict(BRACE_AND_BOLT),
    )
    fixtures.set_clock(api, VISIT_WINDOW_START)
    ctx = fixtures.record_inspection(api, ctx, result="PASS")
    assert ctx["project"]["status"] == "VERIFIED"
    assert ctx["dwelling"]["retrofit_status"] == "VERIFIED"

    response = api.declare_retrofit(
        ctx["dwelling"]["id"],
        factories.declare_retrofit_payload("ANCHOR_BOLT_ONLY"),
        make_policyholder_headers(ctx["policyholder"]["id"]),
    )
    validate_error(response, ApiErrorId.RETROFIT_ALREADY_VERIFIED)


def test_19_declaring_an_event_that_is_no_longer_monitoring_is_refused(api):
    """PRD §2.8: "Rung 25: an event must be `MONITORING` to be declared, otherwise `ERR_EVENT_INVALID_STATE` (409)."

    Design: Corner/errors/event_and_claim_lifecycle_errors_are_each_triggerable
    """
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    ctx = fixtures.setup_declared_event(api)
    assert ctx["event"]["status"] == "DECLARED"

    response = api.declare_event(ctx["event"]["id"], None, PROGRAM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.EVENT_INVALID_STATE)


def test_20_levying_an_event_whose_capacity_still_holds_is_refused(api):
    """PRD §3.8: "The event must be in `CAPACITY_EXHAUSTED`, or the levy is refused with `ERR_EVENT_CAPACITY_NOT_EXHAUSTED`."

    Design: Corner/errors/event_and_claim_lifecycle_errors_are_each_triggerable
    """
    ctx = fixtures.setup_finally_adjusted_claim(api)
    event = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    # Retention alone absorbed the whole finalised loss, so nothing is uncovered.
    assert event["uncovered_cents"] == 0
    assert event["status"] == "LOSS_AGGREGATION"

    response = api.levy_assessment(event["id"], None, PROGRAM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.EVENT_CAPACITY_NOT_EXHAUSTED)


def test_21_second_notice_of_loss_on_the_same_policy_and_event_is_refused(api):
    """PRD §3.8: "At most one claim per policy-and-event pair may exist in any `adjustment_status` other than `DENIED`, so a second notice on the same pairing collides with `ERR_DUPLICATE_CLAIM`."

    Design: Corner/errors/event_and_claim_lifecycle_errors_are_each_triggerable
    """
    ctx = fixtures.setup_filed_claim(api)
    assert ctx["claim"]["adjustment_status"] == "FNOL_RECEIVED"

    response = api.create_claim(
        factories.create_claim_payload(
            ctx["policy"]["id"], ctx["event"]["id"], ctx["event"]["version"]
        ),
        CLAIM_ADJUSTER_HEADERS,
    )
    validate_error(response, ApiErrorId.DUPLICATE_CLAIM)


def test_22_closing_an_event_that_still_has_a_live_claim_is_refused(api):
    """PRD §2.8: "Rung 30: every claim on an event must have reached a terminal `adjustment_status`, meaning `CLOSED` or `DENIED`, before the event may be closed, otherwise `ERR_EVENT_HAS_OPEN_CLAIMS` (409)."

    Design: Corner/errors/event_and_claim_lifecycle_errors_are_each_triggerable
    """
    # Both covers are bound before the ground moves, since the epicenter county
    # closes to new binding once the event is declared.
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    first = fixtures.setup_bound_policy(api)
    second = fixtures.setup_bound_policy(api)
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    declared = fixtures.setup_declared_event(api)
    first.update(declared)
    second.update(declared)

    first = fixtures.setup_finally_adjusted_claim(api, ctx=first)
    # The first claim moved the event's aggregate, so the second notice has to
    # pin the version the event carries now.
    second["event"] = validate_success(
        api.get_catastrophe_event(declared["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    second = fixtures.setup_provisionally_adjusted_claim(api, ctx=second)
    assert second["claim"]["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    event = validate_success(
        api.get_catastrophe_event(declared["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event["status"] == "LOSS_AGGREGATION"

    response = api.close_event(event["id"], None, PROGRAM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.EVENT_HAS_OPEN_CLAIMS)


def test_23_closing_a_claim_that_has_not_been_paid_in_full_is_refused(api):
    """PRD §3.8: "**Closing** a claim moves `FINAL_ADJUSTED → CLOSED`, is performed by program staff, and requires `payment_status` to be exactly `PAID`; a claim that is still short is refused with `ERR_CLAIM_NOT_FULLY_PAID`."

    Design: Corner/errors/event_and_claim_lifecycle_errors_are_each_triggerable
    """
    ctx = fixtures.setup_finally_adjusted_claim(api)
    assert ctx["claim"]["adjustment_status"] == "FINAL_ADJUSTED"
    assert ctx["claim"]["payment_status"] == "UNPAID"

    response = api.close_claim(ctx["claim"]["id"], None, PROGRAM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.CLAIM_NOT_FULLY_PAID)


def test_24_reopening_a_claim_that_has_been_settled_in_full_is_refused(api):
    """PRD §3.8: "It requires `reopen_count` to be strictly less than two — a claim may be reopened twice and no more — the event to be neither `ASSESSMENT_LEVIED` nor `CLOSED`, since the published allocations may not be disturbed, and the claim's `payment_status` to be `UNPAID` or `PARTIALLY_PAID`, because a fully settled claim is refused outright with `ERR_CLAIM_ALREADY_SETTLED`."

    Design: Corner/errors/event_and_claim_lifecycle_errors_are_each_triggerable
    """
    ctx = fixtures.setup_fully_paid_claim(api)
    assert ctx["claim"]["adjustment_status"] == "FINAL_ADJUSTED"
    assert ctx["claim"]["payment_status"] == "PAID"
    assert ctx["claim"]["reopen_count"] == 0

    response = api.reopen_claim(
        ctx["claim"]["id"], factories.reason_payload(), CLAIM_ADJUSTER_HEADERS
    )
    validate_error(response, ApiErrorId.CLAIM_ALREADY_SETTLED)


def test_25_notice_of_loss_against_a_closed_event_is_refused(api):
    """PRD §2.8: "Rung 26: an event must not be `CLOSED` for any operation that touches its loss aggregate — first notice of loss, finalizing an adjustment, reopening a claim, levying the assessment and closing the event itself — otherwise `ERR_EVENT_CLOSED` (409)."

    Design: Corner/errors/event_and_claim_lifecycle_errors_are_each_triggerable
    """
    # Two covers again, one to carry the claim that is settled and closed and one
    # to bring the late notice of loss.
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    settled = fixtures.setup_bound_policy(api)
    latecomer = fixtures.setup_bound_policy(api)
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    declared = fixtures.setup_declared_event(api)
    settled.update(declared)

    settled = fixtures.setup_closed_claim(api, ctx=settled)
    assert settled["claim"]["adjustment_status"] == "CLOSED"
    closed_event = validate_success(
        api.close_event(declared["event"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert closed_event["status"] == "CLOSED"

    response = api.create_claim(
        factories.create_claim_payload(
            latecomer["policy"]["id"], closed_event["id"], closed_event["version"]
        ),
        CLAIM_ADJUSTER_HEADERS,
    )
    validate_error(response, ApiErrorId.EVENT_CLOSED)


def test_26_levying_a_shortfall_with_no_assessable_carrier_is_refused(api):
    """PRD §3.8: "An insurer is assessable when its `compliance_status` is `COMPLIANT` or `UNDER_REVIEW` and its `market_share_pct` is strictly greater than zero." "If the assessable set is empty the levy is refused with `ERR_NO_ASSESSABLE_INSURERS`."

    Design: Corner/errors/assessment_eligibility_and_lock_errors_are_each_triggerable
    """
    ctx = _event_at_capacity_exhausted(api, market_share_pct=0.0)
    # The only carrier in the programme holds no residential market share at all.
    assert ctx["insurer"]["market_share_pct"] == 0.0
    assert ctx["insurer"]["compliance_status"] == "COMPLIANT"

    response = api.levy_assessment(ctx["event"]["id"], None, PROGRAM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.NO_ASSESSABLE_INSURERS)


def test_27_reopening_a_claim_after_the_allocations_were_published_is_refused(api):
    """PRD §2.8: "Rung 27: an event must not be `ASSESSMENT_LEVIED` for any operation that would move the loss aggregate after the allocations were published — first notice of loss, finalizing an adjustment, reopening a claim and levying again — otherwise `ERR_EVENT_ASSESSMENT_LOCKED` (409)."

    Design: Corner/errors/assessment_eligibility_and_lock_errors_are_each_triggerable
    """
    ctx = _event_at_capacity_exhausted(api, market_share_pct=25.0)
    levied = validate_success(
        api.levy_assessment(ctx["event"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert levied["status"] == "ASSESSMENT_LEVIED"
    assert ctx["claim"]["payment_status"] == "UNPAID"
    assert ctx["claim"]["reopen_count"] == 0

    response = api.reopen_claim(
        ctx["claim"]["id"], factories.reason_payload(), CLAIM_ADJUSTER_HEADERS
    )
    validate_error(response, ApiErrorId.EVENT_ASSESSMENT_LOCKED)


def test_28_notice_of_loss_after_the_allocations_were_published_is_refused(api):
    """PRD §2.8: "Rung 27: an event must not be `ASSESSMENT_LEVIED` for any operation that would move the loss aggregate after the allocations were published — first notice of loss, finalizing an adjustment, reopening a claim and levying again — otherwise `ERR_EVENT_ASSESSMENT_LOCKED` (409)."

    Design: Corner/errors/assessment_eligibility_and_lock_errors_are_each_triggerable
    """
    ctx = _event_at_capacity_exhausted(api, market_share_pct=25.0, spare_cover=True)
    levied = validate_success(
        api.levy_assessment(ctx["event"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert levied["status"] == "ASSESSMENT_LEVIED"

    response = api.create_claim(
        factories.create_claim_payload(
            ctx["spare_policy"]["id"], levied["id"], levied["version"]
        ),
        CLAIM_ADJUSTER_HEADERS,
    )
    validate_error(response, ApiErrorId.EVENT_ASSESSMENT_LOCKED)


def test_29_repeating_a_layer_index_within_one_treaty_year_is_refused(api):
    """PRD §3.7: "Two structural rules keep the tower well-formed: `layer_index` must not repeat within a `treaty_year`, or the row is refused with `ERR_DUPLICATE_LAYER_INDEX`; and any layer whose `layer_index` is greater than one must attach at or above the sum of the preceding index's `attachment_point_cents` and `limit_cents` in the same year, so that towers stack upward without overlapping downward, or the row is refused with `ERR_LAYER_ATTACHMENT_GAP`."

    Design: Corner/errors/reinsurance_tower_shape_errors_are_each_triggerable
    """
    first = fixtures.create_reinsurance_layer(api, treaty_year=2026, layer_index=1)
    assert first["status"] == "ACTIVE"

    response = api.create_reinsurance_layer(
        factories.create_reinsurance_layer_payload(
            treaty_year=2026,
            layer_index=1,
            attachment_point_cents=200000000,
            limit_cents=100000000,
        ),
        PROGRAM_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.DUPLICATE_LAYER_INDEX)


def test_30_a_layer_attaching_below_the_one_beneath_it_is_refused(api):
    """PRD §3.7: "Two structural rules keep the tower well-formed: `layer_index` must not repeat within a `treaty_year`, or the row is refused with `ERR_DUPLICATE_LAYER_INDEX`; and any layer whose `layer_index` is greater than one must attach at or above the sum of the preceding index's `attachment_point_cents` and `limit_cents` in the same year, so that towers stack upward without overlapping downward, or the row is refused with `ERR_LAYER_ATTACHMENT_GAP`."

    Design: Corner/errors/reinsurance_tower_shape_errors_are_each_triggerable
    """
    lower = fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=1,
        attachment_point_cents=100000000,
        limit_cents=400000000,
    )
    # The layer beneath exhausts at 500,000,000 cents.
    assert lower["attachment_point_cents"] + lower["limit_cents"] == 500000000

    response = api.create_reinsurance_layer(
        factories.create_reinsurance_layer_payload(
            treaty_year=2026,
            layer_index=2,
            attachment_point_cents=400000000,
            limit_cents=100000000,
        ),
        PROGRAM_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.LAYER_ATTACHMENT_GAP)
