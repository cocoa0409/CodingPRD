"""Cross-entity state dependencies: assignment accept gated on provider
status, claim submit gated on roster lock (PRD §2.7, §3.3, §3.7)."""
from test_helpers import (
    BILLING,
    SCHED,
    ApiErrorId,
    create_case,
    create_crna,
    create_fee_schedule,
    create_published_roster,
    create_site,
    get_success_data,
    make_crna_headers,
    propose_assignment,
    set_clock,
    setup_completed_solo_case,
    validate_error,
    api_client,
)


class TestAssignmentAcceptGatedByProviderActive:
    def _setup_suspended_provider_with_proposed_assignment(self, api):
        """CRNA with expiry 2026-08-05; roster dated 2026-08-03 (within
        currency at proposal time); clock then sweeps past expiry."""
        site = create_site()
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One", expiry="2026-08-05")
        roster = create_published_roster(site["id"], service_date="2026-08-03",
                                         required_primary_slots=1,
                                         scheduled_day_end_minute=1200)
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        assignment = propose_assignment(case["id"], provider["id"],
                                        "CASE_PRIMARY")
        # Sweep: 2026-08-06 > 2026-08-05 -> SUSPENDED.
        set_clock("2026-08-06T00:00:00Z")
        return provider, assignment

    def test_accept_rejected_when_provider_suspended(self, api):
        """PRD §3.3: "the provider must still be `ACTIVE` (a suspended provider
        is rejected with `ERR_PROVIDER_SUSPENDED`)".
        PRD §2.7: "When the logical clock is set to a date strictly later than
        the earlier of a provider's two expiry dates, the provider transitions
        `ACTIVE → SUSPENDED`".

        Design: Difficulty/cross_entity_state_dependency/assignment_accept_gated_by_provider_active
        """
        provider, assignment = \
            self._setup_suspended_provider_with_proposed_assignment(api)
        swept = get_success_data(api.get_provider(provider["id"], SCHED))
        assert swept["status"] == "SUSPENDED"
        resp = api.accept_assignment(assignment["id"],
                                     make_crna_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_PROVIDER_SUSPENDED)

    def test_assignment_stays_proposed_after_rejected_accept(self, api):
        """PRD §3.3: "a suspended provider is rejected with
        `ERR_PROVIDER_SUSPENDED`" — the failed accept leaves the assignment in
        `PROPOSED` (no state mutation on rejection).
        PRD §3.3: "The new assignment begins `PROPOSED`".

        Design: Difficulty/cross_entity_state_dependency/assignment_accept_gated_by_provider_active
        """
        provider, assignment = \
            self._setup_suspended_provider_with_proposed_assignment(api)
        api.accept_assignment(assignment["id"], make_crna_headers(provider["id"]))
        after = get_success_data(api.get_assignment(assignment["id"], SCHED))
        assert after["status"] == "PROPOSED", (
            f"rejected accept must leave the assignment PROPOSED, got "
            f"{after['status']}")


class TestClaimSubmitGatedByRosterLocked:
    def test_submit_rejected_while_roster_published(self, api):
        """PRD §3.7: "Submission moves `READY → SUBMITTED` and requires the
        claim's case's roster to be `LOCKED` (else `ERR_ROSTER_NOT_LOCKED`)".

        Design: Difficulty/cross_entity_state_dependency/claim_submit_gated_by_roster_locked
        """
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST")
        claim_id = ctx["claims"][0]["id"]
        get_success_data(api.mark_claim_ready(claim_id, BILLING))
        resp = api.submit_claim(claim_id, BILLING)
        validate_error(resp, ApiErrorId.ERR_ROSTER_NOT_LOCKED)

    def test_submit_succeeds_after_roster_locks(self, api):
        """PRD §3.1: "`LOCKED` is terminal, and it is the event that opens
        billing — claims may be submitted only after their case's roster is
        locked."
        PRD §3.7: "Submission moves `READY → SUBMITTED` and requires the
        claim's case's roster to be `LOCKED` (else `ERR_ROSTER_NOT_LOCKED`)".

        Design: Difficulty/cross_entity_state_dependency/claim_submit_gated_by_roster_locked
        """
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST")
        claim_id = ctx["claims"][0]["id"]
        get_success_data(api.mark_claim_ready(claim_id, BILLING))
        # Same request fails before the lock and succeeds after it.
        rejected = api.submit_claim(claim_id, BILLING)
        validate_error(rejected, ApiErrorId.ERR_ROSTER_NOT_LOCKED)
        get_success_data(api.lock_roster(ctx["roster"]["id"], SCHED))
        submitted = get_success_data(api.submit_claim(claim_id, BILLING))
        assert submitted["status"] == "SUBMITTED"
