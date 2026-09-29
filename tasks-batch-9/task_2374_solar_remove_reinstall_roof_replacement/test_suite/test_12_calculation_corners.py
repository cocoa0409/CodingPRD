"""Corner tests for the PRD's derived money, fee and posture calculations.

Every test builds its own world from an empty database and a logical clock that
reads 2026-08-01T00:00:00Z, then exercises exactly one computed rule.
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
    assert_credit_ledger_identity,
    create_core_parties,
    create_jurisdiction,
    create_permit,
    create_project,
    deenergize_circuit,
    drive_finding,
    file_warranty_notice,
    get_success_data,
    grade_unit,
    make_ahj_inspector_headers,
    make_roofing_contractor_headers,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    make_system_owner_headers,
    refresh_project,
    reinstall_unit,
    remove_unit,
    reschedule_window,
    set_clock,
    setup_authorized_project,
    store_unit,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local helpers (private to this module by design)
# ---------------------------------------------------------------------------
def _assert_instant(actual, expected_prefix: str, label: str) -> None:
    """Compare an ISO 8601 UTC instant down to whole seconds."""
    assert actual is not None, f"{label} must be stamped, got None"
    assert actual[:19] == expected_prefix, (
        f"{label} expected {expected_prefix} but got {actual}"
    )


def _drive_window_as(window_id: str, action: str, headers: dict, **extra) -> dict:
    """Advance a crew window under a specific party identity."""
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.set_work_window_status(window_id, payload, headers), 200
    )


def _host_owned_project(**overrides) -> tuple:
    """Parties plus a HOST_OWNED project that has collected no consent yet."""
    parties = create_core_parties()
    project = create_project(parties, ownership_model="HOST_OWNED", **overrides)
    return parties, project


# ---------------------------------------------------------------------------
# Provisional downtime credit
# ---------------------------------------------------------------------------
def test_ppa_provisional_credit_applies_the_point_eight_five_ownership_factor():
    """A PPA project reserves its provisional credit at the 0.85 ownership factor.

    PRD §3.9: "An ownership factor then scales the result according to who was
    actually deprived of the energy: 0.00 for `HOST_OWNED` (the host owns the
    array, so no credit is owed at all), 1.00 for `LEASE`, and 0.85 for `PPA`."
    PRD §3.9: "It is the `baseline_daily_kwh` multiplied by
    `downtime_days_estimated`, multiplied by 14 cents, multiplied by the
    ownership factor, with a **single** rounding half up to whole cents applied
    to that entire product at the end."

    Design: Corner/calculations/corner_ppa_provisional_credit_applies_the_zero_point_eight_five_ownership_factor
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_authorized_project(
        ownership_model="PPA",
        site_address="1204 Pima Trail, Gilbert AZ",
        system_dc_kw=7.2,
        baseline_daily_kwh=33.6,
        downtime_days_estimated=5,
        upgrade_budget_cents=3_000_000,
    )
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    sysowner_id = ctx["parties"]["sysowner"]["id"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)

    response = api_client.set_circuit_energization(
        circuit["id"],
        {"action": "DE_ENERGIZE", "interlock_verified": True},
        make_solar_contractor_headers(crew_id),
    )
    validate_success(response, 200)

    project = refresh_project(project_id)
    assert project["phase"] == "DEENERGIZED", (
        f"the only circuit is ISOLATED so the project must advance, got {project['phase']}"
    )
    assert project["required_approval_party_count"] == 3, (
        "a PPA project names a system owner, so the consent quorum is 3, got "
        f"{project['required_approval_party_count']}"
    )
    assert project["provisional_credit_cents"] == 1999, (
        "33.6 kWh * 5 days * 14 cents * 0.85 rounds half up to 1999, got "
        f"{project['provisional_credit_cents']}"
    )
    assert project["credit_authorized_cents"] == 1999, (
        f"reservation authorizes the same amount, got {project['credit_authorized_cents']}"
    )
    assert project["credit_reserved_cents"] == 1999, (
        f"reservation reserves the same amount, got {project['credit_reserved_cents']}"
    )
    assert project["credit_settled_cents"] == 0, (
        f"nothing is settled yet, got {project['credit_settled_cents']}"
    )
    assert project["credit_released_cents"] == 0, (
        f"nothing is released yet, got {project['credit_released_cents']}"
    )
    assert_credit_ledger_identity(project)

    summary = get_success_data(
        api_client.get_downtime_summary(
            project_id, make_system_owner_headers(sysowner_id)
        ),
        200,
    )
    assert summary["downtime_days_actual"] == 0, (
        f"reenergized_at is still absent, got {summary['downtime_days_actual']}"
    )
    assert summary["final_credit_cents"] == 0, (
        f"the final variant has not run yet, got {summary['final_credit_cents']}"
    )
    assert summary["provisional_credit_cents"] == 1999, (
        f"the summary echoes the reserved figure, got {summary['provisional_credit_cents']}"
    )
    assert summary["ledger_balanced"] is True, "the four accounts must balance"


