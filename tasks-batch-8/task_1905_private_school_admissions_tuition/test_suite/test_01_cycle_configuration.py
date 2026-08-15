"""Cycle configuration: creation defaults and validation, open/close gates,
response envelopes, and the operational sweep's report shape."""
from test_helpers import (
    ApiErrorId,
    assert_sweep_result,
    create_cycle_payload,
    get_contract,
    get_cycle,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_cycle,
    make_open_world,
    pin_clock,
    run_sweep,
    set_clock,
    setup_issued_contract_world,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCycleCreation:
    def test_create_cycle_success_defaults(self, api, director_headers):
        """PRD §3.1: "A new cycle starts in `DRAFT` with `aid_committed_cents`
        at zero."
        PRD §3.1: "while `DRAFT` or `OPEN`, `pacing_cap_cents` is forty percent
        of `aid_budget_total_cents` rounded half-up to a whole cent (in `DRAFT`
        no acceptances can occur yet, so the figure is informational)".

        Design: Corner/entities/create_cycle_success_defaults
        """
        pin_clock()
        resp = api.create_cycle(create_cycle_payload(), director_headers)
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["aid_committed_cents"] == 0
        # round_half_up(0.40 * 18,050,000) == 7,220,000
        assert data["pacing_cap_cents"] == 7_220_000
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert is_iso8601_timestamp(data["created_at"])

    def test_create_cycle_missing_required_field_returns_invalid_request(
            self, api, director_headers):
        """PRD §2.7: "The body is well-formed, contains all required fields,
        and carries no unknown fields; failure is `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/create_cycle_missing_required_field_returns_invalid_request
        """
        pin_clock()
        payload = create_cycle_payload()
        del payload["academic_year"]
        resp = api.create_cycle(payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_cycle_deadline_ordering_rejected(self, api, director_headers):
        """PRD §3.1: "Their ordering is validated at creation: the early
        deadline must fall strictly before the regular deadline, the regular
        deadline strictly before the re-enrollment response deadline, and the
        re-enrollment response deadline at or before the melt deadline; any
        other arrangement is rejected with `ERR_VALIDATION`."

        Design: Corner/entities/create_cycle_deadline_ordering_rejected
        """
        pin_clock()
        payload = create_cycle_payload(
            regular_deadline_at="2026-11-01T00:00:00Z",  # == early: not strict
        )
        resp = api.create_cycle(payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 422)


class TestCycleStateGates:
    def test_open_cycle_without_sections_rejected(self, api, director_headers):
        """PRD §3.1: "Opening the cycle moves it `DRAFT` → `OPEN` and requires
        at least one grade section to exist; opening a sectionless cycle fails
        with `ERR_CYCLE_HAS_NO_SECTIONS`, and opening from any state other than
        `DRAFT` fails with `ERR_CYCLE_INVALID_STATE`."

        Design: Corner/state_machines/open_cycle_without_sections_rejected
        """
        cycle = make_cycle()
        resp = api.open_cycle(cycle["id"], director_headers)
        validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_NO_SECTIONS, 409)
        assert get_cycle(cycle["id"])["status"] == "DRAFT"

    def test_close_round_out_of_sequence_rejected(self, api, director_headers):
        """PRD §3.1: "A `round` value that does not match the cycle's current
        phase is rejected with `ERR_CYCLE_INVALID_STATE`, and a close invoked
        at or before that round's deadline is rejected with
        `ERR_ROUND_STILL_OPEN` — the close is only permitted once the logical
        clock has passed the deadline."

        Design: Corner/state_machines/close_round_out_of_sequence_rejected
        """
        world = make_open_world(with_session=False)
        # Past BOTH deadlines, so only the phase gate can fire on REGULAR.
        set_clock("2027-02-01T00:00:00Z")
        resp = api.close_round(world["cycle"]["id"], "REGULAR", director_headers)
        validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE, 409)
        assert get_cycle(world["cycle"]["id"])["status"] == "OPEN"

    def test_close_round_before_deadline_rejected(self, api, director_headers):
        """PRD §3.1: "a close invoked at or before that round's deadline is
        rejected with `ERR_ROUND_STILL_OPEN` — the close is only permitted once
        the logical clock has passed the deadline."

        Design: Corner/state_machines/close_round_before_deadline_rejected
        """
        world = make_open_world(with_session=False)
        # Exactly the early deadline instant: the round is still open.
        set_clock("2026-11-01T00:00:00Z")
        resp = api.close_round(world["cycle"]["id"], "EARLY", director_headers)
        validate_error(resp, ApiErrorId.ERR_ROUND_STILL_OPEN, 422)


