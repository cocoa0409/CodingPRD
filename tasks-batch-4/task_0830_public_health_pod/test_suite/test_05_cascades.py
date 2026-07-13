"""Multi-hop cascades: Cascade A (dispense -> lot depletion -> POD auto-restrict
-> auto-filed AllocationRequest) and Cascade B (credential revocation -> shift
auto-cancel -> POD auto-restrict)."""
from test_helpers import (
    validate_success,
    validate_paginated,
    create_activated_hazard_plan,
    create_open_pod,
    create_countermeasure,
    create_pod_inventory_lot,
    create_verified_staff_member,
    create_screened_dispensing_event,
    dispense_dispensing_event,
    create_confirmed_shift_assignment,
)


def test_dispense_depletes_lot_and_triggers_pod_auto_restrict(api, admin_headers):
    """PRD §3.6: "A successful dispense records the dispensing staff member's
    id (payload field `dispensed_by_staff_member_id`) into
    `dispensed_by_staff_member_id`, decrements `queue_backlog_count` by one,
    records the selected lot's id into `inventory_lot_id`, and decreases that
    lot's `on_hand_quantity` by `dose_count` — hop 1 of Cascade A. If the
    lot's resulting `available_quantity` drops below the countermeasure's
    `reorder_point_quantity` while the POD is still `OPERATIONAL`, the POD
    auto-transitions to `RESTRICTED` — hop 2."

    Design: Difficulty/transitive_cascade/dispense_cascades_to_pod_restrict_and_auto_allocation_request
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure(doses_required=1, reorder_point_quantity=5)
    lot = create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=6)
    staff = create_verified_staff_member(primary_role="VACCINATOR", credential_type="MD_LICENSE")

    de = create_screened_dispensing_event(pod["id"], cm["id"], staff["id"], dose_count=2)
    dispense_dispensing_event(de["id"], staff["id"])

    lot_after = validate_success(api.get_inventory_lot(lot["id"], admin_headers), 200)
    assert lot_after["on_hand_quantity"] == 4
    assert lot_after["available_quantity"] == 4

    pod_after = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after["operational_status"] == "RESTRICTED", (
        "available_quantity 4 < reorder_point_quantity 5 while POD was OPERATIONAL"
    )


def test_pod_auto_restrict_triggers_auto_created_allocation_request(api, admin_headers):
    """PRD §3.6: "If that auto-transition fires, the system auto-files a fresh
    `AllocationRequest` in the same request: `pod_id` set to this POD,
    `countermeasure_id` unchanged, `source_type` forced to `SNS_CACHE`,
    `requested_quantity` set to the countermeasure's own
    `reorder_point_quantity`, and `status` `REQUESTED` — and increments this
    POD's `open_allocation_request_count` by one — hop 3, closing the loop
    back to §3.5's allocation pipeline."

    Design: Difficulty/transitive_cascade/dispense_cascades_to_pod_restrict_and_auto_allocation_request
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure(doses_required=1, reorder_point_quantity=5)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=6)
    staff = create_verified_staff_member(primary_role="VACCINATOR", credential_type="MD_LICENSE")

    de = create_screened_dispensing_event(pod["id"], cm["id"], staff["id"], dose_count=2)
    dispense_dispensing_event(de["id"], staff["id"])

    data, meta = validate_paginated(
        api.list_allocation_requests(
            admin_headers,
            params={"pod_id": pod["id"], "countermeasure_id": cm["id"], "status": "REQUESTED"},
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["source_type"] == "SNS_CACHE"
    assert data[0]["requested_quantity"] == 5

    pod_after = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after["open_allocation_request_count"] == 1


def test_revoke_credential_auto_cancels_confirmed_shift_assignment(api, admin_headers):
    """PRD §3.3: "Revocation is not an isolated edit: it is the trigger of
    Cascade B described in §2.6. Every `ShiftAssignment` referencing this
    staff member's id via `staff_member_id` that is currently `PENDING` or
    `CONFIRMED` is auto-cancelled as the cascade's first hop."
    PRD §3.3: "...cancelling a `CONFIRMED` assignment restores the POD's
    `committed_staff_hours` by subtracting exactly the amount that confirming
    it had added."

    Design: Difficulty/transitive_cascade/revoke_credential_cascades_to_shift_cancel_and_pod_restrict
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_verified_staff_member(primary_role="VACCINATOR")
    shift = create_confirmed_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )

    api.revoke_staff_credential(staff["id"], admin_headers)

    shift_after = validate_success(api.get_shift_assignment(shift["id"], admin_headers), 200)
    assert shift_after["status"] == "CANCELLED"

    pod_after = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after["committed_staff_hours"] == 0


def test_shift_cancellation_from_revoke_triggers_pod_auto_restrict(api, admin_headers):
    """PRD §3.3: "If any of those auto-cancellations leaves confirmed coverage
    for that assignment's `assigned_role` at its POD below one — and that
    POD's `operational_status` was `OPERATIONAL` — the POD auto-transitions to
    `RESTRICTED` as the cascade's second hop, exactly as described for the
    dispensing-side cascade in §3.6."

    Design: Difficulty/transitive_cascade/revoke_credential_cascades_to_shift_cancel_and_pod_restrict
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_verified_staff_member(primary_role="VACCINATOR")
    create_confirmed_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )

    revoked = api.revoke_staff_credential(staff["id"], admin_headers)
    revoked_data = validate_success(revoked, 200)
    assert revoked_data["credential_status"] == "REVOKED"

    pod_after = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after["operational_status"] == "RESTRICTED", (
        "the sole CONFIRMED VACCINATOR coverage at this POD dropped to 0; POD was OPERATIONAL"
    )
