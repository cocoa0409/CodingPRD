"""
Cross-cutting corners of the Digital Estate Fiduciary Access API.

Three layers cut across every entity here. The estate's concurrency token has to
match exactly, and a refused write must leave it alone. The estate's derived
counters are recomputed from the child rows after every mutation, so their
identity has to hold at every observation point of a full disposition cycle. And
the consistency model is immediate: a cascade is already finished inside the
response of the write that caused it, so re-reading changes nothing.

Every test builds its own estate from scratch against an empty database whose
logical clock sits at the fresh-server epoch.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_inventory_counter_identity,
    factories as f,
    fixtures as fx,
    make_platform_compliance_headers,
)
from test_helpers.api_errors import ERR_STALE_ESTATE_VERSION
from test_helpers.constants import (
    ACCESS_CATALOG_DISCLOSED,
    ACCESS_UNVERIFIED,
    BASIS_STATUTORY_DEFAULT,
    BILLING_INTERVAL_ANNUAL,
    CATEGORY_CLOUD_STORAGE,
    CATEGORY_LOYALTY_PROGRAM,
    CATEGORY_SOCIAL_PROFILE,
    CLOCK_EPOCH,
    DECISION_APPROVED,
    DISPOSITION_PENDING,
    ELECTION_MEMORIALIZE,
    ELECTION_REVERSED,
    EL_ACTION_EXECUTE,
    EL_ACTION_REVERSE,
    GRANT_ACTIVE,
    ORDER_PENDING,
    PHASE_AUTHORIZED,
    PHASE_DISCLOSURE,
    PHASE_WIND_DOWN,
    REFUND_POLICY_UNUSED_PERIOD,
    REQUEST_APPROVED,
    SCOPE_CATALOG_ONLY,
    TERM_ACTIVE,
)


def _valued_estate(api, case_number):
    """A disclosed 200000-cent cloud account and a single whole-estate heir."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, case_number)
    vault = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1", quoted_value_cents=200000,
    )
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    fx.add_beneficiary(api, ctx, beneficiary_name="Kai Ives", share_bp=10000, relationship="child")
    return platform, ctx, vault


