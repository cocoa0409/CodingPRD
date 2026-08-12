"""Storm event lifecycle: verification quorum, challenge cycle, void, close-sweep."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_observation_payload, create_event_invoice_payload,
    setup_client, setup_site, setup_contract, link_site, activate_contract,
    setup_active_per_push, setup_storm_event, schedule_visit, set_clock,
    post_observation, verify_event, verify_event_with_two_sources,
    setup_completed_visit, setup_billable_visit, setup_event_invoice,
    setup_issued_event_invoice, make_client_headers,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_region_client_with_site():
    """Client with an ACTIVE PER_PUSH contract on a NE-region site."""
    return setup_active_per_push(client_name="Storm Lifecycle Co",
                                 trigger_depth_inches=2.0,
                                 require_photo_verification=False)


def test_challenge_from_reported_rejected(api):
    """PRD §3.3: "A successful challenge moves the event from `VERIFIED` to `CHALLENGED`" — a never-verified REPORTED event has no challenge transition.
    PRD §2.8: "Fifth, state legality: the target resource's state machine must allow the requested transition, failing as `ERR_INVALID_STATE`"

    Design: Corner/state_machines/storm_event_invalid_from_rejection
    """
    ctx = _setup_region_client_with_site()
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    validate_error(
        api.challenge_storm_event(event["id"], {"reason": "too early"},
                                  make_client_headers(ctx["client"]["id"])),
        ApiErrorId.ERR_INVALID_STATE)


def test_close_sweep_from_reported_rejected(api):
    """PRD §3.3: "Sweeping a `VERIFIED` event stamps `closed_at`, moves it to `CLOSED`" — a REPORTED event has no close-sweep transition.
    PRD §2.8: "Fifth, state legality: the target resource's state machine must allow the requested transition, failing as `ERR_INVALID_STATE`"

    Design: Corner/state_machines/storm_event_invalid_from_rejection
    """
    _setup_region_client_with_site()
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    validate_error(api.close_sweep_storm_event(event["id"], DISPATCH),
                   ApiErrorId.ERR_INVALID_STATE)


def test_verification_quorum_distinct_sources_boundary(api):
    """PRD §3.3: "Verifying a `REPORTED` event requires at least two distinct `source_name` values among the observations eligible inside that window, failing as `ERR_VERIFICATION_QUORUM`."
    PRD §3.3: "`verified_accumulation_inches` is set to the accumulation of the eligible observation with the latest `observed_at`, with ties broken in favor of the most recently created observation"

    Design: Corner/calculations/verification_quorum_distinct_sources_boundary
    """
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=2.5)
    post_observation(event["id"], "NOAA", "2026-12-10T07:00:00Z", 2.5)
    post_observation(event["id"], "NOAA", "2026-12-10T07:30:00Z", 2.6)

    validate_error(api.verify_storm_event(event["id"], DISPATCH),
                   ApiErrorId.ERR_VERIFICATION_QUORUM)

    post_observation(event["id"], "DTN", "2026-12-10T08:00:00Z", 2.55)
    verified = validate_success(api.verify_storm_event(event["id"], DISPATCH), 200)
    assert verified["status"] == "VERIFIED"
    assert verified["verified_accumulation_inches"] == 2.55, (
        "DTN at 08:00 is the eligible observation with the latest observed_at")


def test_observation_out_of_window_rejected_and_late_observation_inert(api):
    """PRD §3.3: "The reading must fall inside the closed eligibility window — from `window_start` through six hours after `window_end`, both ends inclusive — or it is rejected with `ERR_OBSERVATION_OUT_OF_WINDOW`."
    PRD §3.3: "a `CHALLENGED` event returns to `VERIFIED` once the quorum is met again" — while the event stays VERIFIED, no recomputation is triggered by late feed rows.

    Design: Corner/calculations/observation_out_of_window_rejected_and_late_observation_inert
    """
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=2.0)
    verified = verify_event_with_two_sources(event["id"], [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])
    assert verified["verified_accumulation_inches"] == 2.1

    set_clock("2026-12-11T09:00:00Z")
    # 20:00 is past window_end 08:00 + 6h grace = 14:00 -> rejected outright.
    validate_error(
        api.create_observation(
            create_observation_payload(event["id"], "NOAA",
                                       "2026-12-10T20:00:00Z", 9.9),
            ADMIN),
        ApiErrorId.ERR_OBSERVATION_OUT_OF_WINDOW)

    # In-window late arrival is accepted (append-only feed) but inert while VERIFIED.
    get_success_data(api.create_observation(
        create_observation_payload(event["id"], "ON_SITE_SENSOR",
                                   "2026-12-10T08:30:00Z", 0.5),
        ADMIN))
    after = validate_success(api.get_storm_event(event["id"], DISPATCH), 200)
    assert after["status"] == "VERIFIED"
    assert after["verified_accumulation_inches"] == 2.1


def test_storm_event_void_cascades_to_visits_and_draft_invoice(api):
    """PRD §3.3: "when allowed, its `BILLABLE_CONFIRMED` visits become `NON_BILLABLE`, `DRAFT` invoices referencing the event become `VOIDED`, and contract accumulators recompute."

    Design: Corner/state_machines/storm_event_void_cascades_to_visits_and_draft_invoice
    """
    ctx = setup_active_per_push(client_name="Void Co", trigger_depth_inches=1.0)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit, _ = setup_billable_visit(ctx, event, [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])
    assert visit["billing_status"] == "BILLABLE_CONFIRMED"
    invoice = setup_event_invoice(ctx, event)
    assert invoice["status"] == "DRAFT"

    voided = validate_success(api.void_storm_event(event["id"], ADMIN), 200)
    assert voided["status"] == "VOIDED"

    invoice_after = validate_success(api.get_invoice(invoice["id"], DISPATCH), 200)
    assert invoice_after["status"] == "VOIDED"

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "NON_BILLABLE"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 0


def test_storm_event_void_locked_by_issued_invoice(api):
    """PRD §3.3: "Voiding a `VERIFIED` event additionally requires that no `ISSUED`-or-later invoice references it, failing as `ERR_EVENT_LOCKED_BY_INVOICE`"

    Design: Corner/state_machines/storm_event_void_locked_by_issued_invoice
    """
    ctx = setup_active_per_push(client_name="Locked Co", trigger_depth_inches=1.0)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    setup_billable_visit(ctx, event, [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])
    invoice = setup_issued_event_invoice(ctx, event)
    assert invoice["status"] == "ISSUED"

    validate_error(api.void_storm_event(event["id"], ADMIN),
                   ApiErrorId.ERR_EVENT_LOCKED_BY_INVOICE)

    event_after = validate_success(api.get_storm_event(event["id"], DISPATCH), 200)
    assert event_after["status"] == "VERIFIED"


def test_close_sweep_marks_missed_and_closes_event(api):
    """PRD §3.3: "Sweeping a `VERIFIED` event stamps `closed_at`, moves it to `CLOSED`, and marks every visit still `SCHEDULED` or `AWAITING_BACKUP` whose `sla_deadline_at` has already passed as `MISSED` — each such visit gets `sla_miss` set true, its billing forced to `NON_BILLABLE`, and one added to its contract's `season_sla_miss_count`."
    PRD §3.3: "The sweep response reports `visits_marked_missed` and `contracts_expired`."

    Design: Corner/state_machines/close_sweep_marks_missed_and_closes_event
    """
    ctx = setup_active_per_push(client_name="Sweep Co", trigger_depth_inches=1.0)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])
    verify_event_with_two_sources(event["id"], [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])
    # Deadline was window_end 08:00 + 360 min = 14:00; move past it.
    set_clock("2026-12-10T15:00:00Z")

    sweep = validate_success(api.close_sweep_storm_event(event["id"], DISPATCH), 200)
    assert sweep["visits_marked_missed"] == 1

    event_after = validate_success(api.get_storm_event(event["id"], DISPATCH), 200)
    assert event_after["status"] == "CLOSED"

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["execution_status"] == "MISSED"
    assert visit_after["sla_miss"] is True
    assert visit_after["billing_status"] == "NON_BILLABLE"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_sla_miss_count"] == 1


def test_challenge_after_48h_window_returns_expired(api):
    """PRD §3.3: "the logical clock must be no later than forty-eight hours after `verified_at`, inclusive, failing as `ERR_CHALLENGE_WINDOW_EXPIRED`"

    Design: Corner/validations/challenge_after_48h_window_returns_expired
    """
    ctx = _setup_region_client_with_site()
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    post_observation(event["id"], "NOAA", "2026-12-10T07:30:00Z", 2.0)
    post_observation(event["id"], "DTN", "2026-12-10T08:00:00Z", 2.1)
    set_clock("2026-12-10T12:00:00Z")
    verify_event(event["id"])

    # verified_at 2026-12-10T12:00 + 48h = 2026-12-12T12:00; 13:00 is one hour past.
    set_clock("2026-12-12T13:00:00Z")
    validate_error(
        api.challenge_storm_event(event["id"], {"reason": "late dispute"},
                                  make_client_headers(ctx["client"]["id"])),
        ApiErrorId.ERR_CHALLENGE_WINDOW_EXPIRED)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / storm_event_challenge_reverify_cycle
# ---------------------------------------------------------------------------

def _setup_challenge_cycle_scenario(api):
    """PER_PUSH contract (trigger 2.0); one COMPLETED visit on an event that
    first verifies at 2.55, then gets challenged by the owning client."""
    ctx = setup_active_per_push(client_name="Lakeside Campus",
                                trigger_depth_inches=2.0,
                                per_push_rate_cents=45_000,
                                require_photo_verification=False,
                                pavement_area_sqft=60_000)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=2.6)
    visit = setup_completed_visit(ctx, event)
    post_observation(event["id"], "NOAA", "2026-12-10T07:30:00Z", 2.6)
    post_observation(event["id"], "DTN", "2026-12-10T08:00:00Z", 2.55)
    set_clock("2026-12-10T12:00:00Z")
    verified = verify_event(event["id"])
    return ctx, event, visit, verified


def test_challenge_reverify_first_verification_and_challenge_flip(api):
    """PRD §3.3: "`verified_accumulation_inches` is set to the accumulation of the eligible observation with the latest `observed_at`, with ties broken in favor of the most recently created observation"
    PRD §3.3: "A successful challenge moves the event from `VERIFIED` to `CHALLENGED`, records `challenged_at`, `challenged_by_client_id`, and `challenge_reason`, and reverts every visit in `BILLABLE_CONFIRMED` under the event back to `PENDING`"

    Design: Difficulty/non_linear_state_machine/storm_event_challenge_reverify_cycle
    """
    ctx, event, visit, verified = _setup_challenge_cycle_scenario(api)
    assert verified["verified_accumulation_inches"] == 2.55, (
        "latest observed_at wins: DTN 08:00 (2.55) over NOAA 07:30 (2.6)")

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "BILLABLE_CONFIRMED"

    set_clock("2026-12-11T09:00:00Z")
    challenged = validate_success(
        api.challenge_storm_event(
            event["id"],
            {"reason": "On-site sensor shows materially less accumulation"},
            make_client_headers(ctx["client"]["id"])), 200)
    assert challenged["status"] == "CHALLENGED"

    visit_pending = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_pending["billing_status"] == "PENDING"


def test_challenge_reverify_without_fresh_evidence_rejected(api):
    """PRD §3.3: "a `CHALLENGED` event returns to `VERIFIED` once the quorum is met again and at least one eligible observation was created strictly later than `challenged_at` — without such fresh evidence the attempt fails as `ERR_NO_NEW_EVIDENCE`."

    Design: Difficulty/non_linear_state_machine/storm_event_challenge_reverify_cycle
    """
    ctx, event, visit, _ = _setup_challenge_cycle_scenario(api)
    set_clock("2026-12-11T09:00:00Z")
    get_success_data(api.challenge_storm_event(
        event["id"], {"reason": "On-site sensor shows materially less accumulation"},
        make_client_headers(ctx["client"]["id"])))

    # No observation has been created after challenged_at -> re-verify refused.
    validate_error(api.verify_storm_event(event["id"], DISPATCH),
                   ApiErrorId.ERR_NO_NEW_EVIDENCE)


def test_challenge_reverify_with_fresh_evidence_drops_visit_to_non_billable(api):
    """PRD §3.3: "A successful re-verification runs the same three-level cascade using the recomputed latest-observation value, which can carry a visit from `NON_BILLABLE` back to `BILLABLE_CONFIRMED` when the new verified accumulation meets the trigger."
    PRD §3.7: "When the trigger is not met, or execution ends anywhere other than `COMPLETED`, the visit falls to `NON_BILLABLE`."
    PRD §3.7: "`season_billable_push_count` counts the contract's visits with billing in `BILLABLE_CONFIRMED`, `INVOICED`, `DISPUTED`, or `SETTLED`"

    Design: Difficulty/non_linear_state_machine/storm_event_challenge_reverify_cycle
    """
    ctx, event, visit, _ = _setup_challenge_cycle_scenario(api)
    set_clock("2026-12-11T09:00:00Z")
    get_success_data(api.challenge_storm_event(
        event["id"], {"reason": "On-site sensor shows materially less accumulation"},
        make_client_headers(ctx["client"]["id"])))

    # Fresh evidence created strictly after challenged_at (clock now 10:00).
    set_clock("2026-12-11T10:00:00Z")
    post_observation(event["id"], "ON_SITE_SENSOR", "2026-12-10T08:30:00Z", 1.5)
    reverified = validate_success(api.verify_storm_event(event["id"], DISPATCH), 200)
    assert reverified["status"] == "VERIFIED"
    assert reverified["verified_accumulation_inches"] == 1.5, (
        "the late ON_SITE_SENSOR reading at 08:30 is now the latest eligible observation")

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "NON_BILLABLE", "1.5 < trigger 2.0"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / verify_cascade_visit_accumulator_overage_flag
# ---------------------------------------------------------------------------

def _setup_overage_cascade_scenario(api):
    """SEASONAL contract (push cap 1, overage rate 40000, trigger 1.0) with two
    COMPLETED on-time visits on one REPORTED event that will verify at 2.9."""
    from test_helpers import setup_active_seasonal
    ctx = setup_active_seasonal(
        client_name="Airport Parking Auth", seasonal_fee_cents=2_000_000,
        seasonal_push_cap=1, seasonal_overage_rate_cents=40_000,
        trigger_depth_inches=1.0, completion_target_minutes=480,
        pavement_area_sqft=80_000)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=3.0)
    v_a = schedule_visit(event["id"], ctx["contract_site"]["id"],
                         scheduled_start="2026-12-10T09:00:00Z",
                         scheduled_end="2026-12-10T10:00:00Z")
    # Second visit starts exactly 90 minutes after the first ends (legal gap).
    v_b = schedule_visit(event["id"], ctx["contract_site"]["id"],
                         scheduled_start="2026-12-10T11:30:00Z",
                         scheduled_end="2026-12-10T12:30:00Z")
    from test_helpers import run_visit
    run_visit(v_a["id"], "2026-12-10T09:05:00Z", "2026-12-10T10:00:00Z")
    run_visit(v_b["id"], "2026-12-10T11:30:00Z", "2026-12-10T12:30:00Z")
    post_observation(event["id"], "NOAA", "2026-12-10T07:00:00Z", 3.0)
    post_observation(event["id"], "DTN", "2026-12-10T07:30:00Z", 2.9)
    return ctx, event, v_a, v_b


def test_verify_cascade_flips_visits_and_recomputes_accumulator(api):
    """PRD §3.3: "At the first level, every completed visit under the event re-evaluates its billing, moving from `PENDING` to `BILLABLE_CONFIRMED` or `NON_BILLABLE` per the trigger rule of §3.7. At the second level, each flipped visit's owning contract recomputes `season_billable_push_count`, `unbilled_billable_cents`, and `season_billable_minutes`."

    Design: Difficulty/transitive_cascade/verify_cascade_visit_accumulator_overage_flag
    """
    ctx, event, v_a, v_b = _setup_overage_cascade_scenario(api)
    verify_event(event["id"])

    for visit in (v_a, v_b):
        after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
        assert after["billing_status"] == "BILLABLE_CONFIRMED"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 2, (
        "L2: the accumulator recompute is caused by the L1 visit flips")


def test_verify_cascade_overage_flag_and_preview_overage(api):
    """PRD §3.3: "At the third level, `SEASONAL` contracts recompute `overage_active`, and `DRAFT` invoices covering the event recompute their `lines`, `subtotal_cents`, and `total_cents`."
    PRD §3.7: "`overage_active` — meaningful only for `SEASONAL` — flips true once `season_billable_push_count` exceeds `seasonal_push_cap`."
    PRD §3.9: "`overage_pushes` is the count minus `seasonal_push_cap`, floored at zero, and `overage_cents` is that many pushes times `seasonal_overage_rate_cents`."

    Design: Difficulty/transitive_cascade/verify_cascade_visit_accumulator_overage_flag
    """
    ctx, event, v_a, v_b = _setup_overage_cascade_scenario(api)
    verify_event(event["id"])

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["overage_active"] is True, "2 billable pushes > cap 1"

    preview = validate_success(
        api.get_true_up_preview(ctx["contract"]["id"], DISPATCH), 200)
    assert preview["projected_overage_pushes"] == 1
    assert preview["projected_overage_cents"] == 40_000
