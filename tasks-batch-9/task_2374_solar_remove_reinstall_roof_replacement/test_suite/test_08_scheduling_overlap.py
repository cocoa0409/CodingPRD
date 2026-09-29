"""Scheduling-resource contention tests for the Solar Reroof Coordination API.

Two different contended resources with deliberately opposite interval semantics:
the per-party crew calendar, whose intervals are inflated by the party's
symmetric mobilization buffer, and the jurisdiction's per-date inspection quota,
which counts bookings and ignores window geometry entirely.
"""

from test_helpers import (
    COORD,
    api_client,
    add_window,
    book_inspection,
    collect_all_consents,
    create_core_parties,
    create_jurisdiction,
    create_project,
    create_work_window_payload,
    get_success_data,
    record_result,
    refresh_project,
    set_clock,
    submit_permit,
    create_permit,
    validate_error,
    validate_success,
)

HOST_OWNED_PROJECT = {
    "site_address": "77 Ocotillo Ln, Chandler AZ",
    "system_dc_kw": 6.0,
    "baseline_daily_kwh": 30.0,
    "downtime_days_estimated": 4,
    "upgrade_budget_cents": 2_000_000,
}


def _setup_roofer_window_with_ninety_minute_buffer() -> dict:
    """A consented HOST_OWNED project with one SCHEDULED 08:00-12:00 roofing window.

    The roofer party carries a 90-minute mobilization buffer; the solar
    contractor keeps the default.
    """
    set_clock("2026-08-01T00:00:00Z")
    parties = create_core_parties(roofer={"mobilization_buffer_minutes": 90})
    project = create_project(parties, ownership_model="HOST_OWNED", **HOST_OWNED_PROJECT)
    collect_all_consents(project, parties)
    base_window = add_window(
        project["id"],
        parties["roofer"]["id"],
        trade="ROOFING",
        start_utc="2026-08-05T08:00:00Z",
        end_utc="2026-08-05T12:00:00Z",
    )
    return {
        "parties": parties,
        "project": refresh_project(project["id"]),
        "base_window": base_window,
    }


def _setup_two_projects_sharing_one_jurisdiction() -> dict:
    """Two HOST_OWNED projects, each with its own SUBMITTED permit in TWINPEAKS.

    TWINPEAKS accepts two inspections per calendar date across every permit it
    governs, and its one-day backlog floor puts 2026-08-12 comfortably in range
    of a 2026-08-10 clock.
    """
    set_clock("2026-08-10T00:00:00Z")
    jurisdiction = create_jurisdiction(
        name="Twin Peaks AHJ",
        code="TWINPEAKS",
        repermit_required_for_reinstall=False,
        reinspection_required=True,
        inspection_slots_per_day=2,
        backlog_days=1,
        permit_review_days=7,
    )
    parties = create_core_parties()
    project_1 = create_project(
        parties, ownership_model="HOST_OWNED", **HOST_OWNED_PROJECT
    )
    project_2 = create_project(
        parties,
        ownership_model="HOST_OWNED",
        site_address="912 Saguaro Rd, Mesa AZ",
        system_dc_kw=5.2,
        baseline_daily_kwh=26.0,
        downtime_days_estimated=3,
        upgrade_budget_cents=1_500_000,
    )

    permit_1 = create_permit(project_1["id"], jurisdiction["id"], scope="REINSTALL_ONLY")
    submit_permit(permit_1["id"])
    permit_2 = create_permit(project_2["id"], jurisdiction["id"], scope="REINSTALL_ONLY")
    submit_permit(permit_2["id"])

    return {
        "jurisdiction": jurisdiction,
        "parties": parties,
        "project_1": project_1,
        "project_2": project_2,
        "permit_1": permit_1,
        "permit_2": permit_2,
    }


