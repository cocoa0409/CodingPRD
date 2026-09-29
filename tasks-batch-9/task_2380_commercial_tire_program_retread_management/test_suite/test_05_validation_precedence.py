"""Which of two simultaneously violated rules the API is required to report."""

from test_helpers import (
    NON_EXISTENT_UUID,
    factories,
    fixtures,
    validate_error,
)


class TestStateBeatsSlotConflict:
    """Position 9 outranks position 24."""

    def test_ungraded_carcass_reports_its_state_not_the_slot_conflict(self, api):
        """PRD §2.11: "This ordering is normative: a request that violates rules at
        positions 9 and 31 reports the position-9 error."
        PRD §2.11: "9. The target row is in a state from which the requested
        transition is declared — otherwise the entity's invalid-state code:
        `ERR_CASING_INVALID_STATE`, `ERR_TIRE_ASSET_INVALID_STATE`,
        `ERR_RETREAD_JOB_INVALID_STATE`, `ERR_CALL_INVALID_STATE`,
        `ERR_MANIFEST_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`,
        `ERR_INVOICE_INVALID_STATE`, `ERR_FLEET_INVALID_STATE`,
        `ERR_LINE_INVALID_STATE` or `ERR_TECHNICIAN_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_when_scheduling_retread_rejected
        """
        program = fixtures.setup_line_with_occupied_slot()
        line_id = program["line"]["id"]
        assert fixtures.read_line(line_id)["booked_minutes"] == 270

        # Never collected, so never graded: the carcass is still ON_WHEEL.
        ungraded = fixtures.create_casing(program["fleet"]["id"])
        assert ungraded["status"] == "ON_WHEEL"

        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    ungraded["id"],
                    line_id,
                    "2026-08-20T12:00:00Z",
                    "2026-08-20T13:00:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_CASING_INVALID_STATE",
            expected_status=409,
        )

        # Control: the very same slot really is occupied, so the lower-ranked
        # rule would have fired on its own.
        graded = fixtures.create_inspected_casing(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )
        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    graded["id"],
                    line_id,
                    "2026-08-20T12:00:00Z",
                    "2026-08-20T13:00:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_RETREAD_SLOT_CONFLICT",
            expected_status=409,
        )

        assert fixtures.read_line(line_id)["booked_minutes"] == 270, (
            "neither rejected booking touched the line"
        )
        assert fixtures.count_jobs_for_casing(ungraded["id"]) == 0

    def test_state_also_outranks_the_slot_conflict_and_the_down_line_together(
        self, api
    ):
        """PRD §2.11: "When more than one rule could reject a request, the outcome
        must be deterministic. Checks are evaluated in the following order, and the
        first failure is the one reported."
        PRD §2.11: "24. The requested retread slot does not intersect an occupied
        interval on the line — otherwise `ERR_RETREAD_SLOT_CONFLICT`. Applies to
        both scheduling and rescheduling."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_when_scheduling_retread_rejected
        """
        program = fixtures.setup_line_with_occupied_slot()
        line_id = program["line"]["id"]
        collected = fixtures.create_collected_casing(
            program["fleet"]["id"], program["location"]["id"]
        )
        assert collected["status"] == "COLLECTED", "collected but not yet graded"
        fixtures.take_line_down(line_id)

        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    collected["id"],
                    line_id,
                    "2026-08-20T12:00:00Z",
                    "2026-08-20T13:00:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_CASING_INVALID_STATE",
            expected_status=409,
        )

        assert fixtures.read_line(line_id)["booked_minutes"] == 270
        assert fixtures.read_casing(collected["id"])["status"] == "COLLECTED"
        assert fixtures.count_jobs_for_casing(collected["id"]) == 0


