"""Daily huddles and job hazard analyses: conduct side effects, the MISSED
sweep, per-date uniqueness, and the conducted-huddle gate behind JHA approval
(PRD §3.3)."""
from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success,
    create_project, create_project_with_active_plan, create_oriented_worker,
    create_huddle, conduct_huddle, get_huddle, create_jha, get_jha,
    set_clock,
    make_safety_manager_headers, make_site_superintendent_headers,
)

SM = make_safety_manager_headers()
SS = make_site_superintendent_headers()


class TestHuddleConduct:

    def test_conduct_huddle_records_attendance(self, api):
        """PRD §3.3: "A successful conduct stamps `conducted_at`, stores the
        submitted attendance list, and moves the huddle to `CONDUCTED`."

        Design: Corner/state_machines/huddle_conduct_to_conducted_and_attendance
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Dockside", location="Tacoma", annual_hours_worked=45000
        )
        worker = create_oriented_worker(project["id"], full_name="P Quinn")
        huddle = create_huddle(project["id"], huddle_date="2026-08-01",
                               topics="lift plan")

        data = validate_success(
            api.conduct_huddle(huddle["id"],
                               {"attendee_worker_ids": [worker["id"]]}, SS),
            200,
        )
        assert data["status"] == "CONDUCTED"
        assert data["attendee_worker_ids"] == [worker["id"]], (
            f"attendance list must be stored, got {data['attendee_worker_ids']}"
        )
        # conducted_at is stamped from the logical clock (PRD §2.5).
        assert data["conducted_at"] is not None
        assert data["conducted_at"].startswith("2026-08-01T08:00:00"), (
            f"conducted_at must reflect the logical clock, got {data['conducted_at']}"
        )

    def test_unconducted_huddle_flips_to_missed_on_sweep(self, api):
        """PRD §3.3: "if the huddle is never conducted, the clock sweep moves it
        from `SCHEDULED` to `MISSED` once the huddle date has fully elapsed — that
        is, once the current time is later than one day after `huddle_date`."
        PRD §3.3: "Conducting a huddle that is no longer `SCHEDULED` fails with
        `ERR_HUDDLE_INVALID_STATE`"

        Design: Corner/calculations/huddle_missed_auto_transition_on_sweep
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Wallingford", annual_hours_worked=15000)
        huddle = create_huddle(project["id"], huddle_date="2026-08-02",
                               topics="crane pick")

        # Advance the clock to two days after the huddle date: unambiguously
        # later than one day after 2026-08-02, so the date has fully elapsed.
        set_clock("2026-08-04T00:00:00Z")
        after = get_huddle(huddle["id"])
        assert after["status"] == "MISSED", (
            f"huddle must flip to MISSED on the sweep, got {after['status']}"
        )

        resp = api.conduct_huddle(huddle["id"], {"attendee_worker_ids": []}, SS)
        validate_error(resp, ApiErrorId.ERR_HUDDLE_INVALID_STATE)

    def test_duplicate_huddle_date_rejected(self, api):
        """PRD §3.3: "Only one huddle may exist per project per date: a second
        huddle for the same `project_id` and `huddle_date` is rejected with
        `ERR_HUDDLE_ALREADY_EXISTS`."

        Design: Corner/validations/huddle_duplicate_date_rejected
        """
        project = create_project(name="Bitter Lake", annual_hours_worked=22000)
        create_huddle(project["id"], huddle_date="2026-08-05", topics="morning plan")
        resp = api.create_huddle(
            {"project_id": project["id"], "huddle_date": "2026-08-05",
             "topics": "duplicate"}, SS,
        )
        validate_error(resp, ApiErrorId.ERR_HUDDLE_ALREADY_EXISTS)


class TestJhaApprovalGate:

    def test_jha_approve_requires_conducted_huddle(self, api):
        """PRD §3.3: "the JHA must be in `DRAFT` or `RE_REVIEW_REQUIRED` (else
        `ERR_JHA_INVALID_STATE`), and the linked huddle must be `CONDUCTED` (else
        `ERR_HUDDLE_NOT_CONDUCTED`) — hazards reviewed only at a huddle that
        actually happened."

        Design: Corner/errors/jha_approve_with_unconducted_huddle_rejected
        """
        project = create_project(name="West Edge", annual_hours_worked=14000)
        huddle = create_huddle(project["id"], huddle_date="2026-08-02", topics="demo")
        jha = create_jha(project["id"], huddle["id"], task_description="demo wall",
                         hazards="dust", controls="water")

        resp = api.approve_jha(jha["id"], {}, SM)
        validate_error(resp, ApiErrorId.ERR_HUDDLE_NOT_CONDUCTED)
        assert get_jha(jha["id"])["status"] == "DRAFT"
