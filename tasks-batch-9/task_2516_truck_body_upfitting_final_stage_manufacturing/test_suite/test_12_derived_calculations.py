"""Numbers the system computes for itself rather than accepting from a client.

The book axle split, the hydraulic waterfall, the committed auxiliary load, the
earliest feasible in-service date and the invoice are all derived, and each of
them is derived from a precisely stated set of contributing rows.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_HYDRAULIC_DEFICIT_UNRESOLVED,
    ERR_IN_SERVICE_DATE_INFEASIBLE,
)
from test_helpers.assertions import (
    assert_axle_numbers,
    assert_installation_hydraulics,
    assert_order_commitments,
    assert_order_dimensions,
)
from test_helpers.constants import (
    EQ_CRANE_6000,
    EQ_DUMP_HOIST_10T,
    EQ_LIFTGATE_2500,
    vin_f550,
)
from test_helpers.factories import weight_certification_payload
from test_helpers.fixtures import (
    allocate,
    approve_certification,
    catalog_service,
    draft_certification,
    new_configuration,
    new_customer,
    new_equipment_spec,
    new_order,
    patch_body_mount,
    plan_equipment,
    propose_interface,
    read_certification,
    read_chassis,
    read_installation,
    read_interface,
    read_order,
    received_and_inspected_chassis,
    reject_interface,
    release,
    remove_equipment,
    submit_engineering,
)

LIFTGATE_ODD = dict(EQ_LIFTGATE_2500, code="LIFTGATE-ODD", list_price_cents=333333)


def _submitted_service_order(api, order_number, *, vin_serial, availability="2026-08-05", **order):
    """A customer order on a weighed F550 unit, bound and sitting at engineering review."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api,
        ns.cm["id"],
        vin=vin_f550(vin_serial),
        availability_date=availability,
        measured=(4905, 2755),
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number=order_number,
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        **order,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.order = submit_engineering(api, ns.order["id"])
    return ns


def _waterfall_world(api):
    """One crane and one hoist planned on an order that has no truck under it yet."""
    ns = catalog_service(api, with_equipment=False)
    ns.crane = new_equipment_spec(api, EQ_CRANE_6000)
    ns.hoist = new_equipment_spec(api, EQ_DUMP_HOIST_10T)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(13), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5017",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.crane_install = plan_equipment(
        api, ns.order["id"], ns.crane["id"], 208, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.hoist_install = plan_equipment(
        api, ns.order["id"], ns.hoist["id"], 130, "SECONDARY", headers=users.TECHNICIAN
    )
    return ns


def _mixed_electrical_world(api):
    """A liftgate that stays, a crane that was stripped, and a splice awaiting a verdict."""
    ns = catalog_service(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5018",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.lift_install = plan_equipment(
        api, ns.order["id"], ns.liftgate["id"], 320, "NONE", headers=users.TECHNICIAN
    )
    ns.crane_install = plan_equipment(
        api, ns.order["id"], ns.crane["id"], 208, "PRIMARY", headers=users.TECHNICIAN
    )
    remove_equipment(api, ns.crane_install["id"], "customer dropped the crane from the spec")
    # PRD 3.5: the auxiliary ceiling is evaluated at proposal time with the
    # candidate counted in, and the F550 book allows 60 A.  The body's 12 plus
    # the surviving liftgate's 30 already commit 42, so the splice must stay
    # within the remaining 18 A for the proposal itself to be admissible.
    ns.splice = propose_interface(
        api, ns.order["id"], "DIRECT_SPLICE", 15, "DISCRETE_CIRCUIT", waiver=True
    )
    return ns


def _liftgate_only_world(api):
    """A single planned liftgate on a customer order, drawing thirty of the sixty amps."""
    ns = catalog_service(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5019",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.lift_install = plan_equipment(
        api, ns.order["id"], ns.liftgate["id"], 320, "NONE", headers=users.TECHNICIAN
    )
    ns.order = read_order(api, ns.order["id"])
    return ns


