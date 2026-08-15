"""Productions, actor roster lifecycle, response envelope, and not-found errors."""
import pytest

from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    assert_actor,
    assert_production,
    assert_timestamp_ms,
    create_actor,
    create_actor_payload,
    create_booking,
    create_casting_call,
    create_production,
    create_production_payload,
    create_standby_entry,
    is_valid_uuid,
    lock_call,
    setup_published_call,
    setup_shooting_booking,
    start_shooting,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProductionCreation:
    def test_production_create_defaults(self, api, admin_headers):
        """PRD §3.1: "A new production sits in `SETUP` with a `compliance_index` of
        100 and `payroll_exposure_cents` of zero"
        PRD §2.4: "`id` (string): a server-minted unique identifier, formatted as a
        UUID with no type prefix." and "`created_at` (string): an ISO 8601 UTC
        timestamp with three fractional digits recording when the resource was
        created."

        Design: Corner/entities/production_create_defaults
        """
        res = api.create_production(
            create_production_payload(title="Film D"), admin_headers
        )
        prod = validate_success(res, 201)
        assert_production(prod)
        assert prod["status"] == "SETUP"
        assert prod["compliance_index"] == 100
        assert prod["payroll_exposure_cents"] == 0
        assert is_valid_uuid(prod["id"])
        assert isinstance(prod["version"], int) and prod["version"] >= 1
        assert_timestamp_ms(prod["created_at"])
        assert_timestamp_ms(prod["updated_at"])

    def test_production_create_system_fields_input_ignored(self, api, admin_headers):
        """PRD §3.1: "A new production sits in `SETUP` with a `compliance_index` of
        100 and `payroll_exposure_cents` of zero" — even when the create payload
        carries client-supplied status/compliance_index values.


        Design: Corner/entities/production_create_system_fields_input_ignored
        """
        res = api.create_production(
            create_production_payload(
                title="Film I", status="ACTIVE", compliance_index=5
            ),
            admin_headers,
        )
        prod = validate_success(res, 201)
        assert prod["status"] == "SETUP"
        assert prod["compliance_index"] == 100


class TestActorRoster:
    def test_actor_create_defaults(self, api, admin_headers):
        """PRD §3.1: "A registrant starts `REGISTERED` with a `no_show_count` of
        zero and a `reliability_score` of 100"

        Design: Corner/entities/actor_create_defaults
        """
        res = api.create_actor(
            create_actor_payload(legal_name="A One", union_status="SAG_AFTRA"),
            admin_headers,
        )
        actor = validate_success(res, 201)
        assert_actor(actor)
        assert actor["status"] == "REGISTERED"
        assert actor["no_show_count"] == 0
        assert actor["reliability_score"] == 100

    def test_actor_create_invalid_enum_returns_400(self, api, admin_headers):
        """PRD §2.10: "Body schema: required fields present, enum members valid,
        integer ranges respected — slot counts at least zero, rates, capacities,
        bump amounts, and planned durations strictly positive, waiver reductions at
        least zero (`ERR_VALIDATION`)."
        PRD §3.1: "their `union_status` of `SAG_AFTRA` or `NONUNION`"

        Design: Corner/validations/actor_create_invalid_enum_returns_400
        """
        res = api.create_actor(
            {"legal_name": "Bad Enum", "union_status": "GUILD"}, admin_headers
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION)

    def test_reinstate_resets_strikes(self, api, admin_headers):
        """PRD §3.1: "An administrator may later reinstate a `SUSPENDED` actor,
        which returns them to `ELIGIBLE`, resets `no_show_count` to zero,
        recomputes `reliability_score` to 100, and increments `version`."

        Design: Corner/state_machines/reinstate_resets_strikes
        """
        actor = create_actor("NONUNION")
        actor = validate_success(api.suspend_actor(actor["id"], admin_headers), 200)
        assert actor["status"] == "SUSPENDED"

        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        reinstated = validate_success(
            api.reinstate_actor(actor["id"], admin_headers), 200
        )
        assert reinstated["status"] == "ELIGIBLE"
        assert reinstated["no_show_count"] == 0
        assert reinstated["reliability_score"] == 100
        assert reinstated["version"] > actor["version"]

        booking = create_booking(call["id"], actor["id"])
        assert booking["status"] == "OFFERED"

    def test_suspension_cascades_offered_booking_and_standby(self, api, admin_headers):
        """PRD §3.1: "Either way the suspension cascade is identical: every booking
        the actor still holds in `OFFERED` moves to `EXPIRED`, every booking in
        `CONFIRMED` moves to `CANCELLED`, each of those releases its slot back to
        its casting call, every `ACTIVE` standby entry of the actor moves to
        `WITHDRAWN`, and the actor's `version` increments."

        Design: Corner/cross_cutting_complexity_layers/suspension_cascades_offered_booking_and_standby
        """
        prod = create_production(active=True)
        actor = create_actor("SAG_AFTRA")
        call_a = create_casting_call(
            prod["id"],
            publish=True,
            union_slots=1,
            nonunion_slots=0,
            location="Lot 85",
        )
        call_b = create_casting_call(
            prod["id"],
            publish=True,
            union_slots=1,
            nonunion_slots=0,
            location="Lot 86",
            shoot_date="2026-08-12",
            general_call_time="2026-08-12T07:00:00Z",
        )
        booking = create_booking(call_a["id"], actor["id"])
        entry = create_standby_entry(call_b["id"], actor["id"])

        suspended = validate_success(api.suspend_actor(actor["id"], admin_headers), 200)
        assert suspended["status"] == "SUSPENDED"

        booking_after = validate_success(
            api.get_booking(booking["id"], admin_headers), 200
        )
        assert booking_after["status"] == "EXPIRED"
        entry_after = validate_success(
            api.get_standby_entry(entry["id"], admin_headers), 200
        )
        assert entry_after["status"] == "WITHDRAWN"
        call_a_after = validate_success(
            api.get_casting_call(call_a["id"], admin_headers), 200
        )
        assert call_a_after["slots_available"] == 1


