"""Battery-assembly verification axes, the derived certification join and rework."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import assert_assembly_axes, assert_close
from test_helpers.factories import (
    capacity_test_payload,
    insulation_verification_payload,
    rework_payload,
    torque_verification_payload,
)
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def _record(world: World, assembly_id: str, payload):
    return validate_success(
        world.api.record_verification(assembly_id, payload, world.qa_a), 200
    )


def test_the_two_axes_are_independent_and_certification_is_their_join(world: World):
    """An insulation PASS alone leaves certification PENDING, and one FAIL rejects immediately.

    "It is `CERTIFIED` only when both `torque_status` and `insulation_status` are `PASS`; it is
    `REJECTED` when either axis is `FAIL`; and it remains `PENDING` for as long as either axis is
    still `PENDING`." Insulation resistance exactly at the assembly's minimum passes, while a
    torque of 22.10 Nm sits above the inclusive upper edge of 20.00 * 1.10 and fails.

    Design: Difficulty/non_linear_state_machine/battery_assembly_parallel_axes_rework_generations
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-0001", 9)
    assembly = world.add_assembly(lot["id"], "ASM-0001", 6)
    assert_assembly_axes(
        assembly,
        torque_status=C.AXIS_PENDING,
        insulation_status=C.AXIS_PENDING,
        certification_status=C.CERT_PENDING,
    )
    assert assembly["measured_torque_nm"] is None
    assert assembly["measured_ir_megaohm"] is None

    after_ir = _record(world, assembly["id"], insulation_verification_payload(1.00, 500))
    assert_assembly_axes(
        after_ir,
        torque_status=C.AXIS_PENDING,
        insulation_status=C.AXIS_PASS,
        certification_status=C.CERT_PENDING,
    )

    after_torque = _record(world, assembly["id"], torque_verification_payload(22.10, 12))
    assert_assembly_axes(
        after_torque,
        torque_status=C.AXIS_FAIL,
        insulation_status=C.AXIS_PASS,
        certification_status=C.CERT_REJECTED,
    )

    validate_error(
        world.api.record_verification(
            assembly["id"], torque_verification_payload(20.00, 12), world.qa_a
        ),
        E.ERR_ASSEMBLY_AXIS_ALREADY_RECORDED,
    )
    unchanged = world.read_assembly(assembly["id"])
    assert unchanged["torque_status"] == C.AXIS_FAIL
    assert_close(unchanged["measured_torque_nm"], 22.10, "measured_torque_nm", 2)


