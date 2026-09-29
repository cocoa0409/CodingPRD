"""
Multi-hop cascades of the Digital Estate Fiduciary Access API.

A single write in this contract can propagate four entities deep, and the hops
are not unconditional: an approval creates a grant, discloses accounts, opens a
cancellation order for the subscription accounts it just disclosed and only then
recomputes the estate; a letters revocation stops dead at its first hop while any
co-fiduciary still holds issued letters; and a cancellation that fails leaves
every downstream record exactly as it found it while the confirmation of the
same order rewrites three of them.
"""

from datetime import datetime, timedelta

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    COURT_REGISTRAR_HEADERS,
    factories as f,
    fixtures,
    make_platform_compliance_headers,
)
from test_helpers.api_errors import (
    ERR_INVALID_ORDER_STATE,
    ERR_LETTERS_NOT_ISSUED,
)
from test_helpers.constants import (
    ACCESS_CATALOG_DISCLOSED,
    ACCESS_REVOKED,
    BASIS_STATUTORY_DEFAULT,
    BILLING_ACTIVE,
    BILLING_CANCELLED,
    CATEGORY_CLOUD_STORAGE,
    CLAMP_NONE,
    CLOCK_EPOCH,
    DECISION_APPROVED,
    DOC_ACTION_REVOKE,
    DOC_REVOKED,
    GRANT_ACTIVE,
    GRANT_REVOKED,
    GRANT_TERM_DAYS,
    LETTERS_ISSUED,
    LETTERS_REVOKED,
    ORDER_ACTION_CONFIRM,
    ORDER_ACTION_FAIL,
    ORDER_ACTION_REQUEST,
    ORDER_CONFIRMED,
    ORDER_FAILED,
    ORDER_PENDING,
    ORDER_REQUESTED,
    PHASE_DISCLOSURE,
    PHASE_INTAKE,
    REFUND_POLICY_PRORATA_DAILY,
    REQ_ACTION_DECIDE,
    REQ_ACTION_SUBMIT,
    REVOCATION_LETTERS_REVOKED,
    SCOPE_CATALOG_ONLY,
    TERM_ACTIVE,
    TERM_CANCELLED,
)

# The cancellation of the decedent's subscription is asked for from this date.
_EFFECTIVE_DATE = "2026-03-15"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of its fractional-digit width."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stream_estate_awaiting_a_decision(api, case_number):
    """
    One subscription provider, one estate with no directives at all, a
    SUBSCRIPTION account carrying a term, a CLOUD_STORAGE account on the same
    provider, and a catalogue request sitting UNDER_REVIEW.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    platform = fixtures.register_subscription_platform(api)
    ctx = fixtures.authorized_estate(api, case_number)
    subscription = fixtures.add_subscription_asset(
        api, ctx, platform["id"], account_handle="stream-premium"
    )
    term = fixtures.add_subscription_term(api, ctx, subscription["id"])
    cloud = fixtures.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="stream-recordings",
        quoted_value_cents=45000,
    )
    request = fixtures.draft_request(api, ctx, platform["id"], platform["form_code"])
    fixtures.submit_request(api, ctx, request["id"])
    fixtures.start_review(api, platform["id"], request["id"])
    return {
        "ctx": ctx,
        "platform": platform,
        "subscription_id": subscription["id"],
        "term_id": term["id"],
        "cloud_id": cloud["id"],
        "request_id": request["id"],
        "desk": make_platform_compliance_headers(platform["id"]),
    }


def _approve(api, env):
    return validate_success(
        api.transition_platform_request(
            env["request_id"],
            f.request_transition_payload(REQ_ACTION_DECIDE, decision=DECISION_APPROVED),
            env["desk"],
        ),
        200,
    )


def test_approval_creates_the_grant_it_freezes_at_decision_time(api):
    """
    The first hop of the cascade brings an authority grant into existence with
    the scope, basis and clock-derived term the decision fixed for it.

    PRD: "A grant records the `estate_id` and `platform_id` it covers and the `platform_request_id` that produced it, freezes the `granted_scope` and `basis` that the resolution of §3.3 produced at decision time along with the `clamp_reason` that resolution carried, opens its `status` at `ACTIVE`, sets `effective_from` to the current clock instant and `expires_at` to that instant advanced by 90 days, and leaves `revocation_reason` null."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I")
    ctx = env["ctx"]
    _approve(api, env)

    rows, meta = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, platform_request_id=env["request_id"])
    )
    assert meta["total_count"] == 1
    grant = rows[0]
    assert grant["estate_id"] == ctx.estate_id
    assert grant["platform_id"] == env["platform"]["id"]
    assert grant["platform_request_id"] == env["request_id"]
    assert grant["status"] == GRANT_ACTIVE
    assert grant["granted_scope"] == SCOPE_CATALOG_ONLY
    assert grant["basis"] == BASIS_STATUTORY_DEFAULT
    assert grant["clamp_reason"] == CLAMP_NONE
    assert grant["revocation_reason"] is None
    assert _instant(grant["effective_from"]) == _instant(CLOCK_EPOCH)
    assert _instant(grant["expires_at"]) == _instant(CLOCK_EPOCH) + timedelta(
        days=GRANT_TERM_DAYS
    )


