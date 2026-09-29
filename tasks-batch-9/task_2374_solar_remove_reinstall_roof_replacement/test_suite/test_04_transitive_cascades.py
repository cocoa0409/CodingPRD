"""Transitive cascades: the four-level re-permitting chain fired by a deck-finding
scope, and the three-level system-owner veto chain fired by a consent withdrawal.
"""

from test_helpers import (
    CLOCK_EPOCH,
    COORD,
    add_circuit,
    add_finding,
    add_window,
    api_client,
    assert_credit_ledger_identity,
    book_inspection,
    create_core_parties,
    create_jurisdiction,
    create_project,
    create_permit,
    decide_consent,
    decide_permit,
    deenergize_circuit,
    drive_finding,
    get_success_data,
    make_system_owner_headers,
    record_result,
    refresh_project,
    set_clock,
    setup_authorized_project,
    submit_permit,
)

SCOPE_CLOCK_UTC = "2026-08-09T09:00:00Z"
DEENERGIZE_CLOCK_UTC = "2026-08-03T09:00:00Z"
VETO_NOTE = "Asset manager withholds consent pending flashing spec"


# --------------------------------------------------------------------------
# Composite setups
# --------------------------------------------------------------------------
def _setup_approved_permit_with_passed_deck_inspection_and_critical_finding() -> dict:
    """Approved FULL_REPERMIT permit, a PASSED ROOF_DECK inspection, a CRITICAL finding.

    The jurisdiction requires re-permitting for reinstall, so the scope action on the
    CRITICAL STRUCTURAL_DEFLECTION finding is able to reopen the approved permit. The
    clock is advanced before the trigger so the re-submission stamps are distinct from
    the first submission's.
    """
    set_clock(CLOCK_EPOCH)
    jurisdiction = create_jurisdiction(
        name="Westvale AHJ",
        code="WESTVALE",
        repermit_required_for_reinstall=True,
        reinspection_required=True,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=10,
        expedite_fee_cents=0,
    )
    parties = create_core_parties()
    project = create_project(
        parties,
        ownership_model="LEASE",
        site_address="418 Mesquite Way, Tempe AZ",
        system_dc_kw=8.4,
        baseline_daily_kwh=41.75,
        downtime_days_estimated=9,
        upgrade_budget_cents=5_000_000,
    )
    permit = create_permit(
        project["id"], jurisdiction["id"], scope="FULL_REPERMIT", expedited=False
    )
    submit_permit(permit["id"])
    inspection = book_inspection(
        permit["id"],
        inspection_type="ROOF_DECK",
        slot_date="2026-08-03",
        window_start_utc="2026-08-03T15:00:00Z",
        window_end_utc="2026-08-03T17:00:00Z",
    )
    record_result(
        inspection["id"],
        jurisdiction["id"],
        "PASS",
        result_note="Deck nailing pattern acceptable",
    )
    decide_permit(permit["id"], jurisdiction["id"], "APPROVE")
    finding = add_finding(
        project["id"],
        parties["roofer"]["id"],
        finding_type="STRUCTURAL_DEFLECTION",
        severity="CRITICAL",
        affected_area_sqft=150,
        attachment_count_affected=12,
    )
    set_clock(SCOPE_CLOCK_UTC)
    return {
        "jurisdiction": jurisdiction,
        "parties": parties,
        "project": refresh_project(project["id"]),
        "permit": permit,
        "inspection": inspection,
        "finding": finding,
    }


def _setup_deenergized_lease_project_with_scheduled_window() -> dict:
    """LEASE project de-energized at 2026-08-03T09:00:00Z with one SCHEDULED window."""
    set_clock(CLOCK_EPOCH)
    ctx = setup_authorized_project(ownership_model="LEASE")
    project_id = ctx["project"]["id"]
    circuit = add_circuit(project_id, circuit_label="S1", module_count=12, dc_kw=4.92)
    window = add_window(
        project_id,
        ctx["parties"]["roofer"]["id"],
        trade="ROOFING",
        start_utc="2026-08-05T13:00:00Z",
        end_utc="2026-08-05T21:00:00Z",
    )
    set_clock(DEENERGIZE_CLOCK_UTC)
    deenergize_circuit(circuit["id"], ctx["parties"]["crew"]["id"], True)
    ctx["circuit"] = circuit
    ctx["window"] = window
    ctx["project"] = refresh_project(project_id)
    return ctx


def _read_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit_application(permit_id, COORD))


def _read_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, COORD))


def _read_approval(approval_id: str) -> dict:
    return get_success_data(api_client.get_party_approval(approval_id, COORD))


def _read_window(window_id: str) -> dict:
    return get_success_data(api_client.get_work_window(window_id, COORD))


def _read_circuit(circuit_id: str) -> dict:
    return get_success_data(api_client.get_array_circuit(circuit_id, COORD))


