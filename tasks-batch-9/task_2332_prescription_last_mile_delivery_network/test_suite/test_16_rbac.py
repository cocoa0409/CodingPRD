"""Access control: identity, role, tenancy, minimum necessary, and duty separation.

The five roles are peers rather than a hierarchy, so a refusal has to name the
right reason: a missing identity is 401 before anything is routed, a wrong role
is 403 on a resource the caller legitimately owns, a wrong tenant is 403 under
that role's own scope identifier, a courier with no assignment is refused the
redacted projection, and one operations user is barred from finishing work
another started even though both hold the same role.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    OPS_USER_A,
    OPS_USER_C,
    TEST_USERS,
    advance_to_assigned,
    advance_to_out_for_delivery,
    advance_to_picked_up,
    assert_courier_counters,
    assert_courier_projection_shape,
    assert_grant_ledger,
    assert_reliability_scores,
    assert_window_occupancy,
    build_courier,
    build_health_plan,
    build_network,
    build_patient,
    build_pharmacy,
    build_queued_delivery,
    build_window,
    cases_for,
    exhaust_attempt_ladder,
    factories,
    find_by,
    make_courier_headers,
    make_patient_headers,
    make_pharmacy_headers,
    make_plan_admin_headers,
    masked,
    open_case,
    read_assignment,
    read_case,
    read_courier,
    read_delivery,
    read_grant,
    read_window,
    set_clock,
    start_review,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}
LONG_WINDOW = {"window_end": utc_ts(3, 22)}
EVENING_WINDOW = {"window_start": utc_ts(3, 18), "window_end": utc_ts(3, 20)}


def _anonymous(headers):
    """The same headers with the identity claim removed entirely."""
    return {key: value for key, value in headers.items() if key != "X-User-ID"}


def _blank_identity(headers):
    """The same headers with the identity claim present but empty."""
    return {**headers, "X-User-ID": ""}


# ─── Rung one: identity ───────────────────────────────


@pytest.fixture
def a_perfectly_valid_body_and_no_caller(api):
    """Reference data for an order that is legal in every respect but the caller."""
    return build_network(api)


class TestIdentityIsCheckedBeforeAnythingElse:
    """"A request whose `X-User-ID` header is absent or empty is rejected with
    `ERR_UNAUTHENTICATED` before routing, role resolution, or path existence are
    considered at all."
    """

    def test_a_write_and_a_read_without_the_header_are_both_unauthenticated(
        self, api, a_perfectly_valid_body_and_no_caller
    ):
        """Reads are not anonymous either, and the valid body creates nothing.

        "`X-User-ID` is present and non-empty — otherwise `ERR_UNAUTHENTICATED`.
        Checked on every request, ahead of routing, role resolution, and path
        existence."

        Design: Corner/rbac/a_write_with_a_missing_x_user_header_returns_unauthenticated
        """
        net = a_perfectly_valid_body_and_no_caller
        body = factories.pharmacy_order_payload(
            net.pharmacy["id"],
            net.patient["id"],
            health_plan_id=net.plan["id"],
            **STANDARD_ORDER,
        )
        headerless = _anonymous(net.pharmacy_headers)

        validate_error(api.create_pharmacy_order(body, headers=headerless), "ERR_UNAUTHENTICATED", 401)
        validate_error(api.list_pharmacy_orders(headerless), "ERR_UNAUTHENTICATED", 401)

        _rows, meta = validate_paginated(api.list_pharmacy_orders(net.pharmacy_headers))
        assert meta["total_count"] == 0

        accepted = validate_success(
            api.create_pharmacy_order(body, headers=net.pharmacy_headers), 201
        )
        assert accepted["status"] == "INTAKE"

    def test_an_empty_header_is_refused_exactly_like_an_absent_one(
        self, api, a_perfectly_valid_body_and_no_caller
    ):
        """An empty identity loses to no other rule, not even the role check.

        "The role that owns `X-User-ID` is among the addressed endpoint's
        authorised roles — otherwise `ERR_UNAUTHORIZED`. Applies to every
        endpoint."

        Design: Corner/rbac/a_write_with_a_missing_x_user_header_returns_unauthenticated
        """
        net = a_perfectly_valid_body_and_no_caller
        body = factories.pharmacy_order_payload(
            net.pharmacy["id"],
            net.patient["id"],
            health_plan_id=net.plan["id"],
            **STANDARD_ORDER,
        )
        blank = _blank_identity(net.pharmacy_headers)

        write = validate_error(
            api.create_pharmacy_order(body, headers=blank), "ERR_UNAUTHENTICATED", 401
        )
        assert write["error_id"] == "ERR_UNAUTHENTICATED"

        sweep = validate_error(api.run_routing_sweep(blank), "ERR_UNAUTHENTICATED", 401)
        assert sweep["error_id"] == write["error_id"]

        validate_success(api.create_pharmacy_order(body, headers=net.pharmacy_headers), 201)


# ─── Rung two: the role split ─────────────────────────


@pytest.fixture
def a_queued_bag_and_the_courier_who_will_carry_it(api):
    """Cedar Rx owns one QUEUED delivery; Ray is on shift and eligible for it."""
    scn = build_queued_delivery(api)
    scn.courier = build_courier(api)
    return scn


class TestTheRoleSplitRunsInBothDirections:
    """"`NetworkOps` owns reference data, routing, sweeps, settlement, and
    exception adjudication."
    """

    def test_the_owning_pharmacy_may_not_dispatch_settle_or_sweep(
        self, api, a_queued_bag_and_the_courier_who_will_carry_it
    ):
        """Owning the bag is not the same as being allowed to route or bill it.

        "When the resolved role does not appear in the addressed endpoint's
        authorised role list, the request is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/a_pharmacy_operator_cannot_dispatch_settle_or_sweep_and_a_courier_cannot_reserve
        """
        scn = a_queued_bag_and_the_courier_who_will_carry_it
        operator = scn.pharmacy_headers

        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=operator,
                payload=factories.dispatch_payload(scn.courier["id"]),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(api.settle_delivery(scn.delivery["id"], headers=operator), "ERR_UNAUTHORIZED", 403)
        validate_error(api.run_routing_sweep(operator), "ERR_UNAUTHORIZED", 403)

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["settlement_status"] == "PROVISIONAL"
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 0

    def test_the_courier_may_not_create_the_reservation_it_would_carry(
        self, api, a_queued_bag_and_the_courier_who_will_carry_it
    ):
        """The refusal names the role, not the tenancy, and moves no capacity.

        "A `PharmacyOperator` reserves capacity for a `READY` order by naming
        the `order_id`, the `window_id` of the promised interval, and the
        `expected_window_version` proving which view of that window's occupancy
        the client is acting on (§2.7)."

        Design: Corner/rbac/a_pharmacy_operator_cannot_dispatch_settle_or_sweep_and_a_courier_cannot_reserve
        """
        scn = a_queued_bag_and_the_courier_who_will_carry_it
        before = read_window(api, scn.window["id"])

        validate_error(
            api.create_delivery(
                factories.delivery_payload(
                    scn.order["id"], scn.window["id"], before["version"]
                ),
                headers=make_courier_headers(scn.courier["id"]),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        after = read_window(api, scn.window["id"])
        assert_window_occupancy(after, reserved_slots=1, available_slots=0, status="FULL")
        assert after["version"] == before["version"]


# ─── Rungs five and seven: courier peers ──────────────


@pytest.fixture
def an_offer_to_ray_and_a_bystander_named_tova(api):
    """Ray holds a 13:45Z offer; Tova is on shift with no assignment at all."""
    scn = build_queued_delivery(api)
    ray = build_courier(api, display_name="Ray Ortiz")
    tova = build_courier(api, display_name="Tova Mies")
    set_clock(api, utc_ts(3, 13, 45))
    assignment = validate_success(
        api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload(ray["id"])
        ),
        201,
    )
    scn.courier = ray
    scn.assignment = assignment
    return scn, tova


class TestCourierPeersAreSeparatedByTwoDifferentIds:
    """"An acting `Courier`'s identifier equals the `courier_id` of the addressed
    delivery or assignment — otherwise `ERR_COURIER_SCOPE_VIOLATION`."
    """

    def test_one_courier_cannot_accept_or_toggle_for_another(
        self, api, an_offer_to_ray_and_a_bystander_named_tova
    ):
        """The offer and the shift switch both belong to whoever owns the id.

        "When `X-User-Role` is `Courier`, `X-User-ID` is the `id` of the acting
        `Courier`; ownership checks compare the addressed delivery's or
        assignment's `courier_id` to `X-User-ID`, and a mismatch is
        `ERR_COURIER_SCOPE_VIOLATION`."

        Design: Corner/rbac/a_courier_cannot_act_on_another_couriers_assignment_or_read_its_delivery
        """
        scn, tova = an_offer_to_ray_and_a_bystander_named_tova
        bystander = make_courier_headers(tova["id"])

        validate_error(
            api.accept_assignment(scn.assignment["id"], headers=bystander),
            "ERR_COURIER_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api.set_courier_status(
                scn.courier["id"], factories.courier_status_payload("OFFLINE"), headers=bystander
            ),
            "ERR_COURIER_SCOPE_VIOLATION",
            403,
        )

        assignment = read_assignment(api, scn.assignment["id"])
        assert assignment["status"] == "OFFERED"
        assert assignment["responded_at"] is None
        assert read_courier(api, scn.courier["id"])["status"] == "AVAILABLE"

    def test_the_projection_is_refused_to_a_courier_holding_no_assignment(
        self, api, an_offer_to_ray_and_a_bystander_named_tova
    ):
        """No assignment means no disclosure, and no row in either trail.

        "A courier that holds no assignment on the delivery, current or
        historical, is refused with `ERR_HIPAA_SCOPE_VIOLATION` and no row is
        written."

        Design: Corner/rbac/a_courier_cannot_act_on_another_couriers_assignment_or_read_its_delivery
        """
        scn, tova = an_offer_to_ray_and_a_bystander_named_tova

        validate_error(
            api.get_courier_view(scn.delivery["id"], headers=make_courier_headers(tova["id"])),
            "ERR_HIPAA_SCOPE_VIOLATION",
            403,
        )
        _rows, bystander_trail = validate_paginated(
            api.list_courier_disclosures(tova["id"], headers=make_courier_headers(tova["id"]))
        )
        assert bystander_trail["total_count"] == 0

        carrier = make_courier_headers(scn.courier["id"])
        validate_success(api.accept_assignment(scn.assignment["id"], headers=carrier))
        projection = validate_success(api.get_courier_view(scn.delivery["id"], headers=carrier))
        assert_courier_projection_shape(projection)
        assert projection["patient_masked_name"] == masked("Dana Reyes")

        rows, carrier_trail = validate_paginated(
            api.list_courier_disclosures(scn.courier["id"], headers=carrier)
        )
        assert carrier_trail["total_count"] == 1
        by_delivery, delivery_trail = validate_paginated(
            api.list_delivery_disclosures(scn.delivery["id"], headers=scn.pharmacy_headers)
        )
        assert delivery_trail["total_count"] == 1
        assert by_delivery[0]["id"] == rows[0]["id"]
        assert by_delivery[0]["courier_id"] == scn.courier["id"]


# ─── Rungs three and four: tenancy on shared operations ───


@pytest.fixture
def two_pharmacies_two_patients_and_one_reserved_bag(api):
    """Cedar Rx holds Dana's bag; Willow Pharmacy and Ola Grant are outsiders."""
    net = build_network(api)
    willow = build_pharmacy(api, name="Willow Pharmacy")
    ola = build_patient(
        api,
        net.pharmacy["id"],
        full_name="Ola Grant",
        date_of_birth="1988-01-05",
        phone_last4="2290",
        address_line="12 Birch Ct",
    )
    scn = build_queued_delivery(api, net=net)
    evening = build_window(api, net.zone["id"], **EVENING_WINDOW)
    return scn, willow, ola, evening


