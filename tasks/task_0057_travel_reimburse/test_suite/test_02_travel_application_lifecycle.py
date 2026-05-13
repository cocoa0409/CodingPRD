"""Travel application lifecycle: create, draft-edit (OCC), submit,
required_chain pinning, standard_version_pinned, approve, reject, cancel.

Targets PRD §3.2 (required_chain rules), §3.1 (standard pinning at submit),
§2.5 (OCC), and the TravelApplication state machine described in §3.2/§3.3.
"""
from __future__ import annotations
import uuid

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    approval_payload,
    approved_application,
    assert_application_chain_after_submit,
    assert_travel_application,
    create_approval_cast,
    create_employee,
    create_employee_payload,
    create_travel_application_payload,
    draft_application,
    get_success_data,
    make_applicant_headers,
    make_supervisor_headers,
    publish_expense_standard,
    reject_payload,
    standard_test_environment,
    submit_application,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    walk_approval_chain,
)
from test_helpers.fixtures import ADMIN


# ---------------------------------------------------------------------------
# Create + ownership (PRD §2.1, §3.2)
# ---------------------------------------------------------------------------
class TestCreateAndOwnership:

    def test_applicant_creates_draft_application(self, api):
        """PRD §3.2: "The applicant initiates a trip by creating a
        TravelApplication in DRAFT."

        Claim: POST /travel-applications as Applicant → 201 + status=DRAFT.
        """
        cast, _std = standard_test_environment()
        payload = create_travel_application_payload(
            destination_city="Beijing", destination_tier="TIER_1",
            estimated_budget=3000.00,
        )
        app = validate_success(
            api.create_travel_application(payload, cast.applicant_headers),
            expected_status=201,
        )
        assert_travel_application(app)
        assert app["status"] == "DRAFT"
        assert app["applicant_id"] == cast.applicant["id"], (
            "PRD §2.1: applicant_id must be inferred from X-User-ID"
        )

    def test_get_application_returns_full_shape(self, api):
        """PRD §4: GET /travel-applications/{id} returns the full row.

        Claim: a freshly created DRAFT application is fetchable.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast)
        retrieved = validate_success(
            api.get_travel_application(app["id"], cast.applicant_headers),
        )
        assert retrieved["id"] == app["id"]
        assert retrieved["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Submit + required_chain rules (PRD §3.2)
# ---------------------------------------------------------------------------
class TestSubmitChainComputation:

    def test_submit_chain_below_dept_threshold(self, api):
        """PRD §3.2: "Start the chain with the single step SUPERVISOR.
        If estimated_budget is strictly greater than 5,000 CNY or
        travel_scope equals OVERSEAS, append DEPT_HEAD to the chain.
        Append FINANCE next."

        Claim: budget=4500 + DOMESTIC + non-urgent → [SUPERVISOR, FINANCE].
        """
        cast, _std = standard_test_environment()
        app = draft_application(
            cast, estimated_budget=4500.00, travel_scope="DOMESTIC",
            urgent=False,
        )
        submitted = submit_application(cast, app)
        assert_application_chain_after_submit(
            submitted, expected_chain=["SUPERVISOR", "FINANCE"],
        )

    def test_submit_chain_above_dept_threshold_domestic(self, api):
        """PRD §3.2: "If estimated_budget is strictly greater than 5,000
        CNY or travel_scope equals OVERSEAS, append DEPT_HEAD to the chain."

        Claim: budget=10000 + DOMESTIC + non-urgent → [SUPERVISOR, DEPT_HEAD, FINANCE].
        """
        cast, _std = standard_test_environment()
        app = draft_application(
            cast, estimated_budget=10_000.00, travel_scope="DOMESTIC",
            urgent=False,
        )
        submitted = submit_application(cast, app)
        assert_application_chain_after_submit(
            submitted, expected_chain=["SUPERVISOR", "DEPT_HEAD", "FINANCE"],
        )

    def test_submit_chain_above_gm_threshold_domestic(self, api):
        """PRD §3.2: "If estimated_budget is strictly greater than 30,000
        CNY or travel_scope equals OVERSEAS, append GM to the chain."

        Claim: budget=50000 + DOMESTIC + non-urgent →
        [SUPERVISOR, DEPT_HEAD, FINANCE, GM].
        """
        cast, _std = standard_test_environment()
        app = draft_application(
            cast, estimated_budget=50_000.00, travel_scope="DOMESTIC",
            urgent=False,
        )
        submitted = submit_application(cast, app)
        assert_application_chain_after_submit(
            submitted,
            expected_chain=["SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM"],
        )

    def test_submit_chain_overseas_always_full(self, api):
        """PRD §3.2: "If estimated_budget is strictly greater than 5,000
        CNY or travel_scope equals OVERSEAS, append DEPT_HEAD to the chain.
        Append FINANCE next. If estimated_budget is strictly greater than
        30,000 CNY or travel_scope equals OVERSEAS, append GM to the chain."

        Claim: scope=OVERSEAS even with tiny budget →
        [SUPERVISOR, DEPT_HEAD, FINANCE, GM].
        """
        # Publish an OVERSEAS standard so submit can pin.
        publish_expense_standard(
            version=1, city_tier="OVERSEAS", employee_level="STAFF",
            effective_from="2024-01-01T00:00:00.000Z",
            lodging_daily_cap=600.00, per_diem_amount=100.00,
            transportation_daily_cap=200.00,
        )
        cast, _std = standard_test_environment(destination_tier="TIER_2")
        app = draft_application(
            cast, destination_tier="OVERSEAS", travel_scope="OVERSEAS",
            estimated_budget=2_000.00, urgent=False,
        )
        submitted = submit_application(cast, app)
        assert_application_chain_after_submit(
            submitted,
            expected_chain=["SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM"],
        )

    def test_urgent_domestic_drops_dept_head(self, api):
        """PRD §3.2: "if urgent is true and travel_scope is DOMESTIC,
        drop DEPT_HEAD from the chain if it is present — note that an
        urgent trip whose scope is OVERSEAS keeps the full chain because
        expedited routing only fires for domestic trips."

        Claim: urgent=true + DOMESTIC + budget=10000 →
        [SUPERVISOR, FINANCE] (DEPT_HEAD removed).
        """
        cast, _std = standard_test_environment()
        app = draft_application(
            cast, estimated_budget=10_000.00, travel_scope="DOMESTIC",
            urgent=True,
        )
        submitted = submit_application(cast, app)
        assert submitted["required_chain"] == ["SUPERVISOR", "FINANCE"], (
            f"PRD §3.2: urgent DOMESTIC must drop DEPT_HEAD; got "
            f"{submitted['required_chain']}"
        )

    def test_urgent_overseas_keeps_full_chain(self, api):
        """PRD §3.2: "an urgent trip whose scope is OVERSEAS keeps the
        full chain because expedited routing only fires for domestic
        trips."

        Claim: urgent=true + OVERSEAS → [SUPERVISOR, DEPT_HEAD, FINANCE, GM].
        """
        publish_expense_standard(
            version=1, city_tier="OVERSEAS", employee_level="STAFF",
            effective_from="2024-01-01T00:00:00.000Z",
            lodging_daily_cap=600.00, per_diem_amount=100.00,
            transportation_daily_cap=200.00,
        )
        cast, _std = standard_test_environment()
        app = draft_application(
            cast, destination_tier="OVERSEAS", travel_scope="OVERSEAS",
            estimated_budget=2_000.00, urgent=True,
        )
        submitted = submit_application(cast, app)
        assert submitted["required_chain"] == [
            "SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM",
        ], (
            f"PRD §3.2: urgent OVERSEAS keeps the full chain; got "
            f"{submitted['required_chain']}"
        )


# ---------------------------------------------------------------------------
# Submit pinning + ERR_NO_ACTIVE_STANDARD (PRD §3.1)
# ---------------------------------------------------------------------------
class TestSubmitStandardPinning:

    def test_submit_pins_standard_version(self, api):
        """PRD §3.1: "When an applicant later submits a travel application,
        the server pins the currently active standard version — i.e. the
        row whose half-open window [effective_from, effective_to) contains
        the moment of submit — onto the application's standard_version_pinned."

        Claim: after submit, standard_version_pinned == active standard's version.
        """
        cast, std = standard_test_environment(standard_version=7)
        app = draft_application(cast)
        submitted = submit_application(cast, app)
        assert submitted["standard_version_pinned"] == 7, (
            f"PRD §3.1: standard_version_pinned must be the active "
            f"standard's version (7); got {submitted['standard_version_pinned']}"
        )

    def test_submit_without_active_standard_rejected(self, api):
        """PRD §3.1: "If, at submit time, no such row exists for the
        applicable (city_tier, employee_level), the submit fails with
        ERR_NO_ACTIVE_STANDARD."

        Claim: applicant whose (destination_tier, employee_level) bucket
        has no standard → submit rejects with ERR_NO_ACTIVE_STANDARD.
        """
        # Bootstrap a TIER_2/STAFF standard, but route the applicant to
        # an EXECUTIVE bucket with no published standard.
        cast, _std = standard_test_environment(
            applicant_level="STAFF", destination_tier="TIER_2",
        )
        # Make the applicant EXECUTIVE (no standard published for that bucket).
        exec_emp = create_employee(
            full_name="ExecApplicant", employee_level="EXECUTIVE",
            supervisor_id=cast.supervisor["id"],
        )
        exec_headers = make_applicant_headers(exec_emp["id"])
        # DRAFT under exec applicant
        app = get_success_data(
            api.create_travel_application(
                create_travel_application_payload(
                    destination_tier="TIER_2",
                ),
                exec_headers,
            )
        )
        res = api.submit_travel_application(app["id"], exec_headers)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_STANDARD.value)


# ---------------------------------------------------------------------------
# Approval walk (PRD §3.2)
# ---------------------------------------------------------------------------
class TestApprovalWalk:

    def test_finance_terminal_approval_lands_at_approved(self, api):
        """PRD §3.2: "either FINANCE is the last step of the chain (no
        GM required), in which case the finance approval directly
        transitions the application from FINANCE_APPROVED to APPROVED."

        Claim: small DOMESTIC trip walks SUPERVISOR → FINANCE → APPROVED.
        """
        cast, approved = approved_application(
            estimated_budget=4_500.00, travel_scope="DOMESTIC",
        )
        assert approved["status"] == "APPROVED"
        assert approved["required_chain"] == ["SUPERVISOR", "FINANCE"]

    def test_gm_approval_auto_transitions_to_approved(self, api):
        """PRD §3.2: "GM is the last step, in which case the system
        auto-transitions from GM_APPROVED to APPROVED immediately after
        the GM approval lands."

        Claim: full-chain DOMESTIC trip lands at APPROVED after GM step.
        """
        cast, approved = approved_application(
            estimated_budget=50_000.00, travel_scope="DOMESTIC",
        )
        assert approved["status"] == "APPROVED"
        assert approved["required_chain"] == [
            "SUPERVISOR", "DEPT_HEAD", "FINANCE", "GM",
        ]

    def test_wrong_supervisor_rejected(self, api):
        """PRD §2.1: "When the role and endpoint match but the caller is
        not the specific approver expected at the current chain step (or
        is not the applicant's supervisor where supervisory ownership is
        required), the rejection is ERR_NOT_CURRENT_APPROVER (HTTP 403)."

        Claim: a Supervisor whose Employee.id is NOT the applicant's
        supervisor_id → ERR_NOT_CURRENT_APPROVER.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast, estimated_budget=4_500.00)
        submit_application(cast, app)
        wrong_sup = create_employee(
            full_name="WrongSup", employee_level="MANAGER",
        )
        wrong_headers = make_supervisor_headers(wrong_sup["id"])
        res = api.approve_travel_application(
            app["id"], wrong_headers, approval_payload(),
        )
        validate_error(res, ApiErrorId.ERR_NOT_CURRENT_APPROVER.value)

    def test_finance_attempts_supervisor_step_rejected(self, api):
        """PRD §2.8 priority 5 vs 6: when a non-current role calls
        approve, both ERR_INVALID_STATE (the application's status does
        not admit Finance's expected from-state SUPERVISOR_APPROVED /
        DEPT_HEAD_APPROVED) and ERR_NOT_CURRENT_APPROVER (the acting
        role is not the current chain step) are textually applicable.
        PRD §2.8 pins state-legality at priority 5 and chain-step at
        priority 6, but §3.2's race-loser text further pins ERR_INVALID_STATE
        for the analogous "wrong-from-state" scenario. PRD does not
        uniquely determine which of the two fires here for a Finance-on-
        SUBMITTED call; accept either.

        Claim: Finance issuing the SUPERVISOR-step approval on a freshly
        submitted application → one of {ERR_NOT_CURRENT_APPROVER, ERR_INVALID_STATE}.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast, estimated_budget=4_500.00)
        submit_application(cast, app)
        res = api.approve_travel_application(
            app["id"], cast.finance_headers, approval_payload(),
        )
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_NOT_CURRENT_APPROVER.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )


# ---------------------------------------------------------------------------
# Reject (PRD §3.2)
# ---------------------------------------------------------------------------
class TestReject:

    def test_supervisor_reject_terminal_state(self, api):
        """PRD §3.2: "A rejection at any chain step is a terminal move:
        an approver in the current step calls reject, supplying a
        rejection_reason, and the application transitions to REJECTED."

        Claim: SUPERVISOR-step reject transitions to REJECTED.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast, estimated_budget=4_500.00)
        submit_application(cast, app)
        rejected = validate_success(
            api.reject_travel_application(
                app["id"],
                reject_payload("Costs not justified"),
                cast.supervisor_headers,
            ),
        )
        assert rejected["status"] == "REJECTED"

    def test_reject_after_approved_invalid_state(self, api):
        """PRD §3.2: "Reject is not a valid transition out of APPROVED,
        BOOKING_LOCKED, COMPLETED, CANCELLED, or REJECTED; any such
        attempt is ERR_INVALID_STATE."

        Claim: reject on APPROVED application → ERR_INVALID_STATE.
        """
        cast, approved = approved_application(estimated_budget=4_500.00)
        res = api.reject_travel_application(
            approved["id"], reject_payload("change of mind"),
            cast.finance_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Cancel (PRD §3.2)
# ---------------------------------------------------------------------------
class TestCancel:

    def test_cancel_draft_application(self, api):
        """PRD §3.2: "The applicant may cancel the application in two
        situations: while it is still in DRAFT (a trivial cancellation,
        no preconditions other than ownership)."

        Claim: cancel on DRAFT → status=CANCELLED.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast)
        cancelled = validate_success(
            api.cancel_travel_application(app["id"], cast.applicant_headers),
        )
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_approved_without_bookings(self, api):
        """PRD §3.2: "after it has reached APPROVED but before any
        ItinerarySegment with status ACTIVE exists under it. Cancel
        from any other state (notably BOOKING_LOCKED, where bookings
        are already in place) is ERR_INVALID_STATE."

        Claim: cancel on APPROVED w/o bookings → status=CANCELLED.
        """
        cast, approved = approved_application(estimated_budget=4_500.00)
        cancelled = validate_success(
            api.cancel_travel_application(
                approved["id"], cast.applicant_headers,
            ),
        )
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_booking_locked_invalid_state(self, api):
        """PRD §3.2: "Cancel from any other state (notably BOOKING_LOCKED,
        where bookings are already in place) is ERR_INVALID_STATE."

        Claim: cancel on BOOKING_LOCKED → ERR_INVALID_STATE.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        book_segment(
            cast, approved["id"],
            segment_type="FLIGHT",
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T13:00:00.000Z",
            cost=500.00,
        )
        res = api.cancel_travel_application(
            approved["id"], cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# OCC (PRD §2.5)
# ---------------------------------------------------------------------------
class TestOptimisticConcurrency:

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.5: "When supplied, the server compares it to the
        resource's current version; a mismatch is rejected with
        ERR_VERSION_CONFLICT (HTTP 409)."

        Claim: PATCH with stale version → ERR_VERSION_CONFLICT.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast)
        stale_v = app["version"]
        # First PATCH succeeds and bumps version.
        get_success_data(
            api.patch_travel_application(
                app["id"],
                {"version": stale_v, "destination_city": "Beijing"},
                cast.applicant_headers,
            )
        )
        # Second PATCH with the original (now stale) version fails.
        res = api.patch_travel_application(
            app["id"],
            {"version": stale_v, "destination_city": "Hangzhou"},
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_without_version_skips_check(self, api):
        """PRD §2.5: "Omitting version from the request body skips the
        check entirely, and the edit proceeds."

        Claim: PATCH with no version in body proceeds without conflict.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast)
        # No version key in the body — should succeed.
        updated = validate_success(
            api.patch_travel_application(
                app["id"],
                {"destination_city": "Hangzhou"},
                cast.applicant_headers,
            ),
        )
        assert updated["destination_city"] == "Hangzhou"
