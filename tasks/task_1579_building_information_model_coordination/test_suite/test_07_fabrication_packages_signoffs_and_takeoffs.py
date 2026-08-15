"""Fabrication packages: the sign-off lifecycle, void/release lockdown,
segregation of duties, the accept-triggered revocation cascade, the sign-off
slot conservation invariant, and quantity-takeoff extraction variants."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_model,
    advance_phase_to,
    approve_takeoff,
    create_and_accept_model,
    create_model,
    create_federated_model,
    create_package,
    create_partner,
    create_project,
    create_takeoff,
    decline_signoff,
    freeze_fed,
    get_fed,
    get_model,
    get_package,
    get_project,
    get_signoff,
    get_takeoff,
    list_members,
    list_package_signoffs,
    make_fabrication_lead_headers,
    make_lead_engineer_headers,
    make_takeoff_element,
    release_fed,
    release_package,
    setup_frozen_assembly,
    setup_package_in_signoff,
    setup_ready_package,
    setup_two_member_ready_package,
    sign_signoff,
    submit_model,
    submit_package_for_signoff,
    unfreeze_fed,
    validate_error,
    validate_paginated,
    void_package,
)

VDC = TEST_USERS["vdc_manager_headers"]
ENG = TEST_USERS["lead_engineer_headers"]  # operator "eng-1"


class TestSignOffLifecycle:
    def test_package_signoff_lifecycle_and_state_gates(self, api):
        """PRD §3.6: "From `DRAFT` it moves the package to
        `SIGNOFF_IN_PROGRESS` and creates one **SignOff** per scope discipline
        in `REQUESTED`, each recorded under its package through
        `fabrication_package_id` and pinned to the federated member model of
        its discipline at that moment — captured as the sign-off's
        `trade_model_id` — and to that model's current version in
        `pinned_model_version`."
        PRD §3.6: "The package must be `READY_FOR_RELEASE`
        (`ERR_PACKAGE_NOT_RELEASABLE`)"
        PRD §3.6: "when the count reaches `required_signoff_count`, the
        package advances on its own from `SIGNOFF_IN_PROGRESS` to
        `READY_FOR_RELEASE`."
        PRD §3.6: "From any other package state the action is rejected with
        `ERR_PACKAGE_NOT_DRAFT`."

        Design: Corner/state_machines/package_signoff_lifecycle_and_state_gates
        """
        ws = setup_package_in_signoff("SM11", scope=("STRUCTURAL",))
        package = ws["package"]
        signoff = ws["signoffs"][0]
        fab = make_fabrication_lead_headers(ws["fabricator"]["id"])

        assert package["status"] == "SIGNOFF_IN_PROGRESS"
        assert signoff["status"] == "REQUESTED"
        assert signoff["trade_model_id"] == ws["model"]["id"]
        # The member model has been mutated three times (create, submit,
        # accept), so its version — and the pin — is 3 (PRD §2.4).
        assert signoff["pinned_model_version"] == 3
        assert len(ws["signoffs"]) == 1

        # Release is gated on READY_FOR_RELEASE.
        e1 = api.release_fabrication_package(package["id"], fab)
        validate_error(e1, ApiErrorId.ERR_PACKAGE_NOT_RELEASABLE)

        # Decline, then re-request: the same sign-off row returns to
        # REQUESTED — no duplicate rows are created.
        declined = decline_signoff(signoff["id"])
        assert declined["status"] == "DECLINED"
        assert get_package(package["id"])["status"] == "SIGNOFF_IN_PROGRESS"

        submit_package_for_signoff(package["id"], ws["fabricator"]["id"])
        assert get_signoff(signoff["id"])["status"] == "REQUESTED"
        assert len(list_package_signoffs(package["id"])) == 1

        signed = sign_signoff(signoff["id"])
        assert signed["status"] == "SIGNED"
        assert signed["signer_user_id"] == "eng-1"

        package = get_package(package["id"])
        assert package["signed_count"] == 1
        assert package["required_signoff_count"] == 1
        assert package["status"] == "READY_FOR_RELEASE", \
            "the last sign auto-advances the package"

        # submit-for-signoff from READY_FOR_RELEASE is no longer a re-request.
        e2 = api.submit_package_for_signoff(package["id"], fab)
        validate_error(e2, ApiErrorId.ERR_PACKAGE_NOT_DRAFT)

    def test_package_void_revokes_signoffs_and_final_lockdown(self, api):
        """PRD §3.6: "from `DRAFT`, `SIGNOFF_IN_PROGRESS`, or
        `READY_FOR_RELEASE` — a `RELEASED` or already-`VOID` package rejects
        the attempt with `ERR_PACKAGE_ALREADY_FINAL` — the owning
        `FabricationLead` moves the package to its terminal `VOID` state, and
        every sign-off not already `REVOKED` becomes `REVOKED`."
        PRD §3.6: "the sign-off must be `REQUESTED`
        (`ERR_SIGNOFF_NOT_REQUESTED`)"

        Design: Corner/state_machines/package_void_revokes_signoffs_and_final_lockdown
        """
        ws = setup_frozen_assembly("SM12")
        pid = ws["project"]["id"]
        fabricator = create_partner(pid, company_name="FabCo",
                                    discipline="MECHANICAL",
                                    hourly_rate_cents=10000,
                                    coordination_budget_hours=50.0,
                                    software_platform="TEKLA")

        # PKG1 is voided mid-signoff.
        pkg1 = create_package(pid, ws["fed"]["id"], ["STRUCTURAL"],
                              fabricator["id"])
        submit_package_for_signoff(pkg1["id"], fabricator["id"])
        so1 = list_package_signoffs(pkg1["id"])[0]
        voided = void_package(pkg1["id"], fabricator["id"])
        assert voided["status"] == "VOID"
        assert get_signoff(so1["id"])["status"] == "REVOKED"

        # A revoked sign-off is no longer answerable.
        e1 = api.sign_signoff(so1["id"], ENG)
        validate_error(e1, ApiErrorId.ERR_SIGNOFF_NOT_REQUESTED)

        # PKG2 runs the full release path (phase CONSTRUCTION_DOCUMENTS, CRI
        # 100, posture NORMAL, assembly FROZEN).
        advance_phase_to(pid, "CONSTRUCTION_DOCUMENTS")
        pkg2 = create_package(pid, ws["fed"]["id"], ["STRUCTURAL"],
                              fabricator["id"])
        submit_package_for_signoff(pkg2["id"], fabricator["id"])
        so2 = list_package_signoffs(pkg2["id"])[0]
        sign_signoff(so2["id"])
        released = release_package(pkg2["id"], fabricator["id"])
        assert released["status"] == "RELEASED"

        # RELEASED is terminal for voiding.
        e2 = api.void_fabrication_package(
            pkg2["id"], make_fabrication_lead_headers(fabricator["id"]))
        validate_error(e2, ApiErrorId.ERR_PACKAGE_ALREADY_FINAL)
        assert get_package(pkg2["id"])["status"] == "RELEASED"

    def test_sod_signoff_author_conflict_rejected(self, api):
        """PRD §3.6: "the sign-off must be `REQUESTED`
        (`ERR_SIGNOFF_NOT_REQUESTED`), and segregation of duties forbids the
        engineer from judging their own submission — a caller whose
        `X-User-ID` equals the pinned model's `submitted_by_user_id` is
        rejected with `ERR_SOD_SIGNOFF_AUTHOR_CONFLICT`."

        Design: Corner/rbac/sod_signoff_author_conflict_rejected
        """
        ws = setup_package_in_signoff("RB4", scope=("STRUCTURAL",))
        signoff = ws["signoffs"][0]
        # The pinned model was submitted with X-User-ID == the authoring
        # partner's id; a caller carrying that id may not sign.
        e1 = api.sign_signoff(signoff["id"],
                              make_lead_engineer_headers(ws["author"]["id"]))
        validate_error(e1, ApiErrorId.ERR_SOD_SIGNOFF_AUTHOR_CONFLICT)
        assert get_signoff(signoff["id"])["status"] == "REQUESTED"

        signed = sign_signoff(signoff["id"], engineer_id="eng-1")
        assert signed["status"] == "SIGNED"


class TestSignOffSlotConservation:
    def test_sign_revoke_rerequest_conserves_signoff_slots(self, api):
        """PRD §3.6: "Revocation is never a manual act. A `SIGNED` sign-off
        becomes `REVOKED` when the federated model it pins leaves `FROZEN`"
        PRD §3.6: "From `SIGNOFF_IN_PROGRESS` the same action is a re-request:
        every sign-off in `DECLINED` or `REVOKED` returns to `REQUESTED`,
        while `SIGNED` sign-offs are left untouched."
        PRD §3.6: "sets `required_signoff_count` to the number of scope
        disciplines"

        Design: Difficulty/compensating_invariant/sign_revoke_rerequest_conserves_signoff_slots
        """
        ws = setup_two_member_ready_package("CI2")
        package = ws["package"]
        assert package["status"] == "READY_FOR_RELEASE"
        assert package["signed_count"] == 2
        assert package["required_signoff_count"] == 2

        # Compensating action: unfreeze revokes both SIGNED sign-offs.
        unfreeze_fed(ws["fed"]["id"])
        package = get_package(package["id"])
        assert package["status"] == "SIGNOFF_IN_PROGRESS"
        assert package["signed_count"] == 0
        signoffs = list_package_signoffs(package["id"])
        assert len(signoffs) == 2, "no sign-off row is created or destroyed"
        assert {s["status"] for s in signoffs} == {"REVOKED"}

        # Re-request restores the slots to REQUESTED.
        submit_package_for_signoff(package["id"], ws["fabricator"]["id"])
        signoffs = list_package_signoffs(package["id"])
        assert len(signoffs) == 2
        assert {s["status"] for s in signoffs} == {"REQUESTED"}
        assert get_package(package["id"])["required_signoff_count"] == 2

    def test_rerequest_restores_declined_but_leaves_signed(self, api):
        """PRD §3.6: "From `SIGNOFF_IN_PROGRESS` the same action is a
        re-request: every sign-off in `DECLINED` or `REVOKED` returns to
        `REQUESTED`, while `SIGNED` sign-offs are left untouched."

        Design: Difficulty/compensating_invariant/sign_revoke_rerequest_conserves_signoff_slots
        """
        project = create_project("CI2B")
        p1 = create_partner(project["id"], company_name="StructCo",
                            discipline="STRUCTURAL", hourly_rate_cents=12000,
                            coordination_budget_hours=100.0,
                            software_platform="REVIT")
        p2 = create_partner(project["id"], company_name="FabCo",
                            discipline="MECHANICAL", hourly_rate_cents=10000,
                            coordination_budget_hours=50.0,
                            software_platform="TEKLA")
        m1 = create_and_accept_model(project["id"], p1["id"])
        m3 = create_and_accept_model(project["id"], p2["id"], file_format="IFC")
        fed = create_federated_model(project["id"], [m1["id"], m3["id"]])
        freeze_fed(fed["id"])
        package = create_package(project["id"], fed["id"],
                                 ["STRUCTURAL", "MECHANICAL"], p2["id"])
        submit_package_for_signoff(package["id"], p2["id"])
        so_a, so_b = list_package_signoffs(package["id"])

        sign_signoff(so_a["id"], engineer_id="eng-2")
        decline_signoff(so_b["id"], engineer_id="eng-2")
        package = get_package(package["id"])
        assert package["status"] == "SIGNOFF_IN_PROGRESS", \
            "1 of 2 signed: the package has not reached READY_FOR_RELEASE"
        assert package["signed_count"] == 1

        submit_package_for_signoff(package["id"], p2["id"])
        signoffs = {s["id"]: s["status"]
                    for s in list_package_signoffs(package["id"])}
        assert len(signoffs) == 2, "the slot pool is conserved"
        assert signoffs[so_a["id"]] == "SIGNED", "SIGNED sign-offs untouched"
        assert signoffs[so_b["id"]] == "REQUESTED", "DECLINED re-requested"
        assert get_package(package["id"])["signed_count"] == 1


class TestAcceptCascade:
    def test_accept_supersede_unfreeze_revoke_regress_chain(self, api):
        """PRD §3.2: "When the project already holds an `ACCEPTED` revision of
        the same discipline, that earlier revision becomes `SUPERSEDED` and
        the newly accepted revision's `supersedes_model_id` points back at it
        (link 1)."
        PRD §3.2: "Every federation membership referencing the earlier
        revision is re-pointed to the new one while keeping the version it had
        pinned; each containing federated model is flagged `is_stale`, one
        that was `FROZEN` falls back to `ASSEMBLED`, and assemblies in
        `DRAFT`, `ASSEMBLED`, or `RELEASED` keep their status (link 2)."
        PRD §3.2: "On each federated model that left `FROZEN` this way, every
        `SIGNED` sign-off belonging to a fabrication package that pins that
        federated model is revoked to `REVOKED` (link 3)."
        PRD §3.2: "Each package whose `signed_count` thereby drops below its
        `required_signoff_count` regresses from `READY_FOR_RELEASE` to
        `SIGNOFF_IN_PROGRESS` (link 4)."

        Design: Difficulty/transitive_cascade/accept_supersede_unfreeze_revoke_regress_chain
        """
        ws = setup_ready_package("TC1", scope=("STRUCTURAL",))
        assert ws["package"]["status"] == "READY_FOR_RELEASE"
        signoff_id = ws["signoffs"][0]["id"]
        m1_id = ws["model"]["id"]

        # The trigger: a second STRUCTURAL revision is accepted.
        m2 = create_model(ws["project"]["id"], ws["author"]["id"],
                          declared_lod=350)
        submit_model(m2["id"], ws["author"]["id"])
        accept_model(m2["id"])

        # Link 1: supersession with a back-pointer.
        assert get_model(m1_id)["status"] == "SUPERSEDED"
        assert get_model(m2["id"])["supersedes_model_id"] == m1_id

        # Link 2: member re-pointed; the frozen assembly falls back and is
        # flagged stale.
        fed = get_fed(ws["fed"]["id"])
        assert fed["status"] == "ASSEMBLED"
        assert fed["is_stale"] is True
        members = list_members(ws["fed"]["id"])
        assert members[0]["trade_model_id"] == m2["id"]

        # Link 3: the SIGNED sign-off on the package pinning that assembly is
        # revoked.
        assert get_signoff(signoff_id)["status"] == "REVOKED"

        # Link 4: the package regresses below its required count.
        package = get_package(ws["package"]["id"])
        assert package["status"] == "SIGNOFF_IN_PROGRESS"
        assert package["signed_count"] == 0

    def test_supersession_chain_walked_via_listing_filters(self, api):
        """PRD §3.2: "Revisions are listable with `project_id`,
        `trade_partner_id`, `supersedes_model_id`, `status`, and `discipline`
        filters — the way a supersession chain is walked."

        Design: Difficulty/transitive_cascade/accept_supersede_unfreeze_revoke_regress_chain
        """
        ws = setup_ready_package("TC1B", scope=("STRUCTURAL",))
        m1_id = ws["model"]["id"]
        m2 = create_model(ws["project"]["id"], ws["author"]["id"],
                          declared_lod=350)
        submit_model(m2["id"], ws["author"]["id"])
        accept_model(m2["id"])

        # The forward hop: which revision supersedes M1?
        data, meta = validate_paginated(api.list_trade_models(
            VDC, params={"project_id": ws["project"]["id"],
                         "supersedes_model_id": m1_id}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == m2["id"]

        # The retired hop is found by its terminal status.
        data, meta = validate_paginated(api.list_trade_models(
            VDC, params={"project_id": ws["project"]["id"],
                         "status": "SUPERSEDED"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == m1_id


class TestReleasePhaseGate:
    def test_fabrication_release_too_early_phase_rejected(self, api):
        """PRD §3.6: "the project phase must be `CONSTRUCTION_DOCUMENTS` or
        `CONSTRUCTION_ADMINISTRATION` (`ERR_PHASE_TOO_EARLY_FOR_FABRICATION`)."

        Design: Corner/validations/fabrication_release_too_early_phase_rejected
        """
        ws = setup_ready_package("V8", scope=("STRUCTURAL",))
        assert get_project(ws["project"]["id"])["current_phase"] == "SCHEMATIC_DESIGN"
        fab = make_fabrication_lead_headers(ws["fabricator"]["id"])

        e1 = api.release_fabrication_package(ws["package"]["id"], fab)
        validate_error(e1, ApiErrorId.ERR_PHASE_TOO_EARLY_FOR_FABRICATION)

        advance_phase_to(ws["project"]["id"], "CONSTRUCTION_DOCUMENTS")
        released = release_package(ws["package"]["id"], ws["fabricator"]["id"])
        assert released["status"] == "RELEASED", \
            "the identical call succeeds once the phase gate passes"


class TestTakeoffExtraction:
    def test_takeoff_net_per_element_rounding_order(self, api):
        """PRD §3.7: "Under `GROSS`, the gross quantities are summed and the
        sum is rounded half-up to three decimals, with deductions ignored.
        Under `NET`, each element's net — its gross minus its deduction — is
        rounded half-up to three decimals first, and those per-element nets
        are then summed with no second rounding; summing the raw nets and
        rounding once at the end is a different, rejected interpretation."

        Design: Difficulty/combinatorial_formula/takeoff_net_per_element_rounding_order
        """
        ws = setup_frozen_assembly("CF2")
        elements = [make_takeoff_element("E1", 0.1235, 0.0),
                    make_takeoff_element("E2", 0.1235, 0.0)]

        # NET rounds each element first: round_half_up(0.1235, 3) = 0.124,
        # then sums: 0.248. The rejected sum-then-round order gives 0.247.
        t_net = create_takeoff(ws["project"]["id"], ws["fed"]["id"], "NET",
                               elements)
        assert t_net["total_quantity"] == pytest.approx(0.248, abs=1e-6)
        assert t_net["status"] == "EXTRACTED"

        # GROSS on the same elements: single final rounding of 0.2470.
        t_gross = create_takeoff(ws["project"]["id"], ws["fed"]["id"], "GROSS",
                                 elements)
        assert t_gross["total_quantity"] == pytest.approx(0.247, abs=1e-6)
        assert t_gross["status"] == "EXTRACTED"
        assert abs(t_net["total_quantity"]
                   - t_gross["total_quantity"]) > 1e-6, \
            "the two variants disagree on identical inputs"

    def test_gross_ignores_deductions_and_counts_elements(self, api):
        """PRD §3.7: "Under `GROSS`, the gross quantities are summed and the
        sum is rounded half-up to three decimals, with deductions ignored."
        PRD §3.7: "The takeoff's `element_count` is the number of supplied
        elements."

        Design: Difficulty/combinatorial_formula/takeoff_net_per_element_rounding_order
        """
        ws = setup_frozen_assembly("CF2B")
        elements = [make_takeoff_element("E1", 2.0, 0.5),
                    make_takeoff_element("E2", 1.25, 0.25)]

        t_gross = create_takeoff(ws["project"]["id"], ws["fed"]["id"], "GROSS",
                                 elements)
        assert t_gross["total_quantity"] == pytest.approx(3.25, abs=1e-6), \
            "2.0 + 1.25; deductions ignored under GROSS"
        assert t_gross["element_count"] == 2

        t_net = create_takeoff(ws["project"]["id"], ws["fed"]["id"], "NET",
                               elements)
        assert t_net["total_quantity"] == pytest.approx(2.5, abs=1e-6), \
            "(2.0 - 0.5) + (1.25 - 0.25), per-element nets then summed"

    def test_takeoff_supersede_and_approve_gates(self, api):
        """PRD §3.7: "Approval belongs to the `VDCManager` and requires the
        takeoff `EXTRACTED` (`ERR_TAKEOFF_NOT_EXTRACTED`) and its federated
        model `RELEASED` (`ERR_FED_NOT_RELEASED`)"
        PRD §3.7: "Creating the takeoff supersedes any existing takeoff of the
        same `federated_model_id`, `extraction_mode`, and `discipline_filter`,
        whether that predecessor is `EXTRACTED` or `APPROVED`; the new takeoff
        opens in `EXTRACTED`"

        Design: Corner/state_machines/takeoff_supersede_and_approve_gates
        """
        ws = setup_frozen_assembly("SM14")
        t1 = create_takeoff(ws["project"]["id"], ws["fed"]["id"], "NET",
                            [make_takeoff_element("E1", 2.0, 0.5)])
        assert t1["status"] == "EXTRACTED"
        assert t1["total_quantity"] == pytest.approx(1.5, abs=1e-6), \
            "round_half_up(2.0 - 0.5, 3)"

        # Approval while the assembly is merely FROZEN.
        e1 = api.approve_quantity_takeoff(t1["id"], VDC)
        validate_error(e1, ApiErrorId.ERR_FED_NOT_RELEASED)

        release_fed(ws["fed"]["id"])
        approved = approve_takeoff(t1["id"])
        assert approved["status"] == "APPROVED"

        # A new takeoff with the same (federated_model_id, extraction_mode,
        # discipline_filter) key supersedes the APPROVED predecessor.
        t2 = create_takeoff(ws["project"]["id"], ws["fed"]["id"], "NET",
                            [make_takeoff_element("E1", 3.0, 1.0)])
        assert t2["status"] == "EXTRACTED"
        assert get_takeoff(t1["id"])["status"] == "SUPERSEDED"

        # A superseded takeoff can no longer be approved.
        e2 = api.approve_quantity_takeoff(t1["id"], VDC)
        validate_error(e2, ApiErrorId.ERR_TAKEOFF_NOT_EXTRACTED)
