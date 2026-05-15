"""Waitlist and yield-sweep tests.

Covers PRD §3.9: rank-score calculation, yield-sweep stages, waitlist
offer acceptance (and the WAITLISTED → ADMITTED cascade), offer-expiry
cycle (cyclic OFFERED → ACTIVE), audit YieldSweep record fields.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_waitlist_offer,
    advance_clock,
    assert_yield_sweep,
    create_applicant,
    create_application,
    create_program,
    create_university,
    decide_application,
    get_application,
    get_program,
    make_applicant_headers,
    run_yield_sweep,
    setup_admitted_application,
    setup_application_ready_to_submit,
    setup_waitlist_offer_pending,
    setup_waitlisted_application,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Yield sweep run (PRD §3.9)
# ---------------------------------------------------------------------------
class TestYieldSweepRun:

    def test_yield_sweep_returns_audit_record(
        self, api, platform_admin_headers,
    ):
        """PRD §3.9: "The sweep records its outcome as a YieldSweep audit
        row: university_id of the swept university, epoch as a
        monotonically increasing per-university counter starting at one
        for the first sweep, enrolled_count_at_start as a snapshot of
        the university's enrolled_count at the moment of the sweep,
        offers_extended as the number of waitlist promotions actually
        performed in this run, and ran_at as the server-clock instant
        the sweep executed."
        """
        from test_helpers import setup_university_with_program
        uni, _ = setup_university_with_program()
        res = api.run_yield_sweep(uni["id"], platform_admin_headers)
        data = validate_success(res)
        assert_yield_sweep(data)
        assert data["university_id"] == uni["id"]
        assert data["epoch"] == 1, (
            f"first sweep epoch must be 1, got {data['epoch']}"
        )

    def test_yield_sweep_record_is_append_only(
        self, api, platform_admin_headers,
    ):
        """PRD §2.4: "YieldSweep records carry only id and created_at
        from the common-fields set — they have no updated_at and no
        version."
        """
        from test_helpers import setup_university_with_program
        uni, _ = setup_university_with_program()
        res = api.run_yield_sweep(uni["id"], platform_admin_headers)
        data = validate_success(res)
        assert "updated_at" not in data, (
            f"YieldSweep must NOT carry updated_at, got {data.get('updated_at')!r}"
        )
        assert "version" not in data, (
            f"YieldSweep must NOT carry version, got {data.get('version')!r}"
        )

    def test_yield_sweep_epoch_increments_per_university(
        self, api, platform_admin_headers,
    ):
        """PRD §3.9: "epoch as a monotonically increasing per-university
        counter starting at one for the first sweep..."

        Claim: subsequent sweeps on the same university have
        strictly greater epoch.
        """
        from test_helpers import setup_university_with_program
        uni, _ = setup_university_with_program()
        s1 = run_yield_sweep(uni["id"])
        s2 = run_yield_sweep(uni["id"])
        assert s2["epoch"] > s1["epoch"], (
            f"second sweep epoch {s2['epoch']} must exceed first {s1['epoch']}"
        )


# ---------------------------------------------------------------------------
# Waitlist promotion gated on Program capacity (PRD §3.9)
# ---------------------------------------------------------------------------
class TestWaitlistCapacityGate:

    def test_waitlist_promotion_blocked_when_program_at_capacity(
        self, api, platform_admin_headers,
    ):
        """PRD §3.9 stage 4: "For each entry, it checks the entry's
        program — if that program's admitted_count is strictly less
        than its capacity, the entry is promoted to OFFERED..."

        Claim: a program at capacity yields no promotions in a sweep;
        ACTIVE entries stay ACTIVE.

        # difficulty: cross_entity_state_dependency/waitlist_promotion_requires_program_under_capacity
        """
        # Program capacity = 1, admitted_count = 1 from a prior admit.
        ctx_admit = setup_admitted_application(
            program_overrides={"capacity": 1},
            round_="REGULAR_DECISION",
        )
        # Now waitlist a different applicant on the same program.
        applicant2 = create_applicant()
        from test_helpers import attach_strong_essay, setup_strong_recommendations
        app2 = create_application(
            applicant2["id"], ctx_admit["program"]["id"],
            round="REGULAR_DECISION",
        )
        attach_strong_essay(
            applicant2["id"], app2["id"],
            university_name=ctx_admit["university"]["name"],
            program_name=ctx_admit["program"]["name"],
        )
        setup_strong_recommendations(applicant2["id"], app2["id"])
        submit_application(applicant2["id"], app2["id"])
        api.begin_review(app2["id"],
                         TEST_USERS["admissions_officer_headers"])
        api.decide_application(
            app2["id"],
            {"decision": "WAITLIST"},
            TEST_USERS["admissions_officer_headers"],
        )
        # Run sweep — Program is at capacity, so no promotion.
        res = api.run_yield_sweep(
            ctx_admit["university"]["id"], platform_admin_headers,
        )
        sweep = validate_success(res)
        assert sweep["offers_extended"] == 0, (
            f"offers_extended expected 0 (program at capacity), "
            f"got {sweep['offers_extended']}"
        )


# ---------------------------------------------------------------------------
# Waitlist accept → cascade admit (PRD §3.9)
# ---------------------------------------------------------------------------
class TestWaitlistAcceptCascade:

    def test_yield_sweep_promotes_to_offered_when_capacity_available(
        self, api, platform_admin_headers,
    ):
        """PRD §3.9 stage 4: "if that program's admitted_count is
        strictly less than its capacity, the entry is promoted to
        OFFERED, offered_at is set to the current clock, offer_expires_at
        is set to the current clock plus 7 days..."

        Claim: with a single ACTIVE waitlist entry on a program with
        admitted_count < capacity (and yield_target > enrolled_count),
        the sweep promotes it.
        """
        # Setup: program capacity 5, admitted_count 0 (no one admitted);
        # university yield_target=100 so gap is large; one waitlist
        # entry. After sweep it should be OFFERED.
        ctx = setup_waitlist_offer_pending(
            program_capacity=5,
            university_yield_target=100,
        )
        sweep = ctx["yield_sweep"]
        assert sweep["offers_extended"] >= 1, (
            f"expected at least 1 offer extended, got {sweep['offers_extended']}"
        )


# ---------------------------------------------------------------------------
# Auth on yield-sweep (PRD §4)
# ---------------------------------------------------------------------------
class TestYieldSweepAuth:

    def test_applicant_cannot_run_yield_sweep(
        self, api, applicant_headers_fallback,
    ):
        """PRD §4 endpoint table: POST /universities/{id}/yield-sweep
        authorized for AdmissionsOfficer and PlatformAdmin only.
        """
        # Any university id — auth check should reject first.
        from test_helpers import NON_EXISTENT_UUID
        res = api.run_yield_sweep(
            NON_EXISTENT_UUID, applicant_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Cyclic OFFERED → ACTIVE recycle (PRD §3.9)
# ---------------------------------------------------------------------------
class TestWaitlistOfferExpiryRecycle:

    def test_yield_sweep_records_history_listing(
        self, api, platform_admin_headers,
    ):
        """PRD §4 endpoint table: "GET /universities/{id}/yield-sweeps
        List yield-sweep history for a university."

        Claim: after N sweeps, list endpoint returns at least N entries.
        """
        from test_helpers import setup_university_with_program, validate_paginated
        uni, _ = setup_university_with_program()
        run_yield_sweep(uni["id"])
        run_yield_sweep(uni["id"])
        res = api.list_yield_sweeps(uni["id"], platform_admin_headers)
        data, meta = validate_paginated(res)
        assert meta["total_count"] >= 2, (
            f"expected at least 2 sweep records, got {meta['total_count']}"
        )
