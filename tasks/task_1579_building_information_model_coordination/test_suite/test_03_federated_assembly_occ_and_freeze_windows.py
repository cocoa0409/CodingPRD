"""Federated assembly lifecycle, optimistic concurrency on project version,
member/sign-off version pinning, and freeze-window interval rules."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_model,
    create_and_accept_model,
    create_clash_run,
    create_federated_model,
    create_freeze_window,
    create_fabrication_package_payload,
    create_federated_model_payload,
    create_meeting,
    create_model,
    create_package,
    create_partner,
    create_project,
    create_quantity_takeoff_payload,
    freeze_fed,
    get_fed,
    get_model,
    get_project,
    list_members,
    list_package_signoffs,
    make_fabrication_lead_headers,
    make_takeoff_element,
    set_clock,
    setup_accepted_model_scenario,
    setup_frozen_assembly,
    submit_model,
    submit_package_for_signoff,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]


class TestInitialStatesAndBubbleUp:
    def test_initial_states_observed_at_creation(self, api):
        """PRD §3.2: "A `TradeModelAuthor` creates a revision in `DRAFT`"
        PRD §3.3: "The new assembly starts in `ASSEMBLED` when every member
        model is already `ACCEPTED` at creation, and in `DRAFT` otherwise"
        PRD §3.5: "Starting a meeting requires `SCHEDULED`
        (`ERR_MEETING_NOT_SCHEDULED`)"

        Design: Corner/state_machines/initial_states_observed_at_creation
        """
        project = create_project("SM1")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"])
        assert model["status"] == "DRAFT", "a new revision opens in DRAFT"

        fed = create_federated_model(project["id"], [model["id"]], label="F0")
        assert fed["status"] == "DRAFT", \
            "member not yet ACCEPTED: the assembly opens in DRAFT"

        meeting = create_meeting(project["id"])
        assert meeting["status"] == "SCHEDULED"

    def test_federated_auto_assemble_bubble_up(self, api):
        """PRD §3.3: "a `DRAFT` assembly advances to `ASSEMBLED` automatically
        the moment all its members are accepted."

        Design: Corner/state_machines/federated_auto_assemble_bubble_up
        """
        project = create_project("SM2")
        partner = create_partner(project["id"])
        model = create_model(project["id"], partner["id"])
        fed = create_federated_model(project["id"], [model["id"]], label="F0")
        assert fed["status"] == "DRAFT"

        submit_model(model["id"], partner["id"])
        accept_model(model["id"])

        fed_after = get_fed(fed["id"])
        assert fed_after["status"] == "ASSEMBLED", \
            "no direct call targeted the assembly; the accept bubbled it up"


class TestAssemblyValidation:
    def test_cross_project_member_reference_rejected(self, api):
        """PRD §3.3: "Every member must belong to the same project as the
        assembly (`ERR_CROSS_PROJECT_REFERENCE`)"

        Design: Corner/validations/cross_project_member_reference_rejected
        """
        project_a = create_project("V3A")
        project_b = create_project("V3B")
        partner_b = create_partner(project_b["id"], company_name="StructCoB")
        model_b = create_model(project_b["id"], partner_b["id"],
                               life_safety_elements=1, life_safety_compliant=1,
                               envelope_elements=0, envelope_compliant=0,
                               finish_elements=0, finish_compliant=0)

        resp = api.create_federated_model(
            project_a["id"],
            create_federated_model_payload(
                [model_b["id"]], project_a["version"], label="FA"),
            VDC)
        validate_error(resp, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE)

        data = api.list_federated_models(VDC,
                                         params={"project_id": project_a["id"]})
        assert data.json()["meta"]["total_count"] == 0, \
            "no federated model may be created in project A"

    def test_duplicate_discipline_in_assembly_rejected(self, api):
        """PRD §3.3: "no two members may share a discipline
        (`ERR_DUPLICATE_DISCIPLINE_IN_ASSEMBLY`)"

        Design: Corner/validations/duplicate_discipline_in_assembly_rejected
        """
        project = create_project("V4")
        partner = create_partner(project["id"])
        minimal = dict(life_safety_elements=1, life_safety_compliant=1,
                       envelope_elements=0, envelope_compliant=0,
                       finish_elements=0, finish_compliant=0)
        m1 = create_model(project["id"], partner["id"], **minimal)
        m2 = create_model(project["id"], partner["id"], **minimal)

        resp = api.create_federated_model(
            project["id"],
            create_federated_model_payload([m1["id"], m2["id"]],
                                           project["version"], label="F1"),
            VDC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DISCIPLINE_IN_ASSEMBLY)

    def test_freeze_blocked_by_member_audit_below_threshold(self, api):
        """PRD §3.3: "A `VDCManager` may freeze only from `ASSEMBLED` —
        otherwise `ERR_FED_NOT_ASSEMBLED` — and only when every member model's
        `audit_score` is at least 70.0; a member below that floor blocks the
        freeze with `ERR_MEMBER_COMPLIANCE_BELOW_THRESHOLD`."

        Design: Corner/validations/freeze_blocked_by_member_audit_below_threshold
        """
        ws = setup_accepted_model_scenario(
            "V5",
            model_kwargs=dict(life_safety_elements=10, life_safety_compliant=3,
                              envelope_elements=10, envelope_compliant=10,
                              finish_elements=10, finish_compliant=10))
        # 100 x 23/30 element-weighted; audit 100 x (0.5x0.3+0.3+0.2) = 65.0
        assert ws["model"]["submission_score"] == pytest.approx(76.7, abs=1e-6)
        assert ws["model"]["audit_score"] == pytest.approx(65.0, abs=1e-6)

        fed = create_federated_model(ws["project"]["id"], [ws["model"]["id"]])
        assert fed["status"] == "ASSEMBLED"
        resp = api.freeze_federated_model(fed["id"], VDC)
        validate_error(resp, ApiErrorId.ERR_MEMBER_COMPLIANCE_BELOW_THRESHOLD)
        assert get_fed(fed["id"])["status"] == "ASSEMBLED"

    def test_package_scope_discipline_and_fed_state_gates(self, api):
        """PRD §3.6: "The payload's `federated_model_id` must reference an
        assembly of the same project that is currently `FROZEN` — otherwise
        `ERR_FED_NOT_FROZEN` — and `scope_disciplines` must list between one
        and three unique disciplines, each with a member model in that
        assembly (`ERR_SCOPE_DISCIPLINE_NOT_IN_ASSEMBLY`)."
        PRD §3.3: "A `VDCManager` may freeze only from `ASSEMBLED` — otherwise
        `ERR_FED_NOT_ASSEMBLED`" and "What happens to the previous assembly
        depends on where it stood. A superseded assembly in `DRAFT` or
        `ASSEMBLED` simply becomes `SUPERSEDED`."
        PRD §3.7: "creates a **QuantityTakeoff** against a federated model
        that is `FROZEN` or `RELEASED` — any other state draws
        `ERR_FED_NOT_FROZEN`"

        Design: Corner/validations/package_scope_discipline_and_fed_state_gates
        """
        project = create_project("V13")
        p1 = create_partner(project["id"], company_name="StructCo")
        p2 = create_partner(project["id"], company_name="FabCo",
                            discipline="MECHANICAL", hourly_rate_cents=10000,
                            coordination_budget_hours=50.0,
                            software_platform="TEKLA")
        m1 = create_and_accept_model(project["id"], p1["id"])
        f1 = create_federated_model(project["id"], [m1["id"]], label="F1")
        assert f1["status"] == "ASSEMBLED", "never frozen in this scenario"

        # Package scope discipline absent from the assembly. The PRD does not
        # order this check against the FROZEN precondition (which also fails
        # here), so either rule's error satisfies the contract.
        e1 = api.create_fabrication_package(
            project["id"],
            create_fabrication_package_payload(f1["id"], ["ELECTRICAL"]),
            make_fabrication_lead_headers(p2["id"]))
        validate_error_is_one_of(
            e1, [ApiErrorId.ERR_SCOPE_DISCIPLINE_NOT_IN_ASSEMBLY,
                 ApiErrorId.ERR_FED_NOT_FROZEN])

        # Package against an ASSEMBLED (unfrozen) model, valid scope.
        e2 = api.create_fabrication_package(
            project["id"],
            create_fabrication_package_payload(f1["id"], ["STRUCTURAL"]),
            make_fabrication_lead_headers(p2["id"]))
        validate_error(e2, ApiErrorId.ERR_FED_NOT_FROZEN)

        # Unfreeze of an ASSEMBLED model.
        e3 = api.unfreeze_federated_model(f1["id"], VDC)
        validate_error(e3, ApiErrorId.ERR_FED_NOT_FROZEN)

        # Takeoff against an ASSEMBLED model.
        e4 = api.create_quantity_takeoff(
            project["id"],
            create_quantity_takeoff_payload(
                f1["id"], "GROSS", [make_takeoff_element("E1", 1.0, 0.0)],
                get_project(project["id"])["version"]),
            COORD)
        validate_error(e4, ApiErrorId.ERR_FED_NOT_FROZEN)

        # A second assembly over a not-yet-accepted model opens in DRAFT and
        # supersedes the current non-terminal assembly F1.
        m2 = create_model(project["id"], p2["id"], file_format="IFC",
                          life_safety_elements=1, life_safety_compliant=1,
                          envelope_elements=0, envelope_compliant=0,
                          finish_elements=0, finish_compliant=0)
        f2 = create_federated_model(project["id"], [m2["id"]], label="F2")
        assert f2["status"] == "DRAFT"
        assert get_fed(f1["id"])["status"] == "SUPERSEDED"

        e5 = api.freeze_federated_model(f2["id"], VDC)
        validate_error(e5, ApiErrorId.ERR_FED_NOT_ASSEMBLED)


class TestOptimisticConcurrency:
    def test_occ_federated_create_stale_version_rejected(self, api):
        """PRD §2.9: "If the project's current `version` differs — because the
        phase was advanced, a sweep ran, or another assembly or takeoff was
        created since that read — the request is rejected with
        `ERR_STALE_PROJECT_VERSION` (HTTP 412), and the client must re-read
        the project before retrying."
        PRD §3.3: "Assembly creation increments the project's `version` by
        one."

        Design: Corner/complexity_layers/occ_federated_create_stale_version_rejected
        """
        project = create_project("CL1")
        partner = create_partner(project["id"])
        model = create_and_accept_model(project["id"], partner["id"])
        observed = project["version"]

        f1 = validate_success(
            api.create_federated_model(
                project["id"],
                create_federated_model_payload([model["id"]], observed,
                                               label="F1"),
                VDC), 201)
        assert f1["status"] == "ASSEMBLED"

        # The first create advanced the project version; replaying the same
        # observed version is stale now.
        stale = api.create_federated_model(
            project["id"],
            create_federated_model_payload([model["id"]], observed, label="F2",
                                           target_format="NWC"),
            VDC)
        validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION)
        assert get_fed(f1["id"])["status"] == "ASSEMBLED", \
            "the rejected create did not supersede F1"
        assert get_project(project["id"])["version"] == observed + 1, \
            "exactly one increment from the single successful create"

    def test_occ_takeoff_create_stale_version_rejected(self, api):
        """PRD §2.9: "assembling a federated model and extracting a quantity
        takeoff. Each such request must carry `expected_project_version`, set
        to the project `version` the client last observed." and "the request
        is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), and the
        client must re-read the project before retrying."

        Design: Corner/complexity_layers/occ_takeoff_create_stale_version_rejected
        """
        ws = setup_frozen_assembly("CL2")
        observed = get_project(ws["project"]["id"])["version"]

        # An intervening phase advance makes the observed version stale.
        api.advance_phase(ws["project"]["id"], VDC)
        stale = api.create_quantity_takeoff(
            ws["project"]["id"],
            create_quantity_takeoff_payload(
                ws["fed"]["id"], "GROSS",
                [make_takeoff_element("E1", 1.0, 0.0)], observed),
            COORD)
        validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION)

        # Re-read and retry with the fresh version succeeds.
        fresh = get_project(ws["project"]["id"])["version"]
        created = validate_success(
            api.create_quantity_takeoff(
                ws["project"]["id"],
                create_quantity_takeoff_payload(
                    ws["fed"]["id"], "GROSS",
                    [make_takeoff_element("E1", 1.0, 0.0)], fresh),
                COORD), 201)
        assert created["status"] == "EXTRACTED"


class TestVersionPinning:
    def test_version_pinning_on_members_and_signoffs(self, api):
        """PRD §2.7: "When a federated model is assembled, each membership
        records the member model's `version` in `pinned_model_version`;
        freezing re-pins every member to its model's then-current version."
        and "every federation membership that referenced the old revision is
        re-pointed to the new revision while keeping its previously pinned
        version; the containing federated model is flagged `is_stale`"
        and "Freezing an assembly is what clears `is_stale`, by re-pinning
        every member."

        Design: Corner/complexity_layers/version_pinning_on_members_and_signoffs
        """
        project = create_project("CL3")
        p1 = create_partner(project["id"], company_name="StructCo")
        p2 = create_partner(project["id"], company_name="FabCo",
                            discipline="MECHANICAL", hourly_rate_cents=10000,
                            coordination_budget_hours=50.0,
                            software_platform="TEKLA")
        m1 = create_and_accept_model(project["id"], p1["id"])
        # M1 has been mutated three times: create (v1), submit (v2),
        # accept (v3) — PRD §2.4.
        assert m1["version"] == 3

        f1 = create_federated_model(project["id"], [m1["id"]])
        members = list_members(f1["id"])
        assert members[0]["pinned_model_version"] == 3, \
            "assembly pins the member's version at assembly time"

        f1 = freeze_fed(f1["id"])
        package = create_package(project["id"], f1["id"], ["STRUCTURAL"],
                                 p2["id"])
        submit_package_for_signoff(package["id"], p2["id"])
        signoff = list_package_signoffs(package["id"])[0]
        assert signoff["pinned_model_version"] == 3, \
            "sign-off pins the member model's version at submit-for-signoff"

        # Accept a newer STRUCTURAL revision: M1 is superseded and the member
        # is re-pointed while KEEPING the previously pinned version.
        m2 = create_model(project["id"], p1["id"], declared_lod=350)
        submit_model(m2["id"], p1["id"])
        accept_model(m2["id"])

        members = list_members(f1["id"])
        assert members[0]["trade_model_id"] == m2["id"], "member re-pointed"
        assert members[0]["pinned_model_version"] == 3, \
            "the stale pin is kept until re-freeze"
        assert get_fed(f1["id"])["is_stale"] is True

        f1 = freeze_fed(f1["id"])
        members = list_members(f1["id"])
        assert members[0]["pinned_model_version"] == get_model(m2["id"])["version"], \
            "re-freeze re-pins to the member model's current version"
        assert f1["is_stale"] is False


class TestFreezeWindows:
    def test_freeze_window_closed_interval_buffer_gap(self, api):
        """PRD §3.3: "A mandatory coordination buffer applies — relative to
        every existing window on the same assembly, a new window must begin at
        least 3,600 seconds (one hour) after the existing window ends, or end
        at least 3,600 seconds before the existing window begins. A gap of
        exactly 3,600 seconds is allowed; overlap and sub-gap adjacency alike
        are rejected with `ERR_FREEZE_WINDOW_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/freeze_window_closed_interval_buffer_gap
        """
        ws = setup_frozen_assembly("TO2")
        create_freeze_window(ws["fed"]["id"], "2026-09-10T00:00:00Z",
                             "2026-09-11T00:00:00Z", "COORDINATION_FREEZE")

        # Gap of exactly 3,600 seconds after the existing window: allowed.
        w2 = validate_success(
            api.create_freeze_window(
                ws["fed"]["id"],
                {"starts_at": "2026-09-11T01:00:00Z",
                 "ends_at": "2026-09-12T00:00:00Z",
                 "purpose": "FABRICATION_HOLD"}, VDC), 201)
        assert w2["purpose"] == "FABRICATION_HOLD"

        # Ends one second before the existing window starts: gap 3,599 s —
        # sub-gap adjacency is rejected.
        e_gap = api.create_freeze_window(
            ws["fed"]["id"],
            {"starts_at": "2026-09-09T22:00:00Z",
             "ends_at": "2026-09-09T23:59:59Z",
             "purpose": "HANDOVER_FREEZE"}, VDC)
        validate_error(e_gap, ApiErrorId.ERR_FREEZE_WINDOW_GAP_VIOLATION)

        # Direct overlap is rejected too.
        e_overlap = api.create_freeze_window(
            ws["fed"]["id"],
            {"starts_at": "2026-09-10T12:00:00Z",
             "ends_at": "2026-09-10T13:00:00Z",
             "purpose": "COORDINATION_FREEZE"}, VDC)
        validate_error(e_overlap, ApiErrorId.ERR_FREEZE_WINDOW_GAP_VIOLATION)

    def test_freeze_window_gap_allowed_on_the_early_side(self, api):
        """PRD §3.3: "A mandatory coordination buffer applies — relative to
        every existing window on the same assembly, a new window must begin at
        least 3,600 seconds (one hour) after the existing window ends, or end
        at least 3,600 seconds before the existing window begins. A gap of
        exactly 3,600 seconds is allowed; overlap and sub-gap adjacency alike
        are rejected with `ERR_FREEZE_WINDOW_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/freeze_window_closed_interval_buffer_gap
        """
        ws = setup_frozen_assembly("TO2B")
        create_freeze_window(ws["fed"]["id"], "2026-09-10T00:00:00Z",
                             "2026-09-11T00:00:00Z", "COORDINATION_FREEZE")

        # New window ends exactly 3,600 s before the existing one begins:
        # allowed (the buffer rule is symmetric).
        w_early = validate_success(
            api.create_freeze_window(
                ws["fed"]["id"],
                {"starts_at": "2026-09-09T22:00:00Z",
                 "ends_at": "2026-09-09T23:00:00Z",
                 "purpose": "HANDOVER_FREEZE"}, VDC), 201)
        assert w_early["federated_model_id"] == ws["fed"]["id"]

        # One second short of the buffer on the late side: rejected.
        e_gap = api.create_freeze_window(
            ws["fed"]["id"],
            {"starts_at": "2026-09-11T00:59:59Z",
             "ends_at": "2026-09-11T02:00:00Z",
             "purpose": "FABRICATION_HOLD"}, VDC)
        validate_error(e_gap, ApiErrorId.ERR_FREEZE_WINDOW_GAP_VIOLATION)


class TestFreezeWindowRunGate:
    def test_active_coordination_freeze_blocks_run_start(self, api):
        """PRD §3.4: "no `COORDINATION_FREEZE` freeze window on the assembly
        active at the logical clock — `ERR_FREEZE_WINDOW_ACTIVE`, while
        windows of the other two purposes never block a start."
        PRD §3.3: "Windows are closed intervals: a window is active at the
        logical clock when the clock falls on or between its two endpoints."

        Design: Corner/validations/active_coordination_freeze_blocks_run_start
        """
        ws = setup_frozen_assembly("V10")
        run = create_clash_run(ws["fed"]["id"], tolerance_mm=5.0)
        create_freeze_window(ws["fed"]["id"], "2026-09-10T00:00:00Z",
                             "2026-09-11T00:00:00Z", "COORDINATION_FREEZE")

        set_clock("2026-09-10T12:00:00Z")
        e1 = api.start_clash_run(run["id"], COORD)
        validate_error(e1, ApiErrorId.ERR_FREEZE_WINDOW_ACTIVE)

        # The window's end instant is still inside the closed interval.
        set_clock("2026-09-11T00:00:00Z")
        e2 = api.start_clash_run(run["id"], COORD)
        validate_error(e2, ApiErrorId.ERR_FREEZE_WINDOW_ACTIVE)

        # One second past the end, the start goes through.
        set_clock("2026-09-11T00:00:01Z")
        started = validate_success(api.start_clash_run(run["id"], COORD))
        assert started["status"] == "RUNNING"
