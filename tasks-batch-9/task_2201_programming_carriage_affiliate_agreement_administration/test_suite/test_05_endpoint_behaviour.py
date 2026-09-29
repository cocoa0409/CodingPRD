"""Endpoint behaviour: partial updates, action endpoints, filtered listings,
computed reads and the logical-clock sweep.

Every test builds its own operator, agreement and dependent records from
scratch through PRD-declared endpoints, because the server starts each test
against an empty database with its logical clock at 2026-08-01T00:00:00Z.
"""
from datetime import datetime

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    clear_window,
    create_commitment,
    draft_agreement,
    execute_agreement,
    fetch_agreement,
    fetch_commitment,
    fetch_distributor,
    fetch_title,
    fetch_window,
    make_distributor_liaison_headers,
    plan_window,
    publish_rate_card_entry,
    read_clock,
    register_cleared_title,
    register_distributor,
    register_title,
    set_title_rights,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

_ADMIN = TEST_USERS["network_admin_headers"]
_SALES = TEST_USERS["affiliate_sales_exec_headers"]
_ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]
_AUDITOR = TEST_USERS["audit_manager_headers"]
_RIGHTS = TEST_USERS["rights_administrator_headers"]

_TERM_START = "2025-01-01T00:00:00Z"
_TERM_END = "2028-12-31T00:00:00Z"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of the same moment
    compare equal (PRD §2.6 compares instants at whole-second resolution)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(microsecond=0)


def _executed_agreement(**agreement_overrides):
    """One operator of 1,500,000 homes with one EXECUTED agreement priced at a
    flat 40.0000 cents (no escalator), running 2025-01-01 → 2028-12-31."""
    distributor = register_distributor(total_subscribers=1_500_000)
    payload = {
        "term_start_date": _TERM_START,
        "term_end_date": _TERM_END,
        "base_license_fee_cents_per_sub": 40.0000,
        "escalator_pct": 0.00,
        "penetration_floor_pct": 0.50,
        "committed_tier": "BASIC",
    }
    payload.update(agreement_overrides)
    agreement = draft_agreement(distributor["id"], **payload)
    agreement = execute_agreement(agreement["id"])
    return fetch_distributor(distributor["id"]), agreement


def _september_window(agreement_id, title_id, platform, **overrides):
    """A non-exclusive September-2026 window on one title, cleared."""
    payload = {
        "platform": platform,
        "territory_code": "US",
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-30T00:00:00Z",
        "exclusivity": "NON_EXCLUSIVE",
    }
    payload.update(overrides)
    return plan_window(agreement_id, title_id, **payload)


class TestDistributorAdjustment:
    """PATCH /carriage/distributors/{distributorId} as a partial update."""

    def test_patching_credit_limit_alone_leaves_every_other_field_untouched(self):
        """PRD §3.1: "Only a `NetworkAdmin` may adjust an operator's
        `total_subscribers` or `credit_limit_cents` after registration, and
        either adjustment bumps the operator's `version` by one."
        PRD §2.4: "Mutable resources additionally carry `created_at` and
        `updated_at`, both ISO 8601 UTC timestamps with three fractional digits,
        and `version`, an integer that starts at 1 when the resource is created
        and increments by exactly 1 on every mutation the server applies to that
        resource — including mutations the caller did not directly address, such
        as a counter refreshed by a cascade originating on a different resource."

        Design: Corner/endpoints/distributor_patch_is_a_partial_update
        """
        distributor = register_distributor(
            legal_name="Meridian Broadband", total_subscribers=1_500_000
        )
        assert distributor["version"] == 1, "a freshly registered operator carries version 1"

        response = api_client.patch_distributor(
            distributor["id"], {"credit_limit_cents": 250_000_000}, _ADMIN
        )
        data = validate_success(response)

        assert data["credit_limit_cents"] == 250_000_000, (
            f"the adjusted credit limit must be stamped, got {data['credit_limit_cents']}"
        )
        assert data["total_subscribers"] == 1_500_000, (
            "adjusting the credit limit alone must leave total_subscribers at "
            f"1500000, got {data['total_subscribers']}"
        )
        assert data["legal_name"] == "Meridian Broadband", (
            f"legal_name must be untouched, got {data['legal_name']!r}"
        )
        assert data["status"] == "ACTIVE", f"status must stay ACTIVE, got {data['status']}"
        assert data["credit_hold_reason"] == "NONE", (
            f"credit_hold_reason must stay NONE, got {data['credit_hold_reason']}"
        )
        assert data["version"] == 2, (
            f"the adjustment bumps version by exactly one, got {data['version']}"
        )

    def test_patching_an_undeclared_field_is_rejected_and_bumps_nothing(self):
        """PRD §2.8: "Request shape — `ERR_INVALID_REQUEST` (HTTP 400). Every
        required field of the endpoint must be present and non-null; enum fields
        must carry a declared member; integer fields must be integers; monetary
        and subscriber fields must not be negative; a `period_month`,
        `sample_period_start` or `sample_period_end` must match a four-digit
        year, a hyphen, and a two-digit month between `01` and `12`; a
        `territory_code`, `home_territory_code` or the territory of a blackout
        must be exactly two uppercase letters; a `term_end_date` at or before
        `term_start_date` is malformed; and no unknown field may be present."
        PRD §2.8: "**The first rule that fails decides the response, and no side
        effect of the requested operation fires.**"
        PRD §2.8: "The path identifiers used across the API are `distributorId`,
        `agreementId`, `rateCardEntryId`, `mfnClauseId`, `reportId`,
        `engagementId`, `findingId`, `titleId`, `windowId`, `blackoutRuleId`,
        `commitmentId`, `invoiceId` and `analysisId`, and each has its own
        not-found code: `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_RATE_CARD_ENTRY_NOT_FOUND`, `ERR_MFN_CLAUSE_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`,
        `ERR_FINDING_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
        `ERR_BLACKOUT_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND` and `ERR_ANALYSIS_NOT_FOUND`, all HTTP 404."

        Design: Corner/endpoints/distributor_patch_is_a_partial_update
        """
        distributor = register_distributor(
            legal_name="Meridian Broadband", total_subscribers=1_500_000
        )
        adjusted = validate_success(
            api_client.patch_distributor(
                distributor["id"], {"credit_limit_cents": 250_000_000}, _ADMIN
            )
        )
        assert adjusted["version"] == 2, "the accepted adjustment leaves version at 2"

        rejected = api_client.patch_distributor(
            distributor["id"], {"legal_name": "Renamed"}, _ADMIN
        )
        validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST.value)

        after = fetch_distributor(distributor["id"])
        assert after["version"] == 2, (
            f"a rejected request fires no side effect, so version stays 2, got {after['version']}"
        )
        assert after["legal_name"] == "Meridian Broadband", (
            f"legal_name must not be partially applied, got {after['legal_name']!r}"
        )

        missing = api_client.patch_distributor(
            NON_EXISTENT_UUID, {"credit_limit_cents": 300_000_000}, _ADMIN
        )
        validate_error(missing, ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND.value)