def test_a_token_captured_before_an_unrelated_write_is_refused_with_412(api):
    """
    Adding one more account advances the estate's own version by exactly one, and
    the valuation token captured before it is now stale: the create is refused
    with ERR_STALE_ESTATE_VERSION and the refused call leaves the version exactly
    where it stood. Refreshing the token succeeds; because the successful run
    mirrors its roll-up back onto the estate, that same refreshed token is stale
    on the next attempt, and only one run was ever persisted.

    PRD §2.4: `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that record.

    PRD §2.8: A `POST /estates/{estate_id}/valuation-runs` request must carry `expected_estate_version` as a required, non-optional field holding the client's last observed `version` of that estate.

    PRD §2.8: If the supplied value does not equal the estate's current `version`, the create is rejected with `ERR_STALE_ESTATE_VERSION` (HTTP 412).

    Design: Corner/cross-cutting complexity layers/the_estate_occ_token_must_match_exactly_and_a_412_bumps_nothing
    """
    platform, ctx, _vault = _valued_estate(api, "PR-2737-C38A")

    version_1 = fx.estate_version(api, ctx)
    fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_SOCIAL_PROFILE, account_handle="social-1", quoted_value_cents=0,
    )
    version_2 = fx.estate_version(api, ctx)
    assert version_2 == version_1 + 1

    validate_error(
        api.create_valuation_run(
            ctx.estate_id, f.valuation_run_payload(version_1), ctx.fid_headers
        ),
        ERR_STALE_ESTATE_VERSION,
    )
    version_3 = fx.estate_version(api, ctx)
    assert version_3 == version_2

    run1 = validate_success(
        api.create_valuation_run(
            ctx.estate_id, f.valuation_run_payload(version_3), ctx.fid_headers
        ),
        201,
    )
    assert run1["gross_value_cents"] == 200000
    assert run1["included_asset_count"] == 1

    version_4 = fx.estate_version(api, ctx)
    assert version_4 > version_3

    validate_error(
        api.create_valuation_run(
            ctx.estate_id, f.valuation_run_payload(version_3), ctx.fid_headers
        ),
        ERR_STALE_ESTATE_VERSION,
    )
    assert fx.estate_version(api, ctx) == version_4

    rows, meta = validate_paginated(
        api.list_valuation_runs(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [run1["id"]]


def test_a_token_ahead_of_the_estate_is_just_as_stale(api):
    """
    The concurrency check is an equality test rather than a floor, so a token five
    versions ahead of the estate is refused with the same
    ERR_STALE_ESTATE_VERSION as one that lags behind, and the estate is left
    untouched.

    PRD §2.8: If the supplied value does not equal the estate's current `version`, the create is rejected with `ERR_STALE_ESTATE_VERSION` (HTTP 412).

    Design: Corner/cross-cutting complexity layers/the_estate_occ_token_must_match_exactly_and_a_412_bumps_nothing
    """
    _platform, ctx, _vault = _valued_estate(api, "PR-2737-C38B")

    current = fx.estate_version(api, ctx)
    validate_error(
        api.create_valuation_run(
            ctx.estate_id, f.valuation_run_payload(current + 5), ctx.fid_headers
        ),
        ERR_STALE_ESTATE_VERSION,
    )
    assert fx.estate_version(api, ctx) == current

    rows, meta = validate_paginated(
        api.list_valuation_runs(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_estate_counters_reconcile_through_a_whole_disposition_cycle(api):
    """
    Seven observation points across one full cycle — two inventory additions, a
    first disclosure, an election, two memorialization executions, a third
    account added while the estate already sits in wind-down, and a reversal — and
    at every one of them the inventory total equals the pending-or-elected count
    plus the disposed count. The phase tracks along non-monotonically: an elected
    account is still counted as pending, the third account walks the estate back
    from WIND_DOWN to DISCLOSURE without touching the disclosed count, and the
    reversal returns its account to PENDING with its disposal timestamp cleared.

    PRD §2.10: `assets_pending_disposition_count` is the number whose `disposition_status` is `PENDING` or `ELECTED`.

    PRD §2.10: Because every asset's disposition posture is either pending-or-elected or disposed, `inventory_total_count` always equals `assets_pending_disposition_count` plus `assets_disposed_count`.

    PRD §3.2: Otherwise, if `disclosed_asset_count` is 0, the phase is `AUTHORIZED`.

    PRD §3.2: Otherwise, if `inventory_total_count` is 0, or `assets_disposed_count` is strictly less than `inventory_total_count`, the phase is `DISCLOSURE`.

    PRD §3.2: Otherwise the phase is `WIND_DOWN`.

    PRD §3.9: Either way the account's `disposed_at` is cleared and its `disposition_status` returns to `PENDING`, and the estate's counters and phase are recomputed.

    Design: Corner/cross-cutting complexity layers/the_five_estate_counters_reconcile_after_create_disclose_dispose_and_reverse
    """
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-C39")
    desk = make_platform_compliance_headers(platform["id"])

    a1 = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-1", quoted_value_cents=120000,
    )
    a2 = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_CLOUD_STORAGE, account_handle="vault-2", quoted_value_cents=80000,
    )

    point_1 = fx.read_estate(api, ctx)
    assert_inventory_counter_identity(point_1)
    assert point_1["inventory_total_count"] == 2
    assert point_1["disclosed_asset_count"] == 0
    assert point_1["assets_pending_disposition_count"] == 2
    assert point_1["assets_disposed_count"] == 0
    assert point_1["administration_phase"] == PHASE_AUTHORIZED

    fx.approved_request(api, ctx, platform["id"], platform["form_code"])

    point_2 = fx.read_estate(api, ctx)
    assert_inventory_counter_identity(point_2)
    assert point_2["inventory_total_count"] == 2
    assert point_2["disclosed_asset_count"] == 2
    assert point_2["assets_pending_disposition_count"] == 2
    assert point_2["assets_disposed_count"] == 0
    assert point_2["administration_phase"] == PHASE_DISCLOSURE

    el1 = fx.submitted_election(
        api, ctx, a1["id"], election=ELECTION_MEMORIALIZE, election_note="freeze vault-1"
    )

    point_3 = fx.read_estate(api, ctx)
    assert_inventory_counter_identity(point_3)
    assert point_3["inventory_total_count"] == 2
    assert point_3["assets_pending_disposition_count"] == 2
    assert point_3["assets_disposed_count"] == 0
    assert point_3["administration_phase"] == PHASE_DISCLOSURE

    validate_success(
        api.transition_disposition_election(
            el1["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-MEM-1"
            ),
            desk,
        ),
        200,
    )

    point_4 = fx.read_estate(api, ctx)
    assert_inventory_counter_identity(point_4)
    assert point_4["inventory_total_count"] == 2
    assert point_4["assets_pending_disposition_count"] == 1
    assert point_4["assets_disposed_count"] == 1
    assert point_4["administration_phase"] == PHASE_DISCLOSURE

    fx.executed_election(
        api, ctx, platform["id"], a2["id"],
        election=ELECTION_MEMORIALIZE,
        platform_confirmation_reference="CV-MEM-2",
        election_note="freeze vault-2",
    )

    point_5 = fx.read_estate(api, ctx)
    assert_inventory_counter_identity(point_5)
    assert point_5["inventory_total_count"] == 2
    assert point_5["assets_pending_disposition_count"] == 0
    assert point_5["assets_disposed_count"] == 2
    assert point_5["administration_phase"] == PHASE_WIND_DOWN

    a3 = fx.add_asset(
        api, ctx, platform["id"],
        category=CATEGORY_LOYALTY_PROGRAM, account_handle="points-1",
        quoted_value_cents=5000, loyalty_points=2500,
    )
    assert a3["access_status"] == ACCESS_UNVERIFIED

    point_6 = fx.read_estate(api, ctx)
    assert_inventory_counter_identity(point_6)
    assert point_6["inventory_total_count"] == 3
    assert point_6["disclosed_asset_count"] == 2
    assert point_6["assets_pending_disposition_count"] == 1
    assert point_6["assets_disposed_count"] == 2
    assert point_6["administration_phase"] == PHASE_DISCLOSURE

    reversed_election = validate_success(
        api.transition_disposition_election(
            el1["id"],
            f.election_transition_payload(
                EL_ACTION_REVERSE, reversal_reason="family objected to memorialization"
            ),
            desk,
        ),
        200,
    )
    assert reversed_election["status"] == ELECTION_REVERSED

    point_7 = fx.read_estate(api, ctx)
    assert_inventory_counter_identity(point_7)
    assert point_7["inventory_total_count"] == 3
    assert point_7["disclosed_asset_count"] == 2
    assert point_7["assets_pending_disposition_count"] == 2
    assert point_7["assets_disposed_count"] == 1
    assert point_7["administration_phase"] == PHASE_DISCLOSURE

    a1_final = fx.read_asset(api, ctx, a1["id"])
    assert a1_final["disposition_status"] == DISPOSITION_PENDING
    assert a1_final["access_status"] == ACCESS_CATALOG_DISCLOSED
    assert a1_final["disposed_at"] is None


def _subscription_package_under_review(api, case_number):
    """A subscription account with an active term and its package under review."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_subscription_platform(
        api,
        name="StreamOne",
        form_code="S1-FORM",
        review_window_days=30,
        refund_policy=REFUND_POLICY_UNUSED_PERIOD,
        supports_online_tool=True,
        supports_memorialization=True,
        request_fee_cents=900,
    )
    ctx = fx.authorized_estate(api, case_number)
    asset = fx.add_subscription_asset(api, ctx, platform["id"], account_handle="s1")
    term = fx.add_subscription_term(
        api, ctx, asset["id"],
        term_start_date="2026-01-01", term_end_date="2026-12-31",
        billing_interval=BILLING_INTERVAL_ANNUAL, period_fee_cents=11999, auto_renew=True,
    )
    assert term["state"] == TERM_ACTIVE
    request = fx.draft_request(api, ctx, platform["id"], platform["form_code"])
    fx.submit_request(api, ctx, request["id"])
    fx.start_review(api, platform["id"], request["id"])
    return platform, ctx, asset, term, request


def test_the_approval_response_already_carries_the_whole_four_hop_cascade(api):
    """
    One approval writes four hops, and none of them lags. The transition's own
    response already carries the frozen statutory-default resolution and the
    review window it was submitted under. The very first read afterwards finds the
    grant open at CATALOG_ONLY from the clock instant, the subscription account
    disclosed and stamped, an auto-created cancellation order already holding the
    provider's refund policy as a snapshot, and the estate's disclosure and
    open-cancellation counters already recomputed.

    PRD §3.3: When the candidate set is empty there is no winner, and the statutory default applies: the base scope is `CATALOG_ONLY` and the basis is `STATUTORY_DEFAULT`.

    PRD §3.5: On submission the server sets `review_window_start` to the current logical-clock instant and `review_window_end` to that instant advanced by the provider's `review_window_days` days, and the window is **half-open**: the start instant is inside the window and the end instant is outside it.

    PRD §3.6: A grant records the `estate_id` and `platform_id` it covers and the `platform_request_id` that produced it, freezes the `granted_scope` and `basis` that the resolution of §3.3 produced at decision time along with the `clamp_reason` that resolution carried, opens its `status` at `ACTIVE`, sets `effective_from` to the current clock instant and `expires_at` to that instant advanced by 90 days, and leaves `revocation_reason` null.

    PRD §3.6: Whenever an account's `access_status` rises above `UNVERIFIED` for the first time, `disclosed_at` is stamped with the clock instant.

    PRD §3.6: For every account the second hop has just disclosed whose `category` is `SUBSCRIPTION` and which does not already have a cancellation order, the system creates a **`CancellationOrder`** in `PENDING` status and copies the provider's `refund_policy` into the order's `refund_policy_snapshot` at that moment.

    PRD §3.6: The fourth hop recomputes the estate's `disclosed_asset_count` and `open_cancellation_count` and re-derives the administration phase, which is how a first approval carries an estate out of `INTAKE` and into `AUTHORIZED`.

    Design: Corner/consistency model/every_cascade_is_already_visible_in_the_response_that_caused_it
    """
    platform, ctx, asset, _term, request = _subscription_package_under_review(
        api, "PR-2737-C40A"
    )

    decided = fx.decide_request(
        api, platform["id"], request["id"], decision_note="catalog released"
    )
    assert decided["status"] == REQUEST_APPROVED
    assert decided["decision"] == DECISION_APPROVED
    assert decided["resolved_scope"] == SCOPE_CATALOG_ONLY
    assert decided["resolved_basis"] == BASIS_STATUTORY_DEFAULT
    assert decided["review_window_end"].startswith("2026-08-31")

    grants, grant_meta = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, estate_id=ctx.estate_id, status=GRANT_ACTIVE)
    )
    assert grant_meta["total_count"] == 1
    assert grants[0]["granted_scope"] == SCOPE_CATALOG_ONLY
    assert grants[0]["effective_from"].startswith("2026-08-01")

    disclosed = fx.read_asset(api, ctx, asset["id"])
    assert disclosed["access_status"] == ACCESS_CATALOG_DISCLOSED
    assert disclosed["disclosed_at"].startswith("2026-08-01")

    orders, order_meta = validate_paginated(
        api.list_cancellation_orders(ctx.fid_headers, asset_id=asset["id"])
    )
    assert order_meta["total_count"] == 1
    assert orders[0]["status"] == ORDER_PENDING
    assert orders[0]["refund_policy_snapshot"] == REFUND_POLICY_UNUSED_PERIOD

    estate = fx.read_estate(api, ctx)
    assert estate["disclosed_asset_count"] == 1
    assert estate["open_cancellation_count"] == 1
    assert estate["administration_phase"] == PHASE_DISCLOSURE


def test_repeating_the_reads_after_the_cascade_moves_nothing(api):
    """
    Nothing about the cascade converges late. Reading the estate, the grant and the
    auto-created order a second time returns byte-identical counters, phase,
    scope and snapshot, and the estate's version has not budged, because a read is
    not a mutation and the counters were recomputed inside the write itself.

    PRD §2.4: `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that record.

    PRD §2.10: The derived counters are always recomputed from the child rows rather than incremented blindly.

    Design: Corner/consistency model/every_cascade_is_already_visible_in_the_response_that_caused_it
    """
    platform, ctx, asset, _term, request = _subscription_package_under_review(
        api, "PR-2737-C40B"
    )
    fx.decide_request(api, platform["id"], request["id"], decision_note="catalog released")

    first_estate = fx.read_estate(api, ctx)
    grant_rows, _ = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, estate_id=ctx.estate_id, status=GRANT_ACTIVE)
    )
    order_rows, _ = validate_paginated(
        api.list_cancellation_orders(ctx.fid_headers, asset_id=asset["id"])
    )

    second_estate = fx.read_estate(api, ctx)
    assert second_estate["disclosed_asset_count"] == first_estate["disclosed_asset_count"]
    assert second_estate["open_cancellation_count"] == first_estate["open_cancellation_count"]
    assert second_estate["administration_phase"] == first_estate["administration_phase"]
    assert second_estate["version"] == first_estate["version"]
    assert_inventory_counter_identity(second_estate)

    regrant = fx.read_grant(api, ctx, grant_rows[0]["id"])
    assert regrant["granted_scope"] == grant_rows[0]["granted_scope"]
    assert regrant["status"] == GRANT_ACTIVE
    assert regrant["version"] == grant_rows[0]["version"]

    reorder = fx.read_order(api, ctx, order_rows[0]["id"])
    assert reorder["status"] == ORDER_PENDING
    assert reorder["refund_policy_snapshot"] == REFUND_POLICY_UNUSED_PERIOD
    assert reorder["version"] == order_rows[0]["version"]
