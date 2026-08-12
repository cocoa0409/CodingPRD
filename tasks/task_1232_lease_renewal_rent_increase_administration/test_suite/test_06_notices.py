"""Non-renewal notices: serve guards, cascades, cure, enforcement (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_lease,
    create_notice,
    create_offer_for_lease,
    create_policy,
    create_property,
    create_resident,
    create_unit,
    get_concession,
    get_lease,
    get_notice,
    get_offer,
    issue_offer,
    make_resident_headers,
    resident_counter,
    serve_notice,
    set_clock,
    setup_countered_offer_scenario,
    setup_lease_scenario,
    validate_error,
    validate_success,
)

PM1 = TEST_USERS["pm_1_headers"]
PM2 = TEST_USERS["pm_2_headers"]
LA1 = TEST_USERS["la_1_headers"]


class TestServeGuards:
    def test_notice_lead_59_days_rejected(self, api):
        """PRD §3.6: "The `effective_date` must fall on or after the lease's
        `term_end_date` (`ERR_INVALID_EFFECTIVE_DATE`), and the clock date must be no
        later than the `effective_date` minus the policy's `non_renewal_notice_days`,
        preserving the statutory lead time (`ERR_INSUFFICIENT_NOTICE_LEAD`)."

        Design: Corner/validations/notice_lead_59_days_rejected
        """
        sc = setup_lease_scenario(property_name="Lead Court", unit_number="L1")
        notice = create_notice(sc["lease"]["id"], "REPEATED_LATE_PAYMENT", "2027-06-01",
                               creator_headers=LA1)
        # effective 2027-06-01 minus 60 statutory days is 2027-04-02; 2027-04-03
        # leaves only 59 days of lead.
        set_clock("2027-04-03T00:00:00Z")
        resp = api.serve_notice(notice["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_NOTICE_LEAD)
        assert get_notice(notice["id"])["status"] == "DRAFT"
        assert get_lease(sc["lease"]["id"])["status"] == "ACTIVE"

    def test_effective_date_before_term_end_rejected(self, api):
        """PRD §3.6: "The `effective_date` must fall on or after the lease's
        `term_end_date` (`ERR_INVALID_EFFECTIVE_DATE`), and the clock date must be no
        later than the `effective_date` minus the policy's `non_renewal_notice_days`,
        preserving the statutory lead time (`ERR_INSUFFICIENT_NOTICE_LEAD`)."

        Design: Corner/validations/effective_date_before_term_end_rejected
        """
        sc = setup_lease_scenario(property_name="Early End Court", unit_number="E1")
        # One day before the term end 2027-06-01, with 395 days of lead.
        notice = create_notice(sc["lease"]["id"], "OWNER_OCCUPANCY", "2027-05-31",
                               creator_headers=LA1)
        resp = api.serve_notice(notice["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_INVALID_EFFECTIVE_DATE)
        assert get_notice(notice["id"])["status"] == "DRAFT"

    def test_sod_notice_creator_cannot_serve(self, api):
        """PRD §3.6: "Serving the notice is restricted to `PropertyManager` and
        `RegionalDirector` and is guarded by five checks. The server must differ from
        the creator (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.6: "At the first link, the notice itself is stamped — `served_on_date`
        takes the clock date, `cure_deadline_date` is set ten days out,
        `served_by_user_id` records the server — and the lease moves to
        `NON_RENEWAL_NOTICED` with its current status captured into the notice's
        `prior_lease_status`."

        Design: Corner/validations/sod_notice_creator_cannot_serve
        """
        sc = setup_lease_scenario(property_name="Notice SoD Court", unit_number="N1")
        # user_pm_1 creates the notice (a LeasingAgent-tier capability).
        notice = create_notice(sc["lease"]["id"], "LEASE_VIOLATION", "2027-06-01",
                               creator_headers=PM1, evidence_ref="ev-1")
        resp = api.serve_notice(notice["id"], PM1)  # same person -> SoD fires
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # A different PropertyManager serves it — the SoD check, not the role.
        served = serve_notice(notice["id"], server_headers=PM2)
        assert served["status"] == "SERVED"
        assert served["served_on_date"] == "2026-05-01"

    def test_notice_serve_twice_rejected(self, api):
        """PRD §3.6: "Serving the notice is restricted to `PropertyManager` and
        `RegionalDirector` and is guarded by five checks. The server must differ from
        the creator (`ERR_SEGREGATION_OF_DUTIES`). The notice must still be `DRAFT`
        (`ERR_NOTICE_NOT_DRAFT`)."

        Design: Corner/state_machines/notice_serve_twice_rejected
        """
        sc = setup_lease_scenario(property_name="Double Serve Court", unit_number="212")
        notice = create_notice(sc["lease"]["id"], "REPEATED_LATE_PAYMENT", "2027-06-01",
                               creator_headers=LA1)
        serve_notice(notice["id"], server_headers=PM1)
        resp = api.serve_notice(notice["id"], PM2)  # different server, not DRAFT
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_DRAFT)
        after = get_notice(notice["id"])
        assert after["status"] == "SERVED"
        assert after["served_on_date"] == "2026-05-01"
        assert after["cure_deadline_date"] == "2026-05-11"


class TestEnforcement:
    def test_rescind_enforced_notice_rejected(self, api):
        """PRD §3.6: "Once the cure window lapses the rescue is gone: the clock sweep
        moves the notice from `SERVED` to `CONFIRMED` when the clock passes
        `cure_deadline_date`, and a rescind attempt against a notice that is no
        longer `SERVED` returns `ERR_NOTICE_NOT_SERVED`."
        PRD §3.6: "When the sweep finds a `CONFIRMED` notice whose `effective_date`
        has arrived, the notice moves to `ENFORCED`, the lease moves to `ENDED` with
        `status_before_offer` cleared, any `ACCEPTED` offer still waiting on
        execution is moved to `VOIDED`, and that offer's renewal document — if still
        `GENERATED` or `RESIDENT_SIGNED` — is voided with it."

        Design: Corner/state_machines/rescind_enforced_notice_rejected
        """
        sc = setup_lease_scenario(property_name="Terminal Court", unit_number="205",
                                  term_start_date="2025-06-01", term_months=12)
        notice = create_notice(sc["lease"]["id"], "OWNER_OCCUPANCY", "2026-08-31",
                               creator_headers=LA1)
        serve_notice(notice["id"], server_headers=PM1)  # lead 122 days >= 60
        set_clock("2026-05-12T00:00:00Z")  # cure deadline 2026-05-11 passed
        assert get_notice(notice["id"])["status"] == "CONFIRMED"
        set_clock("2026-08-31T00:00:00Z")  # effective date arrives -> enforced
        assert get_notice(notice["id"])["status"] == "ENFORCED"
        resp = api.rescind_notice(notice["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_SERVED)
        assert get_lease(sc["lease"]["id"])["status"] == "ENDED"


class TestRepositioningQuota:
    def _quota_fixture(self, api):
        policy = create_policy()
        prop = create_property(policy["id"], name="Quota Towers")
        leases = []
        for i in range(1, 4):
            unit = create_unit(prop["id"], unit_number=f"A{i}")
            resident = create_resident(full_name=f"Q Res {i}", email=f"qres{i}@x.com")
            leases.append(create_lease(unit["id"], resident["id"],
                                       term_start_date="2025-06-01", term_months=12))
        notices = [
            create_notice(lease["id"], "PROPERTY_REPOSITIONING", "2026-08-31",
                          creator_headers=LA1)
            for lease in leases
        ]
        return notices

    def test_repositioning_quarterly_quota_first_two_serve(self, api):
        """PRD §3.6: "Finally, property repositioning is quota-limited: serving a
        `PROPERTY_REPOSITIONING` notice is rejected with
        `ERR_REPOSITIONING_QUOTA_EXCEEDED` when two or more other notices with that
        cause, in `SERVED`, `CONFIRMED`, or `ENFORCED` status, already exist on the
        same property with an `effective_date` in the same calendar quarter."

        Design: Difficulty/resource_temporal_overlap/repositioning_quarterly_quota_third_rejected
        """
        notices = self._quota_fixture(api)
        first = serve_notice(notices[0]["id"], server_headers=PM1)
        second = serve_notice(notices[1]["id"], server_headers=PM1)
        assert first["status"] == "SERVED"
        assert second["status"] == "SERVED"

    def test_repositioning_quarterly_quota_third_rejected(self, api):
        """PRD §3.6: "Finally, property repositioning is quota-limited: serving a
        `PROPERTY_REPOSITIONING` notice is rejected with
        `ERR_REPOSITIONING_QUOTA_EXCEEDED` when two or more other notices with that
        cause, in `SERVED`, `CONFIRMED`, or `ENFORCED` status, already exist on the
        same property with an `effective_date` in the same calendar quarter."

        Design: Difficulty/resource_temporal_overlap/repositioning_quarterly_quota_third_rejected
        """
        notices = self._quota_fixture(api)
        serve_notice(notices[0]["id"], server_headers=PM1)
        serve_notice(notices[1]["id"], server_headers=PM1)
        resp = api.serve_notice(notices[2]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_REPOSITIONING_QUOTA_EXCEEDED)
        assert get_notice(notices[2]["id"])["status"] == "DRAFT"


class TestServeCascade:
    def _cascade_fixture(self, api):
        """COUNTERED offer with a SUBMITTED concession, plus a DRAFT notice."""
        sc = setup_countered_offer_scenario(
            counter_rent_cents=205000, property_name="Serve Cascade House",
            unit_number="702")
        resp = api.create_concession_approval(
            sc["offer"]["id"],
            {"requested_rent_cents": 205000, "reason": "long tenure"},
            LA1)
        sc["concession"] = validate_success(resp, 201)
        sc["notice"] = create_notice(sc["lease"]["id"], "OWNER_OCCUPANCY",
                                     "2027-06-01", creator_headers=LA1)
        return sc

    def test_notice_serve_cascade_concession_math_and_stamp(self, api):
        """PRD §3.5: "At submission the system computes `concession_bps`: the
        difference between the offer's current `proposed_rent_cents` and the
        `requested_rent_cents`, divided by the `proposed_rent_cents`, expressed in
        basis points and rounded half-up."
        PRD §3.6: "At the first link, the notice itself is stamped — `served_on_date`
        takes the clock date, `cure_deadline_date` is set ten days out,
        `served_by_user_id` records the server — and the lease moves to
        `NON_RENEWAL_NOTICED` with its current status captured into the notice's
        `prior_lease_status`."

        Design: Difficulty/transitive_cascade/notice_serve_cascade_lease_offer_concession
        """
        sc = self._cascade_fixture(api)
        # round_half_up((210800 - 205000) / 210800 * 10000) = 275.
        assert sc["concession"]["concession_bps"] == 275
        served = serve_notice(sc["notice"]["id"], server_headers=PM1)
        assert served["status"] == "SERVED"
        assert served["served_on_date"] == "2026-05-01"
        assert served["cure_deadline_date"] == "2026-05-11"
        assert served["served_by_user_id"] == "user_pm_1"
        assert served["prior_lease_status"] == "RENEWAL_PENDING"

    def test_notice_serve_cascade_lease_offer_concession(self, api):
        """PRD §3.6: "At the second link, the lease leaving an issuable status
        withdraws its open offers: every `DRAFT`, `ISSUED`, or `COUNTERED` offer for
        the lease moves to `WITHDRAWN`, while an `ACCEPTED` offer survives until its
        own execution deadline. At the third link, each withdrawn offer voids its
        pending concession approvals per §2.10 — an effect of the withdrawals, not of
        the serve directly."

        Design: Difficulty/transitive_cascade/notice_serve_cascade_lease_offer_concession
        """
        sc = self._cascade_fixture(api)
        serve_notice(sc["notice"]["id"], server_headers=PM1)
        assert get_lease(sc["lease"]["id"])["status"] == "NON_RENEWAL_NOTICED"
        assert get_offer(sc["offer"]["id"])["status"] == "WITHDRAWN"
        assert get_concession(sc["concession"]["id"])["status"] == "VOIDED"


class TestNoticeRescindRestoresStatus:
    def _mtm_noticed_fixture(self, api):
        """Lease converted to MTM at 2027-06-01 (rent 242650), then noticed."""
        sc = setup_lease_scenario(property_name="MTM Restore Court", unit_number="1202",
                                  market_rent_cents=220000, monthly_rent_cents=200000)
        set_clock("2027-06-01T00:00:00Z")  # half-open end reached -> MTM
        sc["notice"] = create_notice(sc["lease"]["id"], "OWNER_OCCUPANCY",
                                     "2027-08-01", creator_headers=LA1)
        return sc

    def test_notice_serve_then_rescind_restores_mtm_status(self, api):
        """PRD §3.6: "A resident who cures the cause in time can be reprieved: within
        the cure window, a `PropertyManager` or `RegionalDirector` rescinds the
        `SERVED` notice, moving it to `RESCINDED` and restoring the lease's status
        verbatim from `prior_lease_status` — `ACTIVE`, `MTM`, or `RENEWAL_PENDING`
        exactly as captured."

        Design: Difficulty/compensating_invariant/notice_serve_then_rescind_restores_mtm_status
        """
        sc = self._mtm_noticed_fixture(api)
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "MTM"
        assert lease["monthly_rent_cents"] == 242650  # round(211000 * 1.15)

        served = serve_notice(sc["notice"]["id"], server_headers=PM1)
        assert served["status"] == "SERVED"
        assert served["prior_lease_status"] == "MTM"
        assert get_lease(sc["lease"]["id"])["status"] == "NON_RENEWAL_NOTICED"

        # Rescinded at 2027-06-01, inside the cure deadline 2027-06-11.
        resp = api.rescind_notice(sc["notice"]["id"], PM1)
        assert validate_success(resp, 200)["status"] == "RESCINDED"
        # Verbatim restore: MTM, not ACTIVE.
        assert get_lease(sc["lease"]["id"])["status"] == "MTM"

    def test_notice_serve_then_rescind_conserves_mtm_rent(self, api):
        """PRD §3.6: "A resident who cures the cause in time can be reprieved: within
        the cure window, a `PropertyManager` or `RegionalDirector` rescinds the
        `SERVED` notice, moving it to `RESCINDED` and restoring the lease's status
        verbatim from `prior_lease_status` — `ACTIVE`, `MTM`, or `RENEWAL_PENDING`
        exactly as captured."
        PRD §3.2: "The conversion rent is then the base grown by a premium of 1,500
        basis points — fifteen percent — rounded half-up to whole cents."

        Design: Difficulty/compensating_invariant/notice_serve_then_rescind_restores_mtm_status
        """
        sc = self._mtm_noticed_fixture(api)
        serve_notice(sc["notice"]["id"], server_headers=PM1)
        api.rescind_notice(sc["notice"]["id"], PM1)
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "MTM"
        # The MTM premium rent survives the serve/rescind round trip untouched.
        assert lease["monthly_rent_cents"] == 242650
