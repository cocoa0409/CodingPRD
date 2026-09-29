"""Optimistic concurrency on the two routes that demand an expected version.

Certification drafting guards the order's version and allocation guards the
unit's version; each route watches its own row's counter, and every accepted
write moves that counter so the same payload cannot be replayed.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import ERR_STALE_CHASSIS_VERSION, ERR_STALE_UPFIT_ORDER_VERSION
from test_helpers.constants import vin_f550
from test_helpers.factories import allocate_chassis_payload, weight_certification_payload
from test_helpers.fixtures import (
    allocate,
    catalog_service,
    chassis_version,
    new_configuration,
    new_customer,
    new_order,
    order_version,
    patch_body_mount,
    read_chassis,
    read_order,
    received_and_inspected_chassis,
    submit_engineering,
)


def _order_whose_version_moved_three_times(api):
    """UO-5043 created, bound, re-mounted and submitted, with every version captured."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(29), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5043",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.v0 = ns.order["version"]
    ns.v1 = allocate(api, ns.order["id"], ns.chassis["id"])["version"]
    ns.v2 = patch_body_mount(api, ns.order["id"], 122)["version"]
    ns.v3 = submit_engineering(api, ns.order["id"])["version"]
    return ns


def _inspected_unit_and_an_order_waiting_for_it(api):
    """UO-5044 with no truck, and one weighed unit whose create-time version was kept."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5044",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    received = validate_success(
        api.receive_chassis(
            {
                "vin": vin_f550(30),
                "chassis_model_id": ns.cm["id"],
                "ownership": "POOL_STOCK",
                "availability_date": "2026-08-05",
            },
            users.ADMIN,
        ),
        201,
    )
    ns.cv0 = received["version"]
    ns.chassis = validate_success(
        api.inspect_chassis(
            received["id"],
            {"measured_front_axle_weight_lb": 4905, "measured_rear_axle_weight_lb": 2755},
            users.TECHNICIAN,
        )
    )
    ns.cv1 = ns.chassis["version"]
    return ns


class TestCertificationDraftingGuardsTheOrderVersion:
    """Every write since the version was read makes that version unusable."""

    def test_the_version_read_at_order_creation_is_refused_later(self, api):
        """Three writes happened since; the number in hand is history.

        Drafting against the creation-time version is refused as stale and leaves no
        certification behind at all.

        Design: Corner/cross_cutting_complexity_layers/certification_create_rejects_a_stale_upfit_order_version
        """
        ns = _order_whose_version_moved_three_times(api)

        response = api.create_weight_certification(
            weight_certification_payload(ns.order["id"], "AS_DESIGNED", ns.v0), users.ENGINEER
        )

        validate_error(response, ERR_STALE_UPFIT_ORDER_VERSION, 412)
        _, meta = validate_paginated(
            api.list_weight_certifications(users.OFFICER, {"upfit_order_id": ns.order["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_intermediate_version_is_just_as_stale_as_the_oldest_one(self, api):
        """Being nearly current is not being current.

        Drafting against the version left by the body-mount patch is refused as stale
        exactly as the creation-time version was.

        Design: Corner/cross_cutting_complexity_layers/certification_create_rejects_a_stale_upfit_order_version
        """
        ns = _order_whose_version_moved_three_times(api)

        response = api.create_weight_certification(
            weight_certification_payload(ns.order["id"], "AS_DESIGNED", ns.v2), users.ENGINEER
        )

        validate_error(response, ERR_STALE_UPFIT_ORDER_VERSION, 412)

    def test_the_current_version_is_accepted_and_drafts_the_certification(self, api):
        """The freshly read number opens the door.

        The draft is created against the order, on the design basis, at draft status.

        Design: Corner/cross_cutting_complexity_layers/certification_create_rejects_a_stale_upfit_order_version
        """
        ns = _order_whose_version_moved_three_times(api)

        certification = validate_success(
            api.create_weight_certification(
                weight_certification_payload(ns.order["id"], "AS_DESIGNED", ns.v3), users.ENGINEER
            ),
            201,
        )

        assert certification["upfit_order_id"] == ns.order["id"]
        assert certification["basis"] == "AS_DESIGNED"
        assert certification["status"] == "DRAFT"

    def test_every_accepted_write_moves_the_counter_by_exactly_one_step(self, api):
        """Binding, re-mounting, submitting, drafting and approving each cost one version.

        The three setup writes advanced the counter by one each, drafting the
        certification advances it again — which is exactly why the next draft would need a
        freshly read number — and approving that certification advances it once more as it
        moves the compliance dimension.

        Design: Corner/cross_cutting_complexity_layers/certification_create_rejects_a_stale_upfit_order_version
        """
        ns = _order_whose_version_moved_three_times(api)

        assert ns.v1 == ns.v0 + 1
        assert ns.v2 == ns.v1 + 1
        assert ns.v3 == ns.v2 + 1

        certification = validate_success(
            api.create_weight_certification(
                weight_certification_payload(ns.order["id"], "AS_DESIGNED", ns.v3), users.ENGINEER
            ),
            201,
        )
        assert order_version(api, ns.order["id"]) == ns.v3 + 1

        approved = validate_success(
            api.approve_weight_certification(certification["id"], users.OFFICER)
        )
        assert approved["status"] == "APPROVED"
        order = read_order(api, ns.order["id"])
        assert order["version"] == ns.v3 + 2
        assert order["compliance_status"] == "DESIGN_CERTIFIED"


class TestAllocationGuardsTheChassisVersion:
    """The scale ticket already moved the unit's counter before anybody could bind it."""

    def test_the_version_read_at_receipt_is_refused_after_the_scale_ticket(self, api):
        """Weighing the truck moved the row, so the receipt-time number is stale.

        The binding is refused as stale, the order still carries no truck and the unit
        is still merely inspected.

        Design: Corner/cross_cutting_complexity_layers/allocate_chassis_rejects_a_stale_chassis_version
        """
        ns = _inspected_unit_and_an_order_waiting_for_it(api)

        response = api.allocate_chassis(
            ns.order["id"],
            allocate_chassis_payload(ns.chassis["id"], ns.cv0),
            users.SCHEDULER,
        )

        validate_error(response, ERR_STALE_CHASSIS_VERSION, 412)
        assert read_order(api, ns.order["id"])["chassis_id"] is None
        assert read_chassis(api, ns.chassis["id"])["status"] == "INSPECTED"

    def test_the_post_inspection_version_binds_the_unit_to_the_order(self, api):
        """One step later the same call goes through.

        The order names the unit, the unit reads allocated, names the order back, and is
        restamped as customer-assigned because this order is cut for a customer.

        Design: Corner/cross_cutting_complexity_layers/allocate_chassis_rejects_a_stale_chassis_version
        """
        ns = _inspected_unit_and_an_order_waiting_for_it(api)

        bound = validate_success(
            api.allocate_chassis(
                ns.order["id"],
                allocate_chassis_payload(ns.chassis["id"], ns.cv1),
                users.SCHEDULER,
            )
        )

        assert ns.cv1 == ns.cv0 + 1
        assert bound["chassis_id"] == ns.chassis["id"]
        chassis = read_chassis(api, ns.chassis["id"])
        assert chassis["status"] == "ALLOCATED"
        assert chassis["allocated_upfit_order_id"] == ns.order["id"]
        assert chassis["ownership"] == "CUSTOMER_ASSIGNED"

    def test_a_successful_binding_moves_the_counter_so_it_cannot_be_replayed(self, api):
        """The guard is what stops a double binding, not a separate rule.

        The accepted binding advances the unit's counter by one, so replaying the very
        same payload is refused as stale and the unit stays bound to the first order.

        Design: Corner/cross_cutting_complexity_layers/allocate_chassis_rejects_a_stale_chassis_version
        """
        ns = _inspected_unit_and_an_order_waiting_for_it(api)
        validate_success(
            api.allocate_chassis(
                ns.order["id"],
                allocate_chassis_payload(ns.chassis["id"], ns.cv1),
                users.SCHEDULER,
            )
        )

        assert chassis_version(api, ns.chassis["id"]) == ns.cv1 + 1
        validate_error(
            api.allocate_chassis(
                ns.order["id"],
                allocate_chassis_payload(ns.chassis["id"], ns.cv1),
                users.SCHEDULER,
            ),
            ERR_STALE_CHASSIS_VERSION,
            412,
        )
        assert read_chassis(api, ns.chassis["id"])["allocated_upfit_order_id"] == ns.order["id"]

    def test_the_two_guards_watch_their_own_rows_and_ignore_each_other(self, api):
        """The binding route never looks at the order's counter, nor the reverse.

        Moving the order's version by re-mounting the body does not disturb a binding
        carried out with the correct unit version, and the certification drafted
        afterwards is accepted on the order's current version even though the unit's
        version has moved since.

        Design: Corner/cross_cutting_complexity_layers/allocate_chassis_rejects_a_stale_chassis_version
        """
        ns = _inspected_unit_and_an_order_waiting_for_it(api)
        patch_body_mount(api, ns.order["id"], 122)

        bound = validate_success(
            api.allocate_chassis(
                ns.order["id"],
                allocate_chassis_payload(ns.chassis["id"], ns.cv1),
                users.SCHEDULER,
            )
        )
        assert bound["chassis_id"] == ns.chassis["id"]

        certification = validate_success(
            api.create_weight_certification(
                weight_certification_payload(
                    ns.order["id"], "AS_DESIGNED", order_version(api, ns.order["id"])
                ),
                users.ENGINEER,
            ),
            201,
        )
        assert certification["status"] == "DRAFT"
