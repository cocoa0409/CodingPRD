"""RBAC: exclusive operations reject callers of the wrong role."""
from test_helpers import (
    create_region_payload,
    make_therapist_headers,
    setup_completed_booking_with_invoice,
    setup_region_account_therapist,
    setup_scheduling_booking,
    validate_error,
)


class TestRoleExclusiveOperations:
    def test_therapist_cannot_create_region(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/chair-massage/regions` | Create a service region |
        PlatformAdmin |"

        Design: Corner/roles/therapist_cannot_create_region
        """
        ctx = setup_region_account_therapist()
        resp = api.create_region(
            create_region_payload(code="XX", name="XX"),
            make_therapist_headers(ctx["therapist"]["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN", expected_status=403)

    def test_organizer_cannot_issue_invoice(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/chair-massage/invoices/{id}/issue` | Issue a
        DRAFT invoice (checks credit limit) | PlatformAdmin |"

        Design: Corner/roles/organizer_cannot_issue_invoice
        """
        ctx = setup_completed_booking_with_invoice(num_claims_completed=0)
        resp = api.issue_invoice(ctx["invoice"]["id"], ctx["organizer"])
        validate_error(resp, "ERR_FORBIDDEN", expected_status=403)

    def test_therapist_cannot_assign_chair(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/chair-massage/chair-slots/{id}/assign` | Assign a
        therapist to this chair | Organizer |"

        Design: Corner/roles/therapist_cannot_assign_chair
        """
        ctx = setup_scheduling_booking(assign=False)
        chair = ctx["chairs"][0]
        resp = api.assign_chair_slot(
            chair["id"],
            {"therapist_id": ctx["therapist"]["id"]},
            make_therapist_headers(ctx["therapist"]["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN", expected_status=403)
