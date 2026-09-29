"""Nothing is recomputed later: a write's own response already shows what it derived.

Two writes reach sideways out of the row they return — planning a crane rewrites the
parent order's hydraulic and electrical ledgers while returning the child, and approving a
certification advances the parent's compliance dimension while returning the certification.
Both are observable in the same request, and a read issued straight afterwards agrees.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import test_users as users
from test_helpers.assertions import assert_axle_numbers
from test_helpers.factories import equipment_installation_payload
from test_helpers.fixtures import (
    advance_to_in_build,
    advance_to_released,
    approve_certification,
    draft_certification,
    install_body,
    pin_clock,
    plan_equipment,
    projection,
    read_certification,
    read_installation,
    read_order,
    service_order_world,
)

BODY_ACTUAL_WEIGHT_LB = 2160
CRANE_MOUNT_CG_IN = 208
VOLATILE_FIELDS = ("updated_at", "version")


def _truck_on_the_floor_with_its_body_bolted_down(api):
    """UO-5045 in a started body-mount window, body mounted, design basis certified.

    The design certification is approved during setup because the measured basis may only
    be approved once the compliance dimension has taken its first step.
    """
    ns = service_order_world(
        api,
        order_type="CUSTOMER_SPECIFIC",
        order_number="UO-5045",
        config_code="CFG-SVC-A",
    )
    advance_to_released(api, ns)
    pin_clock(api, "2026-08-20T08:00:00Z")
    advance_to_in_build(api, ns, start_date="2026-08-20", end_date="2026-08-28")
    ns.order = install_body(api, ns.order["id"], BODY_ACTUAL_WEIGHT_LB)
    ns.cert_designed = approve_certification(
        api, draft_certification(api, ns.order["id"], "AS_DESIGNED")["id"]
    )
    ns.order = read_order(api, ns.order["id"])
    return ns


def _without_volatile_fields(row):
    return {k: v for k, v in row.items() if k not in VOLATILE_FIELDS}


class TestAWriteResponseAlreadyCarriesWhatItDerived:
    """The waterfall and the ledgers run inside the request, not behind it."""

    def test_the_installation_response_already_shows_its_hydraulic_grant(self, api):
        """The crane comes back with flow already allocated to it.

        The child row returned by the create is at planned status with its hydraulic
        standing resolved and its eight-gallon demand fully granted, so the waterfall ran
        inside this very request.

        Design: Corner/consistency_model/every_write_response_already_shows_the_derived_state_it_caused
        """
        ns = _truck_on_the_floor_with_its_body_bolted_down(api)

        installation = validate_success(
            api.create_equipment_installation(
                equipment_installation_payload(
                    ns.order["id"],
                    ns.crane["id"],
                    mount_cg_from_front_axle_in=CRANE_MOUNT_CG_IN,
                    hydraulic_circuit="PRIMARY",
                ),
                users.TECHNICIAN,
            ),
            201,
        )

        assert installation["status"] == "PLANNED"
        assert installation["hydraulic_status"] == "OK"
        assert installation["allocated_flow_gpm"] == 8

    def test_the_parent_ledgers_are_readable_without_any_further_write(self, api):
        """Planning a child rewrote the parent, and the parent read proves it.

        A read of the order issued straight after the create reports the committed
        power-take-off flow the crane demands and the auxiliary draw of body plus crane
        together, with nothing done in between.

        Design: Corner/consistency_model/every_write_response_already_shows_the_derived_state_it_caused
        """
        ns = _truck_on_the_floor_with_its_body_bolted_down(api)
        plan_equipment(api, ns.order["id"], ns.crane["id"], CRANE_MOUNT_CG_IN, "PRIMARY")

        order = read_order(api, ns.order["id"])

        assert order["committed_pto_flow_gpm"] == 8
        assert order["committed_aux_amp_draw"] == 22

    def test_the_certification_create_response_already_carries_its_weights(self, api):
        """The numbers are on the 201, not null waiting to be filled.

        The measured basis is computed inside the create request off the scale ticket and
        the actual body weight, counting the body alone because a merely planned crane is
        not yet bolted to the truck.

        Design: Corner/consistency_model/every_write_response_already_shows_the_derived_state_it_caused
        """
        ns = _truck_on_the_floor_with_its_body_bolted_down(api)
        plan_equipment(api, ns.order["id"], ns.crane["id"], CRANE_MOUNT_CG_IN, "PRIMARY")

        certification = draft_certification(api, ns.order["id"], "AS_MEASURED")

        assert_axle_numbers(certification, 5099, 4721, 9820, 9680, component_count=1)

    def test_the_approval_response_and_the_parent_read_agree_at_once(self, api):
        """Approving the child moved the parent's compliance dimension in the same request.

        The approve response shows the certification approved with its approver recorded,
        and a read of the order taken immediately afterwards already reports the measured
        step of the compliance dimension.

        Design: Corner/consistency_model/every_write_response_already_shows_the_derived_state_it_caused
        """
        ns = _truck_on_the_floor_with_its_body_bolted_down(api)
        plan_equipment(api, ns.order["id"], ns.crane["id"], CRANE_MOUNT_CG_IN, "PRIMARY")
        certification = draft_certification(api, ns.order["id"], "AS_MEASURED")

        approved = validate_success(
            api.approve_weight_certification(certification["id"], users.OFFICER)
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "co-1"
        assert read_order(api, ns.order["id"])["compliance_status"] == "MEASURED_CERTIFIED"


class TestReadAfterWriteReturnsTheSameRow:
    """A follow-up read is not a second, slower source of truth."""

    def test_the_installation_read_matches_the_body_the_create_returned(self, api):
        """Field for field, only the mutation stamps may differ.

        Reading the crane back returns the same body the create returned once the
        updated-at stamp and the version counter are set aside.

        Design: Corner/consistency_model/every_write_response_already_shows_the_derived_state_it_caused
        """
        ns = _truck_on_the_floor_with_its_body_bolted_down(api)

        created = validate_success(
            api.create_equipment_installation(
                equipment_installation_payload(
                    ns.order["id"],
                    ns.crane["id"],
                    mount_cg_from_front_axle_in=CRANE_MOUNT_CG_IN,
                    hydraulic_circuit="PRIMARY",
                ),
                users.TECHNICIAN,
            ),
            201,
        )
        fetched = read_installation(api, created["id"])

        assert _without_volatile_fields(fetched) == _without_volatile_fields(created)

    def test_the_certification_read_matches_the_body_the_approval_returned(self, api):
        """The approved certification is complete the moment it is returned.

        Reading the certification back reproduces the approval response field for field
        apart from the mutation stamps, so no weight, status or approver was filled in
        after the fact.

        Design: Corner/consistency_model/every_write_response_already_shows_the_derived_state_it_caused
        """
        ns = _truck_on_the_floor_with_its_body_bolted_down(api)
        plan_equipment(api, ns.order["id"], ns.crane["id"], CRANE_MOUNT_CG_IN, "PRIMARY")
        certification = draft_certification(api, ns.order["id"], "AS_MEASURED")

        approved = validate_success(
            api.approve_weight_certification(certification["id"], users.OFFICER)
        )
        fetched = read_certification(api, certification["id"])

        assert _without_volatile_fields(fetched) == _without_volatile_fields(approved)

    def test_the_projection_reads_live_state_rather_than_a_cached_snapshot(self, api):
        """Issued right after the crane was planned, the projection already counts it.

        The design basis, which counts planned items, picks the crane up immediately and
        reports two components with the axle split it produces; the measured basis, taken
        in the same breath, still counts only the body, because the crane is not yet on
        the truck.

        Design: Corner/consistency_model/every_write_response_already_shows_the_derived_state_it_caused
        """
        ns = _truck_on_the_floor_with_its_body_bolted_down(api)
        plan_equipment(api, ns.order["id"], ns.crane["id"], CRANE_MOUNT_CG_IN, "PRIMARY")

        designed = projection(api, ns.order["id"], "AS_DESIGNED")
        measured = projection(api, ns.order["id"], "AS_MEASURED")

        assert_axle_numbers(designed, 4959, 5891, 10850, 8650, component_count=2)
        assert_axle_numbers(measured, 5099, 4721, 9820, 9680, component_count=1)