def test_the_undirected_estate_falls_to_the_statutory_default(api):
    """
    No directive was ever recorded on this estate, so the resolution frozen onto
    the request at decision time is the statutory one.

    PRD: "When the candidate set is empty there is no winner, and the statutory default applies: the base scope is `CATALOG_ONLY` and the basis is `STATUTORY_DEFAULT`."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I2")
    approved = _approve(api, env)

    assert approved["resolved_scope"] == SCOPE_CATALOG_ONLY
    assert approved["resolved_basis"] == BASIS_STATUTORY_DEFAULT
    assert approved["clamp_reason"] == CLAMP_NONE


def test_the_request_keeps_the_same_frozen_triple_as_the_grant(api):
    """
    The decision writes the resolution onto two records at once, so the package
    and the grant it produced agree on scope, basis and clamp.

    PRD: "The frozen triple matters: the request record itself also keeps `resolved_scope`, `resolved_basis` and `clamp_reason` as of the decision, so a directive revoked afterwards does not retroactively rewrite what the provider agreed to."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I3")
    approved = _approve(api, env)

    grant = fixtures.grant_for_request(api, env["ctx"], env["request_id"])
    assert grant["granted_scope"] == approved["resolved_scope"]
    assert grant["basis"] == approved["resolved_basis"]
    assert grant["clamp_reason"] == approved["clamp_reason"]


def test_the_second_hop_discloses_both_accounts_to_the_granted_level(api):
    """
    Every account of that provider on the estate is raised by the same approval,
    and a catalogue-only grant with nothing clamped puts both of them at the
    catalogue level with no clamp note.

    PRD: "If the `granted_scope` is `CATALOG_ONLY`, the account moves to `CATALOG_DISCLOSED`, and its `content_clamp_reason` becomes `COURT_ORDER_REQUIRED` when the grant's own `clamp_reason` is `COURT_ORDER_REQUIRED` and `NONE` otherwise — the account carries a machine-readable note explaining why content stopped short."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I4")
    ctx = env["ctx"]
    _approve(api, env)

    subscription = fixtures.read_asset(api, ctx, env["subscription_id"])
    cloud = fixtures.read_asset(api, ctx, env["cloud_id"])
    assert subscription["access_status"] == ACCESS_CATALOG_DISCLOSED
    assert subscription["content_clamp_reason"] == CLAMP_NONE
    assert cloud["access_status"] == ACCESS_CATALOG_DISCLOSED
    assert cloud["content_clamp_reason"] == CLAMP_NONE


def test_the_second_hop_stamps_the_disclosure_instant_from_the_clock(api):
    """
    Both accounts were opened with no disclosure instant at all; the approval is
    what fills it, and it fills it with the logical clock rather than wall time.

    PRD: "Whenever an account's `access_status` rises above `UNVERIFIED` for the first time, `disclosed_at` is stamped with the clock instant."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I5")
    ctx = env["ctx"]
    assert fixtures.read_asset(api, ctx, env["subscription_id"])["disclosed_at"] is None
    assert fixtures.read_asset(api, ctx, env["cloud_id"])["disclosed_at"] is None

    _approve(api, env)

    subscription = fixtures.read_asset(api, ctx, env["subscription_id"])
    cloud = fixtures.read_asset(api, ctx, env["cloud_id"])
    assert _instant(subscription["disclosed_at"]) == _instant(CLOCK_EPOCH)
    assert _instant(cloud["disclosed_at"]) == _instant(CLOCK_EPOCH)


