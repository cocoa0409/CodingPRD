"""Waitlist purges: scheduling, notice windows, confirmation of interest,
execution cascades, cancellation, reopening, and OCC on scheduling."""
from test_helpers import (
    ApiErrorId, fixtures, get_success_data, make_applicant_headers,
    validate_error,
)

DEVELOPER = fixtures.DEVELOPER
LOTTERY_ADMIN = fixtures.LOTTERY_ADMIN


# --------------------------------------------------------------------------
# Purge execution cascade (difficulty: transitive cascade)
# --------------------------------------------------------------------------
def test_purge_execute_removes_unconfirmed_entry(api):
    """PRD §3.7: "On execution the purge examines every entry of the campaign
    currently in `RANKED` status — entries that are `OFFERED` or `LEASED` are
    never purge-selected — and removes each one whose `last_confirmed_at` is
    either absent or strictly earlier than `notice_sent_at`, stamping
    `removal_reason` `PURGED` and `removed_at`."

    Design: Difficulty/transitive_cascade/purge_execute_cascade_empties_waitlist
    """
    world = fixtures.setup_purge_notices_sent(api)
    entry_id = world["offers"][0]["entry_id"]
    fixtures.set_clock("2026-07-31T00:00:00Z", api)  # past the 30-day deadline

    executed = fixtures.purge_action(api, world["purge"]["id"], "EXECUTE")
    assert executed["entries_removed_count"] == 1
    entry = get_success_data(api.get_waitlist_entry(entry_id, DEVELOPER))
    assert entry["status"] == "REMOVED"
    assert entry["removal_reason"] == "PURGED"


def test_purge_execute_emptying_waitlist_purges_campaign(api):
    """PRD §3.7: "The purge records how many entries it removed in
    `entries_removed_count` and stamps `executed_at`, then the campaign
    recomputes `waitlist_active_count` and branches on the result: if the
    purge emptied the active waitlist — the count is zero — the campaign
    moves from `PURGE_SCHEDULED` to `PURGED`; otherwise it returns from
    `PURGE_SCHEDULED` to `LEASING`."

    Design: Difficulty/transitive_cascade/purge_execute_cascade_empties_waitlist
    """
    world = fixtures.setup_purge_notices_sent(api)
    fixtures.set_clock("2026-07-31T00:00:00Z", api)
    fixtures.purge_action(api, world["purge"]["id"], "EXECUTE")

    campaign = fixtures.get_campaign(api, world["campaign"]["id"])
    assert campaign["waitlist_active_count"] == 0
    assert campaign["status"] == "PURGED", (
        "the campaign flip is caused by the count reaching zero, not by the "
        "EXECUTE call directly"
    )


# --------------------------------------------------------------------------
# Purge gates, cancel leg, and confirmation
# --------------------------------------------------------------------------
def test_purge_execute_before_deadline_returns_not_executable(api):
    """PRD §3.7: "Execution is the purge's bite, and it is gated on time: the
    logical clock must have reached `response_deadline`, else the execution
    is rejected with `ERR_PURGE_NOT_EXECUTABLE`."

    Design: Corner/state_machines/purge_execute_before_deadline_returns_not_executable
    """
    world = fixtures.setup_purge_notices_sent(api)
    # Notices went out at 2026-06-30 with a 30-day window; the clock is
    # still 2026-06-30, before the 2026-07-30 deadline.
    resp = api.advance_purge_run(world["purge"]["id"], {"action": "EXECUTE"},
                                 DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_PURGE_NOT_EXECUTABLE)
    purge = get_success_data(api.get_purge_run(world["purge"]["id"], DEVELOPER))
    assert purge["status"] == "NOTICES_SENT"
    entry = get_success_data(
        api.get_waitlist_entry(world["offers"][0]["entry_id"], DEVELOPER))
    assert entry["status"] == "RANKED"


