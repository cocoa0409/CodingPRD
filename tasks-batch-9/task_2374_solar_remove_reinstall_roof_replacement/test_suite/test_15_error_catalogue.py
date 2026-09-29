"""Error-catalogue corners: distinct error ids for distinct rule violations.

Every test starts against an empty database with the logical clock reading
2026-08-01T00:00:00Z, and builds all of its preconditions from scratch.
"""

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    add_bin,
    add_circuit,
    add_unit,
    add_window,
    api_client,
    assert_credit_ledger_identity,
    build_user_headers,
    create_array_circuit_payload,
    create_core_parties,
    create_hardware_unit_payload,
    create_party,
    create_project,
    create_project_payload,
    create_storage_bin_payload,
    create_work_window_payload,
    drive_window,
    make_solar_contractor_headers,
    open_consent,
    refresh_project,
    set_clock,
    setup_commissioned_project,
    setup_reinstall_project,
    validate_error,
    validate_paginated,
    validate_success,
)

P1_ADDRESS = "77 Ocotillo Ln, Chandler AZ"
P2_ADDRESS = "81 Ocotillo Ln, Chandler AZ"
PROJECT_SHAPE = {
    "site_address": P1_ADDRESS,
    "system_dc_kw": 6.0,
    "baseline_daily_kwh": 30.0,
    "downtime_days_estimated": 4,
    "upgrade_budget_cents": 2000000,
}


def _host_owned_shape(**overrides):
    shape = dict(PROJECT_SHAPE)
    shape.update(overrides)
    return shape


def _setup_two_host_owned_projects(parties):
    """Two HOST_OWNED projects sharing the same parties."""
    p1 = create_project(
        parties, ownership_model="HOST_OWNED", **_host_owned_shape(site_address=P1_ADDRESS)
    )
    p2 = create_project(
        parties, ownership_model="HOST_OWNED", **_host_owned_shape(site_address=P2_ADDRESS)
    )
    return p1, p2


def test_missing_or_unknown_role_headers_are_unauthenticated():
    """Header defects answer 401 before any other rule is consulted.

    PRD §2.1: "If either header is missing or empty, or if `X-User-Role` is not one of the
    six roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/corner_missing_or_unknown_role_headers_are_unauthenticated
    """
    set_clock(CLOCK_EPOCH)
    crew = create_party(
        "SOLAR_CONTRACTOR",
        name="SunSystem Crew A",
        contact_email="crew.a@sunsystem.example",
    )

    no_headers = api_client.list_parties({})
    validate_error(no_headers, "ERR_UNAUTHENTICATED", 401)

    unknown_role = api_client.create_party(
        {
            "name": "Ghost Roofing",
            "party_type": "ROOFER",
            "contact_email": "ghost@example.com",
        },
        build_user_headers(crew["id"], "Architect"),
    )
    validate_error(unknown_role, "ERR_UNAUTHENTICATED", 401)

    no_user_id = api_client.list_parties(
        {"X-User-Role": "SolarContractor", "Content-Type": "application/json"}
    )
    validate_error(no_user_id, "ERR_UNAUTHENTICATED", 401)

    body = no_user_id.json()
    assert body["response_type"] == "error", body["response_type"]
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must carry only error_id and message, got {sorted(body['data'])}"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only the two request fields, got {sorted(body['meta'])}"
    )

    rows, meta = validate_paginated(api_client.list_parties(COORD))
    assert meta["total_count"] == 1, (
        f"the refused POST must persist nothing, got {meta['total_count']} parties"
    )
    assert len(rows) == 1 and rows[0]["id"] == crew["id"], rows


