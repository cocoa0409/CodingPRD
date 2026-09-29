"""Three interval semantics: half-open item windows, closed escort windows, buffered audits."""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    audit_session_payload,
    custody_transfer_payload,
    log_and_store_item,
    read_custodian,
    read_item,
    read_location,
    request_transfer,
    schedule_audit,
    setup_difficulty_base,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestItemCustodyWindowsAreHalfOpen:
    """Adjacency on the same item is legal, PRD section 3.5."""

    def _item_with_one_booked_window(self, env):
        """A folder in G-01 already booked out to the investigator for five days."""
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Handwriting exemplar folder",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=800,
            seized_at="2026-07-31T21:00:00Z",
        )
        first = request_transfer(
            env,
            item["id"],
            env["inv_id"],
            "INVESTIGATIVE_REVIEW",
            "2026-09-10T00:00:00Z",
            "2026-09-15T00:00:00Z",
            headers=env["inv_headers"],
        )
        return item, first

    def test_a_window_starting_exactly_when_the_first_ends_is_accepted(self, api):
        """Touching endpoints are not an overlap for the per-item rule.

        PRD 3.5: "The per-item rule treats each open custody window as half-open, so
        adjacency is allowed."
        PRD 3.5: "A conflict exists when the candidate's `released_at` falls strictly
        before that effective end **and** the existing transfer's `released_at` falls
        strictly before the candidate's `due_back_at`; a candidate starting at exactly the
        instant an existing window ends is therefore not a conflict."
        PRD 3.5: "The new row starts with `status` of `REQUESTED`, with
        `from_custodian_id`, all three signature fields, `returned_at` and `denial_reason`
        null, and it increments both the receiving custodian's `open_escort_count` and the
        item's `open_transfer_count`."

        Design: Difficulty/resource_temporal_overlap/item_custody_windows_half_open_adjacency_allowed
        """
        env = setup_difficulty_base()
        item, first = self._item_with_one_booked_window(env)

        adjacent = validate_success(
            api.create_custody_transfer(
                custody_transfer_payload(
                    item["id"],
                    env["inv_id"],
                    "INVESTIGATIVE_REVIEW",
                    "2026-09-15T00:00:00Z",
                    "2026-09-18T00:00:00Z",
                ),
                env["inv_headers"],
            ),
            201,
        )

        assert adjacent["status"] == "REQUESTED"
        assert adjacent["released_at"] == "2026-09-15T00:00:00.000Z"
        assert first["due_back_at"] == adjacent["released_at"]
        assert read_item(env, item["id"])["open_transfer_count"] == 2
        assert read_custodian(env, env["inv_id"])["open_escort_count"] == 2

    def test_a_window_starting_one_millisecond_earlier_is_refused(self, api):
        """A single millisecond of true overlap is enough to conflict.

        PRD 3.5: "For this purpose an existing transfer's effective end is its
        `returned_at` when one has been recorded, and otherwise its `due_back_at`; only
        transfers on the same item whose `status` is `REQUESTED`, `RELEASED` or `OVERDUE`
        participate, while `RETURNED`, `DENIED` and `LOST` rows are ignored."
        PRD 3.5: "A conflict is refused with `ERR_CUSTODY_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/item_custody_windows_half_open_adjacency_allowed
        """
        env = setup_difficulty_base()
        item, first = self._item_with_one_booked_window(env)
        adjacent = validate_success(
            api.create_custody_transfer(
                custody_transfer_payload(
                    item["id"],
                    env["inv_id"],
                    "INVESTIGATIVE_REVIEW",
                    "2026-09-15T00:00:00Z",
                    "2026-09-18T00:00:00Z",
                ),
                env["inv_headers"],
            ),
            201,
        )

        overlapping = api.create_custody_transfer(
            custody_transfer_payload(
                item["id"],
                env["lab_id"],
                "LAB_ANALYSIS",
                "2026-09-14T23:59:59.999Z",
                "2026-09-17T00:00:00Z",
            ),
            env["lab_headers"],
        )

        validate_error(overlapping, ApiErrorId.ERR_CUSTODY_WINDOW_CONFLICT, 409)
        rows, meta = validate_paginated(
            api.list_custody_transfers(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], adjacent["id"]}
        assert read_custodian(env, env["lab_id"])["open_escort_count"] == 0


