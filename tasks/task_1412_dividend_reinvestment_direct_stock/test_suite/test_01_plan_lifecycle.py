"""Plan entity basics, lifecycle cycles, terminal lockdown, OCC, envelope, auth."""
from test_helpers import (
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    assert_plan,
    create_active_plan,
    create_plan,
    create_plan_payload,
    get_plan,
    get_success_data,
    list_notices,
    make_participant_headers,
    register_participant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPlanEntityBasics:
    def test_plan_create_applies_field_defaults(self, api):
        """PRD §3.1: "`pricing_basis`, either `MARKET_CLOSE` or `FIVE_DAY_AVERAGE`,
        defaulting to `MARKET_CLOSE` when omitted; `basis_method`, either `FIFO`
        or `AVERAGE_COST`, defaulting to `FIFO`"
        PRD §3.1: "A new plan starts in `DRAFT` status."

        Design: Corner/entities/plan_create_applies_field_defaults
        """
        payload = create_plan_payload(issuer_name="Def Corp", ticker="DEF",
                                      name="DEF DRIP")
        del payload["pricing_basis"]
        del payload["basis_method"]
        resp = api.create_plan(payload, ADMIN)
        plan = validate_success(resp, expected_status=201)
        assert_plan(plan)
        assert plan["pricing_basis"] == "MARKET_CLOSE", \
            "omitted pricing_basis must default to MARKET_CLOSE"
        assert plan["basis_method"] == "FIFO", \
            "omitted basis_method must default to FIFO"
        assert plan["status"] == "DRAFT", "a new plan starts in DRAFT"

    def test_plan_create_missing_required_name(self, api):
        """PRD §2.11: "then request body shape — required fields present, enum
        members valid, and numeric ranges sane, such as strictly positive
        quantities and amounts and the participation-election percentage rules —
        reported as `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "The creation payload names the issuer through `issuer_name`
        and `ticker` plus a display `name`"

        Design: Corner/entities/plan_create_missing_required_name
        """
        payload = create_plan_payload(issuer_name="NoName Corp", ticker="NN")
        del payload["name"]
        resp = api.create_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_plan_not_found_returns_404(self, api):
        """PRD §2.8: "For any request whose path addresses nested resources,
        path-templated identifiers are resolved strictly left to right, and the
        request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve, before any later identifier or
        business rule is examined."

        Design: Corner/entities/get_plan_not_found_returns_404
        """
        resp = api.get_plan(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEnvelopeAndPagination:
    def test_plans_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the start of the result set and
        defaults to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/plans_list_pagination_defaults
        """
        for i in range(1, 12):
            get_success_data(api.create_plan(
                create_plan_payload(issuer_name="Pg Corp", ticker=f"PG{i}",
                                    name=f"PG DRIP {i}"), ADMIN))
        resp = api.list_plans(ADMIN)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 10, f"default page must hold 10 items, got {len(data)}"
        assert meta["total_count"] == 11
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_response_envelope_shape_on_single_get(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_shape_on_single_get
        """
        plan = create_plan(issuer_name="Env Corp", ticker="ENV", name="ENV DRIP")
        resp = api.get_plan(plan["id"], ADMIN)
        data = validate_success(resp)
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert data["id"] == plan["id"]


class TestAuthentication:
    def test_unauthenticated_missing_headers(self, api):
        """PRD §2.1: "A request with missing headers, or whose declared role is
        not one of these two, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        resp = api.list_plans(NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestPlanSharedRead:
    def test_participant_shared_read_of_plan_allowed(self, api):
        """PRD §3.1: "Plans can be listed (optionally filtered by `status`) and
        read individually by either role."

        Design: Corner/rbac/participant_shared_read_of_plan_allowed
        """
        plan = create_active_plan(issuer_name="Pub Corp", ticker="PUB",
                                  name="PUB DRIP")
        participant = register_participant("Pat Pb", "ppb@x.com")
        resp = api.get_plan(plan["id"], make_participant_headers(participant["id"]))
        data = validate_success(resp)
        assert data["id"] == plan["id"]
        assert data["status"] == "ACTIVE"


class TestPlanSuspendResumeCycle:
    def test_plan_suspend_resume_cycle_statuses(self, api):
        """PRD §3.7: "Suspension — whether invoked directly by an administrator
        or delivered through a `SUSPENSION` notice — moves an `ACTIVE` plan to
        `SUSPENDED` and cascades."
        PRD §3.7: "Resumption moves a `SUSPENDED` plan back to `ACTIVE` and
        restores every `SUSPENDED` enrollment of the plan to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/plan_suspend_resume_cycle
        """
        plan = create_active_plan(issuer_name="Cyc Corp", ticker="CYC",
                                  name="CYC DRIP")
        assert plan["status"] == "ACTIVE", "publish moves the plan to ACTIVE"

        statuses = []
        statuses.append(validate_success(api.suspend_plan(plan["id"], ADMIN))["status"])
        statuses.append(validate_success(api.resume_plan(plan["id"], ADMIN))["status"])
        statuses.append(validate_success(api.suspend_plan(plan["id"], ADMIN))["status"])
        statuses.append(validate_success(api.resume_plan(plan["id"], ADMIN))["status"])
        assert statuses == ["SUSPENDED", "ACTIVE", "SUSPENDED", "ACTIVE"], (
            f"two full ACTIVE<->SUSPENDED cycles must be traversable, got {statuses}")
        assert get_plan(plan["id"])["status"] == "ACTIVE"

    def test_plan_suspend_resume_cycle_version_increments(self, api):
        """PRD §2.6: "and `version`, an integer that increments by exactly 1 on
        every mutation of the resource, including mutations produced by system
        cascades."
        PRD §3.1: "Publishing moves the plan from `DRAFT` to `ACTIVE` and
        increments its `version`."

        Design: Difficulty/non_linear_state_machine/plan_suspend_resume_cycle
        """
        plan = create_active_plan(issuer_name="Cyc Corp", ticker="CYC",
                                  name="CYC DRIP")
        observed = plan["version"]
        for transition in (api.suspend_plan, api.resume_plan,
                           api.suspend_plan, api.resume_plan):
            plan = validate_success(transition(plan["id"], ADMIN))
            assert plan["version"] == observed + 1, (
                f"each transition must increment version by exactly 1: "
                f"{observed} -> {plan['version']}")
            observed = plan["version"]


class TestPlanTerminalLockdown:
    def test_plan_terminated_terminal_lockdown(self, api):
        """PRD §2.8: "Any state-machine trigger attempted from a state where it
        is not defined — including any action against an entity already in a
        terminal state, or repeating a transition already taken — is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.1: "A plan's endgame is termination, available from either
        `ACTIVE` or `SUSPENDED`; terminating a plan drags every non-terminal
        enrollment of the plan through the full termination cascade of §3.9."

        Design: Corner/state_machines/plan_terminated_terminal_lockdown
        """
        plan = create_active_plan(issuer_name="Lock Corp", ticker="LCK",
                                  name="LCK DRIP")
        plan = validate_success(api.terminate_plan(plan["id"], ADMIN))
        assert plan["status"] == "TERMINATED"

        resp_resume = api.resume_plan(plan["id"], ADMIN)
        validate_error(resp_resume, ApiErrorId.ERR_INVALID_STATE)
        resp_suspend = api.suspend_plan(plan["id"], ADMIN)
        validate_error(resp_suspend, ApiErrorId.ERR_INVALID_STATE)
        assert get_plan(plan["id"])["status"] == "TERMINATED", \
            "TERMINATED is terminal; rejected triggers leave the plan untouched"


class TestPlanModifyOcc:
    def test_occ_plan_modify_stale_version(self, api):
        """PRD §2.7: "A `PATCH /drip/plans/{id}` request must carry
        `expected_plan_version`, holding the value of the plan's `version` the
        client last observed. If the plan's current `version` no longer matches —
        because an intervening mutation has advanced it — the modification is
        rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), since the client's
        edits were computed against a stale configuration of discounts, limits,
        and fees and applying them would silently overwrite the intervening
        modification."
        PRD §3.1: "When the modified plan is `ACTIVE` at the time, the
        modification additionally auto-creates a `DRAFT` plan notice of type
        `MODIFICATION`, which must still go through the publication flow of §3.7"

        Design: Corner/cross_cutting_layers/occ_plan_modify_stale_version
        """
        plan = create_active_plan(issuer_name="Occ Corp", ticker="OCC",
                                  name="OCC DRIP")
        observed_version = plan["version"]

        first = api.patch_plan(plan["id"], {
            "expected_plan_version": observed_version,
            "discount_pct": 0.03,
        }, ADMIN)
        patched = validate_success(first)
        assert patched["discount_pct"] == 0.03
        assert patched["version"] == observed_version + 1, \
            "a successful modification increments the plan's version by exactly 1"

        replay = api.patch_plan(plan["id"], {
            "expected_plan_version": observed_version,
            "discount_pct": 0.04,
        }, ADMIN)
        validate_error(replay, ApiErrorId.ERR_STALE_PLAN_VERSION)

        notices = list_notices(plan["id"])
        mod_notices = [n for n in notices if n["notice_type"] == "MODIFICATION"]
        assert len(mod_notices) == 1, \
            "the successful PATCH on an ACTIVE plan auto-creates one MODIFICATION notice"
        assert mod_notices[0]["status"] == "DRAFT"