class TestProductionWrap:
    def test_production_wrap_blocked_with_open_call_returns_409(
        self, api, director_headers
    ):
        """PRD §3.1: "only once every casting call belonging to it has reached
        `WRAPPED` or `CANCELLED`; if any call is still live, the wrap is rejected
        with `ERR_PRODUCTION_NOT_WRAPPABLE`."

        Design: Corner/state_machines/production_wrap_blocked_with_open_call_returns_409
        """
        prod, call, actor, booking = setup_shooting_booking(
            union_status="NONUNION", union_slots=0, nonunion_slots=1
        )
        assert call is not None and booking is not None
        res = api.wrap_production(prod["id"], director_headers)
        validate_error(res, ApiErrorId.ERR_PRODUCTION_NOT_WRAPPABLE)
        prod_after = validate_success(
            api.get_production(prod["id"], director_headers), 200
        )
        assert prod_after["status"] == "ACTIVE"

    def test_production_wrap_success_after_call_wrapped(
        self, api, director_headers, associate_headers
    ):
        """PRD §3.1: "A successful wrap moves the production to `WRAPPED`, expires
        any still-`ACTIVE` standby entries across its calls, and increments its
        `version`."
        PRD §3.4: "Wrapping freezes the actuals: `actual_union_checkins` records
        the count of union bookings in `CHECKED_IN` or `WRAPPED` at that instant
        (the terminal-state precondition means none remain checked in in
        practice), and `actual_compliant` records whether that count reaches
        `required_union_slots`, exactly equal passing."

        Design: Corner/state_machines/production_wrap_success_after_call_wrapped
        """
        prod = create_production(active=True)
        call = create_casting_call(
            prod["id"], publish=True, union_slots=0, nonunion_slots=1
        )
        lock_call(call["id"])
        start_shooting(call["id"])
        wrapped_call = validate_success(
            api.wrap_casting_call(call["id"], associate_headers), 200
        )
        assert wrapped_call["status"] == "WRAPPED"
        assert wrapped_call["actual_compliant"] is True
        assert wrapped_call["actual_union_checkins"] == 0

        wrapped_prod = validate_success(
            api.wrap_production(prod["id"], director_headers), 200
        )
        assert wrapped_prod["status"] == "WRAPPED"
        assert wrapped_prod["compliance_index"] == 100


