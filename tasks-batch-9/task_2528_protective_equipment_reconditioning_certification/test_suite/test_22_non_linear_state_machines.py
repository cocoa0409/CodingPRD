"""State machines that are not a single forward chain.

A unit carries two independent status axes, and a repair order's verification
cycle can loop back on itself twice before collapsing into condemnation.
"""
from test_helpers import (
    burn_verification_attempts,
    install_repair_order,
    list_destruction_records,
    read_part,
    read_repair_order,
    read_shipment,
    read_unit,
    setup_certified_units,
    setup_repair_order,
    stage_unit,
    verify_repair_order,
    void_label,
)


def test_staging_moves_only_the_custody_axis_and_leaves_recon_status_certified():
    """Staging a certified shell for return advances custody without disturbing
    the reconditioning axis.

    PRD §3.7: "Physical hand-back is tracked on the custody axis, which advances
    under its own requests and never touches `recon_status`."

    Design: Difficulty/non_linear_state_machine/unit_recon_and_custody_axes_advance_independently
    """
    ctx = setup_certified_units(unit_count=1)
    before = read_unit(ctx["unit"]["id"])
    assert before["recon_status"] == "CERTIFIED"
    assert before["custody_status"] == "AT_PLANT"

    staged = stage_unit(ctx["unit"]["id"])

    assert staged["custody_status"] == "STAGED_FOR_RETURN"
    assert staged["recon_status"] == "CERTIFIED"
    assert staged["version"] == before["version"] + 1
    assert staged["certified_at"] is not None


def test_a_void_rewinds_the_recon_axis_while_the_custody_axis_stays_staged():
    """A label void drags the reconditioning axis back to REPAIR_PENDING and
    clears the retention stamps, yet the shell is still physically staged.

    PRD §3.7: "Second, the unit reverts `CERTIFIED → REPAIR_PENDING`, and both
    its `certified_at` and its `record_retention_until` are cleared to null — the
    retention clock never started, because the certification never happened."

    Design: Difficulty/non_linear_state_machine/unit_recon_and_custody_axes_advance_independently
    """
    ctx = setup_certified_units(unit_count=1)
    stage_unit(ctx["unit"]["id"])

    void_label(ctx["label"]["id"])

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "REPAIR_PENDING"
    assert unit["custody_status"] == "STAGED_FOR_RETURN"
    assert unit["certified_at"] is None
    assert unit["record_retention_until"] is None
    assert read_shipment(ctx["shipment"]["id"])["status"] == "IN_PROCESS"


def test_the_first_two_failed_verifications_cycle_the_order_back_to_parts_pending():
    """Two failed sign-offs are absorbed by the cycle: the counter climbs and the
    order returns to PARTS_PENDING with its consumed parts left alone.

    PRD §3.6: "When the order's `verification_failure_count` plus one is less
    than or equal to 2, the counter is incremented and the order cycles back
    `INSTALLED → PARTS_PENDING`; lines already in `INSTALLED` status stay there,
    because the parts have been physically consumed and are not returned to
    stock."

    Design: Difficulty/non_linear_state_machine/repair_order_verification_cycle_exhausts_then_condemns
    """
    ctx = setup_repair_order(target_status="INSTALLED", quantity=1, received_qty=4)
    order_id = ctx["repair_order"]["id"]

    first = verify_repair_order(order_id, "FAILED")
    assert first["status"] == "PARTS_PENDING"
    assert first["verification_failure_count"] == 1

    install_repair_order(order_id)
    second = verify_repair_order(order_id, "FAILED")
    assert second["status"] == "PARTS_PENDING"
    assert second["verification_failure_count"] == 2

    assert read_unit(ctx["unit"]["id"])["recon_status"] == "REPAIR_PENDING"
    part = read_part(ctx["part"]["id"])
    assert part["consumed_qty"] == 1
    assert part["on_hand_qty"] == 3


def test_the_third_failed_verification_cancels_the_order_and_condemns_the_unit():
    """The exhausting attempt is still counted, the order is cancelled with the
    documented reason, and the shell is condemned as unrepairable.

    PRD §3.6: "When `verification_failure_count` plus one exceeds 2, the counter
    is still incremented — so it records every failed attempt including the
    exhausting one — the order's `cancel_reason` is set to `verification attempts
    exhausted`, the order advances `INSTALLED → CANCELLED`, and the unit advances
    `REPAIR_PENDING → CONDEMNED` with `condemn_reason` `REPAIR_UNSUCCESSFUL` and
    the full four-hop cascade of §3.8."

    Design: Difficulty/non_linear_state_machine/repair_order_verification_cycle_exhausts_then_condemns
    """
    ctx = setup_repair_order(target_status="INSTALLED", quantity=1, received_qty=4)
    order_id = ctx["repair_order"]["id"]
    burn_verification_attempts(order_id, attempts=2)

    exhausted = verify_repair_order(order_id, "FAILED")

    assert exhausted["status"] == "CANCELLED"
    assert exhausted["verification_failure_count"] == 3
    assert exhausted["cancel_reason"] == "verification attempts exhausted"
    assert read_repair_order(order_id)["status"] == "CANCELLED"

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "CONDEMNED"
    assert unit["condemn_reason"] == "REPAIR_UNSUCCESSFUL"
    assert unit["custody_status"] == "PENDING_DISPOSAL"

    records = list_destruction_records(unit["id"])
    assert len(records) == 1
    assert records[0]["status"] == "PENDING"
    assert records[0]["condemn_reason_snapshot"] == "REPAIR_UNSUCCESSFUL"

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_condemned"] == 1
    assert shipment["units_in_process"] == 0
    assert shipment["status"] == "READY_FOR_RETURN"