class TestEnvelopes:
    def test_success_envelope_shape_on_reads(self, api, director_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.3: "Paginated list responses carry four fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/success_envelope_shape_on_reads
        """
        cycle = make_cycle()
        single = api.get_cycle(cycle["id"], director_headers)
        body = single.json()
        assert single.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        assert body["data"]["id"] == cycle["id"]

        data, meta = validate_paginated(api.list_cycles(director_headers))
        assert len(data) == 1
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 1 and meta["has_more"] is False

    def test_error_envelope_shape_on_failure(self, api, director_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        pin_clock()
        missing = "00000000-0000-4000-8000-0000000000dd"
        resp = api.get_cycle(missing, director_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert isinstance(error["message"], str) and error["message"].strip()


class TestSweepReporting:
    def test_run_sweep_output_shape(self, api, director_headers):
        """PRD §3.5: "The sweep reports what it did via `expired_offer_count`,
        `lapsed_contract_count`, `lapsed_reenrollment_count`,
        `expired_waitlist_count`, and the `promoted_application_ids` array."

        Design: Corner/endpoints/run_sweep_output_shape
        """
        world = make_open_world(with_session=False)
        data = validate_success(api.run_sweep(world["cycle"]["id"],
                                              director_headers))
        assert_sweep_result(data)

    def test_sweep_noop_returns_zero_counts(self, api, director_headers):
        """PRD §3.5: "An empty candidate set is not an error — nothing
        happens."
        PRD §3.5: "The sweep reports what it did via `expired_offer_count`,
        `lapsed_contract_count`, `lapsed_reenrollment_count`,
        `expired_waitlist_count`, and the `promoted_application_ids` array."

        Design: Corner/state_machines/sweep_noop_returns_zero_counts
        """
        world = make_open_world(with_session=False)
        data = run_sweep(world["cycle"]["id"])
        assert data["expired_offer_count"] == 0
        assert data["lapsed_contract_count"] == 0
        assert data["expired_waitlist_count"] == 0
        assert data["lapsed_reenrollment_count"] == 0
        assert data["promoted_application_ids"] == []

    def test_sweep_second_run_all_zero(self, api, director_headers):
        """PRD §3.6: "When the sweep finds the logical clock past
        `response_due_at` on a contract still `ISSUED` or `SIGNED`, the
        contract moves to `LAPSED`, and the lapse cascades in one request".
        PRD §3.5: "The sweep reports what it did via `expired_offer_count`,
        `lapsed_contract_count`, `lapsed_reenrollment_count`,
        `expired_waitlist_count`, and the `promoted_application_ids` array."

        Design: Corner/complexity_layers/sweep_second_run_all_zero
        """
        ctx = setup_issued_contract_world()  # contract due 2026-11-16
        contract_id = ctx["contract"]["id"]
        set_clock("2026-11-17T00:00:00Z")
        first = run_sweep(ctx["cycle"]["id"])
        assert first["lapsed_contract_count"] == 1
        second = run_sweep(ctx["cycle"]["id"])
        assert second["expired_offer_count"] == 0
        assert second["lapsed_contract_count"] == 0
        assert second["expired_waitlist_count"] == 0
        assert second["lapsed_reenrollment_count"] == 0
        assert second["promoted_application_ids"] == []
        # Terminal states are not re-processed by later sweeps.
        assert get_contract(contract_id)["status"] == "LAPSED"
