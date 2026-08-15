"""Per-capita tax reports: snapshot pinning, lifecycle, SoD, OCC, supersede."""
import pytest

from test_helpers import (
    LOCAL_ADMIN_1_HEADERS,
    SECRETARY_TREASURER_1_HEADERS,
    ST,
    ApiErrorId,
    assert_percapita_report,
    create_percapita_report_payload,
    get_local,
    get_member,
    get_success_data,
    is_valid_uuid,
    list_member_notices,
    make_classification,
    make_local,
    make_local_admin_headers,
    make_member,
    make_member_headers,
    make_payment,
    make_percapita_report,
    run_period,
    send_notice,
    set_clock,
    setup_flat_local_with_journeyman,
    setup_pct_local_with_journeyman,
    sweep_delinquency,
    validate_error,
    validate_success,
)


class TestLifecycle:
    def test_percapita_report_lifecycle_happy_path(self, api):
        """PRD section on per-capita tax: "Creation pins an immutable snapshot:
        `member_count`, the countable headcount at that instant; `rate_cents`,
        copied from the local's `per_capita_rate_cents`; and `tax_due_cents`,
        the product of the two." The report then moves DRAFT -> APPROVED ->
        SUBMITTED -> PAID.

        Design: Corner/state_machines/percapita_report_lifecycle_happy_path
        """
        local, cls = setup_pct_local_with_journeyman()
        make_member(local["id"], cls["id"], full_name="Count Cora", member_number="M-001")
        set_clock("2026-08-01T00:00:00Z")
        report = make_percapita_report(local["id"], "2026-08")
        assert_percapita_report(report)
        assert report["status"] == "DRAFT"
        assert report["member_count"] == 1
        assert report["rate_cents"] == 1500, "pinned from the local at creation"
        assert report["tax_due_cents"] == 1500
        approved = validate_success(api.approve_percapita_report(report["id"], LOCAL_ADMIN_1_HEADERS), 200)
        assert approved["status"] == "APPROVED"
        submitted = validate_success(api.submit_percapita_report(report["id"], SECRETARY_TREASURER_1_HEADERS), 200)
        assert submitted["status"] == "SUBMITTED"
        paid = validate_success(api.mark_percapita_report_paid(report["id"], SECRETARY_TREASURER_1_HEADERS), 200)
        assert paid["status"] == "PAID"

    def test_submit_draft_report_rejected(self, api):
        """PRD section on per-capita tax: "A `SecretaryTreasurer` then submits
        the `APPROVED` report, moving it to `SUBMITTED`" — a DRAFT fails the
        state guard (`ERR_REPORT_STATE_FORBIDDEN`, the validation order's
        per-capita state-guard error).

        Design: Corner/errors/submit_draft_report_rejected
        """
        local = make_local("PCT", name="Local 100")
        set_clock("2026-08-01T00:00:00Z")
        report = make_percapita_report(local["id"], "2026-08")
        resp = api.submit_percapita_report(report["id"], SECRETARY_TREASURER_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_REPORT_STATE_FORBIDDEN)


