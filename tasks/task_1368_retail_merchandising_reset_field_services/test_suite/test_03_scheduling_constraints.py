"""Scheduling constraints: store-list uniqueness, billing-model resolution,
workforce classification, cross-entity ownership, temporal sanity, rep
double-booking (half-open intervals), ON_SITE occupancy, and store-row state
gating of assignment creation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_project_store,
    create_client,
    create_project,
    create_rep,
    create_store,
    get_project,
    make_field_rep_headers,
    make_scenario,
    schedule_assignment,
    scope_project,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    visit_store,
)

PM = TEST_USERS["pm_headers"]


class TestStoreListUniqueness:
    def test_duplicate_store_rejected(self, api):
        """PRD 3.2: "The list rejects duplicates: the same store may not appear
        twice on one project among rows that are not `DROPPED`, and such an
        attempt is rejected with `ERR_DUPLICATE_STORE` (HTTP 409)."

        Design: Corner/validations/duplicate_store_rejected
        """
        client = create_client(name="Dup Client")
        store = create_store()
        project = create_project(client["id"], title="Dup Proj")
        add_project_store(project["id"], store["id"])
        resp = api.create_project_store(
            {
                "project_id": project["id"],
                "store_id": store["id"],
                "due_date": "2026-08-21",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STORE)


class TestBillingModelResolution:
    def test_scope_without_any_billing_model_rejected(self, api):
        """PRD 3.2: "Resolution takes the project's own `billing_model`
        override when set, otherwise the client's default `billing_model`; if
        neither is set, or if the resolved model's required rate is missing
        from the client (`hourly_rate_cents` for an hourly project,
        `per_store_rate_cents` for a per-store project), scoping is rejected
        with `ERR_BILLING_MODEL_UNRESOLVABLE` (HTTP 422)."

        Design: Corner/validations/billing_model_unresolvable_on_scope
        """
        client = api.create_client({"name": "NoBill Client"}, PM)
        client = validate_success(client, 201)
        project = create_project(client["id"], title="NB Proj")
        store = create_store()
        add_project_store(project["id"], store["id"])
        current = get_project(project["id"])["version"]
        resp = api.scope_project(
            project["id"], {"expected_project_version": current}, PM
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_MODEL_UNRESOLVABLE)


class TestWorkforceClassification:
    def test_c1099_on_fixture_install_forbidden(self, api):
        """PRD 3.3: "Worker classification restricts scope: a `C1099` rep may
        only be assigned to projects whose `scope_type` is not
        `FIXTURE_INSTALL`, because heavy-fixture work requires W-2 employees
        under client compliance rules; a violation is rejected with
        `ERR_CLASSIFICATION_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/classification_forbidden_on_fixture_install
        """
        scn = make_scenario(
            scope_type="FIXTURE_INSTALL",
            rep_overrides_list=[{
                "full_name": "Cls Rep",
                "employment_type": "C1099",
                "mileage_policy": "FIRST_STOP",
            }],
        )
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][0]["id"],
                "rep_id": scn["reps"][0]["id"],
                "scheduled_start": "2026-08-05T09:00:00Z",
                "scheduled_end": "2026-08-05T11:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_FORBIDDEN)


class TestCrossEntityOwnership:
    def test_assignment_store_from_other_project_rejected(self, api):
        """PRD 2.5: "Only after existence is established does the system check
        business referential integrity: the store being scheduled must belong
        to the project named in the same request ... A violation of any of
        these cross-entity ownership rules is rejected with
        `ERR_CROSS_ENTITY_MISMATCH` (HTTP 422)."

        Design: Corner/validations/cross_entity_mismatch_assignment_project_store
        """
        client = create_client(name="XM Client")
        store_a = create_store()
        store_b = create_store()
        proj_1 = create_project(client["id"], title="XM P1")
        proj_2 = create_project(client["id"], title="XM P2")
        ps_of_p1 = add_project_store(proj_1["id"], store_a["id"])
        # Give proj_2 its own store row so proj_2 itself is scopable (scoping
        # requires at least one PENDING store-list row, PRD 3.2).
        add_project_store(proj_2["id"], store_b["id"])
        rep = create_rep()
        scope_project(proj_1["id"])
        scope_project(proj_2["id"])
        resp = api.create_assignment(
            {
                "project_id": proj_2["id"],
                "project_store_id": ps_of_p1["id"],
                "rep_id": rep["id"],
                "scheduled_start": "2026-08-05T09:00:00Z",
                "scheduled_end": "2026-08-05T11:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_MISMATCH)


class TestTemporalSanity:
    def test_zero_length_assignment_window_rejected(self, api):
        """PRD 2.10: "An assignment's `scheduled_end` must be strictly after
        its `scheduled_start`." and "Violations of these temporal rules are
        rejected with `ERR_TEMPORAL_INVALID`."

        Design: Corner/validations/scheduled_end_before_start_rejected
        """
        scn = make_scenario()
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][0]["id"],
                "rep_id": scn["reps"][0]["id"],
                "scheduled_start": "2026-08-05T09:00:00Z",
                "scheduled_end": "2026-08-05T09:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID)


class TestProjectScopeOcc:
    def test_scope_with_stale_project_version_rejected(self, api):
        """PRD 2.8: "If the project's version has advanced since that read —
        because another writer added or dropped store-list rows, changed the
        billing override, or otherwise mutated the project — the scoping
        request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
        PRD 3.2: "Adding a store-list row is a mutation of the project for
        concurrency purposes — it increments the parent project's `version` by
        1 alongside the new row's own creation."

        Design: Corner/errors/error_stale_project_version_triggerable
        """
        client = create_client(name="SV Client")
        project = create_project(client["id"], title="SV Proj")
        stale_version = project["version"]
        store = create_store()
        add_project_store(project["id"], store["id"])  # bumps project version
        resp = api.scope_project(
            project["id"], {"expected_project_version": stale_version}, PM
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)


class TestRepDoubleBooking:
    def test_overlapping_window_same_rep_double_booked(self, api):
        """PRD 3.3: "The rep's calendar must not double-book: the new window
        may not overlap any existing `SCHEDULED`, `EN_ROUTE`, or `ON_SITE`
        assignment of the same rep, using half-open interval semantics in which
        one assignment's end exactly equal to another's start is not an
        overlap; a violation is rejected with `ERR_REP_DOUBLE_BOOKED`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rep_schedule_half_open_overlap
        """
        scn = make_scenario(num_stores=2)
        rep = scn["reps"][0]
        schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"],
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z",
        )
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][1]["id"],
                "rep_id": rep["id"],
                "scheduled_start": "2026-08-05T10:00:00Z",
                "scheduled_end": "2026-08-05T12:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_REP_DOUBLE_BOOKED)

    def test_same_window_different_reps_accepted(self, api):
        """PRD 3.3: "The rep's calendar must not double-book: the new window
        may not overlap any existing `SCHEDULED`, `EN_ROUTE`, or `ON_SITE`
        assignment of the same rep, using half-open interval semantics in which
        one assignment's end exactly equal to another's start is not an
        overlap; a violation is rejected with `ERR_REP_DOUBLE_BOOKED`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rep_schedule_half_open_overlap
        """
        scn = make_scenario(num_stores=2, num_reps=2)
        rep_a, rep_b = scn["reps"]
        window = ("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z")
        schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep_a["id"],
            scheduled_start=window[0], scheduled_end=window[1],
        )
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][1]["id"],
                "rep_id": rep_b["id"],
                "scheduled_start": window[0],
                "scheduled_end": window[1],
            },
            PM,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED", (
            "identical windows on different reps must be accepted"
        )


class TestAdjacentBoundary:
    def test_adjacent_assignment_start_equals_prior_end_accepted(self, api):
        """PRD 3.3: "The rep's calendar must not double-book: the new window
        may not overlap any existing `SCHEDULED`, `EN_ROUTE`, or `ON_SITE`
        assignment of the same rep, using half-open interval semantics in which
        one assignment's end exactly equal to another's start is not an
        overlap; a violation is rejected with `ERR_REP_DOUBLE_BOOKED`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/rep_overlap_adjacent_endpoints_not_overlapping
        """
        scn = make_scenario(num_stores=2)
        rep = scn["reps"][0]
        schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"],
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z",
        )
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][1]["id"],
                "rep_id": rep["id"],
                "scheduled_start": "2026-08-05T11:00:00Z",
                "scheduled_end": "2026-08-05T12:00:00Z",
            },
            PM,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED", (
            "start == prior end is adjacency, not overlap; must be accepted"
        )

    def test_assignment_one_minute_into_prior_window_rejected(self, api):
        """PRD 3.3: "The rep's calendar must not double-book: the new window
        may not overlap any existing `SCHEDULED`, `EN_ROUTE`, or `ON_SITE`
        assignment of the same rep, using half-open interval semantics in which
        one assignment's end exactly equal to another's start is not an
        overlap; a violation is rejected with `ERR_REP_DOUBLE_BOOKED`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/rep_overlap_adjacent_endpoints_not_overlapping
        """
        scn = make_scenario(num_stores=2)
        rep = scn["reps"][0]
        schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"],
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z",
        )
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][1]["id"],
                "rep_id": rep["id"],
                "scheduled_start": "2026-08-05T10:59:00Z",
                "scheduled_end": "2026-08-05T12:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_REP_DOUBLE_BOOKED)


class TestStoreRowStateGating:
    def test_assignment_create_on_completed_store_rejected(self, api):
        """PRD 3.3: "Creation is refused unless the store row is `PENDING` (or
        `REWORK_REQUIRED` on the rework path of §3.5), the project is `SCOPED`
        or `IN_FIELD`, the rep is `ACTIVE`, and no existing assignment for that
        same store row sits in `SCHEDULED`, `EN_ROUTE`, or `ON_SITE`."
        PRD 2.6: "Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_depends_on_project_store_state
        """
        scn = make_scenario()
        visit_store(scn, outcome="verify")  # store row -> COMPLETED
        rep = scn["reps"][0]
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][0]["id"],
                "rep_id": rep["id"],
                "scheduled_start": "2026-08-06T09:00:00Z",
                "scheduled_end": "2026-08-06T11:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_assignment_create_on_dropped_store_rejected(self, api):
        """PRD 3.3: "Creation is refused unless the store row is `PENDING` (or
        `REWORK_REQUIRED` on the rework path of §3.5), the project is `SCOPED`
        or `IN_FIELD`, the rep is `ACTIVE`, and no existing assignment for that
        same store row sits in `SCHEDULED`, `EN_ROUTE`, or `ON_SITE`."
        PRD 2.6: "Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_depends_on_project_store_state
        """
        scn = make_scenario()
        ps = scn["ps_rows"][0]
        resp = api.drop_project_store(ps["id"], PM)
        validate_success(resp)
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": ps["id"],
                "rep_id": scn["reps"][0]["id"],
                "scheduled_start": "2026-08-06T09:00:00Z",
                "scheduled_end": "2026-08-06T11:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSingleOnSiteOccupancy:
    def test_checkin_blocked_while_rep_on_site_elsewhere(self, api):
        """PRD 3.3: "A rep may hold at most one `ON_SITE` assignment at a time
        — check-in while the same rep has another assignment `ON_SITE` is
        rejected as a double-booking violation."
        PRD 2.6: "Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rep_single_on_site_occupancy
        """
        scn = make_scenario(num_stores=2)
        rep = scn["reps"][0]
        asg_1 = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"],
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z",
        )
        asg_2 = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][1]["id"], rep["id"],
            scheduled_start="2026-08-05T12:00:00Z",
            scheduled_end="2026-08-05T13:00:00Z",
        )
        set_clock("2026-08-05T09:05:00Z")
        validate_success(
            api.check_in_assignment(asg_1["id"], make_field_rep_headers(rep["id"])),
            201,
        )
        set_clock("2026-08-05T12:00:00Z")
        resp = api.check_in_assignment(asg_2["id"], make_field_rep_headers(rep["id"]))
        assert resp.status_code == 409, (
            f"check-in while the rep is ON_SITE elsewhere must be 409, "
            f"got {resp.status_code}: {resp.text}"
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_REP_DOUBLE_BOOKED, ApiErrorId.ERR_INVALID_STATE]
        )

    def test_checkin_allowed_after_prior_checkout(self, api):
        """PRD 3.3: "A rep may hold at most one `ON_SITE` assignment at a time
        — check-in while the same rep has another assignment `ON_SITE` is
        rejected as a double-booking violation."

        Design: Difficulty/resource_temporal_overlap/rep_single_on_site_occupancy
        """
        scn = make_scenario(num_stores=2)
        rep = scn["reps"][0]
        asg_1, visit_1 = visit_store(
            scn, store_idx=0,
            window=("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z"),
            on_site=("2026-08-05T09:05:00Z", "2026-08-05T10:00:00Z"),
        )
        asg_2 = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][1]["id"], rep["id"],
            scheduled_start="2026-08-05T12:00:00Z",
            scheduled_end="2026-08-05T13:00:00Z",
        )
        set_clock("2026-08-05T12:00:00Z")
        resp = api.check_in_assignment(asg_2["id"], make_field_rep_headers(rep["id"]))
        visit_2 = validate_success(resp, 201)
        assert visit_2["verification_status"] == "PENDING_REVIEW"
