"""The issuance gates: state, badge-overlap, delinquency, and quota."""
from test_helpers import (
    ACS,
    BO,
    ApiErrorId,
    api_client,
    create_applicant,
    create_sponsor,
    get_application,
    get_badge,
    issue_badge,
    open_application,
    record_chrc_fail,
    record_chrc_pass,
    record_sta_cleared,
    record_training,
    report_lost,
    set_clock,
    setup_issued_badge,
    setup_ready_application,
    validate_error,
    validate_success,
)


class TestValidationPriorityPairs:

    def _sponsor_with_badge_and_denied_application(self):
        ctx = setup_issued_badge(sponsor_code="PP", sponsor_name="PrimePark",
                                 badge_number="B701", full_name="Pia Quill",
                                 government_id_number="G9001",
                                 date_of_birth="1990-02-20")
        sponsor, applicant = ctx["sponsor"], ctx["applicant"]
        ap2 = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        denied = record_chrc_fail(ap2["id"])
        return ctx, ap2, denied

    def test_issue_denied_application_state_beats_badge_constraint(self):
        """PRD section 2.6: "Because of this ordering, the badge-issuance step
        rejects an application that is not `READY` with
        `ERR_APPLICATION_NOT_READY` before it ever considers whether the
        applicant already holds a conflicting badge, and it reports a
        delinquent sponsor with `ERR_SPONSOR_DELINQUENT` before it reports an
        exhausted quota with `ERR_SPONSOR_QUOTA_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/issue_denied_application_state_beats_badge_constraint
        """
        _, ap2, denied = self._sponsor_with_badge_and_denied_application()
        assert denied["status"] == "DENIED"

        resp = api_client.issue_badge(ap2["id"], {"badge_number": "B702"}, BO)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_READY)

    def test_issue_denied_leaves_both_records_unchanged(self):
        """PRD section 3.2: "A `FAIL` outcome instead stamps `chrc_outcome`
        as `FAIL`, sets `denial_reason` to `CHRC_FAILED`, and terminates the
        application in `DENIED`."
        PRD section 3.4: "The applicant must not already hold another badge
        of the same `badge_class` in `ACTIVE`, `SUSPENDED`, `LOST`, or
        `STOLEN` status whose validity window — the half-open interval from
        its `issued_at` up to but not including its `expires_at` — covers the
        issuance instant, else `ERR_ACTIVE_BADGE_EXISTS`".

        Design: Difficulty/priority_pair_validation_conflict/issue_denied_application_state_beats_badge_constraint
        """
        ctx, ap2, _ = self._sponsor_with_badge_and_denied_application()

        resp = api_client.issue_badge(ap2["id"], {"badge_number": "B702"}, BO)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_READY)

        app = get_application(ap2["id"])
        assert app["status"] == "DENIED"
        assert app["denial_reason"] == "CHRC_FAILED"
        assert get_badge(ctx["badge"]["id"])["status"] == "ACTIVE", \
            "the pre-existing ACTIVE badge is untouched by the failed issuance"

    def test_issue_active_badge_constraint_beats_sponsor_quota(self):
        """PRD section 2.6: "the server evaluates validations in a fixed
        priority order, and the first failing rule determines the error
        returned."
        PRD section 2.6: "7. **Uniqueness and segregation.** ... failing with
        `ERR_OPEN_APPLICATION_EXISTS`, `ERR_ACTIVE_BADGE_EXISTS`,
        `ERR_BADGE_NUMBER_TAKEN`, or `ERR_SEGREGATION_OF_DUTIES`."
        PRD section 2.6: "10. **Sponsor quota.** Issuance is blocked at the
        sponsor's badge quota, failing with `ERR_SPONSOR_QUOTA_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/issue_active_badge_constraint_beats_sponsor_quota
        """
        ctx = setup_issued_badge(sponsor_code="QQ", sponsor_name="QuickQueue",
                                 quota=1, badge_number="B801",
                                 full_name="Quinn Rapp",
                                 government_id_number="G9101",
                                 date_of_birth="1993-03-21")
        sponsor, applicant = ctx["sponsor"], ctx["applicant"]
        ap2 = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        record_chrc_pass(ap2["id"])
        sta = record_sta_cleared(ap2["id"])
        assert sta["status"] == "READY", \
            "applicant-level training from the first pipeline keeps ap2 READY"

        resp = api_client.issue_badge(ap2["id"], {"badge_number": "B802"}, BO)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_BADGE_EXISTS)

    def test_issue_active_badge_error_fires_at_full_quota(self):
        """PRD section 3.4: "The applicant must not already hold another badge
        of the same `badge_class` in `ACTIVE`, `SUSPENDED`, `LOST`, or
        `STOLEN` status whose validity window — the half-open interval from
        its `issued_at` up to but not including its `expires_at` — covers the
        issuance instant, else `ERR_ACTIVE_BADGE_EXISTS`; because the interval
        is half-open, an old badge expiring exactly at the issuance instant
        does not conflict."
        PRD section 3.4: "And the sponsor's `active_badge_count` must be below
        its `active_badge_quota`, else `ERR_SPONSOR_QUOTA_EXCEEDED` — a
        sponsor sitting exactly at its quota is blocked, while one badge of
        headroom is enough to proceed."

        Design: Difficulty/priority_pair_validation_conflict/issue_active_badge_constraint_beats_sponsor_quota
        """
        ctx = setup_issued_badge(sponsor_code="QQ", sponsor_name="QuickQueue",
                                 quota=1, badge_number="B801",
                                 full_name="Quinn Rapp",
                                 government_id_number="G9101",
                                 date_of_birth="1993-03-21")
        sponsor = ctx["sponsor"]
        assert validate_success(
            api_client.get_sponsor(sponsor["id"], BO))["active_badge_count"] == 1

        applicant = ctx["applicant"]
        ap2 = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        record_chrc_pass(ap2["id"])
        record_sta_cleared(ap2["id"])

        resp = api_client.issue_badge(ap2["id"], {"badge_number": "B802"}, BO)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_BADGE_EXISTS)
        assert validate_success(
            api_client.get_sponsor(sponsor["id"], BO))["active_badge_count"] == 1, \
            "the rejected issuance added nothing"


