"""Contract setup, creation defaults, reference integrity, pagination, and the
logical clock (PRD §2.1, §2.3, §2.4, §2.5, §3.1, §3.2)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId,
    assert_project, assert_project_ledger_invariant, assert_disposal_site,
    assert_capacity_invariant, assert_turbidity_reading,
    create_project_payload, create_reach_payload, create_plant_payload,
    create_disposal_site_payload, create_permit_payload,
    create_turbidity_reading_payload,
    set_clock, create_project, add_permit, add_reach,
)


class TestCreationDefaults:
    def test_project_creation_applies_defaults(self, api, owner_headers):
        """PRD §3.1: "A new project is `PLANNED`, its `compliance_posture` is
        `SUSPENDED` because no issued permit governs it yet, and its ledger fields
        `total_certified_cents` and `total_paid_cents` start at zero."

        Design: Corner/entities/project_creation_applies_defaults
        """
        res = api.create_project(create_project_payload(name="P-NEW"), owner_headers)
        project = validate_success(res, 201)
        assert_project(project)
        assert project["status"] == "PLANNED"
        assert project["compliance_posture"] == "SUSPENDED"
        assert project["total_certified_cents"] == 0
        assert project["total_paid_cents"] == 0
        assert_project_ledger_invariant(project)

    def test_disposal_site_used_cy_input_ignored(self, api, owner_headers):
        """PRD §3.1: "A site opens in status `OPEN` with `used_cy` zero and
        `remaining_cy` equal to `capacity_cy`; at all times used plus remaining
        equals capacity exactly."

        Design: Corner/entities/disposal_site_used_cy_input_ignored
        """
        payload = create_disposal_site_payload(
            name="SITE-CI", capacity_cy=5000, bulking_factor=1.3
        )
        payload["used_cy"] = 9999  # not an input field; must be ignored
        res = api.create_disposal_site(payload, owner_headers)
        site = validate_success(res, 201)
        assert_disposal_site(site)
        assert site["used_cy"] == 0
        assert site["remaining_cy"] == 5000
        assert site["status"] == "OPEN"
        assert_capacity_invariant(site)

    def test_turbidity_reading_has_no_version_field(self, api, owner_headers,
                                                    monitor_headers):
        """PRD §2.5: "The exception is the TurbidityReading. A turbidity sample is
        immutable once recorded, so it carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it."

        Design: Corner/entities/turbidity_reading_has_no_version_field
        """
        project = create_project(name="P-IMM")
        add_permit(project["id"])
        res = api.create_turbidity_reading(
            create_turbidity_reading_payload(
                project["id"], value_ntu=30, taken_utc="2026-05-10T08:00:00Z"
            ),
            monitor_headers,
        )
        reading = validate_success(res, 201)
        assert_turbidity_reading(reading)
        assert "id" in reading and "created_at" in reading
        assert "version" not in reading


class TestReferenceIntegrity:
    def test_project_get_not_found_returns_404(self, api, owner_headers):
        """PRD §2.10: "the first identifier that does not correspond to an
        existing resource produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/project_get_not_found_returns_404
        """
        res = api.get_project(NON_EXISTENT_UUID, owner_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_reach_create_with_unknown_project_returns_not_found(
        self, api, owner_headers
    ):
        """PRD §2.10: "Existence checking is still strictly ordered — path
        identifiers first, left to right, then the foreign-key identifiers in the
        request body — and the first identifier that does not correspond to an
        existing resource produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/reach_create_with_unknown_project_returns_not_found
        """
        res = api.create_reach(
            create_reach_payload(NON_EXISTENT_UUID), owner_headers
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestRequestShape:
    def test_reach_create_missing_required_field_returns_invalid_request(
        self, api, owner_headers
    ):
        """PRD §2.9: "required fields present, enum members valid, numeric
        bounds honored (strictly positive or non-negative as each field
        specifies), end-after-start ordering on every time interval, resolvable
        array elements, `override_note` present where required, and the clock
        never moving backwards; violations yield `ERR_INVALID_REQUEST` (HTTP
        400)."

        Design: Corner/entities/reach_create_missing_required_field_returns_invalid_request
        """
        project = create_project(name="P-RF")
        payload = create_reach_payload(project["id"])
        del payload["design_quantity_cy"]
        res = api.create_reach(payload, owner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_plant_create_with_invalid_enum_rejected(self, api, contractor_headers):
        """PRD §3.3: "a `plant_type` of `CUTTER_SUCTION`, `HOPPER`, `CLAMSHELL`,
        or `BACKHOE`"; PRD §2.9: "required fields present, enum members valid,
        numeric bounds honored (strictly positive or non-negative as each field
        specifies), end-after-start ordering on every time interval, resolvable
        array elements, `override_note` present where required, and the clock
        never moving backwards; violations yield `ERR_INVALID_REQUEST` (HTTP
        400)."

        Design: Corner/entities/plant_create_with_invalid_enum_rejected
        """
        payload = create_plant_payload(contractor_ref="DGE-X", plant_type="DRAGLINE")
        res = api.create_plant(payload, contractor_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestPagination:
    def test_list_reaches_pagination_envelope(self, api, owner_headers,
                                              contractor_headers):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its
        resources sorted by `created_at` in ascending order."

        Design: Corner/entities/list_reaches_pagination_envelope
        """
        project = create_project(name="P-PG")
        r1 = add_reach(project["id"], name="R1")
        r2 = add_reach(project["id"], name="R2", design_quantity_cy=30000,
                       required_depth_ft=20.0, overdepth_allowance_cy=1000)

        res = api.list_reaches(
            contractor_headers,
            params={"project_id": project["id"], "limit": 1, "offset": 0},
        )
        page1, meta1 = validate_paginated(res)
        assert res.json()["response_type"] == "array"
        body_meta = res.json()["meta"]
        assert "api_request_id" in body_meta
        assert "api_request_timestamp" in body_meta
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(page1) == 1

        res2 = api.list_reaches(
            contractor_headers,
            params={"project_id": project["id"], "limit": 1, "offset": 1},
        )
        page2, meta2 = validate_paginated(res2)
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert {page1[0]["id"], page2[0]["id"]} == {r1["id"], r2["id"]}