# ---------------------------------------------------------------------------
# Permit fee
# ---------------------------------------------------------------------------
def test_permit_fee_adds_expedite_and_revision_surcharge_only_on_resubmission():
    """The revision surcharge is absent on the first submission and present once after.

    PRD §3.7: "The scope base is 18,000 cents for `REINSTALL_ONLY`, 46,000 cents
    for `STRUCTURAL_UPGRADE` and 72,000 cents for `FULL_REPERMIT`."
    PRD §3.7: "To that is added 9,000 cents for each revision, counted using the
    value of `revision_count` **after** the increment performed by this very
    submission — so a first submission, whose `revision_count` is still zero,
    adds nothing, while the first resubmission adds 9,000 cents."
    PRD §3.7: "Either way `status` becomes `SUBMITTED`, `submitted_at` is stamped
    with the current instant, and `review_deadline_utc` is set to that
    `submitted_at` plus the jurisdiction's `permit_review_days` whole days."

    Design: Corner/calculations/corner_permit_fee_adds_expedite_and_the_revision_surcharge_only_after_resubmission
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="418 Mesquite Way, Tempe AZ",
        system_dc_kw=8.4,
        baseline_daily_kwh=41.75,
        downtime_days_estimated=9,
        upgrade_budget_cents=5_000_000,
    )
    jurisdiction = create_jurisdiction(
        name="Flatrock AHJ",
        code="FLATROCK",
        repermit_required_for_reinstall=False,
        reinspection_required=False,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=10,
        expedite_fee_cents=12_000,
    )
    permit = create_permit(
        project["id"], jurisdiction["id"], scope="FULL_REPERMIT", expedited=True
    )

    first = validate_success(
        api_client.submit_permit_application(permit["id"], COORD), 200
    )
    assert first["fee_cents"] == 91140, (
        "72000 base + round_half_up(8.4 * 850)=7140 + 12000 expedite + 0 revision "
        f"surcharge is 91140, got {first['fee_cents']}"
    )
    assert first["revision_count"] == 0, (
        f"a first submission does not revise, got {first['revision_count']}"
    )
    _assert_instant(
        first["review_deadline_utc"], "2026-08-11T00:00:00", "review_deadline_utc"
    )

    rejected = get_success_data(
        api_client.decide_permit_application(
            permit["id"],
            {"decision": "REJECT", "rejection_reason": "missing structural calculations"},
            make_ahj_inspector_headers(jurisdiction["id"]),
        ),
        200,
    )
    assert rejected["status"] == "REJECTED", (
        f"the AHJ rejected the application, got {rejected['status']}"
    )
    assert refresh_project(project["id"])["posture"] == "FROZEN", (
        "a REJECTED permit application freezes the project"
    )

    set_clock("2026-08-03T00:00:00Z")

    response = api_client.submit_permit_application(permit["id"], COORD)
    resubmitted = validate_success(response, 200)
    assert resubmitted["status"] == "SUBMITTED", (
        f"resubmission is accepted from REJECTED, got {resubmitted['status']}"
    )
    assert resubmitted["revision_count"] == 1, (
        f"a resubmission out of REJECTED revises once, got {resubmitted['revision_count']}"
    )
    assert resubmitted["fee_cents"] == 100140, (
        f"91140 plus the single 9000 revision surcharge, got {resubmitted['fee_cents']}"
    )
    _assert_instant(resubmitted["submitted_at"], "2026-08-03T00:00:00", "submitted_at")
    _assert_instant(
        resubmitted["review_deadline_utc"],
        "2026-08-13T00:00:00",
        "review_deadline_utc",
    )
    assert resubmitted.get("rejection_reason") is None, (
        "a resubmission clears any recorded rejection_reason, got "
        f"{resubmitted.get('rejection_reason')}"
    )
    assert refresh_project(project["id"])["posture"] == "OPEN", (
        "no REJECTED permit remains and the jurisdiction does not require "
        "re-permitting, so the posture returns to OPEN"
    )


# ---------------------------------------------------------------------------
# Deck upgrade cost — emergency severity bump
# ---------------------------------------------------------------------------
def test_emergency_scope_bump_applies_only_while_the_posture_is_frozen():
    """Two byte-identical findings cost differently either side of a permit rejection.

    PRD §3.6: "When the project's `posture` is `FROZEN` at the instant of
    scoping, an emergency bump of 0.25 is **added to the multiplier** before it
    is used, so the same finding costs strictly more when it is scoped on a
    frozen project than on an `OPEN` or `RESTRICTED` one."
    PRD §3.6: "The published multipliers are 1.00 for `LOW`, 1.15 for `MEDIUM`,
    1.40 for `HIGH` and 1.75 for `CRITICAL`."
    PRD §3.6: "One derived flag is computed at creation and never changes:
    `requires_repermit` is true exactly when the `severity` is `HIGH` or
    `CRITICAL` **and** the `finding_type` is `SHEATHING_ROT` or
    `STRUCTURAL_DEFLECTION`."

    Design: Corner/calculations/corner_emergency_scope_variant_bumps_severity_only_while_posture_is_frozen
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    roofer_id = parties["roofer"]["id"]
    jurisdiction = create_jurisdiction(
        name="Flatrock AHJ",
        code="FLATROCK",
        repermit_required_for_reinstall=False,
        reinspection_required=False,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=7,
    )
    finding_kwargs = {
        "finding_type": "MOISTURE_INTRUSION",
        "severity": "MEDIUM",
        "affected_area_sqft": 80.0,
        "attachment_count_affected": 4,
    }
    f1 = add_finding(project["id"], roofer_id, **finding_kwargs)
    f2 = add_finding(project["id"], roofer_id, **finding_kwargs)
    permit = create_permit(project["id"], jurisdiction["id"], scope="REINSTALL_ONLY")
    validate_success(api_client.submit_permit_application(permit["id"], COORD), 200)

    scoped_open = validate_success(
        api_client.upgrade_deck_finding(
            f1["id"], {"action": "SCOPE"}, make_roofing_contractor_headers(roofer_id)
        ),
        200,
    )
    assert scoped_open["upgrade_cost_cents"] == 106720, (
        "(80 * 950 + 4 * 4200) * 1.15 is 106720 under posture OPEN, got "
        f"{scoped_open['upgrade_cost_cents']}"
    )
    assert refresh_project(project["id"])["posture"] == "OPEN", (
        "a MEDIUM finding and a SUBMITTED permit in a jurisdiction that does not "
        "require re-permitting leave the posture OPEN"
    )

    get_success_data(
        api_client.decide_permit_application(
            permit["id"],
            {"decision": "REJECT", "rejection_reason": "deck repair scope not documented"},
            make_ahj_inspector_headers(jurisdiction["id"]),
        ),
        200,
    )
    assert refresh_project(project["id"])["posture"] == "FROZEN", (
        "a REJECTED permit application freezes the project"
    )

    response = api_client.upgrade_deck_finding(
        f2["id"], {"action": "SCOPE"}, make_roofing_contractor_headers(roofer_id)
    )
    scoped_frozen = validate_success(response, 200)
    assert scoped_frozen["upgrade_cost_cents"] == 129920, (
        "92800 * (1.15 + 0.25) is 129920 while the posture is FROZEN, got "
        f"{scoped_frozen['upgrade_cost_cents']}"
    )
    assert scoped_frozen["requires_repermit"] is False, (
        "MOISTURE_INTRUSION never requires re-permitting"
    )

    first_again = get_success_data(api_client.get_deck_finding(f1["id"], COORD), 200)
    assert first_again["upgrade_cost_cents"] == 106720, (
        f"the earlier finding is not repriced, got {first_again['upgrade_cost_cents']}"
    )
    assert first_again["requires_repermit"] is False, (
        "MOISTURE_INTRUSION never requires re-permitting"
    )

    project_after = refresh_project(project["id"])
    assert project_after["scoped_upgrade_cost_cents"] == 236640, (
        "106720 + 129920 is 236640, got "
        f"{project_after['scoped_upgrade_cost_cents']}"
    )
    assert project_after["posture"] == "FROZEN", (
        "the rejected permit still freezes the project"
    )