class TestAgreementAmendment:
    """PATCH /carriage/agreements/{agreementId} before and after execution."""

    def test_draft_amendment_restamps_the_rate_fields(self):
        """PRD §3.2: "Commercial terms may be amended only while the agreement
        is still pre-execution."
        PRD §3.2: "An amendment may revise `base_license_fee_cents_per_sub`,
        `escalator_pct`, `penetration_floor_pct`, `committed_tier`,
        `term_end_date`, `launch_fee_cents` and `marketing_commitment_cents`,
        re-stamps both rate fields, and increments `version` by one."
        PRD §3.3: "The escalated rate is then `base_license_fee_cents_per_sub`
        multiplied by one plus `escalator_pct`, raised to the power of that
        contract-year index, rounded half up to four decimal places of a cent."
        PRD §3.3: "If there is no `ACTIVE` clause, or the `ACTIVE` clause's
        `benchmark_status` is `NOT_EVALUATED` or `NO_COMPARABLE`, the effective
        rate equals the escalated rate and `mfn_capped` is false."

        Design: Corner/endpoints/agreement_terms_are_patchable_only_before_execution
        """
        distributor = register_distributor(total_subscribers=1_500_000)
        agreement = draft_agreement(
            distributor["id"],
            contract_code="MB-PATCH",
            term_start_date=_TERM_START,
            term_end_date=_TERM_END,
            base_license_fee_cents_per_sub=40.0000,
            escalator_pct=0.00,
            penetration_floor_pct=0.50,
            committed_tier="BASIC",
        )

        response = api_client.patch_agreement(
            agreement["id"], {"base_license_fee_cents_per_sub": 44.0000}, _SALES
        )
        amended = validate_success(response)

        assert amended["base_license_fee_cents_per_sub"] == pytest.approx(44.0000, abs=0.01), (
            "the amended base fee must be stored, got "
            f"{amended['base_license_fee_cents_per_sub']}"
        )
        assert amended["lifecycle_status"] == "DRAFT", (
            f"amending does not move the lifecycle, got {amended['lifecycle_status']}"
        )
        assert amended["escalated_rate_cents_per_sub"] == pytest.approx(44.0000, abs=0.01), (
            "a zero escalator leaves the escalated rate at the amended base, got "
            f"{amended['escalated_rate_cents_per_sub']}"
        )
        assert amended["effective_rate_cents_per_sub"] == pytest.approx(44.0000, abs=0.01), (
            "with no MFN clause the effective rate equals the escalated rate, got "
            f"{amended['effective_rate_cents_per_sub']}"
        )
        assert amended["version"] == 2, (
            f"the amendment increments version by one, got {amended['version']}"
        )

        executed = execute_agreement(agreement["id"])
        assert executed["effective_rate_cents_per_sub"] == pytest.approx(44.0000, abs=0.01), (
            "execution re-stamps the rate from the amended base of 44.0000, got "
            f"{executed['effective_rate_cents_per_sub']}"
        )

    def test_amendment_after_execution_is_refused(self):
        """PRD §3.2: "Once `lifecycle_status` has reached `EXECUTED`,
        `SUSPENDED`, `EXPIRED` or `TERMINATED`, an amendment is refused with
        `ERR_INVALID_AGREEMENT_STATE`."
        PRD §2.8: "**The first rule that fails decides the response, and no side
        effect of the requested operation fires.**"

        Design: Corner/endpoints/agreement_terms_are_patchable_only_before_execution
        """
        distributor = register_distributor(total_subscribers=1_500_000)
        agreement = draft_agreement(
            distributor["id"],
            contract_code="MB-PATCH",
            term_start_date=_TERM_START,
            term_end_date=_TERM_END,
            base_license_fee_cents_per_sub=40.0000,
            escalator_pct=0.00,
            penetration_floor_pct=0.50,
            committed_tier="BASIC",
        )
        validate_success(
            api_client.patch_agreement(
                agreement["id"], {"base_license_fee_cents_per_sub": 44.0000}, _SALES
            )
        )
        execute_agreement(agreement["id"])

        response = api_client.patch_agreement(
            agreement["id"], {"base_license_fee_cents_per_sub": 50.0000}, _SALES
        )
        validate_error(response, ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value)

        after = fetch_agreement(agreement["id"])
        assert after["base_license_fee_cents_per_sub"] == pytest.approx(44.0000, abs=0.01), (
            "the refused amendment must not touch the executed terms, got "
            f"{after['base_license_fee_cents_per_sub']}"
        )
        assert after["lifecycle_status"] == "EXECUTED", (
            f"the agreement stays EXECUTED, got {after['lifecycle_status']}"
        )


