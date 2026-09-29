"""Whole endpoint round trips: write, read back, list, filter and act.

A bay is created, read, filtered and taken out of service; a binding is written
and read from both ends; a computed read is proved to write nothing; and an
adjudication is refused by a budget gate and then let through by an override.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CHASSIS_ALREADY_ALLOCATED,
    ERR_CHASSIS_MODEL_MISMATCH,
    ERR_CHASSIS_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_CHASSIS_VERSION,
    ERR_UPFIT_ORDER_NOT_FOUND,
    ERR_WARRANTY_BUDGET_EXCEEDED,
)
from test_helpers.assertions import (
    assert_axle_numbers,
    assert_claim_split,
    assert_common_fields,
    assert_immutable_label_shape,
    assert_order_ledger,
    assert_pagination_meta,
)
from test_helpers.constants import CM_F450, UNKNOWN_UUID, WORK_BAY_1, vin_f450, vin_f550
from test_helpers.factories import allocate_chassis_payload
from test_helpers.fixtures import (
    adjudicate_claim,
    allocate,
    catalog_service,
    chassis_version,
    draft_certification,
    inspect_claim,
    new_chassis_model,
    new_configuration,
    new_customer,
    new_order,
    new_slot,
    new_work_bay,
    open_claim,
    order_version,
    projection,
    read_chassis,
    read_claim,
    read_order,
    received_and_inspected_chassis,
    service_order_world,
    advance_to_released,
    delivered_service_order,
)

BAY_TWO = {
    "code": "BAY-2",
    "concurrent_capacity": 2,
    "supported_body_types": ["SERVICE", "DUMP", "FLATBED", "VAN"],
}
BAY_THREE = {"code": "BAY-3", "concurrent_capacity": 1, "supported_body_types": ["VAN"]}
CLAIM_COST_CENTS = 73333


def _three_work_bays(api):
    """One narrow bay, one wide bay and one van-only bay, all freshly created."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay_one = new_work_bay(api, WORK_BAY_1, supported_body_types=["SERVICE", "FLATBED"])
    ns.bay_two = new_work_bay(api, BAY_TWO)
    ns.bay_three = new_work_bay(api, BAY_THREE)
    return ns


def _order_and_two_candidate_units(api):
    """A service order drawn on the F550 with one matching and one mismatched unit."""
    ns = catalog_service(api, with_equipment=False)
    ns.wrong_model = new_chassis_model(api, CM_F450)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.wrong_chassis = received_and_inspected_chassis(
        api, ns.wrong_model["id"], vin=vin_f450(23), measured=(4180, 2320)
    )
    ns.right_chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(24), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5032",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    return ns


