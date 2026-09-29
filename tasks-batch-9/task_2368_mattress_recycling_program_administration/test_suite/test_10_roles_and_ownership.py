"""Who may act, on whose record: shared reads against exclusive writes, the ownership
comparison behind each entity-backed role, and the two segregated second signatures."""

from test_helpers import (
    ADMIN_1_USER_ID,
    ADMIN_2_USER_ID,
    AUDITOR_1_USER_ID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    create_ca_program,
    create_enrolled_site,
    create_hauler,
    create_recycler,
    create_registrant,
    create_site,
    create_wa_program,
    make_hauler_headers,
    make_recycler_headers,
    make_registrant_headers,
    make_site_operator_headers,
    make_unrecognised_role_headers,
    propose_rate,
    read_program,
    setup_amendment_required_remittance,
    setup_filed_remittance,
    setup_scheduled_order,
    submit_amendment,
    submit_volume_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN_2 = TEST_USERS["admin_2_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
AUDITOR_2 = TEST_USERS["auditor_2_headers"]

UNKNOWN_PROGRAM_ID = "00000000-0000-4000-8000-00000000bb01"


def test_all_six_roles_read_a_program_but_only_staff_revise_its_forecast(api):
    """PRD §2.1: "A request whose declared role is recognised but is not among the
    roles permitted for the operation is rejected with `ERR_UNAUTHORIZED`."

    PRD §4 opens the program read to "ProgramAdministrator, ProgramAuditor,
    Registrant, CollectionSiteOperator, Hauler, Recycler" while the cost-forecast
    revision names `ProgramAdministrator` alone.

    Design: Corner/rbac/six_roles_share_the_program_read_but_only_admin_writes_the_forecast
    """
    program = create_wa_program(api)
    registrant = create_registrant(
        api,
        legal_name="Cascadia Sleep Wholesale",
        registrant_type="MANUFACTURER",
        home_state_code="WA",
    )
    site = create_site(api, program["id"])
    hauler = create_hauler(api, program["id"])
    recycler = create_recycler(api, program["id"], accepted_unit_classes=["MATTRESS"])

    readers = [
        ADMIN,
        AUDITOR,
        make_registrant_headers(registrant["id"]),
        make_site_operator_headers(site["id"]),
        make_hauler_headers(hauler["id"]),
        make_recycler_headers(recycler["id"]),
    ]
    for headers in readers:
        seen = validate_success(api.get_state_program(program["id"], headers))
        assert seen["id"] == program["id"]
        assert seen["recommended_rate_cents"] == 1075
        assert seen["version"] == 1

    refused = api.update_cost_forecast(
        program["id"],
        {"forecast_annual_cost_cents": 72_000_000},
        make_registrant_headers(registrant["id"]),
    )

    validate_error(refused, "ERR_UNAUTHORIZED", 403)
    stored = read_program(api, program["id"])
    assert stored["forecast_annual_cost_cents"] == 60_000_000
    assert stored["version"] == 1


def test_the_hauler_that_ran_the_route_may_not_settle_or_void_it(api):
    """PRD §2.1: "A request whose declared role is recognised but is not among the
    roles permitted for the operation is rejected with `ERR_UNAUTHORIZED`."

    PRD §2.10: "The ordering is normative: a later check must never mask an earlier
    one, and a request that violates several rules is diagnosed by the earliest
    violated rule only."

    Design: Corner/rbac/hauler_cannot_finalize_settlement_returns_403
    """
    chain = setup_scheduled_order(api, units_manifested=100, route_distance_km=40.0)

    settlement = api.finalize_settlement(chain["order_id"], chain["hauler_headers"])
    void = api.void_pickup_order(
        chain["order_id"], {"reason": "Route cancelled by site"}, chain["hauler_headers"]
    )

    validate_error(settlement, "ERR_UNAUTHORIZED", 403)
    validate_error(void, "ERR_UNAUTHORIZED", 403)
    stored = validate_success(api.get_pickup_order(chain["order_id"], ADMIN))
    assert stored["fulfillment_status"] == "SCHEDULED"
    assert stored["settlement_status"] == "UNSETTLED"


def test_neither_a_registrant_nor_a_site_may_open_the_program_purse(api):
    """PRD §3.5: "A new report starts in `SUBMITTED` with `credited_units` and
    `credit_cents` at 0 and `accepted_at` null — nothing is credited and no custody
    moves until an administrator accepts it."

    PRD §3.7: "A new facility starts in `certification_status` `PROVISIONAL` with
    `certified_at` null, `units_received_count`, `units_processed_count`,
    `units_rejected_count` and `verified_output_weight_kg` at 0, and
    `diversion_rate_pct` at 0."

    Design: Corner/rbac/registrant_cannot_accept_a_volume_report_and_operator_cannot_certify_a_recycler
    """
    program = create_wa_program(api)
    site = create_enrolled_site(api, program["id"])
    site_headers = make_site_operator_headers(site["id"])
    report = submit_volume_report(
        api, site["id"], period_month="2026-08", units_mattress=320, units_foundation=190
    )
    recycler = create_recycler(api, program["id"])
    registrant = create_registrant(
        api,
        legal_name="Cascadia Sleep Wholesale",
        registrant_type="MANUFACTURER",
        home_state_code="WA",
    )

    by_registrant = api.accept_volume_report(
        report["id"], make_registrant_headers(registrant["id"])
    )
    by_operator = api.accept_volume_report(report["id"], site_headers)
    certification = api.certify_recycler(recycler["id"], site_headers)

    validate_error(by_registrant, "ERR_UNAUTHORIZED", 403)
    validate_error(by_operator, "ERR_UNAUTHORIZED", 403)
    validate_error(certification, "ERR_UNAUTHORIZED", 403)
    rows, _ = validate_paginated(api.list_volume_reports(site["id"], ADMIN))
    stored_report = next(row for row in rows if row["id"] == report["id"])
    assert stored_report["status"] == "SUBMITTED"
    assert stored_report["credit_cents"] == 0
    assert stored_report["accepted_at"] is None
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 0
    assert read_program(api, program["id"])["site_credit_paid_cents"] == 0
    stored_recycler = validate_success(api.get_recycler(recycler["id"], ADMIN))
    assert stored_recycler["certification_status"] == "PROVISIONAL"
    assert stored_recycler["certified_at"] is None


def test_audit_authority_does_not_reach_the_fee_schedule_it_may_read(api):
    """PRD §2.1: "A request whose declared role is recognised but is not among the
    roles permitted for the operation is rejected with `ERR_UNAUTHORIZED`."

    PRD §2.1: "`ProgramAuditor` — the independent audit function. Opens fee audits,
    adjudicates exemption claims, requests amendments, closes audits, and verifies
    commodity output records."

    Design: Corner/rbac/auditor_cannot_approve_a_rate_schedule_returns_403
    """
    program = create_ca_program(api)
    schedule = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )

    approval = api.approve_fee_rate_schedule(schedule["id"], AUDITOR)
    activation = api.activate_fee_rate_schedule(schedule["id"], AUDITOR)
    read = api.get_fee_rate_schedule(schedule["id"], AUDITOR)

    validate_error(approval, "ERR_UNAUTHORIZED", 403)
    validate_error(activation, "ERR_UNAUTHORIZED", 403)
    seen = validate_success(read)
    assert seen["status"] == "PROPOSED"
    assert seen["approved_by_user_id"] is None
    assert seen["proposed_by_user_id"] == ADMIN_1_USER_ID


def test_an_unnamed_or_unrecognised_capacity_never_reaches_the_record(api):
    """PRD §2.1: "A request that omits either header, or that presents an
    `X-User-Role` value the server does not recognise, is rejected with
    `ERR_UNAUTHENTICATED`."

    PRD §2.10 orders "Authentication — both headers present and the role recognised
    (`ERR_UNAUTHENTICATED`)." ahead of "Reference resolution in the order described
    in §2.5 (the per-entity 404 codes)."

    Design: Corner/rbac/missing_x_user_role_header_returns_401_unauthenticated
    """
    program = create_ca_program(api)

    anonymous = api.get_state_program(program["id"], NO_AUTH_HEADERS)
    invented_role = api.get_state_program(program["id"], make_unrecognised_role_headers())
    anonymous_on_unknown = api.update_cost_forecast(
        UNKNOWN_PROGRAM_ID, {"forecast_annual_cost_cents": 1}, NO_AUTH_HEADERS
    )

    validate_error(anonymous, "ERR_UNAUTHENTICATED", 401)
    validate_error(invented_role, "ERR_UNAUTHENTICATED", 401)
    validate_error(anonymous_on_unknown, "ERR_UNAUTHENTICATED", 401)


def test_a_registrant_may_only_settle_its_own_filing(api):
    """PRD §2.1: "When `X-User-Role` is `Registrant`, `X-User-ID` is the `id` of the
    acting registrant; ownership checks on any resource that references a registrant
    compare that resource's `registrant_id` to `X-User-ID`."

    PRD §2.1: "In all four entity-backed cases, an authenticated and role-authorized
    principal that reaches for a resource it does not own is rejected with
    `ERR_FORBIDDEN_RESOURCE`."

    Design: Corner/rbac/registrant_cannot_pay_another_registrants_remittance_returns_403
    """
    chain = setup_filed_remittance(api)
    other = create_registrant(
        api,
        legal_name="Golden State Sleep Co",
        registrant_type="MANUFACTURER",
        home_state_code="CA",
    )

    by_stranger = api.pay_sales_remittance(
        chain["remittance_id"], {"amount_cents": 550_000}, make_registrant_headers(other["id"])
    )

    validate_error(by_stranger, "ERR_FORBIDDEN_RESOURCE", 403)
    untouched = validate_success(api.get_sales_remittance(chain["remittance_id"], ADMIN))
    assert untouched["status"] == "FILED"
    assert untouched["fee_paid_cents"] == 0

    paid = validate_success(
        api.pay_sales_remittance(
            chain["remittance_id"], {"amount_cents": 550_000}, chain["registrant_headers"]
        )
    )

    assert paid["status"] == "PAID"
    assert paid["fee_paid_cents"] == 550_000


def test_only_the_hauler_named_on_the_order_may_confirm_collection(api):
    """PRD §2.1: "When `X-User-Role` is `Hauler`, `X-User-ID` is the `id` of the
    acting hauler; ownership checks compare a pickup order's `hauler_id` to
    `X-User-ID`."

    PRD §3.6: "The assigned `Hauler` confirms collection, moving `SCHEDULED →
    PICKED_UP`. Only the hauler named on the order may do so, per the ownership rule
    of §2.1."

    Design: Corner/rbac/hauler_cannot_deliver_another_haulers_order_returns_403
    """
    chain = setup_scheduled_order(api, units_manifested=100, route_distance_km=40.0)
    other = create_hauler(
        api,
        chain["program_id"],
        company_name="Rainier Freight",
        service_regions=["NORTH"],
        per_unit_rate_cents=500,
        per_km_rate_cents=200,
    )

    by_stranger = api.confirm_pickup(chain["order_id"], make_hauler_headers(other["id"]))

    validate_error(by_stranger, "ERR_FORBIDDEN_RESOURCE", 403)
    assert (
        validate_success(api.get_pickup_order(chain["order_id"], ADMIN))["fulfillment_status"]
        == "SCHEDULED"
    )

    collected = validate_success(
        api.confirm_pickup(chain["order_id"], chain["hauler_headers"])
    )

    assert collected["fulfillment_status"] == "PICKED_UP"
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))["active_route_count"] == 1
    assert validate_success(api.get_hauler(other["id"], ADMIN))["active_route_count"] == 0


