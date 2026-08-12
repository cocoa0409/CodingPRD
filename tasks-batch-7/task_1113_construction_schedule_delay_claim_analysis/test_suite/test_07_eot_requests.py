"""Extension-of-time drafting guards: analysis acceptance and the entitlement
ceiling are verified when an EOT request is drafted (PRD §2.6, §3.6)."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    api_client,
    create_project,
    create_delay_event,
    notice_delay_event,
    setup_accepted_update,
    setup_tia_accepted_event,
    TEST_USERS,
    get_success_data,
)

CONTRACTOR = TEST_USERS["contractor_scheduler_headers"]
CLAIMS = TEST_USERS["claims_consultant_headers"]


class TestTiaAcceptanceGuard:
    def test_eot_draft_rejected_when_event_only_noticed(self, api):
        """PRD §3.6: "Three rules guard the draft, in the order given in §2.6: the
        referenced delay event must be in `TIA_ACCEPTED` (`ERR_TIA_NOT_ACCEPTED`);
        the `requested_days` — always at least one — may not exceed the sum of the
        event's `apportioned_compensable_days` and
        `apportioned_excusable_non_compensable_days`
        (`ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT`)". The EOT itself is in DRAFT, so
        its own state precondition passes and the referential rule fires.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_referential_on_eot_submit
        """
        project = create_project()
        event = create_delay_event(project["id"], causation="OWNER_CAUSED")
        notice_delay_event(project["id"], event["id"])  # NOTICED, not TIA_ACCEPTED
        resp = api.create_eot_request(
            project["id"],
            {"delay_event_id": event["id"], "requested_days": 5},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_TIA_NOT_ACCEPTED)

    def test_eot_draft_rejected_when_event_tia_rejected(self, api):
        """PRD §3.6: "the referenced delay event must be in `TIA_ACCEPTED`
        (`ERR_TIA_NOT_ACCEPTED`)". A `TIA_REJECTED` event is not `TIA_ACCEPTED`, so
        drafting an EOT against it fails the same referential rule.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_referential_on_eot_submit
        """
        ctx = setup_accepted_update()
        pid = ctx["project"]["id"]
        event = create_delay_event(
            pid,
            causation="FORCE_MAJEURE",
            event_start_date="2026-05-10T00:00:00Z",
            event_end_date="2026-05-15T00:00:00Z",
            fragnet_activity_ids=[ctx["update_activity_ids"][0]],
            fragnet_inserted_into_version_id=ctx["update"]["id"],
        )
        notice_delay_event(pid, event["id"])
        get_success_data(api_client.submit_tia(pid, event["id"], CONTRACTOR))
        rejected = get_success_data(api_client.reject_tia(pid, event["id"], CLAIMS))
        assert rejected["status"] == "TIA_REJECTED"
        resp = api.create_eot_request(
            pid, {"delay_event_id": event["id"], "requested_days": 5}, CONTRACTOR
        )
        validate_error(resp, ApiErrorId.ERR_TIA_NOT_ACCEPTED)

    def test_eot_draft_rejected_when_event_still_draft(self, api):
        """PRD §3.6: "Three rules guard the draft, in the order given in §2.6: the
        referenced delay event must be in `TIA_ACCEPTED` (`ERR_TIA_NOT_ACCEPTED`)".
        A delay event never noticed is still in DRAFT, so drafting an EOT against
        it is rejected.

        Design: Difficulty/cross_entity_state_dependency/eot_submit_requires_delay_event_tia_accepted_pair_eot_delayevent
        """
        project = create_project()
        event = create_delay_event(project["id"], causation="OWNER_CAUSED")
        assert event["status"] == "DRAFT"
        resp = api.create_eot_request(
            project["id"],
            {"delay_event_id": event["id"], "requested_days": 3},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_TIA_NOT_ACCEPTED)

    def test_eot_draft_rejected_when_event_noticed_not_accepted(self, api):
        """PRD §3.6: "the referenced delay event must be in `TIA_ACCEPTED`
        (`ERR_TIA_NOT_ACCEPTED`)". The TimeExtensionRequest → DelayEvent dependency
        is not satisfied by a NOTICED event.

        Design: Difficulty/cross_entity_state_dependency/eot_submit_requires_delay_event_tia_accepted_pair_eot_delayevent
        """
        project = create_project()
        event = create_delay_event(project["id"], causation="OWNER_CAUSED")
        notice_delay_event(project["id"], event["id"])
        resp = api.create_eot_request(
            project["id"],
            {"delay_event_id": event["id"], "requested_days": 3},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_TIA_NOT_ACCEPTED)


class TestEntitlementCeiling:
    def test_requested_days_exceed_entitlement(self, api):
        """PRD §3.6: "the `requested_days` — always at least one — may not exceed
        the sum of the event's `apportioned_compensable_days` and
        `apportioned_excusable_non_compensable_days`
        (`ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT`)".

        Design: Corner/validations/requested_days_exceed_entitlement
        """
        ctx = setup_accepted_update()
        pid = ctx["project"]["id"]
        event = setup_tia_accepted_event(
            pid, ctx["update"]["id"], ctx["update_activity_ids"][0]
        )
        assert event["status"] == "TIA_ACCEPTED"
        resp = api.create_eot_request(
            pid,
            {"delay_event_id": event["id"], "requested_days": 9999},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT)
