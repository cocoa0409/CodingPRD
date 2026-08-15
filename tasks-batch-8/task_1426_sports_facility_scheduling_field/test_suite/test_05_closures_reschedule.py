"""Weather disruption: closure rain-out cascades, the reschedule cycle and its
hard cap, OCC guards, the reschedule horizon, and derived weekly load."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cancel_permit_as_owner,
    create_condition_payload,
    create_facility,
    create_field_closure,
    create_reschedule_payload,
    get_facility,
    get_invoice,
    get_permit,
    get_success_data,
    get_usage_ledger,
    make_org_coordinator_headers,
    rain_out_permit,
    record_condition,
    reschedule_as_owner,
    set_clock,
    setup_awarded_permit,
    setup_confirmed_permit,
    setup_rained_out_permit,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["field_supervisor_headers"]
ADMIN = TEST_USERS["athletics_admin_headers"]


class TestClosureRainoutCascade:
    def test_closure_rainout_credit_and_negative_balance(self, api):
        """PRD §3.7: "Creating an `ACTIVE` closure immediately rains out every permit
        on that facility and date in `RESERVED` or `CONFIRMED` status whose slot
        intersects the closure — any slot at all for a full-day closure, otherwise
        half-open interval overlap per §2.9. Each affected permit moves to
        `RAINED_OUT`. Its invoice is credited with `credit_cents` equal to the sum of
        `field_fee_cents`, `lights_fee_cents`, and `surcharge_cents`; `total_cents`
        recomputes to whatever `adjustment_cents` remains, typically zero; and
        `balance_due_cents` recomputes and may legitimately go negative, representing
        a credit on account — no money moves automatically, and funds return only
        through the cancellation waterfall."

        Quote 9600 (4000 field + 5600 lights + 0 surcharge), 5000 paid: credit 9600,
        total 0, balance -5000.

        Design: Difficulty/transitive_cascade/closure_rainout_credit_ledger_cascade
        """
        ctx = setup_confirmed_permit(app_overrides={"wants_lights": True})
        set_clock("2026-08-10T08:00:00Z")
        closure = rain_out_permit(ctx["facility"]["id"], "2026-08-10")
        assert closure["status"] == "ACTIVE"

        permit = get_permit(ctx["permit"]["id"])
        assert permit["status"] == "RAINED_OUT", "hop 1: the closure rains out the permit"
        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["credit_cents"] == 9600, "hop 2: full quote credited"
        assert invoice["total_cents"] == 0
        assert invoice["balance_due_cents"] == -5000, \
            "credit on account; no automatic refund"

    def test_closure_rainout_releases_ledger_and_weekly_load(self, api):
        """PRD §3.7: "The released hours leave the season ledger, and the facility's
        `weekly_prime_hours_used` is recomputed."
        PRD §2.9: "Separately, the facility's display counter
        `weekly_prime_hours_used` always reflects the prime load of the week
        containing the logical clock's date, and it is recomputed on every permit
        mutation."

        With the clock in the slot's Mon-Sun week: facility weekly load and the org
        ledger both drop 2 -> 0 when the rain-out releases the hours.

        Design: Difficulty/transitive_cascade/closure_rainout_credit_ledger_cascade
        """
        ctx = setup_confirmed_permit(app_overrides={"wants_lights": True})
        set_clock("2026-08-10T08:00:00Z")
        assert get_facility(ctx["facility"]["id"])["weekly_prime_hours_used"] == 2
        ledger_before = get_usage_ledger(ctx["organization"]["id"], "2026-FALL")
        assert ledger_before["awarded_prime_hours"] == 2

        rain_out_permit(ctx["facility"]["id"], "2026-08-10")

        ledger_after = get_usage_ledger(ctx["organization"]["id"], "2026-FALL")
        assert ledger_after["awarded_prime_hours"] == 0, "hop 3a: ledger release"
        assert get_facility(ctx["facility"]["id"])["weekly_prime_hours_used"] == 0, \
            "hop 3b: facility weekly counter recompute"


class TestRainRescheduleCycle:
    def test_first_reschedule_requotes_and_absorbs_payments(self, api):
        """PRD §3.7: "A successful reschedule replaces `permit_date`, `start_minute`,
        and `end_minute` with the new slot; sets `original_permit_id` to the lineage
        root — on the first reschedule the null becomes the permit's own `id`, the
        root of its reschedule lineage, and any later reschedule keeps that same
        root; and increments both `rain_reschedule_count` and `version`. The fees are
        re-quoted: the new provisional lines replace the invoice's field, lights, and
        surcharge lines; `credit_cents` and `adjustment_cents` reset to 0 because the
        rain credit is consumed by the replacement slot; and `total_cents` and
        `balance_due_cents` recompute, so the organization's earlier payments absorb
        into the new charges."

        Identical 2-hour lights slot on 2026-08-12 re-quotes to 9600; the earlier
        5000 payment absorbs: balance 4600.

        Design: Difficulty/non_linear_state_machine/permit_rain_reschedule_cycle_twice_then_limit
        """
        ctx = setup_rained_out_permit(app_overrides={"wants_lights": True})
        assert ctx["permit"]["status"] == "RAINED_OUT"

        res = reschedule_as_owner(ctx["permit"]["id"], ctx["organization"]["id"],
                                  "2026-08-12", 1080, 1200)
        moved = validate_success(res, 200)
        assert moved["status"] == "CONFIRMED"
        assert moved["rain_reschedule_count"] == 1
        assert moved["permit_date"] == "2026-08-12"

        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["credit_cents"] == 0, "rain credit consumed by the replacement slot"
        assert invoice["total_cents"] == 9600
        assert invoice["balance_due_cents"] == 4600, "9600 re-quote minus 5000 paid"

    def test_third_reschedule_hits_hard_cap(self, api):
        """PRD §3.7: "Eight guards protect the move, each with its own rejection: the
        version check fails with `ERR_STALE_VERSION`; a `rain_reschedule_count`
        already at its hard cap of 2 fails with `ERR_RESCHEDULE_LIMIT_REACHED`; a
        `CLOSED` target facility fails with `ERR_FACILITY_CLOSED`; a `new_date` before
        the permit's current `permit_date` or more than ten days after it fails with
        `ERR_RESCHEDULE_HORIZON_EXCEEDED`; a new slot starting at or before the
        logical clock fails with `ERR_SLOT_IN_PAST`; a half-open overlap with another
        `RESERVED` or `CONFIRMED` permit on the same facility and date fails with
        `ERR_SLOT_OVERLAP`; when lights were approved on the permit, a breach of the
        30-minute buffer or the nightly block cap of §2.9 fails with
        `ERR_LIGHTS_BUFFER_OVERLAP`; and a breach of the season prime cap or the
        weekly turf cap fails with `ERR_PRIME_CAP_EXCEEDED` or
        `ERR_TURF_REST_CAP_EXCEEDED` respectively."

        Two full rain/reschedule cycles succeed (count reaches 2); a third closure
        rains the permit out again, and the third reschedule is rejected even though
        RAINED_OUT is a valid from-state.

        Design: Difficulty/non_linear_state_machine/permit_rain_reschedule_cycle_twice_then_limit
        """
        ctx = setup_rained_out_permit(app_overrides={"wants_lights": True})
        permit_id = ctx["permit"]["id"]
        org_id = ctx["organization"]["id"]

        moved = validate_success(reschedule_as_owner(permit_id, org_id,
                                                     "2026-08-12", 1080, 1200), 200)
        assert moved["rain_reschedule_count"] == 1
        assert moved["status"] == "CONFIRMED"

        rain_out_permit(ctx["facility"]["id"], "2026-08-12")
        assert get_permit(permit_id)["status"] == "RAINED_OUT"
        moved = validate_success(reschedule_as_owner(permit_id, org_id,
                                                     "2026-08-14", 1080, 1200), 200)
        assert moved["rain_reschedule_count"] == 2

        rain_out_permit(ctx["facility"]["id"], "2026-08-14")
        rained = get_permit(permit_id)
        assert rained["status"] == "RAINED_OUT"

        res = api.reschedule_permit(
            permit_id,
            create_reschedule_payload("2026-08-17", 1080, 1200, rained["version"]),
            make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_RESCHEDULE_LIMIT_REACHED)
        assert get_permit(permit_id)["status"] == "RAINED_OUT"


class TestRescheduleOcc:
    def test_occ_permit_reschedule_stale_version_rejected(self, api):
        """PRD §2.7: "Rescheduling a rained-out permit requires the request to carry
        `expected_permit_version`; recording a facility condition decision requires
        `expected_facility_version`; posting a manual invoice adjustment requires
        `expected_invoice_version`. In each case the field must equal the current
        `version` of the entity being acted upon — the permit, the facility, or the
        invoice respectively — as the client last observed it. When the supplied value
        does not match the entity's current `version`, because another write has
        advanced that version since the client's last read, the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "One hazard survives the move: if an `ACTIVE` closure already
        intersects the brand-new slot — same facility, `closure_date` equal to the new
        date, overlapping interval — the rain-out cascade fires again within the same
        request, and the permit lands back in `RAINED_OUT` with its `version` advanced
        a second time."

        The first reschedule lands back in RAINED_OUT (a pre-existing 2026-08-12
        closure re-rains it in-request); replaying the same observed version is then
        stale.

        Design: Corner/complexity_layers/occ_permit_reschedule_stale_version_rejected
        """
        ctx = setup_confirmed_permit()
        permit_id = ctx["permit"]["id"]
        org_id = ctx["organization"]["id"]
        rain_out_permit(ctx["facility"]["id"], "2026-08-10")
        # A pre-existing closure on the reschedule target date.
        rain_out_permit(ctx["facility"]["id"], "2026-08-12")
        observed = get_permit(permit_id)["version"]

        first = validate_success(api.reschedule_permit(
            permit_id,
            create_reschedule_payload("2026-08-12", 1080, 1200, observed),
            make_org_coordinator_headers(org_id)), 200)
        assert first["status"] == "RAINED_OUT", \
            "the 2026-08-12 closure re-rains the new slot within the same request"

        replay = api.reschedule_permit(
            permit_id,
            create_reschedule_payload("2026-08-13", 1080, 1200, observed),
            make_org_coordinator_headers(org_id))
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)


class TestFacilityConditionOcc:
    def test_occ_facility_condition_stale_version_rejected(self, api,
                                                           field_supervisor_headers):
        """PRD §3.2: "The operation is OCC-guarded per §2.7: the request must carry
        `expected_facility_version` matching the facility's current `version`, else it
        fails with `ERR_STALE_VERSION`."
        PRD §2.7: "The stale request's only defect is its out-of-date view: the client
        may re-read the entity and retry with the fresh version, since successive
        reschedules, successive condition decisions, and successive adjustments are
        all legitimate under this specification."

        Design: Corner/complexity_layers/occ_facility_condition_stale_version_rejected
        """
        facility = create_facility()
        observed = facility["version"]

        first = validate_success(api.record_facility_condition(
            facility["id"],
            create_condition_payload("LIMITED", "Wet outfield", observed),
            field_supervisor_headers), 200)
        assert first["condition_status"] == "LIMITED"
        fresh = first["version"]

        replay = api.record_facility_condition(
            facility["id"],
            create_condition_payload("CLOSED", "Standing water", observed),
            field_supervisor_headers)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        assert get_facility(facility["id"])["condition_status"] == "LIMITED"

        retried = validate_success(api.record_facility_condition(
            facility["id"],
            create_condition_payload("CLOSED", "Standing water", fresh),
            field_supervisor_headers), 200)
        assert retried["condition_status"] == "CLOSED"


class TestRescheduleGates:
    def test_reschedule_horizon_exceeded_rejected(self, api):
        """PRD §3.7: "Eight guards protect the move, each with its own rejection: the
        version check fails with `ERR_STALE_VERSION`; a `rain_reschedule_count`
        already at its hard cap of 2 fails with `ERR_RESCHEDULE_LIMIT_REACHED`; a
        `CLOSED` target facility fails with `ERR_FACILITY_CLOSED`; a `new_date` before
        the permit's current `permit_date` or more than ten days after it fails with
        `ERR_RESCHEDULE_HORIZON_EXCEEDED`; a new slot starting at or before the
        logical clock fails with `ERR_SLOT_IN_PAST`; a half-open overlap with another
        `RESERVED` or `CONFIRMED` permit on the same facility and date fails with
        `ERR_SLOT_OVERLAP`; when lights were approved on the permit, a breach of the
        30-minute buffer or the nightly block cap of §2.9 fails with
        `ERR_LIGHTS_BUFFER_OVERLAP`; and a breach of the season prime cap or the
        weekly turf cap fails with `ERR_PRIME_CAP_EXCEEDED` or
        `ERR_TURF_REST_CAP_EXCEEDED` respectively."

        2026-08-21 is eleven days after the original 2026-08-10; the facility is OPEN
        so only the temporal gate can fire. The +10 boundary is inclusive: 2026-08-20
        is accepted.

        Design: Corner/errors/reschedule_horizon_exceeded_rejected
        """
        ctx = setup_rained_out_permit()
        permit_id = ctx["permit"]["id"]
        org_id = ctx["organization"]["id"]

        res = reschedule_as_owner(permit_id, org_id, "2026-08-21", 1080, 1200)
        validate_error(res, ApiErrorId.ERR_RESCHEDULE_HORIZON_EXCEEDED)
        assert get_permit(permit_id)["status"] == "RAINED_OUT"

        moved = validate_success(reschedule_as_owner(permit_id, org_id,
                                                     "2026-08-20", 1080, 1200), 200)
        assert moved["status"] == "CONFIRMED", "exactly +10 days is inside the horizon"
        assert moved["permit_date"] == "2026-08-20"

    def test_reschedule_closed_facility_safety_beats_horizon(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, and
        the order is part of the contract: an earlier failure masks every later check,
        so the error a caller receives always comes from the earliest failing stage."
        PRD §2.8: "8. **Facility safety gate.** New applications and reschedule
        targets are checked against facility condition and occupancy: a CLOSED
        facility yields `ERR_FACILITY_CLOSED`, and a `headcount` above the facility's
        `capacity` yields `ERR_HEADCOUNT_EXCEEDS_CAPACITY` (both 409)."
        PRD §2.8: "9. **Temporal gates.** Submitting into a window that is not OPEN
        yields `ERR_WINDOW_NOT_OPEN`; opening a window before its `opens_at` yields
        `ERR_WINDOW_NOT_YET_OPEN`; a slot starting at or before the logical clock
        yields `ERR_SLOT_IN_PAST`; a reschedule date outside its horizon yields
        `ERR_RESCHEDULE_HORIZON_EXCEEDED`; marking a no-show before the slot has ended
        yields `ERR_NO_SHOW_NOT_YET`; and checking in outside the check-in window
        yields `ERR_CHECKIN_WINDOW_CLOSED` (all 409)."

        The target date is beyond the horizon AND the facility is CLOSED: the safety
        gate (stage 8) masks the temporal gate (stage 9).

        Design: Difficulty/priority_pair_validation_conflict/reschedule_closed_facility_safety_beats_horizon
        """
        ctx = setup_rained_out_permit()
        permit = get_permit(ctx["permit"]["id"])
        record_condition(ctx["facility"]["id"], "CLOSED", "SAFETY: turf failure")

        res = api.reschedule_permit(
            permit["id"],
            create_reschedule_payload("2026-08-25", 1080, 1200, permit["version"]),
            make_org_coordinator_headers(ctx["organization"]["id"]))
        validate_error(res, ApiErrorId.ERR_FACILITY_CLOSED)
        after = get_permit(permit["id"])
        assert after["status"] == "RAINED_OUT", "rejected reschedule must not move the permit"
        assert after["version"] == permit["version"], \
            "rejected reschedule must not bump the version"

    def test_reschedule_beyond_horizon_temporal_gate_isolated(self, api):
        """PRD §3.2: "While a facility is `CLOSED`, two operations are blocked: new
        permit applications naming that facility are rejected with
        `ERR_FACILITY_CLOSED`, and rain reschedules targeting it fail the same way
        (§3.7)."
        PRD §3.7: "Eight guards protect the move, each with its own rejection: the
        version check fails with `ERR_STALE_VERSION`; a `rain_reschedule_count`
        already at its hard cap of 2 fails with `ERR_RESCHEDULE_LIMIT_REACHED`; a
        `CLOSED` target facility fails with `ERR_FACILITY_CLOSED`; a `new_date` before
        the permit's current `permit_date` or more than ten days after it fails with
        `ERR_RESCHEDULE_HORIZON_EXCEEDED`; a new slot starting at or before the
        logical clock fails with `ERR_SLOT_IN_PAST`; a half-open overlap with another
        `RESERVED` or `CONFIRMED` permit on the same facility and date fails with
        `ERR_SLOT_OVERLAP`; when lights were approved on the permit, a breach of the
        30-minute buffer or the nightly block cap of §2.9 fails with
        `ERR_LIGHTS_BUFFER_OVERLAP`; and a breach of the season prime cap or the
        weekly turf cap fails with `ERR_PRIME_CAP_EXCEEDED` or
        `ERR_TURF_REST_CAP_EXCEEDED` respectively."

        Control for the paired-gate claim: with the facility OPEN, the same
        beyond-horizon reschedule surfaces the temporal gate instead.

        Design: Difficulty/priority_pair_validation_conflict/reschedule_closed_facility_safety_beats_horizon
        """
        ctx = setup_rained_out_permit()
        assert get_facility(ctx["facility"]["id"])["condition_status"] == "OPEN"
        res = reschedule_as_owner(ctx["permit"]["id"], ctx["organization"]["id"],
                                  "2026-08-25", 1080, 1200)
        validate_error(res, ApiErrorId.ERR_RESCHEDULE_HORIZON_EXCEEDED)
        assert get_permit(ctx["permit"]["id"])["status"] == "RAINED_OUT"


