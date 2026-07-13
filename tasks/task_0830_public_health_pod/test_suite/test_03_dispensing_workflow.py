"""Registration, screening, deferral/rescreen cycling, dispensing, and the
POD.queue_backlog_count reconciliation that tracks the DispensingEvent
non-terminal states."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_activated_hazard_plan,
    create_open_pod,
    create_countermeasure,
    create_pod_inventory_lot,
    create_verified_staff_member,
    create_unverified_staff_member,
    create_dispensing_event,
    screen_dispensing_event,
    create_screened_dispensing_event,
    defer_dispensing_event,
    create_deferred_dispensing_event,
    rescreen_dispensing_event,
    dispense_dispensing_event,
    create_dispensed_dispensing_event,
)


def test_dispensing_screen_blocked_while_pod_staging(api, admin_headers, clinical_headers):
    """PRD §3.6: "A `ClinicalLead` clinically screens the registrant, moving the
    event from `REGISTERED` to `SCREENED` and recording the screening staff
    member's id in `screened_by_staff_member_id` (supplied in the request
    payload)."
    PRD §3.6: "Dispensing — moving a `SCREENED` event to the terminal
    `DISPENSED` — is the trigger of Cascade A (§2.6). It first requires the
    POD's `operational_status` to be `OPERATIONAL` or `RESTRICTED`
    (`ERR_POD_NOT_OPERATIONAL` otherwise — the same rule that gates
    screening), and requires a POD-scoped `InventoryLot` for this
    countermeasure with `available_quantity` at least `dose_count`
    (`ERR_INSUFFICIENT_INVENTORY`), selected first-expire-first-out per §2.9."

    Design: Difficulty/cross_entity_state_dependency/dispensing_screen_blocked_by_pod_not_operational
    """
    hp = create_activated_hazard_plan()
    pod_res = api.create_pod(
        {
            "hazard_plan_id": hp["id"], "site_name": "Staging POD", "site_type": "FIXED_POD",
            "address": "14 Cross St", "staffing_capacity_lanes": 3, "lane_throughput_rate_per_hour": 15,
        },
        admin_headers,
    )
    pod = validate_success(pod_res, 201)
    assert pod["operational_status"] == "STAGING"
    cm = create_countermeasure()
    staff = create_unverified_staff_member(primary_role="SCREENER")

    de = create_dispensing_event(pod["id"], cm["id"])

    res = api.screen_dispensing_event(
        de["id"], {"screened_by_staff_member_id": staff["id"]}, clinical_headers
    )
    validate_error(res, ApiErrorId.ERR_POD_NOT_OPERATIONAL)


def test_dispensing_screen_succeeds_after_pod_opened(api, admin_headers, clinical_headers):
    """PRD §3.6: "A `ClinicalLead` clinically screens the registrant, moving the
    event from `REGISTERED` to `SCREENED` and recording the screening staff
    member's id in `screened_by_staff_member_id` (supplied in the request
    payload)."
    PRD §3.6: "Dispensing — moving a `SCREENED` event to the terminal
    `DISPENSED` — is the trigger of Cascade A (§2.6). It first requires the
    POD's `operational_status` to be `OPERATIONAL` or `RESTRICTED`
    (`ERR_POD_NOT_OPERATIONAL` otherwise — the same rule that gates
    screening), and requires a POD-scoped `InventoryLot` for this
    countermeasure with `available_quantity` at least `dose_count`
    (`ERR_INSUFFICIENT_INVENTORY`), selected first-expire-first-out per §2.9."

    Design: Difficulty/cross_entity_state_dependency/dispensing_screen_blocked_by_pod_not_operational
    """
    hp = create_activated_hazard_plan()
    pod = validate_success(
        api.create_pod(
            {
                "hazard_plan_id": hp["id"], "site_name": "Staging POD 2", "site_type": "FIXED_POD",
                "address": "15 Cross St", "staffing_capacity_lanes": 3, "lane_throughput_rate_per_hour": 15,
            },
            admin_headers,
        ),
        201,
    )
    cm = create_countermeasure()
    staff = create_unverified_staff_member(primary_role="SCREENER")
    de = create_dispensing_event(pod["id"], cm["id"])
    validate_error(
        api.screen_dispensing_event(de["id"], {"screened_by_staff_member_id": staff["id"]}, clinical_headers),
        ApiErrorId.ERR_POD_NOT_OPERATIONAL,
    )

    api.open_pod(pod["id"], admin_headers)
    res = api.screen_dispensing_event(
        de["id"], {"screened_by_staff_member_id": staff["id"]}, clinical_headers
    )
    screened = validate_success(res, 200)
    assert screened["status"] == "SCREENED"


def test_dispensing_event_defer_then_rescreen_clears_reason(api):
    """PRD §3.6: "From `SCREENED`, the `ClinicalLead` can defer the registrant
    to `DEFERRED`, which requires a non-empty `deferral_reason` in the payload
    (`ERR_VALIDATION` if it is blank) — that reason is stored, and clears
    automatically the moment the registrant is rescreened back to `SCREENED`."

    Design: Difficulty/non_linear_state_machine/dispensing_event_deferred_rescreen_cycle_then_dispense
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    staff = create_verified_staff_member(primary_role="SCREENER")

    de = create_screened_dispensing_event(pod["id"], cm["id"], staff["id"])
    deferred = defer_dispensing_event(de["id"], "Registrant needs physician clearance")
    assert deferred["status"] == "DEFERRED"
    assert deferred["deferral_reason"] == "Registrant needs physician clearance"

    rescreened = rescreen_dispensing_event(deferred["id"])
    assert rescreened["status"] == "SCREENED", "cycle returns to a previously-visited state"
    assert rescreened["deferral_reason"] is None


