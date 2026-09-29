"""Who may do what: role ownership, authentication, fleet scope and second signatures.

The scheduler's exclusive writes are exercised end to end, the two identity
refusals are shown to precede every business rule, a fleet account is confined to
its own builds, and an author is blocked from signing off their own artifact.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CUSTOMER_SCOPE_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import (
    ROLE_UPFIT_ENGINEER,
    UNKNOWN_UUID,
    USER_SCHEDULER,
    WORK_BAY_1,
    vin_f550,
)
from test_helpers.factories import (
    allocate_chassis_payload,
    build_slot_payload,
    compliance_label_payload,
    upfit_order_payload,
    warranty_claim_payload,
)
from test_helpers.fixtures import (
    allocate,
    approve_certification,
    catalog_service,
    chassis_version,
    draft_certification,
    new_configuration,
    new_customer,
    new_order,
    new_work_bay,
    propose_interface,
    read_certification,
    read_interface,
    read_order,
    read_slot,
    received_and_inspected_chassis,
    release,
    submit_engineering,
)

VALLEY = {
    "name": "Valley Aggregates",
    "account_code": "VAG-002",
    "fleet_contact_email": "shop@valley.example",
}
BAD_CHASSIS_MODEL = {"code": "", "make": "FORD", "gvwr_lb": -1, "wheelbase_in": 200}


def _plant_ready_for_an_order(api):
    """Catalog, bay, customer, published configuration and one weighed unit."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api, WORK_BAY_1, supported_body_types=["SERVICE", "FLATBED"])
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(27), measured=(4905, 2755)
    )
    return ns


def _released_order_for_the_scheduler(api):
    """The same plant with UO-5037 released to the floor by the scheduler."""
    ns = _plant_ready_for_an_order(api)
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5037",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    submit_engineering(api, ns.order["id"])
    ns.order = release(api, ns.order["id"])
    return ns