# ---------------------------------------------------------------------------
# Final chronological credit — input-set filtering
# ---------------------------------------------------------------------------
def test_final_credit_halves_only_the_weather_aborted_days():
    """Only WEATHER_ABORTED windows halve a downtime day at settlement.

    PRD §3.9: "Only windows in `WEATHER_ABORTED` count for this; `SUPERSEDED`,
    `REVOKED`, `COMPLETED`, `SCHEDULED` and `IN_PROGRESS` windows are all
    excluded, which means a rescheduled abort stops halving its days once it
    becomes `SUPERSEDED`."
    PRD §3.9: "That day's cents are the `baseline_daily_kwh` multiplied by 14
    cents, multiplied by the ownership factor, multiplied by that day's factor,
    **rounded half up to whole cents for that day**."
    PRD §3.9: "On success the computed figure is written to
    `final_credit_cents`; the difference between `final_credit_cents` and
    `credit_reserved_cents` is taken, and when that difference is positive it is
    added to `credit_authorized_cents` (a negative or zero difference leaves the
    authorized total alone); `credit_settled_cents` is set to
    `final_credit_cents`; `credit_reserved_cents` is set to zero;
    `credit_released_cents` is set to `credit_authorized_cents` minus
    `credit_settled_cents`; and the project's `phase` moves
    `COMMISSIONED → CLOSED`."

    Design: Corner/calculations/corner_final_credit_counts_only_weather_aborted_windows_and_ignores_completed_superseded_and_scheduled_ones
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_authorized_project(
        ownership_model="LEASE",
        site_address="418 Mesquite Way, Tempe AZ",
        system_dc_kw=8.4,
        baseline_daily_kwh=41.75,
        downtime_days_estimated=4,
        upgrade_budget_cents=5_000_000,
    )
    project_id = ctx["project"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]
    owner_id = ctx["parties"]["owner"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]

    circuit = add_circuit(project_id, circuit_label="A1", module_count=1, dc_kw=0.41)
    unit = add_unit(project_id, circuit["id"], crew_id, serial_number="SN-0001")
    storage_bin = add_bin(
        project_id, bin_label="BIN-1", capacity_slots=2, climate_controlled=True
    )

    set_clock("2026-08-05T08:00:00Z")
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
    file_warranty_notice(
        project_id, manufacturer="Meridian Solar", notice_reference="MFR-2026-0011"
    )

    set_clock("2026-08-08T16:00:00Z")
    reinstalled = reinstall_unit(unit["id"], crew_id)
    get_success_data(
        api_client.set_circuit_energization(
            circuit["id"],
            {"action": "RE_ENERGIZE", "interlock_verified": True},
            make_solar_contractor_headers(crew_id),
        ),
        200,
    )

    # Four windows over the downtime span: only the WEATHER_ABORTED one may halve
    # its calendar day.
    w_abort = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-06T14:00:00Z",
        end_utc="2026-08-06T22:00:00Z",
    )
    _drive_window_as(
        w_abort["id"],
        "WEATHER_ABORT",
        make_roofing_contractor_headers(roofer_id),
        abort_reason="monsoon cell over the site",
    )
    w_done = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-07T14:00:00Z",
        end_utc="2026-08-07T22:00:00Z",
    )
    _drive_window_as(w_done["id"], "START", make_roofing_contractor_headers(roofer_id))
    _drive_window_as(
        w_done["id"], "COMPLETE", make_roofing_contractor_headers(roofer_id)
    )
    w_super = add_window(
        project_id,
        crew_id,
        trade="SOLAR_REMOVAL",
        start_utc="2026-08-05T09:00:00Z",
        end_utc="2026-08-05T17:00:00Z",
    )
    _drive_window_as(
        w_super["id"],
        "WEATHER_ABORT",
        make_solar_contractor_headers(crew_id),
        abort_reason="high wind on the removal day",
    )
    w_replacement = reschedule_window(
        w_super["id"], "2026-08-20T09:00:00Z", "2026-08-20T17:00:00Z"
    )
    w_sched = add_window(
        project_id,
        crew_id,
        trade="SOLAR_REINSTALL",
        start_utc="2026-08-07T09:00:00Z",
        end_utc="2026-08-07T17:00:00Z",
    )

    response = api_client.settle_credit(
        project_id, {"settlement_note": "final chronological settlement"}, COORD
    )
    validate_success(response, 200)

    project = refresh_project(project_id)
    assert project["phase"] == "CLOSED", (
        f"settlement closes the project, got {project['phase']}"
    )
    assert project["downtime_days_actual"] == 4, (
        "2026-08-05 through 2026-08-08 inclusive is four dates, got "
        f"{project['downtime_days_actual']}"
    )
    assert project["provisional_credit_cents"] == 2338, (
        "41.75 * 4 * 14 * 1.00 rounds half up to 2338, got "
        f"{project['provisional_credit_cents']}"
    )
    assert project["final_credit_cents"] == 2047, (
        "585 + 292 + 585 + 585 is 2047 with only 2026-08-06 halved, got "
        f"{project['final_credit_cents']}"
    )
    assert project["credit_authorized_cents"] == 2338, (
        "the final figure is lower than the reservation, so nothing is topped up, "
        f"got {project['credit_authorized_cents']}"
    )
    assert project["credit_settled_cents"] == 2047, (
        f"settled equals the final figure, got {project['credit_settled_cents']}"
    )
    assert project["credit_reserved_cents"] == 0, (
        f"settlement empties the reserve, got {project['credit_reserved_cents']}"
    )
    assert project["credit_released_cents"] == 291, (
        f"2338 - 2047 is released, got {project['credit_released_cents']}"
    )
    assert project["weather_abort_count"] == 2, (
        f"two windows were weather-aborted, got {project['weather_abort_count']}"
    )
    assert_credit_ledger_identity(project)

    statuses = {
        "w_abort": (w_abort["id"], "WEATHER_ABORTED"),
        "w_done": (w_done["id"], "COMPLETED"),
        "w_super": (w_super["id"], "SUPERSEDED"),
        "w_replacement": (w_replacement["id"], "SCHEDULED"),
        "w_sched": (w_sched["id"], "SCHEDULED"),
    }
    for label, (window_id, expected) in statuses.items():
        window = get_success_data(api_client.get_work_window(window_id, COORD), 200)
        assert window["status"] == expected, (
            f"{label} must be {expected}, got {window['status']}"
        )

    assert reinstalled["off_roof_days"] == 3, (
        "2026-08-08 minus 2026-08-05 is three whole days, got "
        f"{reinstalled['off_roof_days']}"
    )
    assert reinstalled["warranty_variant"] == "INSTALLER_LENIENT", (
        "the variant was pinned at removal, when warranty_notice_status was still "
        f"PENDING, got {reinstalled['warranty_variant']}"
    )
    assert reinstalled["warranty_preserved"] is True, (
        "three days off the roof on a SERVICEABLE unit preserves the warranty even "
        "under the lenient variant"
    )

    summary = get_success_data(
        api_client.get_downtime_summary(
            project_id, make_solar_owner_headers(owner_id)
        ),
        200,
    )
    assert summary["final_credit_cents"] == 2047, (
        f"the summary echoes the settled figure, got {summary['final_credit_cents']}"
    )
    assert summary["credit_released_cents"] == 291, (
        f"the summary echoes the release, got {summary['credit_released_cents']}"
    )
    assert summary["ledger_balanced"] is True, "the four accounts must balance"


# ---------------------------------------------------------------------------
# Posture — weather abort threshold
# ---------------------------------------------------------------------------
def test_weather_abort_threshold_restricts_posture_at_exactly_two_aborts():
    """One abort leaves the posture OPEN; the second one restricts the project.

    PRD §3.3: "Because that counter feeds the posture rule of §2.6, the second
    abort on a project is the one that bites: two aborts already drive the
    project to `RESTRICTED`, and posture is recomputed at the end of the abort."
    PRD §3.3: "It sets `status` to `WEATHER_ABORTED`, stamps `actual_end_utc`,
    records the reason, and increments the project's `weather_abort_count` by
    one."

    Design: Corner/calculations/corner_weather_abort_threshold_restricts_posture_at_exactly_two_aborts
    """
    set_clock(CLOCK_EPOCH)
    parties, project = _host_owned_project(
        site_address="77 Ocotillo Ln, Chandler AZ",
        system_dc_kw=6.0,
        baseline_daily_kwh=30.0,
        downtime_days_estimated=4,
        upgrade_budget_cents=2_000_000,
    )
    roofer_id = parties["roofer"]["id"]
    crew_id = parties["crew"]["id"]

    w1 = add_window(
        project["id"],
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-10T14:00:00Z",
        end_utc="2026-08-10T22:00:00Z",
    )
    w2 = add_window(
        project["id"],
        crew_id,
        trade="SOLAR_REMOVAL",
        start_utc="2026-08-12T09:00:00Z",
        end_utc="2026-08-12T17:00:00Z",
    )

    _drive_window_as(
        w1["id"],
        "WEATHER_ABORT",
        make_roofing_contractor_headers(roofer_id),
        abort_reason="first monsoon day",
    )
    after_first = refresh_project(project["id"])
    assert after_first["weather_abort_count"] == 1, (
        f"one abort has landed, got {after_first['weather_abort_count']}"
    )
    assert after_first["posture"] == "OPEN", (
        f"a single abort does not reach the threshold, got {after_first['posture']}"
    )

    response = api_client.set_work_window_status(
        w2["id"],
        {"action": "WEATHER_ABORT", "abort_reason": "second monsoon day"},
        make_solar_contractor_headers(crew_id),
    )
    validate_success(response, 200)

    after_second = refresh_project(project["id"])
    assert after_second["weather_abort_count"] == 2, (
        f"two aborts have landed, got {after_second['weather_abort_count']}"
    )
    assert after_second["posture"] == "RESTRICTED", (
        "the counter reaching two restricts the project in the same request, got "
        f"{after_second['posture']}"
    )

    for label, window_id in (("w1", w1["id"]), ("w2", w2["id"])):
        window = get_success_data(api_client.get_work_window(window_id, COORD), 200)
        assert window["status"] == "WEATHER_ABORTED", (
            f"{label} must be WEATHER_ABORTED, got {window['status']}"
        )
