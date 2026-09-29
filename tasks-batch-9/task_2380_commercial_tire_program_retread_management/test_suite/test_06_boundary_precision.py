"""Boundaries where landing exactly on the limit is the accepted case."""

from test_helpers import (
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestManifestCapacityBoundary:
    """A load landing on exactly the capacity is accepted."""

    def test_a_load_landing_on_exactly_the_capacity_is_accepted(self, api):
        """PRD §3.7: "The comparison is strict — a load landing on **exactly** the
        capacity is accepted, and only a load that would push the total strictly
        above it is rejected with `ERR_MANIFEST_CAPACITY_EXCEEDED`."
        PRD §3.7: "On success the casing's `scrap_manifest_id` is set, the
        manifest's `tire_count` and `total_weight_lbs` are recomputed from the
        casings now linked to it, and the manifest's `version` increments."

        Design: Difficulty/boundary_precision_check/manifest_capacity_exact_weight_boundary
        """
        program = fixtures.setup_fleet_program()
        manifest = fixtures.create_manifest(
            program["location"]["id"], hauler_capacity_lbs=250
        )
        assert manifest["tire_count"] == 0
        assert manifest["total_weight_lbs"] == 0

        first = fixtures.create_condemned_casing_with_credit(
            program["fleet"]["id"], program["location"]["id"], scrap_weight_lbs=125
        )
        after_first = fixtures.add_manifest_line(manifest["id"], first["id"])
        assert after_first["tire_count"] == 1
        assert after_first["total_weight_lbs"] == 125

        second = fixtures.create_condemned_casing_with_credit(
            program["fleet"]["id"], program["location"]["id"], scrap_weight_lbs=125
        )
        after_second = fixtures.add_manifest_line(manifest["id"], second["id"])

        assert after_second["total_weight_lbs"] == 250, "exactly the hauler capacity"
        assert after_second["tire_count"] == 2
        assert after_second["status"] == "DRAFT"
        assert (
            fixtures.read_casing(second["id"])["scrap_manifest_id"] == manifest["id"]
        )

    def test_one_pound_over_the_capacity_is_refused_and_leaves_no_linkage(self, api):
        """PRD §3.7: "And the load must stay within the truck: the manifest's
        current `total_weight_lbs` plus the candidate casing's `scrap_weight_lbs`
        must not exceed `hauler_capacity_lbs`."
        PRD §3.7: "The casing's `scrap_manifest_id` must be empty, since a carcass
        cannot be on two loads at once; a repeat is rejected with
        `ERR_CASING_ALREADY_ON_MANIFEST`."

        Design: Difficulty/boundary_precision_check/manifest_capacity_exact_weight_boundary
        """
        program = fixtures.setup_manifest_with_condemned_casings(
            casing_specs=[125, 125], hauler_capacity_lbs=250
        )
        manifest_id = program["manifest"]["id"]
        assert program["manifest"]["total_weight_lbs"] == 250

        overflow = fixtures.create_condemned_casing_with_credit(
            program["fleet"]["id"], program["location"]["id"], scrap_weight_lbs=1
        )

        validate_error(
            api.add_scrap_manifest_line(
                manifest_id,
                factories.manifest_line_payload(overflow["id"]),
                fixtures.OFFICER,
            ),
            "ERR_MANIFEST_CAPACITY_EXCEEDED",
            expected_status=409,
        )

        assert fixtures.read_casing(overflow["id"]).get("scrap_manifest_id") is None
        unchanged = fixtures.read_manifest(manifest_id)
        assert unchanged["tire_count"] == 2
        assert unchanged["total_weight_lbs"] == 250
        assert unchanged["version"] == program["manifest"]["version"]

        # The full-to-the-brim load is still signable.
        signed = fixtures.sign_manifest(manifest_id)
        assert signed["status"] == "SIGNED"


class TestManifestEmptySetBoundary:
    """Zero listed casings is the boundary the signature rejects."""

    def test_signing_an_empty_manifest_is_refused_and_leaves_it_in_draft(self, api):
        """PRD §3.7: "Fourth, the manifest must not be empty — `tire_count` must be
        at least 1, and a manifest with nothing on it is rejected with
        `ERR_MANIFEST_EMPTY`."
        PRD §3.7: "Note that the emptiness check comes after the eligibility check,
        which an empty manifest passes trivially."

        Design: Difficulty/boundary_precision_check/manifest_empty_set_signing_boundary
        """
        program = fixtures.setup_fleet_program()
        manifest = fixtures.create_manifest(program["location"]["id"])
        assert manifest["tire_count"] == 0

        validate_error(
            api.sign_scrap_manifest(
                manifest["id"],
                factories.sign_manifest_payload("2026-08-10T09:00:00Z"),
                fixtures.officer_headers(),
            ),
            "ERR_MANIFEST_EMPTY",
            expected_status=422,
        )

        unsigned = fixtures.read_manifest(manifest["id"])
        assert unsigned["status"] == "DRAFT"
        assert unsigned.get("signed_at") is None
        assert unsigned.get("signed_by_user_id") is None

    def test_one_listed_casing_is_enough_for_the_signature(self, api):
        """PRD §3.7: "A successful signature advances the manifest `DRAFT → SIGNED`,
        records `signed_by_user_id` from the acting officer and `signed_at` from the
        supplied instant, and increments the manifest's `version`."
        PRD §2.10: "A manifest's `tire_count` and `total_weight_lbs` are the count
        of, and the sum of `scrap_weight_lbs` over, the casings whose
        `scrap_manifest_id` is that manifest."

        Design: Difficulty/boundary_precision_check/manifest_empty_set_signing_boundary
        """
        program = fixtures.setup_manifest_with_condemned_casings(casing_specs=[130])
        manifest_before = fixtures.read_manifest(program["manifest"]["id"])
        assert manifest_before["tire_count"] == 1
        assert manifest_before["total_weight_lbs"] == 130

        signed = validate_success(
            api.sign_scrap_manifest(
                program["manifest"]["id"],
                factories.sign_manifest_payload("2026-08-10T09:00:00Z"),
                fixtures.officer_headers(),
            )
        )

        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == "officer-signer"
        assert signed["signed_at"] == "2026-08-10T09:00:00Z"
        assert signed["version"] == manifest_before["version"] + 1


class TestRetreadSlotCooldownBoundary:
    """The occupied interval ends at the incumbent's end plus the cooldown."""

    def test_one_minute_inside_the_cooldown_is_refused(self, api):
        """PRD §3.5: "The practical consequence: a candidate starting at exactly the
        instant an existing job's `scheduled_end_at` plus `cure_cooldown_minutes`
        falls is **accepted**, while a candidate starting one minute earlier is
        rejected with `ERR_RETREAD_SLOT_CONFLICT`."
        PRD §2.10: "A retread line's `booked_minutes` is the sum, over jobs on that
        line whose `status` is `SCHEDULED` or `IN_PRODUCTION`, of that job's
        whole-minute slot length plus the line's `cure_cooldown_minutes`."

        Design: Difficulty/boundary_precision_check/retread_slot_cooldown_exact_minute_boundary
        """
        program = fixtures.setup_line_with_occupied_slot(
            incumbent_start="2026-08-20T08:00:00Z",
            incumbent_end="2026-08-20T12:00:00Z",
        )
        line = fixtures.read_line(program["line"]["id"])
        assert line["cure_cooldown_minutes"] == 30
        assert line["booked_minutes"] == 270, "240 slot minutes plus the 30 cooldown"

        candidate = fixtures.create_inspected_casing(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )

        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    candidate["id"],
                    line["id"],
                    "2026-08-20T12:29:00Z",
                    "2026-08-20T14:29:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_RETREAD_SLOT_CONFLICT",
            expected_status=409,
        )

        assert fixtures.read_line(line["id"])["booked_minutes"] == 270
        assert fixtures.read_casing(candidate["id"])["status"] == "INSPECTED"
        assert fixtures.count_jobs_for_casing(candidate["id"]) == 0

    def test_starting_exactly_when_the_cooldown_lapses_is_accepted(self, api):
        """PRD §3.5: "Each occupying job occupies a half-open interval beginning at
        its `scheduled_start_at` and ending at its `scheduled_end_at` advanced by the
        line's `cure_cooldown_minutes` — the cooldown is part of what the existing
        job holds."
        PRD §3.5: "And it adds the job's `slot_minutes` plus the line's
        `cure_cooldown_minutes` to the line's `booked_minutes`."

        Design: Difficulty/boundary_precision_check/retread_slot_cooldown_exact_minute_boundary
        """
        program = fixtures.setup_line_with_occupied_slot(
            incumbent_start="2026-08-20T08:00:00Z",
            incumbent_end="2026-08-20T12:00:00Z",
        )
        candidate = fixtures.create_inspected_casing(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )

        job = validate_success(
            api.create_retread_job(
                factories.retread_job_payload(
                    candidate["id"],
                    program["line"]["id"],
                    "2026-08-20T12:30:00Z",
                    "2026-08-20T14:30:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            expected_status=201,
        )

        assert job["status"] == "SCHEDULED"
        assert job["slot_minutes"] == 120
        assert fixtures.read_casing(candidate["id"])["status"] == "RETREAD_QUEUED"
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 420, (
            "270 already booked plus this slot's 120 minutes and 30 of cooldown"
        )


def _sla_program():
    program = fixtures.setup_fleet_program()
    assert program["location"]["road_service_response_minutes_committed"] == 120
    program["vehicle"] = fixtures.create_vehicle(program["fleet"]["id"])
    program["technician"] = fixtures.create_technician(program["location"]["id"])
    return program


def _run_normal_call(program, arrived_at):
    return fixtures.run_completed_call(
        program["fleet"]["id"],
        program["vehicle"]["id"],
        program["location"]["id"],
        program["technician"]["id"],
        reported_at="2026-08-05T13:00:00Z",
        dispatched_at="2026-08-05T13:05:00Z",
        arrived_at=arrived_at,
        closed_at="2026-08-05T17:00:00Z",
        labor_hours=1.0,
        dispatch_miles=100,
        priority="NORMAL",
    )


class TestSlaEqualityBoundary:
    """Arriving on exactly the committed minute counts as met."""

    def test_arriving_on_the_committed_minute_earns_no_credit(self, api):
        """PRD §3.6: "`sla_met` is true when `actual_response_minutes` is less than
        or equal to `committed_response_minutes`; arriving on exactly the committed
        minute **counts as met**."
        PRD §3.6: "On a `NORMAL` call, the commitment is the location baseline plus
        a grace allowance of one hour, that is 60 minutes."

        Design: Difficulty/boundary_precision_check/sla_response_equality_counts_as_met
        """
        program = _sla_program()

        call = _run_normal_call(program, arrived_at="2026-08-05T16:00:00Z")

        assert call["committed_response_minutes"] == 180, "120 baseline plus 60 grace"
        assert call["actual_response_minutes"] == 180
        assert call["sla_met"] is True
        assert call["gross_cents"] == 49000, "9500 base, 11000 labour, 28500 mileage"
        assert call["sla_credit_cents"] == 0
        assert call["invoice_total_cents"] == 49000

    def test_arriving_one_minute_late_costs_a_fifth_of_the_call(self, api):
        """PRD §3.6: "`sla_credit_cents` is 20 percent of `gross_cents` rounded half
        up to whole cents when `sla_met` is false, and exactly 0 when `sla_met` is
        true — the fleet is credited a fifth of the call for a missed commitment."
        PRD §3.6: "`actual_response_minutes` is the elapsed time from `reported_at`
        to `arrived_at`, taken in seconds, divided by 60 and truncated down to a
        whole number of minutes."

        Design: Difficulty/boundary_precision_check/sla_response_equality_counts_as_met
        """
        program = _sla_program()

        call = _run_normal_call(program, arrived_at="2026-08-05T16:01:00Z")

        assert call["committed_response_minutes"] == 180
        assert call["actual_response_minutes"] == 181
        assert call["sla_met"] is False
        assert call["gross_cents"] == 49000, "the pricing itself is unchanged"
        assert call["sla_credit_cents"] == 9800
        assert call["invoice_total_cents"] == 39200
