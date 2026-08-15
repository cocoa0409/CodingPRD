"""Roster lifecycle: publish/unpublish/lock gates and posture derivation
(PRD §3.1, §3.2, §3.6)."""
from test_helpers import (
    SCHED,
    ApiErrorId,
    assert_version_incremented,
    complete_case_at,
    create_case,
    create_fee_schedule,
    create_published_roster,
    create_roster,
    create_site,
    get_success_data,
    run_case_clock,
    set_clock,
    setup_site_fee_roster,
    validate_error,
    validate_success,
    api_client,
)


class TestRosterPublishUnpublishCycle:
    def test_publish_unpublish_republish_cycle(self, api):
        """PRD §3.1: "Publishing moves the roster `DRAFT → PUBLISHED` and is
        the gate that opens the day".
        PRD §3.1: "Unpublishing reverts `PUBLISHED → DRAFT`, but only while
        nothing has clinically happened — every case on the roster must still
        be `SCHEDULED` or `CANCELLED`, and the presence of any `IN_PROGRESS` or
        `COMPLETED` case rejects the revert with `ERR_CASES_OUTSTANDING`."

        Design: Corner/state_machines/roster_publish_unpublish_revert_cycle
        """
        site = create_site()
        roster = create_roster(site["id"], required_primary_slots=0,
                               scheduled_day_end_minute=1020)
        published = get_success_data(api.publish_roster(roster["id"], SCHED))
        assert published["lifecycle"] == "PUBLISHED"
        assert_version_incremented(roster["version"], published["version"],
                                   "roster publish")
        unpublished = get_success_data(api.unpublish_roster(roster["id"], SCHED))
        assert unpublished["lifecycle"] == "DRAFT"
        assert_version_incremented(published["version"], unpublished["version"],
                                   "roster unpublish")
        republished = get_success_data(api.publish_roster(roster["id"], SCHED))
        assert republished["lifecycle"] == "PUBLISHED"
        assert_version_incremented(unpublished["version"],
                                   republished["version"], "roster re-publish")

    def test_double_publish_rejected(self, api):
        """PRD §3.1: "Publishing is defined only out of `DRAFT`; attempting it
        from any other lifecycle is rejected with `ERR_ROSTER_NOT_DRAFT`."

        Design: Corner/state_machines/roster_publish_unpublish_revert_cycle
        """
        site = create_site()
        roster = create_published_roster(site["id"], required_primary_slots=0,
                                         scheduled_day_end_minute=1020)
        resp = api.publish_roster(roster["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_ROSTER_NOT_DRAFT)
        after = get_success_data(api.get_roster(roster["id"], SCHED))
        assert after["lifecycle"] == "PUBLISHED"


class TestRosterLockGates:
    def test_lock_blocked_with_scheduled_case_outstanding(self, api):
        """PRD §3.1: "Locking moves `PUBLISHED → LOCKED` and is stricter
        still: every case on the roster must be terminal (`COMPLETED` or
        `CANCELLED`), otherwise the lock is rejected with
        `ERR_CASES_OUTSTANDING`."

        Design: Corner/state_machines/roster_lock_blocked_with_cases_outstanding
        """
        site, fee, roster = setup_site_fee_roster()
        create_case(roster["id"], scheduled_start_minute=540,
                    scheduled_end_minute=600)
        resp = api.lock_roster(roster["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CASES_OUTSTANDING)
        after = get_success_data(api.get_roster(roster["id"], SCHED))
        assert after["lifecycle"] == "PUBLISHED"

    def test_unpublish_blocked_with_in_progress_case(self, api):
        """PRD §3.1: "the presence of any `IN_PROGRESS` or `COMPLETED` case
        rejects the revert with `ERR_CASES_OUTSTANDING`."

        Design: Corner/state_machines/roster_unpublish_blocked_with_in_progress_case
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        run_case_clock(case["id"], "2026-08-10T09:00:00Z")
        resp = api.unpublish_roster(roster["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CASES_OUTSTANDING)
        after = get_success_data(api.get_roster(roster["id"], SCHED))
        assert after["lifecycle"] == "PUBLISHED"

    def test_case_create_on_locked_roster_rejected(self, api):
        """PRD §3.2: "Case creation is permitted while the roster is `DRAFT`
        or `PUBLISHED`; on a `LOCKED` roster it is rejected with
        `ERR_ROSTER_LIFECYCLE_LOCKED`."

        Design: Corner/state_machines/case_create_on_locked_roster_rejected
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        complete_case_at(case["id"], "2026-08-10T09:00:00Z",
                         "2026-08-10T10:00:00Z")
        get_success_data(api.lock_roster(roster["id"], SCHED))
        resp = api.create_case(
            {"roster_id": roster["id"], "procedure_code": "P100",
             "physical_status": "P1", "scheduled_start_minute": 700,
             "scheduled_end_minute": 760}, SCHED)
        validate_error(resp, ApiErrorId.ERR_ROSTER_LIFECYCLE_LOCKED)
        cases = get_success_data(
            api.list_cases(SCHED, params={"roster_id": roster["id"]}))
        rows = cases if isinstance(cases, list) else cases["data"]
        assert len(rows) == 1, "the rejected create must not persist a case"