class TestTreadBeatsBrand:
    """Position 14 outranks position 20."""

    def test_worn_and_unapproved_tire_reports_the_tread_failure(self, api):
        """PRD §2.11: "14. Mount-time tread depth clears the policy minimum —
        otherwise `ERR_TREAD_BELOW_POLICY_MINIMUM`. Applies to mounting."
        PRD §3.3: "The supplied `tread_depth_at_mount_32nds` must be **strictly
        greater** than the policy's `min_tread_depth_32nds`; a depth equal to the
        legal minimum is not mountable and is rejected with
        `ERR_TREAD_BELOW_POLICY_MINIMUM`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_mount_cannot_use_worn_unapproved_tire
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        casing = fixtures.create_casing(program["fleet"]["id"])
        asset = fixtures.create_tire_asset(
            program["fleet"]["id"], casing["id"], brand="Goodyear"
        )
        assert program["policy"]["min_tread_depth_32nds"] == 4
        assert "Goodyear" not in program["policy"]["approved_brands"]

        validate_error(
            api.mount_tire_asset(
                asset["id"],
                factories.mount_payload(
                    vehicle["id"], "2026-08-02T08:00:00Z", 100000, 4, "DRIVE"
                ),
                fixtures.TECH,
            ),
            "ERR_TREAD_BELOW_POLICY_MINIMUM",
            expected_status=422,
        )

        unchanged = fixtures.read_tire_asset(asset["id"])
        assert unchanged["status"] == "IN_INVENTORY"
        assert unchanged.get("vehicle_id") is None
        assert unchanged.get("position") is None

    def test_an_adequately_treaded_tire_falls_through_to_the_brand_failure(self, api):
        """PRD §2.11: "20. The brand is approved and the casing specification
        matches — otherwise `ERR_BRAND_NOT_APPROVED` or `ERR_CASING_SPEC_MISMATCH`,
        with the brand checked first. Applies to mounting."
        PRD §3.3: "The asset's `brand` must appear in the policy's
        `approved_brands`, otherwise `ERR_BRAND_NOT_APPROVED`; and the underlying
        casing's `casing_spec_code` must equal the policy's `casing_spec_code` unless
        the policy's value is the wildcard `ANY`, otherwise `ERR_CASING_SPEC_MISMATCH`
        — with brand checked before specification, so an asset failing both reports the
        brand error."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_mount_cannot_use_worn_unapproved_tire
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        casing = fixtures.create_casing(program["fleet"]["id"])
        asset = fixtures.create_tire_asset(
            program["fleet"]["id"], casing["id"], brand="Goodyear"
        )

        validate_error(
            api.mount_tire_asset(
                asset["id"],
                factories.mount_payload(
                    vehicle["id"], "2026-08-02T08:00:00Z", 100000, 5, "DRIVE"
                ),
                fixtures.TECH,
            ),
            "ERR_BRAND_NOT_APPROVED",
            expected_status=422,
        )
        assert fixtures.read_tire_asset(asset["id"])["status"] == "IN_INVENTORY"

        # Five thirty-seconds clears the minimum, as an approved-brand mount shows,
        # which is why the brand rule is the only one the request still violated.
        mounted = fixtures.create_mounted_asset(
            program["fleet"]["id"],
            casing["id"],
            vehicle["id"],
            tread_depth_at_mount_32nds=5,
        )
        assert mounted["status"] == "MOUNTED"
        assert mounted["tread_depth_at_mount_32nds"] == 5


class TestAuthorizationBeatsExistence:
    """Position 2 outranks position 3."""

    def test_unauthorised_role_gets_403_even_for_a_casing_that_does_not_exist(
        self, api
    ):
        """PRD §2.11: "2. The acting role is authorised for the endpoint —
        otherwise `ERR_UNAUTHORIZED`."
        PRD §2.11: "3. Every identifier in the URL path resolves, checked left to
        right — otherwise the matching not-found code from §2.6."

        Design: Difficulty/priority_pair_validation_conflict/auth_beats_existence_on_inspect_returns_403_not_404
        """
        payload = factories.inspect_casing_payload("B", 1)

        validate_error(
            api.inspect_casing(NON_EXISTENT_UUID, payload, fixtures.SCHEDULER),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )

        # The authorised role on the same identifier reaches the path check.
        validate_error(
            api.inspect_casing(NON_EXISTENT_UUID, payload, fixtures.inspector_headers()),
            "ERR_CASING_NOT_FOUND",
            expected_status=404,
        )

    def test_unauthorised_role_never_reaches_the_state_or_version_checks(self, api):
        """PRD §2.1: "If both headers are present and well-formed but the named
        role is not authorised for the endpoint being called, the request is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.11: "10. The optimistic concurrency check of §2.9 — otherwise
        `ERR_STALE_CASING_VERSION` on casing inspection or `ERR_STALE_FLEET_VERSION`
        on invoice creation."

        Design: Difficulty/priority_pair_validation_conflict/auth_beats_existence_on_inspect_returns_403_not_404
        """
        program = fixtures.setup_fleet_program()
        collected = fixtures.create_collected_casing(
            program["fleet"]["id"], program["location"]["id"]
        )

        validate_error(
            api.inspect_casing(
                collected["id"],
                factories.inspect_casing_payload("B", collected["version"] + 99),
                fixtures.SCHEDULER,
            ),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )

        untouched = fixtures.read_casing(collected["id"])
        assert untouched["status"] == "COLLECTED"
        assert untouched["version"] == collected["version"]
        assert untouched.get("inspection_grade") is None
        assert fixtures.list_ledger(program["fleet"]["id"]) == []