def _operator_on_manual_credit_hold():
    """An executed agreement with one CLEARED VOD window, no invoices at all,
    whose operator has then been placed on a manual credit hold.

    Returns (distributor, agreement, title, window) as read before the hold.
    """
    distributor, agreement = _executed_agreement(contract_code="MB-HOLD")
    title = register_cleared_title(linear_premiere_at="2026-08-15T00:00:00Z")
    window = _september_window(agreement["id"], title["id"], "VOD")
    window = clear_window(window["id"])
    held = validate_success(
        api_client.credit_review(
            distributor["id"],
            {"action": "PLACE_HOLD", "reason": "Manual credit review pending"},
            _ACCOUNTANT,
        )
    )
    assert held["status"] == "CREDIT_HOLD", (
        f"PLACE_HOLD must move the operator to CREDIT_HOLD, got {held['status']}"
    )
    assert held["credit_hold_reason"] == "MANUAL_REVIEW", (
        "a hold a human places directly records MANUAL_REVIEW, got "
        f"{held['credit_hold_reason']}"
    )
    return distributor, agreement, title, window


class TestCreditHoldRelease:
    """POST /carriage/distributors/{distributorId}/credit-review — RELEASE_HOLD."""

    def test_release_hold_restores_active_posture_when_both_balances_permit(self):
        """PRD §3.1: "Placing a hold moves an `ACTIVE` operator to `CREDIT_HOLD`
        with `credit_hold_reason` set to `MANUAL_REVIEW`, and then runs the
        operator-level cascade in full: every agreement of that operator whose
        `lifecycle_status` is `EXECUTED` moves to `SUSPENDED` with
        `suspension_reason` of `DISTRIBUTOR_CREDIT_HOLD`, processed in
        `created_at` ascending order; each of those agreements' rights windows in
        `CLEARED` or `ACTIVE` move to `BLOCKED` with `block_reason` of
        `AGREEMENT_SUSPENDED`; and each content title touched by those windows
        re-derives `cleared_window_count` and `distribution_coverage_status`."
        PRD §3.1: "Releasing a hold is only permitted when
        `receivable_balance_cents` is at or below `credit_limit_cents` **and**
        `audit_recovery_balance_cents` is exactly zero; the operator returns to
        `ACTIVE` with `credit_hold_reason` back to `NONE`."

        Design: Corner/endpoints/release_hold_clears_status_without_reinstating_agreements
        """
        distributor, _agreement, _title, _window = _operator_on_manual_credit_hold()

        held = fetch_distributor(distributor["id"])
        assert held["receivable_balance_cents"] == 0, (
            "with no invoices at all the receivable is 0, the first release "
            f"precondition, got {held['receivable_balance_cents']}"
        )
        assert held["audit_recovery_balance_cents"] == 0, (
            "with no invoices at all the audit-recovery balance is 0, the second "
            f"release precondition, got {held['audit_recovery_balance_cents']}"
        )

        response = api_client.credit_review(
            distributor["id"], {"action": "RELEASE_HOLD"}, _ACCOUNTANT
        )
        released = validate_success(response)

        assert released["status"] == "ACTIVE", (
            f"a permitted release returns the operator to ACTIVE, got {released['status']}"
        )
        assert released["credit_hold_reason"] == "NONE", (
            f"credit_hold_reason returns to NONE, got {released['credit_hold_reason']}"
        )

    def test_release_hold_reinstates_neither_agreement_nor_window(self):
        """PRD §3.1: "Release does not un-suspend anything — agreements suspended
        for `DISTRIBUTOR_CREDIT_HOLD` stay suspended until someone reinstates
        them explicitly."
        PRD §3.6: "`cleared_window_count` is the number of that title's windows
        whose `status` is `CLEARED` or `ACTIVE`."
        PRD §3.6: "`distribution_coverage_status` is derived from the *set of
        distinct platforms* among exactly those windows, by a pinned ladder
        evaluated top to bottom and stopping at the first arm that matches: if
        the set is empty the status is `UNDISTRIBUTED`; otherwise if the set is
        exactly `LINEAR` and nothing else the status is `LINEAR_ONLY`; otherwise
        if the set holds two or more distinct platforms the status is
        `MULTIPLATFORM`; otherwise the set holds exactly one platform which is
        not `LINEAR`, and the status is `EXCLUSIVE_UNCLEARED`, meaning a
        downstream platform is cleared while the linear window that is supposed
        to precede it is not."

        Design: Corner/endpoints/release_hold_clears_status_without_reinstating_agreements
        """
        distributor, agreement, title, window = _operator_on_manual_credit_hold()

        validate_success(
            api_client.credit_review(
                distributor["id"], {"action": "RELEASE_HOLD"}, _ACCOUNTANT
            )
        )

        after_agreement = fetch_agreement(agreement["id"])
        assert after_agreement["lifecycle_status"] == "SUSPENDED", (
            "the agreement stays SUSPENDED after the release, got "
            f"{after_agreement['lifecycle_status']}"
        )
        assert after_agreement["suspension_reason"] == "DISTRIBUTOR_CREDIT_HOLD", (
            "the suspension reason recorded by the hold cascade survives the "
            f"release, got {after_agreement['suspension_reason']}"
        )

        after_window = fetch_window(window["id"])
        assert after_window["status"] == "BLOCKED", (
            f"the window stays BLOCKED after the release, got {after_window['status']}"
        )
        assert after_window["block_reason"] == "AGREEMENT_SUSPENDED", (
            f"the block reason stays AGREEMENT_SUSPENDED, got {after_window['block_reason']}"
        )

        after_title = fetch_title(title["id"])
        assert after_title["cleared_window_count"] == 0, (
            "a blocked window no longer counts as cleared, got "
            f"{after_title['cleared_window_count']}"
        )
        assert after_title["distribution_coverage_status"] == "UNDISTRIBUTED", (
            "an empty occupying window set derives UNDISTRIBUTED, got "
            f"{after_title['distribution_coverage_status']}"
        )


