"""
Cross-entity gates and the two reservation windows of the transfer desk.

Two kinds of dependency are pinned here. The first runs between rows: a purchase
agreement cannot settle while any of the consent prerequisites raised on it is
still undecided, and a bid package cannot be published while the valuation run it
points at has been invalidated by a rate curve the hedge desk published
afterwards. The second kind is temporal capacity: a portfolio hosts exactly one
live marketing window, measured as a half-open interval so that back-to-back
windows may touch, while an acquiring servicer onboards exactly one transfer at a
time, measured as a closed interval so that windows sharing a single calendar day
collide. Testing both together is the point — the two conventions disagree about
what "touching" means.
"""

from test_helpers import (
    C,
    F,
    U,
    ApiClient,
    JsonDict,
    build_approved_agreement,
    build_awarded_trade,
    build_completed_transfer,
    build_published_package,
    build_ready_transfer,
    build_settled_trade,
    build_stratified_package,
    data_of,
    refresh_portfolio,
    rows_of,
    validate_error,
    validate_success,
    ERR_AGENCY_APPROVAL_PENDING,
    ERR_MARKETING_WINDOW_OVERLAP,
    ERR_ONBOARDING_CAPACITY_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALUATION_STALE,
)

# The incumbent marketing window every package below is measured against.
WINDOW_1_START = "2026-08-01T00:00:00Z"
WINDOW_1_END = "2026-08-15T00:00:00Z"

# Straddles the incumbent by five days.
WINDOW_STRADDLE_START = "2026-08-10T00:00:00Z"
WINDOW_STRADDLE_END = "2026-08-24T00:00:00Z"

# Starts exactly when the incumbent ends.
WINDOW_ADJACENT_START = "2026-08-15T00:00:00Z"
WINDOW_ADJACENT_END = "2026-08-29T00:00:00Z"

# Starts one second before the incumbent ends.
WINDOW_ONE_SECOND_EARLY_START = "2026-08-14T23:59:59Z"
WINDOW_ONE_SECOND_EARLY_END = "2026-08-28T00:00:00Z"

# Pool T at curve C1 (4000 bps) and at curve C2 (4050 bps).
POOL_T_RESERVE_AT_C1_CENTS = 162997
POOL_T_STATIC_VALUE_AT_C2_CENTS = 175064
POOL_T_RESERVE_AT_C2_CENTS = 166311

# The single-loan Pool M deal.
POOL_M_RESERVE_CENTS = 40749
POOL_M_PRICE_CENTS = 118001

# Transfer dates and the onboarding blackouts they materialise.
TRANSFER_DATE_1 = "2026-09-01"
WINDOW_1_ONBOARD_START = "2026-08-02"
WINDOW_1_ONBOARD_END = "2026-10-01"
TRANSFER_DATE_TOUCHING = "2026-10-31"
TRANSFER_DATE_CLEAR = "2026-11-01"
WINDOW_2_ONBOARD_START = "2026-10-02"
WINDOW_2_ONBOARD_END = "2026-12-01"

_DESK_KEYS = (
    "clock", "seller", "seller_id", "seller_headers",
    "buyer", "buyer_id", "buyer_headers",
    "assumption_set", "assumption_set_id", "curve", "curve_id",
)


def _second_deal_env(env: JsonDict) -> JsonDict:
    """A fresh environment reusing the same desk, servicers, assumptions, curve."""
    return {key: env[key] for key in _DESK_KEYS}


def _awarded_with_two_prerequisites(api: ApiClient) -> JsonDict:
    """An awarded pool T trade carrying one agency and one investor prerequisite."""
    env = build_awarded_trade(api)
    env["agency_request"] = F.create_approval_request(
        api, env["agreement_id"], approver_type="AGENCY", agency_type="FNMA")
    env["investor_request"] = F.create_approval_request(
        api, env["agreement_id"], approver_type="INVESTOR", agency_type=None)
    return env


def _settle_payload(transfer_date: str) -> JsonDict:
    """The settle request body used throughout this module."""
    return {"sale_date": C.SALE_DATE, "transfer_date": transfer_date}


