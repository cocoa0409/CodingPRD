"""The referral pipeline: gating, slot accounting, decline/reroute cycles, TTL
expiry, and warm handoff (PRD §2.10, §3.5)."""

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    assert_referral, assert_org_slot_invariant,
    register_client, create_staff_member, open_case, grant_consent,
    create_partner_org, create_draft_referral, send_referral, create_sent_referral,
    setup_case_with_sent_referral, staff_headers, partner_headers,
    set_clock, run_sweeps,
    DEFAULT_CLOCK_ISO,
)

ADMIN = TEST_USERS["center_admin_headers"]


class TestReferralDraftState:
    def test_referral_created_in_draft_initial_state(self):
        """PRD §3.5: "A referral is drafted by a `CaseManager` or `CenterAdmin`
        with `case_id`, `organization_id`, a `service_category`, and optional
        handoff `notes` and `ttl_days`."
        PRD §3.5: "A draft referral holds no partner slot."

        Design: Corner/state_machines/referral_created_in_draft_initial_state
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        org = create_partner_org(name="Org D", categories=("EDUCATION",), capacity=2,
                                 email="d@org.test")
        ref = validate_success(api_client.create_referral(
            {"case_id": case["id"], "organization_id": org["id"],
             "service_category": "EDUCATION"}, staff_headers(mgr)), expected_status=201)
        assert_referral(ref)
        assert ref["status"] == "DRAFT"
        assert ref["sent_at"] is None, "sent_at is stamped only on send"
        org_now = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert org_now["referral_slots_used"] == 0, "a DRAFT referral holds no partner slot"


class TestDeclineRerouteCycle:
    def _setup_declined_referral(self):
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org_x = create_partner_org(name="Org X", categories=("HOUSING",), capacity=5,
                                   email="x@org.test")
        org_y = create_partner_org(name="Org Y", categories=("HOUSING",), capacity=5,
                                   email="y@org.test")
        ref = create_sent_referral(case, org_x, "HOUSING", mgr)
        declined = validate_success(api_client.respond_referral(
            ref["id"], {"decision": "DECLINED"}, partner_headers(org_x)))
        assert declined["status"] == "DECLINED"
        return mgr, client, case, org_x, org_y, ref

    def test_declined_referral_reroutes_to_new_org_and_reenters_sent(self):
        """PRD §3.5: "A successful reroute replaces `organization_id`, restamps
        `sent_at`, and increments the new organization's `referral_slots_used` by
        1; a rerouted referral is once again `SENT`."
        PRD §3.5: "Either response stamps `responded_at`; a decline additionally
        releases the partner slot, decrementing `referral_slots_used` by 1."

        Design: Difficulty/non_linear_state_machine/referral_decline_reroute_cycle
        """
        mgr, _client, _case, org_x, org_y, ref = self._setup_declined_referral()
        rerouted = validate_success(api_client.reroute_referral(
            ref["id"], {"organization_id": org_y["id"]}, staff_headers(mgr)))
        assert rerouted["status"] == "SENT", "the cycle SENT -> DECLINED -> SENT completes"
        assert rerouted["organization_id"] == org_y["id"]
        org_x_now = validate_success(api_client.get_organization(org_x["id"], staff_headers(mgr)))
        org_y_now = validate_success(api_client.get_organization(org_y["id"], staff_headers(mgr)))
        assert org_x_now["referral_slots_used"] == 0, "decline released org X's slot"
        assert org_y_now["referral_slots_used"] == 1, "reroute took a slot at org Y"
        assert_org_slot_invariant(org_x_now)
        assert_org_slot_invariant(org_y_now)

    def test_rerouted_referral_can_be_accepted_by_new_org(self):
        """PRD §3.5: "A successful reroute replaces `organization_id`, restamps
        `sent_at`, and increments the new organization's `referral_slots_used` by
        1; a rerouted referral is once again `SENT`."
        PRD §2.10: "A partner organization's `referral_slots_used` always equals
        the count of its referrals currently occupying a slot — precisely those in
        `SENT` or `ACCEPTED`".

        Design: Difficulty/non_linear_state_machine/referral_decline_reroute_cycle
        """
        mgr, _client, _case, _org_x, org_y, ref = self._setup_declined_referral()
        rerouted = validate_success(api_client.reroute_referral(
            ref["id"], {"organization_id": org_y["id"]}, staff_headers(mgr)))
        assert rerouted["sent_at"] is not None, "reroute restamps sent_at"
        accepted = validate_success(api_client.respond_referral(
            ref["id"], {"decision": "ACCEPTED", "warm_handoff_offered": True},
            partner_headers(org_y)))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["warm_handoff_offered"] is True
        assert accepted["responded_at"] is not None
        org_y_now = validate_success(api_client.get_organization(org_y["id"], staff_headers(mgr)))
        assert org_y_now["referral_slots_used"] == 1, "ACCEPTED referrals still occupy a slot"


class TestSendGates:
    def test_send_blocked_while_org_suspended(self):
        """PRD §3.5: "Six conditions must hold, and §2.8 fixes the order in which
        they surface: the referral is `DRAFT` (else `ERR_INVALID_STATE`); the
        case's `privacy_posture` is `STANDARD` (else `ERR_PRIVACY_SEALED`); the
        client holds a `GRANTED` consent with `scope` equal to `REFERRAL_SHARE`
        (else `ERR_CONSENT_MISSING`); the partner is `ACTIVE` (else
        `ERR_ORG_SUSPENDED`); the partner's `referral_slots_used` is below its
        `referral_capacity` (else `ERR_ORG_CAPACITY_FULL`); and the case is
        neither `SUSPENDED` nor `CLOSED` (else `ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/referral_send_requires_organization_active
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org Z", categories=("EMPLOYMENT",), capacity=3,
                                 email="z@org.test")
        validate_success(api_client.suspend_organization(org["id"], ADMIN))
        ref = create_draft_referral(case, org, "EMPLOYMENT", mgr)

        resp = api_client.send_referral(ref["id"], staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED)
        after = validate_success(api_client.get_referral(ref["id"], staff_headers(mgr)))
        assert after["status"] == "DRAFT", "a rejected send leaves the referral DRAFT"

    def test_send_succeeds_after_org_reactivation(self):
        """PRD §3.1: "A `CenterAdmin` may suspend a partner — an
        `ACTIVE`-to-`SUSPENDED` move that blocks new referral sends with
        `ERR_ORG_SUSPENDED` while leaving already-`SENT` or `ACCEPTED` referrals
        untouched — and later reactivate it."
        PRD §3.5: "A successful send stamps `sent_at` with the current logical
        clock and increments the organization's `referral_slots_used` by 1."

        Design: Difficulty/cross_entity_state_dependency/referral_send_requires_organization_active
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org Z", categories=("EMPLOYMENT",), capacity=3,
                                 email="z@org.test")
        validate_success(api_client.suspend_organization(org["id"], ADMIN))
        ref = create_draft_referral(case, org, "EMPLOYMENT", mgr)
        validate_error(api_client.send_referral(ref["id"], staff_headers(mgr)),
                       ApiErrorId.ERR_ORG_SUSPENDED)

        validate_success(api_client.reactivate_organization(org["id"], ADMIN))
        sent = validate_success(api_client.send_referral(ref["id"], staff_headers(mgr)))
        assert sent["status"] == "SENT"
        assert sent["sent_at"] is not None
        org_now = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert org_now["referral_slots_used"] == 1

    def test_missing_consent_wins_over_suspended_org(self):
        """PRD §2.8: "When a request violates several rules at once, the error it
        receives is determined by a fixed precedence ladder; the first failing
        rung decides the response."
        PRD §2.8: "5. **Privacy and consent gates** — the case's
        `privacy_posture` blocks the operation (`ERR_PRIVACY_SEALED`), a required
        consent scope is not `GRANTED` (`ERR_CONSENT_MISSING`)" — a rung evaluated
        before "9. **Cross-entity state** — ... the program is not closed".

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_referral_send
        """
        mgr = create_staff_member()
        client = register_client()  # deliberately no REFERRAL_SHARE consent
        case = open_case(client, mgr)
        org = create_partner_org(name="Org S", categories=("HOUSING",), capacity=5,
                                 email="s@org.test")
        validate_success(api_client.suspend_organization(org["id"], ADMIN))
        ref = create_draft_referral(case, org, "HOUSING", mgr)

        resp = api_client.send_referral(ref["id"], staff_headers(mgr))
        data = validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING)
        assert data["error_id"] == "ERR_CONSENT_MISSING", (
            "the consent gate (rung 5) outranks the org-status gate (rung 9) "
            "when both conditions fail")
        after = validate_success(api_client.get_referral(ref["id"], staff_headers(mgr)))
        assert after["status"] == "DRAFT"

    def test_suspended_org_surfaces_when_consent_present(self):
        """PRD §3.5: "the partner is `ACTIVE` (else `ERR_ORG_SUSPENDED`)"
        — the fourth of the six send conditions: "Six conditions must hold, and
        §2.8 fixes the order in which they surface: the referral is `DRAFT` (else
        `ERR_INVALID_STATE`); the case's `privacy_posture` is `STANDARD` (else
        `ERR_PRIVACY_SEALED`); the client holds a `GRANTED` consent with `scope`
        equal to `REFERRAL_SHARE` (else `ERR_CONSENT_MISSING`); the partner is
        `ACTIVE` (else `ERR_ORG_SUSPENDED`); ...".

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_referral_send
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")  # consent gate passes
        case = open_case(client, mgr)
        org = create_partner_org(name="Org S", categories=("HOUSING",), capacity=5,
                                 email="s@org.test")
        validate_success(api_client.suspend_organization(org["id"], ADMIN))
        ref = create_draft_referral(case, org, "HOUSING", mgr)

        resp = api_client.send_referral(ref["id"], staff_headers(mgr))
        data = validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED)
        assert data["error_id"] == "ERR_ORG_SUSPENDED", (
            "with consent satisfied, the suspended-org condition is the first "
            "failing rung")


class TestCapacityAndWithdrawal:
    def test_org_capacity_full_on_send(self):
        """PRD §3.5: "the partner's `referral_slots_used` is below its
        `referral_capacity` (else `ERR_ORG_CAPACITY_FULL`)"
        PRD §2.10: "A partner organization's `referral_slots_used` always equals
        the count of its referrals currently occupying a slot — precisely those in
        `SENT` or `ACCEPTED`".

        Design: Corner/errors/org_capacity_full_on_send
        """
        mgr = create_staff_member()
        client1 = register_client(full_name="Ida One")
        client2 = register_client(full_name="Ida Two")
        grant_consent(client1, "REFERRAL_SHARE")
        grant_consent(client2, "REFERRAL_SHARE")
        case1 = open_case(client1, mgr)
        case2 = open_case(client2, mgr)
        org = create_partner_org(name="Org Cap1", categories=("HOUSING",), capacity=1,
                                 email="cap@org.test")
        ref1 = create_draft_referral(case1, org, "HOUSING", mgr)
        ref2 = create_draft_referral(case2, org, "HOUSING", mgr)

        sent = validate_success(api_client.send_referral(ref1["id"], staff_headers(mgr)))
        assert sent["status"] == "SENT"
        resp = api_client.send_referral(ref2["id"], staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_ORG_CAPACITY_FULL)
        after = validate_success(api_client.get_referral(ref2["id"], staff_headers(mgr)))
        assert after["status"] == "DRAFT", "a capacity-rejected send holds no slot"

    def test_slot_conservation_across_send_and_withdraw(self):
        """PRD §2.10: "A partner organization's `referral_slots_used` always
        equals the count of its referrals currently occupying a slot — precisely
        those in `SENT` or `ACCEPTED` — and `referral_slots_open` always equals
        `referral_capacity` minus `referral_slots_used`, so used plus open equals
        capacity without exception."
        PRD §3.5: "withdrawing from `SENT` or `ACCEPTED` releases the slot".

        Design: Difficulty/compensating_invariant/org_referral_slot_conservation_across_send_withdraw
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org C", categories=("HEALTH",), capacity=3,
                                 email="c@org.test")
        ref = create_draft_referral(case, org, "HEALTH", mgr)

        validate_success(api_client.send_referral(ref["id"], staff_headers(mgr)))
        mid = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert mid["referral_slots_used"] == 1
        assert mid["referral_slots_open"] == 2
        assert_org_slot_invariant(mid)

        validate_success(api_client.withdraw_referral(ref["id"], staff_headers(mgr)))
        end = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert end["referral_slots_used"] == 0, "withdraw releases exactly the slot the send took"
        assert end["referral_slots_open"] == 3
        assert_org_slot_invariant(end)

    def test_slot_conservation_across_send_and_decline(self):
        """PRD §3.5: "Either response stamps `responded_at`; a decline
        additionally releases the partner slot, decrementing `referral_slots_used`
        by 1."
        PRD §2.10: "A partner organization's `referral_slots_used` always equals
        the count of its referrals currently occupying a slot — precisely those in
        `SENT` or `ACCEPTED` — and `referral_slots_open` always equals
        `referral_capacity` minus `referral_slots_used`, so used plus open equals
        capacity without exception."

        Design: Difficulty/compensating_invariant/org_referral_slot_conservation_across_send_withdraw
        """
        ctx = setup_case_with_sent_referral(org_capacity=3)
        mgr, org, ref = ctx["manager"], ctx["org"], ctx["referral"]
        mid = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert mid["referral_slots_used"] == 1
        assert_org_slot_invariant(mid)

        validate_success(api_client.respond_referral(
            ref["id"], {"decision": "DECLINED"}, partner_headers(org)))
        end = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert end["referral_slots_used"] == 0, "decline restores the baseline exactly"
        assert_org_slot_invariant(end)


class TestTerminalLockdown:
    def test_terminal_lockdown_withdrawn_referral_rejects_send(self):
        """PRD §3.5: "`COMPLETED` and `WITHDRAWN` are the referral's terminal
        states."
        PRD §2.8: "4. **State** — the target resource sits in a valid from-state
        for the requested transition, terminal states reject all further
        transitions, and a `SUSPENDED` or `CLOSED` case rejects new child-service
        writes; failure yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_lockdown_withdrawn_referral_rejects_send
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        org = create_partner_org(name="Org E", categories=("HOUSING",), capacity=2,
                                 email="e@org.test")
        ref = create_draft_referral(case, org, "HOUSING", mgr)
        withdrawn = validate_success(api_client.withdraw_referral(ref["id"], staff_headers(mgr)))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api_client.send_referral(ref["id"], staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_referral(ref["id"], staff_headers(mgr)))
        assert after["status"] == "WITHDRAWN"


class TestWarmHandoff:
    def test_referral_complete_requires_handoff_confirmation(self):
        """PRD §3.5: "Before an `ACCEPTED` referral can complete, the warm handoff
        must be confirmed — a `CaseManager` or `CenterAdmin` records the
        confirmation, which stamps `handoff_confirmed_at` — and completing without
        it fails with `ERR_HANDOFF_NOT_CONFIRMED`."
        PRD §3.5: "Completion stamps `completed_at` with the logical clock (this
        instant later keys the funder outcome window of §3.9) and releases the
        partner slot."

        Design: Corner/errors/referral_complete_requires_handoff_confirmation
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org H", categories=("EMPLOYMENT",), capacity=3,
                                 email="h@org.test")
        ref = create_sent_referral(case, org, "EMPLOYMENT", mgr)
        validate_success(api_client.respond_referral(
            ref["id"], {"decision": "ACCEPTED", "warm_handoff_offered": True},
            partner_headers(org)))

        resp = api_client.complete_referral(ref["id"], staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_HANDOFF_NOT_CONFIRMED)

        confirmed = validate_success(api_client.confirm_handoff(ref["id"], staff_headers(mgr)))
        assert confirmed["handoff_confirmed_at"] is not None
        completed = validate_success(api_client.complete_referral(ref["id"], staff_headers(mgr)))
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None
        org_now = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert org_now["referral_slots_used"] == 0, "completion releases the partner slot"


class TestTtlExpiry:
    def test_referral_ttl_expiry_at_exact_boundary(self):
        """PRD §3.5: "when the sweep finds a `SENT` referral whose `sent_at` plus
        its `ttl_days` has been reached by the logical clock, the referral becomes
        `EXPIRED` and its slot is released."
        PRD §2.4: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; until it is explicitly set, all rules see that
        instant."

        Design: Corner/calculations/referral_ttl_expiry_at_exact_boundary
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org T", categories=("LEGAL",), capacity=2,
                                 email="t@org.test")
        ref = create_draft_referral(case, org, "LEGAL", mgr, ttl_days=14)
        send_referral(ref["id"], mgr)  # sent_at = 2026-08-01T00:00:00Z (default clock)

        # One second before sent_at + ttl_days: not yet reached.
        set_clock("2026-08-14T23:59:59Z")
        sweep1 = run_sweeps()
        assert sweep1["referrals_expired"] == 0
        # Exactly at sent_at + ttl_days: reached, so the referral expires.
        set_clock("2026-08-15T00:00:00Z")
        sweep2 = run_sweeps()
        assert sweep2["referrals_expired"] == 1

        ref_now = validate_success(api_client.get_referral(ref["id"], staff_headers(mgr)))
        assert ref_now["status"] == "EXPIRED"
        org_now = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert org_now["referral_slots_used"] == 0, "expiry releases the org slot"


class TestImmediateConsistency:
    def test_mutations_visible_immediately_in_same_request(self):
        """PRD §2.5: "Cascades obey immediate consistency: when one request
        mutates several resources — a privacy seal that suspends referrals and
        cancels appointments, a verification that supersedes an assessment and
        revises plans — every one of those mutations, with its refreshed
        `updated_at` and incremented `version` where applicable, is committed and
        visible in that same request's response."
        PRD §3.5: "A successful send stamps `sent_at` with the current logical
        clock and increments the organization's `referral_slots_used` by 1."
        PRD §2.4: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; until it is explicitly set, all rules see that
        instant."

        Design: Corner/consistency_model/mutations_visible_immediately_in_same_request
        """
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org I", categories=("HEALTH",), capacity=2,
                                 email="i@org.test")
        ref = create_draft_referral(case, org, "HEALTH", mgr)

        sent = validate_success(api_client.send_referral(ref["id"], staff_headers(mgr)))
        assert sent["status"] == "SENT"
        assert str(sent["sent_at"]).startswith("2026-08-01T00:00:00"), \
            "sent_at is stamped with the pinned startup logical clock"
        org_now = validate_success(api_client.get_organization(org["id"], staff_headers(mgr)))
        assert org_now["referral_slots_used"] == 1, \
            "the slot increment is visible on the very next read"