# --------------------------------------------------------------------------
# Depth-4: finding -> permit -> inspection -> posture
# --------------------------------------------------------------------------
class TestRepermittingCascade:
    def test_scoping_a_repermit_finding_reverts_the_approved_permit_to_submitted(self):
        """The scope action reopens the approved permit and re-prices it.

        "When the finding's `requires_repermit` is true **and** the project has a permit application in `APPROVED` **and** that permit's jurisdiction has `repermit_required_for_reinstall` set to true, that permit reverts `APPROVED → SUBMITTED`: its `revision_count` increases by one, its `reopened_by_finding_id` is set to this finding's identifier, its `submitted_at` is stamped with the current instant, its `fee_cents` is recomputed by the permit fee rule of §3.7, and its `review_deadline_utc` is recomputed as the new `submitted_at` plus the jurisdiction's `permit_review_days` whole days."

        Design: Difficulty/transitive_cascade/critical_structural_scoping_reopens_permit_invalidates_inspection_and_downgrades_posture
        """
        ctx = _setup_approved_permit_with_passed_deck_inspection_and_critical_finding()
        finding_id = ctx["finding"]["id"]
        roofer_id = ctx["parties"]["roofer"]["id"]

        finding = drive_finding(finding_id, roofer_id, "SCOPE")

        assert finding["status"] == "UPGRADE_SCOPED", (
            f"scoping takes an OPEN finding to UPGRADE_SCOPED, got {finding['status']}"
        )
        assert finding["requires_repermit"] is True, (
            "a CRITICAL STRUCTURAL_DEFLECTION finding requires re-permitting"
        )
        assert finding["upgrade_cost_cents"] == 368800, (
            f"expected upgrade_cost_cents 368800, got {finding['upgrade_cost_cents']}"
        )

        permit = _read_permit(ctx["permit"]["id"])
        assert permit["status"] == "SUBMITTED", (
            f"the reopened permit reverts APPROVED -> SUBMITTED, got {permit['status']}"
        )
        assert permit["revision_count"] == 1, (
            f"the reopening increments revision_count to 1, got {permit['revision_count']}"
        )
        assert permit["reopened_by_finding_id"] == finding_id, (
            f"reopened_by_finding_id must name the scoping finding, "
            f"got {permit['reopened_by_finding_id']}"
        )
        assert permit["fee_cents"] == 88140, (
            f"expected the recomputed fee_cents 88140, got {permit['fee_cents']}"
        )
        assert permit["submitted_at"] == "2026-08-09T09:00:00.000Z", (
            f"submitted_at is re-stamped with the current instant, "
            f"got {permit['submitted_at']}"
        )
        assert permit["review_deadline_utc"] == "2026-08-19T09:00:00.000Z", (
            f"review_deadline_utc is submitted_at plus permit_review_days, "
            f"got {permit['review_deadline_utc']}"
        )

    def test_reopened_permit_invalidates_the_passed_deck_inspection_and_restricts_posture(self):
        """The chain reaches the inspection and then the project's derived posture.

        "Because that permit left `APPROVED`, every inspection under it whose `status` is `PASSED` and whose `inspection_type` is `ROOF_DECK` or `MOUNTING` is invalidated to `CORRECTION_REQUIRED` with its `attempt_number` increased by one."

        Design: Difficulty/transitive_cascade/critical_structural_scoping_reopens_permit_invalidates_inspection_and_downgrades_posture
        """
        ctx = _setup_approved_permit_with_passed_deck_inspection_and_critical_finding()
        project_id = ctx["project"]["id"]

        assert ctx["project"]["posture"] == "FROZEN", (
            f"an OPEN CRITICAL finding freezes the project before the scope, "
            f"got {ctx['project']['posture']}"
        )

        drive_finding(ctx["finding"]["id"], ctx["parties"]["roofer"]["id"], "SCOPE")

        inspection = _read_inspection(ctx["inspection"]["id"])
        assert inspection["status"] == "CORRECTION_REQUIRED", (
            f"the PASSED ROOF_DECK inspection is invalidated, got {inspection['status']}"
        )
        assert inspection["attempt_number"] == 2, (
            f"attempt_number is increased by one, got {inspection['attempt_number']}"
        )

        project = refresh_project(project_id)
        assert project["posture"] == "RESTRICTED", (
            f"the now-SUBMITTED re-permit and invalidated inspection restrict the "
            f"project, got {project['posture']}"
        )
        assert project["open_critical_finding_count"] == 0, (
            f"the scoped finding is no longer OPEN, "
            f"got {project['open_critical_finding_count']}"
        )
        assert project["scoped_upgrade_cost_cents"] == 368800, (
            f"expected scoped_upgrade_cost_cents 368800, "
            f"got {project['scoped_upgrade_cost_cents']}"
        )