def test_rework_resets_both_axes_so_the_same_torque_pass_no_longer_certifies(world: World):
    """The identical torque reading certifies in one generation and not in the next.

    "A successful rework resets `torque_status` and `insulation_status` to `PENDING`, clears
    `measured_torque_nm` and `measured_ir_megaohm` back to null, resets `certification_status` to
    `PENDING`, and increments `rework_count` by 1." A torque of 19.00 Nm sits exactly on the
    inclusive lower edge of 20.00 * 0.95 and passes, yet certification only completes once the
    destroyed insulation evidence is re-established, after which a further rework is refused.

    Design: Difficulty/non_linear_state_machine/battery_assembly_parallel_axes_rework_generations
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-0001", 9)
    assembly = world.add_assembly(lot["id"], "ASM-0001", 6)
    _record(world, assembly["id"], insulation_verification_payload(1.00, 500))
    _record(world, assembly["id"], torque_verification_payload(22.10, 12))

    reworked = validate_success(
        world.api.rework_assembly(
            assembly["id"], rework_payload("retorque all links"), world.sup_a
        ),
        200,
    )
    assert reworked["rework_count"] == 1
    assert_assembly_axes(
        reworked,
        torque_status=C.AXIS_PENDING,
        insulation_status=C.AXIS_PENDING,
        certification_status=C.CERT_PENDING,
    )
    assert reworked["measured_torque_nm"] is None
    assert reworked["measured_ir_megaohm"] is None

    second_generation = _record(
        world, assembly["id"], torque_verification_payload(19.00, 12)
    )
    assert_assembly_axes(
        second_generation,
        torque_status=C.AXIS_PASS,
        insulation_status=C.AXIS_PENDING,
        certification_status=C.CERT_PENDING,
    )

    certified = _record(world, assembly["id"], insulation_verification_payload(1.00, 500))
    assert certified["certification_status"] == C.CERT_CERTIFIED

    validate_error(
        world.api.rework_assembly(
            assembly["id"], rework_payload("no defect - must be refused"), world.sup_a
        ),
        E.ERR_ASSEMBLY_STATE_INVALID,
    )
    assert world.read_assembly(assembly["id"])["rework_count"] == 1


def test_scheduling_is_refused_for_pending_and_for_rejected_assemblies_alike(world: World):
    """Neither an undecided nor a rejected assembly may be booked into a chamber.

    "The assembly's `certification_status` must be `CERTIFIED`; a `PENDING`, `REJECTED` or
    `REVOKED` assembly is refused with `ERR_ASSEMBLY_NOT_CERTIFIED`." One assembly holds a torque
    PASS with insulation still undecided, the other has failed insulation at 0.99 against a
    minimum of 1.00, and neither attempt leaves a test row behind.

    Design: Difficulty/cross_entity_state_dependency/capacity_test_requires_certified_assembly
    """
    chamber_id = world.add_chamber()
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-H", 9)

    h1 = world.add_assembly(lot["id"], "ASM-H1", 6)
    pending = _record(world, h1["id"], torque_verification_payload(20.00, 12))
    assert pending["certification_status"] == C.CERT_PENDING

    h2 = world.add_assembly(lot["id"], "ASM-H2", 6, case_type="POLY_CASE")
    rejected = _record(world, h2["id"], insulation_verification_payload(0.99, 500))
    assert rejected["certification_status"] == C.CERT_REJECTED

    for assembly_id in (h1["id"], h2["id"]):
        validate_error(
            world.api.create_capacity_test(
                capacity_test_payload(
                    assembly_id,
                    chamber_id,
                    "2026-09-03T08:00:00Z",
                    "2026-09-03T10:00:00Z",
                    draw_kw=5.00,
                ),
                world.qa_a,
            ),
            E.ERR_ASSEMBLY_NOT_CERTIFIED,
        )

    rows, _ = validate_paginated(world.api.list_capacity_tests(world.qa_a))
    assert rows == [], rows


def test_the_identical_scheduling_payload_succeeds_once_the_assembly_certifies(world: World):
    """Nothing about the request changes; the assembly's derived state does.

    "The owning lot must be in `ASSEMBLY` or `LOT_TESTING` -- tests may legitimately be booked
    before the plan is drawn -- and its hold must be clear." With the insulation axis recorded at
    exactly the minimum the assembly joins to `CERTIFIED`, and the same payload that was refused
    now books the chamber window.

    Design: Difficulty/cross_entity_state_dependency/capacity_test_requires_certified_assembly
    """
    chamber_id = world.add_chamber()
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-H", 9)
    h1 = world.add_assembly(lot["id"], "ASM-H1", 6)
    _record(world, h1["id"], torque_verification_payload(20.00, 12))

    payload = capacity_test_payload(
        h1["id"], chamber_id, "2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z", draw_kw=5.00
    )
    validate_error(
        world.api.create_capacity_test(payload, world.qa_a), E.ERR_ASSEMBLY_NOT_CERTIFIED
    )

    certified = _record(world, h1["id"], insulation_verification_payload(1.00, 500))
    assert certified["certification_status"] == C.CERT_CERTIFIED

    booked = validate_success(world.api.create_capacity_test(payload, world.qa_a), 201)
    assert booked["test_state"] == C.TEST_STATE_SCHEDULED
    assert booked["assembly_id"] == h1["id"]

    rows, _ = validate_paginated(world.api.list_capacity_tests(world.qa_a))
    assert len(rows) == 1, rows
