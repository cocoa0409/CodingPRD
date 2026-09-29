"""Two readings of the same truck: as designed versus as measured.

The certification bases and the warranty splits are both computed twice from the
same order — once from catalog intent and once from what the scale and the
inspector actually found — and the two readings must diverge by exact amounts.
"""

from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_axle_numbers,
    assert_claim_split,
    assert_order_commitments,
    assert_order_ledger,
)
from test_helpers.constants import BODY_SERVICE_11FT, CM_F550, EQ_CRANE_6000, EQ_LIFTGATE_2500
from test_helpers.fixtures import (
    adjudicate_claim,
    allocate,
    approve_certification,
    catalog_service,
    delivered_service_order,
    draft_certification,
    install_body,
    install_equipment,
    inspect_claim,
    new_customer,
    new_configuration,
    new_order,
    new_slot,
    new_work_bay,
    open_claim,
    plan_equipment,
    read_certification,
    read_order,
    received_and_inspected_chassis,
    release,
    start_slot,
    submit_engineering,
)


def _divergence_world(api):
    """A CUSTOMER_SPECIFIC service build with a crane bolted on and a liftgate still planned.

    The chassis rolled in at 4905 / 2755 pounds against catalog curb weights of
    4820 / 2680, the body is mounted 120 inches behind the front axle, the crane
    is planned at 208 inches and installed 40 pounds heavier than the catalog
    says, and the liftgate at 320 inches never leaves the plan.
    """
    ns = catalog_service(api)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4905, 2755))
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-1001",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.crane_install = plan_equipment(
        api, ns.order["id"], ns.crane["id"], 208, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.liftgate_install = plan_equipment(
        api, ns.order["id"], ns.liftgate["id"], 320, "NONE", headers=users.TECHNICIAN
    )
    ns.order = submit_engineering(api, ns.order["id"])
    ns.cert_designed = draft_certification(
        api, ns.order["id"], "AS_DESIGNED", expected_version=ns.order["version"]
    )
    ns.cert_designed = approve_certification(api, ns.cert_designed["id"])
    ns.order = release(api, ns.order["id"])
    ns.slot = new_slot(
        api,
        ns.order["id"],
        ns.bay["id"],
        "2026-09-01",
        "2026-09-10",
        slot_type="FINAL_QC",
    )
    ns.slot = start_slot(api, ns.slot["id"])
    ns.crane_install = install_equipment(api, ns.crane_install["id"], 1290)
    ns.order = install_body(api, ns.order["id"], 2160)
    return ns


class TestAxleLoadBasisDivergence:
    """The as-designed and as-measured bases read the same truck differently."""

    def test_as_designed_basis_uses_catalog_curb_weights_and_every_planned_item(self, api):
        """The design basis moments come from the book, not from the scale.

        Catalog curb weights of 4820 / 2680 carry the body, the cargo allowance,
        the crane and the still-planned liftgate, so all three planned
        components count toward the design reading.

        Design: Difficulty/dual_variant_calc/axle_load_as_designed_versus_as_measured_divergence
        """
        ns = _divergence_world(api)

        designed = read_certification(api, ns.cert_designed["id"])
        assert designed["basis"] == "AS_DESIGNED"
        assert_axle_numbers(designed, 4491, 7139, 11630, 7870, component_count=3)

    def test_as_measured_basis_uses_scale_weights_and_installed_items_only(self, api):
        """The measured basis reads the scale ticket and ignores unbolted plans.

        The crane weighed 1290 pounds when it went on and the body 2160, while
        the liftgate is still only planned, so the measured reading counts two
        components instead of three.

        Design: Difficulty/dual_variant_calc/axle_load_as_designed_versus_as_measured_divergence
        """
        ns = _divergence_world(api)

        measured = draft_certification(
            api, ns.order["id"], "AS_MEASURED", expected_version=ns.order["version"]
        )
        assert measured["basis"] == "AS_MEASURED"
        assert_axle_numbers(measured, 5048, 6062, 11110, 8390, component_count=2)

    def test_the_two_bases_diverge_by_exactly_the_expected_margins(self, api):
        """Both certifications coexist on one order and disagree by fixed amounts.

        The measured front axle sits 557 pounds heavier than the designed one
        while the designed gross weight sits 520 pounds heavier than the
        measured one, because the liftgate that hangs behind the rear axle is
        counted only in the design reading.

        Design: Difficulty/dual_variant_calc/axle_load_as_designed_versus_as_measured_divergence
        """
        ns = _divergence_world(api)
        measured = draft_certification(
            api, ns.order["id"], "AS_MEASURED", expected_version=ns.order["version"]
        )
        designed = read_certification(api, ns.cert_designed["id"])

        assert measured["front_axle_load_lb"] - designed["front_axle_load_lb"] == 557
        assert designed["gvw_lb"] - measured["gvw_lb"] == 520
        assert measured["payload_capacity_lb"] - designed["payload_capacity_lb"] == 520
        assert designed["upfit_order_id"] == measured["upfit_order_id"] == ns.order["id"]

    def test_the_planned_positions_behind_the_catalog_numbers_are_the_ones_seeded(self, api):
        """The catalog rows that feed both bases are the ones the plant published.

        Both readings stand on the same F550 book entry, the same eleven-foot
        service body and the same two pieces of equipment, so the divergence can
        only come from the basis and not from differing inputs.

        Design: Difficulty/dual_variant_calc/axle_load_as_designed_versus_as_measured_divergence
        """
        ns = _divergence_world(api)

        assert ns.cm["curb_front_axle_lb"] == CM_F550["curb_front_axle_lb"]
        assert ns.cm["curb_rear_axle_lb"] == CM_F550["curb_rear_axle_lb"]
        assert ns.body["weight_lb"] == BODY_SERVICE_11FT["weight_lb"]
        assert ns.crane["weight_lb"] == EQ_CRANE_6000["weight_lb"]
        assert ns.liftgate["weight_lb"] == EQ_LIFTGATE_2500["weight_lb"]
        assert ns.chassis["measured_front_axle_weight_lb"] == 4905
        assert ns.chassis["measured_rear_axle_weight_lb"] == 2755
        assert ns.crane_install["actual_weight_lb"] == 1290
        assert ns.liftgate_install["status"] == "PLANNED"