class TestSponsorQuotaBoundary:

    def _three_ready_applications(self):
        sponsor = create_sponsor(sponsor_code="QT", name="QualityTrans",
                                 active_badge_quota=2)
        roster = [
            ("Sam Tull", "1990-05-23", "G9301"),
            ("Tess Ulm", "1991-06-24", "G9302"),
            ("Ulf Vann", "1992-07-25", "G9303"),
        ]
        apps = []
        for name, dob, gid in roster:
            a = create_applicant(sponsor["id"], full_name=name,
                                 date_of_birth=dob, government_id_number=gid)
            app, _ = setup_ready_application(sponsor["id"], a["id"],
                                             badge_class="STERILE")
            apps.append(app)
        return sponsor, apps

    def test_quota_boundary_count_equals_quota(self):
        """PRD section 3.4: "And the sponsor's `active_badge_count` must be
        below its `active_badge_quota`, else `ERR_SPONSOR_QUOTA_EXCEEDED` — a
        sponsor sitting exactly at its quota is blocked, while one badge of
        headroom is enough to proceed."

        Design: Difficulty/boundary_precision_check/sponsor_quota_boundary_count_equals_quota
        """
        _, apps = self._three_ready_applications()

        ok1 = issue_badge(apps[0]["id"], "B1001")
        assert ok1["status"] == "ACTIVE", "count 0 < quota 2"
        ok2 = issue_badge(apps[1]["id"], "B1002")
        assert ok2["status"] == "ACTIVE", "count 1 == quota - 1 still proceeds"

        resp = api_client.issue_badge(apps[2]["id"], {"badge_number": "B1003"}, BO)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_QUOTA_EXCEEDED)

    def test_quota_rejection_leaves_count_unchanged(self):
        """PRD section 2.8: "The count is recomputed whenever a badge enters
        or leaves those two statuses — it rises by one at issuance, falls by
        one when a badge is deactivated, and is unchanged by a replacement,
        which deactivates one badge and issues another in the same step."
        PRD section 3.4: "And the sponsor's `active_badge_count` must be below
        its `active_badge_quota`, else `ERR_SPONSOR_QUOTA_EXCEEDED` — a
        sponsor sitting exactly at its quota is blocked, while one badge of
        headroom is enough to proceed."

        Design: Difficulty/boundary_precision_check/sponsor_quota_boundary_count_equals_quota
        """
        sponsor, apps = self._three_ready_applications()
        issue_badge(apps[0]["id"], "B1001")
        issue_badge(apps[1]["id"], "B1002")

        resp = api_client.issue_badge(apps[2]["id"], {"badge_number": "B1003"}, BO)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_QUOTA_EXCEEDED)

        count = validate_success(
            api_client.get_sponsor(sponsor["id"], BO))["active_badge_count"]
        assert count == 2, "the rejected issuance added nothing"