def _draft_order_and_draft_certification(api):
    """One draft order with a drafted design certification to aim wrong roles at."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(28), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5038",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.certification = draft_certification(api, ns.order["id"], "AS_DESIGNED")
    return ns


class TestSchedulerOwnsTheOrderBook:
    """Opening, binding, releasing, booking and unbooking all belong to one role."""

    def test_the_five_scheduler_only_writes_all_succeed_in_sequence(self, api):
        """The order book from creation to an unbooked window, all as the scheduler.

        Every one of the five writes reserved to the production scheduler is accepted
        with its own success status, the cancelled window reads cancelled, and with the
        order's only scheduled window gone the order falls back to merely released.

        Design: Corner/rbac/production_scheduler_owns_the_order_book_end_to_end
        """
        ns = _plant_ready_for_an_order(api)

        order = validate_success(
            api.create_upfit_order(
                upfit_order_payload(
                    ns.config["id"],
                    order_number="UO-5037",
                    order_type="CUSTOMER_SPECIFIC",
                    customer_id=ns.customer["id"],
                    body_mount_offset_from_front_axle_in=120,
                ),
                users.SCHEDULER,
            ),
            201,
        )
        validate_success(
            api.allocate_chassis(
                order["id"],
                allocate_chassis_payload(
                    ns.chassis["id"], chassis_version(api, ns.chassis["id"])
                ),
                users.SCHEDULER,
            )
        )
        submit_engineering(api, order["id"])
        validate_success(api.release_order(order["id"], users.SCHEDULER))
        slot = validate_success(
            api.create_build_slot(
                build_slot_payload(
                    order["id"], ns.bay["id"], "2026-09-01", "2026-09-05"
                ),
                users.SCHEDULER,
            ),
            201,
        )
        cancelled = validate_success(
            api.cancel_build_slot(
                slot["id"],
                {"reason": "customer pushed the in-service date"},
                users.SCHEDULER,
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert read_slot(api, slot["id"])["status"] == "CANCELLED"
        assert read_order(api, order["id"])["build_status"] == "RELEASED"

    def test_the_shared_read_right_reaches_the_catalog_and_the_yard(self, api):
        """A scheduler cannot author packages but may read what it schedules against.

        The body specification, the bound unit and the bay all read back for the
        production scheduler.

        Design: Corner/rbac/production_scheduler_owns_the_order_book_end_to_end
        """
        ns = _released_order_for_the_scheduler(api)

        body = validate_success(api.get_body_spec(ns.body["id"], users.SCHEDULER))
        chassis = validate_success(api.get_chassis(ns.chassis["id"], users.SCHEDULER))
        bay = validate_success(api.get_work_bay(ns.bay["id"], users.SCHEDULER))

        assert body["id"] == ns.body["id"]
        assert chassis["id"] == ns.chassis["id"]
        assert bay["id"] == ns.bay["id"]

    def test_the_scheduler_cannot_reach_into_the_administrator_s_list(self, api):
        """Cancelling an order is the plant administrator's call, not the scheduler's.

        The scheduler's cancellation is refused as unauthorized and leaves the order
        released, and the identical call by the plant administrator is accepted.

        Design: Corner/rbac/production_scheduler_owns_the_order_book_end_to_end
        """
        ns = _released_order_for_the_scheduler(api)
        reason = {"reason": "customer withdrew the purchase order"}

        validate_error(
            api.cancel_order(ns.order["id"], reason, users.SCHEDULER), ERR_UNAUTHORIZED, 403
        )
        assert read_order(api, ns.order["id"])["build_status"] == "RELEASED"

        cancelled = validate_success(api.cancel_order(ns.order["id"], reason, users.ADMIN))
        assert cancelled["build_status"] == "CANCELLED"


class TestIdentityChecksPrecedeEverything:
    """Missing identity beats a missing row, and a wrong role beats a bad body."""

    def test_an_unsigned_request_is_refused_even_when_the_target_does_not_exist(self, api):
        """No headers, no business logic — not even a lookup.

        Both unsigned calls are refused as unauthenticated, and the read aimed at an
        identifier that was never minted reports the identity failure rather than a
        not-found.

        Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_refused_before_any_business_rule
        """
        ns = _draft_order_and_draft_certification(api)

        validate_error(
            api.create_upfit_order(
                upfit_order_payload(ns.config["id"], order_number="UO-5039"), users.NO_HEADERS
            ),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.get_upfit_order(UNKNOWN_UUID, users.NO_HEADERS), ERR_UNAUTHENTICATED, 401
        )

    def test_three_cross_role_writes_are_each_refused_as_unauthorized(self, api):
        """Engineers do not release, technicians do not approve, warranty does not cancel.

        The release attempt by an upfit engineer, the certification approval by an
        install technician and the order cancellation by a warranty administrator are
        all refused as unauthorized.

        Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_refused_before_any_business_rule
        """
        ns = _draft_order_and_draft_certification(api)

        validate_error(
            api.release_order(ns.order["id"], users.ENGINEER), ERR_UNAUTHORIZED, 403
        )
        validate_error(
            api.approve_weight_certification(ns.certification["id"], users.TECHNICIAN),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.cancel_order(
                ns.order["id"], {"reason": "warranty wants it gone"}, users.WARRANTY_ADMIN
            ),
            ERR_UNAUTHORIZED,
            403,
        )

    def test_the_role_check_outranks_the_request_shape_check(self, api):
        """The body is nonsense and the caller still hears about the role first.

        A chassis-model create by the production scheduler carrying an empty code and a
        negative weight rating is refused as unauthorized rather than as malformed.

        Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_refused_before_any_business_rule
        """
        _draft_order_and_draft_certification(api)

        response = api.create_chassis_model(dict(BAD_CHASSIS_MODEL), users.SCHEDULER)

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_none_of_the_refused_calls_wrote_anything_and_the_positives_pass(self, api):
        """Six refusals change nothing, and the right people then do the same work.

        The order book still holds one order and the certification is still a draft
        after the refusals; then the compliance officer approves that certification,
        the engineer submits the package, the scheduler releases it, the plant
        administrator adds a chassis model and finally cancels the order.

        Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_refused_before_any_business_rule
        """
        ns = _draft_order_and_draft_certification(api)
        api.release_order(ns.order["id"], users.ENGINEER)
        api.approve_weight_certification(ns.certification["id"], users.TECHNICIAN)
        api.create_chassis_model(dict(BAD_CHASSIS_MODEL), users.SCHEDULER)
        api.cancel_order(ns.order["id"], {"reason": "not mine to cancel"}, users.WARRANTY_ADMIN)

        _, meta = validate_paginated(api.list_upfit_orders(users.SCHEDULER))
        assert meta["total_count"] == 1
        assert read_certification(api, ns.certification["id"])["status"] == "DRAFT"

        approved = validate_success(
            api.approve_weight_certification(ns.certification["id"], users.OFFICER)
        )
        assert approved["status"] == "APPROVED"
        allocate(api, ns.order["id"], ns.chassis["id"])
        submit_engineering(api, ns.order["id"])
        assert validate_success(api.release_order(ns.order["id"], users.SCHEDULER))[
            "build_status"
        ] == "RELEASED"
        validate_success(
            api.create_chassis_model(
                {
                    "code": "F600-DRW-96CA",
                    "make": "FORD",
                    "gvwr_lb": 22000,
                    "front_gawr_lb": 7500,
                    "rear_gawr_lb": 15500,
                    "wheelbase_in": 212,
                    "cab_to_axle_in": 96,
                    "curb_front_axle_lb": 5000,
                    "curb_rear_axle_lb": 2900,
                    "max_aux_amp_draw": 60,
                    "electrical_bus": "J1939_CAN",
                    "pto_provision": "FULL",
                    "pto_max_flow_gpm": 22,
                    "body_builder_book_rev": "BBB-2026.1",
                    "incomplete_vehicle_document_rev": "IVD-2026.1",
                },
                users.ADMIN,
            ),
            201,
        )
        assert validate_success(
            api.cancel_order(ns.order["id"], {"reason": "customer withdrew"}, users.ADMIN)
        )["build_status"] == "CANCELLED"


def _two_fleet_accounts_with_one_order_each(api):
    """Metro and Valley, each with its own customer-specific order on one configuration."""
    ns = catalog_service(api, with_equipment=False)
    ns.metro = new_customer(api)
    ns.valley = new_customer(api, **VALLEY)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.metro_order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5041",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.metro["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.valley_order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5042",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.valley["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    return ns


def _order_where_one_officer_authored_the_package(api):
    """Everything on UO-5044 was authored by co-1, and the package submitted by ps-1."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(29), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5044",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.interface = propose_interface(
        api,
        ns.order["id"],
        "BODY_BUILDER_MODULE",
        20,
        "BODY_CONTROLLER",
        headers=users.OFFICER_AS_ENGINEER,
    )
    submit_engineering(
        api, ns.order["id"], headers=users.headers_for(ROLE_UPFIT_ENGINEER, USER_SCHEDULER)
    )
    ns.certification = draft_certification(
        api, ns.order["id"], "AS_DESIGNED", headers=users.OFFICER_AS_ENGINEER
    )
    return ns


