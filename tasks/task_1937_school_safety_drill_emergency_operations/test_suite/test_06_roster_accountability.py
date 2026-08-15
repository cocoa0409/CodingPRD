"""Roster accountability and reunification: entry uniqueness, the
accommodation and pickup-verification safety gates, terminal release, and
the roster headcount conservation invariant."""
from test_helpers import (
    ApiErrorId,
    account_entry,
    add_roster_entry,
    assert_roster_counters_invariant,
    create_accommodation_plan,
    create_roster_entry_payload,
    get_drill,
    get_roster_entry,
    release_entry,
    run_completed_drill,
    schedule_drill,
    setup_active_eop_site,
    start_drill_on,
    unaccount_entry,
    validate_error,
    validate_success,
)


def _in_progress_drill_with_entries(ctx, student_refs=("stu-1",)):
    """Drill IN_PROGRESS on 2026-09-15 with the given students rostered."""
    drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
    start_drill_on(drill["id"], "2026-09-15", "09:00")
    entries = [add_roster_entry(drill["id"], student_ref=ref)
               for ref in student_refs]
    return drill, entries


class TestRosterGates:
    def test_duplicate_roster_entry_rejected(self, api, officer_headers):
        """PRD: "Only one roster entry per student per drill is permitted; a duplicate `student_ref` on the same drill is rejected with `ERR_DUPLICATE_ROSTER_ENTRY`."

        Design: Corner/validations/duplicate_roster_entry_rejected
        """
        ctx = setup_active_eop_site()
        drill, _entries = _in_progress_drill_with_entries(ctx)

        resp = api.add_roster_entry(
            drill["id"],
            create_roster_entry_payload(student_ref="stu-1"),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROSTER_ENTRY)

        current = get_drill(drill["id"])
        assert current["roster_total"] == 1, (
            "The rejected duplicate must not be persisted")

    def test_pickup_not_verified_rejected(self, api, officer_headers):
        """PRD: "The release request must include `guardian_name` (the receiving guardian's name) and `released_to_verified`, a boolean confirming identity verification. Releasing with `released_to_verified` not set to `true` is rejected with `ERR_PICKUP_NOT_VERIFIED`."

        Design: Corner/validations/pickup_not_verified_rejected
        """
        ctx = setup_active_eop_site()
        drill, (entry,) = _in_progress_drill_with_entries(ctx)
        account_entry(entry["id"])

        resp = api.release_roster_entry(
            entry["id"],
            {"guardian_name": "Jane Doe", "released_to_verified": False},
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PICKUP_NOT_VERIFIED)

        current = get_roster_entry(drill["id"], entry["id"])
        assert current["status"] == "ACCOUNTED", (
            "An unverified release must leave the entry ACCOUNTED")

    def test_accommodation_gate_blocks_then_allows(self, api, officer_headers):
        """PRD: "When `accommodation_required` is `true`, an **AccommodationPlan** in `ACTIVE` status must exist for that site and student; absence of one is rejected with `ERR_ACCOMMODATION_MISSING`. Each new roster entry begins in `UNACCOUNTED` status, and the drill's roster counters recompute."
        PRD: "The plan begins in `ACTIVE` status."

        Design: Corner/validations/accommodation_gate_blocks_then_allows
        """
        ctx = setup_active_eop_site(site_name="Cedar Grove High",
                                    enrollment_count=1200)
        site_id = ctx["site"]["id"]
        drill = schedule_drill(site_id, scheduled_date="2026-09-15")
        start_drill_on(drill["id"], "2026-09-15", "09:00")

        blocked = api.add_roster_entry(
            drill["id"],
            create_roster_entry_payload(student_ref="stu-7",
                                        accommodation_required=True),
            officer_headers,
        )
        validate_error(blocked, ApiErrorId.ERR_ACCOMMODATION_MISSING)

        plan = create_accommodation_plan(site_id, student_ref="stu-7")
        assert plan["status"] == "ACTIVE"

        allowed = api.add_roster_entry(
            drill["id"],
            create_roster_entry_payload(student_ref="stu-7",
                                        accommodation_required=True),
            officer_headers,
        )
        entry = validate_success(allowed, 201)
        assert entry["status"] == "UNACCOUNTED"

        current = get_drill(drill["id"])
        assert current["roster_total"] == 1

    def test_state_gate_beats_safety_gate_on_roster_add_error(
            self, api, officer_headers):
        """PRD: "When multiple validation rules apply to a single request, the system evaluates them in a strict priority order, and the first failing rule determines the error response."
        PRD: "(5) state validity — the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE`; (6) safety gates — active-EOP, accommodation-plan, pickup-verification, and roster-completeness gates, each with its own error ID"
        PRD: "While a drill is `SCHEDULED` or `IN_PROGRESS`, the officer builds its accountability roster."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_roster_add
        """
        ctx = setup_active_eop_site()
        drill = run_completed_drill(ctx["site"]["id"],
                                    scheduled_date="2026-09-15")
        assert drill["status"] == "COMPLETED"

        # No AccommodationPlan exists for stu-9, so priority 6 would also
        # fail — but the priority-5 state violation must be reported first.
        resp = api.add_roster_entry(
            drill["id"],
            create_roster_entry_payload(student_ref="stu-9",
                                        accommodation_required=True),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_gate_beats_safety_gate_on_roster_add_no_entry(
            self, api, officer_headers):
        """PRD: "While a drill is `SCHEDULED` or `IN_PROGRESS`, the officer builds its accountability roster. Adding a **RosterEntry** to a drill requires the `student_ref` — an opaque student identifier used by the school — and an optional `accommodation_required` flag that defaults to `false`."
        PRD: "(5) state validity — the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE`; (6) safety gates — active-EOP, accommodation-plan, pickup-verification, and roster-completeness gates, each with its own error ID"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_roster_add
        """
        ctx = setup_active_eop_site()
        drill = run_completed_drill(ctx["site"]["id"],
                                    scheduled_date="2026-09-15")

        resp = api.add_roster_entry(
            drill["id"],
            create_roster_entry_payload(student_ref="stu-9",
                                        accommodation_required=True),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_drill(drill["id"])
        assert current["roster_total"] == 0, (
            "The rejected roster add must not persist any entry")


class TestReleaseTerminal:
    def test_release_twice_returns_invalid_state(self, api, officer_headers):
        """PRD: "The reunification release moves an entry from `ACCOUNTED` to `RELEASED` — the terminal roster state."
        PRD: "(5) state validity — the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE`"

        Design: Corner/state_machines/release_twice_returns_invalid_state
        """
        ctx = setup_active_eop_site()
        drill, (entry,) = _in_progress_drill_with_entries(ctx)
        account_entry(entry["id"])
        release_entry(entry["id"], guardian_name="Jane Doe",
                      released_to_verified=True)

        resp = api.release_roster_entry(
            entry["id"],
            {"guardian_name": "Jane Doe", "released_to_verified": True},
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_roster_entry(drill["id"], entry["id"])
        assert current["status"] == "RELEASED"
        drill_now = get_drill(drill["id"])
        assert drill_now["released_count"] == 1


class TestRosterHeadcountConservation:
    def test_roster_counters_after_account_release_unaccount(self, api):
        """PRD: "`roster_total` counts all roster entries for the drill. `unaccounted_count`, `accounted_count`, and `released_count` count entries in `UNACCOUNTED`, `ACCOUNTED`, and `RELEASED` respectively. The invariant `unaccounted_count` plus `accounted_count` plus `released_count` always equals `roster_total` holds at all times."

        Design: Difficulty/compensating_invariant/roster_headcount_conservation
        """
        ctx = setup_active_eop_site()
        drill, (e1, e2) = _in_progress_drill_with_entries(
            ctx, student_refs=("stu-1", "stu-2"))

        account_entry(e1["id"])
        account_entry(e2["id"])
        release_entry(e1["id"], guardian_name="Jane Doe",
                      released_to_verified=True)
        unaccount_entry(e2["id"])

        current = get_drill(drill["id"])
        assert current["roster_total"] == 2
        assert current["unaccounted_count"] == 1, (
            "stu-2's compensating unaccount returns it to UNACCOUNTED")
        assert current["accounted_count"] == 0
        assert current["released_count"] == 1
        assert_roster_counters_invariant(current)

    def test_compensating_unaccount_clears_accounted_at(self, api):
        """PRD: "An account followed by its compensating unaccount returns every bucket to its prior value — `accounted_at` is cleared and no count drifts."
        PRD: "If a mark was made in error, the officer may undo it: unaccounting moves the entry from `ACCOUNTED` back to `UNACCOUNTED` and clears `accounted_at`, with the counters recomputing."

        Design: Difficulty/compensating_invariant/roster_headcount_conservation
        """
        ctx = setup_active_eop_site()
        drill, (e1, e2) = _in_progress_drill_with_entries(
            ctx, student_refs=("stu-1", "stu-2"))

        account_entry(e1["id"])
        account_entry(e2["id"])
        release_entry(e1["id"], guardian_name="Jane Doe",
                      released_to_verified=True)
        unaccounted = unaccount_entry(e2["id"])
        assert unaccounted["status"] == "UNACCOUNTED"

        current = get_roster_entry(drill["id"], e2["id"])
        assert current.get("accounted_at") in (None, ""), (
            f"accounted_at must be cleared by the compensating unaccount, "
            f"got {current.get('accounted_at')!r}")
        released_entry = get_roster_entry(drill["id"], e1["id"])
        assert released_entry["status"] == "RELEASED"
