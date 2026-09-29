"""State-machine corners: declared initial states, forked and guarded transitions,
declared side effects, terminal-state lockdown, non-idempotent actions, parent
phase bubbling and the two cross-entity cascades.
"""

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    add_bin,
    add_circuit,
    add_finding,
    add_unit,
    add_window,
    api_client,
    assert_array_circuit,
    assert_deck_finding,
    assert_hardware_unit,
    assert_party_approval,
    assert_permit_application,
    assert_work_window,
    book_inspection,
    create_core_parties,
    create_jurisdiction,
    create_permit,
    create_project,
    decide_permit,
    deenergize_circuit,
    drive_finding,
    grade_unit,
    make_roofing_contractor_headers,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    open_consent,
    record_result,
    reenergize_circuit,
    refresh_project,
    reinstall_unit,
    remove_unit,
    set_clock,
    settle_credit,
    setup_authorized_project,
    store_unit,
    submit_permit,
    validate_error,
    validate_success,
)

EPOCH_RENDERED = "2026-08-01T00:00:00.000Z"

HOST_OWNED_OVERRIDES = {
    "site_address": "77 Ocotillo Ln, Chandler AZ",
    "system_dc_kw": 6.0,
    "baseline_daily_kwh": 30.0,
    "downtime_days_estimated": 4,
    "upgrade_budget_cents": 2_000_000,
}


# --------------------------------------------------------------------------
# Private setup helpers
# --------------------------------------------------------------------------
def _authorized_host_owned() -> dict:
    """Three parties plus a HOST_OWNED project carried to AUTHORIZED by both consents."""
    set_clock(CLOCK_EPOCH)
    return setup_authorized_project(ownership_model="HOST_OWNED", **HOST_OWNED_OVERRIDES)


def _intake_host_owned() -> dict:
    """Three parties plus a HOST_OWNED project with no consent record at all."""
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    project = create_project(
        parties, ownership_model="HOST_OWNED", **HOST_OWNED_OVERRIDES
    )
    return {"parties": parties, "project": project}


def _read_unit(unit_id: str) -> dict:
    return validate_success(api_client.get_hardware_unit(unit_id, COORD), 200)


def _read_circuit(circuit_id: str) -> dict:
    return validate_success(api_client.get_array_circuit(circuit_id, COORD), 200)


def _read_bin(bin_id: str) -> dict:
    return validate_success(api_client.get_storage_bin(bin_id, COORD), 200)


def _read_window(window_id: str) -> dict:
    return validate_success(api_client.get_work_window(window_id, COORD), 200)


def _read_finding(finding_id: str) -> dict:
    return validate_success(api_client.get_deck_finding(finding_id, COORD), 200)


def _read_permit(permit_id: str) -> dict:
    return validate_success(api_client.get_permit_application(permit_id, COORD), 200)


def _read_inspection(inspection_id: str) -> dict:
    return validate_success(api_client.get_inspection(inspection_id, COORD), 200)


def _read_approval(approval_id: str) -> dict:
    return validate_success(api_client.get_party_approval(approval_id, COORD), 200)


