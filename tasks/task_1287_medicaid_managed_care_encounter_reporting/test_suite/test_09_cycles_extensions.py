"""Cycle window and rate schedule interval semantics, deadline extensions with OCC,
member disenrollment, and scorecard remediation preconditions."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_batch,
    create_cycle,
    create_cycle_payload,
    create_member,
    create_program,
    create_provider,
    create_rate_schedule,
    create_rate_schedule_payload,
    create_validated_encounter,
    get_scorecard_for,
    get_success_data,
    seal_batch,
    set_clock,
    setup_basic_scenario,
    stage_encounter,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import COMP_TRANSMITTER, OPS, STATE
from test_helpers import make_mco_compliance_headers

COMP = make_mco_compliance_headers("fx-comp-ext")


class TestCycleWindowSemantics:
    def test_cycle_windows_half_open_adjacency_allowed(self):
        """PRD §3.3: "Cycle windows within one program must never overlap, but
        adjacency is allowed — one cycle's start may equal a sibling's end — and the
        window end must be strictly after the window start; violations are rejected with
        `ERR_CYCLE_OVERLAP`."
        PRD §2.4: "Submission cycle service-date windows are half-open: a cycle covers
        service dates from its `window_start_at` up to but not including its
        `window_end_at`."

        Design: Difficulty/resource_temporal_overlap/cycle_windows_half_open_adjacency_allowed
        """
        program = create_program(name="P-OV1")
        cycle1 = create_cycle(program["id"])

        resp_overlap = api_client.create_cycle(create_cycle_payload(
            program["id"], label="2026-08B",
            window_start_at="2026-08-15T00:00:00Z",
            window_end_at="2026-10-01T00:00:00Z",
            submission_deadline_at="2026-10-15T00:00:00Z"), STATE)
        validate_error(resp_overlap, ApiErrorId.ERR_CYCLE_OVERLAP)

        resp_adjacent = api_client.create_cycle(create_cycle_payload(
            program["id"], label="2026-09",
            window_start_at="2026-09-01T00:00:00Z",
            window_end_at="2026-10-01T00:00:00Z",
            submission_deadline_at="2026-10-15T00:00:00Z"), STATE)
        cycle2 = validate_success(resp_adjacent, expected_status=201)
        assert cycle2["status"] == "OPEN"

    def test_cycle_window_rejects_containing_and_empty_windows(self):
        """PRD §3.3: "Cycle windows within one program must never overlap, but
        adjacency is allowed — one cycle's start may equal a sibling's end — and the
        window end must be strictly after the window start; violations are rejected with
        `ERR_CYCLE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cycle_windows_half_open_adjacency_allowed
        """
        program = create_program(name="P-OV1B")
        create_cycle(program["id"])
        # New window strictly inside the existing one overlaps.
        resp_inside = api_client.create_cycle(create_cycle_payload(
            program["id"], label="2026-08-INNER",
            window_start_at="2026-08-10T00:00:00Z",
            window_end_at="2026-08-20T00:00:00Z",
            submission_deadline_at="2026-09-20T00:00:00Z"), STATE)
        validate_error(resp_inside, ApiErrorId.ERR_CYCLE_OVERLAP)
        # A zero-length window on a fresh program violates end > start.
        program2 = create_program(name="P-OV1C")
        resp_empty = api_client.create_cycle(create_cycle_payload(
            program2["id"], label="EMPTY",
            window_start_at="2026-08-01T00:00:00Z",
            window_end_at="2026-08-01T00:00:00Z",
            submission_deadline_at="2026-09-15T00:00:00Z"), STATE)
        validate_error(resp_empty, ApiErrorId.ERR_CYCLE_OVERLAP)


class TestRateScheduleIntervalSemantics:
    def test_rate_schedule_closed_interval_adjacency_is_overlap(self):
        """PRD §3.3: "Within the same program and aid category, closed windows must not
        overlap, and unlike cycles, adjacency counts as overlap: a new schedule whose
        `effective_from` equals an existing schedule's `effective_to` is rejected with
        `ERR_RATE_SCHEDULE_OVERLAP`."
        PRD §2.4: "Capitation rate schedule windows are closed: a schedule covers both
        its `effective_from` and its `effective_to` dates."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_closed_interval_adjacency_is_overlap
        """
        program = create_program(name="P-OV2")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)

        resp_adjacent = api_client.create_rate_schedule(create_rate_schedule_payload(
            program["id"], aid_category="TANF", pmpm_cents=51000,
            effective_from="2026-08-31", effective_to="2026-09-30"), STATE)
        validate_error(resp_adjacent, ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP)

        resp_next = api_client.create_rate_schedule(create_rate_schedule_payload(
            program["id"], aid_category="TANF", pmpm_cents=51000,
            effective_from="2026-09-01", effective_to="2026-09-30"), STATE)
        validate_success(resp_next, expected_status=201)

        # Overlap scope is per program + aid_category: the same dates under SSI succeed.
        resp_ssi = api_client.create_rate_schedule(create_rate_schedule_payload(
            program["id"], aid_category="SSI", pmpm_cents=120000,
            effective_from="2026-08-15", effective_to="2026-09-15"), STATE)
        validate_success(resp_ssi, expected_status=201)

    def test_rate_schedule_enclosing_overlap_rejected(self):
        """PRD §3.3: "Within the same program and aid category, closed windows must not
        overlap, and unlike cycles, adjacency counts as overlap: a new schedule whose
        `effective_from` equals an existing schedule's `effective_to` is rejected with
        `ERR_RATE_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_closed_interval_adjacency_is_overlap
        """
        program = create_program(name="P-OV2B")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        # Strictly inside the existing closed window.
        resp_inside = api_client.create_rate_schedule(create_rate_schedule_payload(
            program["id"], aid_category="TANF", pmpm_cents=51000,
            effective_from="2026-08-10", effective_to="2026-08-20"), STATE)
        validate_error(resp_inside, ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP)
        # Same dates under a different aid category do not collide.
        resp_chip = api_client.create_rate_schedule(create_rate_schedule_payload(
            program["id"], aid_category="CHIP", pmpm_cents=30000,
            effective_from="2026-08-10", effective_to="2026-08-20"), STATE)
        validate_success(resp_chip, expected_status=201)


class TestDeadlineExtensions:
    def test_extension_request_exactly_at_deadline_allowed(self):
        """PRD §3.3: "The request is then only admissible while the logical clock has
        not passed the cycle's current `effective_deadline_at` — a request exactly at
        the deadline is still inside the window, and anything later is rejected with
        `ERR_EXTENSION_WINDOW_CLOSED`"

        Design: Difficulty/boundary_precision_check/extension_request_exactly_at_deadline_allowed
        """
        program = create_program(name="P-BND2")
        cycle = create_cycle(program["id"])
        version_v1 = cycle["version"]

        set_clock("2026-09-15T00:00:00Z")
        requested = validate_success(api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-09-29T00:00:00Z",
            "reason": "clearinghouse outage",
            "expected_cycle_version": version_v1,
        }, COMP))
        assert requested["extension_status"] == "PENDING", "exactly at the deadline is still inside the window"

        denied = validate_success(api_client.deny_extension(cycle["id"], STATE))
        assert denied["extension_status"] == "DENIED"

        set_clock("2026-09-15T00:00:01Z")
        current = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        resp = api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-09-29T00:00:00Z",
            "reason": "retry after denial",
            "expected_cycle_version": current["version"],
        }, COMP)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED)

    def test_extension_request_at_deadline_records_pending_and_bumps_version(self):
        """PRD §3.3: "A granted request moves `extension_status` from `NONE` to
        `PENDING`, records the `requested_new_deadline_at`, and increments the cycle's
        `version`."
        PRD §3.3: "The request is then only admissible while the logical clock has not
        passed the cycle's current `effective_deadline_at` — a request exactly at the
        deadline is still inside the window, and anything later is rejected with
        `ERR_EXTENSION_WINDOW_CLOSED`"

        Design: Difficulty/boundary_precision_check/extension_request_exactly_at_deadline_allowed
        """
        program = create_program(name="P-BND2B")
        cycle = create_cycle(program["id"])
        set_clock("2026-09-15T00:00:00Z")
        requested = validate_success(api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-09-29T00:00:00Z",
            "reason": "boundary filing",
            "expected_cycle_version": cycle["version"],
        }, COMP))
        assert requested["extension_status"] == "PENDING"
        assert requested["requested_new_deadline_at"] == "2026-09-29T00:00:00Z"
        assert requested["version"] == cycle["version"] + 1
        # The effective deadline does not move until approval.
        assert requested["effective_deadline_at"] == "2026-09-15T00:00:00Z"

    def test_extension_regression_and_approve_without_pending_rejected(self):
        """PRD §3.3: "the requested deadline must be strictly later than the current
        effective deadline, never equal to or earlier, or the request is rejected with
        `ERR_EXTENSION_REGRESSION`."
        PRD §3.3: "Approval by a `StateAgency` operator requires `extension_status`
        `PENDING` — anything else draws `ERR_EXTENSION_NOT_PENDING` — and moves it to
        `APPROVED`, at which point the cycle's `effective_deadline_at` becomes the
        `requested_new_deadline_at`."

        Design: Corner/validations/extension_regression_and_approve_without_pending_rejected
        """
        program = create_program(name="P-V11")
        cycle = create_cycle(program["id"])
        version_v1 = cycle["version"]

        resp_r = api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-09-10T00:00:00Z",
            "reason": "backwards",
            "expected_cycle_version": version_v1,
        }, COMP)
        validate_error(resp_r, ApiErrorId.ERR_EXTENSION_REGRESSION)

        resp_a = api_client.approve_extension(cycle["id"], STATE)
        validate_error(resp_a, ApiErrorId.ERR_EXTENSION_NOT_PENDING)

        after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert after["extension_status"] == "NONE"
        assert after["version"] == version_v1, "failed requests must not advance the version"

    def test_extension_approve_applies_new_deadline_and_clears_lateness(self):
        """PRD §3.3: "Approval by a `StateAgency` operator requires `extension_status`
        `PENDING` — anything else draws `ERR_EXTENSION_NOT_PENDING` — and moves it to
        `APPROVED`, at which point the cycle's `effective_deadline_at` becomes the
        `requested_new_deadline_at`."
        PRD §3.5: "it is true exactly when `transmitted_at` falls strictly after the
        cycle's `effective_deadline_at`, with a transmission exactly at the deadline
        counting as on time."

        Design: Corner/state_machines/extension_approve_applies_new_deadline_and_clears_lateness
        """
        scenario = setup_basic_scenario(program_name="P-SM15")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)

        validate_success(api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-09-29T00:00:00Z",
            "reason": "vendor delay",
            "expected_cycle_version": cycle["version"],
        }, COMP))
        approved = validate_success(api_client.approve_extension(cycle["id"], STATE))
        assert approved["extension_status"] == "APPROVED"
        assert approved["effective_deadline_at"] == "2026-09-29T00:00:00Z"

        # Transmit between the old and new deadlines is on time.
        set_clock("2026-09-20T00:00:00Z")
        transmitted = validate_success(api_client.transmit_batch(batch["id"], COMP_TRANSMITTER))
        assert transmitted["late"] is False
        _data, meta = validate_paginated(api_client.list_penalties(STATE, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 0

    def test_occ_extension_request_stale_cycle_version_rejected(self):
        """PRD §2.7: "Requesting a deadline extension on a cycle requires the request to
        carry `expected_cycle_version`, holding the cycle `version` the client last
        observed. A mismatch against the cycle's current `version` is likewise rejected
        with `ERR_STALE_VERSION` (HTTP 412), leaving the cycle's extension posture
        unchanged."
        PRD §3.3: "Filing a fresh request while one is `PENDING` supersedes the pending
        request under the same version pin"

        Design: Corner/cross_cutting_complexity_layers/occ_extension_request_stale_cycle_version_rejected
        """
        program = create_program(name="P-OCC2")
        cycle = create_cycle(program["id"])
        version_v1 = cycle["version"]

        first = validate_success(api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-09-29T00:00:00Z",
            "reason": "first",
            "expected_cycle_version": version_v1,
        }, COMP))
        version_v2 = first["version"]
        assert first["extension_status"] == "PENDING"

        resp_stale = api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-10-05T00:00:00Z",
            "reason": "stale writer",
            "expected_cycle_version": version_v1,
        }, COMP)
        validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api_client.request_extension(cycle["id"], {
            "requested_new_deadline_at": "2026-10-05T00:00:00Z",
            "reason": "fresh writer supersedes pending",
            "expected_cycle_version": version_v2,
        }, COMP))
        assert fresh["requested_new_deadline_at"] == "2026-10-05T00:00:00Z"
        assert fresh["extension_status"] == "PENDING"


class TestMemberDisenrollment:
    def test_member_disenroll_twice_returns_invalid_state(self):
        """PRD §3.2: "Disenrollment moves a member from `ACTIVE` to `DISENROLLED` (a
        member in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`) by
        supplying a `disenrolled_date`; the member's `enrolled_to` is set to that date"

        Design: Corner/state_machines/member_disenroll_twice_returns_invalid_state
        """
        program = create_program(name="P-SM16")
        member = create_member(program["id"])
        first = validate_success(api_client.disenroll_member(member["id"], {"disenrolled_date": "2026-08-20"}, OPS))
        assert first["status"] == "DISENROLLED"
        resp = api_client.disenroll_member(member["id"], {"disenrolled_date": "2026-08-21"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api_client.get_member(member["id"], OPS))
        assert after["enrolled_to"] == "2026-08-20", "first disenroll date is untouched"


class TestScorecardRemediation:
    def test_scorecard_acknowledge_on_green_returns_invalid_state(self):
        """PRD §3.6: "an `McoEncounterOps` operator acknowledges remediation on a
        scorecard whose status is `OPEN` and whose tier is `RED` — remediation applies
        only to red holds, and any other combination is rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/scorecard_acknowledge_on_green_returns_invalid_state
        """
        scenario = setup_basic_scenario(program_name="P-SM13")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                   encounter_ref="E1")
        scorecard = get_scorecard_for(provider["id"], cycle["id"])
        assert scorecard["tier"] == "GREEN"
        assert scorecard["status"] == "OPEN"
        resp = api_client.acknowledge_scorecard_remediation(scorecard["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api_client.get_scorecard(scorecard["id"], OPS))
        assert after["status"] == "OPEN"
