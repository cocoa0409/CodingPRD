"""Harvest tallies, field depletion cascade, and cross-entity state gates."""
from test_helpers import (
    TEST_USERS,
    admit_online_session,
    create_crop,
    create_field,
    create_sales_day,
    create_season,
    create_window,
    enter_session,
    get_crop,
    get_field,
    get_session,
    get_window,
    offline_harvest_line_record,
    only_line_of_session,
    open_window,
    pay_admission,
    set_clock,
    setup_operating_day,
    setup_paid_session,
    sign_waiver,
    upload_batch,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_out,
)

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]


def _tally_world(api):
    """FIELD_ACTIVE session (paid 1450) plus one FINALIZED online line of net
    600 oz and one PROVISIONAL offline line of net 300 oz on a 1000 oz field."""
    world = setup_operating_day(crop_price_per_lb=480)
    session = setup_paid_session(world, container_count=4, enter=True)
    world["session_id"] = session["id"]
    line = weigh_out(session["id"], world["crop_id"], 616, 4)  # net 600
    world["line_id"] = line["id"]
    upload_batch("DEV1", "B1", [offline_harvest_line_record(
        1, "L1", session_ref=session["id"], crop_id=world["crop_id"],
        gross_weight_oz=316, container_count=4)])  # net 300, PROVISIONAL
    return world


class TestForwardVsCommittedTallies:
    def test_field_tallies_split_by_line_status(self, api):
        """PRD §3.2: "`committed_picked_oz` is the sum of `net_oz` over the
        field's `FINALIZED` harvest lines only — verified weight, the basis
        that decides picking-out."
        PRD §3.2: "`projected_remaining_oz` is the field's
        `estimated_harvest_oz` minus the sum of `net_oz` over lines in either
        `PROVISIONAL` or `FINALIZED` status"

        Design: Difficulty/dual_variant_calc/field_remaining_forward_vs_committed
        """
        world = _tally_world(api)
        field = get_field(world["field_id"])
        assert field["committed_picked_oz"] == 600, "FINALIZED lines only"
        assert field["projected_remaining_oz"] == 100, (
            "1000 - 600 FINALIZED - 300 PROVISIONAL")

    def test_crop_tally_and_line_charge_use_committed_basis(self, api):
        """PRD §3.2: "The same crop-level mirror, `season_picked_oz`,
        accumulates `net_oz` over `FINALIZED` lines across the whole season for
        that crop."
        PRD §3.5: "`line_charge_cents` is `net_oz` multiplied by the crop's
        `price_per_lb_cents` and divided by 16 ounces per pound, rounded half
        up to whole cents."

        Design: Difficulty/dual_variant_calc/field_remaining_forward_vs_committed
        """
        world = _tally_world(api)
        crop = get_crop(world["crop_id"])
        assert crop["season_picked_oz"] == 600, (
            "the PROVISIONAL 300 oz is excluded from the crop mirror")
        line = validate_success(api.get_harvest_line(world["line_id"], MANAGER))
        assert line["line_charge_cents"] == 18000, "round_half_up(600*480/16)"


def _provisional_line_world(api):
    """FIELD_ACTIVE session carrying one offline-uploaded PROVISIONAL line of
    net 300 oz on a 1000 oz field."""
    world = setup_operating_day(crop_price_per_lb=480)
    session = setup_paid_session(world, enter=True)
    world["session_id"] = session["id"]
    upload_batch("DEV1", "B9", [offline_harvest_line_record(
        1, "L9", session_ref=session["id"], crop_id=world["crop_id"],
        gross_weight_oz=316, container_count=4)])
    world["line_id"] = only_line_of_session(session["id"])["id"]
    return world


