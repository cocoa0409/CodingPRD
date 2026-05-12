"""Objection lifecycle: filing, uphold (revise allocation), reject (revert).

PRD references:
  - §3.2 Allocation Computation, Publication, and Objection
  - §2.9 Concurrency: ERR_OBJECTION_ALREADY_PENDING
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    create_enterprise,
    file_objection_payload,
    get_cycle,
    make_enterprise_headers,
    setup_published_cycle,
    setup_published_cycle_multi,
    uphold_objection_payload,
    validate_error,
    validate_success,
)


def _file_objection_for(api, allocation_id, filer_enterprise_id):
    return api.file_objection(
        allocation_id,
        file_objection_payload(filer_enterprise_id=filer_enterprise_id),
        make_enterprise_headers(filer_enterprise_id),
    )


# ===========================================================================
# §3.2 — Filing an objection
# ===========================================================================
class TestObjectionFile:
    def test_file_objection_transitions_allocation_to_objected(self, api):
        """PRD §3.2: 'A successful filing creates the objection in status
        PENDING with filed_at set to the current time and resolved_at
        null, and transitions the allocation from PUBLISHED to OBJECTED.'

        Claim: file_objection -> Objection.status=PENDING and
        Allocation.status=OBJECTED.
        """
        ent, cyc, alloc = setup_published_cycle()
        res = _file_objection_for(api, alloc["id"], ent["id"])
        obj = validate_success(res, expected_status=201)
        assert obj["status"] == "PENDING"
        assert obj.get("resolved_at") is None
        # Re-fetch the allocation via the cycle.
        cyc2 = get_cycle(cyc["id"])
        a = next(x for x in (cyc2.get("allocations") or [])
                 if x["id"] == alloc["id"])
        assert a["status"] == "OBJECTED"

    def test_file_objection_by_non_owner_rejected(self, api):
        """PRD §3.2: 'The filing is permitted only when the current time is
        before the parent cycle's objection deadline and when
        filer_enterprise_id equals the allocation's enterprise_id;
        otherwise the request is rejected with ERR_WINDOW_CLOSED or
        ERR_OWNERSHIP_VIOLATION respectively.'

        Claim: a different enterprise filing on someone else's allocation
        -> ERR_OWNERSHIP_VIOLATION.
        """
        ent, cyc, alloc = setup_published_cycle()
        intruder = create_enterprise()
        # The acting principal claims to be the intruder; both X-User-ID
        # and the body's filer_enterprise_id are intruder.
        res = api.file_objection(
            alloc["id"],
            file_objection_payload(filer_enterprise_id=intruder["id"]),
            make_enterprise_headers(intruder["id"]),
        )
        validate_error(res, "ERR_OWNERSHIP_VIOLATION")

    def test_file_objection_after_deadline_rejected(self, api):
        """PRD §3.2: 'The filing is permitted only when the current time is
        before the parent cycle's objection deadline ... otherwise the
        request is rejected with ERR_WINDOW_CLOSED or
        ERR_OWNERSHIP_VIOLATION respectively.'

        Claim: filing after objection_deadline -> ERR_WINDOW_CLOSED.
        """
        ent, cyc, alloc = setup_published_cycle()
        advance_clock(add_seconds(cyc["objection_deadline"], 1))
        res = _file_objection_for(api, alloc["id"], ent["id"])
        validate_error(res, "ERR_WINDOW_CLOSED")

    def test_second_pending_objection_rejected(self, api):
        """PRD §3.2: 'At most one objection per allocation may be in
        PENDING state at a time; a second filing is rejected with
        ERR_OBJECTION_ALREADY_PENDING.'

        Claim: a second objection on the same allocation while the first
        is PENDING -> ERR_OBJECTION_ALREADY_PENDING.
        """
        ent, cyc, alloc = setup_published_cycle()
        first = _file_objection_for(api, alloc["id"], ent["id"])
        validate_success(first, expected_status=201)
        second = _file_objection_for(api, alloc["id"], ent["id"])
        validate_error(second, "ERR_OBJECTION_ALREADY_PENDING")


# ===========================================================================
# §3.2 — Uphold / Reject lifecycle
# ===========================================================================
class TestObjectionResolve:
    def test_uphold_revises_allocation_quotas(self, api, regulator_headers):
        """PRD §3.2: 'Upholding requires a revised_total_quota in the
        request body. The objection moves to UPHELD with resolved_at set
        to the current time, and the allocation transitions from OBJECTED
        to REVISED with its quota recomputed: the new free_quota is the
        revised total multiplied by the cycle's free-paid ratio (rounded
        half-up to two decimal places), the new paid_quota is the revised
        total minus the new free quota, and total_quota is updated to the
        revised value.'

        Claim: after uphold with revised_total_quota=1200,
        Allocation.status=REVISED, total_quota=1200.00,
        free_quota=960.00 (=1200*0.80), paid_quota=240.00 (=1200-960).
        """
        ent, cyc, alloc = setup_published_cycle(
            free_paid_ratio=0.80, ccer_cap_pct=0.05,
            method="INDUSTRY_BENCHMARK",
            activity_volume=1000.00, benchmark_factor=1.50,
        )
        filed = _file_objection_for(api, alloc["id"], ent["id"])
        obj = validate_success(filed, expected_status=201)
        res = api.uphold_objection(
            obj["id"],
            uphold_objection_payload(revised_total_quota=1200.00),
            regulator_headers,
        )
        upheld = validate_success(res, expected_status=200)
        assert upheld["status"] == "UPHELD"
        assert upheld.get("resolved_at") is not None
        cyc2 = get_cycle(cyc["id"])
        a = next(x for x in (cyc2.get("allocations") or [])
                 if x["id"] == alloc["id"])
        assert a["status"] == "REVISED"
        assert a["total_quota"] == pytest.approx(1200.00, abs=0.01)
        assert a["free_quota"] == pytest.approx(960.00, abs=0.01)
        assert a["paid_quota"] == pytest.approx(240.00, abs=0.01)

    def test_reject_returns_allocation_to_published(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'Rejecting an objection takes no body, sets the
        objection to REJECTED with resolved_at set to the current time,
        and returns the allocation from OBJECTED back to PUBLISHED.'

        Claim: reject -> Objection.status=REJECTED, Allocation.status
        returns to PUBLISHED.
        """
        ent, cyc, alloc = setup_published_cycle()
        filed = _file_objection_for(api, alloc["id"], ent["id"])
        obj = validate_success(filed, expected_status=201)
        res = api.reject_objection(obj["id"], regulator_headers)
        rejected = validate_success(res, expected_status=200)
        assert rejected["status"] == "REJECTED"
        assert rejected.get("resolved_at") is not None
        cyc2 = get_cycle(cyc["id"])
        a = next(x for x in (cyc2.get("allocations") or [])
                 if x["id"] == alloc["id"])
        assert a["status"] == "PUBLISHED"