# --------------------------------------------------------------------------
# Depth-3: consent -> project money/round -> siblings and windows
# --------------------------------------------------------------------------
class TestSystemOwnerVetoCascade:
    def test_veto_on_a_deenergized_project_moves_reserved_credit_into_released(self):
        """The veto compensates the money without changing the authorized total.

        "The same veto landing on a project already in `DEENERGIZED` does all of that **and** compensates the money: the whole of `credit_reserved_cents` is moved into `credit_released_cents`, `credit_reserved_cents` becomes zero, and `credit_authorized_cents` is left unchanged."

        Design: Difficulty/transitive_cascade/system_owner_veto_unwinds_consents_reserved_credit_and_scheduled_windows
        """
        ctx = _setup_deenergized_lease_project_with_scheduled_window()
        project_id = ctx["project"]["id"]

        assert ctx["project"]["phase"] == "DEENERGIZED", (
            f"the isolated circuit carries the project to DEENERGIZED, "
            f"got {ctx['project']['phase']}"
        )
        assert ctx["project"]["credit_reserved_cents"] == 5261, (
            f"the provisional credit 5261 cents must be reserved before the veto, "
            f"got {ctx['project']['credit_reserved_cents']}"
        )

        decide_consent(
            ctx["approvals"]["sysowner"]["id"],
            "REQUEST_CHANGES",
            make_system_owner_headers(ctx["parties"]["sysowner"]["id"]),
            decision_note=VETO_NOTE,
        )

        project = refresh_project(project_id)
        assert project["phase"] == "APPROVALS_OPEN", (
            f"the veto withdraws authorization, got phase {project['phase']}"
        )
        assert project["negotiation_round"] == 2, (
            f"the veto increments the negotiation round, "
            f"got {project['negotiation_round']}"
        )
        assert project["credit_authorized_cents"] == 5261, (
            f"credit_authorized_cents is left unchanged, "
            f"got {project['credit_authorized_cents']}"
        )
        assert project["credit_reserved_cents"] == 0, (
            f"credit_reserved_cents becomes zero, "
            f"got {project['credit_reserved_cents']}"
        )
        assert project["credit_released_cents"] == 5261, (
            f"the whole reserved balance moves into credit_released_cents, "
            f"got {project['credit_released_cents']}"
        )
        assert project["credit_settled_cents"] == 0, (
            f"nothing is settled by a veto, got {project['credit_settled_cents']}"
        )
        assert_credit_ledger_identity(project)

    def test_veto_resets_sibling_consents_and_revokes_windows_leaving_circuits_isolated(self):
        """The schedule unwinds while the physical isolation deliberately does not.

        "Physically nothing unwinds — the circuits stay `ISOLATED` — only the money and the schedule do."

        Design: Difficulty/transitive_cascade/system_owner_veto_unwinds_consents_reserved_credit_and_scheduled_windows
        """
        ctx = _setup_deenergized_lease_project_with_scheduled_window()
        approvals = ctx["approvals"]

        decide_consent(
            approvals["sysowner"]["id"],
            "REQUEST_CHANGES",
            make_system_owner_headers(ctx["parties"]["sysowner"]["id"]),
            decision_note=VETO_NOTE,
        )

        sysowner_approval = _read_approval(approvals["sysowner"]["id"])
        assert sysowner_approval["status"] == "CHANGES_REQUESTED", (
            f"the vetoing record moves to CHANGES_REQUESTED, "
            f"got {sysowner_approval['status']}"
        )
        assert sysowner_approval["veto_flag"] is True, (
            "a SYSTEM_OWNER change request raises veto_flag"
        )

        roofer_approval = _read_approval(approvals["roofer"]["id"])
        assert roofer_approval["status"] == "PENDING", (
            f"the roofer's consent resets to PENDING, got {roofer_approval['status']}"
        )
        assert roofer_approval["round_recorded"] == 2, (
            f"the reset roofer consent carries the new round, "
            f"got {roofer_approval['round_recorded']}"
        )

        owner_approval = _read_approval(approvals["owner"]["id"])
        assert owner_approval["status"] == "PENDING", (
            f"the solar owner's consent resets to PENDING, "
            f"got {owner_approval['status']}"
        )
        assert owner_approval["round_recorded"] == 2, (
            f"the reset solar-owner consent carries the new round, "
            f"got {owner_approval['round_recorded']}"
        )

        window = _read_window(ctx["window"]["id"])
        assert window["status"] == "REVOKED", (
            f"every SCHEDULED crew window of the project is revoked, "
            f"got {window['status']}"
        )

        circuit = _read_circuit(ctx["circuit"]["id"])
        assert circuit["status"] == "ISOLATED", (
            f"the circuit stays ISOLATED across the veto, got {circuit['status']}"
        )