class TestFinalizeVoidConservation:
    def test_finalize_commits_provisional_weight(self, api):
        """PRD §3.9: "otherwise the line is created in `PROVISIONAL` status
        with `tare_oz`, `net_oz`, and `line_charge_cents` computed exactly as
        §3.5 defines, and no field checks are applied at upload time"
        PRD §3.5: "A successful finalize applies exactly the same tally side
        effects as a fresh online line, cascade included."

        Design: Difficulty/compensating_invariant/finalize_void_harvest_oz_conservation
        """
        world = _provisional_line_world(api)
        line = validate_success(
            api.get_harvest_line(world["line_id"], MANAGER))
        assert line["status"] == "PROVISIONAL"
        assert get_field(world["field_id"])["committed_picked_oz"] == 0, (
            "provisional weight never touches the committed basis")

        finalized = validate_success(
            api.finalize_harvest_line(world["line_id"], FIELD_STAFF))
        assert finalized["status"] == "FINALIZED"
        assert get_field(world["field_id"])["committed_picked_oz"] == 300
        assert get_field(world["field_id"])["projected_remaining_oz"] == 700
        assert get_crop(world["crop_id"])["season_picked_oz"] == 300

    def test_void_after_finalize_restores_tallies(self, api):
        """PRD §3.5: "When a `FINALIZED` line is voided, its `net_oz` is
        subtracted back out of the field's `committed_picked_oz` and the crop's
        `season_picked_oz` as a compensating reversal; `projected_remaining_oz`
        recomputes in all cases, voided provisional weight included."

        Design: Difficulty/compensating_invariant/finalize_void_harvest_oz_conservation
        """
        world = _provisional_line_world(api)
        validate_success(api.finalize_harvest_line(world["line_id"], FIELD_STAFF))
        voided = validate_success(
            api.void_harvest_line(world["line_id"], FIELD_STAFF))
        assert voided["status"] == "VOIDED"
        field = get_field(world["field_id"])
        assert field["committed_picked_oz"] == 0, "finalize + void conserves ounces"
        assert field["projected_remaining_oz"] == 1000
        assert get_crop(world["crop_id"])["season_picked_oz"] == 0


class TestEnterFieldCrossEntityGate:
    def _picked_out_world(self, api):
        """Session S checked in but never entered; sibling session S2 enters
        and weighs out 20 oz on a 20 oz field, flipping it to PICKED_OUT."""
        world = setup_operating_day(estimated_harvest_oz=20)
        wv_b = sign_waiver(world["season_id"], ["Bob"], signer_name="Bob",
                           signer_email="bob@x.com")
        session_s = setup_paid_session(world, container_count=4, key="ks")
        session_s2 = setup_paid_session(world, container_count=4, enter=True,
                                        waiver_id=wv_b["id"], key="ks2")
        weigh_out(session_s2["id"], world["crop_id"], 36, 4)  # net 20 >= 20
        world["session_s_id"] = session_s["id"]
        return world

    def test_enter_field_blocked_when_field_picked_out(self, api):
        """PRD §3.4: "its field must be `OPEN` (`ERR_FIELD_NOT_OPEN`)"
        PRD §3.2: "The moment a weigh-out creation or finalization pushes a
        field's `committed_picked_oz` to equal or exceed its
        `estimated_harvest_oz`, the field transitions from `OPEN` to
        `PICKED_OUT`"

        Design: Difficulty/cross_entity_state_dependency/enter_field_blocked_when_field_picked_out
        """
        world = self._picked_out_world(api)
        resp = api.enter_field(world["session_s_id"], FIELD_STAFF)
        validate_error(resp, "ERR_FIELD_NOT_OPEN", 409)
        assert get_session(world["session_s_id"])["visit_status"] == "CHECKED_IN"

    def test_grace_window_stays_open_while_field_picked_out(self, api):
        """PRD §3.2: "windows of past dates are untouched, and today's `OPEN`
        window stays `OPEN` as a grace so on-site sessions can finish picking
        and weigh out."

        Design: Difficulty/cross_entity_state_dependency/enter_field_blocked_when_field_picked_out
        """
        world = self._picked_out_world(api)
        assert get_field(world["field_id"])["status"] == "PICKED_OUT"
        assert get_window(world["window_id"])["status"] == "OPEN", (
            "the blocker for enter-field is the field's state, not the window's")


