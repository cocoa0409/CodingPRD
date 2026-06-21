"""Resource creation, schema/type validation, RBAC, and pagination.

Translates queue B (Corner) instances from sections entities, validations,
errors, and rbac that assert PRD-stated creation defaults and rejection rules.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    is_valid_uuid,
    assert_site,
    assert_stall,
    assert_meter_event,
    create_site_payload,
    create_stall_payload,
    create_tariff_payload,
    create_emsp_payload,
    create_driver_payload,
    create_session_payload,
    TEST_USERS,
    make_driver_headers,
    setup_environment,
    create_emsp,
    create_driver,
    create_site,
    set_clock,
    start_session,
    post_meter,
)

CPO = TEST_USERS["cpo_headers"]
STATION = TEST_USERS["station_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_site_returns_201_with_computed_defaults(api):
    """PRD §3.1: "A site also exposes two computed read-only fields:
    `allocated_total_kw`, the sum of `allocated_power_kw` across the site's sessions
    whose `charging_status` is `CHARGING`, recomputed on every load-balance run;
    and `active_session_count`, the number of the site's sessions whose
    `charging_status` is one of `PREPARING`, `CHARGING`, or `SUSPENDED`."

    Design: Corner/entities/create_site_returns_201_with_computed_defaults
    """
    resp = api.create_site(create_site_payload(name="S1", circuit_limit_kw=150,
                                               demand_charge_threshold_kw=120), CPO)
    data = validate_success(resp, expected_status=201)
    assert_site(data)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["allocated_total_kw"] == 0, "allocated_total_kw defaults to 0 with no sessions"
    assert data["active_session_count"] == 0, "active_session_count defaults to 0 with no sessions"


def test_create_site_missing_required_circuit_limit_returns_invalid_request(api):
    """PRD §3.1: "A site is created with a human-readable `name`, which must be
    non-empty, and a `circuit_limit_kw` greater than zero that represents the total
    grid circuit power budget shared by every stall at the site."
    PRD §2.7: "request-body schema conformance — required fields present, types
    valid, and enum values within their declared sets (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_site_missing_required_circuit_limit_returns_invalid_request
    """
    resp = api.create_site({"name": "S2", "demand_charge_threshold_kw": 100}, CPO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_site_threshold_exceeds_circuit_returns_over_circuit_limit(api):
    """PRD §3.1: "it must be greater than zero and may not exceed `circuit_limit_kw`,
    and a request that supplies a threshold larger than the circuit limit is
    rejected with `ERR_OVER_CIRCUIT_LIMIT`."

    Design: Corner/entities/create_site_threshold_exceeds_circuit_returns_over_circuit_limit
    """
    resp = api.create_site(create_site_payload(name="S3", circuit_limit_kw=100,
                                               demand_charge_threshold_kw=150), CPO)
    validate_error(resp, ApiErrorId.ERR_OVER_CIRCUIT_LIMIT.value)


def test_get_site_not_found_returns_404(api):
    """PRD §2.6: "The first identifier that does not resolve causes the request to
    be rejected immediately with `ERR_NOT_FOUND`, before any later identifier or
    business rule is evaluated."

    Design: Corner/entities/get_site_not_found_returns_404
    """
    resp = api.get_site(NON_EXISTENT, CPO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_stall_ocpp_status_defaults_available_system_field(api):
    """PRD §3.1: "An optional `reservation_priority` integer, defaulting to 100 and
    required to be at least 1, ranks the stall in the `PRIORITY` allocation
    waterfall". PRD §3.1: "Each stall also carries an OCPP-reported posture in its
    `ocpp_status` field, which is one of `AVAILABLE`, `OCCUPIED`, `FAULTED`, or
    `UNAVAILABLE` and starts at `AVAILABLE`."

    Design: Corner/entities/stall_ocpp_status_defaults_available_system_field
    """
    site = create_site(name="SX", circuit_limit_kw=100, demand_charge_threshold_kw=100)
    resp = api.create_stall(create_stall_payload(site["id"], connector_type="NACS",
                                                 max_power_kw=50), CPO)
    data = validate_success(resp, expected_status=201)
    assert_stall(data)
    assert data["ocpp_status"] == "AVAILABLE", "new stall starts AVAILABLE"
    assert data["reservation_priority"] == 100, "reservation_priority defaults to 100"


def test_tariff_invalid_tier_order_returns_invalid_tiers(api):
    """PRD §3.3: "If a tariff is submitted with `energy_tier_2_max_kwh` less than or
    equal to `energy_tier_1_max_kwh`, or with `effective_to` earlier than
    `effective_from`, the request is rejected with `ERR_TARIFF_INVALID_TIERS`."

    Design: Corner/entities/tariff_invalid_tier_order_returns_invalid_tiers
    """
    site = create_site(name="STier", circuit_limit_kw=100, demand_charge_threshold_kw=100)
    resp = api.create_tariff(
        create_tariff_payload(site["id"], connector_type="CCS",
                              energy_tier_1_max_kwh=30, energy_tier_2_max_kwh=20),
        CPO,
    )
    validate_error(resp, ApiErrorId.ERR_TARIFF_INVALID_TIERS.value)


def test_meter_event_immutable_no_version_field(api):
    """PRD §2.4: "One resource is deliberately immutable after creation: a
    `MeterEvent`, the OCPP meter sample, carries only an `id` and a `created_at`.
    It has no `updated_at` and no `version`, because a meter reading, once recorded,
    is never modified."

    Design: Corner/entities/meter_event_immutable_no_version_field
    """
    env = setup_environment(email="mev@x.com")
    sess = start_session(env["stall"]["id"], env["driver"]["id"])
    resp = api.create_meter_event(
        sess["id"], {"meter_kwh": 0, "sampled_at": "2026-06-01T00:00:00Z",
                     "reading_context": "TRANSACTION_BEGIN"}, STATION,
    )
    data = validate_success(resp, expected_status=201)
    assert_meter_event(data)
    assert "version" not in data, "MeterEvent response must not carry a version field"
    assert "updated_at" not in data, "MeterEvent response must not carry an updated_at field"


def test_pagination_limit_out_of_bounds_returns_invalid_request(api):
    """PRD §2.3: "A `limit` or `offset` outside its permitted bounds on a list
    endpoint is rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/validations/pagination_limit_out_of_bounds_returns_invalid_request
    """
    resp = api.list_sites(CPO, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


def test_wallet_adjustment_below_zero_rejected(api):
    """PRD §3.2: "the adjustment increments `wallet_balance_cents`, but any
    adjustment that would drive the balance below zero is rejected with
    `ERR_NEGATIVE_WALLET`."

    Design: Corner/endpoints/wallet_adjustment_below_zero_rejected
    """
    emsp = create_emsp(commission_pct=0.05)
    driver = create_driver(emsp["id"], email="nw@x.com", fund=50)
    resp = api.adjust_wallet(driver["id"], {"amount_cents": -100}, CPO)
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_WALLET.value)


def test_list_stalls_under_site_reverse_reachability(api):
    """PRD §2.3: "The `meta` object of every list response carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: "GET `/api/sites/{id}/stalls` List stalls under a site".

    Design: Corner/endpoints/list_stalls_under_site_reverse_reachability
    """
    site = create_site(name="SLS", circuit_limit_kw=100, demand_charge_threshold_kw=100)
    api.create_stall(create_stall_payload(site["id"], connector_type="CCS", max_power_kw=60), CPO)
    api.create_stall(create_stall_payload(site["id"], connector_type="NACS", max_power_kw=50), CPO)
    resp = api.list_site_stalls(site["id"], CPO)
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 stalls, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is False, "has_more must be false for a 2-of-2 page"


def test_confirm_reservation_insufficient_hold_funds(api):
    """PRD §3.5: "confirmation charges the deposit by debiting the driver's
    `wallet_balance_cents` by `hold_fee_cents` and increments the reservation's
    `version`. If that debit would drive the driver's `wallet_balance_cents` below
    zero, the confirmation is rejected with `ERR_INSUFFICIENT_WALLET_HOLD`."

    Design: Corner/errors/confirm_reservation_insufficient_hold_funds
    """
    set_clock("2026-06-01T08:00:00Z")
    emsp = create_emsp(commission_pct=0.05)
    driver = create_driver(emsp["id"], email="hf@x.com", fund=100)
    site = create_site(name="SHF", circuit_limit_kw=200, demand_charge_threshold_kw=200)
    stall = validate_success(
        api.create_stall(create_stall_payload(site["id"], connector_type="CCS", max_power_kw=60), CPO),
        expected_status=201,
    )
    rid = validate_success(
        api.create_reservation(
            {"stall_id": stall["id"], "driver_id": driver["id"],
             "window_start": "2026-06-01T09:00:00Z", "window_end": "2026-06-01T10:00:00Z",
             "hold_fee_cents": 500, "expected_stall_version": stall["version"]},
            make_driver_headers(driver["id"]),
        ),
        expected_status=201,
    )["id"]
    resp = api.confirm_reservation(rid, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET_HOLD.value)


class TestRbac:
    def test_driver_cannot_create_site_returns_forbidden(self, api):
        """PRD §2.1: "When the headers are valid but the named role is not permitted
        to invoke the requested endpoint per the role matrix in §4, the request is
        rejected with `ERR_FORBIDDEN`." PRD §4: POST `/api/sites` is CPOOperator-only.

        Design: Corner/rbac/driver_cannot_create_site_returns_forbidden
        """
        emsp = create_emsp(commission_pct=0.05)
        driver = create_driver(emsp["id"], email="rb2@x.com")
        resp = api.create_site(
            create_site_payload(name="Nope", circuit_limit_kw=100, demand_charge_threshold_kw=100),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_driver_cannot_post_ocpp_status_returns_forbidden(self, api):
        """PRD §2.1: "When the headers are valid but the named role is not permitted
        to invoke the requested endpoint per the role matrix in §4, the request is
        rejected with `ERR_FORBIDDEN`." PRD §4: POST `/api/stalls/{id}/ocpp-status`
        is StationController-only.

        Design: Corner/rbac/driver_cannot_post_ocpp_status_returns_forbidden
        """
        emsp = create_emsp(commission_pct=0.05)
        driver = create_driver(emsp["id"], email="rb3@x.com")
        site = create_site(name="SRB3", circuit_limit_kw=100, demand_charge_threshold_kw=100)
        stall = validate_success(
            api.create_stall(create_stall_payload(site["id"], connector_type="CCS", max_power_kw=60), CPO),
            expected_status=201,
        )
        resp = api.post_stall_ocpp_status(
            stall["id"], {"reported_status": "FAULTED"}, make_driver_headers(driver["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_driver_cannot_stop_other_drivers_session_returns_forbidden(self, api):
        """PRD §2.1: "A `Driver` attempting to confirm, check in, or cancel another
        driver's reservation, or to stop or abort another driver's session, is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/driver_cannot_stop_other_drivers_session_returns_forbidden
        """
        set_clock("2026-06-01T00:00:00Z")
        emsp = create_emsp(commission_pct=0.05)
        d1 = create_driver(emsp["id"], email="d1own@x.com", fund=100000)
        d2 = create_driver(emsp["id"], email="d2own@x.com")
        site = create_site(name="SOWN", circuit_limit_kw=200, demand_charge_threshold_kw=200)
        api.create_tariff(create_tariff_payload(site["id"], connector_type="CCS"), CPO)
        stall = validate_success(
            api.create_stall(create_stall_payload(site["id"], connector_type="CCS", max_power_kw=60), CPO),
            expected_status=201,
        )
        sess = start_session(stall["id"], d1["id"])
        post_meter(sess["id"], 0, "2026-06-01T00:00:00Z", "TRANSACTION_BEGIN")
        api.begin_charging(sess["id"], STATION)
        post_meter(sess["id"], 10, "2026-06-01T00:10:00Z", "TRANSACTION_END")
        resp = api.stop_session(sess["id"], make_driver_headers(d2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name
        one of these three known roles, the request is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_sites({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