def test_the_proposer_may_activate_its_own_rate_but_never_approve_it(api):
    """PRD §2.1: "Approving a fee-rate schedule requires an `X-User-ID` different
    from the schedule's `proposed_by_user_id`."

    PRD §2.10: "Segregation of duties (step 8) is checked **before** the target
    record's own state (step 9)"

    Design: Corner/rbac/proposing_administrator_cannot_approve_its_own_rate_schedule
    """
    program = create_ca_program(api)
    schedule = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )

    self_approval = api.approve_fee_rate_schedule(schedule["id"], ADMIN)

    validate_error(self_approval, "ERR_SEGREGATION_OF_DUTIES", 403)
    assert (
        validate_success(api.get_fee_rate_schedule(schedule["id"], ADMIN))["status"]
        == "PROPOSED"
    )

    approved = validate_success(api.approve_fee_rate_schedule(schedule["id"], ADMIN_2))
    activated = validate_success(api.activate_fee_rate_schedule(schedule["id"], ADMIN))

    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == ADMIN_2_USER_ID
    assert activated["status"] == "ACTIVE"
    assert activated["proposed_by_user_id"] == ADMIN_1_USER_ID


def test_the_auditor_who_sent_the_filing_back_may_not_close_the_audit(api):
    """PRD §3.4: "And it requires the segregation-of-duties separation of §2.1: an
    auditor whose identifier matches `amendment_requested_by_user_id` cannot close
    the audit they sent back."

    PRD §2.1: "Closing a remittance audit requires an `X-User-ID` different from that
    remittance's `amendment_requested_by_user_id` whenever that field has been set;
    when no amendment was ever requested the field is null and the check does not
    apply."

    Design: Corner/rbac/amendment_requesting_auditor_cannot_close_that_audit
    """
    chain = setup_amendment_required_remittance(api)
    parent = submit_amendment(
        api,
        chain["remittance_id"],
        chain["registrant_id"],
        units_sold_mattress=520,
        units_sold_foundation=0,
        expected_remittance_version=chain["remittance"]["version"],
    )
    assert parent["status"] == "UNDER_AUDIT"

    by_requester = api.close_remittance_audit(chain["remittance_id"], AUDITOR)

    validate_error(by_requester, "ERR_SEGREGATION_OF_DUTIES", 403)
    assert (
        validate_success(api.get_sales_remittance(chain["remittance_id"], AUDITOR))["status"]
        == "UNDER_AUDIT"
    )

    closed = validate_success(api.close_remittance_audit(chain["remittance_id"], AUDITOR_2))

    assert closed["status"] == "AUDIT_CLOSED"
    assert closed["amendment_requested_by_user_id"] == AUDITOR_1_USER_ID
    assert closed["amendment_round"] == 1
    assert closed["fee_reconciled_cents"] == 550_000
    assert closed["balance_due_cents"] == 0
    _, meta = validate_paginated(
        api.list_sales_remittances(ADMIN, params={"registrant_id": chain["registrant_id"]})
    )
    assert meta["total_count"] == 2