# --------------------------------------------------------------------------
# The per-party crew calendar
# --------------------------------------------------------------------------
class TestCrewCalendarBufferedOverlap:
    def test_window_starting_exactly_at_the_existing_end_conflicts(self):
        """Exact adjacency at 12:00:00Z is a conflict because the buffer is positive.

        PRD §3.3: "Comparisons are at second resolution and both are strict, which pins two consequences deliberately: whenever the buffer is greater than zero, exact adjacency (a candidate starting precisely at an existing window's `end_utc`) **is** a conflict, and the earliest legal start is the existing window's `end_utc` plus the buffer, which is itself accepted."

        Design: Difficulty/resource_temporal_overlap/crew_party_buffer_makes_adjacent_window_conflict_but_same_slot_on_another_party_legal
        """
        ctx = _setup_roofer_window_with_ninety_minute_buffer()
        project_id = ctx["project"]["id"]
        roofer_id = ctx["parties"]["roofer"]["id"]

        payload = create_work_window_payload(
            project_id,
            roofer_id,
            trade="ROOFING",
            start_utc="2026-08-05T12:00:00Z",
            end_utc="2026-08-05T16:00:00Z",
        )
        response = api_client.create_work_window(payload, COORD)
        validate_error(response, "ERR_CREW_WINDOW_CONFLICT")

        base = get_success_data(
            api_client.get_work_window(ctx["base_window"]["id"], COORD)
        )
        assert base["status"] == "SCHEDULED", (
            f"the incumbent window is untouched, got {base['status']}"
        )

    def test_window_starting_exactly_at_end_plus_buffer_is_accepted(self):
        """13:30:00Z — the existing end plus the 90-minute buffer — is the earliest legal start.

        PRD §3.3: "Comparisons are at second resolution and both are strict, which pins two consequences deliberately: whenever the buffer is greater than zero, exact adjacency (a candidate starting precisely at an existing window's `end_utc`) **is** a conflict, and the earliest legal start is the existing window's `end_utc` plus the buffer, which is itself accepted."

        Design: Difficulty/resource_temporal_overlap/crew_party_buffer_makes_adjacent_window_conflict_but_same_slot_on_another_party_legal
        """
        ctx = _setup_roofer_window_with_ninety_minute_buffer()
        project_id = ctx["project"]["id"]
        roofer_id = ctx["parties"]["roofer"]["id"]

        payload = create_work_window_payload(
            project_id,
            roofer_id,
            trade="ROOFING",
            start_utc="2026-08-05T13:30:00Z",
            end_utc="2026-08-05T17:00:00Z",
        )
        created = validate_success(api_client.create_work_window(payload, COORD), 201)

        assert created["status"] == "SCHEDULED", (
            f"the earliest legal start is accepted, got {created['status']}"
        )
        assert created["start_utc"] == "2026-08-05T13:30:00.000Z", (
            f"the requested start is preserved, got {created['start_utc']}"
        )

    def test_the_refused_interval_is_legal_on_a_different_party(self):
        """The very interval refused on the roofer is accepted on the solar contractor.

        PRD §3.3: "Windows in `COMPLETED`, `WEATHER_ABORTED`, `SUPERSEDED` or `REVOKED` are excluded from the check — those states release the party's interval — and windows belonging to a different party never conflict."

        Design: Difficulty/resource_temporal_overlap/crew_party_buffer_makes_adjacent_window_conflict_but_same_slot_on_another_party_legal
        """
        ctx = _setup_roofer_window_with_ninety_minute_buffer()
        project_id = ctx["project"]["id"]
        roofer_id = ctx["parties"]["roofer"]["id"]
        crew_id = ctx["parties"]["crew"]["id"]

        refused = api_client.create_work_window(
            create_work_window_payload(
                project_id,
                roofer_id,
                trade="ROOFING",
                start_utc="2026-08-05T12:00:00Z",
                end_utc="2026-08-05T16:00:00Z",
            ),
            COORD,
        )
        validate_error(refused, "ERR_CREW_WINDOW_CONFLICT")

        other = add_window(
            project_id,
            crew_id,
            trade="SOLAR_REMOVAL",
            start_utc="2026-08-05T12:00:00Z",
            end_utc="2026-08-05T16:00:00Z",
        )

        assert other["status"] == "SCHEDULED", (
            f"another party's calendar is a different resource, got {other['status']}"
        )
        assert other["party_id"] == crew_id, (
            f"the window belongs to the solar contractor, got {other['party_id']}"
        )
        project = refresh_project(project_id)
        assert project["weather_abort_count"] == 0, (
            f"no window was aborted, got {project['weather_abort_count']}"
        )