class TestHarvestLineSessionGate:
    def test_harvest_line_blocked_until_session_field_active(self, api):
        """PRD §3.5: "The session must be `FIELD_ACTIVE`
        (`ERR_SESSION_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/harvest_line_blocked_until_session_field_active
        """
        world = setup_operating_day()
        session = setup_paid_session(world)  # paid but never entered
        resp = api.create_harvest_line(
            {"session_id": session["id"], "crop_id": world["crop_id"],
             "gross_weight_oz": 36, "container_count": 4},
            FIELD_STAFF)
        validate_error(resp, "ERR_SESSION_NOT_ACTIVE", 409)

    def test_rejected_line_is_never_persisted(self, api):
        """PRD §3.5: "The session must be `FIELD_ACTIVE`
        (`ERR_SESSION_NOT_ACTIVE`), the field must be `OPEN`
        (`ERR_FIELD_NOT_OPEN`)"

        Design: Difficulty/cross_entity_state_dependency/harvest_line_blocked_until_session_field_active
        """
        world = setup_operating_day()
        session = setup_paid_session(world)
        validate_error(
            api.create_harvest_line(
                {"session_id": session["id"], "crop_id": world["crop_id"],
                 "gross_weight_oz": 36, "container_count": 4},
                FIELD_STAFF),
            "ERR_SESSION_NOT_ACTIVE")
        _, meta = validate_paginated(api.list_harvest_lines(
            MANAGER, params={"session_id": session["id"]}))
        assert meta["total_count"] == 0


def _depletion_world(api):
    """Field A (estimate 100 oz) OPEN with today's window OPEN and a SCHEDULED
    window tomorrow; Field B DORMANT in the same rotation group; a FIELD_ACTIVE
    session ready to weigh out."""
    world = setup_operating_day(estimated_harvest_oz=100)
    field_b = create_field(world["season_id"], name="South", rotation_order=2,
                           estimated_harvest_oz=500)
    world["field_b_id"] = field_b["id"]
    create_sales_day(world["season_id"], date="2026-08-05")
    window2 = create_window(world["field_id"], date="2026-08-05",
                            open_time="09:00", close_time="12:00")
    world["window2_id"] = window2["id"]
    session = setup_paid_session(world, container_count=4, enter=True)
    world["session_id"] = session["id"]
    return world


class TestDepletionCascade:
    def test_committed_tally_at_exact_estimate_picks_out(self, api):
        """PRD §3.2: "The moment a weigh-out creation or finalization pushes a
        field's `committed_picked_oz` to equal or exceed its
        `estimated_harvest_oz`, the field transitions from `OPEN` to
        `PICKED_OUT` — the triggering line has already updated the tallies —
        and a cascade fires."

        Design: Difficulty/transitive_cascade/depletion_threshold_cascade
        """
        world = _depletion_world(api)
        weigh_out(world["session_id"], world["crop_id"], 116, 4)  # net 100
        field = get_field(world["field_id"])
        assert field["committed_picked_oz"] == 100
        assert field["status"] == "PICKED_OUT", "100 >= 100 at exact equality"

    def test_depletion_cancels_future_windows_and_pins_successor(self, api):
        """PRD §3.2: "Every `SCHEDULED` window of that field is cancelled with
        `cancel_reason` `DEPLETED`; windows of past dates are untouched, and
        today's `OPEN` window stays `OPEN` as a grace so on-site sessions can
        finish picking and weigh out."
        PRD §3.2: "among fields sharing the same `season_id` and
        `rotation_group` that are `DORMANT` and whose `rest_until` is null or
        not later than the current date, the successor is the field with the
        lowest `rotation_order`, ties broken by earlier `created_at`"

        Design: Difficulty/transitive_cascade/depletion_threshold_cascade
        """
        world = _depletion_world(api)
        weigh_out(world["session_id"], world["crop_id"], 116, 4)
        window2 = get_window(world["window2_id"])
        assert window2["status"] == "CANCELLED"
        assert window2["cancel_reason"] == "DEPLETED"
        assert get_field(world["field_id"])["rotation_successor_field_id"] == \
            world["field_b_id"]
        assert get_window(world["window_id"])["status"] == "OPEN", "grace window"


