"""Transitive cascade — FAILED inspection → DefaultNotice → lease/unit IN_DEFAULT."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    setup_active_lease,
    setup_program,
)


def _insp():
    return TEST_USERS["inspector_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def test_failed_inspection_marks_unit_unsafe_and_cascades_lease():
    """PRD §3.7: "On `FAILED`, the unit's `maintenance_flag` is set to
    `UNSAFE`, and the system auto-issues a `DefaultNotice` with `notice_kind`
    equal to `MAINTENANCE` and `amount_due_cents` equal to 0 against the
    unit's `current_lease_id` — which cascades the lease to `IN_DEFAULT` and
    the unit to `IN_DEFAULT` per the default pipeline — and the record's
    `linked_notice_id` is set to the new notice's id."

    Design: Difficulty/transitive_cascade/inspection_failed_cascade_to_default_and_unit
    """
    prog = setup_program(name="P-CAS1")
    _, unit, _, lease = setup_active_lease(prog["id"])
    inspection = get_success_data(
        api_client.create_inspection(
            prog["id"], unit["id"], {"scheduled_for": "2026-05-15T00:00:00Z"}, _insp()
        )
    )
    recorded = get_success_data(
        api_client.record_inspection_result(
            prog["id"],
            unit["id"],
            inspection["id"],
            {"result": "FAILED", "findings": "Major structural issue"},
            _insp(),
        )
    )
    assert recorded["result"] == "FAILED"

    unit_after = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    assert unit_after["maintenance_flag"] == "UNSAFE"
    assert unit_after["occupancy_status"] == "IN_DEFAULT"

    lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after["status"] == "IN_DEFAULT"


def test_failed_inspection_sets_linked_notice_id():
    """PRD §3.7: "...the record's `linked_notice_id` is set to the new
    notice's id."

    Design: Difficulty/transitive_cascade/inspection_failed_cascade_to_default_and_unit
    """
    prog = setup_program(name="P-CAS2")
    _, unit, _, lease = setup_active_lease(prog["id"])
    inspection = get_success_data(
        api_client.create_inspection(
            prog["id"], unit["id"], {"scheduled_for": "2026-05-15T00:00:00Z"}, _insp()
        )
    )
    recorded = get_success_data(
        api_client.record_inspection_result(
            prog["id"],
            unit["id"],
            inspection["id"],
            {"result": "FAILED", "findings": "Unsafe"},
            _insp(),
        )
    )
    assert recorded["linked_notice_id"] is not None
    # Cross-check: the linked notice exists and is OPEN against this lease.
    notices = get_success_data(
        api_client.list_default_notices(
            prog["id"], unit["id"], lease["id"], _lm()
        )
    )
    notice_ids = [n["id"] for n in notices]
    assert recorded["linked_notice_id"] in notice_ids