def test_purge_cancel_restores_leasing(api):
    """PRD §3.7: "A purge may instead be cancelled from either `SCHEDULED` or
    `NOTICES_SENT`, landing in terminal `CANCELLED` and returning the
    campaign to `LEASING` in both cases." PRD §3.7: "Scheduling lands the
    purge in `SCHEDULED` and flips the campaign from `LEASING` to
    `PURGE_SCHEDULED`, incrementing the campaign's `version`."

    Design: Corner/state_machines/purge_cancel_restores_leasing
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-P2")
    for offer in world["offers"]:
        fixtures.decline_offer(api, offer)
    purge = fixtures.new_purge_run(api, world["campaign"]["id"],
                                   notice_response_days=30)
    mid = fixtures.get_campaign(api, world["campaign"]["id"])
    assert mid["status"] == "PURGE_SCHEDULED"

    cancelled = fixtures.purge_action(api, purge["id"], "CANCEL")
    assert cancelled["status"] == "CANCELLED"
    campaign = fixtures.get_campaign(api, world["campaign"]["id"])
    assert campaign["status"] == "LEASING"


def test_confirm_interest_without_active_purge_returns_invalid_state(api):
    """PRD §3.7: "the owning applicant confirms continued interest on their
    entry, which requires a purge of the entry's campaign to currently sit in
    `NOTICES_SENT` — confirming at any other time is rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/confirm_interest_without_active_purge_returns_invalid_state
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-CI",
                                            certify=False)
    application = world["applications"][0]
    applicant = world["applicants"][0]
    entry = fixtures.get_entry_for_application(api, application["id"])
    resp = api.confirm_interest(entry["id"],
                                make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirmed_entry_survives_purge(api):
    """PRD §3.7: "removes each one whose `last_confirmed_at` is either absent
    or strictly earlier than `notice_sent_at`, stamping `removal_reason`
    `PURGED` and `removed_at`. The boundary is exact: a confirmation stamped
    at precisely `notice_sent_at` preserves the entry, because only a
    strictly earlier timestamp condemns it."

    Design: Corner/state_machines/confirmed_entry_survives_purge
    """
    world = fixtures.setup_purge_notices_sent(
        api, seed="SEED-CS", num_units=1,
        applications=[{"full_name": "Eli E", "email": "e2@x.com"},
                      {"full_name": "Flo F", "email": "f2@x.com"}])
    app_a, app_b = world["applications"]
    applicant_a = world["applicants"][0]
    entry_a = fixtures.get_entry_for_application(api, app_a["id"])
    entry_b = fixtures.get_entry_for_application(api, app_b["id"])

    fixtures.set_clock("2026-07-05T00:00:00Z", api)  # inside the notice window
    confirmed = get_success_data(api.confirm_interest(
        entry_a["id"], make_applicant_headers(applicant_a["id"])))
    assert confirmed["last_confirmed_at"] is not None

    fixtures.set_clock("2026-07-31T00:00:00Z", api)  # past the deadline
    executed = fixtures.purge_action(api, world["purge"]["id"], "EXECUTE")
    assert executed["entries_removed_count"] == 1

    survivor = get_success_data(api.get_waitlist_entry(entry_a["id"],
                                                       DEVELOPER))
    assert survivor["status"] == "RANKED"
    removed = get_success_data(api.get_waitlist_entry(entry_b["id"],
                                                      DEVELOPER))
    assert removed["status"] == "REMOVED"
    assert removed["removal_reason"] == "PURGED"

    campaign = fixtures.get_campaign(api, world["campaign"]["id"])
    assert campaign["waitlist_active_count"] == 1
    assert campaign["status"] == "LEASING", (
        "with one active entry left the campaign returns to LEASING"
    )


def test_occ_purge_create_stale_version_rejected(api):
    """PRD §2.6: "Two operations that write against an `ApplicationCampaign`
    are protected by optimistic concurrency control: creating a lottery run
    for a campaign, and scheduling a purge run for a campaign. Each requires
    the request to carry `expected_campaign_version`, a non-optional field
    holding the campaign `version` the client last observed. If that value
    does not equal the campaign's current `version` at the moment the write
    is attempted, the request is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_layers/occ_purge_create_stale_version_rejected
    """
    world = fixtures.setup_leasing_with_pending_offer(api, seed="SEED-OCCP")
    for offer in world["offers"]:
        fixtures.decline_offer(api, offer)
    campaign_id = world["campaign"]["id"]
    stale_version = fixtures.campaign_version(api, campaign_id)

    purge1 = fixtures.new_purge_run(api, campaign_id,
                                    expected_campaign_version=stale_version)
    assert purge1["status"] == "SCHEDULED"
    fixtures.purge_action(api, purge1["id"], "CANCEL")
    assert fixtures.get_campaign(api, campaign_id)["status"] == "LEASING"

    # The campaign version advanced at purge creation and again at cancel;
    # the pre-purge read is stale even though the state check would pass.
    resp = api.create_purge_run(
        fixtures.create_purge_run_payload(campaign_id, stale_version,
                                          notice_response_days=30),
        DEVELOPER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
