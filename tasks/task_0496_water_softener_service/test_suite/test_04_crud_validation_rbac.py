"""Resource creation defaults, computed-field sizing, validation rejections,
foreign-key checks, listing/pagination, RBAC denials, OCC, and the logical clock.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    NONEXISTENT_UUID,
    setup_account_with_accepted_test,
    setup_active_rental_contract,
    setup_delinquent_account,
    set_clock,
    create_customer,
    create_field_tech,
    create_account,
    make_field_tech_headers,
    create_account_payload,
    create_water_test_payload,
    create_system_payload,
    create_invoice_payload,
)

SM = TEST_USERS["service_manager_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Entities — creation defaults
# ===========================================================================
def test_create_account_defaults(api):
    """PRD §3.1: "On creation the account's `credit_balance_cents` ledger is
    initialized to 0 and its `standing` is set to `GOOD`."
    PRD §3.1: "The account also carries a `hardness_gpg` field ... which remains
    null until the first water test for the account is accepted."

    Design: Corner/entities/create_service_account_returns_201_with_defaults
    """
    cust = create_customer()
    acct = validate_success(api.create_account(
        create_account_payload(cust["id"], property_type="WELL_WHOLE_HOUSE", service_zone="Z-SOUTH"),
        BILLING), 201)
    assert acct["credit_balance_cents"] == 0
    assert acct["standing"] == "GOOD"
    assert acct["version"] == 1
    assert acct.get("hardness_gpg") is None


def test_get_account_not_found(api):
    """PRD §2.5: "A request whose first path identifier names a non-existent
    resource is rejected with `ERR_NOT_FOUND` before any subsequent identifier or
    body field is examined."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NONEXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_water_test_missing_required_field_rejected(api):
    """PRD §2.6: "every create and action endpoint validates the shape of its
    payload: required fields must be present and well-typed ... Any such structural
    violation is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.2: "the measured `hardness_gpg` in grains per gallon (which must be at
    least 0)."

    Design: Corner/entities/create_water_test_missing_required_field_returns_400
    """
    cust = create_customer()
    acct = create_account(cust["id"])
    tech = create_field_tech()
    th = make_field_tech_headers(tech["id"])
    resp = api.create_water_test(
        {"account_id": acct["id"], "iron_ppm": 0, "tds_ppm": 200, "household_size": 4}, th)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_account_invalid_property_type_enum_rejected(api):
    """PRD §3.1: "The `property_type` declares the installation site's water source
    and scope and must be one of `MUNICIPAL_WHOLE_HOUSE`, `WELL_WHOLE_HOUSE`, or
    `POINT_OF_USE`."

    Design: Corner/entities/create_water_test_invalid_enum_property_type_rejected
    """
    cust = create_customer()
    resp = api.create_account(
        {"customer_id": cust["id"], "property_type": "OCEAN", "service_zone": "Z-NORTH"}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_recommend_computes_capacity_server_side(api):
    """PRD §3.2: "The recommended capacity, written to `recommended_grain_capacity`,
    is then the smallest standard tank whose capacity is at least the required
    capacity, choosing from the standard tank sizes of 16000, 24000, 32000, 40000,
    48000, and 64000 grains."
    PRD §3.2: "the flag is true when `tds_ppm` reaches or exceeds the reverse-osmosis
    threshold and false otherwise."

    Design: Corner/entities/water_test_recommend_computed_fields_ignore_client_input
    """
    base = setup_account_with_accepted_test()  # ensures chain; use its tech for a fresh test
    wt = get_success_data(api.create_water_test(
        create_water_test_payload(base["account"]["id"], hardness_gpg=15, iron_ppm=0,
                                  tds_ppm=200, household_size=4), base["tech_headers"]))
    # daily = 4*80*15 = 4800; required = 4800*6 = 28800 -> next tank 32000.
    rec = validate_success(api.recommend_water_test(wt["id"], base["tech_headers"]), 200)
    assert rec["recommended_grain_capacity"] == 32000
    assert rec["recommended_needs_ro"] is False
    assert rec["status"] == "RECOMMENDED"


def test_recommend_iron_inflates_tank_size(api):
    """PRD §3.2: "the effective hardness is the measured `hardness_gpg` plus four
    grains for every part per million of iron measured in `iron_ppm`; this iron
    contribution is why a test with any positive iron reading is pushed toward a
    larger tank than its raw hardness alone would suggest."

    Design: Corner/calculations/recommend_iron_inflates_tank_size_to_48000
    """
    base = setup_account_with_accepted_test()
    wt = get_success_data(api.create_water_test(
        create_water_test_payload(base["account"]["id"], hardness_gpg=15, iron_ppm=2,
                                  tds_ppm=600, household_size=4), base["tech_headers"]))
    # effective = 15 + 2*4 = 23; daily = 4*80*23 = 7360; required = 7360*6 = 44160 -> tank 48000.
    rec = validate_success(api.recommend_water_test(wt["id"], base["tech_headers"]), 200)
    assert rec["recommended_grain_capacity"] == 48000
    assert rec["recommended_needs_ro"] is True


def test_small_household_low_hardness_smallest_tank(api):
    """PRD §3.2: "if the required capacity exceeds the largest standard tank, the
    largest tank (64000) is selected." (smallest-tank floor path)
    PRD §3.2: "The daily softening demand in grains is the `household_size`
    multiplied by 80 gallons per person per day, multiplied by that effective
    hardness. The required capacity is the daily demand multiplied by a six-day
    target between regenerations, rounded up to the next whole grain."

    Design: Corner/calculations/small_household_low_hardness_sizes_smallest_tank
    """
    base = setup_account_with_accepted_test()
    wt = get_success_data(api.create_water_test(
        create_water_test_payload(base["account"]["id"], hardness_gpg=10, iron_ppm=0,
                                  tds_ppm=100, household_size=2), base["tech_headers"]))
    # daily = 2*80*10 = 1600; required = 1600*6 = 9600 -> smallest tank 16000.
    rec = validate_success(api.recommend_water_test(wt["id"], base["tech_headers"]), 200)
    assert rec["recommended_grain_capacity"] == 16000


def test_customer_has_no_version_field(api):
    """PRD §2.4: "The `Customer` entity and the `FieldTech` entity carry only an
    `id` (a server-minted UUID) and a `created_at` timestamp; for these two entities
    both `updated_at` and `version` are absent."

    Design: Corner/entities/customer_immutable_no_version_field
    """
    cust = validate_success(api.create_customer(
        {"full_name": "Immutable One", "email": "immutable-one@example.com"}, SM), 201)
    assert "created_at" in cust
    assert "version" not in cust
    assert "updated_at" not in cust


def test_account_list_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.3: "The `limit` parameter ... if not provided it defaults to 10."

    Design: Corner/entities/account_list_pagination_envelope
    """
    cust = create_customer()
    create_account(cust["id"])
    data, meta = validate_paginated(api.list_accounts(BILLING))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10


# ===========================================================================
# Validations
# ===========================================================================
def test_rental_not_allowed_on_delinquent_account(api):
    """PRD §3.8: "Three conditions gate the create, and all must hold: the account's
    `standing` must be `GOOD`, the named system's `acquisition_mode` must be
    `RENTAL`, and that system must not already carry another contract in `ACTIVE` or
    `SUSPENDED` status. A create that violates any of these is rejected with
    `ERR_RENTAL_NOT_ALLOWED`."

    Design: Corner/validations/rental_not_allowed_on_delinquent_account
    """
    ctx = setup_delinquent_account(acquisition_mode="RENTAL")  # system RENTAL, no contract yet
    assert ctx["account"]["standing"] == "DELINQUENT"
    resp = api.create_rental_contract({
        "account_id": ctx["account"]["id"], "system_id": ctx["system"]["id"],
        "monthly_rate_cents": 4500, "term_months": 12, "start_date": "2026-03-05T00:00:00Z"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_RENTAL_NOT_ALLOWED.value)


def test_supersede_non_void_invoice_rejected(api):
    """PRD §3.10: "When `supersedes_invoice_id` is present it must reference an
    invoice currently in `VOID` status; a supersede pointer at any non-void invoice
    is rejected with `ERR_SUPERSEDE_NOT_VOID`, and only a void invoice may be cited
    this way."

    Design: Corner/validations/supersede_non_void_invoice_returns_422
    """
    cust = create_customer()
    acct = create_account(cust["id"])
    open_inv = get_success_data(api.create_invoice(
        create_invoice_payload(acct["id"], invoice_kind="SERVICE_REPAIR"), BILLING))
    resp = api.create_invoice(create_invoice_payload(
        acct["id"], supersedes_invoice_id=open_inv["id"], invoice_kind="SERVICE_REPAIR"), BILLING)
    validate_error(resp, ApiErrorId.ERR_SUPERSEDE_NOT_VOID.value)


def test_water_test_fk_account_not_found(api):
    """PRD §2.6: "Every such foreign key must reference an existing resource; a body
    foreign key pointing at a non-existent resource is rejected with
    `ERR_FK_NOT_FOUND`."

    Design: Corner/validations/fk_not_found_on_water_test_account_returns_404
    """
    tech = create_field_tech()
    th = make_field_tech_headers(tech["id"])
    resp = api.create_water_test(
        create_water_test_payload(NONEXISTENT_UUID, hardness_gpg=15), th)
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_void_already_void_invoice_is_closed(api):
    """PRD §3.10: "Attempting to pay or void an invoice that is already `PAID` or
    `VOID` is rejected with `ERR_INVOICE_CLOSED`."

    Design: Corner/errors/invoice_void_on_voided_returns_invoice_closed
    """
    cust = create_customer()
    acct = create_account(cust["id"])
    inv = get_success_data(api.create_invoice(
        create_invoice_payload(acct["id"], invoice_kind="SERVICE_REPAIR"), BILLING))
    get_success_data(api.void_invoice(inv["id"], BILLING))
    resp = api.void_invoice(inv["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_CLOSED.value)


# ===========================================================================
# Endpoints — filtered / sub-resource listing
# ===========================================================================
def test_filter_systems_by_account_id(api):
    """PRD §2.5: "Several read endpoints also expose reverse-reachability — listing
    the cartridge schedules, service visits, or warranty claims attached to a given
    system, or the stops attached to a given route."
    PRD §4 (GET /systems): "List softener systems".

    Design: Corner/endpoints/filter_systems_by_account_id
    """
    base = setup_account_with_accepted_test()
    sys = get_success_data(api.create_system(
        create_system_payload(base["account"]["id"], base["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=32000), SM))
    data, meta = validate_paginated(api.list_systems(SM, params={"account_id": base["account"]["id"]}))
    assert meta["total_count"] == 1
    assert any(s["id"] == sys["id"] for s in data)


def test_list_route_stops_subresource(api):
    """PRD §2.5: "the one genuinely nested pair is a route and the stops that belong
    to it ... those, too, validate the parent identifier in the path before
    returning the child collection."

    Design: Corner/endpoints/list_route_stops_subresource
    """
    from test_helpers import setup_planned_route_with_active_system, create_route_stop_payload
    ctx = setup_planned_route_with_active_system(capacity_stops=4)
    stop = get_success_data(api.add_route_stop(ctx["route"]["id"],
                                               create_route_stop_payload(ctx["system"]["id"]), DISPATCHER))
    data, meta = validate_paginated(api.list_route_stops_for_route(ctx["route"]["id"], DISPATCHER))
    assert meta["total_count"] == 1
    assert any(s["id"] == stop["id"] for s in data)


# ===========================================================================
# RBAC
# ===========================================================================
def test_dispatcher_cannot_pay_invoice(api):
    """PRD §2.1: "A `BillingClerk` owns rental contracts and their lifecycle,
    invoices, and account credit top-ups."
    PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/dispatcher_cannot_pay_invoice_unauthorized
    """
    cust = create_customer()
    acct = create_account(cust["id"])
    inv = get_success_data(api.create_invoice(
        create_invoice_payload(acct["id"], invoice_kind="SERVICE_REPAIR"), BILLING))
    resp = api.pay_invoice(inv["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = api.list_accounts({})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_customer_cannot_recommend_water_test(api):
    """PRD §2.1: "A `FieldTech` performs water tests, installs and activates systems,
    records meter readings, runs regenerations, services route stops, replaces
    cartridges, triages claims, and confirms visits."
    PRD §2.1: "the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_recommend_water_test
    """
    base = setup_account_with_accepted_test()
    wt = get_success_data(api.create_water_test(
        create_water_test_payload(base["account"]["id"]), base["tech_headers"]))
    resp = api.recommend_water_test(wt["id"], base["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# Cross-cutting: OCC on terminate
# ===========================================================================
def test_terminate_with_current_version_succeeds(api):
    """PRD §2.10: "The terminate operation requires the request body to carry
    `expected_rentalcontract_version`, holding the client's last observed `version`
    of the target `RentalContract`. Before the termination proceeds, the server
    compares that value against the contract's current `version`; if they differ,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_terminate_correct_version_succeeds
    """
    ctx = setup_active_rental_contract(start_date="2026-01-01T00:00:00Z")
    rc_id = ctx["contract"]["id"]
    get_success_data(api.suspend_rental_contract(rc_id, BILLING))
    resumed = get_success_data(api.resume_rental_contract(rc_id, BILLING))
    assert resumed["version"] == 3
    set_clock("2026-03-02T00:00:00Z", BILLING)
    result = validate_success(api.terminate_rental_contract(
        rc_id, {"expected_rentalcontract_version": resumed["version"]}, BILLING), 200)
    assert result["status"] == "TERMINATED"
    assert result["version"] == 4


def test_terminate_with_stale_version_returns_412(api):
    """PRD §2.10: "if they differ, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.8: "a mismatch with the contract's live `version` is rejected with
    `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_terminate_stale_version_returns_412
    """
    ctx = setup_active_rental_contract(start_date="2026-01-01T00:00:00Z")
    rc_id = ctx["contract"]["id"]
    suspended = get_success_data(api.suspend_rental_contract(rc_id, BILLING))
    stale = suspended["version"] - 1
    resp = api.terminate_rental_contract(rc_id, {"expected_rentalcontract_version": stale}, BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(api.get_rental_contract(rc_id, BILLING), 200)
    assert after["status"] == "SUSPENDED"


# ===========================================================================
# Cross-cutting: logical clock default
# ===========================================================================
def test_clock_default_leaves_invoice_open(api):
    """PRD §2.9: "At server startup the clock reads exactly `2026-01-01T00:00:00Z`,
    and before any clock-setting call it stays at that default and never falls back
    to wall-clock time."
    PRD §3.10: "Re-evaluating an `OPEN` invoice against the clock checks whether it
    has aged past its due date — that is, whether now is later than `period_end` plus
    `due_offset_days`."

    Design: Corner/cross_cutting_complexity_layers/clock_default_start_time_makes_invoice_not_past_due
    """
    cust = create_customer()
    acct = create_account(cust["id"])
    inv = get_success_data(api.create_invoice(create_invoice_payload(
        acct["id"], invoice_kind="SERVICE_REPAIR",
        period_start="2026-07-01T00:00:00Z", period_end="2026-08-01T00:00:00Z",
        due_offset_days=30), BILLING))  # due 2026-08-31; clock still default 2026-01-01
    result = validate_success(api.evaluate_invoice(inv["id"], BILLING), 200)
    assert result["status"] == "OPEN"


# ===========================================================================
# Cross-cutting: voiding the sole PAST_DUE invoice restores GOOD standing
# ===========================================================================
def test_void_past_due_invoice_restores_good_standing(api):
    """PRD §3.10: "And if the voided invoice was the one that had driven the account
    `DELINQUENT` and no other invoice is past due, the void restores `standing` to
    `GOOD`."

    Design: Corner/cross_cutting_complexity_layers/invoice_void_restores_account_to_good_standing
    """
    cust = create_customer()
    acct = create_account(cust["id"])
    inv = get_success_data(api.create_invoice(create_invoice_payload(
        acct["id"], invoice_kind="SERVICE_REPAIR",
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
        due_offset_days=30), BILLING))
    set_clock("2026-03-05T00:00:00Z", BILLING)
    get_success_data(api.evaluate_invoice(inv["id"], BILLING))
    delinquent = validate_success(api.get_account(acct["id"], SM), 200)
    assert delinquent["standing"] == "DELINQUENT"

    voided = validate_success(api.void_invoice(inv["id"], BILLING), 200)
    assert voided["status"] == "VOID"
    restored = validate_success(api.get_account(acct["id"], SM), 200)
    assert restored["standing"] == "GOOD"
