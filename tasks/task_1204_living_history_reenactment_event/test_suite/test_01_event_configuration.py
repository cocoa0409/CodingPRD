"""Event configuration: creation defaults, read/envelope shape, OCC, and
the agreement obligations that gate publication."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    ApiErrorId,
    assert_event,
    create_event_payload,
    create_agreement_payload,
    sign_agreement_payload,
    validate_error,
    validate_success,
    is_iso8601_timestamp,
)
from test_helpers.fixtures import (
    add_signed_agreement,
    create_event,
    get_event,
    open_registration,
    set_clock,
)

ORG = TEST_USERS["organizer_headers"]


class TestEventCreationDefaults:
    def test_event_created_with_defaults_and_planning_posture(self, api):
        """PRD §3.1: "`max_minor_per_adult`, the supervision ratio capping minors
        per checked-in adult within a unit, which defaults to 4 when omitted."
        PRD §3.1: "A new event begins in `PLANNING` posture with
        `restriction_level` `GREEN`, an `approved_combatant_count` of zero, and
        `cancelled_at` null."
        PRD §2.4: "`version` (integer): a system-managed mutation counter."

        Design: Corner/entities/event_created_with_defaults_and_planning_posture
        """
        payload = create_event_payload()
        payload.pop("max_minor_per_adult")
        resp = api_client.create_event(payload, ORG)
        data = validate_success(resp, 201)
        assert_event(data)
        assert data["event_posture"] == "PLANNING", "new event must start in PLANNING"
        assert data["max_minor_per_adult"] == 4, "default supervision ratio must be 4"
        assert data["restriction_level"] == "GREEN"
        assert data["approved_combatant_count"] == 0
        assert data["cancelled_at"] is None
        assert data["version"] == 1, "the creation write sets the mutation counter to 1"


class TestEventNotFound:
    def test_get_missing_event_returns_event_not_found(self, api):
        """PRD §2.9: "The existence family maps each unresolved reference to its
        own error: an unresolvable event reference yields `ERR_EVENT_NOT_FOUND`"
        and "All are HTTP 404."

        Design: Corner/entities/get_missing_event_returns_event_not_found
        """
        create_event()
        resp = api_client.get_event(NON_EXISTENT_UUID, ORG)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND, 404)


class TestResponseEnvelope:
    def test_response_envelope_shape_on_read(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_shape_on_read
        """
        event = create_event()
        resp = api_client.get_event(event["id"], ORG)
        body = resp.json()
        assert resp.status_code == 200
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with req_"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object", "single-resource read uses response_type object"
        assert body["data"]["id"] == event["id"]
        assert body["data"]["version"] == 1


class TestEventVersioning:
    def test_event_version_increments_on_each_mutation(self, api):
        """PRD §2.4: "Every state transition and every mutating write described in
        §3 increments the affected resource's `version` by exactly one and
        refreshes its `updated_at`."
        PRD §3.2: "Because agreement activity changes the event's documentary
        state, submitting an agreement also increments the event's `version` by
        one"

        Design: Corner/cross_cutting_complexity_layers/event_version_increments_on_each_mutation
        """
        event = create_event()
        assert event["version"] == 1, "version at creation is 1"
        opened = open_registration(event["id"])
        assert opened["version"] == 2, "open-registration increments version to 2"
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        reread = get_event(event["id"])
        assert reread["version"] == 3, "agreement submission bumps the event version to 3"


