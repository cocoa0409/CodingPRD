"""Lifecycle transition rules: declared origins, terminal lockdowns and reversible cycles.

Every entity in this service walks a declared state machine.  The tests here pin
the three things those machines promise: the state each row is born in, the exact
origin states each action accepts, and the finality of the terminal states.  The
reversible corners are covered too — route locking and unlocking, pickup
scheduling and its cancellation, and the patient transfer cycle that completes on
one path and unwinds on the other.

Every test builds its own state from scratch against an empty database with the
logical clock at its startup default.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    COMPLIANCE_AUDITOR,
    DELIVERY_DRIVER,
    INTAKE_COORDINATOR,
    PHYSICIAN,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    advance_clock,
    api_client,
    assign_equipment,
    complete_in_home_setup,
    complete_setup_payload,
    create_delivery_route_payload,
    create_equipment_assignment_payload,
    create_qualifying_test_payload,
    create_rental_contract_payload,
    create_route_stop_payload,
    create_transfer_request_payload,
    create_travel_authorization_payload,
    deny_travel_payload,
    dispatch_route,
    drive_cmn_to_active,
    lock_route,
    make_branch,
    make_delivery_route,
    make_route_stop,
    make_stationary_unit,
    open_transfer,
    post_billing_month_payload,
    publish_recall,
    read_cmn,
    read_contract,
    read_equipment_unit,
    read_patient,
    read_recall_notice,
    read_route,
    read_route_stop,
    read_travel_authorization,
    request_travel,
    return_cmn_for_correction,
    setup_contract_in_service,
    setup_dispatched_setup_stop,
    setup_drafted_cmn,
    setup_open_contract,
    setup_reserved_equipment,
    sole_placement,
    submit_cmn,
    unlock_route,
    validate_error,
    validate_success,
)

# ─── Certificate of medical necessity ─────────────────


def test_every_lifecycle_row_is_born_in_its_declared_initial_state():
    """A freshly created certificate, patient, contract, placement, route, stop and recall notice each open in the initial state and with the zeroed roll-ups their machines declare.

    PRD: "A newly opened contract is initialised on both dimensions and across the whole ledger: `billing_status` becomes `ACCRUING`, `service_status` becomes `PENDING_SETUP`, `monthly_allowable_cents` becomes 0, `posted_months` becomes an empty array, `posted_month_count` becomes 0, `lifetime_paid_cents` becomes 0, `malfunction_count` becomes 0 and `cumulative_oxygen_gap_minutes` becomes 0."

    Design: Corner/state_machines/initial_state_of_every_state_machine
    """
    scenario = setup_drafted_cmn()
    patient_id = scenario["patient"]["id"]
    cmn_id = scenario["cmn"]["id"]
    unit_id = scenario["stationary_unit"]["id"]

    # The certificate machine starts at DRAFT; the patient machine starts at ACTIVE.
    assert scenario["cmn"]["status"] == "DRAFT"
    assert scenario["cmn"]["revision_round"] == 0
    assert scenario["cmn"]["version"] == 1
    assert read_patient(patient_id)["status"] == "ACTIVE"
    assert read_equipment_unit(unit_id)["status"] == "IN_STOCK"
    assert read_equipment_unit(unit_id)["quarantine_reason"] == "NONE"

    drive_cmn_to_active(cmn_id)
    contract = validate_success(
        api_client.create_rental_contract(
            create_rental_contract_payload(patient_id, cmn_id), BILLING_SPECIALIST
        ),
        201,
    )
    assert contract["billing_status"] == "ACCRUING"
    assert contract["service_status"] == "PENDING_SETUP"
    assert contract["suspension_reason"] == "NONE"
    assert contract["monthly_allowable_cents"] == 0
    assert contract["posted_months"] == []
    assert contract["posted_month_count"] == 0
    assert contract["lifetime_paid_cents"] == 0
    assert contract["malfunction_count"] == 0
    assert contract["cumulative_oxygen_gap_minutes"] == 0
    assert contract["first_service_month"] is None
    assert contract["last_posted_service_month"] is None
    assert contract["version"] == 1

    # A placement is born RESERVED, with neither timestamp stamped yet.
    placement = assign_equipment(contract["id"], "PRIMARY_STATIONARY")
    assert placement["status"] == "RESERVED"
    assert placement["placed_at"] is None
    assert placement["removed_at"] is None
    assert placement["removal_reason"] == "NONE"
    assert placement["malfunction_count"] == 0
    assert read_equipment_unit(unit_id)["status"] == "RESERVED"

    route = validate_success(
        api_client.create_delivery_route(
            create_delivery_route_payload(scenario["branch"]["id"]), BRANCH_MANAGER
        ),
        201,
    )
    assert route["status"] == "PLANNING"
    assert route["total_o2_liters_committed"] == 0
    assert route["refill_slots_used"] == 0
    assert route["planned_stop_count"] == 0

    stop = validate_success(
        api_client.create_route_stop(
            create_route_stop_payload(route["id"], contract["id"]), BRANCH_MANAGER
        ),
        201,
    )
    assert stop["status"] == "PLANNED"
    assert stop["safety_result"] == "NOT_ASSESSED"
    assert stop["smoking_in_home"] is None
    assert stop["completed_at"] is None
    assert stop["completed_by_user_id"] is None
    assert stop["sequence_index"] == 1
    assert read_route(route["id"])["planned_stop_count"] == 1

    # A recall notice is born OPEN with a frozen affected count and nothing remediated.
    notice = publish_recall(scenario["stationary_unit"]["model_code"], "CLASS_III")
    assert notice["status"] == "OPEN"
    assert notice["affected_unit_count"] == 1
    assert notice["auto_quarantined_unit_count"] == 0
    assert notice["remediated_unit_count"] == 0
    assert read_equipment_unit(unit_id)["status"] == "RESERVED"


def test_certificate_actions_are_refused_outside_their_declared_origin_states():
    """Signature, audit approval, correction return and re-submission are each refused when the certificate does not sit in the origin state that action declares.

    PRD: "This is the generic invalid-transition and terminal-state lockdown guard, and it applies to every action endpoint that drives a lifecycle transition, including repeated triggers of an action already performed."

    Design: Corner/state_machines/cmn_lifecycle_invalid_transitions_rejected
    """
    scenario = setup_drafted_cmn()
    cmn_id = scenario["cmn"]["id"]

    # DRAFT is the origin of submission and of nothing else.
    validate_error(
        api_client.sign_cmn(cmn_id, PHYSICIAN), ApiErrorId.ERR_INVALID_STATE.value
    )
    validate_error(
        api_client.approve_cmn(cmn_id, COMPLIANCE_AUDITOR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.return_cmn_for_correction(
            cmn_id, {"correction_notes": "Nothing to review from draft."}, COMPLIANCE_AUDITOR
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_cmn(cmn_id)["status"] == "DRAFT"

    # SUBMITTED accepts signature or a correction return, never a second submission.
    assert submit_cmn(cmn_id)["status"] == "SUBMITTED"
    validate_error(
        api_client.submit_cmn(cmn_id, INTAKE_COORDINATOR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.approve_cmn(cmn_id, COMPLIANCE_AUDITOR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_cmn(cmn_id)["status"] == "SUBMITTED"

    # RETURNED_FOR_CORRECTION is left by correction or by voiding, not by the audit chain.
    returned = return_cmn_for_correction(cmn_id, "Narrative does not support the hours claimed.")
    assert returned["status"] == "RETURNED_FOR_CORRECTION"
    assert returned["revision_round"] == 1
    before = read_cmn(cmn_id)
    validate_error(
        api_client.submit_cmn(cmn_id, INTAKE_COORDINATOR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.sign_cmn(cmn_id, PHYSICIAN), ApiErrorId.ERR_INVALID_STATE.value
    )
    after = read_cmn(cmn_id)
    assert after["status"] == "RETURNED_FOR_CORRECTION"
    assert after["revision_round"] == 1
    assert after["version"] == before["version"], "a refused transition mutates nothing"


def test_voided_certificate_accepts_no_further_transition_and_opens_no_contract():
    """Voiding a drafted certificate is terminal: submission, a second void and a correction edit are all refused, and no rental contract may be opened against it.

    PRD: "Voiding is the auditor's escape hatch, and it is reachable from exactly three states: `ACTIVE`, `DRAFT` and `RETURNED_FOR_CORRECTION`."

    Design: Corner/state_machines/voided_certificate_is_terminal
    """
    scenario = setup_drafted_cmn()
    cmn_id = scenario["cmn"]["id"]
    patient_id = scenario["patient"]["id"]

    voided = validate_success(
        api_client.void_cmn(
            cmn_id,
            {"void_reason": "Prescription withdrawn by ordering clinician."},
            COMPLIANCE_AUDITOR,
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "Prescription withdrawn by ordering clinician."
    assert read_patient(patient_id)["current_cmn_status"] == "VOIDED"

    validate_error(
        api_client.submit_cmn(cmn_id, INTAKE_COORDINATOR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.void_cmn(
            cmn_id, {"void_reason": "Second attempt at the same void."}, COMPLIANCE_AUDITOR
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.update_cmn(cmn_id, {"narrative_element_count": 1}, INTAKE_COORDINATOR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    after = read_cmn(cmn_id)
    assert after["status"] == "VOIDED"
    assert after["void_reason"] == "Prescription withdrawn by ordering clinician."
    assert after["narrative_element_count"] == 3, "the refused edit left the payload untouched"

    validate_error(
        api_client.create_rental_contract(
            create_rental_contract_payload(patient_id, cmn_id), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_CMN_NOT_ACTIVE.value,
    )


# ─── Delivery routes and their stops ──────────────────


def test_route_locking_is_reversible_until_dispatch_closes_the_editing_window():
    """A planned route refuses to lock while empty, then locks and unlocks repeatedly, and once dispatched it accepts no stop edits and no unlock.

    PRD: "Locking is reversible: the same manager may unlock a route, moving it `LOCKED → PLANNING` and incrementing its `version`, any number of times before dispatch, so a locked route can be reopened for stop edits repeatedly."

    Design: Corner/state_machines/route_lock_unlock_cycle_and_editability_window
    """
    scenario = setup_reserved_equipment()
    contract_id = scenario["contract"]["id"]
    route_id = make_delivery_route(scenario["branch"]["id"])["id"]

    validate_error(
        api_client.lock_route(route_id, BRANCH_MANAGER),
        ApiErrorId.ERR_ROUTE_HAS_NO_STOPS.value,
    )
    assert read_route(route_id)["status"] == "PLANNING"

    stop = make_route_stop(route_id, contract_id, cylinders_requested=2)
    assert stop["liters_committed"] == 1360, "two E-cylinders commit 680 litres each"

    locked = validate_success(api_client.lock_route(route_id, BRANCH_MANAGER))
    assert locked["status"] == "LOCKED"
    assert locked["total_o2_liters_committed"] == 1360

    # The lock reopens and closes again as many times as the manager needs.
    assert unlock_route(route_id)["status"] == "PLANNING"
    assert lock_route(route_id)["status"] == "LOCKED"
    assert unlock_route(route_id)["status"] == "PLANNING"
    assert lock_route(route_id)["status"] == "LOCKED"

    dispatched = validate_success(api_client.dispatch_route(route_id, BRANCH_MANAGER))
    assert dispatched["status"] == "DISPATCHED"

    # Dispatch closes the editing window in both directions.
    validate_error(
        api_client.create_route_stop(
            create_route_stop_payload(
                route_id,
                contract_id,
                window_start_utc="2026-08-01T16:00:00Z",
                window_end_utc="2026-08-01T17:00:00Z",
            ),
            BRANCH_MANAGER,
        ),
        ApiErrorId.ERR_ROUTE_NOT_EDITABLE.value,
    )
    validate_error(
        api_client.cancel_route_stop(stop["id"], BRANCH_MANAGER),
        ApiErrorId.ERR_ROUTE_NOT_EDITABLE.value,
    )
    validate_error(
        api_client.unlock_route(route_id, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    final = read_route(route_id)
    assert final["status"] == "DISPATCHED"
    assert final["planned_stop_count"] == 1
    assert final["total_o2_liters_committed"] == 1360
    assert read_route_stop(stop["id"])["status"] == "PLANNED"


def test_stop_completion_verb_must_match_the_stop_type():
    """The setup-completion verb closes only a setup delivery and the generic completion verb closes only the other stop types; each rejects the other's stop.

    PRD: "The two completion actions are also type-segregated: setup completion applies only to a stop whose type is `SETUP_DELIVERY`, and generic completion applies only to a stop whose type is `TANK_EXCHANGE`, `PORTABLE_REFILL`, `PICKUP` or `MAINTENANCE_SWAP`."

    Design: Corner/state_machines/stop_completion_verb_must_match_stop_type
    """
    scenario = setup_dispatched_setup_stop(stop_overrides={"cylinders_requested": 2})
    contract_id = scenario["contract"]["id"]
    setup_stop_id = scenario["stop"]["id"]

    validate_error(
        api_client.complete_route_stop(setup_stop_id, DELIVERY_DRIVER),
        ApiErrorId.ERR_STOP_TYPE_MISMATCH.value,
    )
    assert read_route_stop(setup_stop_id)["status"] == "PLANNED"

    completed_setup = validate_success(
        api_client.complete_setup(
            setup_stop_id, complete_setup_payload(), RESPIRATORY_THERAPIST
        )
    )
    assert completed_setup["status"] == "COMPLETED"
    assert completed_setup["safety_result"] == "PASS"
    assert read_contract(contract_id)["service_status"] == "IN_SERVICE"

    # A tank exchange is the mirror image: the setup verb is the wrong one for it.
    tank_route_id = make_delivery_route(scenario["branch"]["id"])["id"]
    tank_stop_id = make_route_stop(
        tank_route_id,
        contract_id,
        stop_type="TANK_EXCHANGE",
        window_start_utc="2026-08-01T16:00:00Z",
        window_end_utc="2026-08-01T17:00:00Z",
        cylinders_requested=3,
    )["id"]
    lock_route(tank_route_id)
    dispatch_route(tank_route_id)

    validate_error(
        api_client.complete_setup(
            tank_stop_id, complete_setup_payload(), RESPIRATORY_THERAPIST
        ),
        ApiErrorId.ERR_STOP_TYPE_MISMATCH.value,
    )
    refused = read_route_stop(tank_stop_id)
    assert refused["status"] == "PLANNED"
    assert refused["smoking_in_home"] is None, "the refused setup recorded no assessment"

    driven = validate_success(api_client.complete_route_stop(tank_stop_id, DELIVERY_DRIVER))
    assert driven["status"] == "COMPLETED"
    assert driven["completed_by_user_id"] == "u-drv-1"
    assert driven["completed_at"].startswith("2026-08-01T00:00:00")
    assert read_route(tank_route_id)["status"] == "COMPLETED", "the route bubbles up once every stop is closed"


def test_stop_terminal_actions_require_a_dispatched_route():
    """Setup completion, generic completion and marking a stop missed are all refused while the owning route is only locked, and they leave the stop, the contract and the placement untouched.

    PRD: "All three closing actions — generic completion, setup completion and marking a stop missed — require the owning route to be `DISPATCHED`, failing with `ERR_ROUTE_NOT_DISPATCHED` otherwise, and all three require the stop itself to be in `PLANNED`."

    Design: Corner/state_machines/stop_terminal_actions_require_a_dispatched_route
    """
    scenario = setup_reserved_equipment()
    contract_id = scenario["contract"]["id"]
    route_id = make_delivery_route(scenario["branch"]["id"])["id"]
    stop_id = make_route_stop(route_id, contract_id)["id"]
    lock_route(route_id)

    validate_error(
        api_client.complete_setup(stop_id, complete_setup_payload(), RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_ROUTE_NOT_DISPATCHED.value,
    )
    validate_error(
        api_client.miss_route_stop(stop_id, DELIVERY_DRIVER),
        ApiErrorId.ERR_ROUTE_NOT_DISPATCHED.value,
    )
    # The route-state guard outranks the stop-type guard: a mismatched verb on a
    # route that was never dispatched still reports the route problem first.
    validate_error(
        api_client.complete_route_stop(stop_id, DELIVERY_DRIVER),
        ApiErrorId.ERR_ROUTE_NOT_DISPATCHED.value,
    )

    assert read_route_stop(stop_id)["status"] == "PLANNED"
    assert read_route(route_id)["status"] == "LOCKED"
    assert read_contract(contract_id)["service_status"] == "PENDING_SETUP"
    assert sole_placement(contract_id)["status"] == "RESERVED"

    dispatch_route(route_id)
    completed = validate_success(
        api_client.complete_setup(stop_id, complete_setup_payload(), RESPIRATORY_THERAPIST)
    )
    assert completed["status"] == "COMPLETED"
    assert read_contract(contract_id)["service_status"] == "IN_SERVICE"


def test_missed_stop_keeps_its_committed_litres_and_bubbles_the_route_to_completed():
    """Marking the only stop of a dispatched route missed leaves the route's committed litres untouched, drops the planned count to zero and carries the route to COMPLETED.

    PRD: "That stamps `completed_at` with the logical clock and `completed_by_user_id` with the driver's `X-User-ID`, decrements the route's `planned_stop_count` by 1, and increments the stop's `version` by 1 — but it deliberately **leaves `total_o2_liters_committed` unchanged**, because the oxygen was loaded onto the truck for the day whether or not the driver got through the door."

    Design: Corner/state_machines/missed_stop_keeps_committed_liters_and_bubbles_route_to_completed
    """
    scenario = setup_dispatched_setup_stop(stop_overrides={"cylinders_requested": 2})
    route_id = scenario["route"]["id"]
    stop_id = scenario["stop"]["id"]
    contract_id = scenario["contract"]["id"]

    before = validate_success(api_client.get_route_manifest(route_id, BRANCH_MANAGER))
    assert before["planned_stop_count"] == 1
    assert before["completed_stop_count"] == 0
    assert before["missed_stop_count"] == 0
    assert before["cancelled_stop_count"] == 0
    assert before["refill_slots_used"] == 0
    assert before["total_o2_liters_committed"] == 1360

    missed = validate_success(api_client.miss_route_stop(stop_id, DELIVERY_DRIVER))
    assert missed["status"] == "MISSED"
    assert missed["completed_by_user_id"] == "u-drv-1"
    assert missed["completed_at"].startswith("2026-08-01T00:00:00")

    after = validate_success(api_client.get_route_manifest(route_id, BRANCH_MANAGER))
    assert after["planned_stop_count"] == 0
    assert after["missed_stop_count"] == 1
    assert after["completed_stop_count"] == 0
    assert after["total_o2_liters_committed"] == 1360, "the truck was loaded either way"
    assert after["status"] == "COMPLETED"
    assert read_route(route_id)["status"] == "COMPLETED"

    # A missed setup delivers nothing, so neither dimension of the contract moves.
    assert read_contract(contract_id)["service_status"] == "PENDING_SETUP"
    assert sole_placement(contract_id)["status"] == "RESERVED"


def test_cancelled_stop_drops_out_of_the_route_roll_ups_and_resequences_the_rest():
    """Cancelling the earlier of two planned stops removes exactly its litres from the route roll-up and renumbers the surviving stop to position one, while the cancelled stop keeps its own committed figure.

    PRD: "It decrements the route's `planned_stop_count` by 1, **decreases the route's `total_o2_liters_committed` by exactly this stop's `liters_committed`** so the roll-up returns to its precise pre-creation value, re-derives `refill_slots_used`, and recomputes `sequence_index` for every remaining non-cancelled stop of the route."

    Design: Corner/state_machines/cancelled_stop_excluded_from_route_rollups_and_resequences
    """
    scenario = setup_reserved_equipment()
    contract_id = scenario["contract"]["id"]
    route_id = make_delivery_route(scenario["branch"]["id"])["id"]

    early = make_route_stop(route_id, contract_id, cylinders_requested=2)
    late = make_route_stop(
        route_id,
        contract_id,
        window_start_utc="2026-08-01T15:00:00Z",
        window_end_utc="2026-08-01T16:00:00Z",
        cylinders_requested=3,
    )
    assert early["sequence_index"] == 1
    assert late["sequence_index"] == 2
    assert early["liters_committed"] == 1360
    assert late["liters_committed"] == 2040

    locked = lock_route(route_id)
    assert locked["total_o2_liters_committed"] == 3400
    assert locked["planned_stop_count"] == 2

    cancelled = validate_success(api_client.cancel_route_stop(early["id"], BRANCH_MANAGER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["liters_committed"] == 1360, "the committed figure is never revised"
    assert read_route_stop(late["id"])["sequence_index"] == 1, "the survivor is renumbered"

    manifest = validate_success(api_client.get_route_manifest(route_id, BRANCH_MANAGER))
    assert manifest["planned_stop_count"] == 1
    assert manifest["cancelled_stop_count"] == 1
    assert manifest["total_o2_liters_committed"] == 2040


# ─── Recall notices ───────────────────────────────────


def test_recall_notice_closes_only_once_every_affected_unit_is_remediated():
    """A recall notice cannot jump from OPEN to CLOSED, and once under remediation it closes only after the live remediated count catches the frozen affected count.

    PRD: "Later the same manager closes it, moving it `IN_REMEDIATION → CLOSED` and incrementing its `version` by 1 — but only once the live `remediated_unit_count` is greater than or equal to the frozen `affected_unit_count`."

    Design: Corner/state_machines/recall_close_requires_every_affected_unit_remediated
    """
    branch = make_branch()
    unit = make_stationary_unit(branch["id"])
    notice = publish_recall(unit["model_code"], "CLASS_I")
    notice_id = notice["id"]

    assert notice["status"] == "OPEN"
    assert notice["affected_unit_count"] == 1
    assert notice["auto_quarantined_unit_count"] == 1
    assert notice["remediated_unit_count"] == 0
    assert notice["remediation_deadline_utc"].startswith("2026-08-06T00:00:00")
    quarantined = read_equipment_unit(unit["id"])
    assert quarantined["status"] == "IN_QUARANTINE"
    assert quarantined["quarantine_reason"] == "RECALL"

    validate_error(
        api_client.close_recall_notice(notice_id, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    started = validate_success(api_client.start_recall_remediation(notice_id, BRANCH_MANAGER))
    assert started["status"] == "IN_REMEDIATION"

    validate_error(
        api_client.close_recall_notice(notice_id, BRANCH_MANAGER),
        ApiErrorId.ERR_RECALL_NOT_REMEDIATED.value,
    )
    assert read_recall_notice(notice_id)["status"] == "IN_REMEDIATION"

    serviced = validate_success(
        api_client.service_equipment_unit(unit["id"], RESPIRATORY_THERAPIST)
    )
    assert serviced["status"] == "IN_STOCK"
    assert serviced["quarantine_reason"] == "NONE"
    assert serviced["recall_remediated_at"].startswith("2026-08-01T00:00:00")
    assert serviced["next_pm_due_date"] == "2027-08-01"

    caught_up = read_recall_notice(notice_id)
    assert caught_up["affected_unit_count"] == 1, "the affected count stays frozen"
    assert caught_up["remediated_unit_count"] == 1

    closed = validate_success(api_client.close_recall_notice(notice_id, BRANCH_MANAGER))
    assert closed["status"] == "CLOSED"
    validate_error(
        api_client.start_recall_remediation(notice_id, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_recall_notice(notice_id)["status"] == "CLOSED"


# ─── Rental contract service and billing dimensions ───


def test_cancelling_the_pickup_stop_reverts_the_contract_to_in_service():
    """Scheduling a pickup moves an in-service contract to PICKUP_SCHEDULED, and cancelling that stop undoes the scheduling step completely, leaving the equipment placed and the allowable intact.

    PRD: "When the cancelled stop was a `PICKUP` and no other `PLANNED` pickup stop remains for its contract, the cancellation also reverts the contract's service dimension `PICKUP_SCHEDULED → IN_SERVICE` and increments the contract's `version` by 1 — the pickup scheduling step is fully undone."

    Design: Corner/state_machines/pickup_scheduling_reverts_to_in_service_on_cancel
    """
    scenario = setup_contract_in_service()
    contract_id = scenario["contract"]["id"]
    assert scenario["contract"]["service_status"] == "IN_SERVICE"
    assert scenario["contract"]["monthly_allowable_cents"] == 5590

    pickup_route_id = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )["id"]
    pickup = make_route_stop(
        pickup_route_id,
        contract_id,
        stop_type="PICKUP",
        window_start_utc="2026-08-02T13:00:00Z",
        window_end_utc="2026-08-02T14:00:00Z",
        service_minutes=30,
    )
    assert pickup["liters_committed"] == 0, "the driver is collecting, not delivering"

    scheduled = read_contract(contract_id)
    assert scheduled["service_status"] == "PICKUP_SCHEDULED"
    assert scheduled["billing_status"] == "ACCRUING"
    assert scheduled["monthly_allowable_cents"] == 5590

    cancelled = validate_success(api_client.cancel_route_stop(pickup["id"], BRANCH_MANAGER))
    assert cancelled["status"] == "CANCELLED"

    reverted = read_contract(contract_id)
    assert reverted["service_status"] == "IN_SERVICE"
    assert reverted["billing_status"] == "ACCRUING"
    assert reverted["monthly_allowable_cents"] == 5590
    assert sole_placement(contract_id)["status"] == "PLACED"

    # The scheduling step can be taken again from the state it was rolled back to.
    second = make_route_stop(
        pickup_route_id,
        contract_id,
        stop_type="PICKUP",
        window_start_utc="2026-08-02T13:00:00Z",
        window_end_utc="2026-08-02T14:00:00Z",
        service_minutes=30,
    )
    assert second["cylinders_requested"] == 0
    assert second["liters_committed"] == 0
    assert read_contract(contract_id)["service_status"] == "PICKUP_SCHEDULED"


def test_contract_closes_only_from_a_returned_service_dimension_then_locks_billing_out():
    """A contract still in service refuses closure; once the pickup completes it closes with a zeroed allowable, after which posting, assignment and a second closure are all locked out.

    PRD: "A `BillingSpecialist` may close a contract from `ACCRUING`, from `CAP_REACHED` or from `SUSPENDED`, but only when its service dimension has come to rest in `RETURNED` or `SETUP_FAILED`; a contract still `PENDING_SETUP`, `IN_SERVICE` or `PICKUP_SCHEDULED` is refused with `ERR_CONTRACT_NOT_RETURNED`."

    Design: Corner/state_machines/contract_close_requires_returned_service_and_locks_out_billing
    """
    scenario = setup_contract_in_service()
    contract_id = scenario["contract"]["id"]

    validate_error(
        api_client.close_rental_contract(contract_id, BILLING_SPECIALIST),
        ApiErrorId.ERR_CONTRACT_NOT_RETURNED.value,
    )
    assert read_contract(contract_id)["billing_status"] == "ACCRUING"

    pickup_route_id = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )["id"]
    pickup_id = make_route_stop(
        pickup_route_id,
        contract_id,
        stop_type="PICKUP",
        window_start_utc="2026-08-02T13:00:00Z",
        window_end_utc="2026-08-02T14:00:00Z",
        service_minutes=30,
    )["id"]
    lock_route(pickup_route_id)
    dispatch_route(pickup_route_id)
    assert validate_success(
        api_client.complete_route_stop(pickup_id, DELIVERY_DRIVER)
    )["status"] == "COMPLETED"

    returned = read_contract(contract_id)
    assert returned["service_status"] == "RETURNED"
    assert returned["billing_status"] == "ACCRUING"
    assert returned["monthly_allowable_cents"] == 0
    placement = sole_placement(contract_id)
    assert placement["status"] == "REMOVED"
    assert placement["removal_reason"] == "PICKUP"
    assert read_equipment_unit(scenario["stationary_unit"]["id"])["status"] == "IN_STOCK"

    closed = validate_success(api_client.close_rental_contract(contract_id, BILLING_SPECIALIST))
    assert closed["billing_status"] == "CLOSED"
    assert closed["service_status"] == "RETURNED"
    assert closed["monthly_allowable_cents"] == 0

    validate_error(
        api_client.post_billing_month(
            contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_CONTRACT_CLOSED.value,
    )
    validate_error(
        api_client.create_equipment_assignment(
            contract_id, create_equipment_assignment_payload("BACKUP"), RESPIRATORY_THERAPIST
        ),
        ApiErrorId.ERR_CONTRACT_CLOSED.value,
    )
    validate_error(
        api_client.close_rental_contract(contract_id, BILLING_SPECIALIST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    final = read_contract(contract_id)
    assert final["billing_status"] == "CLOSED"
    assert final["lifetime_paid_cents"] == 0
    assert final["posted_month_count"] == 0


# ─── Patients: transfer and discharge ─────────────────


def test_patient_discharge_is_blocked_by_live_service_and_is_terminal_once_taken():
    """Discharge is refused while a contract still sits in a live service state, and once the setup has failed the discharge goes through and locks the patient out of every further action.

    PRD: "A `BranchManager` discharges an `ACTIVE` patient, moving them to the terminal `DISCHARGED`, but only once no rental contract of that patient still has a live service dimension: any contract in `PENDING_SETUP`, `IN_SERVICE` or `PICKUP_SCHEDULED` blocks the discharge with `ERR_PATIENT_HAS_ACTIVE_SERVICE`, so the equipment must be picked up — or the setup must have failed — before the patient can be discharged."

    Design: Corner/state_machines/patient_discharge_guarded_by_active_service_then_terminal
    """
    scenario = setup_dispatched_setup_stop()
    patient_id = scenario["patient"]["id"]
    contract_id = scenario["contract"]["id"]
    cmn_id = scenario["cmn"]["id"]

    assert read_contract(contract_id)["service_status"] == "PENDING_SETUP"
    validate_error(
        api_client.discharge_patient(patient_id, BRANCH_MANAGER),
        ApiErrorId.ERR_PATIENT_HAS_ACTIVE_SERVICE.value,
    )
    assert read_patient(patient_id)["status"] == "ACTIVE"

    # A failed in-home assessment takes the service dimension out of the live set.
    failed = complete_in_home_setup(scenario["stop"]["id"], smoking_in_home=True)
    assert failed["safety_result"] == "FAIL"
    suspended = read_contract(contract_id)
    assert suspended["service_status"] == "SETUP_FAILED"
    assert suspended["billing_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "SETUP_FAILED"

    discharged = validate_success(api_client.discharge_patient(patient_id, BRANCH_MANAGER))
    assert discharged["status"] == "DISCHARGED"
    assert discharged["current_cmn_status"] == "VOIDED"
    assert read_contract(contract_id)["billing_status"] == "CLOSED"
    voided = read_cmn(cmn_id)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "PATIENT_DISCHARGED"

    validate_error(
        api_client.discharge_patient(patient_id, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    destination = make_branch(name="Orlando", state_code="FL", competitive_bid_area=False)
    validate_error(
        api_client.create_transfer_request(
            patient_id,
            create_transfer_request_payload(destination["id"], "2026-08-15"),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.create_qualifying_test(
            create_qualifying_test_payload(patient_id, tested_at="2026-08-01T00:00:00Z"),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_PATIENT_NOT_ACTIVE.value,
    )
    assert read_patient(patient_id)["status"] == "DISCHARGED"


def test_transfer_cycle_completes_when_due_and_the_cancel_path_leaves_the_branch_alone():
    """A pending transfer refuses to complete before its effective date, completes once the clock reaches it, and a second transfer cancelled instead of completed returns the patient to ACTIVE with the branch untouched.

    PRD: "A `BranchManager` completes the transfer, moving the patient `TRANSFER_PENDING → ACTIVE`, but only once the logical clock's date has reached `transfer_effective_date`; completing early is refused with `ERR_TRANSFER_NOT_DUE`."

    Design: Corner/state_machines/transfer_pending_cycle_completes_then_cancels
    """
    scenario = setup_open_contract()
    patient_id = scenario["patient"]["id"]
    contract_id = scenario["contract"]["id"]
    origin_branch_id = scenario["branch"]["id"]
    destination_branch_id = make_branch(
        name="Orlando", state_code="FL", competitive_bid_area=False
    )["id"]

    validate_error(
        api_client.create_transfer_request(
            patient_id,
            create_transfer_request_payload(origin_branch_id, "2026-08-10"),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_RECEIVING_BRANCH_INVALID.value,
    )
    validate_error(
        api_client.create_transfer_request(
            patient_id,
            create_transfer_request_payload(destination_branch_id, "2026-07-31"),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_TRANSFER_DATE_IN_PAST.value,
    )
    admitted = read_patient(patient_id)
    assert admitted["status"] == "ACTIVE"

    pending = open_transfer(patient_id, destination_branch_id, "2026-08-10")
    assert pending["status"] == "TRANSFER_PENDING"
    assert pending["transfer_to_branch_id"] == destination_branch_id
    assert pending["transfer_effective_date"] == "2026-08-10"
    assert pending["branch_id"] == origin_branch_id, "the origin branch still serves the patient"
    assert pending["version"] == admitted["version"] + 1
    suspended = read_contract(contract_id)
    assert suspended["billing_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "TRANSFER"

    validate_error(
        api_client.complete_transfer_request(patient_id, BRANCH_MANAGER),
        ApiErrorId.ERR_TRANSFER_NOT_DUE.value,
    )
    assert read_patient(patient_id)["status"] == "TRANSFER_PENDING"

    sweep = advance_clock("2026-08-10T09:00:00Z")
    assert sweep["expired_cmn_count"] == 0
    assert sweep["suspended_contract_count"] == 0

    completed = validate_success(
        api_client.complete_transfer_request(patient_id, BRANCH_MANAGER)
    )
    assert completed["status"] == "ACTIVE"
    assert completed["branch_id"] == destination_branch_id
    assert completed["transfer_to_branch_id"] is None
    assert completed["transfer_effective_date"] is None
    resumed = read_contract(contract_id)
    assert resumed["billing_status"] == "ACCRUING"
    assert resumed["suspension_reason"] == "NONE"

    # The cycle is re-enterable; this time it unwinds through cancellation.
    reopened = open_transfer(patient_id, origin_branch_id, "2026-08-12")
    assert reopened["status"] == "TRANSFER_PENDING"
    assert reopened["transfer_to_branch_id"] == origin_branch_id
    assert reopened["branch_id"] == destination_branch_id
    assert reopened["version"] == completed["version"] + 1
    assert read_contract(contract_id)["billing_status"] == "SUSPENDED"

    cancelled = validate_success(
        api_client.cancel_transfer_request(patient_id, INTAKE_COORDINATOR)
    )
    assert cancelled["status"] == "ACTIVE"
    assert cancelled["branch_id"] == destination_branch_id, "cancellation moves no branch"
    assert cancelled["transfer_to_branch_id"] is None
    assert cancelled["transfer_effective_date"] is None
    assert cancelled["version"] == reopened["version"] + 1
    unwound = read_contract(contract_id)
    assert unwound["billing_status"] == "ACCRUING"
    assert unwound["suspension_reason"] == "NONE"


# ─── Travel authorizations and fleet retirement ───────


def test_travel_authorization_decision_is_final():
    """A denied travel authorization is terminal: neither approval nor a second denial is accepted afterwards, and the computed supply figures stay exactly as the request left them.

    PRD: "Both `APPROVED` and `DENIED` are terminal; there is no path between them and no way back to `REQUESTED`."

    Design: Corner/state_machines/travel_authorization_decision_is_final
    """
    scenario = setup_open_contract()
    contract = scenario["contract"]
    destination_branch_id = make_branch(
        name="Asheville", state_code="NC", competitive_bid_area=False
    )["id"]

    validate_error(
        api_client.create_travel_authorization(
            contract["id"],
            create_travel_authorization_payload(
                contract["version"],
                depart_utc="2026-08-06T12:00:00Z",
                return_utc="2026-08-05T12:00:00Z",
                receiving_branch_id=destination_branch_id,
                destination_altitude_feet=500,
            ),
            INTAKE_COORDINATOR,
        ),
        ApiErrorId.ERR_INVALID_TRAVEL_INTERVAL.value,
    )

    authorization = request_travel(
        contract,
        depart_utc="2026-08-05T12:00:00Z",
        return_utc="2026-08-06T12:00:00Z",
        receiving_branch_id=destination_branch_id,
        destination_altitude_feet=500,
    )
    assert authorization["status"] == "REQUESTED"
    assert authorization["decided_by_user_id"] is None
    # A 24-hour trip at no altitude gain: 3.00 lpm over 24 usable hours is 4320
    # litres, a 20 percent reserve adds 864, and 5184 litres needs eight
    # cylinders plus the handling surcharge.
    assert authorization["trip_hours"] == 24
    assert round(float(authorization["altitude_factor"]), 2) == 1.00
    assert round(float(authorization["effective_lpm"]), 2) == 3.00
    assert authorization["base_liters"] == 4320
    assert authorization["reserve_liters"] == 864
    assert authorization["required_liters"] == 5184
    assert authorization["cylinders_raw"] == 8
    assert authorization["handling_surcharge_cylinders"] == 1
    assert authorization["supply_cylinders_authorized"] == 9

    denied = validate_success(
        api_client.deny_travel_authorization(
            authorization["id"], deny_travel_payload(), BRANCH_MANAGER
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["decided_by_user_id"] == "u-mgr-1"
    assert denied["supply_cylinders_authorized"] == 9

    contract_version = read_contract(contract["id"])["version"]
    validate_error(
        api_client.approve_travel_authorization(authorization["id"], BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.deny_travel_authorization(
            authorization["id"], deny_travel_payload(), BRANCH_MANAGER
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    final = read_travel_authorization(authorization["id"])
    assert final["status"] == "DENIED"
    assert final["decided_by_user_id"] == "u-mgr-1"
    assert final["base_liters"] == 4320
    assert final["supply_cylinders_authorized"] == 9
    assert read_contract(contract["id"])["version"] == contract_version


def test_equipment_retirement_is_terminal():
    """A unit in stock cannot be serviced, retires straight to the terminal state, and then refuses both a service and a second retirement without changing anything.

    PRD: "A `BranchManager` may permanently retire a unit from either `IN_STOCK` or `IN_QUARANTINE`, moving it to `RETIRED` and incrementing its `version`; retirement from `RESERVED` or `DEPLOYED` is not a declared transition and is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/equipment_retirement_is_terminal
    """
    branch = make_branch()
    unit = make_stationary_unit(branch["id"])
    unit_id = unit["id"]
    assert unit["status"] == "IN_STOCK"
    assert unit["version"] == 1

    # Service is reachable from quarantine alone, never from stock.
    validate_error(
        api_client.service_equipment_unit(unit_id, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_equipment_unit(unit_id)["status"] == "IN_STOCK"

    retired = validate_success(api_client.retire_equipment_unit(unit_id, BRANCH_MANAGER))
    assert retired["status"] == "RETIRED"
    assert retired["version"] == 2

    validate_error(
        api_client.service_equipment_unit(unit_id, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api_client.retire_equipment_unit(unit_id, BRANCH_MANAGER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    final = read_equipment_unit(unit_id)
    assert final["status"] == "RETIRED"
    assert final["quarantine_reason"] == "NONE"
    assert final["next_pm_due_date"] == "2027-06-01", "the refused service restamped nothing"
    assert final["version"] == 2, "three refused calls mutated nothing"
