"""Security: authentication, authorization (RBAC), and segregation of duties."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_rate_table_payload,
    make_active_rate_table,
    make_compliance_headers,
    make_donor,
    make_draft_agreement,
    make_gift_admin_headers,
    make_gift_officer_headers,
    make_illustration,
    make_valuation_run,
    make_verified_designation,
    reserve_version,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value outside these five names, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api.create_donor(
            {"full_name": "No Headers", "date_of_birth": "1960-01-01T00:00:00Z"},
            headers={},
        )
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401
        assert error["error_id"] == "ERR_UNAUTHENTICATED"
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestAuthorization:
    def test_wrong_role_returns_403_unauthorized(self, api, gift_officer_headers):
        """PRD §2.1: "A request whose authenticated role is not listed among
        the roles authorized for the target endpoint — including per-action
        role restrictions on shared transition endpoints — is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/giving/rate-tables` | Create a rate table in DRAFT
        (window overlap checked) | ComplianceOfficer |"

        Design: Corner/validations/wrong_role_returns_403_unauthorized
        """
        resp = api.create_rate_table(
            create_rate_table_payload(label="Nope"), gift_officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403

    def test_wrong_role_beats_not_found_unauthorized(self, api, gift_officer_headers):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and the **first** failure wins — a request that would fail two
        checks receives the error of the earlier one." The global order lists
        "2. Authorization: the acting role is permitted on this endpoint —
        `ERR_UNAUTHORIZED`" ahead of "4. Existence: every path identifier and
        every foreign-key-valued body field resolves to an existing resource,
        validated left to right — path parameters first, then body fields —
        `ERR_NOT_FOUND`."

        Design: Corner/validations/wrong_role_beats_not_found_unauthorized
        """
        # GiftOfficer may not execute agreements; the nonexistent id must not
        # leak through as a 404 ahead of the authorization failure.
        resp = api.execute_gift_agreement(NON_EXISTENT_UUID, gift_officer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403

    def test_rbac_officer_cannot_execute_rejected(self, api, gift_officer_headers):
        """PRD §4: "| POST | `/giving/gift-agreements/{agreement_id}/execute` |
        Execute a DRAFT agreement through the full gate chain |
        GiftAdministrator |"
        PRD §2.1: "A request whose authenticated role is not listed among the
        roles authorized for the target endpoint — including per-action role
        restrictions on shared transition endpoints — is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_officer_cannot_execute_rejected
        """
        donor = make_donor(full_name="RBAC Exec", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_draft_agreement(donor["id"])
        make_verified_designation(agreement["id"])

        resp = api.execute_gift_agreement(agreement["id"], gift_officer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        after = validate_success(api.get_gift_agreement(agreement["id"], gift_officer_headers))
        assert after["status"] == "DRAFT"

    def test_rbac_estate_manager_cannot_adjust_reserve_rejected(
        self, api, estate_manager_headers, compliance_headers
    ):
        """PRD §4: "| POST | `/giving/reserve-fund/adjustments` | Manual reserve
        CONTRIBUTION / WITHDRAWAL (OCC-guarded) | ComplianceOfficer |"
        PRD §2.1: "A request whose authenticated role is not listed among the
        roles authorized for the target endpoint — including per-action role
        restrictions on shared transition endpoints — is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_estate_manager_cannot_adjust_reserve_rejected
        """
        v0 = reserve_version()
        resp = api.create_reserve_adjustment(
            {
                "direction": "CONTRIBUTION",
                "amount_cents": 1000,
                "expected_reserve_fund_version": v0,
            },
            estate_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        pool = validate_success(api.get_reserve_fund(compliance_headers))
        assert pool["balance_cents"] == 0

    def test_rbac_shared_read_allowed_for_all_roles(
        self, api, gift_officer_headers, compliance_headers, estate_manager_headers, finance_steward_headers
    ):
        """PRD §4: "| GET | `/giving/rate-tables/{rate_table_id}` | Read one
        rate table | All roles |"
        PRD §4: "| GET | `/giving/donors` | List donors (filters:
        `vital_status`, `legacy_society_status`) | All roles |"

        Design: Corner/rbac/rbac_shared_read_allowed_for_all_roles
        """
        donor = make_donor(full_name="Shared Read", date_of_birth="1960-01-01T00:00:00Z")
        table = validate_success(
            api.create_rate_table(create_rate_table_payload(label="T"), compliance_headers),
            201,
        )

        # EstateManager reading a rate table.
        data = validate_success(api.get_rate_table(table["id"], estate_manager_headers))
        assert data["label"] == "T"
        # FinanceSteward listing donors.
        donors, meta = validate_paginated(api.list_donors(finance_steward_headers))
        assert meta["total_count"] == 1
        assert donors[0]["id"] == donor["id"]


class TestSegregationOfDuties:
    def test_sod_execute_by_illustration_creator_rejected(
        self, api, gift_officer_headers
    ):
        """PRD §2.1: "Three operations enforce segregation of duties by
        comparing the actor's `X-User-ID` against the recorded originator; a
        match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). First,
        executing a gift agreement that was created by booking an illustration
        requires the executing `GiftAdministrator` to differ from the
        illustration's `created_by_user_id`."

        Design: Corner/rbac/sod_execute_by_illustration_creator_rejected
        """
        creator = make_gift_officer_headers("officer-1")
        donor = make_donor(full_name="SoD Exec", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        illustration = make_illustration(
            donor["id"],
            vehicle_type="CRT_ANNUITY",
            gift_amount_cents=10000000,
            payout_rate_bps=500,
            annuitant_1_age=80,
            creator_headers=creator,
        )
        agreement = validate_success(api.book_illustration(illustration["id"], creator), 201)
        make_verified_designation(agreement["id"])

        # The illustration's creator may not execute, even in the right role.
        resp = api.execute_gift_agreement(
            agreement["id"], make_gift_admin_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 403

        executed = validate_success(
            api.execute_gift_agreement(agreement["id"], make_gift_admin_headers("admin-1"))
        )
        assert executed["status"] == "EXECUTED"
        assert executed["executed_by_user_id"] == "admin-1"

    def test_sod_valuation_post_by_creator_rejected(self, api, compliance_headers):
        """PRD §2.1: "Second, posting a valuation run requires the posting
        `ComplianceOfficer` to differ from the run's `created_by_user_id`."

        Design: Corner/rbac/sod_valuation_post_by_creator_rejected
        """
        make_active_rate_table()
        creator = make_compliance_headers("co-1")
        run = make_valuation_run(creator_headers=creator)
        assert run["created_by_user_id"] == "co-1"

        resp = api.post_valuation_run(run["id"], creator)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 403

        posted = validate_success(
            api.post_valuation_run(run["id"], make_compliance_headers("co-2"))
        )
        assert posted["status"] == "POSTED"
        assert posted["posted_by_user_id"] == "co-2"
