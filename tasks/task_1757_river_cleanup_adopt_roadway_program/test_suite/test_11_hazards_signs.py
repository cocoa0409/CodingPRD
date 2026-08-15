"""Hazard escalation and recognition signs (PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_event,
    create_hazard_payload,
    create_segment,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    setup_completed_event,
    validate_error,
    validate_success,
)

COORD = make_coordinator_headers()


class TestHazardLifecycle:
    def test_hazard_resolve_before_acknowledge_rejected(self, api):
        """PRD §3.7: "Resolution, valid only from `ACKNOWLEDGED` (else
        `ERR_HAZARD_NOT_ACKNOWLEDGED`), stores the supplied `resolution_note`
        describing the removal or disposal, stamps `resolved_at`, and moves the
        report to its terminal `RESOLVED` state."
        PRD §3.7: "Acknowledgement, valid only from `REPORTED` (anything else
        draws `ERR_HAZARD_NOT_REPORTED`), mints the `agency_reference`
        notification reference"

        Design: Corner/state_machines/hazard_resolve_before_acknowledge_rejected
        """
        segment = create_segment()
        hazard = validate_success(api.create_hazard(
            create_hazard_payload(segment["id"], hazard_type="SYRINGES",
                                  description="needle pack",
                                  location_note="MP 5.2 culvert"), COORD), 201)

        resp = api.resolve_hazard(hazard["id"], {"resolution_note": "removed"}, COORD)
        validate_error(resp, ApiErrorId.ERR_HAZARD_NOT_ACKNOWLEDGED)

        ack = validate_success(api.acknowledge_hazard(hazard["id"], COORD), 200)
        assert ack["agency_reference"] is not None
        assert ack["agency_reference"] != ""

        fin = validate_success(api.resolve_hazard(
            hazard["id"], {"resolution_note": "crew removed and disposed"}, COORD), 200)
        assert fin["status"] == "RESOLVED"

    def test_acknowledge_mints_agency_reference(self, api):
        """PRD §3.7: "Acknowledgement, valid only from `REPORTED` (anything
        else draws `ERR_HAZARD_NOT_REPORTED`), mints the `agency_reference`
        notification reference — the moment the responsible agency is formally
        notified — stamps `acknowledged_at` with the logical clock, and moves
        the report to `ACKNOWLEDGED`."

        Design: Corner/state_machines/hazard_resolve_before_acknowledge_rejected
        """
        segment = create_segment()
        hazard = validate_success(api.create_hazard(
            create_hazard_payload(segment["id"]), COORD), 201)
        assert hazard["status"] == "REPORTED"
        ack = validate_success(api.acknowledge_hazard(hazard["id"], COORD), 200)
        assert ack["status"] == "ACKNOWLEDGED"
        assert ack["agency_reference"]
        assert ack["acknowledged_at"] is not None

    def test_double_acknowledge_hazard_rejected(self, api):
        """PRD §3.7: "Acknowledgement, valid only from `REPORTED` (anything
        else draws `ERR_HAZARD_NOT_REPORTED`)"

        Design: Corner/validations/double_acknowledge_hazard_rejected
        """
        segment = create_segment()
        hazard = validate_success(api.create_hazard(
            create_hazard_payload(segment["id"], hazard_type="ASBESTOS",
                                  description="pipe fragments",
                                  location_note="MP 4.8"), COORD), 201)
        first = validate_success(api.acknowledge_hazard(hazard["id"], COORD), 200)
        ref1 = first["agency_reference"]

        resp = api.acknowledge_hazard(hazard["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_HAZARD_NOT_REPORTED)

        after = validate_success(api.get_hazard(hazard["id"], COORD), 200)
        assert after["status"] == "ACKNOWLEDGED"
        assert after["agency_reference"] == ref1

    def test_double_acknowledge_does_not_remint_reference(self, api):
        """PRD §3.7: "Acknowledgement ... mints the `agency_reference`
        notification reference — the moment the responsible agency is formally
        notified"

        Design: Corner/validations/double_acknowledge_hazard_rejected
        """
        segment = create_segment()
        hazard = validate_success(api.create_hazard(
            create_hazard_payload(segment["id"]), COORD), 201)
        first = validate_success(api.acknowledge_hazard(hazard["id"], COORD), 200)
        resp = api.acknowledge_hazard(hazard["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_HAZARD_NOT_REPORTED)
        after = validate_success(api.get_hazard(hazard["id"], COORD), 200)
        assert after["agency_reference"] == first["agency_reference"]


class TestHazardBlocksEventCreation:
    def test_open_hazard_blocks_event_creation(self, api):
        """PRD §3.7: "An open hazard — one in `REPORTED` or `ACKNOWLEDGED` —
        casts a shadow over its segment: scheduling any new cleanup event there
        is refused with `ERR_HAZARD_UNRESOLVED`"

        Design: Corner/validations/open_hazard_blocks_event_creation
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        hazard = validate_success(api.create_hazard(
            create_hazard_payload(segment["id"], hazard_type="PROPANE_TANK",
                                  description="tank in shallows",
                                  location_note="MP 5.0"), gl), 201)

        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl)
        validate_error(resp, ApiErrorId.ERR_HAZARD_UNRESOLVED)

        api.acknowledge_hazard(hazard["id"], COORD)
        resp2 = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl)
        validate_error(resp2, ApiErrorId.ERR_HAZARD_UNRESOLVED)

        api.resolve_hazard(hazard["id"], {"resolution_note": "removed by hazmat crew"}, COORD)
        ok = validate_success(api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl), 201)
        assert ok["status"] == "SCHEDULED"

    def test_resolved_hazard_lifts_scheduling_gate(self, api):
        """PRD §3.7: "An open hazard — one in `REPORTED` or `ACKNOWLEDGED` —
        casts a shadow over its segment: scheduling any new cleanup event there
        is refused with `ERR_HAZARD_UNRESOLVED`"

        Design: Corner/validations/open_hazard_blocks_event_creation
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        hazard = validate_success(api.create_hazard(
            create_hazard_payload(segment["id"]), gl), 201)
        api.acknowledge_hazard(hazard["id"], COORD)
        api.resolve_hazard(hazard["id"], {"resolution_note": "cleared"}, COORD)
        ok = validate_success(api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl), 201)
        assert ok["status"] == "SCHEDULED"


class TestSigns:
    def test_second_sign_request_rejected(self, api):
        """PRD §3.8: "An agreement may have at most one live sign, where live
        means `REQUESTED` or `INSTALLED`; a second request while one is live is
        refused with `ERR_SIGN_ALREADY_EXISTS`."

        Design: Corner/validations/second_sign_request_rejected
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        validate_success(api.request_sign(
            agreement["id"], {"sign_text": "Riverkeepers of Maple County"}, gl), 201)
        resp = api.request_sign(
            agreement["id"], {"sign_text": "Second Sign Text"}, gl)
        validate_error(resp, ApiErrorId.ERR_SIGN_ALREADY_EXISTS)

    def test_sign_request_on_pending_agreement_rejected(self, api):
        """PRD §3.8: "The owning leader requests one under an `ACTIVE`
        agreement — a request under any other status fails with
        `ERR_AGREEMENT_NOT_ACTIVE`"

        Design: Corner/validations/second_sign_request_rejected
        """
        from test_helpers import create_agreement, create_group, create_segment
        group = create_group()
        segment = create_segment()
        agreement = create_agreement(group, segment)
        gl = make_group_leader_headers(group["id"])
        resp = api.request_sign(
            agreement["id"], {"sign_text": "Riverkeepers of Maple County"}, gl)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_double_sign_install_rejected(self, api):
        """PRD §3.8: "the sign must be `REQUESTED` (else
        `ERR_SIGN_NOT_REQUESTED`)"

        Design: Corner/validations/double_sign_install_rejected
        """
        group, segment, agreement, waiver, event, report = setup_completed_event(
            scheduled_date="2026-09-10", clock_iso="2026-09-10T10:00:00Z",
        )
        gl = make_group_leader_headers(group["id"])
        sign = validate_success(api.request_sign(
            agreement["id"], {"sign_text": "Riverkeepers of Maple County"}, gl), 201)
        validate_success(api.install_sign(sign["id"], COORD), 200)
        resp = api.install_sign(sign["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SIGN_NOT_REQUESTED)

    def test_sign_install_sets_installed_date(self, api):
        """PRD §3.8: "Installation stamps `installed_date` with the clock date
        and moves the sign to `INSTALLED`."

        Design: Corner/validations/double_sign_install_rejected
        """
        group, segment, agreement, waiver, event, report = setup_completed_event(
            scheduled_date="2026-09-10", clock_iso="2026-09-10T10:00:00Z",
        )
        gl = make_group_leader_headers(group["id"])
        sign = validate_success(api.request_sign(
            agreement["id"], {"sign_text": "Riverkeepers of Maple County"}, gl), 201)
        installed = validate_success(api.install_sign(sign["id"], COORD), 200)
        assert installed["status"] == "INSTALLED"
        assert installed["installed_date"] == "2026-09-10"


class TestSignInstallRequiresCompletedCleanup:
    def test_sign_install_requires_completed_cleanup(self, api):
        """PRD §3.8: "at least one cleanup event under the agreement must have
        reached `COMPLETED` — installing before the group's first completed
        cleanup is rejected with `ERR_NO_COMPLETED_CLEANUP`."

        Design: Difficulty/cross_entity_state_dependency/sign_install_requires_completed_cleanup
        """
        from test_helpers import (
            brief_event, complete_event, setup_agreement_with_waiver,
        )
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        sign = validate_success(api.request_sign(
            agreement["id"], {"sign_text": "Riverkeepers of Maple County"}, gl), 201)
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        brief_event(event["id"], group["id"], [waiver["id"]])

        resp = api.install_sign(sign["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_CLEANUP)

        set_clock("2026-09-10T10:00:00Z")
        complete_event(event["id"], group["id"])

        installed = validate_success(api.install_sign(sign["id"], COORD), 200)
        assert installed["status"] == "INSTALLED"
        assert installed["installed_date"] == "2026-09-10"

    def test_sign_install_blocked_until_first_completion(self, api):
        """PRD §3.8: "installing before the group's first completed cleanup is
        rejected with `ERR_NO_COMPLETED_CLEANUP`."

        Design: Difficulty/cross_entity_state_dependency/sign_install_requires_completed_cleanup
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        sign = validate_success(api.request_sign(
            agreement["id"], {"sign_text": "Riverkeepers of Maple County"}, gl), 201)
        # A SCHEDULED (not completed) event does not satisfy the prerequisite.
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        resp = api.install_sign(sign["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_CLEANUP)
