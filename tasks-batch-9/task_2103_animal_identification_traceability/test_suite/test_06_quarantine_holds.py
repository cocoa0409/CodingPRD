"""Quarantine hold orders: interval rules, the investigation cascade, appeals and release."""
from test_helpers import (
    ApiErrorId,
    activate_hold,
    appeal_hold_payload,
    approve_reconciliation_run,
    assert_same_instant,
    create_active_premises,
    create_hold_order_payload,
    create_movement_payload,
    make_producer_headers,
    make_program_admin_headers,
    make_state_official_headers,
    open_reconciliation_run,
    propose_hold,
    read_animal,
    read_hold_order,
    read_movement,
    read_premises,
    read_premises_version,
    read_producer,
    register_producer,
    release_hold,
    report_departure,
    set_clock,
    setup_lot_scenario,
    setup_premises_under_active_hold,
    setup_two_premises_scenario,
    submit_reconciliation_run,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers("admin-reg")
OFFICIAL = make_state_official_headers("saho-1")


class TestHoldWindowIntervals:
    def test_hold_window_that_only_touches_the_previous_one_is_accepted(self, api):
        """PRD §3.6: "Second, an **overlap rule**: the new half-open window from `effective_from` up to but not including `effective_until` may not intersect the window of any existing hold on the same premises whose `status` is `PROPOSED`, `ACTIVE` or `UNDER_APPEAL`, and an intersection is refused with `ERR_HOLD_WINDOW_OVERLAP`. Windows that merely touch — where the previous hold's `effective_until` equals the new hold's `effective_from` — do not intersect and are permitted."
        PRD §3.6: "Creating it raises the target premises' `pending_hold_count` by one — that counter being the number of hold orders on the premises whose `status` is `PROPOSED`, `ACTIVE` or `UNDER_APPEAL` — and increments the premises' `version` by one, which is precisely why the next writer against that premises needs a fresh version number."

        Design: Difficulty/resource_temporal_overlap/hold_windows_touch_ok_but_intersect_rejected
        """
        producer = register_producer(legal_name="Chinook Cattle", state_code="MT")
        premises = create_active_premises(producer["id"], state_code="MT", capacity=30)

        propose_hold(
            premises["id"],
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-08-02T00:00:00Z",
        )
        touching = propose_hold(
            premises["id"],
            effective_from="2026-08-02T00:00:00Z",
            effective_until="2026-08-03T00:00:00Z",
        )
        assert touching["status"] == "PROPOSED", "a window starting where the last ends is allowed"
        assert read_premises(premises["id"])["pending_hold_count"] == 2

    def test_hold_window_strictly_inside_an_existing_one_is_rejected(self, api):
        """PRD §3.6: "Second, an **overlap rule**: the new half-open window from `effective_from` up to but not including `effective_until` may not intersect the window of any existing hold on the same premises whose `status` is `PROPOSED`, `ACTIVE` or `UNDER_APPEAL`, and an intersection is refused with `ERR_HOLD_WINDOW_OVERLAP`. Windows that merely touch — where the previous hold's `effective_until` equals the new hold's `effective_from` — do not intersect and are permitted."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."

        Design: Difficulty/resource_temporal_overlap/hold_windows_touch_ok_but_intersect_rejected
        """
        producer = register_producer(legal_name="Chinook Cattle", state_code="MT")
        premises = create_active_premises(producer["id"], state_code="MT", capacity=30)
        propose_hold(
            premises["id"],
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-08-02T00:00:00Z",
        )
        propose_hold(
            premises["id"],
            effective_from="2026-08-02T00:00:00Z",
            effective_until="2026-08-03T00:00:00Z",
        )

        payload = create_hold_order_payload(
            premises["id"],
            read_premises_version(premises["id"]),
            effective_from="2026-08-01T12:00:00Z",
            effective_until="2026-08-01T18:00:00Z",
        )
        resp = api.create_hold_order(payload, OFFICIAL)
        validate_error(resp, ApiErrorId.ERR_HOLD_WINDOW_OVERLAP, expected_status=409)

        assert read_premises(premises["id"])["pending_hold_count"] == 2, (
            "the rejected proposal created no hold row"
        )


class TestCooldownBeatsWindowShape:
    def test_cooldown_is_reported_ahead_of_an_inverted_window(self, api):
        """PRD §3.6: "First, a **72-hour cooldown**: a premises that has had a hold released records the release instant in `last_hold_released_at`, and a new hold whose `effective_from` falls earlier than three days after that instant is refused with `ERR_HOLD_COOLDOWN_ACTIVE`."
        PRD §2.5: "Guards `POST /movement-events`, `POST /movement-events/{id}/correct` and `POST /hold-orders`, yielding `ERR_ICVI_REQUIRED`, `ERR_HOLD_COOLDOWN_ACTIVE` or `ERR_HOLD_WINDOW_OVERLAP` as detailed in Sections 3.5 and 3.6."
        PRD §2.5: "Specifically: `effective_until` must be strictly later than `effective_from`, and `period_end` must be the same date as or later than `period_start`, and `arrived_at` must be the same instant as or later than `departed_at` — any of these failing gives `ERR_INVALID_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/safety_hold_cooldown_beats_temporal_inverted_window
        """
        premises = _premises_with_released_hold()

        payload = create_hold_order_payload(
            premises["id"],
            read_premises_version(premises["id"]),
            effective_from="2026-08-02T00:00:00Z",
            effective_until="2026-08-01T12:00:00Z",
        )
        resp = api.create_hold_order(payload, OFFICIAL)
        validate_error(resp, ApiErrorId.ERR_HOLD_COOLDOWN_ACTIVE, expected_status=409)

    def test_release_arms_the_cooldown_anchor_and_the_rejected_proposal_creates_nothing(self, api):
        """PRD §3.6: "Release stamps `released_at` from the logical clock, lowers the premises' `pending_hold_count` by one, moves the premises' `health_status` from `QUARANTINED` back to `CLEAR` — but only when no other hold on that premises remains in `ACTIVE` or `UNDER_APPEAL` — and stamps `last_hold_released_at`, arming the 72-hour cooldown for the next proposal."
        PRD §3.6: "First, a **72-hour cooldown**: a premises that has had a hold released records the release instant in `last_hold_released_at`, and a new hold whose `effective_from` falls earlier than three days after that instant is refused with `ERR_HOLD_COOLDOWN_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_hold_cooldown_beats_temporal_inverted_window
        """
        premises = _premises_with_released_hold()
        anchored = read_premises(premises["id"])
        assert_same_instant(
            anchored["last_hold_released_at"], "2026-08-01T06:00:00Z", "last_hold_released_at"
        )

        payload = create_hold_order_payload(
            premises["id"],
            anchored["version"],
            effective_from="2026-08-02T00:00:00Z",
            effective_until="2026-08-01T12:00:00Z",
        )
        resp = api.create_hold_order(payload, OFFICIAL)
        validate_error(resp, ApiErrorId.ERR_HOLD_COOLDOWN_ACTIVE, expected_status=409)

        assert read_premises(premises["id"])["pending_hold_count"] == 0, (
            "no hold row was created by the rejected proposal"
        )


class TestQuarantineBlocksDepartures:
    def test_departure_from_a_quarantined_origin_is_refused(self, api):
        """PRD §2.5: "A premises involved in applying a tag, departing, receiving, correcting or retiring must not have `health_status` equal to `QUARANTINED`, else `ERR_PREMISES_UNDER_HOLD`."
        PRD §3.5: "The origin premises must be `ACTIVE` in registration and must not be `QUARANTINED`."
        PRD §3.6: "Hop one quarantines the premises: its `health_status` becomes `QUARANTINED`, whether it was previously `CLEAR` or `UNDER_INVESTIGATION`."

        Design: Difficulty/cross_entity_state_dependency/departure_blocked_by_quarantined_origin_premises
        """
        scenario = setup_premises_under_active_hold(capacity=25)
        assert read_premises(scenario["origin"]["id"])["health_status"] == "QUARANTINED"
        set_clock("2026-08-02T00:00:00Z")

        resp = api.create_movement_event(
            create_movement_payload(
                scenario["animal"]["id"],
                scenario["origin"]["id"],
                scenario["destination"]["id"],
                "2026-08-02T00:00:00Z",
            ),
            scenario["producer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PREMISES_UNDER_HOLD, expected_status=409)

    def test_refused_departure_appends_no_observation_and_keeps_the_head_in_place(self, api):
        """PRD §2.5: "A premises involved in applying a tag, departing, receiving, correcting or retiring must not have `health_status` equal to `QUARANTINED`, else `ERR_PREMISES_UNDER_HOLD`."
        PRD §3.5: "A `DEPARTURE` sighting is appended with `observed_at` equal to `departed_at`, which re-projects `current_premises_id` to null; the origin premises' `animal_count` falls by one; and the origin producer's `on_time_movement_pct`, `enrolled_head_count` and `incentive_tier` are all re-derived."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."

        Design: Difficulty/cross_entity_state_dependency/departure_blocked_by_quarantined_origin_premises
        """
        scenario = setup_premises_under_active_hold(capacity=25)
        set_clock("2026-08-02T00:00:00Z")

        resp = api.create_movement_event(
            create_movement_payload(
                scenario["animal"]["id"],
                scenario["origin"]["id"],
                scenario["destination"]["id"],
                "2026-08-02T00:00:00Z",
            ),
            scenario["producer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PREMISES_UNDER_HOLD, expected_status=409)

        animal = read_animal(scenario["animal"]["id"])
        assert animal["lifecycle_status"] == "ACTIVE"
        assert animal["current_premises_id"] == scenario["origin"]["id"]
        assert animal["sighting_count"] == 1, "no DEPARTURE observation was appended"
        assert read_premises(scenario["origin"]["id"])["animal_count"] == 1


class TestInvestigationCascade:
    def test_activation_disputes_outbound_traffic_and_widens_the_investigation(self, api):
        """PRD §3.6: "The hold moves `PROPOSED → ACTIVE` and Cascade C unfolds in three linked hops. Hop one quarantines the premises: its `health_status` becomes `QUARANTINED`, whether it was previously `CLEAR` or `UNDER_INVESTIGATION`. Hop two disputes the outbound traffic: every movement event whose `origin_premises_id` is that premises and whose `status` is `REPORTED` transitions `REPORTED → DISPUTED`. Hop two-b flags the animals: each animal that was the subject of one of those disputed movements transitions `trace_status` from `NORMAL` to `TRACE_HIT`, and it does so independently of its `lifecycle_status`, which remains `IN_TRANSIT`. Hop three widens the investigation: the `destination_premises_id` of each movement disputed by hop two transitions its own `health_status` from `CLEAR` to `UNDER_INVESTIGATION`."

        Design: Corner/state_machines/hold_activation_disputes_outbound_movement_and_investigates_destination
        """
        scenario = setup_two_premises_scenario(
            origin_state="WY", destination_state="WY", capacity=10, quantity=10
        )
        set_clock("2026-08-02T00:00:00Z")
        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-02T00:00:00Z",
        )
        hold = propose_hold(
            scenario["origin"]["id"],
            effective_from="2026-08-02T00:00:00Z",
            effective_until="2026-08-30T00:00:00Z",
        )

        activated = validate_success(api.activate_hold_order(hold["id"], OFFICIAL))
        assert activated["status"] == "ACTIVE"

        assert read_premises(scenario["origin"]["id"])["health_status"] == "QUARANTINED"
        assert read_movement(movement["id"])["status"] == "DISPUTED"

        animal = read_animal(scenario["animal"]["id"])
        assert animal["trace_status"] == "TRACE_HIT"
        assert animal["lifecycle_status"] == "IN_TRANSIT", (
            "the trace dimension advances independently of the lifecycle dimension"
        )

        destination = read_premises(scenario["destination"]["id"])
        assert destination["health_status"] == "UNDER_INVESTIGATION"
        assert destination["registration_status"] == "ACTIVE"


class TestAppealCycle:
    def test_third_appeal_on_the_same_hold_is_refused(self, api):
        """PRD §3.6: "Producers may contest an active hold, and the appeal cycle between `ACTIVE` and `UNDER_APPEAL` is bounded at two appeals. Appealing is available only from `ACTIVE`, may be performed only by the producer that owns the held premises — a different producer receives `ERR_NOT_RESOURCE_OWNER` — and requires `appeal_count` to be strictly below 2, with a third attempt refused as `ERR_APPEAL_LIMIT_EXCEEDED`. The appellant may attach free-text `grounds`. A successful appeal moves the hold `ACTIVE → UNDER_APPEAL` and increments `appeal_count` by one; the premises stays `QUARANTINED` for the duration of the appeal. Denying the appeal, available only from `UNDER_APPEAL`, returns the hold to `ACTIVE` and changes no counter."

        Design: Corner/state_machines/hold_appeal_cycle_rejects_third_appeal
        """
        producer = register_producer(legal_name="Appeal Ranch", state_code="MT")
        producer_headers = make_producer_headers(producer["id"])
        premises = create_active_premises(producer["id"], state_code="MT", capacity=10)
        hold = propose_hold(
            premises["id"],
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-08-30T00:00:00Z",
        )
        activate_hold(hold["id"])

        for expected_count, grounds in ((1, "herd tested negative"), (2, "second submission")):
            appealed = validate_success(
                api.appeal_hold_order(
                    hold["id"], appeal_hold_payload(grounds=grounds), producer_headers
                )
            )
            assert appealed["status"] == "UNDER_APPEAL"
            assert appealed["appeal_count"] == expected_count
            denied = validate_success(api.deny_hold_appeal(hold["id"], OFFICIAL))
            assert denied["status"] == "ACTIVE"

        resp = api.appeal_hold_order(
            hold["id"], appeal_hold_payload(grounds="third submission"), producer_headers
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_EXCEEDED, expected_status=409)

        after = read_hold_order(hold["id"])
        assert after["status"] == "ACTIVE"
        assert after["appeal_count"] == 2
        assert read_premises(premises["id"])["health_status"] == "QUARANTINED"


class TestHoldVersionGuard:
    def test_second_hold_reusing_the_earlier_premises_version_is_rejected(self, api):
        """PRD §2.6: "A `POST /hold-orders` request must likewise carry `expected_premises_version` matching the target premises' current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` and HTTP 412."
        PRD §3.6: "Creating it raises the target premises' `pending_hold_count` by one — that counter being the number of hold orders on the premises whose `status` is `PROPOSED`, `ACTIVE` or `UNDER_APPEAL` — and increments the premises' `version` by one, which is precisely why the next writer against that premises needs a fresh version number."

        Design: Corner/validations/stale_expected_premises_version_on_hold_create_returns_412
        """
        producer = register_producer(legal_name="Occ Co", state_code="MT")
        premises = create_active_premises(producer["id"], state_code="MT", capacity=10)
        observed_version = premises["version"]

        first = validate_success(
            api.create_hold_order(
                create_hold_order_payload(
                    premises["id"],
                    observed_version,
                    effective_from="2026-08-01T00:00:00Z",
                    effective_until="2026-08-02T00:00:00Z",
                ),
                OFFICIAL,
            ),
            expected_status=201,
        )

        stale = api.create_hold_order(
            create_hold_order_payload(
                premises["id"],
                observed_version,
                effective_from="2026-08-10T00:00:00Z",
                effective_until="2026-08-11T00:00:00Z",
            ),
            OFFICIAL,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        assert read_premises(premises["id"])["pending_hold_count"] == 1
        rows, meta = validate_paginated(
            api.list_hold_orders(ADMIN, params={"premises_id": premises["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]


class TestParallelPremisesDimensions:
    def test_activating_a_hold_moves_health_while_registration_stands_still(self, api):
        """PRD §3.6: "Hop one quarantines the premises: its `health_status` becomes `QUARANTINED`, whether it was previously `CLEAR` or `UNDER_INVESTIGATION`."
        PRD §3.1: "A freshly registered premises begins with `registration_status` `PENDING_REVIEW`, `health_status` `CLEAR`, `animal_count` 0, `pending_hold_count` 0, and a null `last_hold_released_at` and `last_reconciliation_run_at`."
        PRD §3.6: "Activation is where the epidemiological cascade fires. Activating is available only from `PROPOSED`, and the target premises must not still be in `registration_status` `PENDING_REVIEW`, else `ERR_PREMISES_NOT_ACTIVE`."

        Design: Difficulty/non_linear_state_machine/premises_registration_and_health_dimensions_advance_independently
        """
        scenario = setup_lot_scenario(
            operation_type="COW_CALF", state_code="NE", capacity=300, quantity=100,
            legal_name="Sandhill Cattle",
        )
        premises_id = scenario["premises"]["id"]

        hold = propose_hold(
            premises_id,
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-08-20T00:00:00Z",
        )
        activate_hold(hold["id"])

        after_activation = read_premises(premises_id)
        assert after_activation["health_status"] == "QUARANTINED"
        assert after_activation["registration_status"] == "ACTIVE", (
            "the registration dimension is untouched by a health-dimension transition"
        )

    def test_variance_suspends_registration_while_release_independently_clears_health(self, api):
        """PRD §3.8: "When `variance_pct` exceeds 0.50 the run moves `SUBMITTED → VARIANCE_FLAGGED` and Cascade D runs in three hops: hop one records `approved_by_user_id` and flags the run; hop two suspends the target premises, moving its `registration_status` from `ACTIVE` to `SUSPENDED`, which blocks tag application, movement reporting and lot issuance there with `ERR_PREMISES_NOT_ACTIVE`; hop three re-derives the owning producer, recomputing `enrolled_head_count` without the suspended premises' contribution and re-deriving `incentive_tier`, and lapsing the producer's `enrollment_status` from `ENROLLED` to `LAPSED` if no `ACTIVE` premises remains."
        PRD §3.6: "Release stamps `released_at` from the logical clock, lowers the premises' `pending_hold_count` by one, moves the premises' `health_status` from `QUARANTINED` back to `CLEAR` — but only when no other hold on that premises remains in `ACTIVE` or `UNDER_APPEAL` — and stamps `last_hold_released_at`, arming the 72-hour cooldown for the next proposal."
        PRD §3.8: "The signed `variance_count` is `physical_unapplied_count` less `book_unapplied_count`. The `variance_pct` is 100.0 multiplied by the absolute value of `variance_count`, divided by the greater of 1 and `book_unapplied_count`, rounded half up to two decimal places."

        Design: Difficulty/non_linear_state_machine/premises_registration_and_health_dimensions_advance_independently
        """
        scenario = setup_lot_scenario(
            operation_type="COW_CALF", state_code="NE", capacity=300, quantity=100,
            legal_name="Sandhill Cattle",
        )
        premises_id = scenario["premises"]["id"]
        producer_id = scenario["producer"]["id"]

        hold = propose_hold(
            premises_id,
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-08-20T00:00:00Z",
        )
        activate_hold(hold["id"])

        run = open_reconciliation_run(premises_id, producer_id, "2026-08-01", "2026-08-31")
        submitted = submit_reconciliation_run(run["id"], producer_id, 99)
        assert submitted["book_unapplied_count"] == 100
        assert submitted["variance_pct"] == 1.00

        flagged = approve_reconciliation_run(run["id"])
        assert flagged["status"] == "VARIANCE_FLAGGED"

        release_hold(hold["id"])

        final = read_premises(premises_id)
        assert final["registration_status"] == "SUSPENDED", (
            "release clears health but never restores a suspended registration"
        )
        assert final["health_status"] == "CLEAR"
        assert final["last_hold_released_at"] is not None
        assert final["pending_hold_count"] == 0
        assert read_producer(producer_id)["enrollment_status"] == "NOT_ENROLLED"


def _premises_with_released_hold() -> dict:
    """An ACTIVE premises whose only hold was activated and then released at
    2026-08-01T06:00:00Z, arming the 72-hour cooldown."""
    producer = register_producer(legal_name="Bitterroot Livestock", state_code="MT")
    premises = create_active_premises(producer["id"], state_code="MT", capacity=40)
    hold = propose_hold(
        premises["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2026-08-02T00:00:00Z",
    )
    activate_hold(hold["id"])
    set_clock("2026-08-01T06:00:00Z")
    release_hold(hold["id"])
    return premises