class TestEnvelopeAndNotFound:
    def test_production_get_not_found_returns_404(self, api, admin_headers):
        """PRD §2.10: "Existence of every identifier appearing in the path or body,
        validated left to right, each miss producing that resource's not-found
        error: `ERR_PRODUCTION_NOT_FOUND`, `ERR_ACTOR_NOT_FOUND`,
        `ERR_CASTING_CALL_NOT_FOUND`, `ERR_LOOK_REQUIREMENT_NOT_FOUND`,
        `ERR_HOLDING_AREA_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_TIME_EVENT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`,
        `ERR_BUMP_ADJUSTMENT_NOT_FOUND`, `ERR_PAYROLL_BATCH_NOT_FOUND`,
        `ERR_REPLACEMENT_CASE_NOT_FOUND`, `ERR_STANDBY_ENTRY_NOT_FOUND`, or
        `ERR_RATIO_WAIVER_NOT_FOUND`."

        Design: Corner/entities/production_get_not_found_returns_404
        """
        res = api.get_production(ABSENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_PRODUCTION_NOT_FOUND)

    def test_voucher_not_found_returns_404(self, api, payroll_headers):
        """PRD §2.10: "Existence of every identifier appearing in the path or body,
        validated left to right, each miss producing that resource's not-found
        error: `ERR_PRODUCTION_NOT_FOUND`, `ERR_ACTOR_NOT_FOUND`,
        `ERR_CASTING_CALL_NOT_FOUND`, `ERR_LOOK_REQUIREMENT_NOT_FOUND`,
        `ERR_HOLDING_AREA_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_TIME_EVENT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`,
        `ERR_BUMP_ADJUSTMENT_NOT_FOUND`, `ERR_PAYROLL_BATCH_NOT_FOUND`,
        `ERR_REPLACEMENT_CASE_NOT_FOUND`, `ERR_STANDBY_ENTRY_NOT_FOUND`, or
        `ERR_RATIO_WAIVER_NOT_FOUND`."

        Design: Corner/errors/voucher_not_found_returns_404
        """
        res = api.get_voucher(ABSENT_UUID, payroll_headers)
        validate_error(res, ApiErrorId.ERR_VOUCHER_NOT_FOUND)

    def test_not_found_sweep_returns_404(self, api, admin_headers):
        """PRD §2.10: "Existence of every identifier appearing in the path or body,
        validated left to right, each miss producing that resource's not-found
        error: `ERR_PRODUCTION_NOT_FOUND`, `ERR_ACTOR_NOT_FOUND`,
        `ERR_CASTING_CALL_NOT_FOUND`, `ERR_LOOK_REQUIREMENT_NOT_FOUND`,
        `ERR_HOLDING_AREA_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_TIME_EVENT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`,
        `ERR_BUMP_ADJUSTMENT_NOT_FOUND`, `ERR_PAYROLL_BATCH_NOT_FOUND`,
        `ERR_REPLACEMENT_CASE_NOT_FOUND`, `ERR_STANDBY_ENTRY_NOT_FOUND`, or
        `ERR_RATIO_WAIVER_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_returns_404
        """
        cases = [
            (api.get_actor, ApiErrorId.ERR_ACTOR_NOT_FOUND),
            (api.get_casting_call, ApiErrorId.ERR_CASTING_CALL_NOT_FOUND),
            (api.get_booking, ApiErrorId.ERR_BOOKING_NOT_FOUND),
            (api.get_holding_area, ApiErrorId.ERR_HOLDING_AREA_NOT_FOUND),
            (api.get_look_requirement, ApiErrorId.ERR_LOOK_REQUIREMENT_NOT_FOUND),
            (api.get_standby_entry, ApiErrorId.ERR_STANDBY_ENTRY_NOT_FOUND),
            (api.get_ratio_waiver, ApiErrorId.ERR_RATIO_WAIVER_NOT_FOUND),
            (api.get_replacement_case, ApiErrorId.ERR_REPLACEMENT_CASE_NOT_FOUND),
            (api.get_bump_adjustment, ApiErrorId.ERR_BUMP_ADJUSTMENT_NOT_FOUND),
            (api.get_time_event, ApiErrorId.ERR_TIME_EVENT_NOT_FOUND),
        ]
        for getter, error_id in cases:
            res = getter(ABSENT_UUID, admin_headers)
            validate_error(res, error_id)

    def test_response_envelope_on_error(self, api, admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_on_error
        """
        err_res = api.get_voucher(ABSENT_UUID, admin_headers)
        body = err_res.json()
        assert err_res.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_VOUCHER_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()

        ok_res = api.create_production(
            create_production_payload(title="Film E2"), admin_headers
        )
        ok_body = ok_res.json()
        assert ok_res.status_code == 201
        assert ok_body["response_type"] == "object"
        assert isinstance(ok_body["meta"]["api_request_id"], str)
        assert isinstance(ok_body["meta"]["api_request_timestamp"], str)
        assert ok_body["meta"]["api_request_id"].startswith("req_")


class TestPagination:
    def test_actors_list_pagination_defaults(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter skips a number of items from the
        start of the result set and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/actors_list_pagination_defaults
        """
        for i in range(1, 12):
            create_actor("NONUNION", verify=False, legal_name=f"P{i:02d}")

        page1_res = api.list_actors(admin_headers)
        data, meta = validate_paginated(page1_res)
        assert len(data) == 10
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 11
        assert meta["has_more"] is True

        page2_res = api.list_actors(admin_headers, params={"limit": 5, "offset": 10})
        data2, meta2 = validate_paginated(page2_res)
        assert len(data2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 11


class TestAuthentication:
    @pytest.mark.parametrize("mode", ["no_headers", "unknown_role"])
    def test_auth_missing_role_header_returns_400(self, api, mode):
        """PRD §2.1: "A request missing either header, or presenting a role name
        the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/auth_missing_role_header_returns_400
        """
        if mode == "no_headers":
            headers = {"Content-Type": "application/json"}
        else:
            headers = {
                "X-User-ID": "nobody-1",
                "X-User-Role": "Anonymous",
                "Content-Type": "application/json",
            }
        res = api.list_productions(headers)
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
