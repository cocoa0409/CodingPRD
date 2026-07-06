"""Validation corners: business-rule violations mapped to their specific error_ids."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_client,
    create_campaign,
    create_outlet,
    create_journalist,
    create_spokesperson,
    create_media_list_current,
    create_pitch,
    create_press_release,
    create_scheduled_press_release,
    create_distribution,
    setup_campaign_with_media_list,
    setup_open_period,
    log_time_entry,
    close_period_current_version,
    set_clock,
    TEST_USERS,
    create_interview_payload,
    create_retainer_period_payload,
    create_time_entry_payload,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
SC = TEST_USERS["scheduling_coordinator_headers"]
PA = TEST_USERS["platform_admin_headers"]


def test_log_time_against_closed_period_rejected(api):
    """PRD §3.11: "The target period must be `OPEN`; logging time against a `CLOSED` period is
    rejected with `ERR_PERIOD_CLOSED`."

    Design: Corner/validations/time_entry_against_closed_period_rejected
    """
    client, period = setup_open_period(period_month="2026-08")
    close_period_current_version(period["id"])  # no SUBMITTED entries -> close succeeds
    resp = api.create_time_entry(
        create_time_entry_payload(period["id"], staff_id="staff-e", work_type="STRATEGY",
                                  billable_hours=2.0), AM)
    validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED.value)


def test_close_period_with_submitted_entry_rejected(api):
    """PRD §3.11: "Closing has one workflow precondition — no time entry in the period may
    still be `SUBMITTED`; every entry must be `APPROVED` or `VOID`, else the close is
    rejected with `ERR_PERIOD_HAS_PENDING_ENTRIES`"

    Design: Corner/validations/close_period_with_submitted_entries_rejected
    """
    client, period = setup_open_period(period_month="2026-09")
    log_time_entry(period["id"], 2.0, staff_id="staff-f", work_type="STRATEGY")  # SUBMITTED
    fresh = validate_success(api.get_retainer_period(period["id"], AM))
    resp = api.close_retainer_period(
        period["id"], {"expected_retainer_period_version": fresh["version"]}, AM)
    validate_error(resp, ApiErrorId.ERR_PERIOD_HAS_PENDING_ENTRIES.value)


def test_duplicate_retainer_period_for_client_month_rejected(api):
    """PRD §3.11: "the month must be unique per client, and a second period for the same client
    and `period_month` is rejected with `ERR_DUPLICATE_PERIOD`."

    Design: Corner/validations/duplicate_retainer_period_for_client_month_rejected
    """
    client = create_client()
    validate_success(api.create_retainer_period(
        create_retainer_period_payload(client["id"], period_month="2026-10"), AM), expected_status=201)
    resp = api.create_retainer_period(
        create_retainer_period_payload(client["id"], period_month="2026-10"), AM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD.value)


def test_schedule_press_release_with_past_embargo_rejected(api):
    """PRD §3.5: "Scheduling requires the campaign to be `ACTIVE`, else
    `ERR_CAMPAIGN_NOT_ACTIVE`, and requires the `embargo_until` instant to be strictly after
    the current logical clock; an embargo at or before the current clock is rejected with
    `ERR_EMBARGO_IN_PAST`."

    Design: Corner/validations/schedule_press_release_embargo_in_past_rejected
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    pr = create_press_release(campaign["id"], headline="Stale", embargo_until="2026-02-01T00:00:00Z")
    resp = api.schedule_press_release(pr["id"], MS)
    validate_error(resp, ApiErrorId.ERR_EMBARGO_IN_PAST.value)


