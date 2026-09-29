"""Disease traceback: contact scope variants, hit responses, closing score and the programme goal."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DEFAULT_SERIAL_START,
    activate_hold,
    api_client,
    apply_device,
    assert_trace_hit,
    dispute_movement,
    make_program_admin_headers,
    make_state_official_headers,
    make_trace_analyst_headers,
    open_trace,
    propose_hold,
    read_animal,
    read_hold_order,
    read_premises,
    read_trace_request,
    respond_hit_payload,
    run_trace,
    set_clock,
    setup_environmental_contact_graph,
    setup_isolated_animal_for_trace,
    setup_two_premises_scenario,
    submit_reconciliation_payload,
    validate_error,
    validate_success,
)

ADMIN = make_program_admin_headers("admin-reg")
OFFICIAL = make_state_official_headers("saho-1")
OPENING_ANALYST = make_trace_analyst_headers("fta-1")
CLOSING_ANALYST = make_trace_analyst_headers("fta-2")


class TestContactScopeVariants:
    def test_direct_contact_selects_strict_interval_and_finds_no_contact(self, api):
        """PRD §3.7: "**Contact** between the index animal's residency and a candidate animal's residency is judged by the variant the pathogen class selects, and the selected variant is recorded on `variant_applied`. A `DIRECT_CONTACT` pathogen selects `STRICT_INTERVAL`: the two residencies must overlap for a strictly positive duration, so animals that stood at the same premises days apart are not contacts. An `ENVIRONMENTAL` pathogen selects `PREMISES_WINDOW`: the index residency is first widened by 14 days before its start and 14 days after its end, and the widened interval must then overlap the candidate residency for a strictly positive duration, so animals that occupied the premises up to a fortnight before the index animal arrived or up to a fortnight after it left do count as contacts."
        PRD §3.7: "Three counters are frozen alongside the hit set. `hit_count` is the number of hits, never including the index animal itself."

        Design: Difficulty/dual_variant_calc/trace_scope_strict_interval_vs_premises_window_diverge
        """
        graph = setup_environmental_contact_graph()
        trace = open_trace(
            graph["index_animal"]["id"],
            pathogen_class="DIRECT_CONTACT",
            direction="BOTH",
            lookback_days=30,
            max_hops=3,
        )
        ran = run_trace(trace["id"])

        assert ran["variant_applied"] == "STRICT_INTERVAL"
        assert ran["hit_count"] == 0, (
            "the candidate left the shared premises three days before the index arrived"
        )
        assert read_animal(graph["contact_animal"]["id"])["trace_status"] == "NORMAL"

    def test_environmental_selects_premises_window_and_widens_to_a_prior_resident(self, api):
        """PRD §3.7: "**Contact** between the index animal's residency and a candidate animal's residency is judged by the variant the pathogen class selects, and the selected variant is recorded on `variant_applied`. A `DIRECT_CONTACT` pathogen selects `STRICT_INTERVAL`: the two residencies must overlap for a strictly positive duration, so animals that stood at the same premises days apart are not contacts. An `ENVIRONMENTAL` pathogen selects `PREMISES_WINDOW`: the index residency is first widened by 14 days before its start and 14 days after its end, and the widened interval must then overlap the candidate residency for a strictly positive duration, so animals that occupied the premises up to a fortnight before the index animal arrived or up to a fortnight after it left do count as contacts."
        PRD §3.7: "Each new candidate is appended to `hits` as an object carrying its `animal_id`, the `premises_id` of the residency it was found at, the `hop_depth` at which it was found, a `first_contact_at` equal to the later of the two residency start instants, and `responded` and `resolved` flags both starting false; the candidate then joins the next frontier."
        PRD §3.7: "Every animal that appears in the frozen hit set transitions `trace_status` from `NORMAL` to `TRACE_HIT`, which is what grants the widened read access described in Section 2.7 to federal analysts and to state officials even where the owning producer is `RESTRICTED`."

        Design: Difficulty/dual_variant_calc/trace_scope_strict_interval_vs_premises_window_diverge
        """
        graph = setup_environmental_contact_graph()
        trace = open_trace(
            graph["index_animal"]["id"],
            pathogen_class="ENVIRONMENTAL",
            direction="BOTH",
            lookback_days=30,
            max_hops=3,
        )
        ran = run_trace(trace["id"])

        assert ran["variant_applied"] == "PREMISES_WINDOW"
        assert ran["hit_count"] == 1
        hit = ran["hits"][0]
        assert_trace_hit(hit)
        assert hit["animal_id"] == graph["contact_animal"]["id"]
        assert hit["premises_id"] == graph["p2"]["id"]
        assert hit["hop_depth"] == 1
        assert hit["responded"] is False
        assert hit["resolved"] is False

        assert read_animal(graph["contact_animal"]["id"])["trace_status"] == "TRACE_HIT"


class TestCompletenessScoring:
    def test_completeness_combines_response_resolution_reach_and_dispute_penalty(self, api):
        """PRD §3.7: "Otherwise three ratios are formed over the frozen hits as they stand at close: the responded ratio is the number of hits whose `responded` is true divided by `hit_count`; the resolved ratio is the number of hits whose `resolved` is true divided by `hit_count`; and the reach ratio is 1.0 less the smaller of 1.0 and `hops_unreachable` divided by the greater of 1 and `hops_total`. The raw score weights them at 40.0 for the responded ratio, 35.0 for the resolved ratio and 25.0 for the reach ratio, each of the first two ratios first capped at 1.0."
        PRD §3.7: "A further 5.0 is deducted for each traversed movement event whose `status` at close is `DISPUTED`, with that dispute penalty capped at 15.0 in total — note that a voided hop lowers the reach ratio without contributing to this dispute penalty, because `hops_unreachable` counts both disputed and voided hops while the penalty counts only disputed ones."
        PRD §3.7: "Closing moves the request `RUNNING → COMPLETED`, stamps `closed_at` and `closed_by_user_id`, and recomputes `hops_unreachable` as the number of traversed movement events whose `status` at close is either `DISPUTED` or `VOIDED`."

        Design: Difficulty/combinatorial_formula/completeness_score_weighted_with_reach_ratio_and_dispute_penalty
        """
        closed, _graph = _closed_environmental_trace()

        assert closed["hit_count"] == 1
        assert closed["hops_unreachable"] == 1
        # 40 * 1.0 + 35 * 1.0 + 25 * (1 - 1/2) = 87.5, less the single 5.0 dispute penalty
        assert closed["completeness_score"] == 82.50

    def test_trace_goal_is_met_when_elapsed_and_completeness_clear_their_targets(self, api):
        """PRD §3.7: "Finally the programme goal is evaluated. The request's `elapsed_hours` is the interval from `opened_at` to `closed_at` in seconds, divided by 3600, rounded half up to two decimal places. `trace_goal_met` is true only when `elapsed_hours` is at most 48.00 **and** `completeness_score` is at least 80.00; both boundaries are inclusive, so exactly 48.00 hours and exactly 80.00 points still meet the goal."
        PRD §3.7: "Closing is available only from `RUNNING` and is the second segregation-of-duties decision: the closing analyst's `X-User-ID` must differ from the stored `opened_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/combinatorial_formula/completeness_score_weighted_with_reach_ratio_and_dispute_penalty
        """
        closed, _graph = _closed_environmental_trace()

        assert closed["elapsed_hours"] == 24.00
        assert closed["trace_goal_met"] is True
        assert closed["status"] == "COMPLETED"
        assert closed["closed_by_user_id"] == "fta-2"


class TestEmptyHitSetAndGoalBoundary:
    def test_empty_hit_set_short_circuits_completeness_to_one_hundred(self, api):
        """PRD §3.7: "The **completeness score** is then computed. An empty hit set short-circuits the whole formula: when `hit_count` is 0 the `completeness_score` is exactly 100.00, on the principle that a traceback with nothing to trace is fully traced."

        Design: Difficulty/boundary_precision_check/trace_goal_exactly_48_hours_with_empty_hit_set
        """
        scenario = setup_isolated_animal_for_trace()
        trace = open_trace(
            scenario["animal"]["id"],
            pathogen_class="DIRECT_CONTACT",
            direction="BOTH",
            lookback_days=30,
            max_hops=3,
        )
        ran = run_trace(trace["id"])
        assert ran["hit_count"] == 0
        assert ran["hops_total"] == 0

        set_clock("2026-08-14T00:00:00Z")
        closed = validate_success(api.close_trace_request(trace["id"], CLOSING_ANALYST))
        assert closed["completeness_score"] == 100.00

    def test_elapsed_of_exactly_forty_eight_hours_still_meets_the_goal(self, api):
        """PRD §3.7: "Finally the programme goal is evaluated. The request's `elapsed_hours` is the interval from `opened_at` to `closed_at` in seconds, divided by 3600, rounded half up to two decimal places. `trace_goal_met` is true only when `elapsed_hours` is at most 48.00 **and** `completeness_score` is at least 80.00; both boundaries are inclusive, so exactly 48.00 hours and exactly 80.00 points still meet the goal."
        PRD §3.7: "`premises_touched_count` is the number of distinct premises across the hits taken together with the premises the index animal itself occupied."

        Design: Difficulty/boundary_precision_check/trace_goal_exactly_48_hours_with_empty_hit_set
        """
        scenario = setup_isolated_animal_for_trace()
        trace = open_trace(
            scenario["animal"]["id"],
            pathogen_class="DIRECT_CONTACT",
            direction="BOTH",
            lookback_days=30,
            max_hops=3,
        )
        run_trace(trace["id"])

        set_clock("2026-08-14T00:00:00Z")
        closed = validate_success(api.close_trace_request(trace["id"], CLOSING_ANALYST))
        assert closed["elapsed_hours"] == 48.00
        assert closed["trace_goal_met"] is True
        assert closed["premises_touched_count"] == 1


class TestTraceHoldInteraction:
    def test_hold_release_is_refused_while_its_trace_is_still_running(self, api):
        """PRD §3.6: "When the hold names a trace request, that trace must not still be `RUNNING`, else the release is refused with `ERR_TRACE_STILL_OPEN`."
        PRD §2.5: "A hold cannot be released, and a trace cannot be cancelled, while the linked trace request is `RUNNING`, else `ERR_TRACE_STILL_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/hold_release_blocked_by_running_trace_request
        """
        hold, _trace, _scenario = _active_hold_under_running_trace()
        resp = api.release_hold_order(hold["id"], OFFICIAL)
        validate_error(resp, ApiErrorId.ERR_TRACE_STILL_OPEN, expected_status=409)

    def test_blocked_release_leaves_the_hold_and_quarantine_exactly_in_place(self, api):
        """PRD §3.6: "When the hold names a trace request, that trace must not still be `RUNNING`, else the release is refused with `ERR_TRACE_STILL_OPEN`."
        PRD §3.6: "Release stamps `released_at` from the logical clock, lowers the premises' `pending_hold_count` by one, moves the premises' `health_status` from `QUARANTINED` back to `CLEAR` — but only when no other hold on that premises remains in `ACTIVE` or `UNDER_APPEAL` — and stamps `last_hold_released_at`, arming the 72-hour cooldown for the next proposal."

        Design: Difficulty/cross_entity_state_dependency/hold_release_blocked_by_running_trace_request
        """
        hold, _trace, scenario = _active_hold_under_running_trace()
        resp = api.release_hold_order(hold["id"], OFFICIAL)
        validate_error(resp, ApiErrorId.ERR_TRACE_STILL_OPEN, expected_status=409)

        after_hold = read_hold_order(hold["id"])
        assert after_hold["status"] == "ACTIVE"
        assert after_hold["released_at"] is None

        premises = read_premises(scenario["premises"]["id"])
        assert premises["health_status"] == "QUARANTINED"
        assert premises["last_hold_released_at"] is None

    def test_trace_close_is_refused_while_a_linked_hold_is_still_proposed(self, api):
        """PRD §3.7: "A trace may not be closed while any hold order naming it is still `PROPOSED` or `UNDER_APPEAL`, else `ERR_HOLD_PENDING`."
        PRD §2.5: "A trace cannot be closed while a hold order linked to it sits in `PROPOSED` or `UNDER_APPEAL`, else `ERR_HOLD_PENDING`."

        Design: Corner/validations/trace_close_blocked_while_linked_hold_is_proposed
        """
        scenario = setup_isolated_animal_for_trace()
        trace = open_trace(
            scenario["animal"]["id"],
            pathogen_class="DIRECT_CONTACT",
            direction="BOTH",
            lookback_days=30,
            max_hops=2,
        )
        run_trace(trace["id"])
        hold = propose_hold(
            scenario["premises"]["id"],
            effective_from="2026-08-12T00:00:00Z",
            effective_until="2026-08-30T00:00:00Z",
            trace_request_id=trace["id"],
        )
        assert hold["status"] == "PROPOSED"

        resp = api.close_trace_request(trace["id"], CLOSING_ANALYST)
        validate_error(resp, ApiErrorId.ERR_HOLD_PENDING, expected_status=409)

        after = read_trace_request(trace["id"])
        assert after["status"] == "RUNNING"
        assert after["closed_at"] is None
        assert read_hold_order(hold["id"])["status"] == "PROPOSED"


class TestTraceCancellationAndHitResolution:
    def test_cancelling_a_submitted_trace_never_scores_it(self, api):
        """PRD §3.7: "Abandoning a traceback is also available. Cancellation moves the request to the terminal `CANCELLED` state and is permitted from `SUBMITTED` or from `RUNNING`, but a trace cancelled out of `RUNNING` may not be cancelled while a hold order naming it is `ACTIVE` or `UNDER_APPEAL`, else `ERR_TRACE_STILL_OPEN`; cancelling out of `SUBMITTED` carries no such hold precondition. A `CANCELLED` request computes no hits, and its `completeness_score` and `trace_goal_met` remain null; animals already flagged keep `trace_status` `TRACE_HIT`, because cancellation does not clear them."
        PRD §3.7: "Its `hits` array starts empty, its `hit_count`, `premises_touched_count`, `hops_total` and `hops_unreachable` start at 0, and its `variant_applied`, `closed_at`, `closed_by_user_id`, `elapsed_hours`, `completeness_score` and `trace_goal_met` all start null."

        Design: Corner/state_machines/trace_cancelled_from_submitted_never_scores
        """
        scenario = setup_isolated_animal_for_trace()
        trace = open_trace(
            scenario["animal"]["id"],
            pathogen_class="DIRECT_CONTACT",
            direction="BACKWARD",
            lookback_days=10,
            max_hops=1,
        )
        assert trace["status"] == "SUBMITTED"

        cancelled = validate_success(api.cancel_trace_request(trace["id"], OPENING_ANALYST))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["hit_count"] == 0
        assert cancelled["hits"] == []
        assert cancelled["completeness_score"] is None
        assert cancelled["trace_goal_met"] is None
        assert cancelled["closed_at"] is None

        assert read_animal(scenario["animal"]["id"])["trace_status"] == "NORMAL"

    def test_unknown_hit_animal_and_unknown_run_answer_their_own_not_found(self, api):
        """PRD §2.10: "For `POST /trace-requests/{id}/hits/{animalId}/respond`, the `{id}` segment is resolved to a trace request first — an unknown trace request yields `ERR_TRACE_REQUEST_NOT_FOUND` before the server ever looks at `animalId`. Only once the trace request exists is `animalId` checked, and because the response is recorded against a frozen hit row rather than against the animal table, an animal that exists but is not in that request's hit set yields `ERR_TRACE_HIT_NOT_FOUND`."
        PRD §2.5: "Every resource named by a path segment resolves, validated strictly left to right — for a trace-hit response path, the trace request is resolved before the hit animal. The first unresolved segment decides the error, drawn from `ERR_PRODUCER_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_TAG_LOT_NOT_FOUND`, `ERR_TAG_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_SIGHTING_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_TRACE_REQUEST_NOT_FOUND`, `ERR_HOLD_ORDER_NOT_FOUND`, `ERR_RECONCILIATION_RUN_NOT_FOUND`, or `ERR_AWARD_NOT_FOUND`."

        Design: Corner/validations/unknown_trace_hit_and_unknown_run_return_their_own_not_found_errors
        """
        scenario = setup_two_premises_scenario(
            origin_type="COW_CALF", destination_type="COW_CALF", capacity=10, quantity=10
        )
        stranger = apply_device(
            scenario["lot"]["id"],
            scenario["producer"]["id"],
            DEFAULT_SERIAL_START + 1,
            scenario["destination"]["id"],
            birth_date="2026-05-06",
        )

        trace = open_trace(
            scenario["animal"]["id"],
            pathogen_class="DIRECT_CONTACT",
            direction="BOTH",
            lookback_days=30,
            max_hops=2,
        )
        ran = run_trace(trace["id"])
        assert ran["hit_count"] == 0

        missing_hit = api.respond_trace_hit(
            trace["id"], stranger["id"], respond_hit_payload(True), OFFICIAL
        )
        validate_error(missing_hit, ApiErrorId.ERR_TRACE_HIT_NOT_FOUND, expected_status=404)

        missing_run = api.submit_reconciliation_run(
            NON_EXISTENT_UUID, submit_reconciliation_payload(5), scenario["producer_headers"]
        )
        validate_error(
            missing_run, ApiErrorId.ERR_RECONCILIATION_RUN_NOT_FOUND, expected_status=404
        )

        after = read_trace_request(trace["id"])
        assert after["status"] == "RUNNING"
        assert after["hits"] == []


def _closed_environmental_trace():
    """Run the environmental traceback, work its single hit, dispute the index
    animal's arrival hop, and close the request a day later with a second analyst."""
    graph = setup_environmental_contact_graph()
    trace = open_trace(
        graph["index_animal"]["id"],
        pathogen_class="ENVIRONMENTAL",
        direction="BOTH",
        lookback_days=30,
        max_hops=3,
    )
    ran = run_trace(trace["id"])
    assert ran["hops_total"] == 2, "both movements produced a traversed observation"

    responded = validate_success(
        api_client.respond_trace_hit(
            trace["id"], graph["contact_animal"]["id"], respond_hit_payload(True), OFFICIAL
        )
    )
    assert responded["hits"][0]["responded"] is True
    assert responded["hits"][0]["resolved"] is True

    dispute_movement(graph["index_move"]["id"], reason="origin herd records inconsistent")

    set_clock("2026-08-13T00:00:00Z")
    closed = validate_success(api_client.close_trace_request(trace["id"], CLOSING_ANALYST))
    return closed, graph


def _active_hold_under_running_trace():
    """One animal at an ACTIVE premises with a RUNNING trace and an ACTIVE hold
    issued under that trace."""
    scenario = setup_isolated_animal_for_trace()
    trace = open_trace(
        scenario["animal"]["id"],
        pathogen_class="DIRECT_CONTACT",
        direction="BOTH",
        lookback_days=30,
        max_hops=2,
    )
    run_trace(trace["id"])
    hold = propose_hold(
        scenario["premises"]["id"],
        effective_from="2026-08-12T00:00:00Z",
        effective_until="2026-08-30T00:00:00Z",
        trace_request_id=trace["id"],
    )
    activated = activate_hold(hold["id"])
    return activated, trace, scenario