def test_the_third_hop_fires_only_for_the_subscription_account(api):
    """
    The cancellation hop is conditional on what the previous hop did per account:
    the subscription gets an order carrying the provider's refund terms, while
    the cloud-storage account disclosed by the very same grant gets none.

    PRD: "For every account the second hop has just disclosed whose `category` is `SUBSCRIPTION` and which does not already have a cancellation order, the system creates a **`CancellationOrder`** in `PENDING` status and copies the provider's `refund_policy` into the order's `refund_policy_snapshot` at that moment."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I6")
    ctx = env["ctx"]
    _approve(api, env)

    sub_rows, sub_meta = validate_paginated(
        api.list_cancellation_orders(ctx.fid_headers, asset_id=env["subscription_id"])
    )
    assert sub_meta["total_count"] == 1
    order = sub_rows[0]
    assert order["status"] == ORDER_PENDING
    assert order["refund_policy_snapshot"] == REFUND_POLICY_PRORATA_DAILY

    cloud_rows, cloud_meta = validate_paginated(
        api.list_cancellation_orders(ctx.fid_headers, asset_id=env["cloud_id"])
    )
    assert cloud_meta["total_count"] == 0
    assert cloud_rows == []


def test_the_fourth_hop_recomputes_the_estate_counters(api):
    """
    The estate is the reconciliation point: the same approval that disclosed two
    accounts and opened one order rewrites the counters that describe them.

    PRD: "The fourth hop recomputes the estate's `disclosed_asset_count` and `open_cancellation_count` and re-derives the administration phase, which is how a first approval carries an estate out of `INTAKE` and into `AUTHORIZED`."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I7")
    ctx = env["ctx"]
    before = fixtures.read_estate(api, ctx)
    assert before["disclosed_asset_count"] == 0
    assert before["open_cancellation_count"] == 0

    _approve(api, env)

    after = fixtures.read_estate(api, ctx)
    assert after["disclosed_asset_count"] == 2
    assert after["open_cancellation_count"] == 1
    assert after["inventory_total_count"] == 2


def test_the_re_derived_phase_lands_on_disclosure_not_authorized(api):
    """
    Two accounts are disclosed and none is disposed of, so the ordered phase
    clauses take the estate one step past the merely authorized posture.

    PRD: "`AUTHORIZED → DISCLOSURE` follows the first disclosure, once `disclosed_asset_count` is at least 1 and `assets_disposed_count` is still below `inventory_total_count`."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I8")
    ctx = env["ctx"]
    _approve(api, env)

    estate = fixtures.read_estate(api, ctx)
    assert estate["administration_phase"] == PHASE_DISCLOSURE
    assert estate["disclosed_asset_count"] == 2
    assert estate["assets_disposed_count"] == 0
    assert estate["inventory_total_count"] == 2


def test_the_cascade_stops_short_of_cancelling_the_paid_term(api):
    """
    Opening a cancellation order is not cancelling anything: the term the
    decedent paid for is still active after the whole four-hop cascade has run.

    PRD: "Its `state` is one of `ACTIVE`, `CANCELLED` or `LAPSED`, the latter two terminal; `CANCELLED` is reached only through a confirmed cancellation and `LAPSED` only through the expiry sweep of §3.6."

    Design: Difficulty/transitive_cascade/approval_cascades_grant_to_disclosure_to_cancellation_order_to_estate_counters
    """
    env = _stream_estate_awaiting_a_decision(api, "PR-2737-I9")
    ctx = env["ctx"]
    _approve(api, env)

    term = fixtures.read_term(api, ctx, env["term_id"])
    assert term["state"] == TERM_ACTIVE
    assert term["auto_renew"] is True
    assert term["cancelled_effective_date"] is None

    asset = fixtures.read_asset(api, ctx, env["subscription_id"])
    assert asset["subscription_billing_state"] == BILLING_ACTIVE
    estate = fixtures.read_estate(api, ctx)
    assert estate["cancelled_subscription_count"] == 0


def _two_fiduciary_estate_with_a_live_grant(api, case_number):
    """
    One estate whose two fiduciaries each hold ISSUED letters, with two accounts
    disclosed by a single approved catalogue request and the grant it produced.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    platform = fixtures.register_platform(api)
    ctx = fixtures.authorized_estate(api, case_number)
    second = fixtures.add_second_fiduciary(api, ctx, f"{case_number}-CO")
    first_asset = fixtures.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-a",
        quoted_value_cents=100000,
    )
    second_asset = fixtures.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-b",
        quoted_value_cents=80000,
    )
    request = fixtures.approved_request(api, ctx, platform["id"], platform["form_code"])
    grant = fixtures.grant_for_request(api, ctx, request["id"])
    return {
        "ctx": ctx,
        "platform": platform,
        "second_fiduciary_id": second["id"],
        "second_letters_id": second["letters_document_id"],
        "first_asset_id": first_asset["id"],
        "second_asset_id": second_asset["id"],
        "grant_id": grant["id"],
    }