class TestLogicalClock:
    def test_clock_backwards_rejected(self, api, owner_headers):
        """PRD §2.4: "The clock is monotonic: any attempt to set it backwards is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/clock_backwards_rejected
        """
        set_clock("2026-05-10T00:00:00Z")
        res = api.set_clock({"to_iso8601": "2026-05-09T00:00:00Z"}, owner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_permit_expires_on_clock_advance(self, api, owner_headers):
        """PRD §2.4: "Each set evaluates permit expiry — any `ISSUED` permit whose
        `window_end_utc` is now in the past transitions to `EXPIRED` — recomputes
        the compliance posture of every project per §2.6"
        PRD §2.6: "If no permit governs — including the case of a project with no
        `ISSUED` permit at all — the posture is `SUSPENDED`."

        Design: Corner/state_machines/permit_expires_on_clock_advance
        """
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-EXP")
        permit = add_permit(
            project["id"], window_end_utc="2026-06-30T23:59:59Z"
        )
        set_clock("2026-07-01T00:00:00Z")
        permit_after = validate_success(api.get_permit(permit["id"], owner_headers))
        assert permit_after["status"] == "EXPIRED"
        project_after = validate_success(api.get_project(project["id"], owner_headers))
        assert project_after["compliance_posture"] == "SUSPENDED"


class TestActivationGate:
    def test_activate_incomplete_rejected(self, api, owner_headers):
        """PRD §3.1: "It is gated on three structures existing at once: at least
        one reach, at least one `ISSUED` permit, and at least one `APPROVED`
        dredge plan; if any is missing, activation fails with
        `ERR_ACTIVATION_INCOMPLETE` (HTTP 409)."

        Design: Corner/validations/activate_incomplete_rejected
        """
        project = create_project(name="P-ACT")
        res = api.activate_project(project["id"], owner_headers)
        validate_error(res, ApiErrorId.ERR_ACTIVATION_INCOMPLETE, expected_status=409)
        project_after = validate_success(api.get_project(project["id"], owner_headers))
        assert project_after["status"] == "PLANNED"


class TestPermitWindowDiscipline:
    def test_permit_window_touching_endpoint_conflicts(self, api, owner_headers):
        """PRD §3.2: "A new permit whose window touches an existing issued window
        even at a single endpoint conflicts, and the create is rejected with
        `ERR_PERMIT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/permit_windows_closed_interval_touching_conflicts
        """
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-OVR")
        add_permit(project["id"], permit_number="PER-1",
                   window_start_utc="2026-05-01T00:00:00Z",
                   window_end_utc="2026-06-30T23:59:59Z")
        # Touching the inclusive end: starts exactly at PER-1's window_end_utc.
        res = api.create_permit(
            create_permit_payload(
                project["id"], permit_number="PER-2",
                window_start_utc="2026-06-30T23:59:59Z",
                window_end_utc="2026-07-31T23:59:59Z",
                turbidity_limit_ntu=60, turbidity_ceiling_ntu=120,
                species_standdown_hours=4,
            ),
            owner_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERMIT_WINDOW_OVERLAP,
                       expected_status=409)

    def test_permit_window_strict_gap_allowed(self, api, owner_headers):
        """PRD §3.2: "Permit windows are closed intervals — an instant exactly on
        `window_start_utc` or `window_end_utc` is inside the window — and the
        windows of two `ISSUED` permits on the same project may not share any
        instant."

        Design: Difficulty/resource_temporal_overlap/permit_windows_closed_interval_touching_conflicts
        """
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-OVR2")
        add_permit(project["id"], permit_number="PER-1",
                   window_start_utc="2026-05-01T00:00:00Z",
                   window_end_utc="2026-06-30T23:59:59Z")
        # One second strictly after the inclusive end: no shared instant.
        res = api.create_permit(
            create_permit_payload(
                project["id"], permit_number="PER-3",
                window_start_utc="2026-07-01T00:00:00Z",
                window_end_utc="2026-08-31T23:59:59Z",
                turbidity_limit_ntu=60, turbidity_ceiling_ntu=120,
                species_standdown_hours=4,
            ),
            owner_headers,
        )
        permit3 = validate_success(res, 201)
        assert permit3["status"] == "ISSUED"