class TestClosureLifecycle:
    def test_closure_lift_twice_rejected(self, api, field_supervisor_headers):
        """PRD §3.7: "Lifting an `ACTIVE` closure moves it to the terminal `LIFTED`
        state; lifting a closure already lifted fails with
        `ERR_INVALID_CLOSURE_STATE`. Lifting never reverts rained-out permits — the
        cascade is deliberately one-way and deterministic, and affected organizations
        must use the reschedule path instead."

        Design: Corner/state_machines/closure_lift_twice_rejected
        """
        facility = create_facility()
        closure = create_field_closure(facility["id"], closure_date="2026-08-10",
                                       reason="MAINTENANCE")
        lifted = validate_success(api.lift_closure(closure["id"],
                                                   field_supervisor_headers), 200)
        assert lifted["status"] == "LIFTED"
        res = api.lift_closure(closure["id"], field_supervisor_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_CLOSURE_STATE)
        after = get_success_data(api.get_field_closure(closure["id"],
                                                       field_supervisor_headers))
        assert after["status"] == "LIFTED"


class TestWeeklyPrimeReconcile:
    def test_derived_field_weekly_prime_reconcile(self, api):
        """PRD §2.9: "Separately, the facility's display counter
        `weekly_prime_hours_used` always reflects the prime load of the week
        containing the logical clock's date, and it is recomputed on every permit
        mutation."
        PRD §3.8: "In every cancellation the awarded hours leave the season ledger,
        the facility's `weekly_prime_hours_used` recomputes, waitlist promotion per
        §3.5 runs for the freed slot, and the permit lands in the terminal `CANCELLED`
        state."

        A prime award (2026-08-12 18:00-20:00) shows 2 once the clock enters the
        slot's week; cancelling the RESERVED permit returns the counter to 0.

        Design: Corner/complexity_layers/derived_field_weekly_prime_reconcile
        """
        ctx = setup_awarded_permit(app_overrides={"event_date": "2026-08-12"})
        set_clock("2026-08-10T09:00:00Z")  # same Mon-Sun week as the slot
        facility_id = ctx["facility"]["id"]
        assert get_facility(facility_id)["weekly_prime_hours_used"] == 2

        validate_success(cancel_permit_as_owner(ctx["permit"]["id"],
                                                ctx["organization"]["id"]), 200)
        assert get_facility(facility_id)["weekly_prime_hours_used"] == 0, \
            "cancel releases the prime hours synchronously"


class TestImmediateConsistency:
    def test_immediate_read_after_cascade(self, api):
        """PRD §2.10: "Several counters exist only as derived reconciliations over
        other entities, and the server keeps them exact at all times within the same
        request as the triggering event; none of them accepts a direct write."
        PRD §2.10: "Cascades are deterministic: when a parent decision forces child
        changes — a suspension revoking permits, a closure raining out slots — every
        affected entity is reconciled in the same request, with each mutated entity's
        `version` incremented and `updated_at` refreshed."

        The very next reads after the closure POST already show RAINED_OUT and the
        invoice credit: no delay, no re-read divergence.

        Design: Corner/consistency_model/immediate_read_after_cascade
        """
        ctx = setup_confirmed_permit(app_overrides={"wants_lights": True})
        rain_out_permit(ctx["facility"]["id"], "2026-08-10")
        assert get_permit(ctx["permit"]["id"])["status"] == "RAINED_OUT"
        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["credit_cents"] == 9600
        assert invoice["balance_due_cents"] == -5000
