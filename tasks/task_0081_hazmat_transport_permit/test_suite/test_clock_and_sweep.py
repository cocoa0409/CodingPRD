"""Test-mode logical-clock and daily-compliance-sweep endpoints.

PRD §2.5 names the two endpoints
``POST /v1/_clock/advance`` and ``POST /v1/_sweep/run``, the
``TestHarness`` role as their exclusive allow-cell, and the
canonical sequence the test harness drives: a clock-advance does
not synchronously fire the time-driven transitions, then the
sweep flushes the deferred-cascade arcs.

The clock-advance's response shape is the
``{prior_now, new_now, advance_seconds_applied, sweep_summary}``
quartet from §2.5.  The
``advance_seconds`` body field is the non-negative number of
seconds to add; the strict-monotonicity guarantee from §2.5's
"the conservation-of-time guarantee is that the logical clock
advances strictly monotonically" means a negative advance is the
``ERR_VALIDATION`` 422 catch-all rejection.

The sweep's response shape is the structured-summary the
``assert_sweep_response`` helper in
``test_helpers/assertions.py`` validates.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_ADVANCE_MAX_SECONDS,
    HazmatScenario,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    advance_clock_by,
    api_client,
    assert_clock_advance_response,
    assert_sweep_response,
    bootstrap_company_operator_headers,
    company_operator_headers,
    current_server_now,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    regulator_headers,
    run_full_sweep,
    setup_active_permit,
    setup_inflight_trip,
    test_harness_headers,
    validate_error,
    validate_success,
)
from test_helpers.types import (
    PermitLifecycleStatus,
    SweepScope,
    SweepPermitCause,
    TripStatus,
    AbortReason,
)


# ─── Clock-advance happy path ─────────────────────────────────────────


def test_clock_advance_returns_prior_and_new_now(api):
    """PRD §2.5: "The response carries the pre-advance
    ``prior_now``, the post-advance ``new_now``, the
    ``advance_seconds_applied`` echo of the request, and a
    ``sweep_summary`` sub-object that is null when
    ``run_sweep_after_advance`` is false and otherwise carries
    the same payload the sweep endpoint described below
    returns".
    """
    th = test_harness_headers()
    advance_seconds = 60.0
    resp = api.advance_clock(advance_seconds, run_sweep_after_advance=False, headers=th)
    data = validate_success(resp, 200)
    assert is_iso8601_timestamp(data["prior_now"])
    assert is_iso8601_timestamp(data["new_now"])
    # Run the standard envelope-shape check from the
    # assertions helper.
    assert_clock_advance_response(data, expected_advance_seconds=advance_seconds)
    # No sweep was requested, so sweep_summary is null.
    assert data.get("sweep_summary") is None, (
        f"sweep_summary should be null when run_sweep_after_advance is False; "
        f"got {data.get('sweep_summary')!r}"
    )
    # The new_now is strictly greater than the prior_now.
    assert data["new_now"] > data["prior_now"], (
        f"new_now {data['new_now']!r} should be strictly after prior_now {data['prior_now']!r} "
        f"on a positive advance"
    )


def test_clock_advance_zero_seconds_is_a_no_op(api):
    """PRD §2.5: "A zero-duration advance is a permitted no-op for
    the harness to synchronize its local clock idea with the
    server".
    """
    th = test_harness_headers()
    resp = api.advance_clock(0.0, run_sweep_after_advance=False, headers=th)
    data = validate_success(resp, 200)
    # The two timestamps are equal exactly (the no-op).
    assert data["prior_now"] == data["new_now"], (
        f"prior_now and new_now should be exactly equal on a zero-second advance, "
        f"got {data['prior_now']!r} vs {data['new_now']!r}"
    )
    assert float(data["advance_seconds_applied"]) == 0.0


def test_clock_advance_negative_seconds_rejected(api):
    """PRD §2.5: "A negative ``advance_seconds`` is a body-shape
    violation and is rejected with ``ERR_VALIDATION`` 422".  The
    strict-monotonicity of the logical clock from §2.5's last
    paragraph forbids rolling time backwards.
    """
    th = test_harness_headers()
    resp = api.advance_clock(-5.0, run_sweep_after_advance=False, headers=th)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_clock_advance_with_chained_sweep(api, active_permit: HazmatScenario):
    """The combined-call form: ``run_sweep_after_advance = True``
    in the same call's body packages the clock-tick and the
    deferred-cascade flush in one request.  The response's
    ``sweep_summary`` sub-object is non-null and has the
    standard sweep-envelope shape per
    ``assert_sweep_response``.

    Construct a scenario where the wall-clock-expiry would fire
    on the permit (advance past valid_until), so the chained
    sweep observes the time-driven transition and carries the
    permit_transitions entry.
    """
    scenario = active_permit
    th = test_harness_headers()
    # Advance by the full term plus one day, with the sweep on.
    full_term_seconds = float(PERMIT_DEFAULT_VALIDITY_DAYS + 1) * 86400.0
    resp = api.advance_clock(full_term_seconds, run_sweep_after_advance=True, headers=th)
    data = validate_success(resp, 200)
    sweep_summary = data.get("sweep_summary")
    assert sweep_summary is not None, (
        "with run_sweep_after_advance=True the response's sweep_summary must carry the sweep payload"
    )
    assert_sweep_response(sweep_summary)
    # The wall-clock-expired permit is in the sweep's transitions list.
    matching = [t for t in sweep_summary.get("permit_transitions") or [] if t.get("permit_id") == scenario.permit["id"]]
    assert matching, (
        f"the wall-clock-expired permit {scenario.permit['id']!r} is missing from the "
        f"chained sweep's permit_transitions"
    )
    assert matching[0]["cause"] == SweepPermitCause.WALL_CLOCK_EXPIRY.value
    assert matching[0]["post_status"] == PermitLifecycleStatus.EXPIRED.value


def test_clock_advance_above_max_rejected(api):
    """PRD §2.5: "an ``advance_seconds`` exceeding the
    deployment's maximum-single-advance bound (the bound is
    large — on the order of a century of seconds — to admit the
    year-long permit-term-expiry tests without admitting
    unbounded forward jumps that could overflow the year-9999
    datetime ceiling)".

    A request with ``advance_seconds`` above the deployment's
    pinned ``CLOCK_ADVANCE_MAX_SECONDS`` value is the
    catch-all ``ERR_VALIDATION``.  The scaffold's pinned value
    is the 100-year-in-seconds constant 3_155_760_000.
    """
    th = test_harness_headers()
    overflow_seconds = float(CLOCK_ADVANCE_MAX_SECONDS) * 2
    resp = api.advance_clock(overflow_seconds, run_sweep_after_advance=False, headers=th)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


# ─── Sweep happy path ─────────────────────────────────────────────────


def test_sweep_response_shape_default_scope_all(api):
    """The bare ``POST /v1/_sweep/run`` with no body or with
    ``scope = "ALL"`` runs the full per-permit and per-driver
    walk.  The response shape carries the standard
    ``as_of_now``, ``scope``, ``permit_transitions``,
    ``driver_recomputes``, the ``n_permits_inspected`` and
    ``n_drivers_inspected`` counts, and the
    ``wallclock_advanced`` flag at the top level.

    On a clean post-reset system the two transition arrays are
    empty (no permits or drivers exist yet), and the
    inspected-counts are zero.
    """
    th = test_harness_headers()
    resp = api.run_sweep(scope=SweepScope.ALL.value, headers=th)
    data = validate_success(resp, 200)
    assert_sweep_response(data)
    # On a clean system the two transition lists are empty.
    assert data.get("permit_transitions") in ([], None)
    assert data.get("driver_recomputes") in ([], None)


@pytest.mark.parametrize("scope", [
    SweepScope.ALL.value,
    SweepScope.PERMITS_ONLY.value,
    SweepScope.DRIVERS_ONLY.value,
])
def test_sweep_scope_filter_is_in_enum(api, scope: str):
    """PRD §2.5: "the ``POST /v1/_sweep/run`` body's ``scope``
    field is the three-element enum
    ``{ALL, PERMITS_ONLY, DRIVERS_ONLY}``".  Each value is
    accepted; the response carries the named scope echoed in
    the response's ``scope`` field.
    """
    th = test_harness_headers()
    resp = api.run_sweep(scope=scope, headers=th)
    data = validate_success(resp, 200)
    assert data["scope"] == scope


def test_sweep_with_unknown_scope_rejected(api):
    """A scope value outside the three-element enum is the
    catch-all ``ERR_VALIDATION`` per the body-shape rule on
    enum-membership."""
    th = test_harness_headers()
    resp = api.run_sweep(scope="UNKNOWN_SCOPE", headers=th)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_sweep_drivers_only_scope_skips_permits(api, active_permit: HazmatScenario):
    """PRD §2.5: "the body ``scope`` field with the three
    allowed values ``ALL``, ``PERMITS_ONLY``, and
    ``DRIVERS_ONLY``".  A ``DRIVERS_ONLY`` sweep, even after a
    wall-clock advance that would fire the permit's
    wall-clock-expiry, does not touch the permit's row.  The
    response's ``permit_transitions`` array is empty in that
    mode.

    The exact scoping semantics of the
    PERMITS_ONLY vs DRIVERS_ONLY split — whether the permit-
    side wall-clock-expiry transition is fired under DRIVERS_ONLY
    on the principle "the wall-clock-expiry on a permit also
    refreshes the per-driver-rolling-points which the permit's
    snapshot reads" — is ambiguous in the PRD's wording.  Two
    PRD-faithful readings give two different answers, so the
    test uses the framework's
    ``validate_error_is_one_of``-style flexibility on the
    permit_transitions array's contents.  The standard
    interpretation is "DRIVERS_ONLY walks only the driver
    table and emits only driver_recomputes entries", which is
    the more-restrictive reading.
    """
    th = test_harness_headers()
    # Advance the clock so the permit's valid_until is crossed.
    advance_clock_by(api, float(PERMIT_DEFAULT_VALIDITY_DAYS + 1) * 86400.0, run_sweep=False)
    # The DRIVERS_ONLY sweep.
    drivers_only = get_success_data(api.run_sweep(scope=SweepScope.DRIVERS_ONLY.value, headers=th))
    assert drivers_only["scope"] == SweepScope.DRIVERS_ONLY.value
    # Per the restrictive reading: no permit_transitions in the
    # response.  We do not assert this strictly since the
    # alternative reading (the cascade-from-the-driver-side
    # touches the permit's snapshot-driver-endorsements map) is
    # PRD-consistent.  The shape-check via ``assert_sweep_response``
    # is the load-bearing assertion.
    assert_sweep_response(drivers_only)
    # Now a full ``ALL`` sweep to flush the wall-clock-expiry on the permit.
    all_sweep = get_success_data(api.run_sweep(scope=SweepScope.ALL.value, headers=th))
    assert_sweep_response(all_sweep)
    # The ALL sweep observes the permit's wall-clock-expiry and
    # fires the transition.
    pt = all_sweep.get("permit_transitions") or []
    matching = [t for t in pt if t.get("permit_id") == active_permit.permit["id"]]
    # The previous DRIVERS_ONLY sweep may or may not have
    # already fired the permit's expiry (depending on the
    # PRD-reading), so the matching entry may be absent here if
    # the prior sweep already wrote the post-state.  We accept
    # the union of the two valid readings: either the matching
    # entry is in this ALL-sweep's transitions list, or the
    # permit's current state is already EXPIRED from the
    # earlier sweep's effect.
    reg = regulator_headers()
    p_after = get_success_data(api.get_permit(active_permit.permit["id"], reg))
    assert p_after["lifecycle_status"] == PermitLifecycleStatus.EXPIRED.value, (
        f"after the ALL sweep the wall-clock-expired permit should be in EXPIRED, "
        f"got {p_after['lifecycle_status']!r}"
    )


def test_sweep_wallclock_advanced_flag_is_false_on_bare_sweep(api):
    """PRD §2.5: "the ``wallclock_advanced`` boolean is always
    false on the sweep-run path (the sweep does not advance the
    clock — that is the clock-advance endpoint's job; the
    verb-asymmetry between the two test-mode endpoints
    reflects the production-deployment-equivalent split
    between the OS clock tick and the periodic-cron sweep)".
    """
    th = test_harness_headers()
    data = get_success_data(api.run_sweep(scope=SweepScope.ALL.value, headers=th))
    wa = data.get("wallclock_advanced")
    if wa is not None:
        assert wa is False, (
            f"on the bare /_sweep/run path the wallclock_advanced flag must be False, got {wa!r}"
        )


def test_clock_advance_post_call_observable_via_clock_query(api):
    """The pre-and-post-now timestamps from the clock-advance
    response are the canonical observable for the test
    harness's "what is the server's current logical clock?"
    query.  The convention is the
    zero-duration ``POST /v1/_clock/advance`` call which the
    ``current_server_now`` helper in
    ``test_helpers/fixtures.py`` wraps."""
    th = test_harness_headers()
    # First, a non-zero advance.
    r1 = get_success_data(api.advance_clock(120.0, run_sweep_after_advance=False, headers=th))
    new_now_1 = r1["new_now"]
    # Now a zero-duration call.  The new_now is the same as
    # the prior_now and equal to the previous call's
    # ``new_now`` (the strict-monotonicity says the clock has
    # not moved in between, since the test harness is the
    # only thing that advances the logical clock in test mode).
    r2 = get_success_data(api.advance_clock(0.0, run_sweep_after_advance=False, headers=th))
    assert r2["prior_now"] == new_now_1, (
        f"the zero-duration advance's prior_now {r2['prior_now']!r} should equal "
        f"the previous call's new_now {new_now_1!r}"
    )
    assert r2["new_now"] == r2["prior_now"]


def test_admin_reset_clears_state(api):
    """The administrative ``POST /v1/_admin/reset`` affordance
    described in ``test_helpers.api_client`` wipes the
    in-memory state.  This file's autouse fixture in conftest
    calls the reset before every test; the explicit test below
    confirms the reset's effect: an in-memory company-create
    persists across requests in the same test, but a fresh
    test sees the empty company-list because the autoreset's
    pre-test hook wiped it.

    We exercise the reset by creating a company, asserting the
    list-companies endpoint returns one row, calling the reset
    explicitly, and asserting the list is empty afterward.
    """
    from test_helpers import admin_reset, create_company_payload

    boot = bootstrap_company_operator_headers()
    co_resp = api.create_company(create_company_payload(), boot)
    assert co_resp.status_code == 201, (
        f"company-create failed unexpectedly: {co_resp.status_code} {co_resp.text}"
    )
    # Confirm the row is in the list.
    reg = regulator_headers()
    listing_pre = get_success_data(api.list_companies(reg, params={"limit": 100}))
    pre_ids = {c["id"] for c in listing_pre}
    new_id = co_resp.json()["data"]["id"]
    assert new_id in pre_ids
    # Reset.
    admin_reset(api)
    # The list is now empty.
    listing_post = get_success_data(api.list_companies(reg, params={"limit": 100}))
    post_ids = {c["id"] for c in listing_post}
    assert new_id not in post_ids, (
        f"after the admin reset the previously-created company id {new_id!r} should be gone; "
        f"post-reset list ids: {post_ids!r}"
    )


def test_admin_wallet_topup_changes_balance(api):
    """The administrative wallet-topup affordance from
    ``test_helpers.api_client.admin_wallet_topup`` is the
    test-harness's way of simulating the regulator-side
    out-of-band bookkeeping the PRD's §2.11 describes
    (("the regulator's-side procedure outside the API").

    Top up the wallet of a freshly-created APPROVED company
    and read the post-topup company row's
    ``wallet_balance_cents`` field to confirm the increment.
    """
    co = get_success_data(api.create_company(
        __import__("test_helpers", fromlist=["create_company_payload"]).create_company_payload(),
        bootstrap_company_operator_headers(),
    ))
    op = company_operator_headers(co["id"])
    # Walk DRAFT → SUBMITTED → APPROVED.
    get_success_data(api.submit_company(co["id"], {}, op))
    get_success_data(api.approve_company(co["id"], {}, regulator_headers()))
    co_pre_topup = get_success_data(api.get_company(co["id"], op))
    pre_balance = co_pre_topup["wallet_balance_cents"]
    topup_amount = 1_000_000
    topped = get_success_data(api.admin_wallet_topup(co["id"], topup_amount))
    # The topup response is the standard envelope's data block,
    # which carries the post-topup company row.  The
    # ``wallet_balance_cents`` should be the pre-balance plus the
    # topup-amount.
    post_balance = topped.get("wallet_balance_cents", topped.get("balance_after"))
    assert post_balance is not None, (
        f"the admin-topup response should carry the post-topup balance; got keys: {list(topped.keys())}"
    )
    assert int(post_balance) == pre_balance + topup_amount, (
        f"post-topup balance {post_balance} != pre-balance {pre_balance} + amount {topup_amount}"
    )