# --------------------------------------------------------------------------
# The jurisdiction's per-date inspection quota
# --------------------------------------------------------------------------
class TestJurisdictionDayQuota:
    def test_quota_is_pooled_across_projects_and_ignores_window_geometry(self):
        """Two touching windows on two projects fill the quota; a third booking is refused.

        PRD §3.7: "Aggregate day capacity comes second, and it is scoped to the **jurisdiction**, not to the project: count every inspection booked under any permit application governed by the same jurisdiction whose `slot_date` equals the candidate's `slot_date` and whose `status` is `SCHEDULED` or `CORRECTION_REQUIRED`; when that count has already reached the jurisdiction's `inspection_slots_per_day`, the booking is refused with `ERR_INSPECTION_SLOT_FULL` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/jurisdiction_day_quota_counts_across_projects_and_a_passed_inspection_frees_the_slot
        """
        ctx = _setup_two_projects_sharing_one_jurisdiction()
        permit_1_id = ctx["permit_1"]["id"]
        permit_2_id = ctx["permit_2"]["id"]

        first = book_inspection(
            permit_1_id,
            inspection_type="ROOF_DECK",
            slot_date="2026-08-12",
            window_start_utc="2026-08-12T08:00:00Z",
            window_end_utc="2026-08-12T12:00:00Z",
        )
        second = book_inspection(
            permit_2_id,
            inspection_type="ROOF_DECK",
            slot_date="2026-08-12",
            window_start_utc="2026-08-12T12:00:00Z",
            window_end_utc="2026-08-12T16:00:00Z",
        )

        assert first["status"] == "SCHEDULED", (
            f"the first booking is SCHEDULED, got {first['status']}"
        )
        assert second["status"] == "SCHEDULED", (
            "windows that merely touch at an endpoint are both legal, got "
            f"{second['status']}"
        )

        response = api_client.create_inspection(
            permit_1_id,
            {
                "inspection_type": "MOUNTING",
                "slot_date": "2026-08-12",
                "window_start_utc": "2026-08-12T18:00:00Z",
                "window_end_utc": "2026-08-12T20:00:00Z",
            },
            COORD,
        )
        validate_error(response, "ERR_INSPECTION_SLOT_FULL")

    def test_passing_an_inspection_frees_the_slot_for_the_refused_booking(self):
        """A PASSED inspection releases its slot, so the previously refused booking succeeds.

        PRD §3.7: "`PASS` additionally requires the parent application's `status` to still be `SUBMITTED` or `APPROVED`; it sets `status` to `PASSED`, releases the jurisdiction's slot for that `slot_date`, and, when the inspection's `inspection_type` is `ELECTRICAL_FINAL`, evaluates the project's `REINSTALL → COMMISSIONED` advance."

        Design: Difficulty/resource_temporal_overlap/jurisdiction_day_quota_counts_across_projects_and_a_passed_inspection_frees_the_slot
        """
        ctx = _setup_two_projects_sharing_one_jurisdiction()
        jurisdiction_id = ctx["jurisdiction"]["id"]
        permit_1_id = ctx["permit_1"]["id"]
        permit_2_id = ctx["permit_2"]["id"]

        first = book_inspection(
            permit_1_id,
            inspection_type="ROOF_DECK",
            slot_date="2026-08-12",
            window_start_utc="2026-08-12T08:00:00Z",
            window_end_utc="2026-08-12T12:00:00Z",
        )
        book_inspection(
            permit_2_id,
            inspection_type="ROOF_DECK",
            slot_date="2026-08-12",
            window_start_utc="2026-08-12T12:00:00Z",
            window_end_utc="2026-08-12T16:00:00Z",
        )

        refused = api_client.create_inspection(
            permit_1_id,
            {
                "inspection_type": "MOUNTING",
                "slot_date": "2026-08-12",
                "window_start_utc": "2026-08-12T18:00:00Z",
                "window_end_utc": "2026-08-12T20:00:00Z",
            },
            COORD,
        )
        validate_error(refused, "ERR_INSPECTION_SLOT_FULL")

        passed = record_result(
            first["id"], jurisdiction_id, "PASS", result_note="Deck approved"
        )
        assert passed["status"] == "PASSED", (
            f"the inspector's PASS is recorded, got {passed['status']}"
        )
        assert passed["inspected_at"] == "2026-08-10T00:00:00.000Z", (
            f"inspected_at is the logical clock reading, got {passed['inspected_at']}"
        )

        rebooked = book_inspection(
            permit_1_id,
            inspection_type="MOUNTING",
            slot_date="2026-08-12",
            window_start_utc="2026-08-12T18:00:00Z",
            window_end_utc="2026-08-12T20:00:00Z",
        )
        assert rebooked["status"] == "SCHEDULED", (
            f"the freed slot admits the booking, got {rebooked['status']}"
        )
        assert rebooked["slot_date"] == "2026-08-12", (
            f"the booking lands on the same date, got {rebooked['slot_date']}"
        )
        assert rebooked["attempt_number"] == 1, (
            f"a fresh booking is attempt 1, got {rebooked['attempt_number']}"
        )