def _bound_order_with_a_bare_frame(api):
    """A customer order bound to a weighed unit whose body is not on yet."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(25), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5033",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.order = read_order(api, ns.order["id"])
    return ns


def _inspected_claim_over_a_tiny_cap(api):
    """A delivered build whose warranty budget is a hundred dollars, facing a big claim."""
    ns = delivered_service_order(
        api, order_type="CUSTOMER_SPECIFIC", warranty_liability_cap_cents=10000
    )
    ns.claim = open_claim(
        api, ns.order["id"], "BODY_STRUCTURE", CLAIM_COST_CENTS, claim_number="WC-5031"
    )
    ns.claim = inspect_claim(api, ns.claim["id"], False)
    return ns


class TestWorkBayRoundTrip:
    """A bay is created with its declared default, read back, filtered and stood down."""

    def test_a_new_bay_carries_the_declared_default_status_and_first_version(self, api):
        """Nothing about the status is supplied and the bay comes up active.

        The create response carries the active default, the two supported body types
        in the order they were given, and the common fields every row starts with.

        Design: Corner/endpoints/work_bay_create_read_list_and_set_status_round_trip
        """
        ns = _three_work_bays(api)

        assert ns.bay_one["status"] == "ACTIVE"
        assert ns.bay_one["concurrent_capacity"] == 1
        assert ns.bay_one["supported_body_types"] == ["SERVICE", "FLATBED"]
        assert_common_fields(ns.bay_one, expected_version=1)

    def test_the_technician_reads_the_bay_back_exactly_as_it_was_stored(self, api):
        """The shop floor may read the bay it is asked to work in.

        The read as an installation technician returns the code, the capacity and the
        supported body types in the stored order.

        Design: Corner/endpoints/work_bay_create_read_list_and_set_status_round_trip
        """
        ns = _three_work_bays(api)

        record = validate_success(api.get_work_bay(ns.bay_one["id"], users.TECHNICIAN))

        assert record["code"] == "BAY-1"
        assert record["concurrent_capacity"] == 1
        assert record["supported_body_types"] == ["SERVICE", "FLATBED"]

    def test_standing_a_bay_down_moves_only_its_status_and_version(self, api):
        """Taking the van bay out of service does not rewrite what it supports.

        The bay reads down, its version has advanced by one, and its single supported
        body type is untouched.

        Design: Corner/endpoints/work_bay_create_read_list_and_set_status_round_trip
        """
        ns = _three_work_bays(api)

        stood_down = validate_success(
            api.set_work_bay_status(ns.bay_three["id"], {"status": "DOWN"}, users.ADMIN)
        )

        assert stood_down["status"] == "DOWN"
        assert stood_down["version"] == ns.bay_three["version"] + 1
        assert stood_down["supported_body_types"] == ["VAN"]

    def test_the_status_filter_is_applied_before_the_page_window(self, api):
        """Two bays match the filter, and a window of one still reports both.

        Filtering on the active status lists the two working bays and counts two;
        asking for one row at the second offset returns a single row while the count
        stays at two and nothing more is waiting; filtering on the down status returns
        the van bay alone.

        Design: Corner/endpoints/work_bay_create_read_list_and_set_status_round_trip
        """
        ns = _three_work_bays(api)
        validate_success(
            api.set_work_bay_status(ns.bay_three["id"], {"status": "DOWN"}, users.ADMIN)
        )

        active, meta = validate_paginated(api.list_work_bays(users.ADMIN, {"status": "ACTIVE"}))
        assert sorted(bay["code"] for bay in active) == ["BAY-1", "BAY-2"]
        assert meta["total_count"] == 2

        windowed, window_meta = validate_paginated(
            api.list_work_bays(users.ADMIN, {"status": "ACTIVE", "limit": 1, "offset": 1})
        )
        assert len(windowed) == 1
        assert_pagination_meta(window_meta, 1, 1, 2, False)

        down, down_meta = validate_paginated(api.list_work_bays(users.ADMIN, {"status": "DOWN"}))
        assert [bay["code"] for bay in down] == ["BAY-3"]
        assert down_meta["total_count"] == 1


class TestAllocationLinksBothDirections:
    """Binding a unit writes the forward link and the reverse link in one call."""

    def test_a_unit_of_the_wrong_model_is_refused_and_nothing_is_written(self, api):
        """The whole package was engineered against one model's book.

        The mismatched unit is refused, the order still carries no truck and the
        rejected unit is still merely inspected.

        Design: Corner/endpoints/allocate_chassis_links_the_order_and_the_unit_in_both_directions
        """
        ns = _order_and_two_candidate_units(api)

        response = api.allocate_chassis(
            ns.order["id"],
            allocate_chassis_payload(
                ns.wrong_chassis["id"], chassis_version(api, ns.wrong_chassis["id"])
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_CHASSIS_MODEL_MISMATCH, 422)
        assert read_order(api, ns.order["id"])["chassis_id"] is None
        assert read_chassis(api, ns.wrong_chassis["id"])["status"] == "INSPECTED"

    def test_the_matching_unit_is_linked_from_both_ends_at_once(self, api):
        """One call writes the order's truck and the truck's order.

        The order names the unit, the unit names the order and reads allocated with
        its version advanced by one, and because the order is cut for a customer the
        pool unit is restamped as customer-assigned.

        Design: Corner/endpoints/allocate_chassis_links_the_order_and_the_unit_in_both_directions
        """
        ns = _order_and_two_candidate_units(api)
        version_before = chassis_version(api, ns.right_chassis["id"])

        bound = validate_success(
            api.allocate_chassis(
                ns.order["id"],
                allocate_chassis_payload(ns.right_chassis["id"], version_before),
                users.SCHEDULER,
            )
        )

        assert bound["chassis_id"] == ns.right_chassis["id"]
        chassis = read_chassis(api, ns.right_chassis["id"])
        assert chassis["allocated_upfit_order_id"] == ns.order["id"]
        assert chassis["status"] == "ALLOCATED"
        assert chassis["version"] == version_before + 1
        assert chassis["ownership"] == "CUSTOMER_ASSIGNED"

    def test_both_identifiers_in_the_request_are_resolved_before_anything_else(self, api):
        """A missing truck and a missing order are each reported as not found.

        Naming a unit that was never received is a not-found on the unit, and naming
        an order that was never opened is a not-found on the order.

        Design: Corner/endpoints/allocate_chassis_links_the_order_and_the_unit_in_both_directions
        """
        ns = _order_and_two_candidate_units(api)

        validate_error(
            api.allocate_chassis(
                ns.order["id"], allocate_chassis_payload(UNKNOWN_UUID, 1), users.SCHEDULER
            ),
            ERR_CHASSIS_NOT_FOUND,
            404,
        )
        validate_error(
            api.allocate_chassis(
                UNKNOWN_UUID,
                allocate_chassis_payload(
                    ns.right_chassis["id"], chassis_version(api, ns.right_chassis["id"])
                ),
                users.SCHEDULER,
            ),
            ERR_UPFIT_ORDER_NOT_FOUND,
            404,
        )

    def test_replaying_the_call_with_the_now_stale_version_is_refused(self, api):
        """The version that worked a moment ago is the wrong one now.

        The successful binding advanced the unit's version, so the identical replay
        carrying the old version is refused as stale.

        Design: Corner/endpoints/allocate_chassis_links_the_order_and_the_unit_in_both_directions
        """
        ns = _order_and_two_candidate_units(api)
        stale_version = chassis_version(api, ns.right_chassis["id"])
        validate_success(
            api.allocate_chassis(
                ns.order["id"],
                allocate_chassis_payload(ns.right_chassis["id"], stale_version),
                users.SCHEDULER,
            )
        )

        response = api.allocate_chassis(
            ns.order["id"],
            allocate_chassis_payload(ns.right_chassis["id"], stale_version),
            users.SCHEDULER,
        )

        validate_error(response, ERR_STALE_CHASSIS_VERSION, 412)


class TestWeightProjectionIsAPureRead:
    """The projection endpoint answers on both bases and writes nothing at all."""

    def test_the_designed_basis_answers_from_the_book_with_the_body_counted(self, api):
        """The body is not bolted on yet, but the design basis counts it anyway.

        The read returns the book curb weights carrying the planned body at its
        mount position, and reports the body as the single included component.

        Design: Corner/endpoints/weight_projection_reads_both_bases_without_writing_anything
        """
        ns = _bound_order_with_a_bare_frame(api)

        designed = projection(api, ns.order["id"], "AS_DESIGNED", headers=users.ENGINEER)

        assert_axle_numbers(designed, 5009, 4591, 9600, 9900, component_count=1)

    def test_the_measured_basis_answers_from_the_scale_with_nothing_counted(self, api):
        """The same order on the other basis is just the weighed bare frame.

        The read returns the two scale figures, their sum, the payload capacity left
        over, and a component count of zero because the body is not on the truck yet.

        Design: Corner/endpoints/weight_projection_reads_both_bases_without_writing_anything
        """
        ns = _bound_order_with_a_bare_frame(api)

        measured = projection(api, ns.order["id"], "AS_MEASURED", headers=users.OFFICER)

        assert_axle_numbers(measured, 4905, 2755, 7660, 11840, component_count=0)

    def test_neither_read_leaves_a_row_or_a_version_behind(self, api):
        """A computed read is not a certification and does not touch the order.

        After both reads no certification exists for the order and the order's
        version is exactly what allocation left it at; a certification drafted
        afterwards then stamps precisely the numbers the projection had reported.

        Design: Corner/endpoints/weight_projection_reads_both_bases_without_writing_anything
        """
        ns = _bound_order_with_a_bare_frame(api)
        version_after_allocation = order_version(api, ns.order["id"])
        projection(api, ns.order["id"], "AS_DESIGNED", headers=users.ENGINEER)
        projection(api, ns.order["id"], "AS_MEASURED", headers=users.OFFICER)

        _, meta = validate_paginated(
            api.list_weight_certifications(users.OFFICER, {"upfit_order_id": ns.order["id"]})
        )

        assert meta["total_count"] == 0
        assert order_version(api, ns.order["id"]) == version_after_allocation

        certification = draft_certification(api, ns.order["id"], "AS_DESIGNED")
        assert_axle_numbers(certification, 5009, 4591, 9600, 9900, component_count=1)

    def test_the_basis_is_mandatory_and_only_the_two_named_values_are_accepted(self, api):
        """A read without a basis, and a read on an invented basis, are both refused.

        Omitting the basis is an invalid request, and asking for an as-built basis
        that the contract never defines is refused the same way.

        Design: Corner/endpoints/weight_projection_reads_both_bases_without_writing_anything
        """
        ns = _bound_order_with_a_bare_frame(api)

        validate_error(
            api.weight_projection(ns.order["id"], users.ENGINEER), ERR_INVALID_REQUEST, 422
        )
        validate_error(
            api.weight_projection(ns.order["id"], users.ENGINEER, {"basis": "AS_BUILT"}),
            ERR_INVALID_REQUEST,
            422,
        )


class TestAdjudicationAgainstAWarrantyBudget:
    """The budget gate refuses the payout, and the override lets the same one through."""

    def test_a_claim_larger_than_the_budget_is_refused_and_nothing_moves(self, api):
        """Seven hundred dollars of body repair against a hundred dollar budget.

        The adjudication is refused on the warranty budget, the claim is still merely
        inspected on a provisional split, and the order's upfitter ledger is untouched.

        Design: Corner/endpoints/adjudication_is_refused_over_the_cap_and_allowed_with_the_override
        """
        ns = _inspected_claim_over_a_tiny_cap(api)

        response = api.adjudicate_warranty_claim(ns.claim["id"], users.WARRANTY_ADMIN, {})

        validate_error(response, ERR_WARRANTY_BUDGET_EXCEEDED, 402)
        claim = read_claim(api, ns.claim["id"])
        assert claim["status"] == "INSPECTED"
        assert claim["split_basis"] == "PROVISIONAL"
        assert read_order(api, ns.order["id"])["upfitter_liability_cents"] == 0

    def test_the_override_finalises_the_very_same_split(self, api):
        """The flag suspends the gate; it changes no arithmetic whatsoever.

        The overridden call succeeds, the claim is adjudicated on a final split, and
        the body-structure failure on an intact chassis warranty falls nothing to the
        chassis maker, ninety-five per cent to the upfitter and the five per cent
        goodwill share plus the odd cent to the customer.

        Design: Corner/endpoints/adjudication_is_refused_over_the_cap_and_allowed_with_the_override
        """
        ns = _inspected_claim_over_a_tiny_cap(api)

        adjudicated = adjudicate_claim(api, ns.claim["id"], override=True)

        assert adjudicated["status"] == "ADJUDICATED"
        assert_claim_split(adjudicated, 0, 95, 5, 0, 69666, 3667, split_basis="FINAL")
        assert adjudicated["chassis_liability_cents"] + adjudicated[
            "upfitter_liability_cents"
        ] + adjudicated["customer_goodwill_cents"] == CLAIM_COST_CENTS

    def test_the_override_suspends_the_gate_without_clamping_the_ledger(self, api):
        """The order absorbs the whole payout even though its budget was a hundred dollars.

        The order's three liability totals read the adjudicated split exactly, so the
        cap it was written with is not applied as a ceiling on the recorded figure.

        Design: Corner/endpoints/adjudication_is_refused_over_the_cap_and_allowed_with_the_override
        """
        ns = _inspected_claim_over_a_tiny_cap(api)
        adjudicate_claim(api, ns.claim["id"], override=True)

        order = read_order(api, ns.order["id"])

        assert order["warranty_liability_cap_cents"] == 10000
        assert_order_ledger(order, 0, 69666, 3667)

    def test_the_label_written_on_the_way_to_delivery_is_an_alterer_label(self, api):
        """A body went on and no equipment did, so the upfitter signs as an alterer.

        The label carries the alterer type against the upfitter as responsible party,
        the model's three ratings, and the payload certified off the measured basis of
        the mounted body; the artifact itself carries no version and no update stamp.

        Design: Corner/endpoints/adjudication_is_refused_over_the_cap_and_allowed_with_the_override
        """
        ns = _inspected_claim_over_a_tiny_cap(api)

        label = ns.label

        assert label["label_type"] == "ALTERER"
        assert label["responsible_party"] == "UPFITTER"
        assert label["certified_gvwr_lb"] == 19500
        assert label["certified_front_gawr_lb"] == 7000
        assert label["certified_rear_gawr_lb"] == 14706
        assert label["certified_payload_lb"] == 9680
        assert_immutable_label_shape(label)
        assert_axle_numbers(ns.cert_measured, 5099, 4721, 9820, 9680, component_count=1)

    def test_a_unit_already_committed_to_a_bay_window_cannot_be_bound_again(self, api):
        """The truck sitting in a booked window is not available to a second order.

        The second order's binding attempt is refused as already allocated, the first
        order is still scheduled, and the unit still names the order that holds it.

        Design: Corner/endpoints/adjudication_is_refused_over_the_cap_and_allowed_with_the_override
        """
        ns = service_order_world(
            api,
            order_type="CUSTOMER_SPECIFIC",
            order_number="UO-5031",
            config_code="CFG-SVC-A",
            with_equipment=False,
        )
        advance_to_released(api, ns)
        new_slot(api, ns.order["id"], ns.bay["id"], "2026-09-01", "2026-09-10")
        second_order = new_order(
            api,
            ns.config["id"],
            order_number="UO-5031-B",
            order_type="CUSTOMER_SPECIFIC",
            customer_id=ns.customer["id"],
            body_mount_offset_from_front_axle_in=120,
        )

        response = api.allocate_chassis(
            second_order["id"],
            allocate_chassis_payload(
                ns.chassis["id"], chassis_version(api, ns.chassis["id"])
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_CHASSIS_ALREADY_ALLOCATED, 409)
        assert read_order(api, ns.order["id"])["build_status"] == "SCHEDULED"
        assert read_chassis(api, ns.chassis["id"])["allocated_upfit_order_id"] == ns.order["id"]
        assert read_order(api, second_order["id"])["chassis_id"] is None