class TestApprovalGuards:
    def test_stale_percapita_rate_blocks_approve(self, api, parentbody_admin_headers):
        """PRD section on per-capita approval: "the local's current
        `per_capita_rate_cents` must still equal the report's pinned
        `rate_cents` — a rate change after creation forces re-creation,
        surfacing `ERR_STALE_PER_CAPITA_RATE` at approval."

        Design: Corner/validations/stale_percapita_rate_blocks_approve
        """
        local = make_local("PCT", name="Local 100")
        set_clock("2026-08-01T00:00:00Z")
        report = make_percapita_report(local["id"], "2026-08")
        assert report["rate_cents"] == 1500
        validate_success(api.update_local(local["id"], {"per_capita_rate_cents": 2000}, parentbody_admin_headers), 200)
        resp = api.approve_percapita_report(report["id"], LOCAL_ADMIN_1_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STALE_PER_CAPITA_RATE)

    def test_clerk_cannot_approve_percapita_report(self, api, office_clerk_headers):
        """PRD section on roles: "A request whose role is declared but not
        permitted on the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." The endpoint table
        authorizes only LocalAdmin to approve a per-capita report.

        Design: Corner/rbac/clerk_cannot_approve_percapita_report
        """
        local = make_local("PCT", name="Local 100")
        set_clock("2026-08-01T00:00:00Z")
        report = make_percapita_report(local["id"], "2026-08")
        resp = api.approve_percapita_report(report["id"], office_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_sod_percapita_creator_cannot_approve(self, api):
        """PRD section on segregation of duties: "a per-capita report is
        created by a `SecretaryTreasurer`, recorded as `created_by_user_id`,
        but may only be approved by a `LocalAdmin` whose `X-User-ID` differs
        from the creator's; a same-operator approval is rejected with
        `ERR_SEGREGATION_OF_DUTIES`".

        Design: Corner/rbac/sod_percapita_creator_cannot_approve
        """
        local = make_local("PCT", name="Local 100")
        set_clock("2026-08-01T00:00:00Z")
        report = make_percapita_report(local["id"], "2026-08")
        assert report["created_by_user_id"] == "st_1"
        resp = api.approve_percapita_report(report["id"], make_local_admin_headers("st_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


class TestCreateOccAndSupersede:
    def test_occ_percapita_stale_local_version_rejected(self, api):
        """PRD section on optimistic concurrency: "If `expected_local_version`
        does not equal the local's current `version`, the creation is rejected
        with `ERR_STALE_LOCAL_VERSION` (HTTP 412)." Creation increments the
        local's version, so replaying the observed version is stale.

        Design: Corner/cross_cutting_layers/occ_percapita_stale_local_version_rejected
        """
        local = make_local("PCT", name="Local 100")
        set_clock("2026-08-01T00:00:00Z")
        observed = local["version"]
        first = validate_success(
            api.create_percapita_report(
                local["id"], create_percapita_report_payload("2026-08", observed),
                SECRETARY_TREASURER_1_HEADERS,
            ),
            201,
        )
        assert is_valid_uuid(first["id"])
        resp = api.create_percapita_report(
            local["id"], create_percapita_report_payload("2026-08", observed),
            SECRETARY_TREASURER_1_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_LOCAL_VERSION, 412)

    def test_percapita_draft_supersede_with_fresh_version(self, api):
        """PRD section on per-capita tax: "Creating a report for a local and
        period that already has a `DRAFT` report supersedes that draft to
        `SUPERSEDED`".

        Design: Corner/cross_cutting_layers/percapita_draft_supersede_with_fresh_version
        """
        local = make_local("PCT", name="Local 100")
        set_clock("2026-08-01T00:00:00Z")
        first = make_percapita_report(local["id"], "2026-08")
        second = make_percapita_report(local["id"], "2026-08")
        assert second["status"] == "DRAFT"
        superseded = get_success_data(
            api.list_percapita_reports(local["id"], ST, params={"status": "SUPERSEDED"})
        )
        assert len(superseded) == 1 and superseded[0]["id"] == first["id"], (
            "the first DRAFT flipped to SUPERSEDED"
        )


class TestHeadcountInputSet:
    def test_per_capita_input_set_filters_status_and_exemption(self, api):
        """PRD section on per-capita tax: "the countable set keeps members
        whose status is `ACTIVE` or `DELINQUENT`, whose classification is not
        `per_capita_exempt`, and who do not have a completed transfer into the
        local with an effective period strictly later than the report period."
        A SUSPENDED member and a per-capita-exempt retiree are both excluded.

        Design: Corner/calculations/per_capita_input_set_filters_status_and_exemption
        """
        local = make_local("FLAT", name="Local 200")
        cls_j = make_classification(local["id"], "JOURNEYMAN", 0)
        cls_r = make_classification(
            local["id"], "RETIREE", 0, flat_dues_cents=1000, per_capita_exempt=True
        )
        payer = make_member(local["id"], cls_j["id"], full_name="Paying Pat", member_number="M-001")
        delinquent = make_member(local["id"], cls_j["id"], full_name="Del Dan", member_number="M-002")
        retiree = make_member(local["id"], cls_r["id"], full_name="Retired Ruth", member_number="M-003", joined_at="2020-01-15")
        suspendee = make_member(local["id"], cls_j["id"], full_name="Susp Sue", member_number="M-004")
        run_period(local["id"], "2026-05")
        run_period(local["id"], "2026-06")
        make_payment(payer["id"], 10000)  # settle both 5000 periods
        set_clock("2026-08-01T00:00:00Z")
        sweep_delinquency(local["id"])
        notice = list_member_notices(suspendee["id"])[0]
        send_notice(suspendee["id"], notice["id"])
        set_clock("2026-08-12T00:00:00Z")
        sweep_delinquency(local["id"])
        assert get_member(delinquent["id"])["status"] == "DELINQUENT"
        assert get_member(suspendee["id"])["status"] == "SUSPENDED"
        assert get_member(retiree["id"])["status"] == "ACTIVE"
        report = make_percapita_report(local["id"], "2026-08")
        assert report["member_count"] == 2, "ACTIVE journeyman + DELINQUENT member only"
        assert report["tax_due_cents"] == 3000, "2 x 1500"