# --------------------------------------------------------------------------
# Initial states
# --------------------------------------------------------------------------
def test_initial_states_of_every_created_entity_are_the_declared_ones():
    """Every machine opens in its declared state on a freshly created row.

    PRD §3.2: "On creation the project's `phase` is `INTAKE` and its `posture` is
    `OPEN`."
    PRD §3.4: "A new circuit starts with `status` `ENERGIZED`, `interlock_verified`
    false, and `isolated_at` and `reenergized_at` both absent."
    PRD §3.5: "A newly registered unit is `ON_ROOF` and `UNINSPECTED`."
    PRD §3.5: "A unit's `storage_bin_id`, `storage_label`, `warranty_variant`,
    `warranty_preserved`, `off_roof_days`, `removed_at`, `stored_at` and
    `reinstalled_at` are all absent at registration, and `warranty_risk_points` is
    zero."
    PRD §3.7: "A new application is `DRAFT` with `revision_count` zero, `fee_cents`
    zero, and `submitted_at`, `decided_at`, `review_deadline_utc`,
    `rejection_reason` and `reopened_by_finding_id` all absent."
    PRD §3.3: "A new window is created in `SCHEDULED` with `supersedes_window_id`
    absent and both `actual_start_utc` and `actual_end_utc` absent."
    PRD §3.2: "The new record's `approval_role` is copied from the referenced
    party's `party_type`, its `status` is `PENDING`, its `round_recorded` is set to
    the project's current `negotiation_round`, its `change_request_count` is zero,
    its `veto_flag` is false, and `decided_at` is absent."
    PRD §3.2: "Creating the **first** consent record on a project also advances the
    project from `INTAKE` to `APPROVALS_OPEN` and triggers a posture recomputation;
    the project must be in `INTAKE` for that advance to apply."

    Design: Corner/state_machines/corner_initial_states_of_every_created_entity_are_the_declared_ones
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    roofer_id = parties["roofer"]["id"]
    crew_id = parties["crew"]["id"]
    jurisdiction = create_jurisdiction(
        name="Flatrock AHJ",
        code="FLATROCK",
        repermit_required_for_reinstall=False,
        reinspection_required=False,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=7,
    )
    p1 = create_project(parties, ownership_model="HOST_OWNED", **HOST_OWNED_OVERRIDES)
    p2 = create_project(
        parties,
        ownership_model="HOST_OWNED",
        site_address="912 Saguaro Rd, Mesa AZ",
        system_dc_kw=5.2,
        baseline_daily_kwh=26.0,
        downtime_days_estimated=3,
        upgrade_budget_cents=1_500_000,
    )

    circuit = add_circuit(p1["id"], circuit_label="A1", module_count=1, dc_kw=0.41)
    unit = add_unit(p1["id"], circuit["id"], crew_id, serial_number="SN-0001")
    permit = create_permit(p1["id"], jurisdiction["id"], scope="REINSTALL_ONLY")
    window = add_window(
        p1["id"],
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-10T14:00:00Z",
        end_utc="2026-08-10T22:00:00Z",
    )
    approval = open_consent(p2["id"], roofer_id)

    assert_array_circuit(circuit)
    assert_hardware_unit(unit)
    assert_permit_application(permit)
    assert_work_window(window)
    assert_party_approval(approval)

    p1_read = refresh_project(p1["id"])
    assert p1_read["phase"] == "INTAKE", (
        f"a project with no consent record stays INTAKE, got {p1_read['phase']}"
    )
    assert p1_read["posture"] == "OPEN", p1_read["posture"]

    assert circuit["status"] == "ENERGIZED", circuit["status"]
    assert circuit["interlock_verified"] is False, circuit["interlock_verified"]
    assert circuit.get("isolated_at") is None, circuit.get("isolated_at")

    assert unit["handling_status"] == "ON_ROOF", unit["handling_status"]
    assert unit["condition_grade"] == "UNINSPECTED", unit["condition_grade"]
    assert unit.get("warranty_variant") is None, (
        f"the warranty variant is pinned at removal, not registration, got "
        f"{unit.get('warranty_variant')!r}"
    )
    assert unit.get("storage_bin_id") is None, unit.get("storage_bin_id")
    assert unit.get("warranty_preserved") is None, unit.get("warranty_preserved")

    assert permit["status"] == "DRAFT", permit["status"]
    assert permit["revision_count"] == 0, permit["revision_count"]
    assert permit["fee_cents"] == 0, permit["fee_cents"]
    assert permit.get("review_deadline_utc") is None, permit.get("review_deadline_utc")

    assert window["status"] == "SCHEDULED", window["status"]
    assert window["weather_risk_score"] == 0, (
        f"weather_risk_score defaults to 0, got {window['weather_risk_score']}"
    )

    assert approval["status"] == "PENDING", approval["status"]
    assert approval["round_recorded"] == 1, approval["round_recorded"]
    assert approval["change_request_count"] == 0, approval["change_request_count"]
    assert approval["veto_flag"] is False, approval["veto_flag"]
    assert approval["approval_role"] == "ROOFER", approval["approval_role"]

    p2_read = refresh_project(p2["id"])
    assert p2_read["phase"] == "APPROVALS_OPEN", (
        f"the first consent record advances INTAKE to APPROVALS_OPEN, got "
        f"{p2_read['phase']}"
    )


# --------------------------------------------------------------------------
# Valid transitions
# --------------------------------------------------------------------------
def test_unverified_interlock_parks_the_circuit_in_isolation_pending_then_reaches_isolated():
    """The same action forks on interlock_verified, and only ISOLATED de-energizes the project.

    PRD §3.4: "From the same `ENERGIZED` state under the same phase precondition but
    with `interlock_verified` submitted as false, the circuit instead moves
    `ENERGIZED → ISOLATION_PENDING` and records `interlock_verified` as false — a
    de-energize was recorded, but without a verified lockout/tagout interlock."
    PRD §3.4: "That branch produces no project-level consequence at all, precisely
    because the circuit is not yet `ISOLATED`."
    PRD §3.4: "A circuit sitting in `ISOLATION_PENDING` is finished off by a second
    de-energize carrying `interlock_verified` true, which moves `ISOLATION_PENDING →
    ISOLATED`, records the verified interlock, and stamps `isolated_at`."
    PRD §3.9: "An ownership factor then scales the result according to who was
    actually deprived of the energy: 0.00 for `HOST_OWNED` (the host owns the array,
    so no credit is owed at all), 1.00 for `LEASE`, and 0.85 for `PPA`."

    Design: Corner/state_machines/corner_unverified_interlock_parks_the_circuit_in_isolation_pending_then_reaches_isolated
    """
    ctx = _authorized_host_owned()
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    assert ctx["project"]["phase"] == "AUTHORIZED", ctx["project"]["phase"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)

    pending = deenergize_circuit(
        circuit["id"], crew_id, False, isolation_note="lockout tag not yet witnessed"
    )
    assert pending["status"] == "ISOLATION_PENDING", (
        f"an unverified interlock parks the circuit in ISOLATION_PENDING, got "
        f"{pending['status']}"
    )
    assert pending["interlock_verified"] is False, pending["interlock_verified"]
    assert pending.get("isolated_at") is None, pending.get("isolated_at")

    mid = refresh_project(project_id)
    assert mid["phase"] == "AUTHORIZED", (
        f"ISOLATION_PENDING must not de-energize the project, got {mid['phase']}"
    )
    assert mid["provisional_credit_cents"] == 0, mid["provisional_credit_cents"]
    assert mid.get("deenergized_at") is None, mid.get("deenergized_at")

    isolated = deenergize_circuit(
        circuit["id"], crew_id, True, isolation_note="lockout witnessed by crew lead"
    )
    assert isolated["status"] == "ISOLATED", isolated["status"]
    assert isolated["interlock_verified"] is True, isolated["interlock_verified"]
    assert isolated["isolated_at"] == EPOCH_RENDERED, isolated["isolated_at"]

    final = refresh_project(project_id)
    assert final["phase"] == "DEENERGIZED", final["phase"]
    assert final["deenergized_at"] == EPOCH_RENDERED, final["deenergized_at"]
    assert final["provisional_credit_cents"] == 0, (
        f"a HOST_OWNED project has an ownership factor of 0.00, got "
        f"{final['provisional_credit_cents']}"
    )
    assert final["credit_authorized_cents"] == 0, final["credit_authorized_cents"]
    assert final["credit_reserved_cents"] == 0, final["credit_reserved_cents"]


# --------------------------------------------------------------------------
# Preconditions
# --------------------------------------------------------------------------
def test_deenergize_precondition_requires_authorized_phase_and_reenergize_requires_isolated():
    """Both energization preconditions bite, and neither refusal mutates the circuit.

    PRD §3.4: "From `ENERGIZED`, when the project's `phase` is `AUTHORIZED` and
    `interlock_verified` is submitted as true, the circuit moves `ENERGIZED →
    ISOLATED`, its `interlock_verified` is recorded as true, and `isolated_at` is
    stamped with the current instant."
    PRD §3.9: "Re-energization closes the physical cycle, moving a circuit `ISOLATED
    → ENERGIZED` and stamping the circuit's `reenergized_at`."
    PRD §2.11: "8. State legality of the requested transition, including the
    negotiation-round freshness check on a consent decision and the requirement that
    a permit application be `SUBMITTED` or `APPROVED` before an inspection can be
    booked under it — `ERR_INVALID_STATE`, `ERR_APPROVAL_ROUND_STALE`,
    `ERR_PERMIT_NOT_SUBMITTED` or `ERR_SETTLEMENT_NOT_READY`."

    Design: Corner/state_machines/corner_deenergize_precondition_requires_authorized_phase_and_reenergize_requires_isolated
    """
    ctx = _intake_host_owned()
    project_id = ctx["project"]["id"]
    crew_headers = make_solar_contractor_headers(ctx["parties"]["crew"]["id"])
    circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)

    too_early = api_client.set_circuit_energization(
        circuit["id"], {"action": "DE_ENERGIZE", "interlock_verified": True}, crew_headers
    )
    validate_error(too_early, "ERR_INVALID_STATE", 409)

    wrong_status = api_client.set_circuit_energization(
        circuit["id"], {"action": "RE_ENERGIZE", "interlock_verified": True}, crew_headers
    )
    validate_error(wrong_status, "ERR_INVALID_STATE", 409)

    after = _read_circuit(circuit["id"])
    assert after["status"] == "ENERGIZED", (
        f"a refused energization must not mutate the circuit, got {after['status']}"
    )
    assert after["interlock_verified"] is False, after["interlock_verified"]
    assert after.get("isolated_at") is None, after.get("isolated_at")

    project = refresh_project(project_id)
    assert project["phase"] == "INTAKE", project["phase"]
    assert project.get("deenergized_at") is None, project.get("deenergized_at")


# --------------------------------------------------------------------------
# Side effects
# --------------------------------------------------------------------------
def test_weather_abort_side_effects_stamp_the_window_and_bump_the_project_counter():
    """The first weather abort writes every declared side effect and leaves posture OPEN.

    PRD §3.3: "It sets `status` to `WEATHER_ABORTED`, stamps `actual_end_utc`,
    records the reason, and increments the project's `weather_abort_count` by one."
    PRD §3.3: "Because that counter feeds the posture rule of §2.6, the second abort
    on a project is the one that bites: two aborts already drive the project to
    `RESTRICTED`, and posture is recomputed at the end of the abort."

    Design: Corner/state_machines/corner_weather_abort_side_effects_stamp_the_window_and_bump_the_project_counter
    """
    ctx = _intake_host_owned()
    project_id = ctx["project"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]

    window = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-10T14:00:00Z",
        end_utc="2026-08-10T22:00:00Z",
        weather_risk_score=65,
    )
    set_clock("2026-08-10T13:00:00Z")

    aborted = validate_success(
        api_client.set_work_window_status(
            window["id"],
            {"action": "WEATHER_ABORT", "abort_reason": "monsoon cell over the site"},
            make_roofing_contractor_headers(roofer_id),
        ),
        200,
    )
    assert aborted["status"] == "WEATHER_ABORTED", aborted["status"]
    assert aborted["actual_end_utc"] == "2026-08-10T13:00:00.000Z", (
        f"actual_end_utc is stamped from the logical clock, got "
        f"{aborted['actual_end_utc']}"
    )
    assert aborted.get("actual_start_utc") is None, (
        f"a window aborted from SCHEDULED never started, got "
        f"{aborted.get('actual_start_utc')!r}"
    )
    assert aborted["abort_reason"] == "monsoon cell over the site", aborted["abort_reason"]

    project = refresh_project(project_id)
    assert project["weather_abort_count"] == 1, project["weather_abort_count"]
    assert project["posture"] == "OPEN", (
        f"one abort is below the two-abort threshold, so posture stays OPEN, got "
        f"{project['posture']}"
    )


# --------------------------------------------------------------------------
# Invalid transitions
# --------------------------------------------------------------------------
def test_completing_a_scheduled_window_and_starting_one_early_are_invalid_transitions():
    """COMPLETE is not reachable from SCHEDULED, and START is guarded by the clock.

    PRD §3.3: "`COMPLETE` moves an `IN_PROGRESS` window to `COMPLETED`, stamps
    `actual_end_utc`, and releases the crew interval for overlap purposes."
    PRD §3.3: "`START` moves a `SCHEDULED` window to `IN_PROGRESS` and stamps
    `actual_start_utc` with the current instant; it requires the project not to be
    frozen and requires the current instant to be at or after the window's
    `start_utc`."

    Design: Corner/state_machines/corner_completing_a_scheduled_window_and_starting_one_early_are_invalid_transitions
    """
    ctx = _intake_host_owned()
    project_id = ctx["project"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]

    window = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-10T14:00:00Z",
        end_utc="2026-08-10T22:00:00Z",
    )

    complete = api_client.set_work_window_status(
        window["id"], {"action": "COMPLETE"}, COORD
    )
    validate_error(complete, "ERR_INVALID_STATE", 409)

    early_start = api_client.set_work_window_status(
        window["id"], {"action": "START"}, COORD
    )
    validate_error(early_start, "ERR_INVALID_STATE", 409)

    after = _read_window(window["id"])
    assert after["status"] == "SCHEDULED", after["status"]
    assert after.get("actual_start_utc") is None, after.get("actual_start_utc")
    assert after.get("actual_end_utc") is None, after.get("actual_end_utc")

    project = refresh_project(project_id)
    assert project["weather_abort_count"] == 0, project["weather_abort_count"]


# --------------------------------------------------------------------------
# Terminal states
# --------------------------------------------------------------------------
def test_closed_project_waived_finding_and_scrapped_unit_admit_no_further_transitions():
    """Three terminal states each refuse a further action without moving the ledger.

    PRD §3.9: "The project's `phase` must be `COMMISSIONED`; a settlement requested
    on any other phase is refused with `ERR_SETTLEMENT_NOT_READY` (HTTP 409)."
    PRD §3.9: "`CLOSED` is terminal for a project."
    PRD §3.6: "**Completing** takes a finding from `UPGRADE_SCOPED` to
    `UPGRADE_COMPLETED`, stamps `completed_at`, and records the acting `X-User-ID`
    as `completed_by_party_id`."
    PRD §3.6: "`WAIVED` is terminal for a finding."
    PRD §3.5: "The unit must be `REMOVED` and the project must not be frozen."
    PRD §3.5: "`SCRAPPED` is terminal on the handling dimension."

    Design: Corner/state_machines/corner_closed_project_waived_finding_and_scrapped_unit_admit_no_further_transitions
    """
    ctx = _authorized_host_owned()
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=2, dc_kw=0.82)
    u1 = add_unit(project_id, circuit["id"], crew_id, serial_number="SN-0001")
    u2 = add_unit(project_id, circuit["id"], crew_id, serial_number="SN-0002")
    storage_bin = add_bin(project_id, bin_label="BIN-1", capacity_slots=2)

    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(u1["id"], crew_id)
    remove_unit(u2["id"], crew_id)
    grade_unit(u1["id"], crew_id, "SERVICEABLE", "RETAIN")
    grade_unit(
        u2["id"], crew_id, "DAMAGED", "SCRAP", damage_note="cracked glass on removal"
    )
    store_unit(u1["id"], storage_bin["id"], crew_id)

    finding = add_finding(
        project_id,
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=10.0,
        attachment_count_affected=0,
    )
    drive_finding(
        finding["id"],
        roofer_id,
        "WAIVE",
        waiver_reason="deck sound, fasteners re-seated under the roofing scope",
    )
    reinstall_unit(u1["id"], crew_id)
    reenergize_circuit(circuit["id"], crew_id)
    settle_credit(project_id, settlement_note="host owned, no credit owed")

    second_settlement = api_client.settle_credit(
        project_id, {"settlement_note": "second attempt"}, COORD
    )
    validate_error(second_settlement, "ERR_SETTLEMENT_NOT_READY", 409)

    complete_waived = api_client.upgrade_deck_finding(
        finding["id"], {"action": "COMPLETE"}, make_roofing_contractor_headers(roofer_id)
    )
    validate_error(complete_waived, "ERR_INVALID_STATE", 409)

    store_scrapped = api_client.store_hardware_unit(
        u2["id"],
        {"storage_bin_id": storage_bin["id"]},
        make_solar_contractor_headers(crew_id),
    )
    validate_error(store_scrapped, "ERR_INVALID_STATE", 409)

    project = refresh_project(project_id)
    assert project["phase"] == "CLOSED", project["phase"]
    assert project["downtime_days_actual"] == 1, (
        f"de-energized and re-energized on the same UTC date is one distinct date, got "
        f"{project['downtime_days_actual']}"
    )
    assert project["final_credit_cents"] == 0, project["final_credit_cents"]
    assert project["credit_settled_cents"] == 0, project["credit_settled_cents"]
    assert project["reinstalled_unit_count"] == 1, project["reinstalled_unit_count"]
    assert project["scrapped_unit_count"] == 1, project["scrapped_unit_count"]
    assert project["registered_unit_count"] == 2, project["registered_unit_count"]

    finding_read = _read_finding(finding["id"])
    assert_deck_finding(finding_read)
    assert finding_read["status"] == "WAIVED", finding_read["status"]
    assert finding_read["upgrade_cost_cents"] == 0, finding_read["upgrade_cost_cents"]
    assert finding_read.get("completed_by_party_id") is None, (
        f"a refused COMPLETE must not record a signer, got "
        f"{finding_read.get('completed_by_party_id')!r}"
    )

    u2_read = _read_unit(u2["id"])
    assert u2_read["handling_status"] == "SCRAPPED", u2_read["handling_status"]
    assert u2_read.get("storage_bin_id") is None, (
        f"a refused storage must not write the bin reference, got "
        f"{u2_read.get('storage_bin_id')!r}"
    )

    bin_read = _read_bin(storage_bin["id"])
    assert bin_read["occupied_slots"] == 0, bin_read["occupied_slots"]


# --------------------------------------------------------------------------
# Non-idempotent actions
# --------------------------------------------------------------------------
def test_repeating_removal_or_approval_a_second_time_yields_invalid_state():
    """Neither removal nor consent approval is idempotent, and neither re-stamps.

    PRD §3.5: "It requires the unit to be `ON_ROOF`, its circuit's `status` to be
    `ISOLATED` — otherwise `ERR_CIRCUIT_NOT_ISOLATED` (HTTP 409) — and the project
    not to be frozen."
    PRD §3.5: "Removal also **pins the warranty rule set** that will judge this unit
    later: `warranty_variant` becomes `MANUFACTURER_STRICT` when the project's
    `warranty_notice_status` is `FILED` at that instant, and `INSTALLER_LENIENT`
    otherwise."
    PRD §3.2: "An `APPROVE` decision is accepted from either `PENDING` or
    `CHANGES_REQUESTED`."

    Design: Corner/state_machines/corner_repeating_removal_or_approval_a_second_time_yields_invalid_state
    """
    ctx = _authorized_host_owned()
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    owner_id = ctx["parties"]["owner"]["id"]
    owner_approval_id = ctx["approvals"]["owner"]["id"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)
    unit = add_unit(project_id, circuit["id"], crew_id, serial_number="SN-0001")
    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(unit["id"], crew_id)

    set_clock("2026-08-02T00:00:00Z")

    second_removal = api_client.remove_hardware_unit(
        unit["id"], make_solar_contractor_headers(crew_id)
    )
    validate_error(second_removal, "ERR_INVALID_STATE", 409)

    second_approve = api_client.decide_party_approval(
        owner_approval_id, {"decision": "APPROVE"}, make_solar_owner_headers(owner_id)
    )
    validate_error(second_approve, "ERR_INVALID_STATE", 409)

    unit_read = _read_unit(unit["id"])
    assert unit_read["handling_status"] == "REMOVED", unit_read["handling_status"]
    assert unit_read["removed_at"] == EPOCH_RENDERED, (
        f"a refused second removal must not re-stamp removed_at, got "
        f"{unit_read['removed_at']}"
    )
    assert unit_read["warranty_variant"] == "INSTALLER_LENIENT", (
        f"no notice was on file at removal, so the lenient variant is pinned, got "
        f"{unit_read['warranty_variant']}"
    )

    approval_read = _read_approval(owner_approval_id)
    assert approval_read["status"] == "APPROVED", approval_read["status"]
    assert approval_read["decided_at"] == EPOCH_RENDERED, (
        f"a refused second approval must not re-stamp decided_at, got "
        f"{approval_read['decided_at']}"
    )

    project = refresh_project(project_id)
    assert project["negotiation_round"] == 1, project["negotiation_round"]
    assert project["phase"] == "DEENERGIZED", project["phase"]


# --------------------------------------------------------------------------
# Parent phase bubbling
# --------------------------------------------------------------------------
def test_project_bubbles_to_deck_work_only_once_the_last_unit_leaves_the_roof_set():
    """The DECK_WORK advance reads the whole unit population, not the last write.

    PRD §3.5: "That advance requires the project's `phase` to be `DEENERGIZED`,
    `registered_unit_count` to be at least 1, and the count of the project's units
    whose `handling_status` is neither `STORED` nor `SCRAPPED` to be zero — in other
    words, every registered unit is either safely in a bin or written off."
    PRD §3.5: "On success the unit's `storage_bin_id` is written, `storage_position`
    is either the supplied value or the bin's `occupied_slots` plus one at that
    moment, and `storage_label` is composed as the bin's `bin_label` followed by a
    hyphen and the `storage_position`."

    Design: Corner/state_machines/corner_project_bubbles_to_deck_work_only_once_the_last_unit_leaves_the_roof_set
    """
    ctx = _authorized_host_owned()
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=2, dc_kw=0.82)
    u1 = add_unit(project_id, circuit["id"], crew_id, serial_number="SN-0001")
    u2 = add_unit(project_id, circuit["id"], crew_id, serial_number="SN-0002")
    storage_bin = add_bin(project_id, bin_label="BIN-1", capacity_slots=2)

    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(u1["id"], crew_id)
    remove_unit(u2["id"], crew_id)

    first_stored = store_unit(u1["id"], storage_bin["id"], crew_id)
    mid = refresh_project(project_id)
    assert mid["phase"] == "DEENERGIZED", (
        f"one unit is still REMOVED, so the project stays DEENERGIZED, got "
        f"{mid['phase']}"
    )
    assert mid["stored_unit_count"] == 1, mid["stored_unit_count"]

    second_stored = store_unit(u2["id"], storage_bin["id"], crew_id)
    final = refresh_project(project_id)
    assert final["phase"] == "DECK_WORK", (
        f"storing the last unit bubbles the project to DECK_WORK, got {final['phase']}"
    )
    assert final["stored_unit_count"] == 2, final["stored_unit_count"]

    assert first_stored["storage_label"] == "BIN-1-1", first_stored["storage_label"]
    assert second_stored["storage_label"] == "BIN-1-2", second_stored["storage_label"]

    bin_read = _read_bin(storage_bin["id"])
    assert bin_read["occupied_slots"] == 2, bin_read["occupied_slots"]


# --------------------------------------------------------------------------
# Cross-entity cascades
# --------------------------------------------------------------------------
def test_permit_rejection_freezes_the_project_and_revokes_only_future_scheduled_windows():
    """One AHJ rejection freezes the project and revokes only the window still ahead.

    PRD §3.7: "`REJECT` sets `status` to `REJECTED`, stamps `decided_at`, records the
    `rejection_reason`, and drives the project's `posture` to `FROZEN`; because the
    project froze, every crew window of the project still in `SCHEDULED` whose
    `start_utc` is at or after the current instant is set to `REVOKED`."
    PRD §3.7: "Either way `status` becomes `SUBMITTED`, `submitted_at` is stamped
    with the current instant, and `review_deadline_utc` is set to that `submitted_at`
    plus the jurisdiction's `permit_review_days` whole days."
    PRD §3.7: "The scope base is 18,000 cents for `REINSTALL_ONLY`, 46,000 cents for
    `STRUCTURAL_UPGRADE` and 72,000 cents for `FULL_REPERMIT`."
    PRD §3.7: "To that is added the project's `system_dc_kw` multiplied by 850 cents
    per kilowatt, rounded half up to whole cents — this per-kilowatt term is the only
    term that is rounded."

    Design: Corner/state_machines/corner_permit_rejection_freezes_the_project_and_revokes_only_future_scheduled_windows
    """
    ctx = _intake_host_owned()
    project_id = ctx["project"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]
    jurisdiction = create_jurisdiction(
        name="Flatrock AHJ",
        code="FLATROCK",
        repermit_required_for_reinstall=False,
        reinspection_required=False,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=7,
    )

    w_past = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-07-25T14:00:00Z",
        end_utc="2026-07-25T22:00:00Z",
    )
    w_future = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-10T14:00:00Z",
        end_utc="2026-08-10T22:00:00Z",
    )

    permit = create_permit(project_id, jurisdiction["id"], scope="REINSTALL_ONLY")
    submit_permit(permit["id"])

    rejected = decide_permit(
        permit["id"],
        jurisdiction["id"],
        "REJECT",
        rejection_reason="attachment detail does not match the mounting listing",
    )
    assert rejected["status"] == "REJECTED", rejected["status"]
    assert (
        rejected["rejection_reason"]
        == "attachment detail does not match the mounting listing"
    ), rejected["rejection_reason"]
    assert rejected["fee_cents"] == 23_100, (
        f"18000 base plus 6.0 kW at 850 cents is 23100, got {rejected['fee_cents']}"
    )
    assert rejected["revision_count"] == 0, (
        f"a rejection does not count as a revision, got {rejected['revision_count']}"
    )
    assert rejected["review_deadline_utc"] == "2026-08-08T00:00:00.000Z", (
        f"submitted_at plus 7 whole days, got {rejected['review_deadline_utc']}"
    )

    project = refresh_project(project_id)
    assert project["posture"] == "FROZEN", project["posture"]

    assert _read_window(w_future["id"])["status"] == "REVOKED", (
        "a SCHEDULED window starting at or after the current instant is revoked"
    )
    assert _read_window(w_past["id"])["status"] == "SCHEDULED", (
        "a window that already started is left alone by the rejection cascade"
    )


def test_reinstall_frees_the_bin_slot_while_retaining_storage_provenance():
    """Reinstall drops the derived occupancy to zero yet keeps the storage provenance.

    PRD §3.9: "Reinstall also recomputes the `occupied_slots` of the unit's storage
    bin, since the slot is freed, while `storage_bin_id` and `storage_label` are
    deliberately **retained** as provenance rather than cleared."
    PRD §3.5: "A bin's `occupied_slots` starts at zero and is thereafter always the
    count of hardware units whose `storage_bin_id` is that bin **and** whose
    `handling_status` is exactly `STORED`."
    PRD §3.9: "Under `INSTALLER_LENIENT`, the unit's `warranty_preserved` is true
    only when `off_roof_days` is at most 14 **and** the unit's `condition_grade` is
    exactly `SERVICEABLE`."
    PRD §3.9: "When `warranty_preserved` comes out true, the unit's
    `warranty_risk_points` is 0."

    Design: Corner/state_machines/corner_reinstall_frees_the_bin_slot_while_retaining_storage_provenance
    """
    ctx = _authorized_host_owned()
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)
    unit = add_unit(project_id, circuit["id"], crew_id, serial_number="SN-0001")
    storage_bin = add_bin(project_id, bin_label="BIN-1", capacity_slots=2)

    deenergize_circuit(circuit["id"], crew_id, True)
    remove_unit(unit["id"], crew_id)
    grade_unit(unit["id"], crew_id, "SERVICEABLE", "RETAIN")
    store_unit(unit["id"], storage_bin["id"], crew_id)

    finding = add_finding(
        project_id,
        roofer_id,
        finding_type="FASTENER_PULLOUT",
        severity="LOW",
        affected_area_sqft=10.0,
        attachment_count_affected=0,
    )
    drive_finding(
        finding["id"],
        roofer_id,
        "WAIVE",
        waiver_reason="deck sound, fasteners re-seated under the roofing scope",
    )

    occupied_before = _read_bin(storage_bin["id"])
    assert occupied_before["occupied_slots"] == 1, (
        f"the stored unit occupies one slot, got {occupied_before['occupied_slots']}"
    )

    reinstalled = reinstall_unit(unit["id"], crew_id)
    assert reinstalled["handling_status"] == "REINSTALLED", (
        reinstalled["handling_status"]
    )
    assert reinstalled["storage_bin_id"] == storage_bin["id"], (
        f"storage_bin_id is retained as provenance, got "
        f"{reinstalled.get('storage_bin_id')!r}"
    )
    assert reinstalled["storage_label"] == "BIN-1-1", reinstalled["storage_label"]
    assert reinstalled["off_roof_days"] == 0, reinstalled["off_roof_days"]
    assert reinstalled["warranty_variant"] == "INSTALLER_LENIENT", (
        reinstalled["warranty_variant"]
    )
    assert reinstalled["warranty_preserved"] is True, reinstalled["warranty_preserved"]
    assert reinstalled["warranty_risk_points"] == 0, reinstalled["warranty_risk_points"]

    bin_after = _read_bin(storage_bin["id"])
    assert bin_after["occupied_slots"] == 0, (
        f"a reinstalled unit is no longer STORED, so the slot is free, got "
        f"{bin_after['occupied_slots']}"
    )

    project = refresh_project(project_id)
    assert project["stored_unit_count"] == 0, project["stored_unit_count"]
    assert project["reinstalled_unit_count"] == 1, project["reinstalled_unit_count"]
    assert project["warranty_preserved"] is True, project["warranty_preserved"]


def test_scoping_a_high_flashing_finding_does_not_reopen_the_approved_permit():
    """requires_repermit is false for a flashing failure, so the cascade stays shut.

    PRD §3.6: "One derived flag is computed at creation and never changes:
    `requires_repermit` is true exactly when the `severity` is `HIGH` or `CRITICAL`
    **and** the `finding_type` is `SHEATHING_ROT` or `STRUCTURAL_DEFLECTION`."
    PRD §3.6: "When the finding's `requires_repermit` is true **and** the project has
    a permit application in `APPROVED` **and** that permit's jurisdiction has
    `repermit_required_for_reinstall` set to true, that permit reverts `APPROVED →
    SUBMITTED`: its `revision_count` increases by one, its `reopened_by_finding_id`
    is set to this finding's identifier, its `submitted_at` is stamped with the
    current instant, its `fee_cents` is recomputed by the permit fee rule of §3.7,
    and its `review_deadline_utc` is recomputed as the new `submitted_at` plus the
    jurisdiction's `permit_review_days` whole days."
    PRD §2.6: "If the project is not `FROZEN`, the posture is `RESTRICTED` when at
    least one of these four conditions holds: the project has a deck finding whose
    `severity` is `HIGH` and whose `status` is either `OPEN` or `UPGRADE_SCOPED`; the
    project has a permit application whose `status` is either `DRAFT` or `SUBMITTED`
    and whose jurisdiction has `repermit_required_for_reinstall` set to true; some
    inspection booked under any permit application of the project has `status`
    `FAILED` or `CORRECTION_REQUIRED`; or the project's `weather_abort_count` has
    reached two or more."
    PRD §3.6: "On success the finding's `upgrade_cost_cents` is written, `status`
    becomes `UPGRADE_SCOPED`, `scoped_at` is stamped with the current instant, and
    `scoped_by_party_id` records the acting `X-User-ID`."

    Design: Corner/state_machines/corner_scoping_a_high_flashing_finding_does_not_reopen_the_approved_permit
    """
    ctx = _intake_host_owned()
    project_id = ctx["project"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]
    jurisdiction = create_jurisdiction(
        name="Westvale AHJ",
        code="WESTVALE",
        repermit_required_for_reinstall=True,
        reinspection_required=True,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=10,
    )

    permit = create_permit(project_id, jurisdiction["id"], scope="STRUCTURAL_UPGRADE")
    submit_permit(permit["id"])
    decide_permit(permit["id"], jurisdiction["id"], "APPROVE")

    inspection = book_inspection(
        permit["id"],
        inspection_type="ROOF_DECK",
        slot_date="2026-08-05",
        window_start_utc="2026-08-05T15:00:00Z",
        window_end_utc="2026-08-05T17:00:00Z",
    )
    record_result(
        inspection["id"], jurisdiction["id"], "PASS", result_note="deck acceptable"
    )

    finding = add_finding(
        project_id,
        roofer_id,
        finding_type="FLASHING_FAILURE",
        severity="HIGH",
        affected_area_sqft=120.0,
        attachment_count_affected=6,
    )

    scoped = validate_success(
        api_client.upgrade_deck_finding(
            finding["id"], {"action": "SCOPE"}, make_roofing_contractor_headers(roofer_id)
        ),
        200,
    )
    assert scoped["status"] == "UPGRADE_SCOPED", scoped["status"]
    assert scoped["requires_repermit"] is False, (
        f"a FLASHING_FAILURE is not a re-permit trigger, got "
        f"{scoped['requires_repermit']}"
    )
    assert scoped["upgrade_cost_cents"] == 198_940, (
        f"expected the published 198940 cents, got {scoped['upgrade_cost_cents']}"
    )
    assert scoped["scoped_by_party_id"] == roofer_id, scoped["scoped_by_party_id"]

    permit_read = _read_permit(permit["id"])
    assert permit_read["status"] == "APPROVED", (
        f"the approved permit must not be reopened, got {permit_read['status']}"
    )
    assert permit_read["revision_count"] == 0, permit_read["revision_count"]
    assert permit_read.get("reopened_by_finding_id") is None, (
        permit_read.get("reopened_by_finding_id")
    )
    assert permit_read["fee_cents"] == 51_100, (
        f"46000 base plus 6.0 kW at 850 cents is 51100, got {permit_read['fee_cents']}"
    )

    inspection_read = _read_inspection(inspection["id"])
    assert inspection_read["status"] == "PASSED", (
        f"a passed inspection survives a non-re-permitting scope, got "
        f"{inspection_read['status']}"
    )
    assert inspection_read["attempt_number"] == 1, inspection_read["attempt_number"]

    project = refresh_project(project_id)
    assert project["posture"] == "RESTRICTED", (
        f"a HIGH finding in UPGRADE_SCOPED restricts the project, got "
        f"{project['posture']}"
    )
    assert project["scoped_upgrade_cost_cents"] == 198_940, (
        project["scoped_upgrade_cost_cents"]
    )
