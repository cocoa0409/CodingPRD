"""Engineering surveys, the project engineering pin, and the release gate."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS,
    create_engineering_survey_payload, create_abatement_payload,
    create_structure_survey_payload, complete_survey_payload,
    make_structural_engineer_headers, make_peer_review_engineer_headers,
    make_abatement_supervisor_headers,
    create_project, create_and_complete_survey, set_clock,
    setup_preconditions_pending, setup_release_ready, setup_released_project,
    create_confirmed_disconnect, pin_engineering_survey,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]
AUTHORITY = TEST_USERS["authority_reviewer_headers"]


class TestEngineeringSurveyCycle:
    def _certified_survey(self, project_id):
        es = get_success_data(
            api_client.create_engineering_survey(
                project_id, create_engineering_survey_payload(),
                make_structural_engineer_headers("cy-a-1"),
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "SUBMIT"}, make_structural_engineer_headers("cy-a-1")
            )
        )
        return get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "CERTIFY"}, make_peer_review_engineer_headers("cy-p-1")
            )
        )

    def test_engineering_survey_certified_revision_cycle(self):
        """PRD §3.4: "Requesting a revision on a `CERTIFIED` survey is heavier:
        the survey returns to `DRAFT`, its `revision_number` increments by 1, and
        `certified_by_user_id` is cleared"
        PRD §3.4: "The author submits the survey from `DRAFT` to `SUBMITTED`; a
        `PeerReviewEngineer` then either certifies it — moving it to `CERTIFIED`
        and recording `certified_by_user_id`"

        Design: Difficulty/non_linear_state_machine/engineering_survey_certified_revision_cycle
        """
        project = create_project(name="Cycle Lot", address="8 Elm St", lot_area_sqft=20000)
        es = self._certified_survey(project["id"])
        assert es["revision_number"] == 1
        back = get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "REQUEST_REVISION"},
                make_peer_review_engineer_headers("cy-p-1"),
            )
        )
        assert back["status"] == "DRAFT"
        assert back["revision_number"] == 2
        assert back["certified_by_user_id"] is None
        get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "SUBMIT"}, make_structural_engineer_headers("cy-a-1")
            )
        )
        again = get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "CERTIFY"}, make_peer_review_engineer_headers("cy-p-1")
            )
        )
        assert again["status"] == "CERTIFIED"
        assert again["revision_number"] == 2, "revision never resets"

    def test_engineering_survey_submitted_revision_request_returns_to_draft(self):
        """PRD §3.4: "Requesting a revision on a merely `SUBMITTED` survey simply
        sends it back."
        PRD §3.4: "The survey is born in `DRAFT` with `revision_number` 1"

        Design: Difficulty/non_linear_state_machine/engineering_survey_certified_revision_cycle
        """
        project = create_project(name="Cycle2", address="8B Elm St", lot_area_sqft=20000)
        es = get_success_data(
            api_client.create_engineering_survey(
                project["id"], create_engineering_survey_payload(),
                make_structural_engineer_headers("cy2-a-1"),
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "SUBMIT"}, make_structural_engineer_headers("cy2-a-1")
            )
        )
        back = get_success_data(
            api_client.transition_engineering_survey(
                es["id"], {"action": "REQUEST_REVISION"},
                make_peer_review_engineer_headers("cy2-p-1"),
            )
        )
        assert back["status"] == "DRAFT"
        assert back["revision_number"] == 1, "SUBMITTED bounce does not bump the revision"


class TestEngineeringPin:
    def _project_with_two_certified_surveys(self):
        project = create_project(name="OCC1", address="13 Role St", lot_area_sqft=12000)
        create_and_complete_survey(project["id"])
        surveys = []
        for i, method in enumerate(("MECHANICAL", "SELECTIVE_DECONSTRUCTION"), start=1):
            es = get_success_data(
                api_client.create_engineering_survey(
                    project["id"],
                    create_engineering_survey_payload(demolition_method=method),
                    make_structural_engineer_headers(f"oc-a-{i}"),
                )
            )
            get_success_data(
                api_client.transition_engineering_survey(
                    es["id"], {"action": "SUBMIT"},
                    make_structural_engineer_headers(f"oc-a-{i}"),
                )
            )
            surveys.append(
                get_success_data(
                    api_client.transition_engineering_survey(
                        es["id"], {"action": "CERTIFY"},
                        make_peer_review_engineer_headers(f"oc-p-{i}"),
                    )
                )
            )
        return project, surveys

    def test_occ_engineering_pin_stale_version_rejected(self):
        """PRD §2.6: "If the project's current `version` has advanced past that
        value, the pin is rejected with `ERR_STALE_VERSION` (HTTP 412). Pinning
        legitimately supersedes any prior pin, so a later pin carrying an
        up-to-date version succeeds; only a stale `expected_project_version` is
        rejected."

        Design: Corner/cross_cutting_layers/occ_engineering_pin_stale_version_rejected
        """
        project, (es1, es2) = self._project_with_two_certified_surveys()
        observed = get_success_data(api_client.get_project(project["id"], SUPERVISOR))["version"]
        first = get_success_data(
            api_client.pin_engineering_survey(
                project["id"],
                {"engineering_survey_id": es1["id"], "expected_project_version": observed},
                SUPERVISOR,
            )
        )
        assert first["pinned_engineering_survey_id"] == es1["id"]
        assert first["version"] == observed + 1
        stale = api_client.pin_engineering_survey(
            project["id"],
            {"engineering_survey_id": es2["id"], "expected_project_version": observed},
            SUPERVISOR,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_success_data(
            api_client.pin_engineering_survey(
                project["id"],
                {"engineering_survey_id": es2["id"],
                 "expected_project_version": first["version"]},
                SUPERVISOR,
            )
        )
        assert fresh["pinned_engineering_survey_id"] == es2["id"]

    def test_pin_requires_certified_survey(self):
        """PRD §3.4: "the named survey must belong to this project (else
        `ERR_NOT_FOUND`) and must be `CERTIFIED` (else
        `ERR_ENGINEERING_NOT_CERTIFIED`)."
        PRD §3.4: "Pinning is allowed only while the project is in
        `PRECONDITIONS_PENDING` or `RELEASED`"

        Design: Corner/cross_cutting_layers/occ_engineering_pin_stale_version_rejected
        """
        project = create_project(name="PinGate", address="13B Role St", lot_area_sqft=12000)
        create_and_complete_survey(project["id"])
        es = get_success_data(
            api_client.create_engineering_survey(
                project["id"], create_engineering_survey_payload(),
                make_structural_engineer_headers("pg-a-1"),
            )
        )
        observed = get_success_data(api_client.get_project(project["id"], SUPERVISOR))["version"]
        resp = api_client.pin_engineering_survey(
            project["id"],
            {"engineering_survey_id": es["id"], "expected_project_version": observed},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_ENGINEERING_NOT_CERTIFIED)


class TestReleaseGate:
    def test_release_state_beats_safety(self):
        """PRD §2.9: "5. **State legality** — the entity's state machine allows
        the requested transition from its current state"
        PRD §2.9: "8. **Release prerequisites**, evaluated in their own sub-order:
        surveys complete (`ERR_SURVEY_INCOMPLETE`), then abatements certified
        (`ERR_HAZMAT_UNRESOLVED`)"
        PRD §3.7: "Release is the pivot of the whole workflow: the moment a
        project in `PRECONDITIONS_PENDING` proves every prerequisite and earns
        `RELEASED`."

        Design: Difficulty/priority_pair_validation_conflict/release_state_beats_safety
        """
        project = create_project(name="Prio 1", address="31 Elm St", lot_area_sqft=20000)
        survey = get_success_data(
            api_client.create_structure_survey(
                project["id"], create_structure_survey_payload(), SURVEYOR
            )
        )
        get_success_data(
            api_client.create_abatement(survey["id"], create_abatement_payload(), SURVEYOR)
        )
        # Project is SURVEY_PHASE (release only defined from PRECONDITIONS_PENDING)
        # AND an abatement is IDENTIFIED — the state violation surfaces first.
        resp = api_client.release_project(project["id"], {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_release_safety_beats_temporal(self):
        """PRD §2.9: "8. **Release prerequisites**, evaluated in their own
        sub-order: surveys complete (`ERR_SURVEY_INCOMPLETE`), then abatements
        certified (`ERR_HAZMAT_UNRESOLVED`), then utilities confirmed
        (`ERR_UTILITY_UNVERIFIED`), then a permit active and unexpired
        (`ERR_PERMIT_NOT_ACTIVE`), then the pinned engineering survey certified
        (`ERR_ENGINEERING_NOT_CERTIFIED`)."
        PRD §2.9: "9. **Temporal rules** — notification completeness before the
        wait window (`ERR_NOTIFICATIONS_INCOMPLETE`, then
        `ERR_NOTIFICATION_WINDOW_OPEN`)"

        Design: Difficulty/priority_pair_validation_conflict/release_safety_beats_temporal
        """
        project = create_project(name="Prio 2", address="33 Elm St", lot_area_sqft=20000)
        survey = create_and_complete_survey(project["id"], hazmat_found=True)
        get_success_data(
            api_client.create_abatement(survey["id"], create_abatement_payload(), SURVEYOR)
        )
        # PRECONDITIONS_PENDING with an IDENTIFIED abatement and zero
        # notifications: the safety leg beats the temporal leg.
        resp = api_client.release_project(project["id"], {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_HAZMAT_UNRESOLVED)
        after = get_success_data(api_client.get_project(project["id"], SUPERVISOR))
        assert after["status"] == "PRECONDITIONS_PENDING"

    def test_release_with_zero_notifications_returns_incomplete(self):
        """PRD §3.7: "6. At least one neighbor notification must exist and all of
        them must be `DELIVERED`; otherwise `ERR_NOTIFICATIONS_INCOMPLETE`."

        Design: Corner/validations/release_with_zero_notifications_returns_incomplete
        """
        ctx = setup_preconditions_pending(name="NoNotif", address="52 Pine St")
        pid = ctx["project"]["id"]
        pin_engineering_survey(pid, ctx["engineering"]["id"])
        set_clock("2026-08-05T09:00:00Z")
        resp = api_client.release_project(pid, {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATIONS_INCOMPLETE)

    def test_release_with_undelivered_notification_rejected(self):
        """PRD §3.7: "6. At least one neighbor notification must exist and all of
        them must be `DELIVERED`; otherwise `ERR_NOTIFICATIONS_INCOMPLETE`."

        Design: Corner/validations/release_with_undelivered_notification_rejected
        """
        ctx = setup_preconditions_pending(name="Undeliv", address="74 Pine St")
        pid = ctx["project"]["id"]
        pin_engineering_survey(pid, ctx["engineering"]["id"])
        get_success_data(
            api_client.create_neighbor_notification(
                pid,
                {"address": "76 Pine St", "notice_method": "CERTIFIED_MAIL",
                 "scheduled_delivery_date": "2026-08-02"},
                SUPERVISOR,
            )
        )
        resp = api_client.release_project(pid, {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATIONS_INCOMPLETE)

    def test_release_without_engineering_pin_rejected(self):
        """PRD §3.7: "5. The pinned engineering survey must exist and be
        `CERTIFIED`; otherwise `ERR_ENGINEERING_NOT_CERTIFIED`."

        Design: Corner/validations/release_without_engineering_pin_rejected
        """
        # Build the full gate state but never pin the CERTIFIED survey.
        ctx2 = setup_preconditions_pending(name="NoPin", address="70 Pine St")
        pid = ctx2["project"]["id"]
        # Deliver one notification and advance the clock past the wait window.
        nn = get_success_data(
            api_client.create_neighbor_notification(
                pid,
                {"address": "72 Pine St", "notice_method": "CERTIFIED_MAIL",
                 "scheduled_delivery_date": "2026-08-02"},
                SUPERVISOR,
            )
        )
        set_clock("2026-08-02T09:00:00Z")
        get_success_data(
            api_client.transition_neighbor_notification(nn["id"], {"action": "DELIVER"}, SUPERVISOR)
        )
        set_clock("2026-08-05T09:00:00Z")
        resp = api_client.release_project(pid, {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ENGINEERING_NOT_CERTIFIED)

    def test_release_with_permit_not_active_rejected(self):
        """PRD §3.7: "4. A permit of the project must be `ACTIVE` with
        `expires_at` strictly after the current logical time; otherwise
        `ERR_PERMIT_NOT_ACTIVE`."

        Design: Corner/validations/release_with_permit_not_active_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        project = create_project(name="NoAct", address="98 Pine St", lot_area_sqft=30000)
        pid = project["id"]
        create_and_complete_survey(pid)
        create_confirmed_disconnect(pid)
        pm = get_success_data(
            api_client.create_permit(pid, {"permit_number": "P-1",
                                           "gross_floor_area_sqft": 20000}, PERMIT)
        )
        get_success_data(api_client.transition_permit(pm["id"], {"action": "SUBMIT"}, PERMIT))
        get_success_data(api_client.transition_permit(pm["id"], {"action": "APPROVE"}, AUTHORITY))
        resp = api_client.release_project(pid, {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)
        after = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert after["status"] == "PRECONDITIONS_PENDING"

    def test_notification_wait_window_exactly_72h(self):
        """PRD §3.6: "The notification wait window ends 72 hours after the most
        recent delivery: the system takes the latest `delivered_at` across the
        project's `DELIVERED` notifications, adds 72 hours, and permits release
        only when the current logical time has reached that instant. The boundary
        is inclusive — release at exactly the 72-hour mark is allowed."
        PRD §3.7: "7. The 72-hour wait window of §3.6 must have elapsed — the
        current logical time at or past the latest `delivered_at` plus 72 hours;
        otherwise `ERR_NOTIFICATION_WINDOW_OPEN`."

        Design: Difficulty/boundary_precision_check/notification_wait_window_exactly_72h
        """
        ctx_a = setup_release_ready(name="Wait A", address="55 Elm St")
        ctx_b = setup_release_ready(name="Wait B", address="59 Elm St")
        # Both delivered at 2026-08-02T09:00:00Z; window ends 2026-08-05T09:00:00Z.
        set_clock("2026-08-05T08:59:59Z")
        resp_a = api_client.release_project(ctx_a["project"]["id"], {}, SUPERVISOR)
        validate_error(resp_a, ApiErrorId.ERR_NOTIFICATION_WINDOW_OPEN)
        set_clock("2026-08-05T09:00:00Z")
        ok_b = api_client.release_project(ctx_b["project"]["id"], {}, SUPERVISOR)
        assert validate_success(ok_b)["status"] == "RELEASED"

    def test_release_success_moves_to_released_and_bumps_version(self):
        """PRD §3.7: "A successful release moves the project from
        `PRECONDITIONS_PENDING` to `RELEASED` and increments its `version` by 1."

        Design: Difficulty/boundary_precision_check/notification_wait_window_exactly_72h
        """
        ctx = setup_release_ready(name="Wait C", address="55B Elm St")
        pid = ctx["project"]["id"]
        before = get_success_data(api_client.get_project(pid, SUPERVISOR))
        released = get_success_data(api_client.release_project(pid, {}, SUPERVISOR))
        assert released["status"] == "RELEASED"
        assert released["version"] == before["version"] + 1


    def test_release_from_draft_is_a_state_violation(self):
        """PRD §3.7: "Release is the pivot of the whole workflow: the moment a
        project in `PRECONDITIONS_PENDING` proves every prerequisite and earns
        `RELEASED`."
        PRD §2.9: "5. **State legality** — the entity's state machine allows the
        requested transition from its current state ... violations surface as
        `ERR_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/release_state_beats_safety
        """
        project = create_project(name="Prio1B", address="31B Elm St", lot_area_sqft=20000)
        # DRAFT with no prerequisites at all: the phase gate rejects first.
        resp = api_client.release_project(project["id"], {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_release_blocked_by_unresolved_hazmat_alone(self):
        """PRD §3.7: "2. No abatement order descended from any of the project's
        surveys may stand outside `CLEARANCE_CERTIFIED`; otherwise
        `ERR_HAZMAT_UNRESOLVED`."
        PRD §2.9: "8. **Release prerequisites**, evaluated in their own
        sub-order: surveys complete (`ERR_SURVEY_INCOMPLETE`), then abatements
        certified (`ERR_HAZMAT_UNRESOLVED`)"

        Design: Difficulty/priority_pair_validation_conflict/release_safety_beats_temporal
        """
        # Fully gated except the abatement is CERTIFIED-pending: surveys COMPLETE,
        # so the safety sub-order advances to the hazmat leg.
        project = create_project(name="Prio2B", address="33B Elm St", lot_area_sqft=20000)
        survey = create_and_complete_survey(project["id"], hazmat_found=True)
        ab = get_success_data(
            api_client.create_abatement(survey["id"], create_abatement_payload(), SURVEYOR)
        )
        starter = make_abatement_supervisor_headers("p2b-s-1")
        get_success_data(api_client.transition_abatement(ab["id"], {"action": "START"}, starter))
        get_success_data(
            api_client.transition_abatement(ab["id"], {"action": "REQUEST_CLEARANCE"}, starter)
        )
        resp = api_client.release_project(project["id"], {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_HAZMAT_UNRESOLVED)
        after = get_success_data(api_client.get_project(project["id"], SUPERVISOR))
        assert after["status"] == "PRECONDITIONS_PENDING"


class TestPinStaleAndCascade:
    def test_release_blocked_by_stale_engineering_pin(self):
        """PRD §3.4: "the pin fields are kept but are now stale — any release
        attempt will fail with `ERR_ENGINEERING_PIN_STALE` until a
        `SiteSupervisor` re-pins"
        PRD §3.7: "8. The pinned survey's current `revision_number` must still
        equal `pinned_engineering_revision`; otherwise `ERR_ENGINEERING_PIN_STALE`."

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_stale_engineering_pin
        """
        ctx = setup_released_project(name="Pin Lot", address="63 Elm St",
                                     required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        es_id = ctx["engineering"]["id"]
        author = ctx["engineering"]["author_user_id"]
        # Certified revision goes back to DRAFT (cascade reverts project), then
        # re-SUBMIT and re-CERTIFY at revision 2 while the pin still records 1.
        get_success_data(
            api_client.transition_engineering_survey(
                es_id, {"action": "REQUEST_REVISION"},
                make_peer_review_engineer_headers("sp-p-x"),
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es_id, {"action": "SUBMIT"}, make_structural_engineer_headers(author)
            )
        )
        recertified = get_success_data(
            api_client.transition_engineering_survey(
                es_id, {"action": "CERTIFY"}, make_peer_review_engineer_headers("sp-p-y")
            )
        )
        assert recertified["status"] == "CERTIFIED"
        assert recertified["revision_number"] == 2
        resp = api_client.release_project(pid, {}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ENGINEERING_PIN_STALE)
        after = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert after["status"] == "PRECONDITIONS_PENDING"

    def test_repin_after_revision_restores_release(self):
        """PRD §3.4: "the pin fields are kept but are now stale — any release
        attempt will fail with `ERR_ENGINEERING_PIN_STALE` until a
        `SiteSupervisor` re-pins"
        PRD §3.4: "the pin records the survey's id as
        `pinned_engineering_survey_id` and its `revision_number` at pin time as
        `pinned_engineering_revision`, increments the project's `version` by 1,
        and supersedes any prior pin."

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_stale_engineering_pin
        """
        ctx = setup_released_project(name="PinFix", address="63B Elm St",
                                     required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        es_id = ctx["engineering"]["id"]
        author = ctx["engineering"]["author_user_id"]
        get_success_data(
            api_client.transition_engineering_survey(
                es_id, {"action": "REQUEST_REVISION"},
                make_peer_review_engineer_headers("sp2-p-x"),
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es_id, {"action": "SUBMIT"}, make_structural_engineer_headers(author)
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es_id, {"action": "CERTIFY"}, make_peer_review_engineer_headers("sp2-p-y")
            )
        )
        # The cascade voided nothing DELIVERED, so the wait window still stands;
        # re-pinning at revision 2 must clear the stale-pin failure.
        pinned = pin_engineering_survey(pid, es_id)
        assert pinned["pinned_engineering_revision"] == 2
        released = get_success_data(api_client.release_project(pid, {}, SUPERVISOR))
        assert released["status"] == "RELEASED"

    def test_engineering_revision_cascade_reverts_project_and_voids_notifications(self):
        """PRD §3.4: "If a revision request sends the project's pinned survey back
        to `DRAFT` while the project is `RELEASED`, the survey's `revision_number`
        no longer matches `pinned_engineering_revision`, and the project cascades
        from `RELEASED` to `PRECONDITIONS_PENDING`: the pin fields are kept but
        are now stale — any release attempt will fail with
        `ERR_ENGINEERING_PIN_STALE` until a `SiteSupervisor` re-pins — every
        neighbor notification still in `PENDING_DELIVERY` is voided, and the
        project's `version` increments by 1."

        Design: Difficulty/transitive_cascade/engineering_revision_cascade_reverts_project_and_voids_notifications
        """
        ctx = setup_released_project(name="Cascade A", address="11 Elm St",
                                     required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        es_id = ctx["engineering"]["id"]
        nn2 = get_success_data(
            api_client.create_neighbor_notification(
                pid,
                {"address": "15 Elm St", "notice_method": "DOOR_HANGER",
                 "scheduled_delivery_date": "2026-08-06"},
                SUPERVISOR,
            )
        )
        get_success_data(
            api_client.transition_engineering_survey(
                es_id, {"action": "REQUEST_REVISION"},
                make_peer_review_engineer_headers("ca-p-1"),
            )
        )
        survey_after = get_success_data(
            api_client.list_engineering_surveys(pid, SUPERVISOR)
        )[0]
        assert survey_after["status"] == "DRAFT"
        assert survey_after["revision_number"] == 2
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["status"] == "PRECONDITIONS_PENDING"
        assert project["pinned_engineering_revision"] == 1, "pin kept but stale"
        notifications, _ = validate_paginated(
            api_client.list_neighbor_notifications(pid, SUPERVISOR)
        )
        by_id = {n["id"]: n["status"] for n in notifications}
        assert by_id[nn2["id"]] == "VOIDED"
        assert by_id[ctx["notification"]["id"]] == "DELIVERED"

    def test_engineering_revision_cascade_bumps_project_version(self):
        """PRD §3.4: "every neighbor notification still in `PENDING_DELIVERY` is
        voided, and the project's `version` increments by 1."
        PRD §2.7: "Every such cascade mutates the affected project —
        incrementing its `version` by 1 and refreshing `updated_at` — alongside
        the primary mutation that caused it."

        Design: Difficulty/transitive_cascade/engineering_revision_cascade_reverts_project_and_voids_notifications
        """
        ctx = setup_released_project(name="CascadeA2", address="11B Elm St")
        pid = ctx["project"]["id"]
        before = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert before["status"] == "RELEASED"
        get_success_data(
            api_client.transition_engineering_survey(
                ctx["engineering"]["id"], {"action": "REQUEST_REVISION"},
                make_peer_review_engineer_headers("ca2-p-1"),
            )
        )
        after = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert after["status"] == "PRECONDITIONS_PENDING"
        assert after["version"] == before["version"] + 1
