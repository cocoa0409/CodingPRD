"""Parcel creation, contingency lifecycle, response envelope, and access gates."""
from test_helpers import (
    DEV,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    ApiErrorId,
    assert_parcel,
    create_acquired_parcel,
    create_parcel,
    create_parcel_payload,
    get_parcel,
    is_iso8601_timestamp,
    open_contingency,
    parse_instant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestParcelCreation:
    def test_parcel_create_applies_defaults(self, api):
        """PRD §3.1: "Two planning fields shape later forecasting: `planned_sellout_months`, the number of months over which the developer expects to sell out (defaulting to 24 when omitted), and `absorption_method`, which selects which pace variant feeds the projections and takes one of exactly two values, `STRAIGHT_LINE` or `TRAILING_WEIGHTED`, defaulting to `STRAIGHT_LINE`."
        PRD §3.1: "A new parcel starts in `DRAFT` with all derived counters at zero and its `straight_line_pace_pm` at zero until lots are recorded."
        PRD §3.1: "The `earnest_money_refunded` flag is therefore true only on an in-period manual termination and false in every other circumstance, including auto-expiry."

        Design: Corner/entities/parcel_create_defaults_applied
        """
        data = validate_success(api.create_parcel(
            {"parcel_name": "DP", "county": "Travis", "earnest_money_cents": 100000},
            DEV), 201)
        assert_parcel(data)
        assert data["status"] == "DRAFT"
        assert data["absorption_method"] == "STRAIGHT_LINE"
        assert data["planned_sellout_months"] == 24
        assert data["total_lots_planned"] == 0
        assert data["lots_closed_count"] == 0
        assert data["lots_available_count"] == 0
        assert data["closed_pct"] == 0
        assert data["straight_line_pace_pm"] == 0
        assert data["earnest_money_refunded"] is False

    def test_parcel_create_missing_parcel_name_rejected(self, api):
        """PRD §3.1: "A `DeveloperOperator` begins the pipeline by creating a development parcel, supplying a `parcel_name`, the `county` the land sits in, and the `earnest_money_cents` deposit — a non-negative integer number of cents."
        PRD §2.8: "4. **Request shape** — required fields present, types correct, enum values valid, and payload-internal rules such as window ordering and line-item shape; violations yield `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, or `ERR_INVALID_CONTINGENCY_EXTENSION` (400)."

        Design: Corner/entities/parcel_create_missing_required_returns_invalid_request
        """
        resp = api.create_parcel(
            {"county": "Travis", "earnest_money_cents": 100000}, DEV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_parcel_get_unknown_id_returns_not_found(self, api):
        """PRD §2.8: "3. **Resource existence** — path identifiers are resolved first, in left-to-right order, followed by foreign keys carried in the request body (`parcel_id`, `builder_id`, `phase_id`, `lot_id`, `agreement_id`, `loan_id`, `provider_id`). The first unresolvable reference short-circuits the request with the matching not-found error: `ERR_PARCEL_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_BUILDER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CLOSING_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`, `ERR_HOA_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, or `ERR_CONNECTION_NOT_FOUND` (all 404)."

        Design: Corner/entities/parcel_get_not_found_returns_404
        """
        resp = api.get_parcel(NON_EXISTENT_UUID, DEV)
        validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_FOUND)

    def test_parcel_create_ignores_client_supplied_derived_counter(self, api):
        """PRD §2.9: "Several entities carry derived fields that the server recomputes on every relevant mutation rather than accepting from clients."
        PRD §3.1: "A new parcel starts in `DRAFT` with all derived counters at zero and its `straight_line_pace_pm` at zero until lots are recorded."

        Design: Corner/entities/computed_field_input_ignored
        """
        data = validate_success(api.create_parcel(
            {"parcel_name": "CP", "county": "Travis", "earnest_money_cents": 100000,
             "lots_closed_count": 99}, DEV), 201)
        assert data["lots_closed_count"] == 0, (
            "client-supplied derived counter must not be stored")


class TestResponseEnvelope:
    def test_success_envelope_shape_for_object_and_array(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.3: "The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0."

        Design: Corner/endpoints/response_envelope_shape_on_success
        """
        resp = api.create_parcel(
            create_parcel_payload(parcel_name="ENV"), DEV)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        created_id = body["data"]["id"]

        list_resp = api.list_parcels(DEV)
        assert list_resp.json()["response_type"] == "array"
        rows, list_meta = validate_paginated(list_resp)
        assert isinstance(rows, list)
        assert list_meta["limit"] == 10
        assert list_meta["offset"] == 0
        assert any(row["id"] == created_id for row in rows)


class TestAccessGates:
    def test_request_without_auth_headers_rejected(self, api):
        """PRD §2.1: "A request whose `X-User-Role` does not name one of these five roles, or whose `X-User-ID` is absent, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.create_parcel(
            {"parcel_name": "NOAUTH", "county": "Travis",
             "earnest_money_cents": 100000},
            NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_builder_rep_cannot_create_parcel(self, api, builder_rep_headers):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "| POST | `/api/parcels` | Create a development parcel (starts `DRAFT`) | DeveloperOperator |"

        Design: Corner/rbac/builder_rep_cannot_create_parcel_returns_403
        """
        resp = api.create_parcel(
            {"parcel_name": "RBP", "county": "Travis", "earnest_money_cents": 100000},
            builder_rep_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestContingencyLifecycle:
    def test_terminate_from_acquired_rejected(self, api):
        """PRD §3.1: "The same `ERR_PARCEL_INVALID_STATE` guards every parcel action's from-state: opening the contingency from anything other than `DRAFT`, and clearing, terminating, or extending from anything other than `CONTINGENCY_ACTIVE`."
        PRD §3.1: "The `earnest_money_refunded` flag is therefore true only on an in-period manual termination and false in every other circumstance, including auto-expiry."

        Design: Corner/state_machines/parcel_terminate_from_acquired_returns_invalid_state
        """
        parcel = create_acquired_parcel(parcel_name="SP")
        resp = api.terminate_contingency(parcel["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_PARCEL_INVALID_STATE)
        after = get_parcel(parcel["id"])
        assert after["status"] == "ACQUIRED"
        assert after["earnest_money_refunded"] is False

    def test_extend_contingency_not_strictly_later_rejected(self, api):
        """PRD §3.1: "While the contingency is active the developer may extend it: the extension operation is a self-loop that keeps the parcel in `CONTINGENCY_ACTIVE`, replaces `contingency_end_date` with the supplied `new_contingency_end_date`, and is rejected with `ERR_INVALID_CONTINGENCY_EXTENSION` unless the new date falls strictly later than the deadline currently on record."

        Design: Corner/validations/invalid_contingency_extension_returns_400
        """
        parcel = create_parcel(parcel_name="EP2")
        opened = open_contingency(parcel["id"], "2027-01-01T00:00:00Z")
        resp = api.extend_contingency(parcel["id"], {
            "new_contingency_end_date": "2026-12-01T00:00:00Z",
            "expected_parcel_version": opened["version"],
        }, DEV)
        validate_error(resp, ApiErrorId.ERR_INVALID_CONTINGENCY_EXTENSION)

    def test_occ_stale_parcel_version_rejected(self, api):
        """PRD §2.7: "Extending a parcel's contingency requires the request to carry `expected_parcel_version` holding the client's last observed `version` of the target `Parcel`. If the parcel's current `version` has advanced beyond what the client observed — because a prior extension or any other parcel mutation superseded the client's view of the deadline — the extension is rejected with `ERR_STALE_PARCEL_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_parcel_version_returns_412
        """
        parcel = create_parcel(parcel_name="OXP")
        opened = open_contingency(parcel["id"], "2027-01-01T00:00:00Z")
        observed_version = opened["version"]

        extended = validate_success(api.extend_contingency(parcel["id"], {
            "new_contingency_end_date": "2027-02-01T00:00:00Z",
            "expected_parcel_version": observed_version,
        }, DEV))
        assert parse_instant(extended["contingency_end_date"]) == parse_instant(
            "2027-02-01T00:00:00Z")
        assert extended["version"] == observed_version + 1

        stale = api.extend_contingency(parcel["id"], {
            "new_contingency_end_date": "2027-03-01T00:00:00Z",
            "expected_parcel_version": observed_version,
        }, DEV)
        validate_error(stale, ApiErrorId.ERR_STALE_PARCEL_VERSION)
        assert parse_instant(get_parcel(parcel["id"])["contingency_end_date"]) == \
            parse_instant("2027-02-01T00:00:00Z")


class TestContingencyDeadlineBoundary:
    def test_terminate_at_exact_deadline_refunds_deposit(self, api):
        """PRD §2.5: "Because the deadline is inclusive, setting the clock to exactly the contingency deadline does not trigger expiry — only a value strictly past it does."
        PRD §3.1: "Alternatively, the developer may walk away in-period by terminating the contingency, moving the parcel to `TERMINATED` with `earnest_money_refunded` set to true, recording that the deposit comes back."

        Design: Difficulty/boundary_precision_check/contingency_terminate_at_exact_deadline
        """
        parcel_a = create_parcel(parcel_name="PA")
        open_contingency(parcel_a["id"], "2026-09-01T00:00:00Z")
        parcel_b = create_parcel(parcel_name="PB")
        open_contingency(parcel_b["id"], "2026-09-01T00:00:00Z")

        set_clock("2026-09-01T00:00:00Z")
        terminated = validate_success(api.terminate_contingency(parcel_a["id"], DEV))
        assert terminated["status"] == "TERMINATED"
        assert terminated["earnest_money_refunded"] is True
        # the clock equal to the deadline does not auto-expire the sibling parcel
        assert get_parcel(parcel_b["id"])["status"] == "CONTINGENCY_ACTIVE"

    def test_clock_past_deadline_auto_expires_and_blocks_terminate(self, api):
        """PRD §3.1: "Timing matters here: if the clock has already been advanced strictly past the deadline, the parcel will have auto-expired to `TERMINATED` on its own (with `earnest_money_refunded` set to false — the deposit is forfeited on expiry), and the manual termination attempt is then rejected with `ERR_PARCEL_INVALID_STATE` because the parcel no longer sits in `CONTINGENCY_ACTIVE`."

        Design: Difficulty/boundary_precision_check/contingency_terminate_at_exact_deadline
        """
        parcel = create_parcel(parcel_name="PB")
        open_contingency(parcel["id"], "2026-09-01T00:00:00Z")

        set_clock("2026-09-01T00:00:01Z")
        expired = get_parcel(parcel["id"])
        assert expired["status"] == "TERMINATED"
        assert expired["earnest_money_refunded"] is False
        validate_error(api.terminate_contingency(parcel["id"], DEV),
                       ApiErrorId.ERR_PARCEL_INVALID_STATE)