class TestBadgeNumberUniqueness:

    def test_duplicate_badge_number_rejected(self):
        """PRD section 3.4: "A `BadgingOfficer` issues the credential for a
        `READY` application by presenting a `badge_number`, which must be
        globally unique across all badges ever printed — a reused number is
        refused with `ERR_BADGE_NUMBER_TAKEN`."

        Design: Corner/validations/duplicate_badge_number_rejected
        """
        sponsor = create_sponsor()
        a1 = create_applicant(sponsor["id"])
        app1, _ = setup_ready_application(sponsor["id"], a1["id"],
                                          badge_class="STERILE")
        a2 = create_applicant(sponsor["id"], full_name="Ben Okafor",
                              date_of_birth="1988-05-02",
                              government_id_number="G1002")
        app2, _ = setup_ready_application(sponsor["id"], a2["id"],
                                          badge_class="STERILE")

        issue_badge(app1["id"], "B900")
        resp = api_client.issue_badge(app2["id"], {"badge_number": "B900"}, BO)
        validate_error(resp, ApiErrorId.ERR_BADGE_NUMBER_TAKEN)


class TestSponsorDelinquencyGate:

    def _setup_delinquency_scenario(self):
        sponsor = create_sponsor()
        a1 = create_applicant(sponsor["id"])
        app1, _ = setup_ready_application(sponsor["id"], a1["id"],
                                          badge_class="STERILE")
        b1 = issue_badge(app1["id"], "B1301")

        a2 = create_applicant(sponsor["id"], full_name="Ben Okafor",
                              date_of_birth="1988-05-02",
                              government_id_number="G1002")
        app2, _ = setup_ready_application(sponsor["id"], a2["id"],
                                          badge_class="STERILE")

        set_clock("2026-08-10T00:00:00Z")
        report_lost(b1["id"], report_type="LOST")

        set_clock("2026-09-08T00:00:00Z")
        a3 = create_applicant(sponsor["id"], full_name="Cory Pell",
                              date_of_birth="1995-03-03",
                              government_id_number="G1003")
        app3, _ = setup_ready_application(
            sponsor["id"], a3["id"], badge_class="STERILE",
            completed_at="2026-09-01T00:00:00Z",
            fingerprint_submitted_at="2026-09-08T00:00:00Z")
        return sponsor, b1, app2, app3

    def test_sponsor_delinquency_blocks_issuance_at_return_deadline(self):
        """PRD section 2.8: "A sponsor is delinquent when any of its badges
        sits in `LOST`, `STOLEN`, `EXPIRED`, or `REVOKED` status with a
        `return_deadline` at or before the current logical clock — the overdue
        comparison is inclusive, so a badge whose return deadline is exactly
        now already counts against the sponsor. Issuance is refused while the
        sponsor is delinquent".

        Design: Corner/validations/sponsor_delinquency_blocks_issuance_at_return_deadline
        """
        _, b1, app2, app3 = self._setup_delinquency_scenario()
        assert get_badge(b1["id"])["return_deadline"] == "2026-09-09T00:00:00Z"

        ok = issue_badge(app2["id"], "B1302")
        assert ok["status"] == "ACTIVE", \
            "2026-09-08: the deadline has not yet been reached"

        set_clock("2026-09-09T00:00:00Z")
        resp = api_client.issue_badge(app3["id"], {"badge_number": "B1303"}, BO)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_DELINQUENT)


