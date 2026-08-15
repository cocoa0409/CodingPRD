"""Client onboarding, lifecycle guards, termination cascade, and AUM (PRD §3.1)."""
from test_helpers import (
    ADVISOR,
    ApiErrorId,
    assert_client,
    create_active_client,
    create_active_ips,
    create_benchmark,
    create_client_payload,
    create_portfolio_payload,
    deposit,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_active_portfolio,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClientCreation:
    def test_client_create_missing_required_field_rejected(self, api):
        """PRD §3.1: "An `Advisor` opens a relationship by creating a client
        with the household's legal `full_name` and a `risk_tolerance_score`
        between 1 and 100 inclusive."
        PRD §2.7: "required fields present; types valid; enum values within
        their declared sets; ranges enforced (risk scores between 1 and 100
        inclusive; `target_pct` greater than 0 and at most 100; `band_pct`
        greater than 0 and at most 50; quantities at least 1 on intake;
        `amount_cents` greater than 0; price inputs at least 1;
        `review_cadence_months` between 1 and 24 inclusive; dates in
        `YYYY-MM-DD` form; datetimes in ISO 8601 UTC); a duplicate
        `asset_class` inside a `targets` array; unknown request fields — all
        rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/client_create_required_fields_defaults_and_initial_state
        """
        resp = api.create_client({"risk_tolerance_score": 50}, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_client_create_defaults_and_initial_state(self, api):
        """PRD §3.1: "The client begins life in `PROSPECT` status."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
        PRD §2.4: "`version` is an integer that increments by exactly one on
        every mutation of the resource"

        Design: Corner/entities/client_create_required_fields_defaults_and_initial_state
        """
        resp = api.create_client(
            create_client_payload(full_name="New Client", risk_tolerance_score=50),
            ADVISOR)
        client = validate_success(resp, 201)
        assert_client(client)
        assert client["status"] == "PROSPECT", "a new client is born PROSPECT"
        assert client["version"] == 1
        assert is_valid_uuid(client["id"])
        assert is_iso8601_timestamp(client["created_at"])

    def test_client_create_system_field_injection_rejected(self, api):
        """PRD §2.7: "unknown request fields — all rejected as
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/client_create_system_field_injection_rejected
        """
        resp = api.create_client(
            {"full_name": "Inject", "risk_tolerance_score": 50, "status": "ACTIVE"},
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(api.list_clients(ADVISOR))
        assert meta["total_count"] == 0, "no client was persisted"


class TestClientLifecycle:
    def test_terminate_requires_active_and_closed_portfolios(self, api):
        """PRD §3.1: "An `Advisor` terminates a client, moving it
        `ACTIVE → TERMINATED`, only when every portfolio of the client has
        `lifecycle_status` equal to `CLOSED`; otherwise the request is rejected
        with `ERR_CLIENT_INVALID_STATE`."
        PRD §3.1: "Activation, an `Advisor` action, moves the client
        `PROSPECT → ACTIVE`; attempting it from any other state is rejected
        with `ERR_CLIENT_INVALID_STATE`."

        Design: Corner/state_machines/client_lifecycle_terminal_lockdown_and_terminate_guard
        """
        ca = get_success_data(api.create_client(
            create_client_payload(full_name="A", risk_tolerance_score=50), ADVISOR))
        cb = get_success_data(api.create_client(
            create_client_payload(full_name="B", risk_tolerance_score=50), ADVISOR))
        # Terminate from PROSPECT: wrong from-state.
        validate_error(api.terminate_client(ca["id"], ADVISOR),
                       ApiErrorId.ERR_CLIENT_INVALID_STATE)
        ca = get_success_data(api.activate_client(ca["id"], ADVISOR))
        assert ca["status"] == "ACTIVE"
        # Double activate: wrong from-state.
        validate_error(api.activate_client(ca["id"], ADVISOR),
                       ApiErrorId.ERR_CLIENT_INVALID_STATE)
        # Terminate while a portfolio is still OPEN: guard fires.
        pb = get_success_data(api.create_portfolio(
            create_portfolio_payload(cb["id"], name="PB"), ADVISOR))
        get_success_data(api.activate_client(cb["id"], ADVISOR))
        validate_error(api.terminate_client(cb["id"], ADVISOR),
                       ApiErrorId.ERR_CLIENT_INVALID_STATE)
        assert pb["lifecycle_status"] == "OPEN"

    def test_terminated_client_is_terminal(self, api):
        """PRD §3.1: "`TERMINATED` is the client's terminal state".

        Design: Corner/state_machines/client_lifecycle_terminal_lockdown_and_terminate_guard
        """
        ca = create_active_client(full_name="A", risk_tolerance_score=50)
        terminated = validate_success(api.terminate_client(ca["id"], ADVISOR))
        assert terminated["status"] == "TERMINATED"
        # No transition out of TERMINATED.
        validate_error(api.activate_client(ca["id"], ADVISOR),
                       ApiErrorId.ERR_CLIENT_INVALID_STATE)
        validate_error(api.terminate_client(ca["id"], ADVISOR),
                       ApiErrorId.ERR_CLIENT_INVALID_STATE)

    def test_client_terminate_cascade_archives_ips(self, api):
        """PRD §3.1: "every IPS of the client in `DRAFT`, `PENDING_COMPLIANCE`,
        `PENDING_CLIENT`, or `ACTIVE` transitions to `ARCHIVED`".

        Design: Corner/state_machines/client_terminate_cascade_archives_ips
        """
        client = create_active_client(full_name="Term", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips1 = create_active_ips(client, bench, objective_text="V1",
                                 targets=[{"asset_class": "CASH_EQUIVALENT",
                                           "target_pct": 100.00, "band_pct": 50.00}])
        assert ips1["status"] == "ACTIVE"
        ips2 = get_success_data(api.create_ips(
            {"client_id": client["id"], "benchmark_id": bench["id"],
             "objective_text": "V2 draft", "risk_tolerance_score": 50}, ADVISOR))
        assert ips2["status"] == "DRAFT"
        terminated = validate_success(api.terminate_client(client["id"], ADVISOR))
        assert terminated["status"] == "TERMINATED"
        assert validate_success(api.get_ips(ips1["id"], ADVISOR))["status"] == "ARCHIVED"
        assert validate_success(api.get_ips(ips2["id"], ADVISOR))["status"] == "ARCHIVED"

    def test_client_total_aum_aggregation(self, api):
        """PRD §2.9: "A client's `total_aum_cents` is the sum of
        `total_value_cents` over that client's portfolios whose
        `lifecycle_status` is `OPEN`, `ACTIVE`, or `FROZEN`; `CLOSED`
        portfolios are excluded."

        Design: Corner/entities/client_total_aum_aggregation
        """
        fx = setup_active_portfolio(targets=[
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
        ], client_name="AUM Client")
        deposit(fx["portfolio"]["id"], 100000)
        p2 = get_success_data(api.create_portfolio(
            create_portfolio_payload(fx["client"]["id"], name="P2",
                                     tax_status="TAX_DEFERRED"), ADVISOR))
        get_success_data(api.activate_portfolio(p2["id"], ADVISOR))
        deposit(p2["id"], 50000)
        client = validate_success(api.get_client(fx["client"]["id"], ADVISOR))
        assert client["total_aum_cents"] == 150000, (
            f"expected 150000 across both non-CLOSED portfolios, got "
            f"{client['total_aum_cents']}")
