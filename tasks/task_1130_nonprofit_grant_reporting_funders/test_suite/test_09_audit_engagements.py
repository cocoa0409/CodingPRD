"""Audit engagements: overlap geometry, auditor capacity, the advance ladder,
finding lifecycle, and grant closeout (PRD §3.8, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_engagement,
    create_engagement,
    create_engagement_in_conducted,
    create_funder,
    create_grant,
    activate_grant,
    add_budget_line,
    add_fund,
    edit_report,
    file_finding,
    make_funder_headers,
    resolve_finding,
    set_clock,
    setup_active_grant,
    start_report,
    start_review,
    submit_report,
    validate_error,
    validate_success,
    walk_report_to_accepted,
    api_client,
)

OFFICER = TEST_USERS["officer_headers"]
DIRECTOR = TEST_USERS["director_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestEngagementOverlap:
    def test_grant_engagement_strict_overlap(self, api):
        """PRD §3.8: "The window must not overlap any other non-`CLOSED`
        engagement on the same grant; because intervals are half-open,
        adjacency is allowed — one engagement ending exactly when another
        begins is not an overlap. A violation is rejected with
        `ERR_ENGAGEMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/grant_engagement_strict_overlap
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]

        e1 = create_engagement(
            gid, engagement_type="SITE_VISIT", auditor_org="AudCo",
            scheduled_start="2026-07-01T00:00:00Z",
            scheduled_end="2026-07-10T00:00:00Z",
        )
        assert e1["status"] == "SCHEDULED"

        resp = api.create_audit_engagement(
            gid,
            {
                "engagement_type": "DESK_REVIEW",
                "auditor_org": "OtherCo",
                "scheduled_start": "2026-07-05T00:00:00Z",
                "scheduled_end": "2026-07-15T00:00:00Z",
            },
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_OVERLAP)

    def test_grant_engagement_adjacency_allowed(self, api):
        """PRD §3.8: "because intervals are half-open, adjacency is allowed —
        one engagement ending exactly when another begins is not an overlap."
        PRD §3.8: "the engagement window as `scheduled_start` (inclusive) and
        `scheduled_end` (exclusive — the window is a half-open interval)."

        Design: Difficulty/resource_temporal_overlap/grant_engagement_strict_overlap
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        create_engagement(
            gid, engagement_type="SITE_VISIT", auditor_org="AudCo",
            scheduled_start="2026-07-01T00:00:00Z",
            scheduled_end="2026-07-10T00:00:00Z",
        )
        # E3 starts exactly at E1's scheduled_end: half-open adjacency.
        resp = api.create_audit_engagement(
            gid,
            {
                "engagement_type": "FINANCIAL_AUDIT",
                "auditor_org": "AudCo",
                "scheduled_start": "2026-07-10T00:00:00Z",
                "scheduled_end": "2026-07-20T00:00:00Z",
            },
            DIRECTOR,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"


class TestAuditorCapacity:
    def test_auditor_org_capacity_two_overlap(self, api):
        """PRD §3.8: "Independently, the named `auditor_org` may hold at most 2
        mutually-overlapping active engagements across the whole system; if
        creating this engagement would give the firm a third
        mutually-overlapping active engagement, creation is rejected with
        `ERR_AUDITOR_CAPACITY` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/auditor_org_capacity_two_overlap
        """
        funder = create_funder()
        grants = []
        for title in ("A", "B", "C"):
            grant = create_grant(
                funder["id"], title=title, award_amount_cents=1_000_000,
            )
            add_budget_line(grant["id"], budgeted_cents=1_000_000)
            add_fund(grant["id"], allocated_cents=1_000_000)
            activate_grant(grant["id"])
            grants.append(grant)

        e1 = create_engagement(
            grants[0]["id"], engagement_type="SITE_VISIT", auditor_org="AudCo",
            scheduled_start="2026-07-01T00:00:00Z",
            scheduled_end="2026-07-31T00:00:00Z",
        )
        assert e1["status"] == "SCHEDULED"
        e2 = create_engagement(
            grants[1]["id"], engagement_type="DESK_REVIEW", auditor_org="AudCo",
            scheduled_start="2026-07-10T00:00:00Z",
            scheduled_end="2026-08-10T00:00:00Z",
        )
        assert e2["status"] == "SCHEDULED"

        resp = api.create_audit_engagement(
            grants[2]["id"],
            {
                "engagement_type": "FINANCIAL_AUDIT",
                "auditor_org": "AudCo",
                "scheduled_start": "2026-07-15T00:00:00Z",
                "scheduled_end": "2026-07-20T00:00:00Z",
            },
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_AUDITOR_CAPACITY)

    def test_auditor_org_capacity_is_cross_grant(self, api):
        """PRD §3.8: "the named `auditor_org` may hold at most 2
        mutually-overlapping active engagements across the whole system" — the
        capacity resource is the audit firm, not the grant.

        Design: Difficulty/resource_temporal_overlap/auditor_org_capacity_two_overlap
        """
        funder = create_funder()
        grants = []
        for _ in range(2):
            grant = create_grant(
                funder["id"], award_amount_cents=1_000_000,
            )
            add_budget_line(grant["id"], budgeted_cents=1_000_000)
            add_fund(grant["id"], allocated_cents=1_000_000)
            activate_grant(grant["id"])
            grants.append(grant)

        # Two overlapping engagements for AudCo on two different grants.
        create_engagement(
            grants[0]["id"], auditor_org="AudCo",
            scheduled_start="2026-07-01T00:00:00Z",
            scheduled_end="2026-07-31T00:00:00Z",
        )
        create_engagement(
            grants[1]["id"], auditor_org="AudCo",
            scheduled_start="2026-07-10T00:00:00Z",
            scheduled_end="2026-08-10T00:00:00Z",
        )
        # A different firm on a third grant inside the same window is fine.
        other = create_engagement(
            grants[0]["id"], auditor_org="OtherCo",
            scheduled_start="2026-08-01T00:00:00Z",
            scheduled_end="2026-08-10T00:00:00Z",
        )
        assert other["auditor_org"] == "OtherCo"


class TestEngagementLifecycle:
    def test_engagement_close_blocked_by_open_finding(self, api):
        """PRD §3.8: "The final advance is guarded: every `AuditFinding` of the
        engagement must be `RESOLVED` before the engagement can close,
        otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/engagement_close_blocked_by_open_finding
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        engagement = create_engagement(
            gid, engagement_type="FINANCIAL_AUDIT",
        )
        advance_engagement(engagement["id"], steps=4)  # -> FINDINGS_ISSUED
        file_finding(engagement["id"], severity="OBSERVATION",
                     description="obs")  # stays OPEN

        resp = api.advance_audit_engagement(engagement["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_audit_engagement(engagement["id"], AUDITOR))
        assert fetched["status"] == "FINDINGS_ISSUED"

    def test_finding_reopen_cycle(self, api):
        """PRD §3.8: "The auditor then dispositions the response: resolving
        moves `RESPONSE_SUBMITTED` to `RESOLVED`, while reopening moves it back
        to `OPEN` — and the reopen loop may repeat, `RESPONSE_SUBMITTED` to
        `OPEN` to `RESPONSE_SUBMITTED` again, until the auditor is satisfied."
        PRD §3.8: "The grantee answers a finding through a `GrantsOfficer`,
        moving it from `OPEN` to `RESPONSE_SUBMITTED` and storing the supplied
        `response_text`."

        Design: Corner/state_machines/finding_reopen_cycle
        """
        ctx = setup_active_grant()
        engagement = create_engagement_in_conducted(
            ctx["grant"]["id"], engagement_type="DESK_REVIEW",
        )
        finding = file_finding(engagement["id"], severity="OBSERVATION",
                               description="obs")
        validate_success(api.respond_audit_finding(
            finding["id"], {"response_text": "r1"}, OFFICER,
        ))

        reopened = validate_success(api.reopen_audit_finding(finding["id"], AUDITOR))
        assert reopened["status"] == "OPEN"

        responded = validate_success(api.respond_audit_finding(
            finding["id"], {"response_text": "r2"}, OFFICER,
        ))
        assert responded["status"] == "RESPONSE_SUBMITTED"
        assert responded["response_text"] == "r2"

    def test_finding_respond_on_resolved_rejected(self, api):
        """PRD §3.8: "Responding to a finding that is not `OPEN` is rejected
        with `ERR_FINDING_NOT_OPEN` (HTTP 409)."

        Design: Corner/errors/finding_respond_on_resolved_rejected
        """
        ctx = setup_active_grant()
        engagement = create_engagement_in_conducted(
            ctx["grant"]["id"], engagement_type="DESK_REVIEW",
        )
        finding = file_finding(engagement["id"], severity="OBSERVATION",
                               description="obs")
        resolve_finding(finding["id"])

        resp = api.respond_audit_finding(
            finding["id"], {"response_text": "again"}, OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_FINDING_NOT_OPEN)


class TestGrantCloseout:
    def test_final_report_accept_moves_grant_to_closeout(self, api):
        """PRD §3.4: "Accepting the `FINAL` report has a cross-entity cascade:
        the grant itself transitions from `ACTIVE` to `CLOSEOUT`."
        PRD §3.2: "A grant whose final report has been accepted moves
        automatically from `ACTIVE` to `CLOSEOUT`."

        Design: Corner/state_machines/final_report_accept_moves_grant_to_closeout
        """
        ctx = setup_active_grant()
        funder_id = ctx["funder"]["id"]
        r4 = ctx["reports"][3]  # FINAL period of the QUARTERLY calendar
        assert r4["period_type"] == "FINAL"

        set_clock("2027-03-15T00:00:00Z")
        start_report(r4["id"])
        edit_report(r4["id"])
        submit_report(r4["id"])
        start_review(r4["id"], funder_id)
        validate_success(api.accept_report(
            r4["id"], make_funder_headers(funder_id),
        ))

        grant = validate_success(api.get_grant(ctx["grant"]["id"], OFFICER))
        assert grant["status"] == "CLOSEOUT", (
            f"accepting the FINAL report must bubble the grant to CLOSEOUT, "
            f"got {grant['status']}"
        )

    def test_grant_closeout_from_active_rejected(self, api):
        """PRD §3.2: "A grant whose final report has been accepted moves
        automatically from `ACTIVE` to `CLOSEOUT`, and a `ProgramDirector` then
        closes it, moving `CLOSEOUT` to `CLOSED`." — the only closeout arc is
        from CLOSEOUT, so closeout from ACTIVE is a generic state-machine
        rejection.
        PRD §5: `ERR_INVALID_STATE` (409) is the "generic state-machine
        rejection: trigger not valid from current state".

        Design: Corner/state_machines/grant_closeout_from_active_rejected
        """
        ctx = setup_active_grant()
        resp = api.closeout_grant(ctx["grant"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
