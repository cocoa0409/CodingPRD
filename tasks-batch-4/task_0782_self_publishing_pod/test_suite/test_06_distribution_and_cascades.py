"""Distribution-request review branches, the publish cascade, and the withdraw
cascade.

Translates difficulty instances
`non_linear_state_machine/distribution_request_approve_vs_reject_branch`,
`transitive_cascade/publish_cascades_dr_live_then_title_live`,
`transitive_cascade/withdraw_cascades_format_unlisted_then_title_unlisted`, and
`cross_entity_state_dependency/distribution_live_requires_format_published`, plus
the corner instance
`state_machines/withdraw_non_live_distribution_returns_invalid_state`.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_publisher_headers,
    create_publisher, create_title, create_amz_channel,
    create_price, create_distribution_request,
    setup_locked_print_format, setup_ready_to_publish, setup_published_print_format,
    publish_format,
)

REVIEWER = TEST_USERS["reviewer_headers"]


def _branch_scenario(api):
    """Locked print format with ACTIVE US + UK prices and two REQUESTED
    distribution requests (US and UK)."""
    channel = create_amz_channel(api)
    base = setup_locked_print_format(api)
    pub, fmt = base["publisher"], base["format"]
    create_price(api, pub["id"], fmt["id"], channel["id"], territory="US")
    create_price(api, pub["id"], fmt["id"], channel["id"], territory="UK", list_price_cents=1500)
    dr_us = create_distribution_request(api, pub["id"], fmt["id"], channel["id"], territory="US")
    dr_uk = create_distribution_request(api, pub["id"], fmt["id"], channel["id"], territory="UK")
    return pub, fmt, dr_us, dr_uk


# --- approve vs reject branch ------------------------------------------------

def test_approve_leaves_request_approved_with_no_reason(api):
    """PRD 3.6: "On approval, the request transitions REQUESTED -> APPROVED; then,
    if the target format is already PUBLISHED, it immediately advances
    APPROVED -> LIVE in the same operation ... If the format is not yet PUBLISHED,
    the request simply waits in APPROVED until the format publishes".

    Design: Difficulty/non_linear_state_machine/distribution_request_approve_vs_reject_branch
    """
    pub, fmt, dr_us, dr_uk = _branch_scenario(api)
    approved = get_success_data(api.approve_distribution(dr_us["id"], REVIEWER))
    assert approved["status"] == "APPROVED", "format is only CONTENT_LOCKED, so DR waits in APPROVED"
    assert approved["reason"] is None, "approval must not capture a reason"


def test_reject_captures_reason_and_is_terminal(api):
    """PRD 3.6: "On rejection, the request transitions REQUESTED -> REJECTED and
    captures the reviewer's reason; this branch is divergent - the format's and
    the title's states are left completely untouched, and a rejected request can
    never reach LIVE."

    Design: Difficulty/non_linear_state_machine/distribution_request_approve_vs_reject_branch
    """
    pub, fmt, dr_us, dr_uk = _branch_scenario(api)
    rejected = get_success_data(
        api.reject_distribution(dr_uk["id"], {"reason": "cover art too low res"}, REVIEWER)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["reason"] == "cover art too low res"


# --- publish cascade: format -> isbn / dr -> title ---------------------------

def test_publish_sets_format_published_and_locks_isbn(api):
    """PRD 3.7: "First the format itself moves CONTENT_LOCKED -> PUBLISHED. That
    publication then locks the edition's identifier: the assigned Isbn (the one
    whose assigned_format_id points at this format) transitions ASSIGNED ->
    LOCKED."

    Design: Difficulty/transitive_cascade/publish_cascades_dr_live_then_title_live
    """
    base = setup_ready_to_publish(api, with_distribution=True)
    pub, fmt, isbn = base["publisher"], base["format"], base["isbn"]
    headers = make_publisher_headers(pub["id"])
    published = get_success_data(api.publish_format(fmt["id"], headers))
    assert published["status"] == "PUBLISHED"
    got_isbn = get_success_data(api.get_isbn(isbn["id"], headers))
    assert got_isbn["status"] == "LOCKED"


def test_publish_cascades_approved_request_to_live_and_title_to_live(api):
    """PRD 3.7: "It also activates the format's approved listings: every
    DistributionRequest for this format that is sitting in APPROVED transitions
    APPROVED -> LIVE. Each of those requests reaching LIVE in turn drives the
    parent Title DRAFT -> LIVE if the title is not already LIVE."

    Design: Difficulty/transitive_cascade/publish_cascades_dr_live_then_title_live
    """
    base = setup_ready_to_publish(api, with_distribution=True)
    pub, fmt, title, dr = base["publisher"], base["format"], base["title"], base["dr"]
    headers = make_publisher_headers(pub["id"])
    assert dr["status"] == "APPROVED", "the request waits in APPROVED before publish"
    publish_format(api, pub["id"], fmt["id"])
    got_dr = get_success_data(api.get_distribution(dr["id"], headers))
    assert got_dr["status"] == "LIVE"
    got_title = get_success_data(api.get_title(title["id"], headers))
    assert got_title["status"] == "LIVE"


# --- distribution reaches LIVE only when format PUBLISHED --------------------

def test_approve_while_content_locked_leaves_request_approved(api):
    """PRD 3.6: "If the format is not yet PUBLISHED, the request simply waits in
    APPROVED until the format publishes, at which point publication itself
    completes the advance to LIVE".

    Design: Difficulty/cross_entity_state_dependency/distribution_live_requires_format_published
    """
    base = setup_ready_to_publish(api, with_distribution=True)
    assert base["dr"]["status"] == "APPROVED", \
        "approving while CONTENT_LOCKED must leave the request APPROVED, not LIVE"


def test_publish_advances_waiting_request_to_live(api):
    """PRD 3.7: "It also activates the format's approved listings: every
    DistributionRequest for this format that is sitting in APPROVED transitions
    APPROVED -> LIVE."

    Design: Difficulty/cross_entity_state_dependency/distribution_live_requires_format_published
    """
    base = setup_ready_to_publish(api, with_distribution=True)
    pub, fmt, dr = base["publisher"], base["format"], base["dr"]
    headers = make_publisher_headers(pub["id"])
    publish_format(api, pub["id"], fmt["id"])
    got_dr = get_success_data(api.get_distribution(dr["id"], headers))
    assert got_dr["status"] == "LIVE"


# --- withdraw cascade: dr -> format -> title ---------------------------------

def test_withdraw_sets_request_withdrawn_and_unlists_format(api):
    """PRD 3.6: "Withdrawal triggers a downstream cascade: once the request is
    withdrawn, if no remaining LIVE distribution request exists for the format,
    the format transitions PUBLISHED -> UNLISTED".

    Design: Difficulty/transitive_cascade/withdraw_cascades_format_unlisted_then_title_unlisted
    """
    base = setup_published_print_format(api, with_distribution=True)
    pub, fmt, dr = base["publisher"], base["format"], base["dr"]
    headers = make_publisher_headers(pub["id"])
    withdrawn = get_success_data(api.withdraw_distribution(dr["id"], headers))
    assert withdrawn["status"] == "WITHDRAWN"
    got_fmt = get_success_data(api.get_format(fmt["id"], headers))
    assert got_fmt["status"] == "UNLISTED"


def test_withdraw_cascades_title_to_unlisted(api):
    """PRD 3.6: "and once a format goes unlisted, if every format under the parent
    title is now UNLISTED, the title transitions LIVE -> UNLISTED."

    Design: Difficulty/transitive_cascade/withdraw_cascades_format_unlisted_then_title_unlisted
    """
    base = setup_published_print_format(api, with_distribution=True)
    pub, fmt, title, dr = base["publisher"], base["format"], base["title"], base["dr"]
    headers = make_publisher_headers(pub["id"])
    api.withdraw_distribution(dr["id"], headers)
    got_title = get_success_data(api.get_title(title["id"], headers))
    assert got_title["status"] == "UNLISTED", \
        "the single format is UNLISTED, so its title must go UNLISTED"


def test_withdraw_non_live_distribution_returns_invalid_state(api):
    """PRD 3.6: "A Publisher may later withdraw a live listing, transitioning it
    LIVE -> WITHDRAWN; withdrawal is only valid from LIVE, otherwise
    ERR_DISTRIBUTION_INVALID_STATE."

    Design: Corner/state_machines/withdraw_non_live_distribution_returns_invalid_state
    """
    channel = create_amz_channel(api)
    base = setup_locked_print_format(api)
    pub, fmt = base["publisher"], base["format"]
    create_price(api, pub["id"], fmt["id"], channel["id"], territory="US")
    dr = create_distribution_request(api, pub["id"], fmt["id"], channel["id"], territory="US")
    assert dr["status"] == "REQUESTED"
    validate_error(
        api.withdraw_distribution(dr["id"], make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_DISTRIBUTION_INVALID_STATE,
    )
