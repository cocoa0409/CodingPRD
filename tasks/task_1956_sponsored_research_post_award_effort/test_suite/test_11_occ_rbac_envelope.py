"""Optimistic concurrency, RBAC denials, response envelope shape, pagination,
and FK reverse-read discovery (PRD §2.1–§2.6)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, TEST_USERS,
    create_person_payload, create_sponsor_payload, create_award_payload,
    create_drawdown_request_payload,
    setup_sponsor_pi, create_active_award, post_expenditure,
    post_salary_expenditure, setup_salary_award, make_commitment, make_cycle,
    open_cycle, find_award_statement, certify_statement, make_person,
    make_sponsor, create_drawdown,
    setup_transfer_pair, create_submitted_transfer,
    make_pi_headers, make_research_staff_headers,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]
SO = TEST_USERS["sponsor_official_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


class TestOccDrawdownCreate:
    def test_stale_award_version_rejected_on_second_create(self, api):
        """PRD §2.6: "Creating a drawdown request requires
        `expected_award_version` matching the target award's current `version`;
        a mismatch is rejected with `ERR_STALE_AWARD_VERSION` (HTTP 412),
        because the eligible-pool computation the client priced its amount
        against may have shifted."

        Design: Corner/cross_cutting_layers/occ_drawdown_create_stale_award_version
        """
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "OC-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=100_000, cash_disbursed=True)
        v = validate_success(api.get_award(award["id"], GA), 200)["version"]
        d1 = validate_success(api.create_drawdown_request(
            create_drawdown_request_payload(award["id"], 50_000, v), GA), 201)
        assert d1["award_id"] == award["id"]
        # The create itself bumped the award version; the same observed version
        # is now stale.
        res = api.create_drawdown_request(
            create_drawdown_request_payload(award["id"], 40_000, v), GA)
        validate_error(res, ApiErrorId.ERR_STALE_AWARD_VERSION.value)


class TestOccCertifyStaleStatement:
    def _setup(self, api):
        sponsor, person, award, sal, _fr = setup_salary_award("OC-003")
        post_salary_expenditure(award["id"], sal["id"], person["id"],
                                25.0, 1, "2026-03-01T00:00:00Z")
        cycle = open_cycle(make_cycle()["id"])
        statement = find_award_statement(cycle["id"], award["id"])
        return person, award, sal, statement

    def test_payroll_cascade_bumps_statement_version(self, api):
        """PRD §2.6: "a payroll posting in the cycle window silently recomputes
        `charged_effort_pct` and bumps the statement's `version`..."
        PRD §3.4: "Its numerator is the sum of `amount_cents` over the person's
        `POSTED`, non-`TRANSFERRED_OUT` salary expenditures on the award whose
        `transaction_date` falls in the half-open cycle window. Its denominator
        is the person's monthly IBS rate — annual IBS divided by appointment
        months, rounded half-up — multiplied by the cycle's `cycle_months`."

        Design: Corner/cross_cutting_layers/occ_certify_stale_statement_after_payroll_cascade
        """
        person, award, sal, statement = self._setup(api)
        assert statement["charged_effort_pct"] == 3.47   # one 416667 posting
        post_salary_expenditure(award["id"], sal["id"], person["id"],
                                25.0, 1, "2026-04-01T00:00:00Z")
        st_after = validate_success(api.get_effort_statement(statement["id"], GA), 200)
        # 833334 / 12000000 = 6.9445% -> 6.94; single cascade bump v1 -> v2.
        assert st_after["charged_effort_pct"] == 6.94
        assert st_after["version"] == statement["version"] + 1

    def test_certify_with_stale_version_rejected(self, api):
        """PRD §2.6: "Certifying an effort statement requires
        `expected_effort_statement_version` matching the statement's current
        `version`; a mismatch is rejected with `ERR_STALE_STATEMENT_VERSION`
        (HTTP 412), because a payroll posting in the cycle window silently
        recomputes `charged_effort_pct` and bumps the statement's `version`,
        and the certifier would otherwise attest against a charged figure they
        never saw."

        Design: Corner/cross_cutting_layers/occ_certify_stale_statement_after_payroll_cascade
        """
        person, award, sal, statement = self._setup(api)
        stale_version = statement["version"]
        post_salary_expenditure(award["id"], sal["id"], person["id"],
                                25.0, 1, "2026-04-01T00:00:00Z")
        res = api.certify_effort_statement(
            statement["id"],
            {"certified_effort_pct": 3.47,
             "expected_effort_statement_version": stale_version},
            # entity-backed ownership: X-User-ID must be the person id
            make_pi_headers(person["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_STATEMENT_VERSION.value)


class TestRbacDenials:
    def test_staff_cannot_post_expenditure(self, api):
        """PRD §2.1: "`GrantsAccountant` is the central post-award accountant:
        it posts and disallows expenditures..." PRD §2.1: "a role not permitted
        on the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/staff_cannot_post_expenditure
        """
        sponsor, pi = setup_sponsor_pi()
        staff = make_person(role_type="RESEARCH_STAFF", ibs=6_000_000,
                            full_name="S. Staff")
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "RB-901",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        e = validate_success(api.create_expenditure(
            {"award_id": award["id"], "budget_line_id": lines["TRAVEL"]["id"],
             "expenditure_type": "TRAVEL", "amount_cents": 10_000,
             "transaction_date": "2026-03-01T00:00:00Z",
             "is_allocable": True, "is_reasonable": True, "is_consistent": True},
            GC), 201)
        res = api.post_expenditure(e["id"], make_research_staff_headers(staff["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_sponsor_official_cannot_create_sponsor(self, api):
        """PRD §2.1: "`SponsoredProgramsOfficer` staffs the central
        sponsored-programs office: it creates sponsors, persons, awards, and
        subawards..." PRD §2.1: "a role not permitted on the endpoint is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/sponsor_official_cannot_create_sponsor
        """
        res = api.create_sponsor(
            create_sponsor_payload(name="Rogue"), SO)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, presenting a malformed
        header, or naming a role outside the declared set is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        res = api.list_sponsors(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value,
                       expected_status=401)


class TestEnvelopeShape:
    def test_success_and_error_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format..." with meta +
        response_type + data; "All error API responses (4xx status codes)
        follow this standard envelope format" with data.error_id +
        data.message.

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        res = api.create_sponsor(
            create_sponsor_payload(name="Env Co", sponsor_type="INDUSTRY",
                                   payment_method="FIXED_PRICE_SCHEDULE",
                                   f_and_a_rate_bps=0), SPO)
        body = res.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        err_res = api.get_sponsor("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", GA)
        err_body = err_res.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_SPONSOR_NOT_FOUND"
        assert len(err_body["data"]["message"].strip()) > 0


class TestPaginationAndRoleFilter:
    def test_pagination_defaults_and_role_type_filter(self, api):
        """PRD §2.3: "The default `limit` is 10, with a minimum of 1 and a
        maximum of 100; the default `offset` is 0. The response `meta` block
        carries `limit`, `offset`, `total_count`, and `has_more` so a caller
        can page deterministically."
        PRD §4: GET /api/persons supports filter `role_type`.

        Design: Corner/endpoints/pagination_defaults_and_role_type_filter
        """
        for name in ("PI One", "PI Two", "PI Three"):
            validate_success(api.create_person(
                create_person_payload(full_name=name), SPO), 201)
        for i in range(1, 10):
            validate_success(api.create_person(
                create_person_payload(full_name=f"S{i}",
                                      role_type="RESEARCH_STAFF",
                                      institutional_base_salary_annual_cents=6_000_000),
                SPO), 201)
        page1, meta1 = validate_paginated(api.list_persons(GA))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_persons(GA, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["has_more"] is False
        pis, meta3 = validate_paginated(api.list_persons(
            GA, params={"role_type": "PRINCIPAL_INVESTIGATOR"}))
        assert len(pis) == 3
        assert meta3["total_count"] == 3


class TestFkFilteredListReverseReachability:
    def _setup(self, api):
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair(
            source_number="FK-001", target_number="FK-002")
        tr = create_submitted_transfer(e, aw_t, l_t)
        validate_success(api.approve_cost_transfer(tr["id"], GA), 200)
        return aw_s, aw_t, e

    def test_award_id_filter_returns_only_that_awards_rows(self, api):
        """PRD §4: GET /api/expenditures lists expenditures with filters
        including `award_id`, `budget_line_id`, `person_id`, `status`,
        `transferred_from_id`, `invoiced_receivable_id`, and
        `expenditure_type` ("List expenditures (filters: `award_id`,
        `budget_line_id`, `person_id`, `status`, `transferred_from_id`,
        `invoiced_receivable_id`, `expenditure_type`)").

        Design: Corner/endpoints/fk_filtered_list_reverse_reachability
        """
        aw_s, aw_t, e = self._setup(api)
        rows = validate_success(api.list_expenditures(
            GA, params={"award_id": aw_s["id"]}), 200)
        assert len(rows) == 1
        assert rows[0]["id"] == e["id"]
        assert rows[0]["status"] == "TRANSFERRED_OUT"

    def test_transferred_from_id_discovers_the_mirror(self, api):
        """PRD §3.3: "Second the system creates a mirror expenditure on the
        target award: same `amount_cents`, status `POSTED`,
        `transferred_from_id` pointing back to the source, same expenditure
        type and category, `cash_disbursed` copied, `transaction_date` copied,
        and `posted_at` set to now."
        PRD §4: "GET | `/api/expenditures` | List expenditures (filters:
        `award_id`, `budget_line_id`, `person_id`, `status`,
        `transferred_from_id`, `invoiced_receivable_id`, `expenditure_type`)".

        Design: Corner/endpoints/fk_filtered_list_reverse_reachability
        """
        aw_s, aw_t, e = self._setup(api)
        mirrors = validate_success(api.list_expenditures(
            GA, params={"transferred_from_id": e["id"]}), 200)
        assert len(mirrors) == 1
        assert mirrors[0]["amount_cents"] == 100_000
        assert mirrors[0]["status"] == "POSTED"
        assert mirrors[0]["award_id"] == aw_t["id"]