class TestEscortCapacityUsesClosedIntervals:
    """Touching endpoints do count against the receiving custodian, PRD section 3.5.

    The three items sit in different bins and are distinct, so the per-item window
    rule cannot fire and only the escort capacity limit is in play.
    """

    def _investigator_holding_two_overlapping_escorts(self, env):
        """Two open escorts on the investigator plus a third, untransferred item."""
        first_item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Interview notes packet 1",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=100,
            seized_at="2026-07-31T22:00:00Z",
        )
        second_item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Interview notes packet 2",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=100,
            seized_at="2026-07-31T22:10:00Z",
        )
        third_item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_v_id"],
            item_description="Seized revolver",
            category="FIREARM",
            packaging_type="RIGID_BOX",
            appraised_value_cents=60000,
            seized_at="2026-07-31T22:20:00Z",
        )
        request_transfer(
            env,
            first_item["id"],
            env["inv_id"],
            "INVESTIGATIVE_REVIEW",
            "2026-09-10T00:00:00Z",
            "2026-09-15T00:00:00Z",
            headers=env["inv_headers"],
        )
        request_transfer(
            env,
            second_item["id"],
            env["inv_id"],
            "INVESTIGATIVE_REVIEW",
            "2026-09-12T00:00:00Z",
            "2026-09-16T00:00:00Z",
            headers=env["inv_headers"],
        )
        return third_item

    def test_a_third_escort_touching_the_first_window_is_refused(self, api):
        """The first window merely touches the candidate, yet still counts.

        PRD 3.5: "The escort rule is a capacity limit on the receiving custodian,
        spanning all items and all cases, and it treats windows as closed intervals so
        that touching endpoints do count."
        PRD 3.5: "The service counts the open transfers — again `REQUESTED`, `RELEASED` or
        `OVERDUE` — assigned to the same `to_custodian_id` whose `released_at` is at or
        before the candidate's `due_back_at` and whose effective end (its `returned_at` if
        recorded, otherwise its `due_back_at`) is at or after the candidate's
        `released_at`."
        PRD 3.5: "If that count reaches 2, the request is refused with
        `ERR_ESCORT_CAPACITY_EXCEEDED`: no custodian may be responsible for more than two
        overlapping escorts at once."

        Design: Difficulty/resource_temporal_overlap/custodian_escort_capacity_closed_interval_third_overlap_rejected
        """
        env = setup_difficulty_base()
        third_item = self._investigator_holding_two_overlapping_escorts(env)

        response = api.create_custody_transfer(
            custody_transfer_payload(
                third_item["id"],
                env["inv_id"],
                "INVESTIGATIVE_REVIEW",
                "2026-09-15T00:00:00Z",
                "2026-09-18T00:00:00Z",
            ),
            env["inv_headers"],
        )

        validate_error(response, ApiErrorId.ERR_ESCORT_CAPACITY_EXCEEDED, 409)
        assert read_custodian(env, env["inv_id"])["open_escort_count"] == 2
        rows, meta = validate_paginated(
            api.list_custody_transfers(
                env["manager"], params={"to_custodian_id": env["inv_id"]}
            )
        )
        assert meta["total_count"] == 2
        assert third_item["id"] not in {row["evidence_item_id"] for row in rows}

    def test_the_same_window_is_accepted_for_a_custodian_with_no_escorts(self, api):
        """The window itself is lawful; only the investigator's load was the problem.

        PRD 3.5: "An item leaves the room only under a transfer, and a transfer is
        requested by an `Investigator`, a `LabAnalyst` or an `EvidenceTechnician`
        supplying the `evidence_item_id`, the `to_custodian_id` of the custodian who will
        hold it, a `purpose` of `LAB_ANALYSIS`, `COURT_PRESENTATION` or
        `INVESTIGATIVE_REVIEW`, and the planned window as `released_at` and `due_back_at`."
        PRD 3.5: "The escort rule is a capacity limit on the receiving custodian, spanning
        all items and all cases, and it treats windows as closed intervals so that touching
        endpoints do count."

        Design: Difficulty/resource_temporal_overlap/custodian_escort_capacity_closed_interval_third_overlap_rejected
        """
        env = setup_difficulty_base()
        third_item = self._investigator_holding_two_overlapping_escorts(env)
        api.create_custody_transfer(
            custody_transfer_payload(
                third_item["id"],
                env["inv_id"],
                "INVESTIGATIVE_REVIEW",
                "2026-09-15T00:00:00Z",
                "2026-09-18T00:00:00Z",
            ),
            env["inv_headers"],
        )

        accepted = validate_success(
            api.create_custody_transfer(
                custody_transfer_payload(
                    third_item["id"],
                    env["lab_id"],
                    "LAB_ANALYSIS",
                    "2026-09-15T00:00:00Z",
                    "2026-09-18T00:00:00Z",
                ),
                env["lab_headers"],
            ),
            201,
        )

        assert accepted["status"] == "REQUESTED"
        assert accepted["released_at"] == "2026-09-15T00:00:00.000Z"
        assert read_custodian(env, env["lab_id"])["open_escort_count"] == 1
        assert read_item(env, third_item["id"])["open_transfer_count"] == 1


