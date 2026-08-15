"""Authentication, role authorization, and party-ownership checks (PRD §2.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PARTIES,
    TEST_USERS,
    build_user_headers,
    create_draft_holdback,
    find_approval,
    get_approvals,
    get_holdback,
    list_inspections,
    make_buyer_headers,
    make_inspector_headers,
    make_lender_headers,
    schedule_inspection,
    setup_active_holdback,
    setup_escrow_file,
    setup_pending_holdback,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or is not one of these seven values, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.9: "the server evaluates them in a fixed order and returns the error of the first check that fails"

        A headerless request against a nonexistent file is 401 — auth precedes
        even the not-found check.

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        resp = api.get_file(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unknown_role_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or is not one of these seven values, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        headers = {"X-User-ID": "somebody", "X-User-Role": "SuperAdmin"}
        resp = api.get_file(NON_EXISTENT_UUID, headers=headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_buyer_cannot_create_escrow_file(self, api):
        """PRD §2.1: "A well-authenticated caller whose role is not in the target endpoint's allowed role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST | `/escrow/files` | Open an escrow file for a property transaction | EscrowOfficer"

        Design: Corner/validations/buyer_cannot_create_escrow_file
        """
        resp = api.create_file(
            {"property_address": "9 Nowhere Rd", "closing_date": "2026-08-01",
             "buyer_user_id": "buyer_1", "seller_user_id": "seller_1",
             "lender_user_id": "lender_1"},
            TEST_USERS["buyer_1_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_officer_cannot_submit_bid(self, api):
        """PRD §2.1: "A well-authenticated caller whose role is not in the target endpoint's allowed role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST | `/escrow/bids` | Contractor submits a bid on an ACTIVE holdback | Contractor"

        The money administrator cannot also be the bidding contractor.

        Design: Corner/rbac/officer_cannot_submit_bid
        """
        ctx = setup_active_holdback()
        resp = api.create_bid(
            {"holdback_id": ctx["holdback"]["id"], "amount_cents": 210000,
             "scope_text": "Officer bid"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_contractor_cannot_report_inspection(self, api):
        """PRD §2.1: "A well-authenticated caller whose role is not in the target endpoint's allowed role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST | `/escrow/inspections/{id}/report` | Assigned inspector reports PASSED or FAILED | Inspector"

        The party performing the work cannot verify it; the inspection stays
        PLANNED.

        Design: Corner/rbac/contractor_cannot_report_inspection
        """
        ctx = setup_active_holdback()
        ins = schedule_inspection(ctx["holdback"]["id"], purpose="DRAW_VERIFICATION")

        resp = api.report_inspection(ins["id"], {"result": "PASSED"},
                                     TEST_USERS["contr_1_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        statuses = {i["id"]: i["status"]
                    for i in list_inspections(ctx["holdback"]["id"])}
        assert statuses[ins["id"]] == "PLANNED"


class TestSharedReads:
    @pytest.mark.parametrize(
        "role", ["EscrowOfficer", "Buyer", "Seller", "Lender", "Insurer",
                 "Contractor", "Inspector"]
    )
    def test_all_roles_can_read_holdback(self, api, role):
        """PRD §4: "GET | `/escrow/holdbacks/{id}` | Get a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector"
        PRD §2.1: "`X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity."

        Every authenticated role may read a holdback, including a least
        privileged role with a user id not on the file.

        Design: Corner/rbac/all_roles_can_read_holdback
        """
        file = setup_escrow_file(with_insurer=True)
        hb = create_draft_holdback(file["id"])

        headers = build_user_headers(f"reader-{role.lower()}-9", role)
        data = validate_success(api.get_holdback(hb["id"], headers), 200)
        assert data["status"] == "DRAFT"
        assert data["id"] == hb["id"]


class TestPartyOwnership:
    def test_non_party_buyer_cannot_select_bid(self, api):
        """PRD §3.3: "Selection belongs to the buyer of record: the caller's user id must equal the file's `buyer_user_id`, failing which the attempt is `ERR_NOT_FILE_PARTY`."
        PRD §2.1: "A mismatch on any such check is rejected with `ERR_NOT_FILE_PARTY` (HTTP 403)."

        Role Buyer is allowed on select, but buyer_2 is not the buyer of
        record; the bid remains SUBMITTED.

        Design: Corner/validations/non_party_buyer_cannot_select_bid
        """
        ctx = setup_active_holdback()
        bid = submit_bid(ctx["holdback"]["id"])

        resp = api.select_bid(bid["id"], make_buyer_headers("buyer_2"))
        validate_error(resp, ApiErrorId.ERR_NOT_FILE_PARTY)

        data, _ = validate_paginated(api.list_bids(ctx["holdback"]["id"], OFFICER))
        assert data[0]["status"] == "SUBMITTED"

    def test_lender_cannot_decide_insurer_approval(self, api):
        """PRD §3.2: "The lender and insurer of record decide their own approvals. The caller's role must match the approval's `approver_role` and the caller's user id must match the file's corresponding `lender_user_id` or `insurer_user_id`; anyone else is turned away with `ERR_NOT_FILE_PARTY`."

        Approval ownership is per-row: the INSURER approval rejects the
        lender's user id.

        Design: Corner/validations/lender_cannot_decide_insurer_approval
        """
        ctx = setup_pending_holdback(with_insurer=True)
        file, hb = ctx["file"], ctx["holdback"]
        insurer_ap = find_approval(ctx["approvals"], "INSURER")
        assert insurer_ap["approver_role"] == "INSURER"

        resp = api.decide_approval(insurer_ap["id"], {"decision": "APPROVED"},
                                   make_lender_headers(file["lender_user_id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FILE_PARTY)

        approvals = get_approvals(hb["id"])
        assert find_approval(approvals, "INSURER")["status"] == "REQUESTED"
        assert get_holdback(hb["id"])["status"] == "PENDING_APPROVALS"

    def test_unassigned_inspector_cannot_report(self, api):
        """PRD §3.4: "Reporting belongs to the assigned inspector: the caller's user id must equal the inspection's `inspector_user_id` (`ERR_NOT_FILE_PARTY`), and the inspection must still be `PLANNED` (`ERR_INSPECTION_NOT_PLANNED`)."

        Design: Corner/validations/unassigned_inspector_cannot_report
        """
        ctx = setup_active_holdback()
        ins = schedule_inspection(ctx["holdback"]["id"], purpose="DRAW_VERIFICATION")

        resp = api.report_inspection(ins["id"], {"result": "PASSED"},
                                     make_inspector_headers(PARTIES["inspector_b"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FILE_PARTY)

        statuses = {i["id"]: i["status"]
                    for i in list_inspections(ctx["holdback"]["id"])}
        assert statuses[ins["id"]] == "PLANNED"