class TestTenancyIsTheOnlyThingSeparatingSharedOperations:
    """"`Patient` has no operation of its own that a pharmacy operator cannot
    also perform on their behalf; the difference between the two roles is scope,
    not capability."
    """

    def test_the_outside_pharmacy_and_the_outside_patient_each_get_their_own_id(
        self, api, two_pharmacies_two_patients_and_one_reserved_bag
    ):
        """Two callers, one request each, two different scope identifiers.

        "An acting `PharmacyOperator`'s identifier equals the `pharmacy_id` of
        the `PharmacyOrder` behind the addressed resource — otherwise
        `ERR_PHARMACY_SCOPE_VIOLATION`. Guards releasing an order to ready,
        holding an order, reserving a delivery, cancelling a delivery,
        rescheduling a delivery, confirming a physical return, reading one
        order, and reading one delivery."

        "An acting `Patient`'s identifier equals the `patient_id` of the
        `PharmacyOrder` behind the addressed resource — otherwise
        `ERR_PATIENT_SCOPE_VIOLATION`."

        Design: Corner/rbac/cross_tenant_writes_are_rejected_by_scope_while_the_owner_keeps_the_shared_operation
        """
        scn, willow, ola, evening = two_pharmacies_two_patients_and_one_reserved_bag
        intruding_operator = make_pharmacy_headers(willow["id"])

        validate_error(
            api.reschedule_delivery(
                scn.delivery["id"],
                factories.reschedule_payload(evening["id"]),
                headers=intruding_operator,
            ),
            "ERR_PHARMACY_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api.cancel_delivery(scn.delivery["id"], headers=make_patient_headers(ola["id"])),
            "ERR_PATIENT_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api.get_delivery(scn.delivery["id"], headers=intruding_operator),
            "ERR_PHARMACY_SCOPE_VIOLATION",
            403,
        )

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["settlement_status"] == "PROVISIONAL"
        assert delivery["window_id"] == scn.window["id"]
        assert_window_occupancy(read_window(api, evening["id"]), reserved_slots=0, status="OPEN")

    def test_the_owning_patient_may_issue_the_refused_reschedule(
        self, api, two_pharmacies_two_patients_and_one_reserved_bag
    ):
        """The same body, from the recipient herself, moves the slot across.

        "An unpicked delivery — one whose custody is `QUEUED` or `ASSIGNED` —
        may be moved to another window by the pharmacy operator who owns it or
        by the patient themselves, by supplying the new `window_id`."

        Design: Corner/rbac/cross_tenant_writes_are_rejected_by_scope_while_the_owner_keeps_the_shared_operation
        """
        scn, _willow, _ola, evening = two_pharmacies_two_patients_and_one_reserved_bag

        moved = validate_success(
            api.reschedule_delivery(
                scn.delivery["id"],
                factories.reschedule_payload(evening["id"]),
                headers=scn.patient_headers,
            )
        )
        assert moved["window_id"] == evening["id"]
        assert moved["custody_status"] == "QUEUED"

        assert_window_occupancy(
            read_window(api, scn.window["id"]), reserved_slots=0, available_slots=1, status="OPEN"
        )
        assert_window_occupancy(
            read_window(api, evening["id"]), reserved_slots=1, available_slots=0, status="FULL"
        )


