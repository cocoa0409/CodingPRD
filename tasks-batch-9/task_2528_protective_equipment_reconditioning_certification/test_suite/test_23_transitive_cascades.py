"""Cascades that propagate through several entities from one request.

Condemning a shell walks unit, destruction record, shipment ledger, shipment
status, account exposure and the loaner recall deadline. Voiding a label walks
the same chain backwards.
"""
from test_helpers import (
    CONDEMN_IMPACTS,
    determine,
    issue_label,
    list_destruction_records,
    read_account,
    read_shipment,
    read_unit,
    setup_certified_units,
    setup_determined_units,
    setup_tested_units,
    void_label,
)


def _date_of(timestamp: str) -> str:
    """The UTC calendar date part of an ISO 8601 instant."""
    return timestamp[:10]


def test_a_condemn_determination_reaches_the_loaner_recall_deadline():
    """The only unit of a shipment is condemned, and the consequences run all the
    way out to the program's recall deadline two weeks from the clock.

    PRD §3.8: "Hop four checks whether that brought `units_in_process` to 0 and,
    if so, advances the shipment `IN_PROCESS → READY_FOR_RETURN`, which itself
    decrements the account's `open_shipment_count` by one and, when that reaches
    0, sets the account's `loaner_recall_due_at` to the logical clock plus 14
    days."

    Design: Difficulty/transitive_cascade/condemn_determination_cascades_five_hops_to_loaner_recall
    """
    ctx = setup_determined_units(
        unit_count=1, determination="CONDEMN", impacts=CONDEMN_IMPACTS
    )

    assert ctx["shell_test"]["determination"] == "CONDEMN"
    assert ctx["shell_test"]["determined_by_user_id"] == "insp-1"

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "CONDEMNED"
    assert unit["condemn_reason"] == "SI_EXCEEDS_LIMIT"
    assert unit["custody_status"] == "PENDING_DISPOSAL"

    records = list_destruction_records(unit["id"])
    assert len(records) == 1
    assert records[0]["status"] == "PENDING"
    assert records[0]["equipment_unit_id"] == unit["id"]
    assert records[0]["condemn_reason_snapshot"] == "SI_EXCEEDS_LIMIT"

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_in_process"] == 0
    assert shipment["units_condemned"] == 1
    assert shipment["status"] == "READY_FOR_RETURN"

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 0
    assert _date_of(account["loaner_recall_due_at"]) == "2026-08-15"


def test_a_condemnation_that_leaves_work_on_the_floor_stops_after_the_ledger_hop():
    """With a second unit still in process the cascade moves the ledger but does
    not close the shipment, so the account keeps its open shipment and no recall
    deadline is set.

    PRD §3.8: "Hop three decrements the parent shipment's `units_in_process` by
    one and increments its `units_condemned` by one."

    Design: Difficulty/transitive_cascade/condemn_determination_cascades_five_hops_to_loaner_recall
    """
    ctx = setup_tested_units(unit_count=2, impacts=CONDEMN_IMPACTS)

    determine(ctx["shell_tests"][0]["id"], "CONDEMN")

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_in_process"] == 1
    assert shipment["units_condemned"] == 1
    assert shipment["status"] == "IN_PROCESS"

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 1
    assert account["loaner_recall_due_at"] is None
    assert read_unit(ctx["units"][1]["id"])["recon_status"] == "TESTED"


def test_voiding_the_last_label_reopens_the_shipment_and_unlocks_settlement():
    """Voiding the only label on a closed-out shipment rewinds every effect of
    issuance: the ledger, the shipment status, the account exposure and the
    recall deadline all go back.

    PRD §3.7: "Fourth, if the shipment had already reached `READY_FOR_RETURN`, it
    reverts `READY_FOR_RETURN → IN_PROCESS`, which clears `final_total_cents` to
    null, sets `settlement_locked` back to false, increments the account's
    `open_shipment_count` by one and clears the account's `loaner_recall_due_at`
    to null."

    Design: Difficulty/transitive_cascade/label_void_compensates_five_hops_and_unlocks_settlement
    """
    ctx = setup_certified_units(unit_count=1)
    assert ctx["shipment"]["status"] == "READY_FOR_RETURN"
    assert ctx["account"]["open_shipment_count"] == 0
    assert _date_of(ctx["account"]["loaner_recall_due_at"]) == "2026-08-15"

    label = void_label(ctx["label"]["id"])

    assert label["status"] == "VOIDED"
    assert _date_of(label["voided_at"]) == "2026-08-01"
    assert label["voided_by_user_id"] == "comp-1"
    assert label["void_reason"] == "traceability code misprinted on the decal"

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "REPAIR_PENDING"
    assert unit["certified_at"] is None
    assert unit["record_retention_until"] is None

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_certified"] == 0
    assert shipment["units_in_process"] == 1
    assert shipment["status"] == "IN_PROCESS"
    assert shipment["final_total_cents"] is None
    assert shipment["settlement_locked"] is False

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 1
    assert account["loaner_recall_due_at"] is None


def test_voiding_a_label_on_a_shipment_still_in_process_moves_only_the_ledger():
    """When the shipment never reached READY_FOR_RETURN the void still rebalances
    the disposition ledger, but the account's exposure is untouched.

    PRD §3.7: "Third, on the parent shipment `units_certified` falls by one and
    `units_in_process` rises by one, keeping the disposition ledger of §2.8
    balanced."

    Design: Difficulty/transitive_cascade/label_void_compensates_five_hops_and_unlocks_settlement
    """
    ctx = setup_determined_units(unit_count=2, determination="PASS")
    label = issue_label(ctx["units"][0]["id"])
    assert read_shipment(ctx["shipment"]["id"])["units_certified"] == 1

    void_label(label["id"])

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_certified"] == 0
    assert shipment["units_in_process"] == 2
    assert shipment["status"] == "IN_PROCESS"

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 1
    assert account["loaner_recall_due_at"] is None