def _revoke_letters(api, document_id, reason):
    return api.transition_document(
        document_id,
        f.document_transition_payload(DOC_ACTION_REVOKE, revocation_reason=reason),
        COURT_REGISTRAR_HEADERS,
    )


def test_revoking_one_set_of_letters_reaches_only_that_fiduciary(api):
    """
    The first hop is unconditional and narrow: it disqualifies the fiduciary the
    revoked document named and leaves the co-fiduciary's standing alone.

    PRD: "When a `CourtRegistrar` revokes a `LETTERS_OF_AUTHORITY` document, the first hop sets the named fiduciary's `letters_status` to `REVOKED`."

    Design: Difficulty/transitive_cascade/letters_revocation_cascade_only_fires_when_the_last_issued_letters_are_gone
    """
    env = _two_fiduciary_estate_with_a_live_grant(api, "PR-2737-J")
    ctx = env["ctx"]

    revoked = validate_success(
        _revoke_letters(api, ctx.letters_id, "first executor resigned"), 200
    )
    assert revoked["verification_status"] == DOC_REVOKED

    assert fixtures.read_fiduciary(api, ctx, ctx.fiduciary_id)["letters_status"] == (
        LETTERS_REVOKED
    )
    assert fixtures.read_fiduciary(api, ctx, env["second_fiduciary_id"])["letters_status"] == (
        LETTERS_ISSUED
    )


def test_the_cascade_stops_after_the_first_hop_while_a_co_fiduciary_stands(api):
    """
    Because someone still holds issued letters, the grant, the disclosures and
    the estate's derived counters are all left exactly as they were.

    PRD: "If a co-fiduciary still holds `ISSUED` letters, the cascade stops after the first hop: the revoked fiduciary can no longer act, but the estate's grants and disclosures stand untouched."

    Design: Difficulty/transitive_cascade/letters_revocation_cascade_only_fires_when_the_last_issued_letters_are_gone
    """
    env = _two_fiduciary_estate_with_a_live_grant(api, "PR-2737-J2")
    ctx = env["ctx"]
    get_success_data(_revoke_letters(api, ctx.letters_id, "first executor resigned"))

    grant = fixtures.read_grant(api, ctx, env["grant_id"])
    assert grant["status"] == GRANT_ACTIVE
    assert grant["revocation_reason"] is None

    for asset_id in (env["first_asset_id"], env["second_asset_id"]):
        assert fixtures.read_asset(api, ctx, asset_id)["access_status"] == (
            ACCESS_CATALOG_DISCLOSED
        )

    estate = fixtures.read_estate(api, ctx)
    assert estate["disclosed_asset_count"] == 2
    assert estate["administration_phase"] == PHASE_DISCLOSURE


