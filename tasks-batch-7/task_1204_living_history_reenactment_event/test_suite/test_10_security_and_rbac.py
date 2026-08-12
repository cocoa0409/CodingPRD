"""Authentication, role exclusivity, and entity-backed ownership."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    create_event_payload,
    ticket_line,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_event,
    create_participant,
    declare_equipment,
    schedule_inspection,
    setup_approved_unit,
    setup_paid_order,
    setup_published_event,
    setup_registration_open_event,
    submit_participant,
)
from test_helpers.test_users import (
    make_participant_headers,
    make_spectator_headers,
    make_unit_commander_headers,
)

ORG = TEST_USERS["organizer_headers"]
AO = TEST_USERS["authenticity_officer_headers"]
SO1 = TEST_USERS["safety_officer_headers"]


class TestAuthentication:
    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` does not name one of these
        roles, or that omits `X-User-ID` on any non-creation call where an
        identity is required, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_returns_unauthenticated
        """
        event = create_event()
        resp = api_client.get_event(
            event["id"], {"X-User-ID": "test-organizer-1",
                          "Content-Type": "application/json"}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleExclusivity:
    def test_spectator_cannot_create_event_forbidden(self, api):
        """PRD §2.1: "Authorization is then per-endpoint: a caller whose role is
        not listed for the endpoint, or who fails an entity-backed ownership
        check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "`/events` | Create an event in `PLANNING` posture |
        EventOrganizer" — no other role is listed.

        Design: Corner/validations/spectator_cannot_create_event_forbidden
        """
        resp = api_client.create_event(
            create_event_payload(name="Rogue Event", site_name="Nowhere"),
            make_spectator_headers("spec-9"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_unit_commander_cannot_vet_participant(self, api):
        """PRD §3.3: "Authenticity vetting belongs to the `AuthenticityOfficer`
        alone, acting on a `SUBMITTED` record with a `decision`"
        PRD §2.1: "a caller whose role is not listed for the endpoint, or who
        fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/unit_commander_cannot_vet_participant
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        participant = create_participant(event["id"], unit_id=unit["id"])
        submit_participant(participant["id"], unit_id=unit["id"])

        resp = api_client.vet_participant(
            participant["id"], {"decision": "APPROVE"},
            make_unit_commander_headers(unit["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        reread = validate_success(api_client.get_participant(participant["id"], ORG), 200)
        assert reread["status"] == "SUBMITTED", "the denied vet changes nothing"

    def test_authenticity_officer_cannot_record_inspection(self, api):
        """PRD §3.4: "Recording an outcome likewise belongs to the
        `SafetyOfficer` and is valid only from `SCHEDULED`
        (`ERR_INVALID_INSPECTION_STATUS`)."
        PRD §2.1: "a caller whose role is not listed for the endpoint, or who
        fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/authenticity_officer_cannot_record_inspection
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"], name="Civilians of the Valley",
                                   unit_type="CIVILIAN", portrayal_name="Townsfolk")
        participant = create_participant(event["id"], unit_id=unit["id"],
                                         impression_class="CIVILIAN")
        item = declare_equipment(participant["id"], unit_id=unit["id"],
                                 item_type="TENTAGE", description="A-frame canvas tent")
        inspection = schedule_inspection(item["id"], officer="so-1",
                                         scheduled_for="2026-07-10T09:00:00Z",
                                         inspection_kind="AUTHENTICITY")

        resp = api_client.record_inspection(inspection["id"], {"outcome": "PASS"}, AO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        inspections = validate_success(api_client.list_item_inspections(item["id"], SO1), 200)
        assert inspections[0]["status"] == "SCHEDULED", (
            "the denied recording leaves the inspection untouched"
        )


class TestOwnership:
    def test_spectator_cannot_refund_others_order(self, api):
        """PRD §3.7: "Refunds move an order `PAID → REFUNDED` at the request of
        the owning spectator (ownership enforced as `ERR_FORBIDDEN`) or an
        organizer"
        PRD §2.1: "the server stores it as `buyer_user_id` on each ticket order
        the spectator creates, and ownership checks on orders and parking passes
        compare that stored `buyer_user_id` to `X-User-ID`."

        Design: Corner/rbac/spectator_cannot_refund_others_order
        """
        event = setup_published_event()
        order = setup_paid_order(event["id"], buyer="spec-1",
                                 lines=[ticket_line("ADULT_DAY", 1)])
        resp = api_client.refund_ticket_order(
            order["id"], {"reason": "PATRON_CHOICE"}, make_spectator_headers("spec-2")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        reread = validate_success(api_client.get_ticket_order(order["id"], ORG), 200)
        assert reread["status"] == "PAID", "the denied refund leaves the order PAID"

    def test_participant_cannot_withdraw_stranger(self, api):
        """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id`
        of the acting Participant; ownership checks compare the participant
        reference to `X-User-ID`, and a participant acts only on itself and its
        own equipment."
        PRD §2.1: "a caller whose role is not listed for the endpoint, or who
        fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/participant_cannot_withdraw_stranger
        """
        event = setup_registration_open_event()
        unit = setup_approved_unit(event["id"])
        pa_a = create_participant(event["id"], unit_id=unit["id"], full_name="Ada Adams")
        pa_b = create_participant(event["id"], unit_id=unit["id"], full_name="Bob Baker",
                                  age_at_event=40)

        resp = api_client.withdraw_participant(
            pa_a["id"], make_participant_headers(pa_b["id"]), {"reason": "hostile"}
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        reread = validate_success(api_client.get_participant(pa_a["id"], ORG), 200)
        assert reread["status"] == "DRAFT", "the denied withdrawal changes nothing"