def _lead_time_catalog(api):
    """The F550 book, the service body, and both a non-hydraulic and a hydraulic item."""
    ns = catalog_service(api, with_equipment=False)
    ns.liftgate = new_equipment_spec(api, EQ_LIFTGATE_2500)
    ns.hoist = new_equipment_spec(api, EQ_DUMP_HOIST_10T)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    return ns


def _lead_time_order(api, ns, order_number, *, vin_serial, requested_date, spec, circuit):
    """One submitted order on a unit that becomes available on the tenth of August."""
    chassis = received_and_inspected_chassis(
        api,
        ns.cm["id"],
        vin=vin_f550(vin_serial),
        availability_date="2026-08-10",
        measured=(4905, 2755),
    )
    order = new_order(
        api,
        ns.config["id"],
        order_number=order_number,
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        requested_in_service_date=requested_date,
    )
    plan_equipment(api, order["id"], spec["id"], 320, circuit, headers=users.TECHNICIAN)
    allocate(api, order["id"], chassis["id"])
    return submit_engineering(api, order["id"])


def _pool_stock_world(api):
    """A tier-A pool build whose only standard item carries an awkward list price."""
    ns = catalog_service(api, with_equipment=False)
    ns.odd_liftgate = new_equipment_spec(api, LIFTGATE_ODD)
    ns.config = new_configuration(
        api,
        ns.cm["id"],
        ns.body["id"],
        config_code="CFG-POOL-A",
        standardization_tier="TIER_A",
        standard_equipment_spec_ids=[ns.odd_liftgate["id"]],
    )
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(15), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5021",
        order_type="POOL_STOCK",
        body_mount_offset_from_front_axle_in=120,
    )
    ns.lift_install = plan_equipment(
        api, ns.order["id"], ns.odd_liftgate["id"], 320, "NONE", headers=users.TECHNICIAN
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.order = submit_engineering(api, ns.order["id"])
    return ns


def _released_and_design_certified(api):
    """A released bare-body order carrying an approved book certification and an invoice."""
    ns = _submitted_service_order(api, "UO-5022", vin_serial=16)
    ns.cert = draft_certification(
        api, ns.order["id"], "AS_DESIGNED", expected_version=ns.order["version"]
    )
    ns.cert = approve_certification(api, ns.cert["id"])
    ns.order = release(api, ns.order["id"])
    return ns


class TestBookAxleSplitFromTheMountPosition:
    """The as-designed certification derives every figure from the book and the offset."""

    def test_the_stamped_axle_split_follows_the_body_centre_of_gravity(self, api):
        """One hundred and eighty-two inches behind the front axle puts most of the body on the rear.

        The body's centre of gravity sits sixty-two inches behind its own front
        edge, which is mounted one hundred and twenty inches behind the front axle,
        so of the twenty-one hundred pounds the rear axle carries nineteen hundred
        and eleven and the front carries one hundred and eighty-nine. The gross
        weight is the plain sum of curb weights and the body, unaffected by where
        along the frame the body sits.

        Design: Corner/calculations/as_designed_certification_stamps_the_book_axle_split
        """
        ns = _submitted_service_order(api, "UO-5016", vin_serial=12)

        certification = validate_success(
            api.create_weight_certification(
                weight_certification_payload(
                    ns.order["id"], "AS_DESIGNED", ns.order["version"]
                ),
                users.ENGINEER,
            ),
            201,
        )

        assert_axle_numbers(certification, 5009, 4591, 9600, 9900, component_count=1)

    def test_the_payload_capacity_takes_the_smallest_of_the_three_buckets(self, api):
        """The gross rating is the binding constraint here, not either axle rating.

        Nine thousand nine hundred pounds is what the gross rating leaves over the
        gross weight, and it is smaller than the head-room either axle rating
        allows, so it is the figure stamped. The row records the book basis, the
        single body component and the engineer who drafted it, and it starts as a
        draft.

        Design: Corner/calculations/as_designed_certification_stamps_the_book_axle_split
        """
        ns = _submitted_service_order(api, "UO-5016", vin_serial=12)

        certification = draft_certification(
            api, ns.order["id"], "AS_DESIGNED", expected_version=ns.order["version"]
        )

        assert certification["payload_capacity_lb"] == 19500 - certification["gvw_lb"]
        assert certification["payload_capacity_lb"] == 9900
        assert certification["basis"] == "AS_DESIGNED"
        assert certification["status"] == "DRAFT"
        assert certification["created_by_user_id"] == "eng-1"
        assert certification["included_component_count"] == 1


class TestHydraulicWaterfallByDutyPriority:
    """Eighteen gallons are handed out in duty order until the pool runs dry."""

    def test_nothing_is_granted_until_a_truck_is_actually_bound(self, api):
        """With no unit under the order the pool is zero and both items starve.

        The crane and the hoist each read a zero grant and a deficit verdict while
        the order carries no truck, because the available flow comes from the bound
        unit's own provision.

        Design: Corner/calculations/pto_waterfall_grants_the_first_duty_priority_before_the_second
        """
        ns = _waterfall_world(api)
        assert read_order(api, ns.order["id"])["chassis_id"] is None

        assert_installation_hydraulics(read_installation(api, ns.crane_install["id"]), 0, "DEFICIT")
        assert_installation_hydraulics(read_installation(api, ns.hoist_install["id"]), 0, "DEFICIT")

    def test_binding_the_truck_fills_the_first_bucket_before_the_second(self, api):
        """The crane takes its eight gallons whole; the hoist gets the ten that are left.

        Duty priority one is served before duty priority two, so the crane's demand
        of eight gallons is met in full and the hoist, which wants twelve, receives
        only the ten-gallon remainder of the eighteen-gallon provision and is left
        in deficit.

        Design: Corner/calculations/pto_waterfall_grants_the_first_duty_priority_before_the_second
        """
        ns = _waterfall_world(api)

        allocate(api, ns.order["id"], ns.chassis["id"])

        assert_installation_hydraulics(read_installation(api, ns.crane_install["id"]), 8, "OK")
        assert_installation_hydraulics(read_installation(api, ns.hoist_install["id"]), 10, "DEFICIT")
        assert ns.crane["duty_priority"] < ns.hoist["duty_priority"]

    def test_the_committed_flow_records_demand_rather_than_what_was_granted(self, api):
        """Twenty gallons are asked for even though only eighteen can be served.

        The order's committed flow is the sum of the two demands, not the sum of the
        two grants, and the binding itself completes normally with the unit reading
        allocated.

        Design: Corner/calculations/pto_waterfall_grants_the_first_duty_priority_before_the_second
        """
        ns = _waterfall_world(api)

        allocate(api, ns.order["id"], ns.chassis["id"])

        order = read_order(api, ns.order["id"])
        assert_order_commitments(order, flow_gpm=20)
        assert order["chassis_id"] == ns.chassis["id"]
        assert read_chassis(api, ns.chassis["id"])["status"] == "ALLOCATED"

    def test_the_unresolved_deficit_cannot_escape_into_production(self, api):
        """Release is the gate that refuses to let a starved item onto the floor.

        With the hoist still short of flow the release attempt is refused on the
        unresolved deficit and the order stays at engineering review.

        Design: Corner/calculations/pto_waterfall_grants_the_first_duty_priority_before_the_second
        """
        ns = _waterfall_world(api)
        allocate(api, ns.order["id"], ns.chassis["id"])
        submit_engineering(api, ns.order["id"])

        response = api.release_order(ns.order["id"], users.SCHEDULER)

        validate_error(response, ERR_HYDRAULIC_DEFICIT_UNRESOLVED, 409)
        assert_order_dimensions(
            read_order(api, ns.order["id"]), build_status="ENGINEERING_REVIEW"
        )


class TestAuxiliaryLoadMembership:
    """Only planned installations and approved interfaces are counted into the load."""

    def test_a_rejected_interface_and_a_removed_item_are_both_left_out(self, api):
        """Forty-two amps is the body plus the surviving liftgate, and nothing else.

        The splice is refused, so its fifteen amps never join the aggregate, and
        the crane was stripped, so its ten amps are gone too; the committed load is
        the body's twelve plus the liftgate's thirty. The stripped crane also took
        its hydraulic demand with it.

        Design: Corner/calculations/aux_load_counts_only_planned_installs_and_approved_interfaces
        """
        ns = _mixed_electrical_world(api)

        rejected = reject_interface(
            api,
            ns.splice["id"],
            "splice into the discrete circuit is not acceptable on this build",
            headers=users.OFFICER,
        )

        assert rejected["status"] == "REJECTED"
        assert_order_commitments(read_order(api, ns.order["id"]), aux_amps=42, flow_gpm=0)
        assert read_installation(api, ns.crane_install["id"])["status"] == "REMOVED"

    def test_the_warranty_verdict_survives_the_rejection_without_binding_the_truck(self, api):
        """The stamp on the row is one thing; the posture of the truck is another.

        A direct splice on this chassis network is computed as warranty-voiding and
        the row keeps that verdict after it is refused, yet the chassis warranty
        posture stays intact because a refused proposal never becomes binding.

        Design: Corner/calculations/aux_load_counts_only_planned_installs_and_approved_interfaces
        """
        ns = _mixed_electrical_world(api)

        reject_interface(
            api,
            ns.splice["id"],
            "splice into the discrete circuit is not acceptable on this build",
            headers=users.OFFICER,
        )

        assert read_interface(api, ns.splice["id"])["warranty_impact"] == "VOIDS"
        assert_order_commitments(
            read_order(api, ns.order["id"]), warranty_status="INTACT", aux_amps=42
        )


class TestAuxiliaryLoadFallsBackToTheBodyBaseline:
    """Strip every item and the committed load returns to the body's own draw."""

    def test_removing_the_only_item_leaves_the_body_baseline_behind(self, api):
        """Twelve amps is the floor of the aggregate, not zero.

        The liftgate's thirty amps leave the aggregate with it, and what remains is
        the body's own twelve amps; the order carries no hydraulic demand either.

        Design: Corner/calculations/committed_aux_amp_draw_falls_back_to_the_body_baseline_after_a_removal
        """
        ns = _liftgate_only_world(api)
        assert_order_commitments(ns.order, aux_amps=42)

        removed = remove_equipment(api, ns.lift_install["id"], "liftgate deleted from the order")

        assert removed["status"] == "REMOVED"
        assert_order_commitments(read_order(api, ns.order["id"]), aux_amps=12, flow_gpm=0)

    def test_the_stripped_row_keeps_no_flow_and_the_order_takes_a_new_version(self, api):
        """The order is the ledger holder for the aggregate, so it moves too.

        The removed row carries no allocated flow and no hydraulic verdict, and the
        order's version advances by exactly one because the recomputed aggregate
        lives on the order row.

        Design: Corner/calculations/committed_aux_amp_draw_falls_back_to_the_body_baseline_after_a_removal
        """
        ns = _liftgate_only_world(api)
        version_before = ns.order["version"]

        remove_equipment(api, ns.lift_install["id"], "liftgate deleted from the order")

        stripped = read_installation(api, ns.lift_install["id"])
        assert_installation_hydraulics(stripped, 0, "NOT_APPLICABLE")
        assert read_order(api, ns.order["id"])["version"] == version_before + 1


class TestEarliestFeasibleInServiceDate:
    """The lead time is built from the body family and the items hung on the truck."""

    def test_the_boundary_date_itself_is_feasible(self, api):
        """The second of September is exactly the earliest date, and exactly is enough.

        The clock stands at the first of August but the unit is not available until
        the tenth, so the count starts there; a service body allows twenty-one days
        and the single non-hydraulic liftgate adds two, landing on the second of
        September, which is the date the customer asked for.

        Design: Corner/calculations/in_service_date_exactly_at_the_earliest_feasible_boundary
        """
        ns = _lead_time_catalog(api)
        order = _lead_time_order(
            api,
            ns,
            "UO-5020",
            vin_serial=21,
            requested_date="2026-09-02",
            spec=ns.liftgate,
            circuit="NONE",
        )

        released = validate_success(api.release_order(order["id"], users.SCHEDULER))

        assert_order_dimensions(released, build_status="RELEASED")

    def test_the_release_prices_the_build_at_the_same_moment(self, api):
        """Body, liftgate, labour and the certification fee make up the invoice.

        The subtotal is the body's fourteen thousand five hundred dollars, the
        liftgate's three thousand two hundred and eighteen service-body labour hours
        at a hundred and fifteen dollars, and because a customer-specific order
        takes no standardization discount the discounted subtotal is the subtotal
        itself; being under twenty thousand dollars it draws the smallest
        certification fee.

        Design: Corner/calculations/in_service_date_exactly_at_the_earliest_feasible_boundary
        """
        ns = _lead_time_catalog(api)
        order = _lead_time_order(
            api,
            ns,
            "UO-5020",
            vin_serial=21,
            requested_date="2026-09-02",
            spec=ns.liftgate,
            circuit="NONE",
        )

        released = validate_success(api.release_order(order["id"], users.SCHEDULER))

        assert released["invoice_total_cents"] == 1450000 + 320000 + 18 * 11500 + 45000
        assert released["invoice_total_cents"] == 2022000

    def test_one_day_earlier_than_the_boundary_is_refused(self, api):
        """The first of September is a day short of the twenty-three-day lead time.

        An otherwise identical order asking for the first is refused at release on
        the infeasible in-service date and stays at engineering review.

        Design: Corner/calculations/in_service_date_exactly_at_the_earliest_feasible_boundary
        """
        ns = _lead_time_catalog(api)
        order = _lead_time_order(
            api,
            ns,
            "UO-5020",
            vin_serial=21,
            requested_date="2026-09-01",
            spec=ns.liftgate,
            circuit="NONE",
        )

        response = api.release_order(order["id"], users.SCHEDULER)

        validate_error(response, ERR_IN_SERVICE_DATE_INFEASIBLE, 422)
        assert_order_dimensions(
            read_order(api, order["id"]), build_status="ENGINEERING_REVIEW"
        )

    def test_a_hydraulic_item_pushes_the_boundary_three_days_later(self, api):
        """The same date that suits a liftgate build does not suit a hoist build.

        A hydraulic item costs five days of integration where a non-hydraulic one
        costs two, so the earliest feasible date moves to the fifth of September and
        the second is refused for this order.

        Design: Corner/calculations/in_service_date_exactly_at_the_earliest_feasible_boundary
        """
        ns = _lead_time_catalog(api)
        order = _lead_time_order(
            api,
            ns,
            "UO-5020",
            vin_serial=21,
            requested_date="2026-09-02",
            spec=ns.hoist,
            circuit="PRIMARY",
        )

        response = api.release_order(order["id"], users.SCHEDULER)

        validate_error(response, ERR_IN_SERVICE_DATE_INFEASIBLE, 422)


class TestPoolStockDiscountRoundsOnce:
    """The tier-A discount is rounded half up once and the fee band reads the result."""

    def test_the_awkward_percentage_is_rounded_half_up_exactly_once(self, api):
        """A subtotal of 1990333 cents gives a discount that is not a whole cent.

        Eight percent of the subtotal is 159226.64 cents, which rounds half up to
        159227, leaving a discounted subtotal of 1831106; that figure is below two
        million cents, so the smallest certification fee applies and the invoice is
        1876106 cents.

        Design: Corner/calculations/pool_stock_invoice_discount_rounds_half_up_exactly_once
        """
        ns = _pool_stock_world(api)

        released = validate_success(api.release_order(ns.order["id"], users.SCHEDULER))

        assert_order_dimensions(released, build_status="RELEASED")
        assert released["invoice_total_cents"] == 1876106

    def test_the_pool_build_stays_unowned_and_unpromised(self, api):
        """A pool-stock allocation is not a promise to anybody.

        The bound unit keeps its pool-stock ownership rather than being restamped to
        a customer, the order names no customer, and the contracted payload defaults
        to nothing at all.

        Design: Corner/calculations/pool_stock_invoice_discount_rounds_half_up_exactly_once
        """
        ns = _pool_stock_world(api)

        validate_success(api.release_order(ns.order["id"], users.SCHEDULER))

        assert read_chassis(api, ns.chassis["id"])["ownership"] == "POOL_STOCK"
        order = read_order(api, ns.order["id"])
        assert order["customer_id"] is None
        assert order["required_payload_lb"] == 0


class TestBodyMountPatchPropagates:
    """Sliding the body along the frame undoes the certification and re-prices the build."""

    def test_moving_the_body_voids_the_book_certification_without_touching_production(self, api):
        """One dimension steps back while the other stands still.

        The order records the new offset, the approved book certification is voided
        with the reason naming the mount change, the certification dimension falls
        back to nothing started, and the production dimension is left at released.

        Design: Corner/calculations/body_mount_patch_propagates_to_the_certification_and_the_invoice
        """
        ns = _released_and_design_certified(api)
        assert_order_dimensions(
            ns.order, build_status="RELEASED", compliance_status="DESIGN_CERTIFIED"
        )

        patched = patch_body_mount(api, ns.order["id"], 130)

        assert patched["body_mount_offset_from_front_axle_in"] == 130
        voided = read_certification(api, ns.cert["id"])
        assert voided["status"] == "VOIDED"
        assert voided["voided_reason"] == "BODY_MOUNT_CHANGED"
        assert_order_dimensions(
            patched, build_status="RELEASED", compliance_status="NOT_STARTED"
        )

    def test_the_recomputed_invoice_reaches_the_same_figure_it_started_from(self, api):
        """Moving the body changes no price input, so the recompute is a fixed point.

        The invoice is the body plus service-body labour with no discount and the
        smallest certification fee both before and after the move, because the mount
        position is not a priced input.

        Design: Corner/calculations/body_mount_patch_propagates_to_the_certification_and_the_invoice
        """
        ns = _released_and_design_certified(api)
        assert ns.order["invoice_total_cents"] == 1702000

        patched = patch_body_mount(api, ns.order["id"], 130)

        assert patched["invoice_total_cents"] == 1702000
        assert read_order(api, ns.order["id"])["invoice_total_cents"] == 1702000

    def test_a_certification_drafted_after_the_move_stamps_the_shifted_split(self, api):
        """Ten inches rearward moves a hundred and five pounds off the front axle.

        The fresh book certification reads 4904 pounds on the front axle and 4696 on
        the rear, while the gross weight and the payload capacity are unchanged
        because sliding the body neither adds nor removes weight.

        Design: Corner/calculations/body_mount_patch_propagates_to_the_certification_and_the_invoice
        """
        ns = _released_and_design_certified(api)
        patched = patch_body_mount(api, ns.order["id"], 130)

        fresh = draft_certification(
            api, ns.order["id"], "AS_DESIGNED", expected_version=patched["version"]
        )

        assert_axle_numbers(fresh, 4904, 4696, 9600, 9900, component_count=1)