class TestOptimisticConcurrency:
    def test_occ_event_patch_stale_version_rejected(self, api):
        """PRD §2.8: "If that value does not match the event's current `version` —
        for example, because another organizer has since patched the event or
        submitted an agreement, both of which advance the event's version — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is
        applied."

        Design: Corner/cross_cutting_complexity_layers/occ_event_patch_stale_version_rejected
        """
        event = create_event()
        first = api_client.patch_event(
            event["id"],
            {"expected_event_version": event["version"], "max_minor_per_adult": 3},
            ORG,
        )
        patched = validate_success(first, 200)
        assert patched["version"] == 2
        assert patched["max_minor_per_adult"] == 3

        stale = api_client.patch_event(
            event["id"],
            {"expected_event_version": event["version"], "max_minor_per_adult": 2},
            ORG,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        reread = get_event(event["id"])
        assert reread["max_minor_per_adult"] == 3, "stale PATCH must apply no change"
        assert reread["version"] == 2

    def test_occ_agreement_create_stale_version_rejected(self, api):
        """PRD §2.8: "Exactly two write operations are guarded by optimistic
        concurrency control, both against the Event: updating an event's mutable
        settings, and submitting a new agreement under an event."
        PRD §2.8: "If that value does not match the event's current `version` —
        for example, because another organizer has since patched the event or
        submitted an agreement, both of which advance the event's version — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is
        applied."

        Design: Corner/cross_cutting_complexity_layers/occ_agreement_create_stale_version_rejected
        """
        event = create_event()
        first = api_client.create_agreement(
            event["id"],
            create_agreement_payload(expected_event_version=event["version"]),
            ORG,
        )
        agreement = validate_success(first, 201)
        assert agreement["status"] == "SUBMITTED"

        stale = api_client.create_agreement(
            event["id"],
            create_agreement_payload(
                document_ref="DOC-LAND-2",
                effective_until="2026-08-15T00:00:00Z",
                expected_event_version=event["version"],
            ),
            ORG,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        listing = validate_success(api_client.list_agreements(event["id"], ORG), 200)
        assert len(listing) == 1, "no superseding agreement may be created"
        assert listing[0]["id"] == agreement["id"]
        assert listing[0]["status"] == "SUBMITTED", "rejected create must not supersede"


class TestAgreementLifecycle:
    def test_agreement_superseded_by_new_version(self, api):
        """PRD §3.2: "Submitting one automatically supersedes every prior agreement
        of the same `agreement_type` for the same event: any such agreement in
        `SUBMITTED` or `SIGNED` moves to `SUPERSEDED`."
        PRD §3.2: "The event's agreement listing returns agreements of every
        status, including `SUPERSEDED`, in creation order."

        Design: Corner/state_machines/agreement_superseded_by_new_version
        """
        event = create_event()
        first = add_signed_agreement(event["id"], "LANDOWNER_USE", document_ref="DOC-LAND-1")
        assert first["status"] == "SIGNED"
        set_clock("2026-05-02T00:00:00Z")
        current = get_event(event["id"])
        resp = api_client.create_agreement(
            event["id"],
            create_agreement_payload(
                document_ref="DOC-LAND-2",
                effective_until="2026-08-15T00:00:00Z",
                expected_event_version=current["version"],
            ),
            ORG,
        )
        second = validate_success(resp, 201)
        assert second["status"] == "SUBMITTED"

        listing = validate_success(api_client.list_agreements(event["id"], ORG), 200)
        assert [a["id"] for a in listing] == [first["id"], second["id"]], (
            "agreements list must be in creation order"
        )
        assert listing[0]["status"] == "SUPERSEDED", "prior SIGNED agreement is superseded"
        assert listing[1]["status"] == "SUBMITTED"

    def test_sign_already_signed_agreement_rejected(self, api):
        """PRD §3.2: "Signing is an organizer action valid only from `SUBMITTED`
        (any other status is rejected with `ERR_INVALID_AGREEMENT_STATUS`)"

        Design: Corner/state_machines/sign_already_signed_agreement_rejected
        """
        event = create_event()
        agreement = add_signed_agreement(event["id"], "LANDOWNER_USE")
        assert agreement["status"] == "SIGNED"
        resp = api_client.sign_agreement(
            agreement["id"], sign_agreement_payload(), ORG
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AGREEMENT_STATUS, 409)
        listing = validate_success(api_client.list_agreements(event["id"], ORG), 200)
        assert listing[0]["status"] == "SIGNED", "rejected re-sign must not change status"


class TestPublishGates:
    def test_publish_without_landowner_agreement_rejected(self, api):
        """PRD §3.2: "First, a `SIGNED` `LANDOWNER_USE` agreement must exist whose
        window covers the entire event: `effective_from` on or before
        `event_starts_at` and `effective_until` on or after `event_ends_at`;
        without one, publication fails with `ERR_AGREEMENT_NOT_IN_FORCE`."

        Design: Corner/state_machines/publish_without_landowner_agreement_rejected
        """
        event = create_event()
        open_registration(event["id"])
        resp = api_client.publish_event(event["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_FORCE, 409)
        reread = get_event(event["id"])
        assert reread["event_posture"] == "REGISTRATION_OPEN", (
            "rejected publish must leave the posture unchanged"
        )

    def test_publish_with_insufficient_insurance_rejected(self, api):
        """PRD §3.2: "Second, a `SIGNED` `INSURANCE_LIABILITY` agreement must exist
        whose window likewise covers the event and whose `coverage_amount_cents`
        is at least the event's `required_liability_cents`; otherwise publication
        fails with `ERR_INSURANCE_COVERAGE_INSUFFICIENT`."

        Design: Corner/state_machines/publish_with_insufficient_insurance_rejected
        """
        event = create_event(required_liability_cents=1000000)
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        add_signed_agreement(
            event["id"], "INSURANCE_LIABILITY", coverage_amount_cents=500000
        )
        open_registration(event["id"])
        resp = api_client.publish_event(event["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_COVERAGE_INSUFFICIENT, 422)
        reread = get_event(event["id"])
        assert reread["event_posture"] == "REGISTRATION_OPEN", (
            "rejected publish must leave the posture unchanged"
        )


class TestChildResourceNotFoundVariants:
    def test_child_resource_not_found_variants(self, api):
        """PRD §2.9: "The existence family maps each unresolved reference to its
        own error: an unresolvable event reference yields `ERR_EVENT_NOT_FOUND`; a
        unit, `ERR_UNIT_NOT_FOUND`; a participant or a non-null supervisor
        reference, `ERR_PARTICIPANT_NOT_FOUND`; an equipment item,
        `ERR_EQUIPMENT_NOT_FOUND`; an inspection, `ERR_INSPECTION_NOT_FOUND`; a
        site area, `ERR_AREA_NOT_FOUND`; a program slot, `ERR_SLOT_NOT_FOUND`; a
        ticket order, `ERR_ORDER_NOT_FOUND`; a parking pass, `ERR_PASS_NOT_FOUND`;
        a vendor, `ERR_VENDOR_NOT_FOUND`; an agreement, `ERR_AGREEMENT_NOT_FOUND`;
        a contingency alert, `ERR_ALERT_NOT_FOUND`; and an allocation,
        `ERR_ALLOCATION_NOT_FOUND`. All are HTTP 404."

        Design: Corner/entities/child_resource_not_found_variants
        """
        create_event()
        so1 = TEST_USERS["safety_officer_headers"]
        cases = [
            (api_client.get_equipment_item(NON_EXISTENT_UUID, ORG),
             ApiErrorId.ERR_EQUIPMENT_NOT_FOUND),
            (api_client.record_inspection(NON_EXISTENT_UUID, {"outcome": "PASS"}, so1),
             ApiErrorId.ERR_INSPECTION_NOT_FOUND),
            (api_client.get_site_area(NON_EXISTENT_UUID, ORG),
             ApiErrorId.ERR_AREA_NOT_FOUND),
            (api_client.confirm_program_slot(NON_EXISTENT_UUID, ORG),
             ApiErrorId.ERR_SLOT_NOT_FOUND),
            (api_client.get_ticket_order(NON_EXISTENT_UUID, ORG),
             ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api_client.void_parking_pass(NON_EXISTENT_UUID, ORG),
             ApiErrorId.ERR_PASS_NOT_FOUND),
            (api_client.get_vendor(NON_EXISTENT_UUID, ORG),
             ApiErrorId.ERR_VENDOR_NOT_FOUND),
            (api_client.sign_agreement(NON_EXISTENT_UUID, {"signer_name": "Nobody"}, ORG),
             ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api_client.resolve_contingency_alert(NON_EXISTENT_UUID, so1),
             ApiErrorId.ERR_ALERT_NOT_FOUND),
            (api_client.get_allocation(NON_EXISTENT_UUID, ORG),
             ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        ]
        for resp, error_id in cases:
            validate_error(resp, error_id, 404)