# ─── Rung six: the payer boundary ─────────────────────


@pytest.fixture
def one_funding_plan_and_one_uninvolved_plan(api):
    """Meridian's 2026 pool funds Cedar Rx's bag; Aspen Benefit funds nothing."""
    scn = build_queued_delivery(api)
    aspen = build_health_plan(api, name="Aspen Benefit", payer_type="MEDICAID", member_cost_share_pct=0.05)
    return scn, aspen


class TestThePayerRoleIsReadOnlyAndSingleTenant:
    """"`PlanAdministrator` is a read-heavy payer role that funds grant pools and
    audits the allocations drawn against them; it never touches custody,
    routing, or settlement, and never reads patient records directly."
    """

    def test_the_other_plans_administrator_reaches_neither_pool_nor_delivery(
        self, api, one_funding_plan_and_one_uninvolved_plan
    ):
        """The rows exist; being out of scope is reported instead of a 404.

        "An acting `PlanAdministrator`'s identifier equals the `health_plan_id`
        of the addressed grant pool, or of the `PharmacyOrder` behind the
        addressed delivery — otherwise `ERR_PLAN_SCOPE_VIOLATION`."

        "Existence is deliberately checked *after* scoping, so probing a real
        identifier belonging to another tenant yields 403 rather than leaking
        the difference between 404 and 200."

        Design: Corner/rbac/a_plan_administrator_cannot_read_another_plans_grant_or_touch_settlement
        """
        scn, aspen = one_funding_plan_and_one_uninvolved_plan
        outsider = make_plan_admin_headers(aspen["id"])

        validate_error(
            api.get_plan_grant(scn.net.grant["id"], headers=outsider),
            "ERR_PLAN_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api.get_delivery(scn.delivery["id"], headers=outsider),
            "ERR_PLAN_SCOPE_VIOLATION",
            403,
        )

        assert read_grant(api, scn.net.grant["id"])["status"] == "ACTIVE"

    def test_the_funding_administrator_reads_the_ledger_but_cannot_settle(
        self, api, one_funding_plan_and_one_uninvolved_plan
    ):
        """A refused read does not become a write, and the money stays open.

        "Reading the ledger is deliberately broad."

        "A `PlanAdministrator` may read its own pools with their live
        `committed_cents`, `consumed_cents`, and `remaining_cents`, and may read
        the allocations drawn against them with the full line vector"

        Design: Corner/rbac/a_plan_administrator_cannot_read_another_plans_grant_or_touch_settlement
        """
        scn, _aspen = one_funding_plan_and_one_uninvolved_plan
        payer = scn.net.plan_admin_headers

        validate_error(
            api.settle_delivery(scn.delivery["id"], headers=payer), "ERR_UNAUTHORIZED", 403
        )
        assert read_delivery(api, scn.delivery["id"])["settlement_status"] == "PROVISIONAL"

        pools, pool_page = validate_paginated(
            api.list_plan_grants(payer, health_plan_id=scn.net.plan["id"])
        )
        assert pool_page["total_count"] == 1
        assert_grant_ledger(pools[0], committed_cents=150, consumed_cents=0, status="ACTIVE")

        lines, allocation_page = validate_paginated(
            api.list_fee_allocations(payer, plan_grant_id=scn.net.grant["id"])
        )
        assert allocation_page["total_count"] == 1
        assert lines[0]["variant"] == "PROVISIONAL"
        assert lines[0]["status"] == "ACTIVE"
        assert lines[0]["plan_grant_cents"] == 150


