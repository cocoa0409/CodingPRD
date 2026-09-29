"""Double opt-in, the absorbing UNSUBSCRIBED status, and review steps that are not idempotent."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import anonymous_headers, community_manager_headers

CONFIRMATION_INSTANT = "2026-08-03T09:15:00Z"


def test_confirming_consent_stamps_both_consent_instants_from_the_logical_clock(api):
    """PRD §3.7: "Confirmation moves the member `PENDING_CONFIRMATION → SUBSCRIBED` and sets both
    `consent_confirmed_at` and `consent_changed_at` to the logical clock, refreshing `updated_at`
    and advancing `version` by 1."
    PRD §2.4: "Time in this system is a server-controlled logical clock, not the host's wall clock."
    PRD §3.7: "A new member is in `consent_status` `PENDING_CONFIRMATION` with `sent_count_total` 0
    and `last_sent_at`, `consent_confirmed_at` and `consent_changed_at` all null."

    Design: Corner/state_machines/confirm_consent_moves_pending_member_to_subscribed_and_stamps_both_times
    """
    program = fx.create_program(api)
    member = fx.join_community(api, program["id"], "optin@example.com")
    fx.move_clock(api, CONFIRMATION_INSTANT)

    response = api.confirm_consent(
        member["id"], f.confirm_consent_payload(member["consent_token"]), anonymous_headers()
    )

    confirmed = validate_success(response, 200)
    assert confirmed["consent_status"] == "SUBSCRIBED", confirmed
    assert confirmed["consent_confirmed_at"].startswith("2026-08-03T09:15:00"), confirmed
    assert confirmed["consent_changed_at"].startswith("2026-08-03T09:15:00"), confirmed
    assert confirmed["consent_confirmed_at"] == confirmed["consent_changed_at"], confirmed
    assert confirmed["version"] == 2, confirmed
    assert confirmed["sent_count_total"] == 0, confirmed
    assert confirmed["last_sent_at"] is None, confirmed
    assert confirmed["consent_token"] == member["consent_token"], confirmed


def test_a_wrong_token_is_a_token_error_while_pending_and_a_state_error_once_resolved(api):
    """PRD §2.9: "22. The supplied `consent_token` must equal the member's stored `consent_token`,
    else `ERR_CONSENT_TOKEN_INVALID` (422)."
    PRD §2.9: "18. A member's `consent_status` must permit the requested action — confirmation
    requires `PENDING_CONFIRMATION` (`ERR_CONSENT_ALREADY_RESOLVED`), a `PAUSE` action requires
    `SUBSCRIBED` and a `RESUME` action requires `PAUSED` (`ERR_CONSENT_TRANSITION_INVALID`), and an
    `UNSUBSCRIBE` action requires a member who is not already `UNSUBSCRIBED`
    (`ERR_CONSENT_ALREADY_RESOLVED`) — all 409."
    PRD §3.7: "The member must be in `PENDING_CONFIRMATION`, refusing otherwise with
    `ERR_CONSENT_ALREADY_RESOLVED`."

    Design: Corner/state_machines/confirm_consent_with_a_wrong_token_returns_consent_token_invalid
    """
    program = fx.create_program(api)
    member = fx.join_community(api, program["id"], "optin@example.com")

    bad_token = api.confirm_consent(
        member["id"], f.confirm_consent_payload("not-the-real-token"), anonymous_headers()
    )
    still_pending = fx.read_member(api, member["id"])
    accepted = api.confirm_consent(
        member["id"], f.confirm_consent_payload(member["consent_token"]), anonymous_headers()
    )
    replayed = api.confirm_consent(
        member["id"], f.confirm_consent_payload("not-the-real-token"), anonymous_headers()
    )

    validate_error(bad_token, ApiErrorId.CONSENT_TOKEN_INVALID, 422)
    assert still_pending["consent_status"] == "PENDING_CONFIRMATION", still_pending
    assert still_pending["version"] == 1, still_pending
    assert still_pending["consent_confirmed_at"] is None, still_pending
    confirmed = validate_success(accepted, 200)
    assert confirmed["consent_status"] == "SUBSCRIBED", confirmed
    assert confirmed["version"] == 2, confirmed
    validate_error(replayed, ApiErrorId.CONSENT_ALREADY_RESOLVED, 409)
    assert fx.read_member(api, member["id"])["version"] == 2


def test_an_unsubscribed_member_can_be_neither_resumed_nor_paused_nor_unsubscribed_again(api):
    """PRD §3.7: "`RESUME` requires `PAUSED` and moves the member `PAUSED → SUBSCRIBED`; either
    action on the wrong starting status is refused with `ERR_CONSENT_TRANSITION_INVALID`."
    PRD §3.7: "`UNSUBSCRIBE` is accepted from `PENDING_CONFIRMATION`, `SUBSCRIBED` or `PAUSED`,
    refusing an already-unsubscribed member with `ERR_CONSENT_ALREADY_RESOLVED`, and moves the
    member to the terminal `UNSUBSCRIBED`, permanently excluding them from every future dispatch
    audience."
    PRD §3.7: "A `CommunityManager` may unsubscribe a member on their behalf without the ownership
    restriction."

    Design: Corner/state_machines/unsubscribed_member_cannot_be_resumed_or_paused
    """
    program = fx.create_program(api)
    member = fx.subscribed_member(api, program["id"], "leaver@example.com")
    departed = fx.change_consent(api, member["id"], "UNSUBSCRIBE")

    resumed = api.change_consent(
        member["id"], f.consent_change_payload("RESUME"), community_manager_headers()
    )
    paused = api.change_consent(
        member["id"], f.consent_change_payload("PAUSE"), community_manager_headers()
    )
    again = api.change_consent(
        member["id"], f.consent_change_payload("UNSUBSCRIBE"), community_manager_headers()
    )

    assert departed["consent_status"] == "UNSUBSCRIBED", departed
    assert departed["version"] == 3, departed
    validate_error(resumed, ApiErrorId.CONSENT_TRANSITION_INVALID, 409)
    validate_error(paused, ApiErrorId.CONSENT_TRANSITION_INVALID, 409)
    validate_error(again, ApiErrorId.CONSENT_ALREADY_RESOLVED, 409)
    unchanged = fx.read_member(api, member["id"])
    assert unchanged["consent_status"] == "UNSUBSCRIBED", unchanged
    assert unchanged["version"] == 3, unchanged


def test_triage_refuses_a_replay_while_drafting_legitimately_repeats(api):
    """PRD §3.8: "A `CommunityManager` triages a review, moving it `NEW → TRIAGED` and optionally
    attaching a `note`; a review in any other state is refused with `ERR_REVIEW_NOT_NEW`."
    PRD §3.8: "The same manager then drafts the public response by supplying a `response_body` of 1
    to 2,000 characters; drafting is accepted from `TRIAGED` or from `DRAFTING` — redrafting is
    normal — and refused from any other state with `ERR_REVIEW_NOT_DRAFTABLE`."
    PRD §3.8: "A rating of 1 or 2 gives 24 hours; a rating of exactly 3 gives 72 hours — three
    days; a rating of 4 or 5 gives 168 hours — a full week."

    Design: Corner/state_machines/re_triaging_a_triaged_review_is_rejected_rather_than_treated_as_idempotent
    """
    program = fx.create_program(api)
    review = fx.ingest_review(
        api, program["id"], external_ref="gd-77", rating=2, posted_at="2026-07-31T00:00:00Z"
    )
    triaged = fx.triage_review(api, review["id"], note="first pass")

    replayed = api.triage_employer_review(
        review["id"], community_manager_headers(), f.triage_payload("second pass")
    )
    first_draft = fx.draft_review_response(api, review["id"], "first draft")
    second_draft = fx.draft_review_response(api, review["id"], "second draft")

    assert review["response_due_at"] == "2026-08-01T00:00:00.000Z", review
    assert triaged["state"] == "TRIAGED", triaged
    assert triaged["version"] == 2, triaged
    validate_error(replayed, ApiErrorId.REVIEW_NOT_NEW, 409)
    assert first_draft["state"] == "DRAFTING", first_draft
    assert first_draft["response_body"] == "first draft", first_draft
    assert first_draft["version"] == 3, first_draft
    assert second_draft["state"] == "DRAFTING", second_draft
    assert second_draft["response_body"] == "second draft", second_draft
    assert second_draft["version"] == 4, second_draft
    assert second_draft["response_due_at"] == "2026-08-01T00:00:00.000Z", second_draft