def test_losing_the_last_letters_revokes_every_active_grant(api):
    """
    The identical transition applied to the last issued letters opens the second
    hop, which ends the estate's authority and records why.

    PRD: "When it does fire, every `ACTIVE` `AuthorityGrant` of the estate — across all providers — is walked in ascending `created_at` order and moved to `REVOKED` with `revocation_reason` set to `LETTERS_REVOKED`."

    Design: Difficulty/transitive_cascade/letters_revocation_cascade_only_fires_when_the_last_issued_letters_are_gone
    """
    env = _two_fiduciary_estate_with_a_live_grant(api, "PR-2737-J3")
    ctx = env["ctx"]
    get_success_data(_revoke_letters(api, ctx.letters_id, "first executor resigned"))
    get_success_data(
        _revoke_letters(api, env["second_letters_id"], "second appointment vacated")
    )

    assert fixtures.read_fiduciary(api, ctx, env["second_fiduciary_id"])["letters_status"] == (
        LETTERS_REVOKED
    )
    grant = fixtures.read_grant(api, ctx, env["grant_id"])
    assert grant["status"] == GRANT_REVOKED
    assert grant["revocation_reason"] == REVOCATION_LETTERS_REVOKED


def test_the_third_hop_pulls_every_disclosed_account_back(api):
    """
    With no authority left, both accounts lose their disclosure and the clamp
    note that explained where content stopped is reset.

    PRD: "The third hop then walks every account of the estate whose `access_status` is `CATALOG_DISCLOSED` or `CONTENT_DISCLOSED`, in ascending `created_at` order, dropping each to `ACCESS_REVOKED` and resetting its `content_clamp_reason` to `NONE`, since with no authority at all there is no longer any particular reason content was withheld."

    Design: Difficulty/transitive_cascade/letters_revocation_cascade_only_fires_when_the_last_issued_letters_are_gone
    """
    env = _two_fiduciary_estate_with_a_live_grant(api, "PR-2737-J4")
    ctx = env["ctx"]
    get_success_data(_revoke_letters(api, ctx.letters_id, "first executor resigned"))
    get_success_data(
        _revoke_letters(api, env["second_letters_id"], "second appointment vacated")
    )

    for asset_id in (env["first_asset_id"], env["second_asset_id"]):
        asset = fixtures.read_asset(api, ctx, asset_id)
        assert asset["access_status"] == ACCESS_REVOKED
        assert asset["content_clamp_reason"] == CLAMP_NONE


def test_the_fourth_hop_walks_the_estate_all_the_way_back_to_intake(api):
    """
    The last hop recomputes the disclosure counter, and with nothing disclosed
    and nobody holding letters the derived phase returns to where it started.

    PRD: "The fourth hop recomputes `disclosed_asset_count` and re-derives the phase, which with no disclosed accounts and no live grants returns the estate to `INTAKE`."

    Design: Difficulty/transitive_cascade/letters_revocation_cascade_only_fires_when_the_last_issued_letters_are_gone
    """
    env = _two_fiduciary_estate_with_a_live_grant(api, "PR-2737-J5")
    ctx = env["ctx"]
    get_success_data(_revoke_letters(api, ctx.letters_id, "first executor resigned"))
    get_success_data(
        _revoke_letters(api, env["second_letters_id"], "second appointment vacated")
    )

    estate = fixtures.read_estate(api, ctx)
    assert estate["disclosed_asset_count"] == 0
    assert estate["administration_phase"] == PHASE_INTAKE
    assert estate["inventory_total_count"] == 2