class TestCustomerScopeConfinesAFleetAccount:
    """A fleet account sees its own builds and nothing else in the plant."""

    def test_reaching_another_account_s_order_is_forbidden_on_read_and_on_write(self, api):
        """Metro cannot read Valley's build, nor open a claim against it.

        The cross-account read and the cross-account claim are both refused as a
        customer-scope violation.

        Design: Corner/rbac/customer_scope_confines_a_fleet_account_to_its_own_builds_forbidden
        """
        ns = _two_fleet_accounts_with_one_order_each(api)
        metro = users.customer_headers(ns.metro["id"])

        validate_error(
            api.get_upfit_order(ns.valley_order["id"], metro), ERR_CUSTOMER_SCOPE_VIOLATION, 403
        )
        validate_error(
            api.create_warranty_claim(
                warranty_claim_payload(
                    ns.valley_order["id"], "BODY_STRUCTURE", 50000, claim_number="WC-5043"
                ),
                metro,
            ),
            ERR_CUSTOMER_SCOPE_VIOLATION,
            403,
        )

    def test_the_collection_route_is_scoped_and_not_merely_the_detail_route(self, api):
        """Metro's order list contains Metro's order and nothing else.

        The same detail route on its own order is fine, and the listing reports a single
        matching order, so the scope rule filters the collection rather than only
        guarding direct reads.

        Design: Corner/rbac/customer_scope_confines_a_fleet_account_to_its_own_builds_forbidden
        """
        ns = _two_fleet_accounts_with_one_order_each(api)
        metro = users.customer_headers(ns.metro["id"])

        own = validate_success(api.get_upfit_order(ns.metro_order["id"], metro))
        orders, meta = validate_paginated(api.list_upfit_orders(metro))

        assert own["order_number"] == "UO-5041"
        assert meta["total_count"] == 1
        assert [order["order_number"] for order in orders] == ["UO-5041"]

    def test_the_rule_binds_only_the_fleet_identity_and_covers_its_own_record(self, api):
        """Valley's account row is closed to Metro, and staff see both builds.

        Metro reading Valley's customer record is refused while its own record reads
        back, and a warranty administrator reads either order without restriction
        because the scope rule binds only the entity-backed identity.

        Design: Corner/rbac/customer_scope_confines_a_fleet_account_to_its_own_builds_forbidden
        """
        ns = _two_fleet_accounts_with_one_order_each(api)
        metro = users.customer_headers(ns.metro["id"])

        validate_error(
            api.get_customer(ns.valley["id"], metro), ERR_CUSTOMER_SCOPE_VIOLATION, 403
        )
        assert validate_success(api.get_customer(ns.metro["id"], metro))["account_code"] == "MFS-001"
        assert validate_success(
            api.get_upfit_order(ns.metro_order["id"], users.WARRANTY_ADMIN)
        )["order_number"] == "UO-5041"
        assert validate_success(
            api.get_upfit_order(ns.valley_order["id"], users.WARRANTY_ADMIN)
        )["order_number"] == "UO-5042"

    def test_the_role_check_still_outranks_the_scope_check(self, api):
        """Metro asking to release its own order hears about the role, not the scope.

        Releasing is a production scheduler's act, so the customer's attempt on its own
        order is refused as unauthorized rather than as a scope violation.

        Design: Corner/rbac/customer_scope_confines_a_fleet_account_to_its_own_builds_forbidden
        """
        ns = _two_fleet_accounts_with_one_order_each(api)
        metro = users.customer_headers(ns.metro["id"])

        error = validate_error(
            api.release_order(ns.metro_order["id"], metro), ERR_UNAUTHORIZED, 403
        )

        assert error["error_id"] != ERR_CUSTOMER_SCOPE_VIOLATION