def test_settle_is_refused_while_a_sibling_prerequisite_is_still_pending(api):
    """
    One granted agency consent does not let the trade settle while the investor
    consent on the same agreement is still undecided.

    PRD: "An agreement still in `PENDING_APPROVALS` reaches this operation rather than being turned away on state grounds, precisely so that the informative answer is given: while at least one request on it is `PENDING`, that is, while `approval_pending_count` is greater than 0, settlement fails with `ERR_AGENCY_APPROVAL_PENDING` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/settlement_blocked_by_a_sibling_approval_request_state
    """
    env = _awarded_with_two_prerequisites(api)
    assert env["agency_request"]["status"] == "PENDING"
    assert env["investor_request"]["status"] == "PENDING"

    submitted = F.submit_for_approval(api, env["agreement_id"])
    assert submitted["status"] == "PENDING_APPROVALS"
    assert submitted["approval_pending_count"] == 2

    decided = F.decide(api, env["agency_request"]["id"], decision="APPROVED")
    assert decided["status"] == "APPROVED"

    before = F.read_agreement(api, env["agreement_id"])
    assert before["status"] == "PENDING_APPROVALS"
    assert before["approval_pending_count"] == 1

    response = api.settle_agreement(
        env["agreement_id"], _settle_payload(C.TRANSFER_DATE), U.MANAGER)
    validate_error(response, ERR_AGENCY_APPROVAL_PENDING, 409)

    after = F.read_agreement(api, env["agreement_id"])
    assert after["status"] == "PENDING_APPROVALS"
    assert after["sale_date"] is None
    assert after["transfer_date"] is None
    assert after["version"] == before["version"]
    assert rows_of(api.list_servicing_transfers(U.MANAGER)) == []


def test_settle_succeeds_unchanged_once_the_second_prerequisite_is_decided(api):
    """
    The identical settle request goes through the moment the last prerequisite is
    decided, with no field on the agreement edited in between.

    PRD: "When `approval_pending_count` reaches 0 and `condition_count` is 0, the agreement moves `PENDING_APPROVALS → APPROVED` and its `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/settlement_blocked_by_a_sibling_approval_request_state
    """
    env = _awarded_with_two_prerequisites(api)
    F.submit_for_approval(api, env["agreement_id"])
    F.decide(api, env["agency_request"]["id"], decision="APPROVED")

    blocked = api.settle_agreement(
        env["agreement_id"], _settle_payload(C.TRANSFER_DATE), U.MANAGER)
    validate_error(blocked, ERR_AGENCY_APPROVAL_PENDING, 409)

    F.decide(api, env["investor_request"]["id"], decision="APPROVED",
             headers=U.APPROVER_2)
    joined = F.read_agreement(api, env["agreement_id"])
    assert joined["status"] == "APPROVED"
    assert joined["approval_pending_count"] == 0
    assert joined["condition_count"] == 0

    settled = validate_success(api.settle_agreement(
        env["agreement_id"], _settle_payload(C.TRANSFER_DATE), U.MANAGER))
    assert settled["status"] == "SETTLED"
    assert settled["sale_date"] == C.SALE_DATE
    assert settled["transfer_date"] == C.TRANSFER_DATE

    transfers = rows_of(api.list_servicing_transfers(
        U.MANAGER, {"purchase_agreement_id": env["agreement_id"]}))
    assert len(transfers) == 1
    assert transfers[0]["status"] == "IN_PROGRESS"


def test_one_approver_cannot_supply_both_consents_the_agreement_needs(api):
    """
    The second consent on the same agreement must come from a different operator,
    so the unblocking decision cannot be taken by the approver who granted the
    first one.

    PRD: "When an `AgencyApprover` records a decision, the acting `X-User-ID` must differ from `decided_by_user_id` of *every* approval request on the same agreement that has already been decided."

    Design: Difficulty/cross_entity_state_dependency/settlement_blocked_by_a_sibling_approval_request_state
    """
    env = _awarded_with_two_prerequisites(api)
    F.submit_for_approval(api, env["agreement_id"])
    F.decide(api, env["agency_request"]["id"], decision="APPROVED")

    response = api.decide_approval_request(
        env["investor_request"]["id"], {"decision": "APPROVED"}, U.APPROVER)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    still_pending = data_of(
        api.get_approval_request(env["investor_request"]["id"], U.MANAGER))
    assert still_pending["status"] == "PENDING"
    assert still_pending["decided_by_user_id"] is None

    agreement = F.read_agreement(api, env["agreement_id"])
    assert agreement["status"] == "PENDING_APPROVALS"
    assert agreement["approval_pending_count"] == 1