def _title_with_two_cleared_windows():
    """One executed agreement; one OWNED_CLEARED title carrying a CLEARED LINEAR
    window and a CLEARED VOD window over September 2026.

    Returns (agreement, title, linear_window, vod_window).
    """
    _distributor, agreement = _executed_agreement(contract_code="MB-RIGHTS")
    title = register_cleared_title(linear_premiere_at="2026-08-15T00:00:00Z")
    linear_window = _september_window(agreement["id"], title["id"], "LINEAR")
    linear_window = clear_window(linear_window["id"])
    vod_window = _september_window(agreement["id"], title["id"], "VOD")
    vod_window = clear_window(vod_window["id"])
    return agreement, title, linear_window, vod_window


class TestTitleRightsExpiry:
    """POST /carriage/content-titles/{titleId}/rights-status — EXPIRED_RIGHTS."""

    def test_expiring_rights_blocks_every_cleared_window_with_rights_lapsed(self):
        """PRD §3.6: "Moving a title to `EXPIRED_RIGHTS` is destructive: every
        rights window of that title in `CLEARED` or `ACTIVE` moves to `BLOCKED`
        with `block_reason` of `RIGHTS_LAPSED`, and the title then re-derives
        `cleared_window_count` and `distribution_coverage_status`."
        PRD §3.6: "`distribution_coverage_status` is derived from the *set of
        distinct platforms* among exactly those windows, by a pinned ladder
        evaluated top to bottom and stopping at the first arm that matches: if
        the set is empty the status is `UNDISTRIBUTED`; otherwise if the set is
        exactly `LINEAR` and nothing else the status is `LINEAR_ONLY`; otherwise
        if the set holds two or more distinct platforms the status is
        `MULTIPLATFORM`; otherwise the set holds exactly one platform which is
        not `LINEAR`, and the status is `EXCLUSIVE_UNCLEARED`, meaning a
        downstream platform is cleared while the linear window that is supposed
        to precede it is not."
        PRD §3.6: "Every rights-status change increments the title's `version` by
        one."

        Design: Corner/endpoints/expiring_title_rights_blocks_its_cleared_windows
        """
        _agreement, title, linear_window, vod_window = _title_with_two_cleared_windows()

        before = fetch_title(title["id"])
        assert before["cleared_window_count"] == 2, (
            f"two cleared windows must be counted, got {before['cleared_window_count']}"
        )
        assert before["distribution_coverage_status"] == "MULTIPLATFORM", (
            "LINEAR plus VOD is two distinct platforms, so coverage is "
            f"MULTIPLATFORM, got {before['distribution_coverage_status']}"
        )

        response = api_client.set_title_rights_status(
            title["id"], {"rights_status": "EXPIRED_RIGHTS"}, _RIGHTS
        )
        data = validate_success(response)

        assert data["rights_status"] == "EXPIRED_RIGHTS", (
            f"the rights status must be stamped, got {data['rights_status']}"
        )
        assert data["cleared_window_count"] == 0, (
            "both windows left the occupying states, so the count re-derives to "
            f"0, got {data['cleared_window_count']}"
        )
        assert data["distribution_coverage_status"] == "UNDISTRIBUTED", (
            "an empty occupying window set derives UNDISTRIBUTED, got "
            f"{data['distribution_coverage_status']}"
        )
        assert data["version"] == before["version"] + 1, (
            "the rights-status change increments the title's version by one, got "
            f"{data['version']} from {before['version']}"
        )

        for window in (linear_window, vod_window):
            after = fetch_window(window["id"])
            assert after["status"] == "BLOCKED", (
                f"window {window['platform']} must be BLOCKED, got {after['status']}"
            )
            assert after["block_reason"] == "RIGHTS_LAPSED", (
                "a title losing its rights records RIGHTS_LAPSED, got "
                f"{after['block_reason']}"
            )

    def test_unblocking_is_refused_while_the_title_rights_are_expired(self):
        """PRD §3.6: "Only `OWNED_CLEARED` permits a window on that title to be
        cleared; `PENDING_CLEARANCE`, `THIRD_PARTY_LICENSED` and
        `EXPIRED_RIGHTS` all block clearance with
        `ERR_TITLE_RIGHTS_NOT_CLEARED`."
        PRD §3.6: "Unblocking moves a window `BLOCKED → CLEARED`, requires the
        granting agreement to be `EXECUTED` and the title to be `OWNED_CLEARED`,
        and re-runs both the occupancy check and the blackout-intersection check
        — a slot that was taken over while the window sat blocked cannot be
        reclaimed."

        Design: Corner/endpoints/expiring_title_rights_blocks_its_cleared_windows
        """
        _agreement, title, _linear_window, vod_window = _title_with_two_cleared_windows()
        set_title_rights(title["id"], "EXPIRED_RIGHTS")

        response = api_client.rights_window_lifecycle(
            vod_window["id"], {"action": "UNBLOCK"}, _RIGHTS
        )
        validate_error(response, ApiErrorId.ERR_TITLE_RIGHTS_NOT_CLEARED.value)

        after = fetch_window(vod_window["id"])
        assert after["status"] == "BLOCKED", (
            f"the refused unblock leaves the window BLOCKED, got {after['status']}"
        )
        assert after["block_reason"] == "RIGHTS_LAPSED", (
            f"the block reason is unchanged, got {after['block_reason']}"
        )