class TestBadgeIdentityWindowHalfOpen:

    def _setup_window_overlap(self):
        ctx = setup_issued_badge(sponsor_code="HW", sponsor_name="HubWest",
                                 badge_number="B1301", full_name="Xenia Zahn",
                                 government_id_number="G9601",
                                 date_of_birth="1995-10-28",
                                 completed_at="2026-07-10T00:00:00Z")
        sponsor, applicant, b1 = ctx["sponsor"], ctx["applicant"], ctx["badge"]
        assert b1["expires_at"] == "2027-07-10T00:00:00Z"

        set_clock("2027-07-09T00:00:00Z")
        ap2 = open_application(applicant["id"], sponsor["id"],
                               badge_class="STERILE")
        record_chrc_pass(ap2["id"],
                         fingerprint_submitted_at="2027-07-09T00:00:00Z")
        record_sta_cleared(ap2["id"])
        record_training(applicant["id"], "STERILE_INITIAL",
                        completed_at="2027-07-01T00:00:00Z")
        assert get_application(ap2["id"])["status"] == "READY"
        return sponsor, b1, ap2

    def test_overlapping_issuance_rejected_one_day_before_expiry(self):
        """PRD section 3.4: "The applicant must not already hold another badge
        of the same `badge_class` in `ACTIVE`, `SUSPENDED`, `LOST`, or
        `STOLEN` status whose validity window — the half-open interval from
        its `issued_at` up to but not including its `expires_at` — covers the
        issuance instant, else `ERR_ACTIVE_BADGE_EXISTS`; because the interval
        is half-open, an old badge expiring exactly at the issuance instant
        does not conflict."

        Design: Difficulty/resource_temporal_overlap/badge_identity_window_half_open_at_expiry
        """
        _, b1, ap2 = self._setup_window_overlap()

        resp = api_client.issue_badge(ap2["id"], {"badge_number": "B1302"}, BO)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_BADGE_EXISTS)

        set_clock("2027-07-10T00:00:00Z")
        assert get_badge(b1["id"])["status"] == "EXPIRED", \
            "the half-open window is closed at its end instant"

    def test_issuance_at_exact_expiry_succeeds_after_sweep(self):
        """PRD section 3.4: "because the interval is half-open, an old badge
        expiring exactly at the issuance instant does not conflict."
        PRD section 2.5: "Badges in `ACTIVE` or `SUSPENDED` whose `expires_at`
        has been reached or passed transition to `EXPIRED`".

        Design: Difficulty/resource_temporal_overlap/badge_identity_window_half_open_at_expiry
        """
        _, b1, ap2 = self._setup_window_overlap()
        validate_error(
            api_client.issue_badge(ap2["id"], {"badge_number": "B1302"}, BO),
            ApiErrorId.ERR_ACTIVE_BADGE_EXISTS)

        set_clock("2027-07-10T00:00:00Z")
        assert get_badge(b1["id"])["status"] == "EXPIRED"

        badge = issue_badge(ap2["id"], "B1302")
        assert badge["status"] == "ACTIVE"
        assert badge["expires_at"] == "2028-07-01T00:00:00Z", \
            "min(2029-07-10 cap, fresh completion expiry 2028-07-01)"


class TestIssuanceRbac:

    def test_access_system_cannot_issue_badge_forbidden(self):
        """PRD section 4: the `POST /badging/applications/{id}/issue-badge`
        row lists only `BadgingOfficer` under Authorized Role(s).
        PRD section 2.6: "The caller's role must be one of the endpoint's
        allowed roles; otherwise `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/access_system_cannot_issue_badge_forbidden
        """
        sponsor = create_sponsor()
        applicant = create_applicant(sponsor["id"])
        app, _ = setup_ready_application(sponsor["id"], applicant["id"],
                                         badge_class="STERILE")
        assert app["status"] == "READY"
        resp = api_client.issue_badge(app["id"], {"badge_number": "B2001"}, ACS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
