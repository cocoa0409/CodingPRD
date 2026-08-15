"""Grower registration/suspension, load intake gates, quota history records."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_warehouse,
    api_client,
    assert_grower,
    assert_quota_history,
    clear_aflatoxin,
    create_grower_payload,
    create_quota_history_payload,
    get_buying_point,
    get_grower,
    grade_load,
    make_grower_headers,
    report_load,
    setup_buying_point,
    setup_grower,
    setup_settlement_foundation,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_load,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK_1 = TEST_USERS["clerk_1_headers"]


class TestGrowerRegistration:

    def test_grower_created_with_system_defaults(self):
        """PRD section 3.2: "A new grower starts `ACTIVE` with
        `no_show_strikes` at zero."
        PRD section 2.4: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD section 2.4: "`created_at` (string): an ISO 8601 UTC timestamp with
        three fractional digits, set when the resource is created."

        Design: Corner/entities/grower_created_with_system_defaults
        """
        grower = setup_grower()
        assert_grower(grower)
        assert grower["status"] == "ACTIVE"
        assert grower["no_show_strikes"] == 0
        assert isinstance(grower["version"], int) and grower["version"] >= 1
        # three fractional digits on created_at
        assert grower["created_at"].endswith("Z")
        frac = grower["created_at"].split(".")[-1].rstrip("Z")
        assert len(frac) == 3, \
            f"created_at must carry three fractional digits: {grower['created_at']}"

    def test_reinstate_active_grower_rejected(self):
        """PRD section 3.2: "Reinstating a `SUSPENDED` grower returns it to
        `ACTIVE` and resets `no_show_strikes` to zero."
        PRD section 2.9: "**State preconditions** — the target resource is in a
        valid from-state, and state-gated creations are satisfied
        (`ERR_INVALID_STATE`, including the specialized grower-suspension,
        intake-suspension, and drying gate codes described in §3)."

        Design: Corner/state_machines/reinstate_active_grower_rejected
        """
        setup_buying_point()
        grower = setup_grower()
        resp = api_client.reinstate_grower(grower["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_grower(grower["id"])["status"] == "ACTIVE"


class TestLoadIntake:

    def test_load_create_missing_required_grower_id(self):
        """PRD section 3.3: "The payload is just `grower_id` and `crop_year`".
        PRD section 2.9: "**Request schema** — required fields present, types
        valid, enum values in range, and numeric constraints satisfied
        (positive tonnages, percentages within 0 to 100, positive
        `amount_cents`): `ERR_INVALID_REQUEST`."

        Design: Corner/entities/load_create_missing_required_grower_id
        """
        setup_buying_point()
        resp = api_client.create_load({"crop_year": 2026}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_weigh_twice_returns_invalid_state(self):
        """PRD section 3.3: "Recording a weight supplies `gross_tons` —
        strictly positive, at most three decimal places — stamps `weighed_at`
        from the logical clock, moves the load from `REPORTED` to `WEIGHED`,
        and increments the load's `version`."
        PRD section 2.9: "**State preconditions** — the target resource is in a
        valid from-state, and state-gated creations are satisfied
        (`ERR_INVALID_STATE`, including the specialized grower-suspension,
        intake-suspension, and drying gate codes described in §3)."

        Design: Corner/state_machines/weigh_twice_returns_invalid_state
        """
        bp = setup_buying_point()
        add_warehouse(bp["id"])
        grower = setup_grower()
        load = report_load(grower["id"])
        weigh_load(load["id"], 25.0)

        resp = api_client.weigh_load(load["id"], {"gross_tons": 30.0}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = api_client.get_load(load["id"], ADMIN).json()["data"]
        assert after["status"] == "WEIGHED"
        assert after["gross_tons"] == 25.0

    def test_settlement_clerk_cannot_weigh_returns_forbidden(self):
        """PRD section 4: the weigh endpoint row lists only `BuyingPointAdmin`.
        PRD section 2.1: "A request whose role is recognized but not permitted
        for the target operation is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/settlement_clerk_cannot_weigh_returns_forbidden
        """
        bp = setup_buying_point()
        add_warehouse(bp["id"])
        grower = setup_grower()
        load = report_load(grower["id"])
        resp = api_client.weigh_load(load["id"], {"gross_tons": 25.0}, CLERK_1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = api_client.get_load(load["id"], ADMIN).json()["data"]
        assert after["status"] == "REPORTED"
        assert after["gross_tons"] is None

    def test_grower_cannot_create_load_for_other_grower(self):
        """PRD section 2.1: "ownership checks on any resource that references a
        grower — a load's `grower_id`, a pledge's `grower_id`, a settlement's
        `grower_id`, a quota history's `grower_id` — compare that field to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_OWNERSHIP_FORBIDDEN`."

        Design: Corner/rbac/grower_cannot_create_load_for_other_grower
        """
        bp = setup_buying_point()
        add_warehouse(bp["id"])
        grower_a = setup_grower(name="Grower A", farm_number="F-1001")
        grower_b = setup_grower(name="Grower B", farm_number="F-1002")
        resp = api_client.create_load(
            {"grower_id": grower_a["id"], "crop_year": 2026},
            make_grower_headers(grower_b["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_FORBIDDEN)

    def test_grower_list_scoped_to_own_loads(self):
        """PRD section 2.1: "a `Grower` listing loads, pledges, settlements, or
        quota histories sees only its own".
        PRD section 3.3: "a `Grower`-role listing is auto-scoped to the
        caller's own loads."

        Design: Corner/rbac/grower_list_scoped_to_own_loads
        """
        bp = setup_buying_point()
        add_warehouse(bp["id"])
        g1 = setup_grower(name="Grower One", farm_number="F-1001")
        g2 = setup_grower(name="Grower Two", farm_number="F-1002")
        report_load(g1["id"])
        report_load(g2["id"])

        resp = api_client.list_loads(make_grower_headers(g1["id"]))
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["grower_id"] == g1["id"]

        resp = api_client.list_loads(ADMIN)
        _data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2


class TestGrowerSuspensionGate:

    def test_suspended_grower_load_create_rejected_both_roles(self):
        """PRD section 3.3: "the grower must be `ACTIVE`, or the report is
        rejected with `ERR_GROWER_SUSPENDED`".
        PRD section 3.6: "while suspended the grower cannot report new loads
        (§3.3)."

        Design: Difficulty/cross_entity_state_dependency/load_create_blocked_when_grower_suspended
        """
        bp = setup_buying_point()
        add_warehouse(bp["id"])
        grower = setup_grower()
        api_client.suspend_grower(grower["id"], ADMIN)

        resp = api_client.create_load(
            {"grower_id": grower["id"], "crop_year": 2026},
            make_grower_headers(grower["id"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_SUSPENDED)

        resp = api_client.create_load(
            {"grower_id": grower["id"], "crop_year": 2026}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_GROWER_SUSPENDED)

    def test_reinstated_grower_reports_again(self):
        """PRD section 3.2: "Reinstating a `SUSPENDED` grower returns it to
        `ACTIVE` and resets `no_show_strikes` to zero."
        PRD section 3.3: "A reported load opens with `status` `REPORTED`,
        `aflatoxin_status` `UNTESTED`, and `drying_status` `NOT_REQUIRED`".

        Design: Difficulty/cross_entity_state_dependency/load_create_blocked_when_grower_suspended
        """
        bp = setup_buying_point()
        add_warehouse(bp["id"])
        grower = setup_grower()
        api_client.suspend_grower(grower["id"], ADMIN)

        reinstated = api_client.reinstate_grower(grower["id"], ADMIN)
        data = validate_success(reinstated)
        assert data["status"] == "ACTIVE"
        assert data["no_show_strikes"] == 0

        load = report_load(grower["id"])
        assert load["status"] == "REPORTED"
        assert load["aflatoxin_status"] == "UNTESTED"
        assert load["drying_status"] == "NOT_REQUIRED"
        assert get_grower(grower["id"])["no_show_strikes"] == 0


class TestLoadListingFilters:

    def test_list_filter_by_enum_status(self):
        """PRD section 3.3: "Loads may be listed with `grower_id`, `status`,
        `aflatoxin_status`, and `settlement_id` filters".
        PRD section 3.5: "Confirmation maps the determination onto the load —
        `aflatoxin_status` becomes `PASSED`, `SEGREGATED`, or `REJECTED`
        respectively".

        Design: Corner/endpoints/list_filter_by_enum_status
        """
        f = setup_settlement_foundation()
        gid = f["grower"]["id"]
        load_a = report_load(gid)
        weighed_a = weigh_load(load_a["id"], 25.0)
        grade_load(load_a["id"], weighed_a["version"])
        clear_aflatoxin(load_a["id"], result_ppb=8.0, sample_ref="S-A")

        load_b = report_load(gid)
        weighed_b = weigh_load(load_b["id"], 25.0)
        grade_load(load_b["id"], weighed_b["version"])
        clear_aflatoxin(load_b["id"], result_ppb=18.5, sample_ref="S-B")

        resp = api_client.list_loads(ADMIN, params={"aflatoxin_status": "PASSED"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["id"] == load_a["id"]

        resp = api_client.list_loads(ADMIN,
                                     params={"aflatoxin_status": "SEGREGATED"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["id"] == load_b["id"]


class TestQuotaHistory:

    def test_quota_history_duplicate_rejected(self):
        """PRD section 3.2: "At most one quota history may exist per grower per
        crop year — a second record for the same pair is rejected with
        `ERR_DUPLICATE_QUOTA_HISTORY`."
        PRD section 3.2: "A quota history begins with `used_quota_tons` at
        zero".

        Design: Corner/entities/quota_history_duplicate_rejected
        """
        setup_buying_point()
        grower = setup_grower()
        api_client.create_quota_history(
            create_quota_history_payload(grower_id=grower["id"], crop_year=2026,
                                         quota_tons=100), ADMIN)

        resp = api_client.create_quota_history(
            create_quota_history_payload(grower_id=grower["id"], crop_year=2026,
                                         quota_tons=50), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUOTA_HISTORY)

        resp = api_client.create_quota_history(
            create_quota_history_payload(grower_id=grower["id"], crop_year=2027,
                                         quota_tons=80), ADMIN)
        qh2 = validate_success(resp, expected_status=201)
        assert_quota_history(qh2)
        assert qh2["used_quota_tons"] == 0
