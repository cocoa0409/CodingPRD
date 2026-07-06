"""Pre-orders, subscriptions, back-issues, and series catalog rules."""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_customer,
    create_series,
    create_issue,
    create_pre_order_payload,
    create_pull_subscription_payload,
    create_back_issue_payload,
    create_comic_issue_payload,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict: INVALID_STATE beats PAST_CUTOFF
# ---------------------------------------------------------------------------
def test_reconfirm_after_cutoff_reports_invalid_state(api, clerk_headers):
    """PRD §2.8: "State — the target resource is in a state from which the
    requested transition or operation is defined, else ERR_INVALID_STATE (409)."
    PRD §2.8: "A lower-numbered check that fails masks any higher-numbered check
    that would also have failed."

    Design: Difficulty/priority_pair_validation_conflict/preorder_confirm_invalid_state_beats_past_cutoff
    """
    cust = create_customer()
    series = create_series()
    issue = create_issue(series["id"], cover_price_cents=400,
                        order_cutoff_date="2026-03-15T00:00:00Z")
    po = validate_success(
        api.create_pre_order(create_pre_order_payload(cust["id"], issue["id"], quantity=1),
                             clerk_headers),
        201,
    )
    # Confirm while clock at default 2026-03-01 (before cutoff): succeeds.
    validate_success(api.transition_pre_order(po["id"], {"to_status": "CONFIRMED"}, clerk_headers), 200)
    # Advance clock past cutoff, then re-confirm the now-CONFIRMED pre-order.
    validate_success(api.set_clock("2026-03-20T00:00:00Z", clerk_headers), 200)
    res = api.transition_pre_order(po["id"], {"to_status": "CONFIRMED"}, clerk_headers)
    # State check (priority 5) masks the temporal cutoff check (priority 6).
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_reconfirm_after_cutoff_not_reported_past_cutoff(api, clerk_headers):
    """PRD §3.4: "Confirming a pre-order advances it from `PENDING` to `CONFIRMED` and carries two preconditions evaluated together: the logical clock must be strictly before the issue's `order_cutoff_date`, else the confirmation is rejected with `ERR_PAST_CUTOFF"

    Design: Difficulty/priority_pair_validation_conflict/preorder_confirm_invalid_state_beats_past_cutoff
    """
    cust = create_customer()
    series = create_series()
    issue = create_issue(series["id"], cover_price_cents=400,
                        order_cutoff_date="2026-03-15T00:00:00Z")
    po = validate_success(
        api.create_pre_order(create_pre_order_payload(cust["id"], issue["id"], quantity=1),
                             clerk_headers),
        201,
    )
    validate_success(api.transition_pre_order(po["id"], {"to_status": "CONFIRMED"}, clerk_headers), 200)
    validate_success(api.set_clock("2026-03-20T00:00:00Z", clerk_headers), 200)
    res = api.transition_pre_order(po["id"], {"to_status": "CONFIRMED"}, clerk_headers)
    body = res.json()
    # The already-CONFIRMED state pre-empts the cutoff path; not ERR_PAST_CUTOFF.
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"


# ---------------------------------------------------------------------------
# Queue B — calculations / validations / state machines / errors / entities
# ---------------------------------------------------------------------------
def test_estimated_total_computed_from_cover_price(api, clerk_headers):
    """PRD §3.4: "At creation the pre-order opens in `PENDING` status and its
    `estimated_total_cents` is fixed to `quantity` multiplied by the issue's
    `cover_price_cents`."

    Design: Corner/calculations/estimated_total_computed_from_cover_price
    """
    cust = create_customer()
    series = create_series()
    issue = create_issue(series["id"], cover_price_cents=450, copies_ordered=10)
    po = validate_success(
        api.create_pre_order(create_pre_order_payload(cust["id"], issue["id"], quantity=3),
                             clerk_headers),
        201,
    )
    assert po["estimated_total_cents"] == 1350


def test_preorder_confirm_past_cutoff_rejected(api, clerk_headers):
    """PRD §3.4: "the logical clock must be strictly before the issue's `order_cutoff_date`, else the confirmation is rejected with `ERR_PAST_CUTOFF"

    Design: Corner/validations/preorder_confirm_past_cutoff_rejected
    """
    cust = create_customer()
    series = create_series()
    issue = create_issue(series["id"], cover_price_cents=400,
                        order_cutoff_date="2026-03-15T00:00:00Z")
    po = validate_success(
        api.create_pre_order(create_pre_order_payload(cust["id"], issue["id"], quantity=1),
                             clerk_headers),
        201,
    )
    validate_success(api.set_clock("2026-03-20T00:00:00Z", clerk_headers), 200)
    res = api.transition_pre_order(po["id"], {"to_status": "CONFIRMED"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_PAST_CUTOFF, expected_status=422)


def test_subscription_pause_resume_cycle(api, clerk_headers):
    """PRD §3.2: "A customer may pause an active subscription, moving it to `PAUSED`, and resume a paused one back to `ACTIVE`; this pause/resume oscillation may repeat any number of times."

    Design: Corner/state_machines/subscription_pause_resume_valid_cycle
    """
    cust = create_customer()
    series = create_series()
    sub = validate_success(
        api.create_pull_subscription(
            create_pull_subscription_payload(cust["id"], series["id"]), clerk_headers
        ),
        201,
    )
    validate_success(
        api.transition_pull_subscription(sub["id"], {"to_status": "PAUSED"}, clerk_headers), 200
    )
    resumed = validate_success(
        api.transition_pull_subscription(sub["id"], {"to_status": "ACTIVE"}, clerk_headers), 200
    )
    assert resumed["status"] == "ACTIVE"


def test_series_discontinued_blocks_issue_order(api, clerk_headers):
    """PRD §3.1: "Moving from `SOLICITED` to `ORDERED` is permitted only when the parent series is still `ACTIVE`; if the series has been discontinued, the advance is rejected with `ERR_SERIES_DISCONTINUED`."

    Design: Corner/errors/series_discontinued_blocks_issue_order
    """
    series = create_series()
    issue = create_issue(series["id"])
    validate_success(api.discontinue_comic_series(series["id"], clerk_headers), 200)
    res = api.transition_comic_issue(issue["id"], {"to_status": "ORDERED"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_SERIES_DISCONTINUED, expected_status=409)


def test_back_issue_bad_enum_condition_validation(api, clerk_headers):
    """PRD §3.5: "created with a `series_id`, an `issue_number` label, a `condition` of either `RAW` or `GRADED"
    PRD §2.8: "Well-formedness — required fields present, enums valid, numbers in
    range, ends_at strictly after starts_at, and commission_pct at least 0 and
    strictly below 1, else ERR_VALIDATION (400)."

    Design: Corner/entities/comic_issue_bad_enum_condition_backissue_validation
    """
    series = create_series()
    res = api.create_back_issue(
        create_back_issue_payload(series["id"], condition="MINT", price_cents=500), clerk_headers
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)