class TestFinalizeAndScopeRules:
    def test_finalize_finalized_line_rejected(self, api):
        """PRD §3.5: "A line created online by staff is a staff-attested
        weigh-out and is born directly in `FINALIZED` status"
        PRD §3.5: "a line that is not `PROVISIONAL` cannot be finalized and the
        attempt is rejected with `ERR_LINE_NOT_PROVISIONAL` (409)."

        Design: Corner/state_machines/finalize_finalized_line_rejected
        """
        world = setup_operating_day()
        session = setup_paid_session(world, enter=True)
        line = weigh_out(session["id"], world["crop_id"], 36, 4)
        assert line["status"] == "FINALIZED", "online lines are born FINALIZED"
        resp = api.finalize_harvest_line(line["id"], FIELD_STAFF)
        validate_error(resp, "ERR_LINE_NOT_PROVISIONAL", 409)

    def test_harvest_line_cross_scope_rejected(self, api):
        """PRD §3.5: "the crop must belong to the same season as the field, the
        window, and the session (`ERR_CROSS_SCOPE_REFERENCE`, 422)."

        Design: Corner/validations/harvest_line_cross_scope_rejected
        """
        world = setup_operating_day()
        session = setup_paid_session(world, enter=True)
        season2 = create_season(name="2027 Harvest", start_date="2027-05-01",
                                end_date="2027-09-30", waiver_text="WAIVER-2027")
        foreign_crop = create_crop(season2["id"], name="Blueberry",
                                   price_per_lb_cents=500)
        resp = api.create_harvest_line(
            {"session_id": session["id"], "crop_id": foreign_crop["id"],
             "gross_weight_oz": 36, "container_count": 4},
            FIELD_STAFF)
        validate_error(resp, "ERR_CROSS_SCOPE_REFERENCE", 422)


class TestFieldEditOcc:
    def test_occ_field_patch_stale_version_rejected(self, api):
        """PRD §2.6: "A field-edit request must carry `expected_field_version`
        equal to the field's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "the field's `committed_picked_oz` and the crop's
        `season_picked_oz` each increase by the line's `net_oz`, the `version`
        of both field and crop increments"

        Design: Corner/cross_cutting_layers/occ_field_patch_stale_version_rejected
        """
        world = setup_operating_day()
        version_at_open = world["field"]["version"]
        session = setup_paid_session(world, container_count=4, enter=True)
        weigh_out(session["id"], world["crop_id"], 616, 4)  # bumps Field.version

        resp = api.patch_field(world["field_id"],
                               {"expected_field_version": version_at_open,
                                "rotation_order": 5},
                               MANAGER)
        validate_error(resp, "ERR_STALE_VERSION", 412)

        fresh_version = get_field(world["field_id"])["version"]
        patched = validate_success(api.patch_field(
            world["field_id"],
            {"expected_field_version": fresh_version, "rotation_order": 5},
            MANAGER))
        assert patched["rotation_order"] == 5
        assert patched["version"] == fresh_version + 1, (
            "version increments by one on every mutation")


class TestImmediateConsistency:
    def test_immediate_consistency_derived_fields_same_request(self, api):
        """PRD §2.5: "Derived fields — harvest tallies, booked slot and parking
        aggregates, payment and refund totals, session charges — are never
        cached stale: each is recomputed immediately inside the mutating
        request that affects it, so any read after a successful write observes
        the post-write state."
        PRD §3.7: "A new payment starts `PENDING`; `CASH` and online `CARD`
        settle immediately"

        Design: Corner/consistency_model/immediate_consistency_derived_fields_same_request
        """
        world = setup_operating_day()
        session = admit_online_session(world, container_count=4)
        payment = pay_admission(session, key="k1")
        assert payment["status"] == "SETTLED", "CASH settles in-request"
        session = enter_session(session["id"])

        line = weigh_out(session["id"], world["crop_id"], 36, 4)
        assert line["tare_oz"] == 16
        assert line["net_oz"] == 20
        assert line["line_charge_cents"] == 600
        assert line["status"] == "FINALIZED"

        assert get_field(world["field_id"])["committed_picked_oz"] == 20, (
            "no lag, no recompute endpoint")
        after = get_session(session["id"])
        assert after["total_paid_cents"] == 1450
        assert after["payment_status"] == "PAID"