def test_four_uniqueness_rules_report_four_distinct_duplicate_errors():
    """Circuit label, bin label, serial and consent party each get their own code.

    PRD §3.4: "Each string on the one-line diagram is registered as an **ArrayCircuit** by
    the coordinator, carrying a `circuit_label` unique within the project (a repeat is
    `ERR_DUPLICATE_CIRCUIT_LABEL`, HTTP 409), a `module_count` of at least 1 recording how
    many modules were originally on the circuit, and a `dc_kw` capacity strictly greater
    than zero."
    PRD §3.5: "**Storage bins** are created by the coordinator with a `bin_label` unique
    within the project (a repeat is `ERR_DUPLICATE_BIN_LABEL`, HTTP 409), a
    `capacity_slots` count of at least 1, a `climate_controlled` flag defaulting to false,
    and an `accepts_unit_types` list which must be a non-empty subset of `PANEL` and
    `OPTIMIZER` and which defaults to accepting both."
    PRD §3.5: "A duplicate serial within the project is `ERR_DUPLICATE_SERIAL` (HTTP 409)."
    PRD §3.2: "At most one consent record may exist per project-and-party pair; a second
    attempt answers `ERR_DUPLICATE_APPROVAL_PARTY` (HTTP 409)."

    Design: Corner/errors/corner_four_uniqueness_rules_report_four_distinct_duplicate_errors
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    p1, p2 = _setup_two_host_owned_projects(parties)
    roofer_id = parties["roofer"]["id"]
    crew_id = parties["crew"]["id"]
    crew_headers = make_solar_contractor_headers(crew_id)

    c1 = add_circuit(p1["id"], circuit_label="A1", module_count=1, dc_kw=0.41)
    add_bin(p1["id"], bin_label="BIN-1", capacity_slots=2)
    add_unit(p1["id"], c1["id"], crew_id, serial_number="SN-0001", rated_watts=410)
    ap_roof = open_consent(p1["id"], roofer_id)
    c2 = add_circuit(p2["id"], circuit_label="A1", module_count=1, dc_kw=0.41)

    dup_circuit = api_client.create_array_circuit(
        p1["id"],
        create_array_circuit_payload(circuit_label="A1", module_count=3, dc_kw=1.23),
        COORD,
    )
    validate_error(dup_circuit, "ERR_DUPLICATE_CIRCUIT_LABEL", 409)

    dup_bin = api_client.create_storage_bin(
        p1["id"], create_storage_bin_payload(bin_label="BIN-1", capacity_slots=8), COORD
    )
    validate_error(dup_bin, "ERR_DUPLICATE_BIN_LABEL", 409)

    dup_serial = api_client.create_hardware_unit(
        p1["id"],
        create_hardware_unit_payload(
            c1["id"],
            unit_type="OPTIMIZER",
            manufacturer="Volt Logic",
            model_code="VL-500",
            serial_number="SN-0001",
            rated_watts=500,
        ),
        crew_headers,
    )
    validate_error(dup_serial, "ERR_DUPLICATE_SERIAL", 409)

    dup_approval = api_client.create_party_approval(
        p1["id"], {"party_id": roofer_id}, COORD
    )
    validate_error(dup_approval, "ERR_DUPLICATE_APPROVAL_PARTY", 409)

    # The very same labels and serial are free inside the neighbouring project.
    bin2 = validate_success(
        api_client.create_storage_bin(
            p2["id"],
            create_storage_bin_payload(bin_label="BIN-1", capacity_slots=2),
            COORD,
        ),
        201,
    )
    u2 = validate_success(
        api_client.create_hardware_unit(
            p2["id"],
            create_hardware_unit_payload(
                c2["id"], serial_number="SN-0001", rated_watts=410
            ),
            crew_headers,
        ),
        201,
    )
    assert bin2["project_id"] == p2["id"], bin2["project_id"]
    assert u2["serial_number"] == "SN-0001", u2["serial_number"]

    circuits, circuit_meta = validate_paginated(
        api_client.list_project_array_circuits(p1["id"], COORD)
    )
    assert circuit_meta["total_count"] == 1, circuit_meta
    assert len(circuits) == 1 and circuits[0]["id"] == c1["id"], circuits

    bins, bin_meta = validate_paginated(
        api_client.list_project_storage_bins(p1["id"], COORD)
    )
    assert bin_meta["total_count"] == 1, bin_meta

    units, unit_meta = validate_paginated(
        api_client.list_hardware_units(COORD, params={"project_id": p1["id"]})
    )
    assert unit_meta["total_count"] == 1, unit_meta

    approvals, approval_meta = validate_paginated(
        api_client.list_party_approvals(COORD, params={"project_id": p1["id"]})
    )
    assert approval_meta["total_count"] == 1, approval_meta
    assert len(approvals) == 1 and approvals[0]["id"] == ap_roof["id"], approvals


def test_party_type_mismatch_is_enforced_on_project_roles_approvals_and_crews():
    """Every party slot admits only its own party_type, and never a 404 instead.

    PRD §3.2: "Each reference must point at a party of the matching type — a `ROOFER` for
    the roofer slot, a `SOLAR_OWNER` for the solar-owner slot, a `SOLAR_CONTRACTOR` for the
    crew that will de-energize, remove and reinstall, and a `SYSTEM_OWNER` for the
    system-owner slot — and any mismatch is rejected with `ERR_PARTY_TYPE_MISMATCH`
    (HTTP 422)."
    PRD §3.2: "A coordinator opens a consent request by naming a `party_id`; the referenced
    party must be of type `ROOFER`, `SOLAR_OWNER` or `SYSTEM_OWNER`, and it must equal the
    project's corresponding party field for that type, otherwise the request is
    `ERR_PARTY_TYPE_MISMATCH`."
    PRD §3.3: "The `party_id` must reference a party whose `party_type` is `ROOFER` or
    `SOLAR_CONTRACTOR`; anything else is `ERR_PARTY_TYPE_MISMATCH`."

    Design: Corner/errors/corner_party_type_mismatch_is_enforced_on_project_roles_approvals_and_crews
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    owner_id = parties["owner"]["id"]
    crew_id = parties["crew"]["id"]
    p1 = create_project(parties, ownership_model="HOST_OWNED", **_host_owned_shape())

    wrong_slot = api_client.create_project(
        create_project_payload(
            roofer_party_id=owner_id,
            solar_owner_party_id=owner_id,
            solar_contractor_party_id=crew_id,
            ownership_model="HOST_OWNED",
            **_host_owned_shape(site_address="99 Ocotillo Ln, Chandler AZ"),
        ),
        COORD,
    )
    validate_error(wrong_slot, "ERR_PARTY_TYPE_MISMATCH", 422)

    wrong_consenter = api_client.create_party_approval(
        p1["id"], {"party_id": crew_id}, COORD
    )
    validate_error(wrong_consenter, "ERR_PARTY_TYPE_MISMATCH", 422)

    wrong_crew = api_client.create_work_window(
        create_work_window_payload(
            p1["id"],
            owner_id,
            trade="ROOFING",
            start_utc="2026-08-10T14:00:00Z",
            end_utc="2026-08-10T22:00:00Z",
        ),
        COORD,
    )
    validate_error(wrong_crew, "ERR_PARTY_TYPE_MISMATCH", 422)

    w_ok = validate_success(
        api_client.create_work_window(
            create_work_window_payload(
                p1["id"],
                crew_id,
                trade="SOLAR_REMOVAL",
                start_utc="2026-08-10T14:00:00Z",
                end_utc="2026-08-10T22:00:00Z",
            ),
            COORD,
        ),
        201,
    )
    assert w_ok["party_id"] == crew_id, w_ok["party_id"]

    projects, project_meta = validate_paginated(api_client.list_projects(COORD))
    assert project_meta["total_count"] == 1, project_meta
    assert len(projects) == 1 and projects[0]["id"] == p1["id"], projects

    approvals, approval_meta = validate_paginated(
        api_client.list_party_approvals(COORD, params={"project_id": p1["id"]})
    )
    assert approval_meta["total_count"] == 0, approval_meta
    assert approvals == [], approvals
    assert refresh_project(p1["id"])["phase"] == "INTAKE", (
        "no consent record was persisted, so the project stays in INTAKE"
    )


