"""Badge suspension cycle, deactivation bookkeeping, return, and replacement."""
from test_helpers import (
    BO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_applicant,
    create_sponsor,
    get_badge,
    grant_escort_privilege,
    issue_badge,
    make_security_manager_headers,
    make_sponsor_signatory_headers,
    mark_returned,
    open_application,
    record_chrc_pass,
    record_violation,
    replace_badge,
    report_lost,
    revoke_badge,
    set_clock,
    setup_issued_badge,
    setup_ready_application,
    suspend_badge,
    sustain_violation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSuspendReinstateCycle:

    def test_suspend_reinstate_cycle_first_pass(self):
        """PRD section 3.5: "A `SecurityManager` may suspend an `ACTIVE` badge
        at any time, optionally noting a `reason`; the badge moves to
        `SUSPENDED` with `suspension_reason` set to `MANUAL`, `suspended_by`
        recording the acting manager, and `suspended_until` left null, marking
        it immediately reinstatable."
        PRD section 3.5: "Reinstatement returns a `SUSPENDED` badge to
        `ACTIVE`, clearing `suspended_by`, `suspended_until`, and
        `suspension_reason` to null."

        Design: Difficulty/non_linear_state_machine/badge_suspend_reinstate_cycle
        """
        ctx = setup_issued_badge(sponsor_code="CY", sponsor_name="CityCabs",
                                 badge_number="B501", full_name="Jesse Kay",
                                 government_id_number="G5001",
                                 date_of_birth="1994-04-04")
        badge_id = ctx["badge"]["id"]

        s1 = suspend_badge(badge_id, manager_id="mgr-1")
        assert s1["status"] == "SUSPENDED"
        assert s1["suspended_by"] == "mgr-1"
        assert s1["suspended_until"] is None, \
            "a manual suspension is immediately reinstatable"

        r1 = api_client.reinstate_badge(badge_id,
                                        make_security_manager_headers("mgr-2"))
        d1 = validate_success(r1)
        assert d1["status"] == "ACTIVE"
        assert d1["suspended_by"] is None, "suspension fields cleared"

    def test_suspend_reinstate_cycle_repeats(self):
        """PRD section 3.5: "Reinstatement returns a `SUSPENDED` badge to
        `ACTIVE`, clearing `suspended_by`, `suspended_until`, and
        `suspension_reason` to null."
        PRD section 2.9: "Reinstating a suspended badge requires the calling
        `SecurityManager` to be a different person than the manager recorded
        in the badge's `suspended_by` field."

        Design: Difficulty/non_linear_state_machine/badge_suspend_reinstate_cycle
        """
        ctx = setup_issued_badge(sponsor_code="CY", sponsor_name="CityCabs",
                                 badge_number="B501", full_name="Jesse Kay",
                                 government_id_number="G5001",
                                 date_of_birth="1994-04-04")
        badge_id = ctx["badge"]["id"]

        suspend_badge(badge_id, manager_id="mgr-1")
        validate_success(api_client.reinstate_badge(
            badge_id, make_security_manager_headers("mgr-2")))

        s2 = suspend_badge(badge_id, manager_id="mgr-2", reason="second incident")
        assert s2["status"] == "SUSPENDED"
        assert s2["suspended_by"] == "mgr-2", "the cycle records the new actor"

        r2 = api_client.reinstate_badge(badge_id,
                                        make_security_manager_headers("mgr-1"))
        d2 = validate_success(r2)
        assert d2["status"] == "ACTIVE"
        assert d2["suspended_by"] is None


class TestReturnAndTerminalStates:

    def test_mark_returned_on_returned_badge_rejected(self):
        """PRD section 3.5: "A `BadgingOfficer` marks a badge in `LOST`,
        `STOLEN`, `EXPIRED`, or `REVOKED` as returned; the badge moves to
        `RETURNED` with `returned_at` stamped from the clock. Any other status
        is refused with `ERR_BADGE_NOT_INACTIVE`."

        Design: Corner/state_machines/mark_returned_on_returned_badge_rejected
        """
        ctx = setup_issued_badge(badge_number="B201")
        badge_id = ctx["badge"]["id"]
        revoke_badge(badge_id)
        first = mark_returned(badge_id)
        assert first["status"] == "RETURNED"
        assert first["returned_at"] == "2026-08-01T00:00:00Z"

        resp = api_client.mark_returned(badge_id, BO)
        validate_error(resp, ApiErrorId.ERR_BADGE_NOT_INACTIVE)
        assert get_badge(badge_id)["returned_at"] == first["returned_at"], \
            "a rejected second return must not move returned_at"

    def test_reinstate_active_badge_rejected(self):
        """PRD section 3.5: "Reinstatement returns a `SUSPENDED` badge to
        `ACTIVE`, clearing `suspended_by`, `suspended_until`, and
        `suspension_reason` to null."
        PRD section 2.6: "The target entity must be in the state the
        transition requires, failing with the corresponding state error such
        as ... `ERR_BADGE_NOT_SUSPENDED` ...".

        Design: Corner/validations/reinstate_active_badge_rejected
        """
        ctx = setup_issued_badge(badge_number="B1801")
        resp = api_client.reinstate_badge(
            ctx["badge"]["id"], make_security_manager_headers("mgr-2"))
        validate_error(resp, ApiErrorId.ERR_BADGE_NOT_SUSPENDED)

    def test_get_badge_not_found_returns_404(self):
        """PRD section 2.6: "Path identifiers are validated left to right and
        body references must exist — each unknown resource yields its specific
        not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`,
        `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or
        `ERR_AUDIT_CYCLE_NOT_FOUND`)".

        Design: Corner/entities/get_badge_not_found_returns_404
        """
        resp = api_client.get_badge(NON_EXISTENT_UUID, BO)
        validate_error(resp, ApiErrorId.ERR_BADGE_NOT_FOUND)


class TestReplacement:

    def test_replace_lost_badge_rejected(self):
        """PRD section 3.5: "A `BadgingOfficer` may replace a badge in
        `ACTIVE`, `SUSPENDED`, or `EXPIRED` status by presenting a fresh
        `badge_number`."
        PRD section 3.5: "Three conditions guard the operation, all reported
        as `ERR_BADGE_NOT_REPLACEABLE`: the badge must be in one of those
        three statuses; every required course for its `badge_class` must hold
        a completion current under the renewal-grace regime — `expires_at`
        plus thirty days still in the future; and the computed expiry of the
        replacement must lie in the future."

        Design: Corner/validations/replace_lost_badge_rejected
        """
        ctx = setup_issued_badge(badge_number="B1701")
        badge_id = ctx["badge"]["id"]
        report_lost(badge_id, sponsor_id=ctx["sponsor"]["id"],
                    report_type="LOST")

        resp = api_client.replace_badge(
            badge_id, {"badge_number": "B1701R"}, BO)
        validate_error(resp, ApiErrorId.ERR_BADGE_NOT_REPLACEABLE)

        badge = get_badge(badge_id)
        assert badge["status"] == "LOST"
        assert badge["return_deadline"] == "2026-08-31T00:00:00Z", \
            "the return obligation survives the rejected replacement"

    def test_replace_conserves_sponsor_active_badge_count_invariant(self):
        """PRD section 3.5: "The sponsor's `active_badge_count` is unchanged:
        one deactivation offsets one issuance."
        PRD section 2.8: "Circulation is measured by the read-only,
        server-computed `active_badge_count`: the number of the sponsor's
        badges currently in `ACTIVE` or `SUSPENDED` status."

        Design: Difficulty/compensating_invariant/replace_conserves_sponsor_active_badge_count
        """
        ctx = setup_issued_badge(sponsor_code="RC", sponsor_name="RampCargo",
                                 quota=2, badge_number="B1401",
                                 full_name="Yara Ames",
                                 government_id_number="G9701",
                                 date_of_birth="1990-12-01")
        sponsor = ctx["sponsor"]
        other = create_applicant(sponsor["id"], full_name="Zack Bly",
                                 date_of_birth="1991-01-02",
                                 government_id_number="G9702")
        app2, _ = setup_ready_application(sponsor["id"], other["id"],
                                          badge_class="STERILE")
        issue_badge(app2["id"], "B1402")

        before = validate_success(api_client.get_sponsor(sponsor["id"], BO))
        assert before["active_badge_count"] == 2

        new_badge = replace_badge(ctx["badge"]["id"], "B1401R")

        after = validate_success(api_client.get_sponsor(sponsor["id"], BO))
        assert after["active_badge_count"] == 2, \
            "the deactivation and the issuance cancel out"
        assert new_badge["status"] == "ACTIVE"

    def test_replace_voids_old_badge_without_return_obligation(self):
        """PRD section 3.5: "On success the old badge becomes `VOIDED` with
        `deactivated_at` set to now, `return_deadline` left null because a
        voided badge is administratively accounted and carries no return
        obligation, and `superseded_by_badge_id` pointing at its replacement".
        PRD section 3.5: "The new badge is created in `ACTIVE` status under
        the same applicant, sponsor, and class, with `issued_at` set to now
        and `expires_at` computed under the renewal variant of the expiry
        rule — each required course's horizon is its completion's `expires_at`
        plus thirty days, and the badge expires at the earlier of twenty-four
        months after issuance or the nearest such horizon."

        Design: Difficulty/compensating_invariant/replace_conserves_sponsor_active_badge_count
        """
        ctx = setup_issued_badge(sponsor_code="RC", sponsor_name="RampCargo",
                                 quota=2, badge_number="B1401",
                                 full_name="Yara Ames",
                                 government_id_number="G9701",
                                 date_of_birth="1990-12-01")
        new_badge = replace_badge(ctx["badge"]["id"], "B1401R")

        assert new_badge["expires_at"] == "2027-07-01T00:00:00Z", \
            "renewal horizon 2027-06-01 + 30 days, below the 24-month cap"

        old = get_badge(ctx["badge"]["id"])
        assert old["status"] == "VOIDED"
        assert old["return_deadline"] is None
        assert old["superseded_by_badge_id"] == new_badge["id"]


class TestSegregationAndSuspensionServed:

    def test_reinstate_by_suspending_manager_rejected(self):
        """PRD section 2.9: "Reinstating a suspended badge requires the
        calling `SecurityManager` to be a different person than the manager
        recorded in the badge's `suspended_by` field."
        PRD section 2.9: "Either conflict is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/reinstate_by_suspending_manager_rejected
        """
        ctx = setup_issued_badge(badge_number="B2201")
        badge_id = ctx["badge"]["id"]
        suspend_badge(badge_id, manager_id="mgr-1")

        resp = api_client.reinstate_badge(
            badge_id, make_security_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = api_client.reinstate_badge(
            badge_id, make_security_manager_headers("mgr-2"))
        assert validate_success(ok)["status"] == "ACTIVE"

    def test_reinstate_before_suspension_served_rejected(self):
        """PRD section 3.5: "when `suspended_until` is set the current logical
        clock must have reached or passed it, else `ERR_SUSPENSION_NOT_SERVED`
        — a condition that can only bite on points-driven suspensions, since
        manual and sponsor suspensions carry a null `suspended_until`."

        Design: Corner/validations/reinstate_before_suspension_served_rejected
        """
        ctx = setup_issued_badge(badge_class="SIDA", badge_number="B1501")
        badge_id = ctx["badge"]["id"]
        v1 = record_violation(badge_id, "UNAUTHORIZED_AREA",
                              occurred_at="2026-08-02T00:00:00Z")
        sustain_violation(v1["id"])
        v2 = record_violation(badge_id, "ESCORT_VIOLATION",
                              occurred_at="2026-08-03T00:00:00Z")
        v2_sustained = sustain_violation(v2["id"])
        assert v2_sustained["status"] == "SUSTAINED"
        badge = get_badge(badge_id)
        assert badge["status"] == "SUSPENDED"
        assert badge["suspended_until"] == "2026-08-08T00:00:00Z"

        set_clock("2026-08-07T00:00:00Z", headers=make_security_manager_headers("mgr-1"))
        early = api_client.reinstate_badge(
            badge_id, make_security_manager_headers("mgr-2"))
        validate_error(early, ApiErrorId.ERR_SUSPENSION_NOT_SERVED)

        set_clock("2026-08-08T00:00:00Z", headers=make_security_manager_headers("mgr-1"))
        served = api_client.reinstate_badge(
            badge_id, make_security_manager_headers("mgr-2"))
        data = validate_success(served)
        assert data["status"] == "ACTIVE", "the >= boundary is inclusive"
        assert data["suspended_by"] is None
        assert data["suspended_until"] is None


class TestSponsorSuspensionCascade:

    def _setup_sponsor_with_application_and_badged_escort(self):
        sponsor = create_sponsor(sponsor_code="SP", name="SkyPark")
        a1 = create_applicant(sponsor["id"], full_name="Mia Nash",
                              date_of_birth="1991-10-10",
                              government_id_number="G8001")
        ap1 = open_application(a1["id"], sponsor["id"], badge_class="SIDA")
        record_chrc_pass(ap1["id"])  # rests in STA_PENDING

        a2 = create_applicant(sponsor["id"], full_name="Ned Ortiz",
                              date_of_birth="1992-11-11",
                              government_id_number="G8002")
        app2, _ = setup_ready_application(sponsor["id"], a2["id"],
                                          badge_class="STERILE")
        b2 = issue_badge(app2["id"], "B602")
        ep2 = grant_escort_privilege(b2["id"], b2["version"], max_escortees=2,
                                     manager_id="mgr-8")
        return sponsor, ap1, b2, ep2

    def test_sponsor_suspend_denies_applications_and_suspends_badges(self):
        """PRD section 3.9: "Every non-terminal application of that sponsor
        collapses to `DENIED` with `denial_reason` `SPONSOR_SUSPENDED`. Every
        badge of that sponsor in `ACTIVE` status moves to `SUSPENDED` with
        `suspension_reason` `SPONSOR_SUSPENDED`, `suspended_by` set to the
        acting manager, and `suspended_until` null".

        Design: Difficulty/transitive_cascade/sponsor_suspend_cascades_applications_badges_escorts
        """
        sponsor, ap1, b2, _ = \
            self._setup_sponsor_with_application_and_badged_escort()

        resp = api_client.suspend_sponsor(
            sponsor["id"], {"reason": "security directive"},
            make_security_manager_headers("mgr-9"))
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"

        app = validate_success(api_client.get_application(ap1["id"], BO))
        assert app["status"] == "DENIED"
        assert app["denial_reason"] == "SPONSOR_SUSPENDED"

        badge = get_badge(b2["id"])
        assert badge["status"] == "SUSPENDED"
        assert badge["suspension_reason"] == "SPONSOR_SUSPENDED"
        assert badge["suspended_by"] == "mgr-9"
        assert badge["suspended_until"] is None

    def test_sponsor_suspend_revokes_escorts_and_blocks_creation(self):
        """PRD section 3.9: "And each badge that newly entered `SUSPENDED`
        revokes its `GRANTED` escort privilege with `revoked_reason`
        `BADGE_SUSPENDED`."
        PRD section 3.1: "Registration is refused with `ERR_SPONSOR_NOT_ACTIVE`
        when the sponsor has been suspended."

        Design: Difficulty/transitive_cascade/sponsor_suspend_cascades_applications_badges_escorts
        """
        sponsor, _, b2, ep2 = \
            self._setup_sponsor_with_application_and_badged_escort()

        validate_success(api_client.suspend_sponsor(
            sponsor["id"], {"reason": "security directive"},
            make_security_manager_headers("mgr-9")))

        lst, _ = validate_paginated(
            api_client.list_escort_privileges(b2["id"], BO))
        assert len(lst) == 1
        assert lst[0]["id"] == ep2["id"]
        assert lst[0]["status"] == "REVOKED"
        assert lst[0]["revoked_reason"] == "BADGE_SUSPENDED"

        resp = api_client.create_applicant(
            {
                "sponsor_id": sponsor["id"],
                "full_name": "Oda Pell",
                "date_of_birth": "1997-01-01",
                "government_id_number": "G8003",
            },
            make_sponsor_signatory_headers(sponsor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ACTIVE)

    def test_suspend_already_suspended_sponsor_rejected(self):
        """PRD section 3.9: "Acting on a sponsor that is not `ACTIVE` is
        refused with `ERR_SPONSOR_NOT_ACTIVE`."

        Design: Corner/state_machines/suspend_already_suspended_sponsor_rejected
        """
        sponsor = create_sponsor()
        validate_success(api_client.suspend_sponsor(
            sponsor["id"], {"reason": "directive"},
            make_security_manager_headers("mgr-1")))
        resp = api_client.suspend_sponsor(
            sponsor["id"], {"reason": "again"},
            make_security_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ACTIVE)


class TestImmediateConsistencyAndListing:

    def test_badge_suspend_immediately_visible(self):
        """PRD section 3.5: "the badge moves to `SUSPENDED` with
        `suspension_reason` set to `MANUAL`, `suspended_by` recording the
        acting manager, and `suspended_until` left null, marking it
        immediately reinstatable."
        PRD section 2.5: "Sponsor badge counts are recomputed as part of the
        same step, so a client observing the system immediately after a clock
        set sees a fully reconciled state."

        Design: Corner/consistency_model/badge_suspend_immediately_visible
        """
        ctx = setup_issued_badge(badge_number="B2801")
        badge_id = ctx["badge"]["id"]
        resp = api_client.suspend_badge(
            badge_id, {"reason": "investigation"},
            make_security_manager_headers("mgr-1"))
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"
        assert data["suspended_by"] == "mgr-1"
        assert data["suspension_reason"] == "MANUAL"

        reread = validate_success(api_client.get_badge(badge_id, BO))
        assert reread["status"] == "SUSPENDED"
        assert reread["suspended_by"] == "mgr-1", "no reconciliation lag"

    def test_badges_list_filter_by_status_and_sponsor(self):
        """PRD section 3.5: "The badge collection can be listed with optional
        `applicant_id`, `sponsor_id`, `application_id`,
        `superseded_by_badge_id`, and `status` filters, which makes the
        replacement chain directly queryable."

        Design: Corner/cross_cutting_layers/badges_list_filter_by_status_and_sponsor
        """
        ctx = setup_issued_badge(badge_number="B2701")
        sponsor = ctx["sponsor"]
        b1 = ctx["badge"]
        other = create_applicant(sponsor["id"], full_name="Ben Okafor",
                                 date_of_birth="1988-05-02",
                                 government_id_number="G1002")
        app2, _ = setup_ready_application(sponsor["id"], other["id"],
                                          badge_class="STERILE")
        b2 = issue_badge(app2["id"], "B2702")

        suspend_badge(b1["id"], manager_id="mgr-1", reason="review")

        lst1, meta1 = validate_paginated(api_client.list_badges(
            BO, params={"sponsor_id": sponsor["id"], "status": "SUSPENDED"}))
        assert meta1["total_count"] == 1
        assert lst1[0]["id"] == b1["id"]

        lst2, meta2 = validate_paginated(api_client.list_badges(
            BO, params={"applicant_id": other["id"], "status": "ACTIVE"}))
        assert meta2["total_count"] == 1
        assert lst2[0]["id"] == b2["id"]
