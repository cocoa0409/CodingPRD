"""Role-based access control: entity-backed qualification and read-only roles."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]
EXEC = th.TEST_USERS["executive_director_headers"]


class TestEntityBackedRoles:
    def test_non_officer_claiming_chair_role_rejected(self, api):
        """PRD §2.1: "Three roles are entity-backed by the board roster. When
        `X-User-Role` is `BoardChair`, `X-User-ID` must be the `id` of an `ACTIVE`
        `BoardMember` whose `officer_role` is `CHAIR`; when `X-User-Role` is
        `Treasurer`, `X-User-ID` must be the `id` of an `ACTIVE` `BoardMember` whose
        `officer_role` is `TREASURER`; when `X-User-Role` is `BoardDirector`,
        `X-User-ID` must be the `id` of any `ACTIVE` `BoardMember`. In all three
        cases the member must belong to the nonprofit being acted on, and ownership
        checks on any resource that references a `BoardMember` compare the
        resource's foreign-key field to `X-User-ID`. A caller who fails this
        qualification is rejected with `ERR_IDENTITY_NOT_QUALIFIED` (HTTP 403)."

        Design: Corner/rbac/non_officer_claiming_chair_role_rejected
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-RB-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        meeting = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z")

        # D1 is ACTIVE but officer_role NONE — not the CHAIR officer
        resp = api.call_to_order(
            meeting["id"], {"attendance": [chair["id"], d1["id"]]},
            th.make_board_chair_headers(d1["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_IDENTITY_NOT_QUALIFIED, 403)

        called = th.validate_success(api.call_to_order(
            meeting["id"], {"attendance": [chair["id"], d1["id"]]},
            th.make_board_chair_headers(chair["id"])))
        assert called["status"] == "IN_SESSION"

    def test_treasurer_endpoints_require_officer_role(self, api):
        """PRD §2.1: "when `X-User-Role` is `Treasurer`, `X-User-ID` must be the
        `id` of an `ACTIVE` `BoardMember` whose `officer_role` is `TREASURER`"
        PRD §2.1: "A caller who fails this qualification is rejected with
        `ERR_IDENTITY_NOT_QUALIFIED` (HTTP 403)."

        Design: Corner/rbac/treasurer_endpoints_require_officer_role
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-RB4-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        d1 = sc["members"][1]
        payload = th.create_filing_payload(np_id, 2026, total_revenue_cents=100,
                                           total_expenses_cents=60,
                                           contributions_cents=70,
                                           program_service_revenue_cents=20,
                                           preparer_user_id="staff-1")

        # D1 is ACTIVE but officer_role NONE — not the TREASURER officer
        resp = api.create_filing(payload, th.make_treasurer_headers(d1["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_IDENTITY_NOT_QUALIFIED, 403)

        # the identical payload succeeds as GovernanceAdmin (a shared operation)
        created = th.validate_success(api.create_filing(payload, ADMIN), 201)
        th.assert_filing(created)
        assert created["nonprofit_id"] == np_id


class TestReadOnlyRole:
    def test_executive_director_is_read_only(self, api):
        """PRD §2.1: "The `ExecutiveDirector` role is a read-only observer,
        deliberately excluded from every evaluation and governance write as a matter
        of segregation from their own evaluation."
        PRD §2.1: "Access to each operation is restricted to a designated list of
        roles; a caller whose role is not on the endpoint's list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/executive_director_is_read_only
        """
        org = fx.create_nonprofit(name="O", ein="EIN-RB3-1", receipts=1_000_000)

        fetched = th.validate_success(api.get_nonprofit(org["id"], EXEC))
        assert fetched["id"] == org["id"], "the read-only role passes GET endpoints"

        resp = api.create_meeting(
            th.create_meeting_payload(org["id"],
                                      scheduled_start="2026-08-05T10:00:00Z",
                                      duration_minutes=60, notice_waived=True),
            EXEC)
        th.validate_error(resp, th.ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