def test_two_weather_aborts_restrict_the_project_and_block_reinstall_and_reenergize():
    """A second weather abort alone turns reinstall and re-energize into 409s.

    PRD §2.6: "If the project is not `FROZEN`, the posture is `RESTRICTED` when at least
    one of these four conditions holds: the project has a deck finding whose `severity` is
    `HIGH` and whose `status` is either `OPEN` or `UPGRADE_SCOPED`; the project has a
    permit application whose `status` is either `DRAFT` or `SUBMITTED` and whose
    jurisdiction has `repermit_required_for_reinstall` set to true; some inspection booked
    under any permit application of the project has `status` `FAILED` or
    `CORRECTION_REQUIRED`; or the project's `weather_abort_count` has reached two or more."
    PRD §2.6: "Two operations demand more, requiring the posture to be exactly `OPEN`
    because they restore energy or put hardware back on the roof: reinstalling a unit and
    re-energizing a circuit."
    PRD §2.6: "When the posture on those two is `RESTRICTED`, the refusal is
    `ERR_PROJECT_POSTURE_RESTRICTED` (HTTP 409)."
    PRD §3.3: "It sets `status` to `WEATHER_ABORTED`, stamps `actual_end_utc`, records the
    reason, and increments the project's `weather_abort_count` by one."

    Design: Corner/errors/corner_two_weather_aborts_restrict_the_project_and_block_reinstall_and_reenergize
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_reinstall_project(
        ownership_model="HOST_OWNED", circuit_count=1, unit_count=1, **_host_owned_shape()
    )
    project_id = ctx["project"]["id"]
    crew_id = ctx["parties"]["crew"]["id"]
    roofer_id = ctx["parties"]["roofer"]["id"]
    circuit = ctx["circuits"][0]
    unit = ctx["units"][0]
    crew_headers = make_solar_contractor_headers(crew_id)

    w1 = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-10T14:00:00Z",
        end_utc="2026-08-10T22:00:00Z",
    )
    w2 = add_window(
        project_id,
        roofer_id,
        trade="ROOFING",
        start_utc="2026-08-12T14:00:00Z",
        end_utc="2026-08-12T22:00:00Z",
    )
    drive_window(w1["id"], "WEATHER_ABORT", abort_reason="first monsoon cell")
    drive_window(w2["id"], "WEATHER_ABORT", abort_reason="second monsoon cell")

    blocked_reinstall = api_client.reinstall_hardware_unit(unit["id"], crew_headers)
    validate_error(blocked_reinstall, "ERR_PROJECT_POSTURE_RESTRICTED", 409)

    blocked_reenergize = api_client.set_circuit_energization(
        circuit["id"], {"action": "RE_ENERGIZE", "interlock_verified": True}, crew_headers
    )
    validate_error(blocked_reenergize, "ERR_PROJECT_POSTURE_RESTRICTED", 409)

    project = refresh_project(project_id)
    assert project["weather_abort_count"] == 2, project["weather_abort_count"]
    assert project["posture"] == "RESTRICTED", project["posture"]
    assert project["phase"] == "REINSTALL", project["phase"]
    assert project["reinstalled_unit_count"] == 0, project["reinstalled_unit_count"]

    unit_after = validate_success(api_client.get_hardware_unit(unit["id"], COORD), 200)
    assert unit_after["handling_status"] == "STORED", unit_after["handling_status"]
    assert unit_after.get("reinstalled_at") is None, unit_after.get("reinstalled_at")
    assert unit_after.get("off_roof_days") is None, unit_after.get("off_roof_days")

    circuit_after = validate_success(
        api_client.get_array_circuit(circuit["id"], COORD), 200
    )
    assert circuit_after["status"] == "ISOLATED", circuit_after["status"]


def test_perturbed_credit_ledger_blocks_settlement_with_the_identity_guard():
    """The defensive ledger identity check refuses settlement on a broken ledger.

    PRD §2.7: "Because no legitimate workflow can unbalance the ledger, the identity is
    nevertheless re-verified defensively before settlement is applied; a project whose
    accounts do not satisfy it is refused with `ERR_CREDIT_LEDGER_UNBALANCED` (HTTP 409)."
    PRD §2.7: "A test-driving capability exists purely so that guard is reachable: given a
    `project_id` and a `released_delta_cents` amount, it adds that amount to
    `credit_released_cents` while leaving `credit_authorized_cents`,
    `credit_reserved_cents` and `credit_settled_cents` untouched, and increments the
    project's `version`."

    Design: Corner/errors/corner_perturbed_credit_ledger_blocks_settlement_with_the_identity_guard
    """
    set_clock(CLOCK_EPOCH)
    ctx = setup_commissioned_project(
        ownership_model="HOST_OWNED", circuit_count=1, unit_count=1, **_host_owned_shape()
    )
    project_id = ctx["project"]["id"]
    assert ctx["project"]["phase"] == "COMMISSIONED", ctx["project"]["phase"]
    assert_credit_ledger_identity(ctx["project"])

    perturbed = validate_success(
        api_client.perturb_ledger(project_id, 5000, COORD), 200
    )
    assert perturbed is not None, "the perturbation endpoint must answer with a payload"

    summary = validate_success(api_client.get_downtime_summary(project_id, COORD), 200)
    assert summary["credit_released_cents"] == 5000, summary["credit_released_cents"]
    assert summary["ledger_balanced"] is False, (
        f"the perturbed ledger must report itself unbalanced, got {summary}"
    )

    refused = api_client.settle_credit(
        project_id, {"settlement_note": "attempted close on a broken ledger"}, COORD
    )
    validate_error(refused, "ERR_CREDIT_LEDGER_UNBALANCED", 409)

    project = refresh_project(project_id)
    assert project["phase"] == "COMMISSIONED", (
        f"settlement was refused, so the project must not close, got {project['phase']}"
    )
    assert project["final_credit_cents"] == 0, project["final_credit_cents"]
    assert project["credit_settled_cents"] == 0, project["credit_settled_cents"]
    assert project["credit_authorized_cents"] == 0, project["credit_authorized_cents"]
    assert project["credit_reserved_cents"] == 0, project["credit_reserved_cents"]
    assert project["credit_released_cents"] == 5000, project["credit_released_cents"]
