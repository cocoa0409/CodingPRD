"""Lineup construction: confirm gate chain, capacity boundary, expanded
staging windows, position uniqueness, check-in windows, and invariants."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_lineup_assignment, assert_staging_area,
)

COMMITTEE = th.make_committee_admin_headers()
ENTRANT1 = th.make_entrant_headers("entrant_1")


def _band_entry_paid(api, parade_id, entrant_id, org_name):
    entry = th.create_approved_entry(parade_id, entrant_id, category="BAND", org_name=org_name)
    get_success_data(api.pay_fee(entry["id"], th.make_entrant_headers(entrant_id)))
    return entry


class TestStagingCapacityBoundary:
    """Difficulty: staging_capacity_exact_full_rejects_next (capacity 2)."""

    def _setup(self, api):
        """OPERATIONAL parade, capacity-2 lot, three paid BAND entries holding
        TENTATIVE assignments at mutually non-conflicting expanded windows."""
        ctx = th.setup_operational_parade(
            name="Capacity Parade", staging_overrides={"name": "Lot E", "capacity": 2}
        )
        windows = [("2026-07-04T07:00:00Z", "2026-07-04T07:15:00Z"),
                   ("2026-07-04T08:00:00Z", "2026-07-04T08:15:00Z"),
                   ("2026-07-04T09:00:00Z", "2026-07-04T09:15:00Z")]
        assignments = []
        for i, (arrive, depart) in enumerate(windows, start=1):
            entry = _band_entry_paid(api, ctx["parade"]["id"], f"entrant_{i}", f"Band {i}")
            assignments.append(th.create_tentative_assignment(
                ctx["parade"]["id"], entry["id"], ctx["staging"]["id"],
                position_number=i, arrive_at=arrive, depart_at=depart,
            ))
        return ctx, assignments

    def test_confirm_succeeds_until_reserved_reaches_capacity_minus_one(self, api):
        """PRD §3.5: "Capacity is aggregate and inclusive at the boundary: a
        lot whose `reserved_slots` already equals its `capacity` rejects the
        confirmation, while a lot with exactly one free slot accepts it."

        Design: Difficulty/boundary_precision_check/staging_capacity_exact_full_rejects_next
        """
        ctx, assignments = self._setup(api)
        first = validate_success(api.confirm_assignment(assignments[0]["id"], COMMITTEE))
        assert first["status"] == "CONFIRMED", "reserved 0 < 2 must accept"
        second = validate_success(api.confirm_assignment(assignments[1]["id"], COMMITTEE))
        assert second["status"] == "CONFIRMED", "reserved 1 < 2 must accept"

        staging = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert staging["reserved_slots"] == 2

    def test_confirm_at_exact_capacity_rejected_without_drift(self, api):
        """PRD §3.5: "Capacity is aggregate and inclusive at the boundary: a
        lot whose `reserved_slots` already equals its `capacity` rejects the
        confirmation, while a lot with exactly one free slot accepts it."
        PRD §3.5: "A successful confirmation recomputes the lot's
        `reserved_slots` upward by one, since the counter tracks assignments in
        `CONFIRMED` or `CHECKED_IN` status."

        Design: Difficulty/boundary_precision_check/staging_capacity_exact_full_rejects_next
        """
        ctx, assignments = self._setup(api)
        th.confirm_assignment(assignments[0]["id"])
        th.confirm_assignment(assignments[1]["id"])

        resp = api.confirm_assignment(assignments[2]["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_STAGING_CAPACITY_FULL)

        staging = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert staging["reserved_slots"] == 2, "the rejection must not drift the counter"
        third = validate_success(api.get_lineup_assignment(assignments[2]["id"], COMMITTEE))
        assert third["status"] == "TENTATIVE"


class TestStagingWindowConflict:
    """Difficulty: staging_closed_intervals_with_buffer_reject_touching."""

    def _setup(self, api):
        """OPERATIONAL parade; E1 certified+paid CONFIRMED at [07:30, 08:00];
        E2 certified+paid TENTATIVE at [08:10, 08:40] on the same lot."""
        ctx = th.setup_operational_parade(
            name="Window Parade", staging_overrides={"name": "Lot H", "capacity": 5}
        )
        entry1, _ = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_1", inspector_id="insp_1",
            estimated_participants=50, org_name="Float One",
        )
        a1 = th.create_confirmed_assignment(
            ctx["parade"]["id"], entry1["id"], ctx["staging"]["id"], position_number=1,
            arrive_at="2026-07-04T07:30:00Z", depart_at="2026-07-04T08:00:00Z",
        )
        entry2, _ = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_2", inspector_id="insp_1",
            estimated_participants=40, org_name="Float Two",
            vehicle_class="TOWED", fuel_type="NONE",
        )
        a2 = th.create_tentative_assignment(
            ctx["parade"]["id"], entry2["id"], ctx["staging"]["id"], position_number=2,
            arrive_at="2026-07-04T08:10:00Z", depart_at="2026-07-04T08:40:00Z",
        )
        return ctx, a1, a2

    def test_buffered_windows_intersect_rejects_confirm(self, api):
        """PRD §3.5: "Every assignment occupies an expanded window on its
        staging lot, running from fifteen minutes before `arrive_at` to fifteen
        minutes after `depart_at`, inclusive at both ends. A confirmation is
        rejected with `ERR_STAGING_WINDOW_CONFLICT` when that expanded window
        intersects the expanded window of any other assignment on the same lot
        in `CONFIRMED` or `CHECKED_IN` status — and because the intervals are
        closed, merely touching endpoints count as an intersection: a candidate
        arriving at exactly the minute another assignment's expanded window
        ends is a conflict."

        Design: Difficulty/resource_temporal_overlap/staging_closed_intervals_with_buffer_reject_touching
        """
        # Raw windows [07:30,08:00] and [08:10,08:40] do not touch, but the
        # expanded windows [07:15,08:15] and [07:55,08:55] intersect.
        _, _, a2 = self._setup(api)
        resp = api.confirm_assignment(a2["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_STAGING_WINDOW_CONFLICT)

    def test_rejected_confirm_leaves_assignment_and_slots_untouched(self, api):
        """PRD §3.5: "A successful confirmation recomputes the lot's
        `reserved_slots` upward by one, since the counter tracks assignments in
        `CONFIRMED` or `CHECKED_IN` status."
        PRD §3.5: "New assignments are born `TENTATIVE` and occupy no slot
        yet."

        Design: Difficulty/resource_temporal_overlap/staging_closed_intervals_with_buffer_reject_touching
        """
        ctx, _, a2 = self._setup(api)
        validate_error(
            api.confirm_assignment(a2["id"], COMMITTEE), ApiErrorId.ERR_STAGING_WINDOW_CONFLICT
        )
        after = validate_success(api.get_lineup_assignment(a2["id"], COMMITTEE))
        assert after["status"] == "TENTATIVE"
        staging = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert staging["reserved_slots"] == 1


class TestConfirmGateOrdering:
    """Difficulty: priority_pair_validation_conflict instances."""

    def test_frozen_posture_beats_unpaid_fee(self, api):
        """PRD §3.5: "Confirmation is the most heavily gated transition in the
        system, and its seven checks run in a fixed order so that the first
        failure is the one reported. First the parade's posture must not be
        `FROZEN` (`ERR_EVENT_FROZEN`), and the entry must stand `APPROVED`
        (`ERR_ENTRY_NOT_APPROVED`)."
        PRD §3.5: "After capacity comes the temporal check, and only at the
        very end the fiscal gate: the entry's `fee_paid` must be true, or the
        confirmation fails with `ERR_ENTRY_FEE_OUTSTANDING` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_frozen_event_and_unpaid_fee_state_wins
        """
        ctx = th.setup_operational_parade(name="Frozen Parade",
                                          staging_overrides={"name": "Lot C"})
        entry = th.create_approved_entry(ctx["parade"]["id"], "entrant_1",
                                         category="BAND", org_name="Unpaid Band")
        # Fee deliberately NOT paid — the fiscal gate would also fail.
        assignment = th.create_tentative_assignment(
            ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
        )
        get_success_data(
            api.revoke_permit(ctx["permit"]["id"], th.make_agency_reviewer_headers())
        )

        resp = api.confirm_assignment(assignment["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_EVENT_FROZEN)

        after = validate_success(api.get_lineup_assignment(assignment["id"], COMMITTEE))
        assert after["status"] == "TENTATIVE", (
            "the revoke cascade pulls only CONFIRMED/CHECKED_IN assignments"
        )

    def test_frozen_posture_beats_unpaid_fee_paid_variant(self, api):
        """PRD §2.4: "While a parade is frozen, the following mutations are all
        rejected with `ERR_EVENT_FROZEN` (HTTP 409): starting review on an
        entry, approving, rejecting, or requesting revision on an entry, an
        entrant's resubmission of an entry, confirming a lineup assignment,
        checking a lineup assignment in, submitting a score sheet, finalizing a
        score sheet, activating a sponsor package, approving a script item,
        announcing or presenting an award, and publishing the lineup."

        Design: Difficulty/priority_pair_validation_conflict/confirm_frozen_event_and_unpaid_fee_state_wins
        """
        ctx = th.setup_operational_parade(name="Frozen Paid Parade",
                                          staging_overrides={"name": "Lot C2"})
        entry = _band_entry_paid(api, ctx["parade"]["id"], "entrant_1", "Paid Band")
        assignment = th.create_tentative_assignment(
            ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
        )
        get_success_data(
            api.revoke_permit(ctx["permit"]["id"], th.make_agency_reviewer_headers())
        )
        # Even with the fee settled, the frozen posture alone blocks confirm.
        resp = api.confirm_assignment(assignment["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_EVENT_FROZEN)

    def test_uncertified_float_beats_window_conflict(self, api):
        """PRD §3.5: "Next, the safety gate: if the entry has any floats at
        all, every one of them must be `CERTIFIED`, else `ERR_FLOAT_UNCERTIFIED`
        (HTTP 422). Then come the two constraint checks — the requested
        `position_number` must not already be held by another assignment of the
        same parade in `TENTATIVE`, `CONFIRMED`, or `CHECKED_IN` status
        (`ERR_LINEUP_POSITION_TAKEN`), and the staging lot must have room
        (`ERR_STAGING_CAPACITY_FULL`, HTTP 422). Capacity is aggregate and
        inclusive at the boundary: a lot whose `reserved_slots` already equals
        its `capacity` rejects the confirmation, while a lot with exactly one
        free slot accepts it. After capacity comes the temporal check, and only
        at the very end the fiscal gate: the entry's `fee_paid` must be true,
        or the confirmation fails with `ERR_ENTRY_FEE_OUTSTANDING` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_uncertified_float_and_window_conflict_safety_wins
        """
        ctx = th.setup_operational_parade(name="Safety Parade",
                                          staging_overrides={"name": "Lot D", "capacity": 5})
        entry1, _ = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_1", inspector_id="insp_1",
            estimated_participants=50, org_name="Cert Float",
        )
        th.create_confirmed_assignment(
            ctx["parade"]["id"], entry1["id"], ctx["staging"]["id"], position_number=1,
            arrive_at="2026-07-04T07:30:00Z", depart_at="2026-07-04T08:00:00Z",
        )
        entry2 = th.create_approved_entry(ctx["parade"]["id"], "entrant_2",
                                          category="FLOAT", org_name="Uncert Float",
                                          estimated_participants=40)
        get_success_data(
            api.create_float(entry2["id"],
                             th.create_float_payload(vehicle_class="TOWED", fuel_type="NONE"),
                             th.make_entrant_headers("entrant_2"))
        )  # float left PENDING_INSPECTION
        get_success_data(api.pay_fee(entry2["id"], th.make_entrant_headers("entrant_2")))
        a2 = th.create_tentative_assignment(
            ctx["parade"]["id"], entry2["id"], ctx["staging"]["id"], position_number=2,
            arrive_at="2026-07-04T08:10:00Z", depart_at="2026-07-04T08:40:00Z",
        )
        # Expanded windows [07:55,08:55] and [07:15,08:15] do intersect, but
        # the safety gate runs first.
        resp = api.confirm_assignment(a2["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_FLOAT_UNCERTIFIED)

    def test_uncertified_float_gate_leaves_no_side_effects(self, api):
        """PRD §3.5: "New assignments are born `TENTATIVE` and occupy no slot
        yet."
        PRD §3.5: "A successful confirmation recomputes the lot's
        `reserved_slots` upward by one, since the counter tracks assignments in
        `CONFIRMED` or `CHECKED_IN` status."

        Design: Difficulty/priority_pair_validation_conflict/confirm_uncertified_float_and_window_conflict_safety_wins
        """
        ctx = th.setup_operational_parade(name="Safety Parade 2",
                                          staging_overrides={"name": "Lot D2", "capacity": 5})
        entry1, _ = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_1", inspector_id="insp_1",
            estimated_participants=50, org_name="Cert Float",
        )
        th.create_confirmed_assignment(
            ctx["parade"]["id"], entry1["id"], ctx["staging"]["id"], position_number=1,
            arrive_at="2026-07-04T07:30:00Z", depart_at="2026-07-04T08:00:00Z",
        )
        entry2 = th.create_approved_entry(ctx["parade"]["id"], "entrant_2",
                                          category="FLOAT", org_name="Uncert Float",
                                          estimated_participants=40)
        get_success_data(
            api.create_float(entry2["id"], th.create_float_payload(),
                             th.make_entrant_headers("entrant_2"))
        )
        get_success_data(api.pay_fee(entry2["id"], th.make_entrant_headers("entrant_2")))
        a2 = th.create_tentative_assignment(
            ctx["parade"]["id"], entry2["id"], ctx["staging"]["id"], position_number=2,
            arrive_at="2026-07-04T08:10:00Z", depart_at="2026-07-04T08:40:00Z",
        )
        validate_error(api.confirm_assignment(a2["id"], COMMITTEE), ApiErrorId.ERR_FLOAT_UNCERTIFIED)

        after = validate_success(api.get_lineup_assignment(a2["id"], COMMITTEE))
        assert after["status"] == "TENTATIVE"
        staging = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert staging["reserved_slots"] == 1


class TestConfirmEntryGate:
    """Difficulty: confirm_requires_entry_approved_cross_entity."""

    def _setup_suspended_with_tentative(self, api):
        """OPERATIONAL parade; approved+paid FLOAT entry with a TENTATIVE
        assignment; then the float FAILS, suspending the entry."""
        ctx = th.setup_operational_parade(name="Gate Parade",
                                          staging_overrides={"name": "Lot F"})
        entry = th.create_approved_entry(ctx["parade"]["id"], "entrant_1",
                                         category="FLOAT", org_name="Gated Floats",
                                         estimated_participants=120)
        get_success_data(api.pay_fee(entry["id"], ENTRANT1))
        assignment = th.create_tentative_assignment(
            ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
        )
        float_obj = get_success_data(
            api.create_float(entry["id"], th.create_float_payload(), ENTRANT1)
        )
        inspection = get_success_data(
            api.schedule_inspection(float_obj["id"], th.schedule_inspection_payload(),
                                    th.make_safety_inspector_headers("insp_1"))
        )
        get_success_data(
            api.fail_inspection(inspection["id"], {"checklist_score": 55},
                                th.make_safety_inspector_headers("insp_1"))
        )
        return ctx, entry, assignment

    def test_confirm_suspended_entry_rejected_not_approved(self, api):
        """PRD §3.5: "First the parade's posture must not be `FROZEN`
        (`ERR_EVENT_FROZEN`), and the entry must stand `APPROVED`
        (`ERR_ENTRY_NOT_APPROVED`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_entry_approved_cross_entity
        """
        _, entry, assignment = self._setup_suspended_with_tentative(api)
        suspended = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert suspended["status"] == "SUSPENDED"

        resp = api.confirm_assignment(assignment["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_APPROVED)

    def test_suspension_leaves_tentative_assignment_in_place(self, api):
        """PRD §3.4: "Failing requires a score strictly below 70 — a fail
        attempted at 70 or above is `ERR_VALIDATION` — and fires a four-hop
        cascade of its own: the float's `compliance_status` becomes `FAILED`;
        the parent entry, if `APPROVED`, drops to `SUSPENDED`; that suspension
        pulls the entry's `CONFIRMED` and `CHECKED_IN` lineup assignments to
        `PULLED`; and each pull releases its staging slot and cancels the
        entry's approved `ENTRY_INTRO` script items."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_entry_approved_cross_entity
        """
        ctx, _, assignment = self._setup_suspended_with_tentative(api)
        after = validate_success(api.get_lineup_assignment(assignment["id"], COMMITTEE))
        assert after["status"] == "TENTATIVE", (
            "the suspension cascade pulls only CONFIRMED/CHECKED_IN assignments"
        )
        staging = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert staging["reserved_slots"] == 0


class TestSlotInvariant:
    """Difficulty: confirm_then_pull_restores_reserved_slots."""

    def test_confirm_raises_reserved_slots_by_one(self, api):
        """PRD §3.5: "A successful confirmation recomputes the lot's
        `reserved_slots` upward by one, since the counter tracks assignments in
        `CONFIRMED` or `CHECKED_IN` status."

        Design: Difficulty/compensating_invariant/confirm_then_pull_restores_reserved_slots
        """
        ctx = th.setup_operational_parade(name="Invariant Parade",
                                          staging_overrides={"name": "Lot I"})
        entry, _ = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_1", inspector_id="insp_1",
            estimated_participants=50, org_name="Invariant Floats",
        )
        assignment = th.create_tentative_assignment(
            ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
        )
        baseline = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert baseline["reserved_slots"] == 0

        confirmed = validate_success(api.confirm_assignment(assignment["id"], COMMITTEE))
        assert_lineup_assignment(confirmed)
        assert confirmed["status"] == "CONFIRMED"

        after = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert after["reserved_slots"] == 1, "confirm adds exactly one reserved slot"

    def test_compensating_pull_restores_reserved_slots_to_baseline(self, api):
        """PRD §3.5: "Pulling an assignment — by explicit committee action from
        `TENTATIVE` or `CONFIRMED`, or by system cascade from `CHECKED_IN` —
        moves it to `PULLED`, terminal; a pull from `CONFIRMED` or `CHECKED_IN`
        releases the slot, a pull from `TENTATIVE` does not touch the counter,
        and every pull regardless of origin cancels the entry's approved
        `ENTRY_INTRO` items."

        Design: Difficulty/compensating_invariant/confirm_then_pull_restores_reserved_slots
        """
        ctx = th.setup_operational_parade(name="Invariant Parade 2",
                                          staging_overrides={"name": "Lot I2"})
        entry, _ = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_1", inspector_id="insp_1",
            estimated_participants=50, org_name="Invariant Floats",
        )
        assignment = th.create_confirmed_assignment(
            ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
        )
        pulled = validate_success(api.pull_assignment(assignment["id"], COMMITTEE))
        assert pulled["status"] == "PULLED"

        after = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert_staging_area(after)
        assert after["reserved_slots"] == 0, (
            "the compensating pull must restore the counter to its pre-confirm baseline"
        )


class TestLineupCreationGates:

    def test_window_outside_staging_hours_rejected(self, api):
        """PRD §3.5: "The window must sit inside the staging lot's trading
        hours — `arrive_at` at or after the lot's `open_time`, `depart_at` at
        or before its `close_time`, and `depart_at` strictly after `arrive_at`
        — a rule checked both at creation and again at confirmation, with
        violations surfaced as `ERR_WINDOW_OUTSIDE_STAGING_HOURS` (HTTP 422)."

        Design: Corner/validations/lineup_window_outside_staging_hours_rejected
        """
        ctx = th.setup_operational_parade(name="Hours Parade",
                                          staging_overrides={"name": "Lot T", "capacity": 5})
        entry = th.create_approved_entry(ctx["parade"]["id"], "entrant_1",
                                         category="BAND", org_name="Early Bird Band")
        resp = api.create_lineup_assignment(
            ctx["parade"]["id"],
            th.create_lineup_assignment_payload(
                entry["id"], ctx["staging"]["id"], position_number=1,
                arrive_at="2026-07-04T06:30:00Z", depart_at="2026-07-04T07:30:00Z",
            ),
            COMMITTEE,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_STAGING_HOURS)


class TestCheckInWindow:

    def test_checkin_before_arrival_window_rejected(self, api):
        """PRD §3.5: "On parade day, an assignment is checked in — moving it
        from `CONFIRMED` to `CHECKED_IN` — only after the lineup has been
        published (`ERR_LINEUP_NOT_PUBLISHED` while the parade is in any
        earlier status), only while the parade is unfrozen, and only while the
        logical clock reads within the assignment's own arrival-to-departure
        window, inclusive at both ends; outside that window the attempt fails
        with `ERR_CHECKIN_WINDOW_NOT_OPEN` (HTTP 422)."

        Design: Corner/validations/checkin_before_window_rejected
        """
        ctx = th.setup_published_parade(name="Checkin Parade", confirm=True)
        th.set_clock("2026-07-04T07:00:00Z")  # arrive_at is 07:30

        resp = api.check_in_assignment(ctx["assignment"]["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_NOT_OPEN)

        after = validate_success(api.get_lineup_assignment(ctx["assignment"]["id"], COMMITTEE))
        assert after["status"] == "CONFIRMED"