def test_dispensing_event_dispense_reachable_after_rescreen_cycle(api, admin_headers):
    """PRD §3.6: "From `SCREENED`, the `ClinicalLead` can defer the registrant
    to `DEFERRED`, which requires a non-empty `deferral_reason` in the payload
    (`ERR_VALIDATION` if it is blank) — that reason is stored, and clears
    automatically the moment the registrant is rescreened back to `SCREENED`."
    PRD §3.6: "Dispensing — moving a `SCREENED` event to the terminal
    `DISPENSED` — is the trigger of Cascade A (§2.6)."

    Design: Difficulty/non_linear_state_machine/dispensing_event_deferred_rescreen_cycle_then_dispense
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure(doses_required=1, reorder_point_quantity=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=50)
    staff = create_verified_staff_member(primary_role="SCREENER")

    de = create_deferred_dispensing_event(pod["id"], cm["id"], staff["id"])
    rescreened = rescreen_dispensing_event(de["id"])
    assert rescreened["status"] == "SCREENED"

    dispensed = dispense_dispensing_event(rescreened["id"], staff["id"])
    assert dispensed["status"] == "DISPENSED", "terminal state reached only after the cycle"


def test_dispensing_event_terminal_dispensed_lockdown(api, admin_headers, clinical_headers):
    """PRD §3.6: "Dispensing — moving a `SCREENED` event to the terminal
    `DISPENSED` — is the trigger of Cascade A (§2.6)."

    Design: Corner/state_machines/dispensing_event_terminal_dispensed_lockdown
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure(doses_required=1, reorder_point_quantity=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=50)
    staff = create_verified_staff_member(primary_role="VACCINATOR")

    de = create_dispensed_dispensing_event(pod["id"], cm["id"], staff["id"])

    res = api.refuse_dispensing_event(de["id"], clinical_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_dispensing_event_defer_missing_reason_rejected(api, clinical_headers):
    """PRD §3.6: "From `SCREENED`, the `ClinicalLead` can defer the registrant
    to `DEFERRED`, which requires a non-empty `deferral_reason` in the payload
    (`ERR_VALIDATION` if it is blank) — that reason is stored, and clears
    automatically the moment the registrant is rescreened back to `SCREENED`."

    Design: Corner/validations/dispensing_event_defer_missing_reason_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    staff = create_verified_staff_member(primary_role="SCREENER")

    de = create_screened_dispensing_event(pod["id"], cm["id"], staff["id"])

    res = api.defer_dispensing_event(de["id"], {"deferral_reason": ""}, clinical_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_dispensing_events_filtered_list_by_screened_by_staff_member_id(api, admin_headers):
    """PRD §4 endpoint table: "List dispensing events, filtered by POD,
    countermeasure, lot, staff, or status"

    Design: Corner/endpoints/dispensing_events_filtered_list_by_screened_by_staff_member_id
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    staff_x = create_verified_staff_member(primary_role="SCREENER")
    staff_y = create_verified_staff_member(primary_role="SCREENER")

    de_x = create_screened_dispensing_event(pod["id"], cm["id"], staff_x["id"])
    create_screened_dispensing_event(pod["id"], cm["id"], staff_y["id"])

    data, meta = validate_paginated(
        api.list_dispensing_events(admin_headers, params={"screened_by_staff_member_id": staff_x["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == de_x["id"]


def test_pod_queue_backlog_count_increments_and_decrements(api, admin_headers, clinical_headers):
    """PRD §3.2: "`queue_backlog_count` counts this POD's `DispensingEvent` rows
    currently sitting in `REGISTERED`, `SCREENED`, or `DEFERRED`; it rises by
    one on every new registration and falls by one on every refusal or
    successful dispense."

    Design: Corner/complexity_layers/pod_queue_backlog_count_increments_and_decrements
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure()
    staff = create_verified_staff_member(primary_role="SCREENER")

    de1 = create_dispensing_event(pod["id"], cm["id"])
    create_dispensing_event(pod["id"], cm["id"])

    pod_after_creates = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after_creates["queue_backlog_count"] == 2

    screen_dispensing_event(de1["id"], staff["id"])
    api.refuse_dispensing_event(de1["id"], clinical_headers)

    pod_after_refuse = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after_refuse["queue_backlog_count"] == 1
