"""Staff roster defaults, computed task values and ledger-entry immutability."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_maintenance_task,
    assert_staff_member,
    assert_two_decimals,
    assert_usage_ledger_entry,
    assert_version,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

UNUSED_UUID = "11111111-2222-3333-4444-555555555555"


class TestStaffRoster:
    def test_employment_status_defaults_to_active(self, client, roster):
        """The roster row is usable without naming an employment status.

        "`employment_status` is optional and defaults to `ACTIVE`; setting it to
        `INACTIVE` leaves the row readable and referenced by history, but the
        person can no longer act, as §2.1 describes."

        "`roles` must be a non-empty array of distinct values drawn from
        `FieldOperationsCoordinator`, `TurfAgronomist`, `SafetyInspector`,
        `CertificationOfficer` and `FacilitiesDirector`"

        Design: Corner/entities/staff_member_employment_status_defaults_to_active
        """
        created = validate_success(
            client.create_staff_member(
                factories.make_staff_member_payload(
                    full_name="Tobias Lund", roles=["TurfAgronomist"]
                ),
                roster.director_headers,
            ),
            201,
        )
        assert_staff_member(created)
        assert created["employment_status"] == "ACTIVE"
        assert created["roles"] == ["TurfAgronomist"]
        assert_version(created, 1, "StaffMember")

        inactive = validate_success(
            client.create_staff_member(
                factories.make_staff_member_payload(
                    full_name="Selma Aziz",
                    roles=["TurfAgronomist"],
                    employment_status="INACTIVE",
                ),
                roster.director_headers,
            ),
            201,
        )
        assert inactive["employment_status"] == "INACTIVE", (
            "the default must be a default rather than a constant"
        )


class TestMaintenanceTaskRecord:
    def test_recovery_credit_and_surface_class_are_computed(self, client, roster):
        """Both values are derived at creation and then frozen on the task.

        "The field's `surface_type` is copied into the task's own `surface_class`
        at creation and then frozen, so the historical record of what class of
        work was done survives even a later replacement."

        "At creation the task also materialises `recovery_credit_hours`, the
        rest-hour credit it will grant once completed, from a fixed table keyed on
        `task_type`: a full-depth `AERATION` is worth 12.00 hours of recovery, an
        `OVERSEEDING` a full day at 24.00 hours, a `FERTILITY` application 6.00
        hours, an `IRRIGATION` cycle 4.00 hours, a `GROOMING` pass 3.00 hours, an
        `INFILL_REDISTRIBUTION` 6.00 hours, and a `SEAM_INSPECTION` nothing at all
        at 0.00 hours — inspecting a seam does not rest a surface."

        "The optional `planned_for_certification_window` flag defaults to false
        and marks the task as part of the documented agronomic programme that the
        certification completeness score counts — it has no other effect."

        "`status` initialises to `SCHEDULED`, with `started_at_utc`,
        `completed_at_utc` and `cancellation_reason` all null."

        Design: Corner/entities/maintenance_task_recovery_credit_and_surface_class_are_computed
        """
        grass = fixtures.register_grass_practice_3(client, roster)
        synthetic = fixtures.register_synthetic_stadium_1(client, roster)

        aeration = fixtures.schedule_task(
            client,
            roster,
            grass["id"],
            task_type="AERATION",
            scheduled_start_utc="2026-08-10T08:00:00Z",
            scheduled_end_utc="2026-08-10T10:00:00Z",
        )
        assert_maintenance_task(aeration)
        assert_two_decimals(
            aeration["recovery_credit_hours"], 12.00, "AERATION recovery_credit_hours"
        )
        assert aeration["surface_class"] == "NATURAL_GRASS"
        assert aeration["status"] == "SCHEDULED"
        assert aeration["planned_for_certification_window"] is False
        assert aeration.get("started_at_utc") is None
        assert aeration.get("completed_at_utc") is None
        assert aeration.get("cancellation_reason") is None

        seam = fixtures.schedule_task(
            client,
            roster,
            synthetic["id"],
            task_type="SEAM_INSPECTION",
            scheduled_start_utc="2026-08-11T08:00:00Z",
            scheduled_end_utc="2026-08-11T09:00:00Z",
        )
        assert_maintenance_task(seam)
        assert_two_decimals(
            seam["recovery_credit_hours"], 0.00, "SEAM_INSPECTION recovery_credit_hours"
        )
        assert seam["surface_class"] == "SYNTHETIC_TURF"

        overseeding = fixtures.schedule_task(
            client,
            roster,
            grass["id"],
            task_type="OVERSEEDING",
            scheduled_start_utc="2026-08-12T08:00:00Z",
            scheduled_end_utc="2026-08-12T10:00:00Z",
        )
        assert_two_decimals(
            overseeding["recovery_credit_hours"],
            24.00,
            "OVERSEEDING recovery_credit_hours",
        )
        irrigation = fixtures.schedule_task(
            client,
            roster,
            grass["id"],
            task_type="IRRIGATION",
            scheduled_start_utc="2026-08-13T08:00:00Z",
            scheduled_end_utc="2026-08-13T10:00:00Z",
        )
        assert_two_decimals(
            irrigation["recovery_credit_hours"], 4.00, "IRRIGATION recovery_credit_hours"
        )

    def test_body_level_foreign_keys_resolve_to_their_own_codes(self, client, roster):
        """A bad reference is reported against the collection it names.

        "A `field_id` in the body that does not resolve yields
        `ERR_FIELD_NOT_FOUND`, and this applies to maintenance-task creation,
        safety-assessment recording, booking creation, certification-packet
        creation, replacement-plan creation, and — for the
        `predecessor_field_id` reference — field registration."

        "An unresolvable `assigned_staff_member_id`,
        `inspector_staff_member_id`, `requested_by_staff_member_id`,
        `submitted_by_staff_member_id` or `decided_by_staff_member_id` yields
        `ERR_STAFF_MEMBER_NOT_FOUND`"

        "An unresolvable `governing_assessment_id` or
        `verification_assessment_id` yields `ERR_SAFETY_ASSESSMENT_NOT_FOUND`, on
        certification-packet creation and remediation verification submission
        respectively. An unresolvable `capital_budget_id` yields
        `ERR_CAPITAL_BUDGET_NOT_FOUND` on replacement-plan creation."

        Design: Corner/entities/maintenance_task_with_unknown_field_id_returns_not_found
        """
        field = fixtures.register_grass_practice_3(client, roster)

        validate_error(
            client.create_maintenance_task(
                factories.make_maintenance_task_payload(
                    field_id=UNUSED_UUID,
                    assigned_staff_member_id=roster.id_of("agronomist"),
                    task_type="AERATION",
                ),
                roster.agronomist_headers,
            ),
            ApiErrorId.FIELD_NOT_FOUND,
            404,
        )
        _tasks, task_meta = validate_paginated(
            client.list_maintenance_tasks(roster.director_headers, params={"limit": 100})
        )
        assert task_meta["total_count"] == 0

        validate_error(
            client.create_maintenance_task(
                factories.make_maintenance_task_payload(
                    field_id=field["id"],
                    assigned_staff_member_id=UNUSED_UUID,
                    task_type="AERATION",
                ),
                roster.agronomist_headers,
            ),
            ApiErrorId.STAFF_MEMBER_NOT_FOUND,
            404,
        )

        validate_error(
            client.create_replacement_plan(
                factories.make_replacement_plan_payload(
                    field_id=field["id"],
                    capital_budget_id=UNUSED_UUID,
                    expected_field_version=field["version"],
                    target_surface_type="NATURAL_GRASS",
                    area_sq_ft=60000,
                ),
                roster.director_headers,
            ),
            ApiErrorId.CAPITAL_BUDGET_NOT_FOUND,
            404,
        )
        validate_error(
            client.create_certification_packet(
                factories.make_certification_packet_payload(
                    field_id=field["id"],
                    governing_assessment_id=UNUSED_UUID,
                    expected_field_version=field["version"],
                ),
                roster.cert_officer_headers,
            ),
            ApiErrorId.SAFETY_ASSESSMENT_NOT_FOUND,
            404,
        )


class TestUsageLedgerEntry:
    def test_ledger_entry_is_immutable_and_carries_no_version(self, client, roster):
        """A ledger entry is the one resource kind without the versioned commons.

        "`UsageLedgerEntry` is the exception: because a ledger entry is immutable
        once appended, it carries only `id` and `created_at`. A ledger entry has
        no `updated_at` and no `version`, and none should be emitted for it."

        "ledger entries are immutable, are never deleted and are never amended.
        When an effect has to be undone, it is undone by appending a further
        compensating entry, never by editing history."

        "Each entry also carries `effective_at_utc`, the logical-clock instant at
        which it was appended, and `note`, a short machine-generated audit string
        naming the transition that produced it."

        Design: Corner/entities/usage_ledger_entry_is_immutable_and_carries_no_version
        """
        field = fixtures.register_grass_practice_3(client, roster)
        booking = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="GAME",
            window_start_utc="2026-08-02T19:00:00Z",
            window_end_utc="2026-08-02T20:30:00Z",
            expected_participant_count=40,
        )
        fixtures.confirm_booking(client, roster, booking["id"])
        fixtures.set_clock(client, roster, "2026-08-02T20:30:00Z")
        fixtures.close_out_booking(
            client,
            roster,
            booking["id"],
            outcome="PLAYED",
            actual_duration_hours=1.50,
            actual_participant_count=40,
            weather_condition="WET",
        )

        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert_usage_ledger_entry(entry)
        assert entry["entry_type"] == "PLAY_WEAR"

        # 1.50 h x 1.50 GAME x 1.00 crowd x 1.20 grass x 1.35 wet = 3.645 -> 3.65.
        assert_two_decimals(entry["wear_units_delta"], 3.65, "wear_units_delta")
        assert_two_decimals(entry["running_balance_after"], 3.65, "running_balance_after")
        # 3.65 units all inside the first tier at 0.50 plus the 2.00 wet surcharge.
        assert_two_decimals(
            entry["rest_requirement_hours"], 3.83, "rest_requirement_hours"
        )
        assert_instant_equals(
            entry["effective_at_utc"], "2026-08-02T20:30:00Z", "effective_at_utc"
        )
        # Only `effective_at_utc` is specified as "the logical-clock instant at
        # which it was appended"; `created_at` is merely "recording creation", so
        # its clock source is not uniquely derivable and is not asserted here.

        single = validate_success(
            client.get_usage_ledger_entry(entry["id"], roster.coordinator_headers), 200
        )
        assert "id" in single and "created_at" in single
        assert "updated_at" not in single, "a ledger entry has no `updated_at`"
        assert "version" not in single, "a ledger entry has no `version`"