# ─── Inside one role: segregation of duties ───────────


@pytest.fixture
def a_case_opened_by_one_operator_on_a_bag_another_revoked(api):
    """Two operators have already touched this bag, in two different ways.

    One revoked Ray's accepted leg; the other opened and took up a hand-written
    damage case after Tova carried the bag through all three failed runs and the
    pharmacy received it back.
    """
    scn = build_queued_delivery(api, window_kwargs=LONG_WINDOW)
    ray = build_courier(api, display_name="Ray Ortiz")
    set_clock(api, utc_ts(3, 13, 40))
    offer = validate_success(
        api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload(ray["id"])
        ),
        201,
    )
    validate_success(api.accept_assignment(offer["id"], headers=make_courier_headers(ray["id"])))
    validate_success(api.revoke_assignment(offer["id"], headers=TEST_USERS["ops_second"]))

    tova = build_courier(api, display_name="Tova Mies")
    advance_to_assigned(api, scn, courier=tova, dispatch_clock=utc_ts(3, 13, 45))
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn)
    exhaust_attempt_ladder(api, scn)
    scn.delivery = validate_success(
        api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers)
    )

    damage = open_case(api, scn.delivery["id"], "DAMAGED", headers=OPS_HEADERS)
    start_review(api, damage["id"], headers=OPS_HEADERS)
    return scn, damage