def test_no_further_package_can_be_submitted_once_the_letters_are_gone(api):
    """
    The collapse is not only retrospective: a package drafted while the letters
    still stood cannot be submitted after they are revoked.

    PRD: "The cited letters must be `VERIFIED` *and* the fiduciary they name must have `letters_status` equal to `ISSUED`, or the submission is rejected with `ERR_LETTERS_NOT_ISSUED` — revoking letters immediately disqualifies that fiduciary from acting."

    Design: Difficulty/transitive_cascade/letters_revocation_cascade_only_fires_when_the_last_issued_letters_are_gone
    """
    env = _two_fiduciary_estate_with_a_live_grant(api, "PR-2737-J6")
    ctx = env["ctx"]
    later = fixtures.draft_request(
        api, ctx, env["platform"]["id"], env["platform"]["form_code"]
    )
    get_success_data(_revoke_letters(api, ctx.letters_id, "first executor resigned"))
    get_success_data(
        _revoke_letters(api, env["second_letters_id"], "second appointment vacated")
    )

    refused = api.transition_platform_request(
        later["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
    )
    validate_error(refused, ERR_LETTERS_NOT_ISSUED)


def _subscription_with_a_pending_order(api, case_number):
    """
    One subscription account with an active auto-renewing term, disclosed by an
    approved catalogue request, whose cancellation order is still PENDING.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    platform = fixtures.register_subscription_platform(api)
    ctx = fixtures.authorized_estate(api, case_number)
    asset = fixtures.add_subscription_asset(
        api, ctx, platform["id"], account_handle="stream-premium"
    )
    term = fixtures.add_subscription_term(api, ctx, asset["id"])
    fixtures.approved_request(api, ctx, platform["id"], platform["form_code"])
    order = fixtures.cancellation_order_for_asset(api, ctx, asset["id"])
    return {
        "ctx": ctx,
        "platform": platform,
        "asset_id": asset["id"],
        "term_id": term["id"],
        "order_id": order["id"],
        "desk": make_platform_compliance_headers(platform["id"]),
    }


def _order_after_a_failed_attempt(api, case_number):
    env = _subscription_with_a_pending_order(api, case_number)
    get_success_data(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date=_EFFECTIVE_DATE),
            env["ctx"].fid_headers,
        )
    )
    env["failed"] = get_success_data(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(
                ORDER_ACTION_FAIL, reason="provider portal rejected the form"
            ),
            env["desk"],
        )
    )
    return env


def test_a_failed_cancellation_propagates_to_nothing(api):
    """
    Failing the order records the provider's excuse and stops there: the paid
    term keeps running, its renewal is still armed and the account is still
    billing.

    PRD: "Failing advances `REQUESTED → FAILED` and stores the provider's `failure_reason`, and it changes nothing else — the term stays `ACTIVE` and its `auto_renew` is left exactly as it was, because a failed cancellation attempt has not stopped anything."

    Design: Difficulty/transitive_cascade/cancellation_confirm_cascades_to_term_then_asset_then_estate_while_fail_cascades_nowhere
    """
    env = _order_after_a_failed_attempt(api, "PR-2737-K")
    ctx = env["ctx"]

    assert env["failed"]["status"] == ORDER_FAILED
    assert env["failed"]["failure_reason"] is not None

    term = fixtures.read_term(api, ctx, env["term_id"])
    assert term["state"] == TERM_ACTIVE
    assert term["auto_renew"] is True
    assert term["cancelled_effective_date"] is None

    asset = fixtures.read_asset(api, ctx, env["asset_id"])
    assert asset["subscription_billing_state"] == BILLING_ACTIVE
    assert fixtures.read_estate(api, ctx)["cancelled_subscription_count"] == 0


def test_a_failed_order_can_be_requested_again_with_a_new_date(api):
    """
    FAILED is not terminal: the fiduciary asks again, and the retry replaces the
    effective date and clears the provider's excuse.

    PRD: "A `Fiduciary` may request again from `FAILED`, which returns the order to `REQUESTED`, overwrites `effective_date` with the new one, clears `failure_reason` and re-stamps `requested_at`; the disclosure and date-of-death guards apply to the retry just as they did to the first attempt."

    Design: Difficulty/transitive_cascade/cancellation_confirm_cascades_to_term_then_asset_then_estate_while_fail_cascades_nowhere
    """
    env = _order_after_a_failed_attempt(api, "PR-2737-K2")
    ctx = env["ctx"]

    retried = validate_success(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date="2026-04-01"),
            ctx.fid_headers,
        ),
        200,
    )
    assert retried["status"] == ORDER_REQUESTED
    assert retried["failure_reason"] is None
    assert retried["effective_date"] == "2026-04-01"
    assert retried["requested_at"] is not None


def test_confirming_cascades_through_the_term_and_the_account(api):
    """
    The confirmation of the very same order rewrites two records the failure had
    left alone: the term is cancelled with its renewal forced off and the date it
    was asked to stop on, and the account stops billing.

    PRD: "Confirming advances `REQUESTED → CONFIRMED`, stores the provider's `platform_reference` and the `auto_renew_stopped` flag it reports, stamps `confirmed_at`, and cascades three hops: the account's `SubscriptionTerm` moves to `CANCELLED` with its own `auto_renew` forced to false and its `cancelled_effective_date` copied from the order's `effective_date`; the account's `subscription_billing_state` moves to `CANCELLED`; and the estate's `open_cancellation_count` and `cancelled_subscription_count` are recomputed."

    Design: Difficulty/transitive_cascade/cancellation_confirm_cascades_to_term_then_asset_then_estate_while_fail_cascades_nowhere
    """
    env = _order_after_a_failed_attempt(api, "PR-2737-K3")
    ctx = env["ctx"]
    get_success_data(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date=_EFFECTIVE_DATE),
            ctx.fid_headers,
        )
    )

    confirmed = validate_success(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(
                ORDER_ACTION_CONFIRM,
                platform_reference="SO-CANCEL-77",
                auto_renew_stopped=True,
            ),
            env["desk"],
        ),
        200,
    )
    assert confirmed["status"] == ORDER_CONFIRMED
    assert confirmed["platform_reference"] == "SO-CANCEL-77"
    assert confirmed["auto_renew_stopped"] is True
    assert _instant(confirmed["confirmed_at"]) == _instant(CLOCK_EPOCH)

    term = fixtures.read_term(api, ctx, env["term_id"])
    assert term["state"] == TERM_CANCELLED
    assert term["auto_renew"] is False
    assert term["cancelled_effective_date"] == _EFFECTIVE_DATE

    asset = fixtures.read_asset(api, ctx, env["asset_id"])
    assert asset["subscription_billing_state"] == BILLING_CANCELLED


def test_confirming_recomputes_both_subscription_counters_on_the_estate(api):
    """
    The last hop reaches the estate: the order no longer counts as open and the
    cancelled term is counted instead.

    PRD: "`cancelled_subscription_count` is the number of subscription terms across the estate's assets whose `state` is `CANCELLED`."

    Design: Difficulty/transitive_cascade/cancellation_confirm_cascades_to_term_then_asset_then_estate_while_fail_cascades_nowhere
    """
    env = _order_after_a_failed_attempt(api, "PR-2737-K4")
    ctx = env["ctx"]
    get_success_data(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date=_EFFECTIVE_DATE),
            ctx.fid_headers,
        )
    )
    get_success_data(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(
                ORDER_ACTION_CONFIRM,
                platform_reference="SO-CANCEL-77",
                auto_renew_stopped=True,
            ),
            env["desk"],
        )
    )

    estate = fixtures.read_estate(api, ctx)
    assert estate["cancelled_subscription_count"] == 1
    assert estate["open_cancellation_count"] == 0


def test_a_confirmed_order_cannot_be_confirmed_twice(api):
    """
    CONFIRMED defines no further action, so a repeat confirmation is refused and
    the cascade does not run a second time.

    PRD: "Acting on an order whose current `status` does not define the action is rejected with `ERR_INVALID_ORDER_STATE`."

    Design: Difficulty/transitive_cascade/cancellation_confirm_cascades_to_term_then_asset_then_estate_while_fail_cascades_nowhere
    """
    env = _order_after_a_failed_attempt(api, "PR-2737-K5")
    ctx = env["ctx"]
    get_success_data(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(ORDER_ACTION_REQUEST, effective_date=_EFFECTIVE_DATE),
            ctx.fid_headers,
        )
    )
    get_success_data(
        api.transition_cancellation_order(
            env["order_id"],
            f.order_transition_payload(
                ORDER_ACTION_CONFIRM,
                platform_reference="SO-CANCEL-77",
                auto_renew_stopped=True,
            ),
            env["desk"],
        )
    )

    refused = api.transition_cancellation_order(
        env["order_id"],
        f.order_transition_payload(
            ORDER_ACTION_CONFIRM, platform_reference="SO-CANCEL-78", auto_renew_stopped=True
        ),
        env["desk"],
    )
    validate_error(refused, ERR_INVALID_ORDER_STATE)

    order = fixtures.read_order(api, ctx, env["order_id"])
    assert order["status"] == ORDER_CONFIRMED
    assert order["platform_reference"] == "SO-CANCEL-77"