def _two_titles_three_windows():
    """One executed agreement; title A with a CLEARED LINEAR window and a
    CLEARED VOD window in September 2026; title B with one PLANNED VOD window in
    October 2026.

    Returns (agreement, title_a, title_b, a_linear, a_vod, b_vod).
    """
    _distributor, agreement = _executed_agreement(contract_code="MB-JOIN")
    title_a = register_cleared_title(linear_premiere_at="2026-08-15T00:00:00Z")
    title_b = register_title(linear_premiere_at="2026-08-16T00:00:00Z")
    a_linear = _september_window(agreement["id"], title_a["id"], "LINEAR")
    a_linear = clear_window(a_linear["id"])
    a_vod = _september_window(agreement["id"], title_a["id"], "VOD")
    a_vod = clear_window(a_vod["id"])
    b_vod = plan_window(
        agreement["id"],
        title_b["id"],
        platform="VOD",
        territory_code="US",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-31T00:00:00Z",
        exclusivity="NON_EXCLUSIVE",
    )
    return agreement, title_a, title_b, a_linear, a_vod, b_vod


class TestRightsWindowListing:
    """GET /carriage/rights-windows — title, platform and status filters."""

    def test_title_platform_and_status_filters_combine_conjunctively(self):
        """PRD §2.3: "Filter query parameters combine conjunctively: supplying
        both an agreement filter and a status filter returns only records
        satisfying both."
        PRD §2.3: "`total_count` is the number of records matching the filter
        before pagination is applied, and `has_more` is true exactly when records
        remain beyond the current page."

        Design: Corner/endpoints/rights_window_listing_joins_by_title_platform_and_status
        """
        agreement, title_a, _title_b, _a_linear, a_vod, b_vod = _two_titles_three_windows()

        data, meta = validate_paginated(
            api_client.list_rights_windows(
                _SALES, params={"content_title_id": title_a["id"], "limit": 10}
            )
        )
        assert meta["total_count"] == 2, (
            f"title A carries exactly two windows, got total_count {meta['total_count']}"
        )
        assert len(data) == 2, f"both matching rows must be returned, got {len(data)}"
        assert all(row["content_title_id"] == title_a["id"] for row in data), (
            "every returned row must belong to the filtered title"
        )

        data, meta = validate_paginated(
            api_client.list_rights_windows(
                _SALES,
                params={"content_title_id": title_a["id"], "platform": "VOD", "limit": 10},
            )
        )
        assert meta["total_count"] == 1, (
            "adding platform=VOD narrows title A's two windows to one, got "
            f"total_count {meta['total_count']}"
        )
        assert data[0]["id"] == a_vod["id"], (
            f"the single row must be title A's VOD window, got {data[0]['id']}"
        )

        data, meta = validate_paginated(
            api_client.list_rights_windows(_SALES, params={"status": "PLANNED", "limit": 10})
        )
        assert meta["total_count"] == 1, (
            f"only one window is still PLANNED, got total_count {meta['total_count']}"
        )
        assert data[0]["id"] == b_vod["id"], (
            f"the uncleared row must be title B's VOD window, got {data[0]['id']}"
        )

        _data, meta = validate_paginated(
            api_client.list_rights_windows(
                _SALES, params={"agreement_id": agreement["id"], "limit": 10}
            )
        )
        assert meta["total_count"] == 3, (
            f"all three windows hang off the one agreement, got {meta['total_count']}"
        )

    def test_filter_matching_nothing_returns_an_empty_page(self):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside `meta`."
        PRD §2.3: "`total_count` is the number of records matching the filter
        before pagination is applied, and `has_more` is true exactly when records
        remain beyond the current page."
        PRD §2.3: "`limit` defaults to 10, may not be smaller than 1, and may not
        be larger than 100."

        Design: Corner/endpoints/rights_window_listing_joins_by_title_platform_and_status
        """
        _two_titles_three_windows()

        data, meta = validate_paginated(
            api_client.list_rights_windows(
                _SALES, params={"content_title_id": NON_EXISTENT_UUID, "limit": 10}
            )
        )
        assert meta["total_count"] == 0, (
            f"no window matches the filter, so total_count is 0, got {meta['total_count']}"
        )
        assert data == [], f"the data array must be empty, got {data}"
        assert meta["limit"] == 10, f"the supplied limit is echoed, got {meta['limit']}"
        assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"
        assert meta["has_more"] is False, (
            f"no records remain beyond an empty page, got {meta['has_more']}"
        )


class TestRateCardListing:
    """GET /carriage/rate-card-entries — class and tier filters."""

    def test_class_and_tier_filters_narrow_the_published_card(self):
        """PRD §2.3: "Filter query parameters combine conjunctively: supplying
        both an agreement filter and a status filter returns only records
        satisfying both."
        PRD §2.3: "`total_count` is the number of records matching the filter
        before pagination is applied, and `has_more` is true exactly when records
        remain beyond the current page."
        PRD §3.1: "Each row states the `rate_card_class` and `tier` it prices —
        the tier being one of `BASIC`, `EXPANDED_BASIC`, `DIGITAL_TIER` or
        `PREMIUM` — a `published_rate_cents_per_sub` strictly greater than zero,
        an inclusive `effective_from` instant and an optional `effective_to`
        instant that is exclusive and must be strictly later than
        `effective_from` when supplied; a null `effective_to` means the row is
        open-ended."

        Design: Corner/endpoints/rate_card_listing_filters_by_class_then_tier
        """
        class_a_basic = publish_rate_card_entry(
            rate_card_class="CLASS_A",
            tier="BASIC",
            published_rate_cents_per_sub=40.0000,
            effective_from="2026-01-01T00:00:00Z",
        )
        publish_rate_card_entry(
            rate_card_class="CLASS_A",
            tier="EXPANDED_BASIC",
            published_rate_cents_per_sub=44.5000,
            effective_from="2026-01-01T00:00:00Z",
        )
        publish_rate_card_entry(
            rate_card_class="CLASS_B",
            tier="BASIC",
            published_rate_cents_per_sub=38.0000,
            effective_from="2026-01-01T00:00:00Z",
        )

        _data, meta = validate_paginated(
            api_client.list_rate_card_entries(
                _ACCOUNTANT, params={"rate_card_class": "CLASS_A", "limit": 10}
            )
        )
        assert meta["total_count"] == 2, (
            f"two of the three rows price CLASS_A, got total_count {meta['total_count']}"
        )

        data, meta = validate_paginated(
            api_client.list_rate_card_entries(
                _ACCOUNTANT,
                params={"rate_card_class": "CLASS_A", "tier": "BASIC", "limit": 10},
            )
        )
        assert meta["total_count"] == 1, (
            "adding tier=BASIC narrows CLASS_A to one row, got total_count "
            f"{meta['total_count']}"
        )
        assert data[0]["id"] == class_a_basic["id"], (
            f"the single row must be the CLASS_A/BASIC row, got {data[0]['id']}"
        )
        assert data[0]["published_rate_cents_per_sub"] == pytest.approx(40.0000, abs=0.01), (
            "the published rate is carried through, got "
            f"{data[0]['published_rate_cents_per_sub']}"
        )

    def test_unfiltered_listing_counts_every_row_and_unknown_id_is_not_found(self):
        """PRD §2.3: "`total_count` is the number of records matching the filter
        before pagination is applied, and `has_more` is true exactly when records
        remain beyond the current page."
        PRD §2.8: "The path identifiers used across the API are `distributorId`,
        `agreementId`, `rateCardEntryId`, `mfnClauseId`, `reportId`,
        `engagementId`, `findingId`, `titleId`, `windowId`, `blackoutRuleId`,
        `commitmentId`, `invoiceId` and `analysisId`, and each has its own
        not-found code: `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_RATE_CARD_ENTRY_NOT_FOUND`, `ERR_MFN_CLAUSE_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`,
        `ERR_FINDING_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
        `ERR_BLACKOUT_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND` and `ERR_ANALYSIS_NOT_FOUND`, all HTTP 404."

        Design: Corner/endpoints/rate_card_listing_filters_by_class_then_tier
        """
        for rate_card_class, tier, rate in (
            ("CLASS_A", "BASIC", 40.0000),
            ("CLASS_A", "EXPANDED_BASIC", 44.5000),
            ("CLASS_B", "BASIC", 38.0000),
        ):
            publish_rate_card_entry(
                rate_card_class=rate_card_class,
                tier=tier,
                published_rate_cents_per_sub=rate,
                effective_from="2026-01-01T00:00:00Z",
            )

        data, meta = validate_paginated(
            api_client.list_rate_card_entries(_ACCOUNTANT, params={"limit": 10})
        )
        assert meta["total_count"] == 3, (
            f"an unfiltered listing counts all three rows, got {meta['total_count']}"
        )
        assert len(data) == 3, f"all three rows fit inside the page, got {len(data)}"

        validate_error(
            api_client.get_rate_card_entry(NON_EXISTENT_UUID, _ACCOUNTANT),
            ApiErrorId.ERR_RATE_CARD_ENTRY_NOT_FOUND.value,
        )


class TestSettlementSummaryRead:
    """GET /carriage/agreements/{agreementId}/settlement-summary."""

    def test_summary_is_derived_at_read_time_and_mutates_nothing(self):
        """PRD §3.8: "It reports the `agreement_id`; the agreement's stored
        `recognized_revenue_cents`; `accepted_report_fee_total_cents`, the sum of
        `license_fee_due_cents` across that agreement's reports in `ACCEPTED` or
        `AUDIT_ADJUSTED` status; `invoiced_gross_total_cents`, the sum of
        `gross_license_fee_cents` across that agreement's invoices other than
        those in `VOID`; `open_receivable_cents`, the sum of `net_due_cents` less
        `paid_cents` across that agreement's invoices in `ISSUED` or
        `PARTIALLY_PAID`; and four marketing roll-ups across the agreement's
        commitment lines — `marketing_committed_cents`, `marketing_earned_cents`,
        `marketing_remaining_cents` and `marketing_forfeited_cents`, each the sum
        of the corresponding per-line field."
        PRD §3.8: "It closes with two booleans:
        `marketing_conserved_identity_holds`, true when every one of those lines
        satisfies committed equals earned plus remaining plus forfeited, and
        `revenue_identity_holds`, true when `recognized_revenue_cents` equals
        `accepted_report_fee_total_cents`."
        PRD §2.4: "Mutable resources additionally carry `created_at` and
        `updated_at`, both ISO 8601 UTC timestamps with three fractional digits,
        and `version`, an integer that starts at 1 when the resource is created
        and increments by exactly 1 on every mutation the server applies to that
        resource — including mutations the caller did not directly address, such
        as a counter refreshed by a cascade originating on a different resource."

        Design: Corner/endpoints/settlement_summary_read_is_side_effect_free
        """
        distributor, agreement = _executed_agreement(contract_code="MB-SUM")
        version_before = agreement["version"]

        liaison_read = validate_success(
            api_client.get_settlement_summary(
                agreement["id"], make_distributor_liaison_headers(distributor["id"])
            )
        )
        auditor_read = validate_success(
            api_client.get_settlement_summary(agreement["id"], _AUDITOR)
        )

        for label, data in (("liaison read", liaison_read), ("auditor read", auditor_read)):
            assert data["agreement_id"] == agreement["id"], (
                f"{label} must report the agreement it rolls up, got {data['agreement_id']}"
            )
            for field in (
                "recognized_revenue_cents",
                "accepted_report_fee_total_cents",
                "invoiced_gross_total_cents",
                "open_receivable_cents",
                "marketing_committed_cents",
                "marketing_earned_cents",
                "marketing_remaining_cents",
                "marketing_forfeited_cents",
            ):
                assert data[field] == 0, (
                    f"{label}: with no reports, invoices or commitments {field} "
                    f"rolls up to 0, got {data[field]}"
                )
            assert data["revenue_identity_holds"] is True, (
                f"{label}: recognized revenue equals the accepted fee total, so "
                f"revenue_identity_holds is true, got {data['revenue_identity_holds']}"
            )
            assert data["marketing_conserved_identity_holds"] is True, (
                f"{label}: every commitment line satisfies the conserved identity, "
                f"got {data['marketing_conserved_identity_holds']}"
            )

        assert liaison_read["recognized_revenue_cents"] == auditor_read[
            "recognized_revenue_cents"
        ], "two reads of the same agreement must report identical figures"

        after = fetch_agreement(agreement["id"])
        assert after["version"] == version_before, (
            "a read is not a mutation, so the agreement's version is unchanged: "
            f"expected {version_before}, got {after['version']}"
        )

    def test_summary_of_an_unknown_agreement_is_not_found(self):
        """PRD §2.8: "Path parameters are resolved left to right, and the first
        unresolvable segment decides the response."
        PRD §2.8: "The path identifiers used across the API are `distributorId`,
        `agreementId`, `rateCardEntryId`, `mfnClauseId`, `reportId`,
        `engagementId`, `findingId`, `titleId`, `windowId`, `blackoutRuleId`,
        `commitmentId`, `invoiceId` and `analysisId`, and each has its own
        not-found code: `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_RATE_CARD_ENTRY_NOT_FOUND`, `ERR_MFN_CLAUSE_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`,
        `ERR_FINDING_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
        `ERR_BLACKOUT_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND` and `ERR_ANALYSIS_NOT_FOUND`, all HTTP 404."

        Design: Corner/endpoints/settlement_summary_read_is_side_effect_free
        """
        _executed_agreement(contract_code="MB-SUM")

        validate_error(
            api_client.get_settlement_summary(NON_EXISTENT_UUID, _AUDITOR),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        )


def _agreement_expiring_end_of_2026():
    """An executed agreement whose term ends 2026-12-31, carrying one CLEARED
    VOD window over September 2026 and one untouched COOP_ADVERTISING commitment
    of 1,000,000 cents due 2026-10-01.

    Returns (agreement, title, window, commitment).
    """
    _distributor, agreement = _executed_agreement(
        contract_code="MB-SWEEP", term_end_date="2026-12-31T00:00:00Z"
    )
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-10-01T00:00:00Z",
    )
    title = register_cleared_title(linear_premiere_at="2026-08-15T00:00:00Z")
    window = _september_window(agreement["id"], title["id"], "VOD")
    window = clear_window(window["id"])
    return agreement, title, window, commitment


class TestClockAdvanceSweep:
    """POST /_clock/set_current_utc — the pinned six-step sweep."""

    def test_one_advance_expires_the_agreement_window_and_forfeits_the_commitment(self):
        """PRD §2.5: "A `NetworkAdmin` moves the clock by supplying `to_iso8601`."
        PRD §2.5: "A successful advance increments `set_count` by one and then
        runs a single sweep whose step order is pinned and observable:"
        PRD §2.5: "Agreements whose `lifecycle_status` is `EXECUTED` or
        `SUSPENDED` and whose `term_end_date` is at or before the new
        `current_utc` move to `EXPIRED`, processed in `term_end_date` ascending,
        then `created_at` ascending."
        PRD §2.5: "Rights windows in `CLEARED` or `ACTIVE` whose `window_end` is
        at or before `current_utc` move to `EXPIRED`."
        PRD §2.5: "Marketing commitments whose `performance_deadline` is strictly
        before `current_utc` and whose `remaining_cents` is still positive forfeit
        their remainder, processed in `performance_deadline` ascending, then
        `created_at` ascending."
        PRD §2.5: "Every content title touched by steps 2 and 3 re-derives
        `cleared_window_count` and `distribution_coverage_status`."
        PRD §3.8: "And when a clock advance finds the `performance_deadline`
        passed with `remaining_cents` still positive, that remainder is added to
        `forfeited_cents`, `remaining_cents` drops to 0, and `status` becomes
        `FORFEITED` — permanently, since nothing un-forfeits a commitment."
        PRD §3.9: "`renewal_status` is the agreement's other, independent
        dimension (§3.2). It begins at `NOT_DUE` and advances only through
        deliberate negotiation events, never as a side effect of billing or
        reporting."

        Design: Corner/endpoints/single_clock_advance_sweeps_every_time_dependent_entity
        """
        agreement, title, window, commitment = _agreement_expiring_end_of_2026()
        set_count_before = read_clock()["set_count"]

        response = api_client.set_clock({"to_iso8601": "2027-02-01T00:00:00Z"}, _ADMIN)
        clock = validate_success(response)

        assert _instant(clock["current_utc"]) == _instant("2027-02-01T00:00:00Z"), (
            f"the logical now must be the supplied instant, got {clock['current_utc']}"
        )
        assert clock["set_count"] == set_count_before + 1, (
            "a successful advance increments set_count by one, got "
            f"{clock['set_count']} from {set_count_before}"
        )

        after_agreement = fetch_agreement(agreement["id"])
        assert after_agreement["lifecycle_status"] == "EXPIRED", (
            "a term ending 2026-12-31 is at or before the new now, so the "
            f"agreement is swept to EXPIRED, got {after_agreement['lifecycle_status']}"
        )
        assert after_agreement["renewal_status"] == "NOT_DUE", (
            "no renewal was ever started, so the renewal dimension stays NOT_DUE, "
            f"got {after_agreement['renewal_status']}"
        )

        after_window = fetch_window(window["id"])
        assert after_window["status"] == "EXPIRED", (
            f"a window whose end has passed is swept to EXPIRED, got {after_window['status']}"
        )

        after_commitment = fetch_commitment(commitment["id"])
        assert after_commitment["status"] == "FORFEITED", (
            "an unearned line past its deadline becomes FORFEITED, got "
            f"{after_commitment['status']}"
        )
        assert after_commitment["earned_cents"] == 0, (
            f"nothing was ever earned on the line, got {after_commitment['earned_cents']}"
        )
        assert after_commitment["remaining_cents"] == 0, (
            f"the remainder drops to 0 on forfeiture, got {after_commitment['remaining_cents']}"
        )
        assert after_commitment["forfeited_cents"] == 1_000_000, (
            "the whole 1,000,000-cent remainder is added to forfeited_cents, got "
            f"{after_commitment['forfeited_cents']}"
        )

        after_title = fetch_title(title["id"])
        assert after_title["cleared_window_count"] == 0, (
            "the title's only occupying window expired, got "
            f"{after_title['cleared_window_count']}"
        )
        assert after_title["distribution_coverage_status"] == "UNDISTRIBUTED", (
            "an empty occupying window set derives UNDISTRIBUTED, got "
            f"{after_title['distribution_coverage_status']}"
        )

    def test_a_swept_agreement_is_terminal_and_cannot_be_suspended(self):
        """PRD §3.2: "`lifecycle_status` runs through `DRAFT`, `NEGOTIATING`,
        `EXECUTED`, `SUSPENDED` and terminally `EXPIRED` or `TERMINATED`."
        PRD §3.2: "An action that is not a declared transition out of the current
        `lifecycle_status` is rejected with `ERR_INVALID_AGREEMENT_STATE`; an
        action that is not a declared transition out of the current
        `renewal_status` is rejected with `ERR_INVALID_RENEWAL_STATE`."
        PRD §2.5: "Agreements whose `lifecycle_status` is `EXECUTED` or
        `SUSPENDED` and whose `term_end_date` is at or before the new
        `current_utc` move to `EXPIRED`, processed in `term_end_date` ascending,
        then `created_at` ascending."

        Design: Corner/endpoints/single_clock_advance_sweeps_every_time_dependent_entity
        """
        agreement, _title, _window, _commitment = _agreement_expiring_end_of_2026()
        validate_success(api_client.set_clock({"to_iso8601": "2027-02-01T00:00:00Z"}, _ADMIN))

        response = api_client.agreement_lifecycle(
            agreement["id"],
            {"action": "SUSPEND", "suspension_reason": "MANUAL_SUSPENSION"},
            _SALES,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value)

        after = fetch_agreement(agreement["id"])
        assert after["lifecycle_status"] == "EXPIRED", (
            f"EXPIRED is terminal, so the state is unchanged, got {after['lifecycle_status']}"
        )