class TestSegregationOfDutiesReadsTwoHistoryFields:
    """"The acting operator must be neither the case's `opened_by_ops_user_id`,
    where that field is non-null, nor the `revoked_by_ops_user_id` of any
    assignment on the case's delivery; either collision is
    `ERR_SEGREGATION_OF_DUTIES`."
    """

    def test_neither_the_opener_nor_the_earlier_revoker_may_adjudicate(
        self, api, a_case_opened_by_one_operator_on_a_bag_another_revoked
    ):
        """The bar reaches an operator who never touched the case, only the bag.

        "Segregation of duties operates *inside* the `NetworkOps` role rather
        than between roles."

        Design: Corner/rbac/the_case_opener_and_the_assignment_revoker_cannot_adjudicate_that_case
        """
        scn, damage = a_case_opened_by_one_operator_on_a_bag_another_revoked
        version = read_delivery(api, scn.delivery["id"])["version"]
        body = factories.adjudication_payload("DENY", version)

        validate_error(
            api.adjudicate_exception_case(damage["id"], body, headers=OPS_HEADERS),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        validate_error(
            api.adjudicate_exception_case(damage["id"], body, headers=TEST_USERS["ops_second"]),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        case = read_case(api, damage["id"])
        assert case["status"] == "UNDER_REVIEW"
        assert case["adjudicated_by_ops_user_id"] is None
        assert read_delivery(api, scn.delivery["id"])["version"] == version

    def test_an_uninvolved_third_operator_completes_the_identical_call(
        self, api, a_case_opened_by_one_operator_on_a_bag_another_revoked
    ):
        """The two refusals bumped nothing, so the same version is still current.

        "The case moves `UNDER_REVIEW → DENIED` and `credit_cents` is set to 0."

        Design: Corner/rbac/the_case_opener_and_the_assignment_revoker_cannot_adjudicate_that_case
        """
        scn, damage = a_case_opened_by_one_operator_on_a_bag_another_revoked
        version = read_delivery(api, scn.delivery["id"])["version"]
        body = factories.adjudication_payload("DENY", version)

        validate_error(
            api.adjudicate_exception_case(damage["id"], body, headers=OPS_HEADERS),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        denied = validate_success(
            api.adjudicate_exception_case(damage["id"], body, headers=TEST_USERS["ops_third"])
        )
        assert denied["status"] == "DENIED"
        assert denied["disposition"] == "DENY"
        assert denied["credit_cents"] == 0
        assert denied["adjudicated_by_ops_user_id"] == OPS_USER_C

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["settlement_status"] == "PROVISIONAL"
        assert delivery["custody_status"] == "RETURNED"

        cases = cases_for(api, scn.delivery["id"])
        assert find_by(cases, exception_type="ATTEMPTS_EXHAUSTED")["opened_by_ops_user_id"] is None
        assert find_by(cases, exception_type="DAMAGED")["opened_by_ops_user_id"] == OPS_USER_A


# ─── One shared endpoint, one reserved transition ─────


@pytest.fixture
def a_courier_suspended_by_three_failed_runs(api):
    """Ray missed the door three times, which trips the lifetime-score gate."""
    scn = build_queued_delivery(api, window_kwargs=LONG_WINDOW)
    advance_to_assigned(api, scn, courier=build_courier(api, display_name="Ray Ortiz"))
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn)
    exhaust_attempt_ladder(api, scn)
    return scn


class TestOnlyOperationsMayLiftASuspension:
    """"Only `NetworkOps` may lift a suspension, by submitting `AVAILABLE` for a
    courier whose `status` is `SUSPENDED`; a `Courier` attempting to clear its
    own `SUSPENDED` status is rejected with `ERR_INVALID_COURIER_STATE`."
    """

    def test_the_suspended_courier_cannot_clear_its_own_status(
        self, api, a_courier_suspended_by_three_failed_runs
    ):
        """Role and tenancy are both right here; only the transition is not.

        "`Courier.status` is compatible with the operation — otherwise
        `ERR_COURIER_SUSPENDED` when the courier is `SUSPENDED` at dispatch or
        accept, `ERR_COURIER_UNAVAILABLE` when it is `OFFLINE` at dispatch or
        accept, and `ERR_INVALID_COURIER_STATE` for an illegal availability
        change (going `OFFLINE` while `active_delivery_count` is greater than 0,
        or a `Courier` trying to clear its own `SUSPENDED` status)."

        Design: Corner/rbac/a_suspended_courier_cannot_clear_its_own_suspension_but_ops_can
        """
        scn = a_courier_suspended_by_three_failed_runs
        before = read_courier(api, scn.courier["id"])
        assert_courier_counters(
            before, attempt_total_count=3, delivered_count=0, active_delivery_count=0, status="SUSPENDED"
        )
        assert_reliability_scores(before, rolling=50.00, lifetime=0.00)

        validate_error(
            api.set_courier_status(
                scn.courier["id"],
                factories.courier_status_payload("AVAILABLE"),
                headers=scn.courier_headers,
            ),
            "ERR_INVALID_COURIER_STATE",
            409,
        )

        after = read_courier(api, scn.courier["id"])
        assert after["status"] == "SUSPENDED"
        assert after["version"] == before["version"]

    def test_operations_issuing_the_identical_body_reinstates_the_courier(
        self, api, a_courier_suspended_by_three_failed_runs
    ):
        """Reinstatement rewrites no history and touches no bag.

        "Reinstatement closes the `AVAILABLE → SUSPENDED → AVAILABLE` cycle.
        Every availability change bumps the courier's `version`."

        Design: Corner/rbac/a_suspended_courier_cannot_clear_its_own_suspension_but_ops_can
        """
        scn = a_courier_suspended_by_three_failed_runs
        before = read_courier(api, scn.courier["id"])

        reinstated = validate_success(
            api.set_courier_status(
                scn.courier["id"],
                factories.courier_status_payload("AVAILABLE"),
                headers=OPS_HEADERS,
            )
        )
        assert reinstated["status"] == "AVAILABLE"
        assert reinstated["version"] == before["version"] + 1
        assert_courier_counters(reinstated, attempt_total_count=3, delivered_count=0)
        assert_reliability_scores(reinstated, rolling=50.00, lifetime=0.00)

        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "RETURN_PENDING"