class TestWarrantySplitBasisDivergence:
    """A chassis-electrical claim is priced twice: on intake and on adjudication."""

    def _tainted_claim_world(self, api):
        ns = delivered_service_order(
            api,
            interfaces=[("CAN_GATEWAY", 8, "J1939_BUS")],
            order_type="CUSTOMER_SPECIFIC",
            warranty_liability_cap_cents=5000000,
        )
        ns.claim = open_claim(
            api, ns.order["id"], "CHASSIS_ELECTRICAL", 73333, claim_number="WC-3001"
        )
        return ns

    def test_provisional_split_on_intake_follows_the_base_table(self, api):
        """A fresh claim is priced from the failure system alone.

        A chassis-electrical failure splits sixty / thirty-five / five before
        anyone has looked at the truck, and the cents land on 44000 / 25667 /
        3666 with the goodwill share absorbing the rounding remainder.

        Design: Difficulty/dual_variant_calc/warranty_split_provisional_versus_final_taint_shift
        """
        ns = self._tainted_claim_world(api)

        assert_claim_split(
            ns.claim, 60, 35, 5, 44000, 25667, 3666, split_basis="PROVISIONAL"
        )
        assert ns.claim["status"] == "SUBMITTED"

    def test_confirmed_taint_on_a_conditional_chassis_shifts_forty_five_points(self, api):
        """Adjudication re-prices the same claim once the taint is confirmed.

        The gateway interface leaves the chassis warranty CONDITIONAL, so a
        confirmed taint on a chassis system moves forty-five points from the
        chassis maker to the upfitter, giving fifteen / eighty / five and cents
        of 11000 / 58666 / 3667.

        Design: Difficulty/dual_variant_calc/warranty_split_provisional_versus_final_taint_shift
        """
        ns = self._tainted_claim_world(api)
        assert_order_commitments(read_order(api, ns.order["id"]), warranty_status="CONDITIONAL")
        assert ns.interfaces[0]["warranty_impact"] == "CONDITIONAL"

        inspect_claim(api, ns.claim["id"], True)
        adjudicated = adjudicate_claim(api, ns.claim["id"])

        assert_claim_split(adjudicated, 15, 80, 5, 11000, 58666, 3667, split_basis="FINAL")
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["taint_confirmed"] is True

    def test_the_upfitter_share_moves_by_exactly_the_repriced_delta(self, api):
        """The two readings of one claim differ by a fixed number of cents.

        The upfitter share climbs from 25667 cents provisionally to 58666 cents
        finally — a delta of 32999 — and the order ledger only counts the claim
        once it has been adjudicated.

        Design: Difficulty/dual_variant_calc/warranty_split_provisional_versus_final_taint_shift
        """
        ns = self._tainted_claim_world(api)
        assert_order_ledger(read_order(api, ns.order["id"]), 0, 0, 0)

        inspect_claim(api, ns.claim["id"], True)
        adjudicated = adjudicate_claim(api, ns.claim["id"])

        assert (
            adjudicated["upfitter_liability_cents"] - ns.claim["upfitter_liability_cents"]
            == 32999
        )
        assert ns.claim["chassis_liability_cents"] - adjudicated["chassis_liability_cents"] == 33000
        assert_order_ledger(read_order(api, ns.order["id"]), 11000, 58666, 3667)