def test_release_with_no_distributions_rejected(api):
    """PRD §3.5: "at least one distribution must exist for the release (otherwise
    `ERR_NO_DISTRIBUTIONS`)."

    Design: Corner/validations/release_without_distributions_rejected
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    pr = create_scheduled_press_release(campaign["id"], "2026-03-15T00:00:00Z", headline="Empty")
    set_clock("2026-03-15T00:00:00Z")
    resp = api.release_press_release(pr["id"], MS)
    validate_error(resp, ApiErrorId.ERR_NO_DISTRIBUTIONS.value)


def test_distribution_on_released_press_release_rejected(api):
    """PRD §3.5: "the target release must still be open to new recipients — it must be in
    `DRAFT` or `SCHEDULED`; if the release is already `RELEASED` or `WITHDRAWN`, the create
    is rejected with `ERR_DISTRIBUTION_RELEASE_LOCKED`."

    Design: Corner/validations/distribution_on_released_press_release_rejected
    """
    scn = setup_campaign_with_media_list()
    pr = create_scheduled_press_release(scn["campaign"]["id"], "2026-03-15T00:00:00Z", headline="Out")
    create_distribution(pr["id"], scn["journalist"]["id"])
    set_clock("2026-03-15T00:00:00Z")
    validate_success(api.release_press_release(pr["id"], MS))

    resp = api.create_distribution(
        {"press_release_id": pr["id"], "journalist_id": scn["journalist"]["id"]}, MS)
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_RELEASE_LOCKED.value)


def test_distribution_journalist_not_in_campaign_list_rejected(api):
    """PRD §3.5: "The recipient journalist must belong to a media list of the release's
    campaign, else `ERR_JOURNALIST_NOT_IN_LIST`."

    Design: Corner/validations/distribution_journalist_not_in_campaign_list_rejected
    """
    scn = setup_campaign_with_media_list()  # list contains scn["journalist"]
    outsider = create_journalist(scn["outlet"]["id"], full_name="DN J2")
    pr = create_press_release(scn["campaign"]["id"], headline="DN PR", embargo_until="2026-03-20T00:00:00Z")
    resp = api.create_distribution(
        {"press_release_id": pr["id"], "journalist_id": outsider["id"]}, MS)
    validate_error(resp, ApiErrorId.ERR_JOURNALIST_NOT_IN_LIST.value)


def test_interview_ends_before_starts_invalid_request(api):
    """PRD §2.8: "(5) request well-formedness — required fields present and well-typed, enums
    in their allowed set, and numeric ranges satisfied (`billable_hours` strictly greater
    than zero, `ends_at` strictly after `starts_at`, `period_month` matching the year-month
    format), else `ERR_INVALID_REQUEST`;"

    Design: Corner/validations/interview_ends_before_starts_invalid_request
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"], full_name="BT Jo")
    spokesperson = create_spokesperson(client["id"], full_name="BT Spoke")
    resp = api.create_interview(
        create_interview_payload(campaign["id"], spokesperson["id"], journalist["id"],
                                 "2026-04-10T11:00:00Z", "2026-04-10T10:00:00Z"), SC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_send_pitch_to_blocklisted_journalist_rejected(api):
    """PRD §3.4: "the recipient journalist must be `ACTIVE`, else
    `ERR_JOURNALIST_BLOCKLISTED`;"

    Design: Corner/validations/pitch_send_to_blocklisted_journalist_rejected
    """
    scn = setup_campaign_with_media_list()
    pitch = create_pitch(scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"])
    validate_success(api.blocklist_journalist(scn["journalist"]["id"], MS))
    resp = api.send_pitch(pitch["id"], MS)
    validate_error(resp, ApiErrorId.ERR_JOURNALIST_BLOCKLISTED.value)


def test_activate_campaign_for_suspended_client_rejected(api):
    """PRD §3.3: "In both cases the owning client must be `ACTIVE`; if the client is suspended,
    activation is rejected with `ERR_CLIENT_SUSPENDED`."

    Design: Corner/validations/activate_campaign_for_suspended_client_rejected
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.suspend_client(client["id"], PA))
    resp = api.activate_campaign(campaign["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED.value)


def test_confirm_cancelled_interview_after_deactivation_invalid_state(api):
    """PRD §3.6: "First, every interview for that spokesperson in `REQUESTED` or `CONFIRMED` is
    cancelled (advancing to `CANCELLED`), freeing the spokesperson's calendar slot. Then,
    for each such cancelled interview that carried a `pitch_id` whose pitch is currently
    `ACCEPTED`, that pitch is reverted from `ACCEPTED` back to `RESPONDED` as compensation,
    so the pitch can be re-accepted and re-anchored to a fresh interview later."
    PRD §2.8: "(7) state validity — the target resource is in a state from which the
    requested transition is legal, else `ERR_INVALID_STATE`;"

    Deactivating the spokesperson cascades its lone REQUESTED interview to CANCELLED; a
    subsequent confirm on that CANCELLED interview is an invalid transition.

    Design: Corner/validations/confirm_interview_after_spokesperson_deactivated_invalid_state
    """
    from test_helpers import setup_interview_scenario
    scn = setup_interview_scenario(
        starts_at="2026-05-10T10:00:00Z", ends_at="2026-05-10T11:00:00Z")
    validate_success(api.deactivate_spokesperson(scn["spokesperson"]["id"], AM))
    cancelled = validate_success(api.get_interview(scn["interview"]["id"], SC))
    assert cancelled["status"] == "CANCELLED"

    resp = api.confirm_interview(scn["interview"]["id"], SC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