class TestSegregationOfDutiesBlocksTheAuthor:
    """Nobody signs off their own work, whichever role they happen to be wearing."""

    def test_all_three_self_approvals_are_refused_and_nothing_moves(self, api):
        """One officer authored the tap and the numbers, and one scheduler submitted.

        Approving the interface they proposed, approving the certification they drafted
        and releasing the package they submitted are each refused on segregation of
        duties, and all three records are exactly where they were.

        Design: Corner/rbac/segregation_of_duties_blocks_the_author_from_approving_their_own_artifact
        """
        ns = _order_where_one_officer_authored_the_package(api)

        validate_error(
            api.approve_interface(ns.interface["id"], users.OFFICER),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            api.approve_weight_certification(ns.certification["id"], users.OFFICER),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            api.release_order(ns.order["id"], users.SCHEDULER), ERR_SEGREGATION_OF_DUTIES, 403
        )

        assert read_interface(api, ns.interface["id"])["status"] == "PROPOSED"
        assert read_certification(api, ns.certification["id"])["status"] == "DRAFT"
        assert read_order(api, ns.order["id"])["build_status"] == "ENGINEERING_REVIEW"

    def test_a_second_person_clears_every_one_of_the_three(self, api):
        """The work is fine; only the signature was wrong.

        The other compliance officer approves both the interface and the certification,
        and the other scheduler releases the order.

        Design: Corner/rbac/segregation_of_duties_blocks_the_author_from_approving_their_own_artifact
        """
        ns = _order_where_one_officer_authored_the_package(api)

        interface = validate_success(api.approve_interface(ns.interface["id"], users.OFFICER_ALT))
        certification = validate_success(
            api.approve_weight_certification(ns.certification["id"], users.OFFICER_ALT)
        )
        released = validate_success(api.release_order(ns.order["id"], users.SCHEDULER_ALT))

        assert interface["status"] == "APPROVED"
        assert certification["status"] == "APPROVED"
        assert released["build_status"] == "RELEASED"

    def test_the_rule_keys_on_the_recorded_author_rather_than_the_role(self, api):
        """The audit trail records the person, and the person is what is compared.

        The interface names its proposer, the certification names its drafter and the
        order names its submitter, each by the operator identity that made the call
        rather than by the role that identity was wearing.

        Design: Corner/rbac/segregation_of_duties_blocks_the_author_from_approving_their_own_artifact
        """
        ns = _order_where_one_officer_authored_the_package(api)

        assert read_interface(api, ns.interface["id"])["proposed_by_user_id"] == "co-1"
        assert read_certification(api, ns.certification["id"])["created_by_user_id"] == "co-1"
        assert read_order(api, ns.order["id"])["engineering_submitted_by_user_id"] == "ps-1"

    def test_the_fourth_site_is_the_officer_who_signs_the_plate(self, api):
        """The officer who approved the numbers may not also issue the label citing them.

        With the certification approved by the second officer, that same officer's
        attempt to issue a label citing it is refused on segregation of duties.

        Design: Corner/rbac/segregation_of_duties_blocks_the_author_from_approving_their_own_artifact
        """
        ns = _order_where_one_officer_authored_the_package(api)
        approved = approve_certification(api, ns.certification["id"], headers=users.OFFICER_ALT)
        assert approved["approved_by_user_id"] == "co-2"

        response = api.create_compliance_label(
            compliance_label_payload(ns.order["id"], ns.certification["id"]), users.OFFICER_ALT
        )

        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    def test_the_role_check_outranks_the_duties_check(self, api):
        """Wearing the wrong hat is reported before the self-approval is even considered.

        The author calling the approval route as an upfit engineer is refused as
        unauthorized rather than on segregation of duties, and the interface is still
        proposed.

        Design: Corner/rbac/segregation_of_duties_blocks_the_author_from_approving_their_own_artifact
        """
        ns = _order_where_one_officer_authored_the_package(api)

        error = validate_error(
            api.approve_interface(ns.interface["id"], users.OFFICER_AS_ENGINEER),
            ERR_UNAUTHORIZED,
            403,
        )

        assert error["error_id"] != ERR_SEGREGATION_OF_DUTIES
        assert read_interface(api, ns.interface["id"])["status"] == "PROPOSED"