def test_new_curve_stales_the_bound_run_and_the_portfolio_freshness(api):
    """
    A rate curve published by the hedge desk invalidates the valuation run a
    stratified package points at, without the package itself being touched.

    PRD: "The second link stales the valuations that were priced off it: every `ValuationRun` whose bound snapshot is the one just superseded and whose status is `COMPLETED` moves `COMPLETED → STALE`, has `staled_at` stamped, and has its `version` incremented by 1; where such a run is the one a portfolio currently resolves to, that portfolio's `valuation_freshness` recomputes to `STALE`."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_by_bound_valuation_run_state
    """
    env = build_stratified_package(api)
    assert env["package"]["status"] == "STRATIFIED"
    assert env["valuation_run"]["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS
    assert env["valuation_run"]["status"] == "COMPLETED"

    F.create_rate_curve(api, C.CURVE_C2)

    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert run["status"] == "STALE"
    assert run["staled_at"] is not None
    assert run["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS

    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["valuation_freshness"] == "STALE"


def test_publication_is_refused_while_the_bound_run_is_stale(api):
    """
    Publishing a package whose pointed-at valuation run was staled by a later
    curve is refused, and the package is left exactly as it stood.

    PRD: "First, the bound valuation run must be `COMPLETED`; a `STALE` or `SUPERSEDED` run is not a publishable basis and the attempt is refused with `ERR_VALUATION_STALE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_by_bound_valuation_run_state
    """
    env = build_stratified_package(api)
    stratified_version = env["package"]["version"]

    F.create_rate_curve(api, C.CURVE_C2)

    before = F.read_package(api, env["package_id"])
    assert before["status"] == "STRATIFIED"
    assert before["suspended_reason"] is None
    assert before["version"] == stratified_version

    response = api.publish_bid_package(env["package_id"], U.MANAGER)
    validate_error(response, ERR_VALUATION_STALE, 409)

    after = F.read_package(api, env["package_id"])
    assert after["status"] == "STRATIFIED"
    assert after["published_at"] is None
    assert after["reserve_price_cents"] is None
    assert after["version"] == stratified_version


def test_a_fresh_run_on_the_new_curve_publishes_in_an_adjacent_window(api):
    """
    A package bound to a run recomputed against the new curve publishes into the
    window that starts exactly when the stale package's window ends, while the
    stale package stays unpublishable.

    PRD: "Second, the marketing window must be free: the half-open interval from `marketing_start_at` up to `bid_deadline_at` must not overlap the window of any other package on the same portfolio whose status is `STRATIFIED`, `PUBLISHED` or `BIDDING_SUSPENDED` — capacity is exactly one live window per portfolio, and because the interval is half-open, back-to-back windows that merely touch at an instant do not collide."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_by_bound_valuation_run_state
    """
    env = build_stratified_package(api, marketing_start_at=WINDOW_1_START,
                                  bid_deadline_at=WINDOW_1_END)
    F.create_rate_curve(api, C.CURVE_C2)

    refresh_portfolio(api, env)
    fresh_run = F.run_valuation(api, env["portfolio_id"],
                                env["assumption_set_id"],
                                env["portfolio_version"])
    assert fresh_run["status"] == "COMPLETED"
    assert fresh_run["value_cents"] == POOL_T_STATIC_VALUE_AT_C2_CENTS

    adjacent = F.create_bid_package(
        api, env["portfolio_id"], fresh_run["id"], scheme="BY_NOTE_RATE",
        marketing_start_at=WINDOW_ADJACENT_START,
        bid_deadline_at=WINDOW_ADJACENT_END)
    F.stratify(api, adjacent["id"])
    published = F.publish(api, adjacent["id"])
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None
    assert published["reserve_price_cents"] == POOL_T_RESERVE_AT_C2_CENTS

    blocked = api.publish_bid_package(env["package_id"], U.MANAGER)
    validate_error(blocked, ERR_VALUATION_STALE, 409)
    assert F.read_package(api, env["package_id"])["status"] == "STRATIFIED"


def test_a_marketing_window_straddling_the_incumbent_cannot_publish(api):
    """
    A second package whose window starts five days inside the live one may be
    created and stratified, but is refused at publication.

    PRD: "Second, the marketing window must be free: the half-open interval from `marketing_start_at` up to `bid_deadline_at` must not overlap the window of any other package on the same portfolio whose status is `STRATIFIED`, `PUBLISHED` or `BIDDING_SUSPENDED` — capacity is exactly one live window per portfolio, and because the interval is half-open, back-to-back windows that merely touch at an instant do not collide."

    Design: Difficulty/resource_temporal_overlap/marketing_windows_on_one_portfolio_are_half_open_capacity_one
    """
    env = build_published_package(api, marketing_start_at=WINDOW_1_START,
                                 bid_deadline_at=WINDOW_1_END)
    assert env["package"]["status"] == "PUBLISHED"
    assert env["package"]["reserve_price_cents"] == POOL_T_RESERVE_AT_C1_CENTS

    straddling = F.create_bid_package(
        api, env["portfolio_id"], env["valuation_run_id"],
        scheme="BY_NOTE_RATE", marketing_start_at=WINDOW_STRADDLE_START,
        bid_deadline_at=WINDOW_STRADDLE_END)
    assert straddling["status"] == "DRAFT"
    assert F.stratify(api, straddling["id"])["status"] == "STRATIFIED"

    response = api.publish_bid_package(straddling["id"], U.MANAGER)
    validate_error(response, ERR_MARKETING_WINDOW_OVERLAP, 409)

    after = F.read_package(api, straddling["id"])
    assert after["status"] == "STRATIFIED"
    assert after["published_at"] is None
    assert after["reserve_price_cents"] is None
    assert F.read_package(api, env["package_id"])["status"] == "PUBLISHED"


def test_a_marketing_window_starting_at_the_incumbent_deadline_publishes(api):
    """
    The instant the incumbent's window ends belongs to the newcomer only, so a
    back-to-back window publishes alongside the live one.

    PRD: "Second, the marketing window must be free: the half-open interval from `marketing_start_at` up to `bid_deadline_at` must not overlap the window of any other package on the same portfolio whose status is `STRATIFIED`, `PUBLISHED` or `BIDDING_SUSPENDED` — capacity is exactly one live window per portfolio, and because the interval is half-open, back-to-back windows that merely touch at an instant do not collide."

    Design: Difficulty/resource_temporal_overlap/marketing_windows_on_one_portfolio_are_half_open_capacity_one
    """
    env = build_published_package(api, marketing_start_at=WINDOW_1_START,
                                 bid_deadline_at=WINDOW_1_END)

    adjacent = F.create_bid_package(
        api, env["portfolio_id"], env["valuation_run_id"],
        scheme="BY_NOTE_RATE", marketing_start_at=WINDOW_ADJACENT_START,
        bid_deadline_at=WINDOW_ADJACENT_END)
    F.stratify(api, adjacent["id"])

    published = F.publish(api, adjacent["id"])
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None
    assert published["reserve_price_cents"] == POOL_T_RESERVE_AT_C1_CENTS
    assert F.read_package(api, env["package_id"])["status"] == "PUBLISHED"


def test_a_marketing_window_starting_one_second_early_cannot_publish(api):
    """
    Moving the newcomer's start one second before the incumbent's deadline turns
    the legal back-to-back window into a collision.

    PRD: "Second, the marketing window must be free: the half-open interval from `marketing_start_at` up to `bid_deadline_at` must not overlap the window of any other package on the same portfolio whose status is `STRATIFIED`, `PUBLISHED` or `BIDDING_SUSPENDED` — capacity is exactly one live window per portfolio, and because the interval is half-open, back-to-back windows that merely touch at an instant do not collide."

    Design: Difficulty/resource_temporal_overlap/marketing_windows_on_one_portfolio_are_half_open_capacity_one
    """
    env = build_published_package(api, marketing_start_at=WINDOW_1_START,
                                 bid_deadline_at=WINDOW_1_END)

    overlapping = F.create_bid_package(
        api, env["portfolio_id"], env["valuation_run_id"],
        scheme="BY_NOTE_RATE",
        marketing_start_at=WINDOW_ONE_SECOND_EARLY_START,
        bid_deadline_at=WINDOW_ONE_SECOND_EARLY_END)
    F.stratify(api, overlapping["id"])

    response = api.publish_bid_package(overlapping["id"], U.MANAGER)
    validate_error(response, ERR_MARKETING_WINDOW_OVERLAP, 409)

    after = F.read_package(api, overlapping["id"])
    assert after["status"] == "STRATIFIED"
    assert after["published_at"] is None


def test_onboarding_windows_sharing_one_calendar_day_collide(api):
    """
    A second deal for the same acquiring servicer whose blackout shares exactly
    one day with the live one is refused at settlement.

    PRD: "Because the interval is closed, two windows that merely touch at an endpoint **do** collide, and the refusal is `ERR_ONBOARDING_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/buyer_onboarding_windows_are_closed_and_collide_on_touch
    """
    env = build_settled_trade(api, transfer_date=TRANSFER_DATE_1)
    incumbent = env["transfer"]
    assert incumbent["status"] == "IN_PROGRESS"
    assert incumbent["onboarding_window_start"] == WINDOW_1_ONBOARD_START
    assert incumbent["onboarding_window_end"] == WINDOW_1_ONBOARD_END

    second = build_approved_agreement(api, _second_deal_env(env),
                                      loans=C.LOANS_M, name="Pool-M")
    assert second["valuation_run"]["value_cents"] == C.POOL_M_STATIC_VALUE_CENTS
    assert second["package"]["reserve_price_cents"] == POOL_M_RESERVE_CENTS
    assert second["bid"]["bid_value_cents"] == POOL_M_PRICE_CENTS
    assert second["agreement"]["purchase_price_cents"] == POOL_M_PRICE_CENTS
    assert second["agreement"]["status"] == "APPROVED"

    response = api.settle_agreement(
        second["agreement_id"], _settle_payload(TRANSFER_DATE_TOUCHING),
        U.MANAGER)
    validate_error(response, ERR_ONBOARDING_CAPACITY_EXCEEDED, 409)

    after = F.read_agreement(api, second["agreement_id"])
    assert after["status"] == "APPROVED"
    assert after["transfer_date"] is None
    assert after["sale_date"] is None
    assert len(rows_of(api.list_servicing_transfers(U.MANAGER))) == 1


def test_an_onboarding_window_clear_by_one_day_settles(api):
    """
    Moving the transfer date one day later lifts the blackout clear of the
    incumbent's last day and the same buyer onboards a second transfer.

    PRD: "Finally, the buyer's onboarding capacity is exactly one transfer at a time: the closed window running from 30 calendar days before the transfer date to 30 calendar days after it must not intersect the equivalent window of any existing servicing transfer for the same buyer whose status is `IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/buyer_onboarding_windows_are_closed_and_collide_on_touch
    """
    env = build_settled_trade(api, transfer_date=TRANSFER_DATE_1)
    second = build_approved_agreement(api, _second_deal_env(env),
                                      loans=C.LOANS_M, name="Pool-M")

    blocked = api.settle_agreement(
        second["agreement_id"], _settle_payload(TRANSFER_DATE_TOUCHING),
        U.MANAGER)
    validate_error(blocked, ERR_ONBOARDING_CAPACITY_EXCEEDED, 409)

    settled = validate_success(api.settle_agreement(
        second["agreement_id"], _settle_payload(TRANSFER_DATE_CLEAR),
        U.MANAGER))
    assert settled["status"] == "SETTLED"
    assert settled["transfer_date"] == TRANSFER_DATE_CLEAR

    opened = F.find_transfer(api, second["agreement_id"])
    assert opened["status"] == "IN_PROGRESS"
    assert opened["onboarding_window_start"] == WINDOW_2_ONBOARD_START
    assert opened["onboarding_window_end"] == WINDOW_2_ONBOARD_END

    buyer = data_of(api.get_counterparty(env["buyer_id"], U.MANAGER))
    assert buyer["open_transfer_count"] == 2


def test_completing_the_incumbent_transfer_frees_the_onboarding_window(api):
    """
    The blackout is only reserved by transfers still in progress, so once the
    incumbent completes the previously refused transfer date is accepted.

    PRD: "Finally, the buyer's onboarding capacity is exactly one transfer at a time: the closed window running from 30 calendar days before the transfer date to 30 calendar days after it must not intersect the equivalent window of any existing servicing transfer for the same buyer whose status is `IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/buyer_onboarding_windows_are_closed_and_collide_on_touch
    """
    env = build_settled_trade(api, transfer_date=TRANSFER_DATE_1)
    second = build_approved_agreement(api, _second_deal_env(env),
                                      loans=C.LOANS_M, name="Pool-M")

    blocked = api.settle_agreement(
        second["agreement_id"], _settle_payload(TRANSFER_DATE_TOUCHING),
        U.MANAGER)
    validate_error(blocked, ERR_ONBOARDING_CAPACITY_EXCEEDED, 409)

    build_ready_transfer(api, env)
    build_completed_transfer(api, env)
    assert env["transfer"]["status"] == "COMPLETED"

    settled = validate_success(api.settle_agreement(
        second["agreement_id"], _settle_payload(TRANSFER_DATE_TOUCHING),
        U.MANAGER))
    assert settled["status"] == "SETTLED"
    assert settled["transfer_date"] == TRANSFER_DATE_TOUCHING

    opened = F.find_transfer(api, second["agreement_id"])
    assert opened["onboarding_window_start"] == WINDOW_1_ONBOARD_END
    assert opened["onboarding_window_end"] == "2026-11-30"

    buyer = data_of(api.get_counterparty(env["buyer_id"], U.MANAGER))
    assert buyer["open_transfer_count"] == 1
