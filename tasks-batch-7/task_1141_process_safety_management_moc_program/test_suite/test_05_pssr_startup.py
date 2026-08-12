"""PSSR lifecycle and the startup-authorization gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_pssr,
    begin_pssr_fieldwork,
    classify,
    create_pssr_for_moc,
    create_pssr_payload,
    create_standard_actors,
    drive_moc_to_implemented,
    get_moc,
    get_pssr,
    list_moc_pssrs,
    make_pssr_lead_headers,
    moc_version,
    new_draft_moc,
    new_personnel,
    setup_implemented_scenario,
    setup_unit_with_study,
    validate_error,
    validate_success,
    verify_item,
    work_item_to_submitted,
)

MANAGER = TEST_USERS["manager_headers"]


class TestStartupAuthorizationGate:
    def test_authorize_without_approved_pssr_rejected(self, api):
        """PRD §3.5: "when `requires_pssr` holds, a linked PSSR in `APPROVED`
        status must exist (`ERR_PSSR_NOT_APPROVED`)" — a PERMANENT MOC always has
        requires_pssr true (PRD §3.2), and no PSSR exists yet here.

        Design: Difficulty/cross_entity_state_dependency/authorize_requires_pssr_approved
        """
        unit, study, actors, moc = setup_implemented_scenario(change_class="PERMANENT")
        resp = api.authorize_startup(moc["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_PSSR_NOT_APPROVED.value)
        assert get_moc(moc["id"])["status"] == "IMPLEMENTED_PSSR_PENDING"

    def test_authorize_after_pssr_approval_succeeds(self, api):
        """PRD §3.5: "Passing all three moves the MOC to `STARTUP_AUTHORIZED`" —
        once the linked PSSR stands APPROVED, the same authorize call succeeds.

        Design: Difficulty/cross_entity_state_dependency/authorize_requires_pssr_approved
        """
        unit, study, actors, moc = setup_implemented_scenario(change_class="PERMANENT")
        pssr = create_pssr_for_moc(moc["id"], actors["lead"]["id"])
        begin_pssr_fieldwork(pssr["id"], actors["lead"]["id"])
        approve_pssr(pssr["id"], actors["lead"]["id"])
        assert get_pssr(pssr["id"])["status"] == "APPROVED"

        authorized = validate_success(api.authorize_startup(moc["id"], MANAGER), 200)
        assert authorized["status"] == "STARTUP_AUTHORIZED"


class TestPssrApproveReject:
    def test_pssr_approve_with_open_punch_returns_error(self, api):
        """PRD §3.5: "Approval carries three further gates: the lead must not be
        the MOC's requester (`ERR_SOD_PSSR_LEAD_IS_REQUESTER`), `punch_open_count`
        must be zero (`ERR_PSSR_OPEN_PUNCH_ITEMS`), and the MOC must currently
        stand in `IMPLEMENTED_PSSR_PENDING` (`ERR_MOC_INVALID_STATE`)."

        Design: Corner/state_machines/pssr_approve_with_open_punch_returns_error
        """
        unit, study, actors, moc = setup_implemented_scenario(change_class="PERMANENT")
        pssr = create_pssr_for_moc(moc["id"], actors["lead"]["id"])
        begin_pssr_fieldwork(pssr["id"], actors["lead"]["id"])
        resp = api.create_punch_item(pssr["id"],
                                     {"title": "fix sign", "priority": "P2",
                                      "assignee_id": actors["req"]["id"]},
                                     make_pssr_lead_headers(actors["lead"]["id"]))
        validate_success(resp, 201)

        denied = api.approve_pssr(pssr["id"], make_pssr_lead_headers(actors["lead"]["id"]))
        validate_error(denied, ApiErrorId.ERR_PSSR_OPEN_PUNCH_ITEMS.value)
        after = get_pssr(pssr["id"])
        assert after["status"] == "PUNCH_LIST"
        assert after["punch_open_count"] == 1

    def test_pssr_reject_returns_moc_to_implementation(self, api):
        """PRD §3.5: "Rejection needs no such gates beyond state and ownership,
        lands in `REJECTED`, and pushes the MOC backward from
        `IMPLEMENTED_PSSR_PENDING` to `APPROVED_IMPLEMENTATION` — the change must
        re-clear mark-implemented before startup can be sought again."

        Design: Corner/state_machines/pssr_reject_returns_moc_to_implementation
        """
        unit, study, actors, moc = setup_implemented_scenario(change_class="PERMANENT")
        pssr = create_pssr_for_moc(moc["id"], actors["lead"]["id"])
        begin_pssr_fieldwork(pssr["id"], actors["lead"]["id"])

        rejected = validate_success(
            api.reject_pssr(pssr["id"], make_pssr_lead_headers(actors["lead"]["id"])), 200)
        assert rejected["status"] == "REJECTED"
        assert get_moc(moc["id"])["status"] == "APPROVED_IMPLEMENTATION", (
            "PSSR rejection must push the MOC backward to APPROVED_IMPLEMENTATION"
        )


class TestPunchItems:
    def test_punch_item_moves_pssr_to_punch_list(self, api):
        """PRD §3.5: "every punch item spawns an action item in `OPEN` status with
        `source_type` `PSSR` sourced to this review and due per its priority SLA,
        increments the review's `punch_open_count` and the unit's
        `open_action_count`, and recomputes the unit index. The first punch item
        moves the review from `IN_FIELD` to `PUNCH_LIST`." At the default clock a
        P1 SLA is thirty days (PRD §3.9): due 2026-05-31.

        Design: Corner/endpoints/punch_item_moves_pssr_to_punch_list
        """
        unit, study, actors, moc = setup_implemented_scenario(change_class="PERMANENT")
        pssr = create_pssr_for_moc(moc["id"], actors["lead"]["id"])
        begin_pssr_fieldwork(pssr["id"], actors["lead"]["id"])

        resp = api.create_punch_item(pssr["id"],
                                     {"title": "Missing guard rail", "priority": "P1",
                                      "assignee_id": actors["req"]["id"]},
                                     make_pssr_lead_headers(actors["lead"]["id"]))
        punch = validate_success(resp, 201)
        assert punch["source_type"] == "PSSR"
        assert punch["source_id"] == pssr["id"]
        assert punch["priority"] == "P1"
        assert punch["status"] == "OPEN"
        assert punch["due_date"] == "2026-05-31T00:00:00Z", (
            f"P1 SLA from the 2026-05-01 default clock must be 2026-05-31, got {punch['due_date']}"
        )

        after = get_pssr(pssr["id"])
        assert after["status"] == "PUNCH_LIST"
        assert after["punch_open_count"] == 1

    def test_punch_count_reconciles_after_verify(self, api):
        """PRD §3.9: "a `PSSR` item decrements its review's `punch_open_count`" —
        after the punch item is verified closed the count reconciles to zero and
        the gate of PRD §3.5 ("`punch_open_count` must be zero") opens.
        PRD §3.5: "An approved review stamps `approved_at` and lands in
        `APPROVED`."

        Design: Corner/cross_cutting_complexity_layers/punch_count_reconciles_after_verify
        """
        unit, study, actors, moc = setup_implemented_scenario(change_class="PERMANENT")
        pssr = create_pssr_for_moc(moc["id"], actors["lead"]["id"])
        begin_pssr_fieldwork(pssr["id"], actors["lead"]["id"])
        punch = validate_success(api.create_punch_item(
            pssr["id"], {"title": "Missing guard rail", "priority": "P1",
                         "assignee_id": actors["req"]["id"]},
            make_pssr_lead_headers(actors["lead"]["id"])), 201)
        assert get_pssr(pssr["id"])["punch_open_count"] == 1

        work_item_to_submitted(punch["id"], actors["req"]["id"], file_ref="s3://ev/rail.jpg")
        verify_item(punch["id"])
        assert get_pssr(pssr["id"])["punch_open_count"] == 0, (
            "verifying the punch item must reconcile the review's punch_open_count to 0"
        )

        approved = validate_success(
            api.approve_pssr(pssr["id"], make_pssr_lead_headers(actors["lead"]["id"])), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_at"] == "2026-05-01T00:00:00Z"


class TestPssrFieldworkWindow:
    def test_begin_fieldwork_outside_window_rejected(self, api):
        """PRD §3.5: "Once the logical clock falls inside the declared window —
        from `field_window_start` through `field_window_end`, both bounds
        inclusive, otherwise `ERR_FIELDWORK_WINDOW_NOT_ACTIVE`" — at the default
        clock 2026-05-01 a June window is not yet active.

        Design: Corner/endpoints/begin_fieldwork_outside_window_rejected
        """
        unit, study, actors, moc = setup_implemented_scenario(change_class="PERMANENT")
        pssr = create_pssr_for_moc(moc["id"], actors["lead"]["id"],
                                   window_start="2026-06-01", window_end="2026-06-05")
        resp = api.begin_pssr_fieldwork(pssr["id"], make_pssr_lead_headers(actors["lead"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FIELDWORK_WINDOW_NOT_ACTIVE.value)
        assert get_pssr(pssr["id"])["status"] == "PLANNED"


class TestPssrSegregationOfDuties:
    def test_sod_pssr_lead_is_requester_rejected(self, api):
        """PRD §3.5: "the lead must not be the MOC's requester
        (`ERR_SOD_PSSR_LEAD_IS_REQUESTER`)" — the requester holds PSSR_CERTIFIED
        and legitimately leads the fieldwork, but approval by the requester is a
        segregation-of-duties violation.

        Design: Corner/validations/sod_pssr_lead_is_requester_rejected
        """
        unit, study = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ", qualifications=["PSSR_CERTIFIED"])
        rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
        app = new_personnel("App", "E-APP")
        moc = drive_moc_to_implemented(unit["id"], req["id"], rev["id"], app["id"])

        pssr = create_pssr_for_moc(moc["id"], req["id"])
        begin_pssr_fieldwork(pssr["id"], req["id"])
        resp = api.approve_pssr(pssr["id"], make_pssr_lead_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_PSSR_LEAD_IS_REQUESTER.value)
        assert get_pssr(pssr["id"])["status"] == "IN_FIELD"


class TestPssrOptimisticConcurrency:
    def test_occ_stale_version_pssr_create_returns_412(self, api):
        """PRD §2.7: "If the supplied value does not match the MOC's current
        `version`, the request is rejected with `ERR_STALE_MOC_VERSION` (HTTP
        412)" and "This stale-version check is evaluated before any business-rule
        validation on those two endpoints." The MOC here is CLASSIFIED (version
        advanced past the captured one), and the stale check fires first.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_pssr_create_returns_412
        """
        unit, study = setup_unit_with_study()
        req = new_personnel("Req", "E-REQ")
        lead = new_personnel("Lead", "E-LEAD", qualifications=["PSSR_CERTIFIED"])
        moc = new_draft_moc(unit["id"], req["id"])
        stale_version = moc["version"]
        classify(moc["id"], change_class="PERMANENT", severity=2, likelihood=2)

        resp = api.create_pssr(moc["id"], create_pssr_payload(stale_version),
                               make_pssr_lead_headers(lead["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_MOC_VERSION.value)
        assert resp.status_code == 412
        assert list_moc_pssrs(moc["id"]) == [], "no Pssr row may be created on a stale version"


class TestPssrWindowOverlap:
    def _two_implemented_mocs(self):
        unit, study = setup_unit_with_study()
        actors = create_standard_actors()
        moc_a = drive_moc_to_implemented(unit["id"], actors["req"]["id"], actors["rev"]["id"],
                                         actors["app"]["id"], document_ref="SOP-A")
        moc_b = drive_moc_to_implemented(unit["id"], actors["req"]["id"], actors["rev"]["id"],
                                         actors["app"]["id"], document_ref="SOP-B")
        return unit, actors, moc_a, moc_b

    def test_pssr_window_adjacency_allowed(self, api):
        """PRD §3.5: "windows are treated as half-open intervals from start
        inclusive to end exclusive, so two reviews whose windows merely touch
        (one starting exactly when the other ends) do not conflict, while a true
        intersection is rejected with `ERR_PSSR_WINDOW_OVERLAP`" — a new window
        starting 2026-07-10 exactly when the occupant's ends is adjacency, not
        overlap. The check also excludes "the same-MOC sibling being superseded",
        so the incumbent here hangs off a different MOC and is left PLANNED.

        Design: Difficulty/resource_temporal_overlap/pssr_window_half_open_adjacency
        """
        unit, actors, moc_a, moc_b = self._two_implemented_mocs()
        pssr_a = create_pssr_for_moc(moc_a["id"], actors["lead"]["id"],
                                     window_start="2026-07-01", window_end="2026-07-10")

        version_b = moc_version(moc_b["id"])
        resp = api.create_pssr(moc_b["id"],
                               create_pssr_payload(version_b, field_window_start="2026-07-10",
                                                   field_window_end="2026-07-15"),
                               make_pssr_lead_headers(actors["lead"]["id"]))
        created = validate_success(resp, 201)
        assert created["status"] == "PLANNED"
        assert get_pssr(pssr_a["id"])["status"] == "PLANNED", (
            "a different MOC's PSSR must not be voided by this create"
        )

    def test_pssr_window_overlap_rejected(self, api):
        """PRD §3.5: "a true intersection is rejected with
        `ERR_PSSR_WINDOW_OVERLAP`" — starting one day before the occupant's end
        (2026-07-09 < 2026-07-10) intersects the half-open window
        [2026-07-01, 2026-07-10).

        Design: Difficulty/resource_temporal_overlap/pssr_window_half_open_adjacency
        """
        unit, actors, moc_a, moc_b = self._two_implemented_mocs()
        create_pssr_for_moc(moc_a["id"], actors["lead"]["id"],
                            window_start="2026-07-01", window_end="2026-07-10")

        version_b = moc_version(moc_b["id"])
        resp = api.create_pssr(moc_b["id"],
                               create_pssr_payload(version_b, field_window_start="2026-07-09",
                                                   field_window_end="2026-07-12"),
                               make_pssr_lead_headers(actors["lead"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PSSR_WINDOW_OVERLAP.value)
