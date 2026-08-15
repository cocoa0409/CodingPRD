"""Optimistic concurrency (PRD §2.5) and the provider suspension /
reinstatement cycle (PRD §2.7), plus immediate visibility of mutation side
effects (PRD §3.3)."""
from test_helpers import (
    ADMIN,
    SCHED,
    ApiErrorId,
    assert_version_incremented,
    create_case,
    create_crna,
    create_fee_schedule,
    create_published_roster,
    create_roster,
    create_site,
    create_provider,
    get_success_data,
    make_physician_headers,
    propose_assignment,
    set_clock,
    setup_site_fee_roster,
    validate_error,
    validate_success,
    api_client,
)


class TestOccAssignmentCreate:
    def test_stale_case_version_rejected(self, api):
        """PRD §2.5: "Proposing a case assignment requires
        `expected_case_version`, carrying the client's last observed `version`
        of the target case. If the case's current version has advanced since
        that observation — for example because another writer has just created
        a same-role assignment and thereby superseded the prior one — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_assignment_create_stale_case_version_rejected
        """
        site, fee, roster = setup_site_fee_roster(scheduled_day_end_minute=1200)
        p1 = create_crna("Crna One")
        p2 = create_crna("Crna Two")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        observed_version = case["version"]
        # First create advances the case version (assignment churn is a case
        # mutation), making the observed version stale.
        first = api.create_case_assignment(
            case["id"], {"provider_id": p1["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": observed_version}, SCHED)
        first_created = validate_success(first, expected_status=201)
        resp = api.create_case_assignment(
            case["id"], {"provider_id": p2["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": observed_version}, SCHED)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_rejected_stale_write_does_not_supersede(self, api):
        """PRD §2.5: "If the case's current version has advanced since that
        observation ... the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.3: "The new assignment begins `PROPOSED`".

        Design: Corner/cross_cutting_layers/occ_assignment_create_stale_case_version_rejected
        """
        site, fee, roster = setup_site_fee_roster(scheduled_day_end_minute=1200)
        p1 = create_crna("Crna One")
        p2 = create_crna("Crna Two")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        observed_version = case["version"]
        first = get_success_data(api.create_case_assignment(
            case["id"], {"provider_id": p1["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": observed_version}, SCHED))
        api.create_case_assignment(
            case["id"], {"provider_id": p2["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": observed_version}, SCHED)
        after = get_success_data(api.get_assignment(first["id"], SCHED))
        assert after["status"] == "PROPOSED", \
            "the rejected stale write must not supersede the live assignment"


class TestOccRosterPatch:
    def test_stale_roster_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.5: "Updating a roster's staffing requirements requires
        `expected_roster_version`; a value that no longer matches the roster's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "While the roster is `DRAFT` or `PUBLISHED`, a `Scheduler`
        may adjust `required_primary_slots` or `scheduled_day_end_minute`
        through the roster-update operation; the request must carry
        `expected_roster_version` per §2.5, each accepted patch increments the
        roster's `version`".

        Design: Corner/cross_cutting_layers/occ_roster_patch_stale_version_rejected
        """
        site = create_site()
        roster = create_roster(site["id"], required_primary_slots=1,
                               scheduled_day_end_minute=1020)
        observed = roster["version"]
        # Publish advances the roster version, so the pre-publish observation
        # is stale by the time the PATCH arrives.
        get_success_data(api.publish_roster(roster["id"], SCHED))
        stale = api.update_roster(
            roster["id"], {"required_primary_slots": 3,
                           "expected_roster_version": observed}, SCHED)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        unchanged = get_success_data(api.get_roster(roster["id"], SCHED))
        assert unchanged["required_primary_slots"] == 1
        fresh = get_success_data(api.update_roster(
            roster["id"], {"required_primary_slots": 3,
                           "expected_roster_version": unchanged["version"]}, SCHED))
        assert fresh["required_primary_slots"] == 3
        assert_version_incremented(unchanged["version"], fresh["version"],
                                   "roster patch")


class TestOccProviderCredentials:
    def test_stale_provider_version_rejected(self, api):
        """PRD §2.5: "Updating a provider's credential dates requires
        `expected_provider_version`; a value that no longer matches the
        provider's current `version` — which a clock-sweep suspension may have
        advanced — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_provider_credentials_stale_version_rejected
        """
        provider = create_crna("Crna One")
        observed = provider["version"]
        first = get_success_data(api.update_provider_credentials(
            provider["id"], {"credential_expires_on": "2027-06-30",
                             "dea_expires_on": "2027-06-30",
                             "expected_provider_version": observed}, ADMIN))
        assert_version_incremented(observed, first["version"],
                                   "first credential patch")
        stale = api.update_provider_credentials(
            provider["id"], {"credential_expires_on": "2027-12-31",
                             "dea_expires_on": "2027-12-31",
                             "expected_provider_version": observed}, ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api.get_provider(provider["id"], ADMIN))
        assert after["credential_expires_on"] == "2027-06-30", \
            "the stale patch must not apply"


class TestProviderSuspensionCycle:
    def test_sweep_suspends_then_renewal_reinstates(self, api):
        """PRD §2.7: "When the logical clock is set to a date strictly later
        than the earlier of a provider's two expiry dates, the provider
        transitions `ACTIVE → SUSPENDED` and its `version` increments by one.
        ... Reinstatement happens through the credential-update operation: when
        a `GroupAdministrator` patches both expiry dates so that both are on or
        after the current clock date, a suspended provider returns to
        `ACTIVE`. The patch and the reinstatement together increment `version`
        exactly once."

        Design: Corner/state_machines/provider_suspend_then_reinstate_on_credential_renewal
        """
        provider = create_provider("CRNA", "Crna One", expiry="2026-08-05",
                                   dea="2026-08-06")
        v0 = provider["version"]
        set_clock("2026-08-06T00:00:00Z")
        suspended = get_success_data(api.get_provider(provider["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        assert_version_incremented(v0, suspended["version"],
                                   "suspension sweep")
        reinstated = get_success_data(api.update_provider_credentials(
            provider["id"],
            {"credential_expires_on": "2027-01-31",
             "dea_expires_on": "2027-01-31",
             "expected_provider_version": suspended["version"]}, ADMIN))
        assert reinstated["status"] == "ACTIVE"
        assert_version_incremented(suspended["version"], reinstated["version"],
                                   "patch + reinstate (single increment)")

    def test_partial_renewal_stays_suspended(self, api):
        """PRD §2.7: "If the patch leaves either expiry still before the clock
        date, the provider remains `SUSPENDED`, but the patch itself still
        succeeds and still increments `version`."

        Design: Corner/state_machines/provider_partial_renewal_stays_suspended
        """
        provider = create_provider("CRNA", "Crna One", expiry="2026-08-05",
                                   dea="2026-08-06")
        set_clock("2026-08-07T00:00:00Z")
        suspended = get_success_data(api.get_provider(provider["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        patched = get_success_data(api.update_provider_credentials(
            provider["id"],
            {"credential_expires_on": "2027-01-31",
             "dea_expires_on": "2026-08-06",
             "expected_provider_version": suspended["version"]}, ADMIN))
        assert patched["credential_expires_on"] == "2027-01-31", \
            "the patch itself succeeds and applies the new dates"
        assert patched["status"] == "SUSPENDED", (
            "dea_expires_on 2026-08-06 is still before clock date 2026-08-07 "
            "-> remains SUSPENDED")
        assert_version_incremented(suspended["version"], patched["version"],
                                   "patch without reinstatement")


class TestImmediateVisibility:
    def test_accept_response_and_follow_on_reads_are_consistent(self, api):
        """PRD §3.3: "When a `CASE_PRIMARY` assignment confirms, the case's
        `provisional_charge_cents` is computed as a forward-looking estimate".
        PRD §3.1: "Posture is never stored as an input; it is re-derived on
        every read. A roster reads `STAFFED` exactly when the count of
        `CONFIRMED` `CASE_PRIMARY` assignments across the roster's cases
        reaches `required_primary_slots`".

        Design: Corner/consistency_model/immediate_visibility_of_accept_side_effects
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=1,
                                                  scheduled_day_end_minute=1200)
        physician = create_provider("ANESTHESIOLOGIST", "Dr. Avery")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=660)
        assignment = propose_assignment(case["id"], physician["id"],
                                        "CASE_PRIMARY")
        accepted = get_success_data(api.accept_assignment(
            assignment["id"], make_physician_headers(physician["id"])))
        # Mutation visible in the same response.
        assert accepted["status"] == "CONFIRMED"
        assert_version_incremented(assignment["version"], accepted["version"],
                                   "accept")
        # Follow-on reads show the derived effects with no recompute call.
        case_after = get_success_data(api.get_case(case["id"], SCHED))
        assert case_after["provisional_charge_cents"] == 104000, (
            f"13.0 units x 8000 = 104000 recomputed synchronously, got "
            f"{case_after['provisional_charge_cents']}")
        roster_after = get_success_data(api.get_roster(roster["id"], SCHED))
        assert roster_after["posture"] == "STAFFED"
