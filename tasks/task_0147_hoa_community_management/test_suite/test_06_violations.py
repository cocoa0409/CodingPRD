"""Violations and the tiered fine schedule — PRD §3.5.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    VIOLATION_CURE_WINDOW_DAYS,
    advance_clock_by_seconds,
    advance_clock_to,
    assert_violation,
    create_violation_payload,
    get_member,
    get_violation,
    open_violation,
    parse_iso,
    setup_single_unit_roster,
    TEST_USERS,
    validate_error,
    validate_success,
    version_payload,
    cure_violation,
)


class TestViolationOpen:

    def test_secretary_opens_violation_returns_open_with_index_one(self, api):
        """PRD §3.5: "The occurrence_index is a 1-based counter scoped
        to the unit ... The index drives the fine schedule: occurrence
        1 is a warning with fine_cents = 0".

        Claim: a freshly opened violation on a unit with no prior
        violations has occurrence_index=1, fine_cents=0, status=OPEN.
        """
        _member, unit = setup_single_unit_roster()
        resp = api.create_violation(
            create_violation_payload(unit_id=unit["id"]),
            TEST_USERS["secretary_role_headers"],
        )
        body = validate_success(resp, expected_status=201)
        assert_violation(body)
        assert body["status"] == "OPEN"
        assert body["occurrence_index"] == 1
        assert body["fine_cents"] == 0

    def test_cure_deadline_is_opened_at_plus_14_days(self, api):
        """PRD §3.5: "computes cure_deadline = opened_at + 14 days".

        Claim: cure_deadline - opened_at == 14 days exactly.
        """
        _member, unit = setup_single_unit_roster()
        v = open_violation(unit["id"])
        delta = parse_iso(v["cure_deadline"]) - parse_iso(v["opened_at"])
        assert delta == timedelta(days=14), (
            f"cure_deadline must be opened_at+14d per PRD §3.5; got "
            f"delta={delta}"
        )


class TestViolationCure:

    def test_cure_before_deadline_transitions_to_cured(self, api):
        """PRD §3.5: "The SecretaryRole may mark the violation CURED at
        any instant on or before cure_deadline; the cure leaves
        fine_cents at zero and refreshes updated_at."

        Claim: POST /cure on an OPEN violation within the cure window
        returns status=CURED, fine_cents=0.
        """
        _member, unit = setup_single_unit_roster()
        v = open_violation(unit["id"])
        resp = api.cure_violation(
            v["id"], version_payload(v.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        body = validate_success(resp, expected_status=200)
        assert body["status"] == "CURED"
        assert body["fine_cents"] == 0


class TestViolationAutoFineSchedule:

    def test_occurrence_two_auto_fine_is_5000_cents(self, api):
        """PRD §3.5: "occurrence 2 is a 5,000-cent fine".

        Claim: a second violation on a unit (with one prior CURED) that
        auto-FINES posts fine_cents=5000.
        """
        member, unit = setup_single_unit_roster()
        # First violation: cure it so occurrence_index=2 for the next.
        v1 = open_violation(unit["id"])
        cure_violation(v1)
        # Second violation: let it auto-fine.
        advance_clock_by_seconds(2)
        v2 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v2["cure_deadline"]) + timedelta(seconds=1),
        )
        v2_after = get_violation(v2["id"])
        assert v2_after["status"] == "FINED", (
            f"V2 must auto-FINE past cure_deadline; got "
            f"{v2_after['status']}"
        )
        assert v2_after["fine_cents"] == 5000, (
            f"PRD §3.5 schedule: occurrence 2 == 5000; got "
            f"{v2_after['fine_cents']}"
        )

    def test_occurrence_four_or_higher_auto_fine_is_20000_cents(self, api):
        """PRD §3.5: "occurrence 4 or higher is a 20,000-cent fine".

        Claim: a fourth violation auto-FINEs with fine_cents=20000.
        """
        member, unit = setup_single_unit_roster()
        # Three prior CURED so the fourth is occurrence_index=4.
        for _ in range(3):
            v = open_violation(unit["id"])
            cure_violation(v)
            advance_clock_by_seconds(1)
        # Fourth violation auto-fines.
        v4 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v4["cure_deadline"]) + timedelta(seconds=1),
        )
        v4_after = get_violation(v4["id"])
        assert v4_after["status"] == "FINED"
        assert v4_after["fine_cents"] == 20000, (
            f"PRD §3.5: occurrence 4 or higher is 20000; got "
            f"{v4_after['fine_cents']}"
        )


class TestViolationFinedRecomputesMemberOverdue:

    def test_auto_fined_violation_raises_member_total_overdue_by_fine(self, api):
        """PRD §3.5: "transitions any still-OPEN violation to FINED,
        sets fine_cents to the schedule value for the violation's
        occurrence_index, and recomputes the owner's
        Member.total_overdue_amount_cents."

        Claim: after a violation auto-FINEs with fine_cents=5000, the
        owner's total_overdue_amount_cents increases by exactly 5000
        relative to the pre-fine snapshot.
        """
        member, unit = setup_single_unit_roster()
        v1 = open_violation(unit["id"])
        cure_violation(v1)
        advance_clock_by_seconds(2)
        # Snapshot before V2 auto-fines.
        m_before = get_member(member["id"])
        before = m_before["total_overdue_amount_cents"]
        # Open and auto-fine V2 (occurrence 2 → 5000).
        v2 = open_violation(unit["id"])
        advance_clock_to(
            parse_iso(v2["cure_deadline"]) + timedelta(seconds=1),
        )
        m_after = get_member(member["id"])
        assert m_after["total_overdue_amount_cents"] == before + 5000, (
            f"Member.total_overdue must rise by 5000 (V2 fine) per PRD "
            f"§3.5; got {m_after['total_overdue_amount_cents']} after "
            f"{before}"
        )
