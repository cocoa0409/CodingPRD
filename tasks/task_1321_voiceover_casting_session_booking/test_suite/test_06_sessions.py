"""Session booking: project-state dependency, patch capability, pickup
prerequisite, temporal preconditions, overlap discipline, and session fees."""
from test_helpers import (
    ApiErrorId,
    create_cast_project,
    create_casting_project,
    create_client,
    create_project,
    create_session,
    create_session_payload,
    create_studio,
    create_talent,
    list_project_invoices,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_delivery_payload
from test_helpers.fixtures import CD, ENGINEER, confirm_session


class TestSessionProjectStateDependency:
    def test_session_create_on_casting_project_rejected(self, api):
        """PRD §3.6: "Once a project is in `CAST`, a `CastingDirector`
        schedules sessions under it. Creating a session against a project in
        any other state is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/session_create_depends_on_project_cast
        """
        ctx = create_casting_project()
        studio = create_studio()
        resp = api.create_session(ctx["project"]["id"],
                                  create_session_payload(studio["id"]), CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_session_create_on_draft_project_rejected(self, api):
        """PRD §3.6: "Once a project is in `CAST`, a `CastingDirector`
        schedules sessions under it. Creating a session against a project in
        any other state is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/session_create_depends_on_project_cast
        """
        client = create_client()
        project = create_project(client)  # stays DRAFT
        studio = create_studio()
        resp = api.create_session(project["id"],
                                  create_session_payload(studio["id"]), CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSessionCreationGuards:
    def test_directed_patch_unsupported_returns_patch_error(self, api):
        """PRD §3.6: "A session requesting `directed_patch` may only be placed
        in a studio whose `has_directed_patch` is true; otherwise creation is
        rejected with `ERR_PATCH_NOT_SUPPORTED` (HTTP 422)."

        Design: Corner/validations/directed_patch_unsupported_returns_patch_error
        """
        ctx = create_cast_project()
        studio = create_studio(has_directed_patch=False)
        resp = api.create_session(
            ctx["project"]["id"],
            create_session_payload(studio["id"], directed_patch=True),
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_PATCH_NOT_SUPPORTED)

    def test_pickup_without_completed_primary_returns_pickup_prerequisite(self, api):
        """PRD §3.6: "confirming a `PICKUP` session requires the project to
        already have at least one `COMPLETED` `PRIMARY` session ... either
        failure is rejected with `ERR_PICKUP_PREREQUISITE` (HTTP 422)."

        Design: Corner/validations/pickup_without_completed_primary_returns_pickup_prerequisite
        """
        ctx = create_cast_project()
        studio = create_studio()
        session = create_session(ctx["project"]["id"], studio,
                                 session_kind="PICKUP",
                                 start_at="2026-08-02T10:00:00Z",
                                 duration_minutes=30)
        resp = api.confirm_session(session["id"], CD)
        validate_error(resp, ApiErrorId.ERR_PICKUP_PREREQUISITE)


class TestSessionTemporalPreconditions:
    def test_session_complete_before_end_at_returns_temporal_violation(self, api):
        """PRD §3.6: "A session — whether still `TENTATIVE` or already
        `CONFIRMED` — is marked `COMPLETED` by a `StudioEngineer` once the
        clock has reached or passed its `end_at`; completing earlier is
        rejected with `ERR_TEMPORAL_VIOLATION`."

        Design: Corner/state_machines/session_complete_before_end_at_returns_temporal_violation
        """
        ctx = create_cast_project()
        studio = create_studio()
        session = create_session(ctx["project"]["id"], studio)
        confirm_session(session["id"])
        set_clock("2026-08-02T10:30:00Z")  # end_at is 11:00 — too early
        resp = api.complete_session(session["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION)

    def test_session_cancel_after_start_at_returns_temporal_violation(self, api):
        """PRD §3.6: "a `CastingDirector` may cancel a `TENTATIVE` or
        `CONFIRMED` session only while the clock is still strictly before its
        `start_at`; cancelling at or after the start is rejected with
        `ERR_TEMPORAL_VIOLATION`."

        Design: Corner/state_machines/session_cancel_after_start_at_returns_temporal_violation
        """
        ctx = create_cast_project()
        studio = create_studio()
        session = create_session(ctx["project"]["id"], studio)  # TENTATIVE
        set_clock("2026-08-02T10:30:00Z")  # start_at 10:00 already passed
        resp = api.cancel_session(session["id"], CD)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION)


class TestStudioOverlap:
    def _setup_three_cast_projects_one_studio(self):
        client = create_client()
        talents = [create_talent() for _ in range(3)]
        studio = create_studio()
        projects = []
        for i, t in enumerate(talents):
            ctx = create_cast_project(client=client, talent=t)
            projects.append(ctx["project"])
        return client, talents, studio, projects

    def test_adjacent_sessions_do_not_collide(self, api):
        """PRD §2.9: "Adjacency is not a collision: when one session's `end_at`
        equals another's `start_at`, both may stand — the buffer between
        sessions is zero."

        Design: Difficulty/resource_temporal_overlap/studio_overlap_half_open_interval
        """
        _, _, studio, projects = self._setup_three_cast_projects_one_studio()
        s1 = create_session(projects[0]["id"], studio,
                            start_at="2026-08-02T10:00:00Z", duration_minutes=60)
        s2 = create_session(projects[1]["id"], studio,
                            start_at="2026-08-02T11:00:00Z", duration_minutes=60)
        confirm_session(s1["id"])
        resp = api.confirm_session(s2["id"], CD)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONFIRMED"

    def test_one_minute_overlap_on_same_studio_rejected_at_confirm(self, api):
        """PRD §2.9: "Two sessions collide when the first session's start is
        strictly before the second session's end and the second session's start
        is strictly before the first session's end." PRD §3.6: "the overlap
        check is re-evaluated at confirm time against the same per-studio and
        per-talent `CONFIRMED` sets".

        Design: Difficulty/resource_temporal_overlap/studio_overlap_half_open_interval
        """
        _, _, studio, projects = self._setup_three_cast_projects_one_studio()
        # Create both while nothing is CONFIRMED so creation succeeds for both.
        s1 = create_session(projects[0]["id"], studio,
                            start_at="2026-08-02T10:00:00Z", duration_minutes=60)
        s3 = create_session(projects[2]["id"], studio,
                            start_at="2026-08-02T10:59:00Z", duration_minutes=60)
        confirm_session(s1["id"])  # 10:00-11:00 CONFIRMED
        resp = api.confirm_session(s3["id"], CD)  # 10:59-11:59 overlaps by 1 min
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)


class TestTalentOverlap:
    def _setup_one_talent_two_projects_two_studios(self):
        client = create_client()
        talent = create_talent()
        studio_a = create_studio(studio_name="Studio A")
        studio_b = create_studio(studio_name="Studio B", location="New York",
                                 operating_tz="America/New_York")
        p1 = create_cast_project(client=client, talent=talent,
                                 product_category="TECH")["project"]
        p2 = create_cast_project(client=client, talent=talent,
                                 product_category="RETAIL")["project"]
        return client, talent, studio_a, studio_b, p1, p2

    def test_talent_double_booked_across_studios_rejected_at_confirm(self, api):
        """PRD §3.6: "And the requested interval must not collide with any
        `CONFIRMED` session sharing the same studio or the same talent, under
        the half-open overlap rule of Section 2.9; a collision is rejected with
        `ERR_SESSION_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/talent_overlap_different_resource
        """
        _, _, studio_a, studio_b, p1, p2 = (
            self._setup_one_talent_two_projects_two_studios())
        s1 = create_session(p1["id"], studio_a,
                            start_at="2026-08-02T10:00:00Z", duration_minutes=60)
        s2 = create_session(p2["id"], studio_b,
                            start_at="2026-08-02T10:30:00Z", duration_minutes=60)
        confirm_session(s1["id"])
        resp = api.confirm_session(s2["id"], CD)
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)

    def test_talent_overlap_rejected_at_creation_against_confirmed(self, api):
        """PRD §3.6: "And the requested interval must not collide with any
        `CONFIRMED` session sharing the same studio or the same talent, under
        the half-open overlap rule of Section 2.9; a collision is rejected with
        `ERR_SESSION_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/talent_overlap_different_resource
        """
        _, _, studio_a, studio_b, p1, p2 = (
            self._setup_one_talent_two_projects_two_studios())
        s1 = create_session(p1["id"], studio_a,
                            start_at="2026-08-02T10:00:00Z", duration_minutes=60)
        confirm_session(s1["id"])
        # Created after s1 is CONFIRMED: the same talent is already booked.
        resp = api.create_session(
            p2["id"],
            create_session_payload(studio_b["id"],
                                   start_at="2026-08-02T10:30:00Z",
                                   duration_minutes=60),
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)


class TestSessionFeeFinalVariant:
    def test_final_fee_with_directed_patch_surcharge(self, api):
        """PRD §3.7: "The billed minutes are converted to hours and multiplied
        by the studio's `hourly_rate_cents`. When the session ran with
        `directed_patch`, a 25 percent surcharge is applied to that amount and
        the result is rounded half-up to integer cents." PRD §3.7: "Completing
        a `PRIMARY` or `RETAKE` session defers its `SESSION_FEE` invoice until
        the project is delivered".

        Design: Difficulty/dual_variant_calc/session_fee_provisional_vs_final_on_session
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="UNION", base_session_fee_cents=80000))
        studio = create_studio(has_directed_patch=True, hourly_rate_cents=24000)
        session = create_session(ctx["project"]["id"], studio,
                                 directed_patch=True, duration_minutes=45,
                                 start_at="2026-08-02T10:00:00Z")
        confirm_session(session["id"])
        set_clock("2026-08-02T10:50:00Z")  # 50 minutes elapsed, past end_at 10:45
        resp = api.complete_session(session["id"], ENGINEER)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"

        # PRIMARY defers invoicing until delivery.
        assert list_project_invoices(ctx["project"]["id"]) == []

        # Deliver, then the SESSION_FEE invoice carries the final variant:
        # elapsed 50 -> billed 50; 50/60 * 24000 = 20000; +25% patch = 25000.
        delivery = validate_success(
            api.create_delivery(ctx["project"]["id"],
                                create_delivery_payload(session["id"]), ENGINEER),
            expected_status=201,
        )
        invoices = list_project_invoices(ctx["project"]["id"])
        fee = [i for i in invoices if i["invoice_kind"] == "SESSION_FEE"]
        assert len(fee) == 1, f"expected one SESSION_FEE invoice, got {invoices!r}"
        assert fee[0]["total_cents"] == 25000

    def test_final_fee_without_patch_uses_elapsed_minutes(self, api):
        """PRD §3.7: "The elapsed minutes from `start_at` to the moment
        completion is recorded are rounded up to a 5-minute granularity,
        subject to a 15-minute minimum — a session that ran 12 minutes still
        bills 15." PRD §3.7: "No patch surcharge applies to the provisional
        quote."

        Design: Difficulty/dual_variant_calc/session_fee_provisional_vs_final_on_session
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="UNION", base_session_fee_cents=80000))
        studio = create_studio(has_directed_patch=False, hourly_rate_cents=24000)
        session = create_session(ctx["project"]["id"], studio,
                                 directed_patch=False, duration_minutes=60,
                                 start_at="2026-08-02T10:00:00Z")
        confirm_session(session["id"])
        set_clock("2026-08-02T11:00:00Z")  # == end_at; elapsed exactly 60 minutes
        resp = api.complete_session(session["id"], ENGINEER)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"

        delivery = validate_success(
            api.create_delivery(ctx["project"]["id"],
                                create_delivery_payload(session["id"]), ENGINEER),
            expected_status=201,
        )
        invoices = list_project_invoices(ctx["project"]["id"])
        fee = [i for i in invoices if i["invoice_kind"] == "SESSION_FEE"]
        assert len(fee) == 1
        # elapsed 60 -> billed 60; 60/60 * 24000 = 24000; no patch surcharge.
        assert fee[0]["total_cents"] == 24000