class TestAuditWindowsCarryA48HourBuffer:
    """Each scheduled window is inflated by two days on both sides, PRD section 3.8."""

    def _one_scheduled_session_on_the_refrigerator(self, env):
        """A session on R-01 running 2026-08-08T17:00Z to 2026-08-10T17:00Z."""
        first = schedule_audit(
            env,
            env["loc_r_id"],
            read_location(env, env["loc_r_id"])["version"],
            "2026-08-08T17:00:00Z",
            "2026-08-10T17:00:00Z",
        )
        return first, read_location(env, env["loc_r_id"])["version"]

    def test_starting_exactly_48_hours_after_the_prior_end_still_conflicts(self, api):
        """The inflated end of 2026-08-12T17:00Z is inclusive, so the candidate is refused.

        PRD 3.8: "Beyond that, sessions on the same location must be well separated:
        every existing session on that location whose `status` is `SCHEDULED`,
        `IN_PROGRESS` or `RECONCILED` is treated as occupying its window inflated by 48
        hours — two full days — on both sides, and a candidate conflicts when its
        `scheduled_start_at` is at or before that inflated end **and** the existing
        session's `scheduled_start_at` is at or before the candidate's inflated end."
        PRD 3.8: "The boundary is inclusive, so scheduling a session to begin exactly 48
        hours after an existing session's end still conflicts; the refusal is
        `ERR_AUDIT_WINDOW_BUFFER`."
        PRD 3.8: "Creating it also increments the target location's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/audit_window_48h_buffer_on_location
        """
        env = setup_difficulty_base()
        first, version_after_first = self._one_scheduled_session_on_the_refrigerator(env)

        response = api.create_audit_session(
            audit_session_payload(
                env["loc_r_id"],
                env["aud_id"],
                "2026-08-12T17:00:00Z",
                "2026-08-12T21:00:00Z",
                version_after_first,
            ),
            env["aud_headers"],
        )

        validate_error(response, ApiErrorId.ERR_AUDIT_WINDOW_BUFFER, 409)
        assert first["scheduled_end_at"] == "2026-08-10T17:00:00.000Z"
        # The refused creation touched nothing on the location.
        assert read_location(env, env["loc_r_id"])["version"] == version_after_first
        rows, meta = validate_paginated(
            api.list_audit_sessions(
                env["manager"], params={"storage_location_id": env["loc_r_id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

    def test_starting_one_millisecond_later_clears_the_buffer(self, api):
        """A millisecond past the inflated end is outside the buffer and is accepted.

        PRD 3.8: "A session begins with `status` of `SCHEDULED`, a `risk_index` of 0.00,
        empty `expected_evidence_item_ids` and `scanned_evidence_item_ids`, zero
        `expected_item_count`, `scanned_item_count`, `missing_count` and `misplaced_count`,
        and null `started_at`, `reconciled_at` and `closed_at`."
        PRD 3.8: "Inventory reconciliation is scheduled one storage location at a time by
        an `InternalAuditor`, who supplies the `storage_location_id`, the `auditor_id`
        (which must equal their own `X-User-ID`), the planned window as
        `scheduled_start_at` and `scheduled_end_at`, and the
        `expected_storage_location_version` described in §2.9."

        Design: Difficulty/resource_temporal_overlap/audit_window_48h_buffer_on_location
        """
        env = setup_difficulty_base()
        first, version_after_first = self._one_scheduled_session_on_the_refrigerator(env)
        api.create_audit_session(
            audit_session_payload(
                env["loc_r_id"],
                env["aud_id"],
                "2026-08-12T17:00:00Z",
                "2026-08-12T21:00:00Z",
                version_after_first,
            ),
            env["aud_headers"],
        )

        accepted = validate_success(
            api.create_audit_session(
                audit_session_payload(
                    env["loc_r_id"],
                    env["aud_id"],
                    "2026-08-12T17:00:00.001Z",
                    "2026-08-12T21:00:00Z",
                    version_after_first,
                ),
                env["aud_headers"],
            ),
            201,
        )

        assert accepted["status"] == "SCHEDULED"
        assert accepted["scheduled_start_at"] == "2026-08-12T17:00:00.001Z"
        assert Decimal(str(accepted["risk_index"])) == Decimal("0.00")
        assert accepted["expected_item_count"] == 0
        assert accepted["started_at"] is None
        assert read_location(env, env["loc_r_id"])["version"] == version_after_first + 1
        rows, meta = validate_paginated(
            api.list_audit_sessions(
                env["manager"], params={"storage_location_id": env["loc_r_id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], accepted["id"]}
