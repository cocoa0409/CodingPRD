"""Read-after-write visibility of the recertification cascade.

Issuing a label touches four entities at once; every one of them must already
read correctly on the very next request, with no settling period.
"""
from datetime import datetime

from test_helpers import (
    CERTIFYING_INSPECTOR_1_USER_ID,
    INSPECTOR_1,
    PLANT_MANAGER,
    assert_certification_label,
    assert_disposition_ledger_conserved,
    assert_label_code,
    create_certification_label_payload,
    setup_test_passed_unit,
    validate_success,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z."""
    assert isinstance(value, str) and value, f"expected a timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _same_instant(actual: str, expected: str) -> bool:
    """True when two ISO 8601 UTC strings denote exactly the same instant."""
    return _instant(actual) == _instant(expected)


def test_the_label_cascade_is_visible_to_the_very_next_read(api):
    """One label issue writes the label, the unit, the shipment and the account,
    and every one of those writes is already visible to the next read: the label
    is ACTIVE in the creation body with the first traceability code of the day,
    the unit reads CERTIFIED with its retention deadline, the shipment reads
    READY_FOR_RETURN with a rebalanced disposition ledger, and the account reads
    no open shipments with the fourteen-day loaner recall stamped.

    PRD: "The new label is created in `ACTIVE` status with `issued_by_user_id`
    taken from the acting `X-User-ID`, and with `void_reason`, `voided_at` and
    `voided_by_user_id` all null."

    PRD: "The first label issued on 1 August 2026 for a model whose
    `standard_code` is `ND002` therefore reads `RCP-ND002-20260801-001`; a second
    label the same day for a different model whose `standard_code` is `ND010`
    reads `RCP-ND010-20260801-002`; and if the first of those is later voided, the
    next label issued that day is still numbered 003."

    PRD: "The unit advances `TEST_PASSED → CERTIFIED`, has `certified_at` stamped
    from the logical clock, and has `record_retention_until` set to
    `certified_at` advanced by the model's `record_retention_years`."

    PRD: "On the parent shipment, `units_in_process` falls by one and
    `units_certified` rises by one; if that brings `units_in_process` to 0, the
    shipment advances `IN_PROCESS → READY_FOR_RETURN`, which in turn decrements
    the account's `open_shipment_count` and, when that reaches 0, sets the
    account's `loaner_recall_due_at` to the clock plus 14 days."

    Design: Corner/consistency_model/the_label_cascade_is_visible_to_the_very_next_read
    """
    ctx = setup_test_passed_unit()
    unit = ctx["unit"]
    assert unit["recon_status"] == "TEST_PASSED"
    assert ctx["shipment"]["status"] == "IN_PROCESS"
    assert ctx["shipment"]["units_in_process"] == 1

    response = api.create_certification_label(
        create_certification_label_payload(unit["id"], unit["version"]), INSPECTOR_1
    )
    label = validate_success(response, 201)

    assert_certification_label(label)
    assert label["equipment_unit_id"] == unit["id"]
    assert label["status"] == "ACTIVE"
    assert label["standard_code_snapshot"] == "ND002"
    assert_label_code(label, "ND002", "20260801", 1)
    assert label["issued_by_user_id"] == CERTIFYING_INSPECTOR_1_USER_ID
    assert label["void_reason"] is None
    assert label["voided_at"] is None
    assert label["voided_by_user_id"] is None
    assert label["version"] == 1

    unit_after = validate_success(api.get_equipment_unit(unit["id"], INSPECTOR_1), 200)
    assert unit_after["recon_status"] == "CERTIFIED"
    assert unit_after["custody_status"] == "AT_PLANT"
    assert _same_instant(unit_after["certified_at"], "2026-08-01T00:00:00Z")
    assert _same_instant(unit_after["record_retention_until"], "2029-08-01T00:00:00Z")

    shipment_after = validate_success(
        api.get_intake_shipment(ctx["shipment"]["id"], PLANT_MANAGER), 200
    )
    assert shipment_after["units_in_process"] == 0
    assert shipment_after["units_certified"] == 1
    assert shipment_after["units_condemned"] == 0
    assert shipment_after["units_released"] == 0
    assert shipment_after["status"] == "READY_FOR_RETURN"
    assert_disposition_ledger_conserved(shipment_after)

    account_after = validate_success(
        api.get_customer_account(ctx["account"]["id"], PLANT_MANAGER), 200
    )
    assert account_after["open_shipment_count"] == 0
    assert _same_instant(account_after["loaner_recall_due_at"], "2026-08-15T00:00:00Z")
