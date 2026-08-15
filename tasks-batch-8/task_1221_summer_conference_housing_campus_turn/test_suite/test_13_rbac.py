"""Role-based access control: exclusive operations and coordinator ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    create_building,
    create_building_payload,
    create_building_turn_active,
    create_group,
    create_group_with_revision,
    get_group,
    get_success_data,
    make_coordinator_headers,
    setup_confirmed_group,
    setup_finalized_invoice,
    submit_group,
    submit_screening,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
FACILITIES = TEST_USERS["facilities_headers"]
HOUSEKEEPING = TEST_USERS["housekeeping_headers"]
FINANCE = TEST_USERS["finance_headers"]
SCREENING = TEST_USERS["screening_headers"]


class TestExclusiveOperationDenial:
    def test_rbac_coordinator_cannot_confirm_group(self, api):
        """PRD endpoint table: "POST /conference-groups/{id}/confirm —
        ConferenceServicesAdmin"
        PRD: "a caller whose role is not in the endpoint's list is rejected with
        ERR_UNAUTHORIZED_ROLE (HTTP 403)."

        Design: Corner/rbac/rbac_coordinator_cannot_confirm_group
        """
        building, rooms = create_building_turn_active(name="Quebec Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev = create_group_with_revision(
            building["id"], rooms, client_name="RBAC Test", deposit_paid_cents=5000)
        submit_group(group["id"])
        # The coordinator calls confirm on their OWN group: ownership holds, but
        # the role is not in the endpoint's role list.
        resp = api.confirm_group(group["id"], make_coordinator_headers(group["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_group(group["id"])["status"] == "SUBMITTED"

    def test_rbac_housekeeping_cannot_record_payment(self, api):
        """PRD endpoint table: "POST /invoices/{id}/record-payment —
        FinanceOfficer, ConferenceServicesAdmin"
        PRD: "a caller whose role is not in the endpoint's list is rejected with
        ERR_UNAUTHORIZED_ROLE (HTTP 403)."

        Design: Corner/rbac/rbac_housekeeping_cannot_record_payment
        """
        building, rooms = create_building_turn_active(name="Sierra Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, _assignments, invoice = setup_finalized_invoice(
            building, rooms, client_name="Pay RBAC", deposit_paid_cents=5000)
        resp = api.record_payment(invoice["id"], invoice["balance_due_cents"],
                                  HOUSEKEEPING)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_invoice(invoice["id"], FINANCE))
        assert after["status"] == "FINALIZED", "no payment was recorded"

    def test_rbac_facilities_cannot_decide_screening(self, api):
        """PRD endpoint table: "POST /background-screenings/{id}/decide —
        ScreeningReviewer, ConferenceServicesAdmin"
        PRD: "a caller whose role is not in the endpoint's list is rejected with
        ERR_UNAUTHORIZED_ROLE (HTTP 403)."

        Design: Corner/rbac/rbac_facilities_cannot_decide_screening
        """
        building = create_building(name="Tango Hall", key_pool_size=5)
        group = create_group(building["id"], client_name="Screen RBAC",
                             arrival_date="2026-06-22", departure_date="2026-06-26",
                             has_minor_participants=True, deposit_paid_cents=0)
        chaperone = add_participant(group["id"], full_name="Chap One",
                                    date_of_birth="1980-01-01",
                                    role_in_group="CHAPERONE")
        screening = submit_screening(chaperone["id"], group["id"], "CONS-R")
        get_success_data(api.begin_review_screening(screening["id"], SCREENING))
        resp = api.decide_screening(screening["id"], "CLEAR", FACILITIES)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_background_screening(screening["id"], SCREENING))
        assert after["status"] == "IN_REVIEW"


class TestCoordinatorOwnership:
    def test_rbac_coordinator_forbidden_other_group(self, api):
        """PRD: "When X-User-Role is ClientCoordinator, X-User-ID is the id of
        the acting ConferenceGroup; ownership checks on any resource that
        references a ConferenceGroup compare the resource's group foreign key —
        directly, or via the parent group of the addressed participant,
        assignment, screening, or damage assessment — to X-User-ID, and a
        mismatch is rejected with ERR_FORBIDDEN_OWNERSHIP (HTTP 403)."

        Design: Corner/rbac/rbac_coordinator_forbidden_other_group
        """
        building = get_success_data(api.create_building(
            create_building_payload(name="Romeo Hall", key_pool_size=5), ADMIN))
        group_a = get_success_data(api.create_conference_group(
            {"building_id": building["id"], "client_name": "Group A",
             "contact_email": "a@x.com", "arrival_date": "2026-06-15",
             "departure_date": "2026-06-17", "contracted_bed_count": 1}, ADMIN))
        group_b = get_success_data(api.create_conference_group(
            {"building_id": building["id"], "client_name": "Group B",
             "contact_email": "b@x.com", "arrival_date": "2026-06-15",
             "departure_date": "2026-06-17", "contracted_bed_count": 1}, ADMIN))
        add_participant(group_b["id"], full_name="B One")
        # Group A's coordinator identity acts on group B: role passes, ownership fails.
        resp = api.submit_group(group_b["id"], make_coordinator_headers(group_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert get_group(group_b["id"])["status"] == "DRAFT"
