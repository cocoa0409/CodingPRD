"""Liens — PRD §3.6.

Covers: lien creation thresholds, cooling-off, record, release.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock_by_days,
    advance_clock_to,
    create_lien_for_unit,
    get_lien,
    parse_iso,
    setup_issued_cycle,
    setup_single_unit_roster,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestLienCreationGate:

    def test_lien_creation_below_overdue_threshold_returns_invalid_state(
        self, api, secretary_role_headers,
    ):
        """PRD §3.6: "The creation is admitted only when the unit
        owner's Member.total_overdue_amount_cents is at least 180,000
        cents (eighteen hundred dollars)".

        Claim: a unit whose owner has total_overdue==0 cannot have a
        lien created on it; the rejection uses ERR_INVALID_STATE per
        PRD §2.7 (state-precondition check on POST /hoa/liens).
        """
        _member, unit = setup_single_unit_roster()
        # Owner has 0 overdue and no aged-overdue charge.
        resp = api.create_lien(
            {"unit_id": unit["id"]}, secretary_role_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestLienCoolingOff:

    def test_record_before_30d_cooling_off_returns_lien_cooling_off(
        self, api, president_role_headers,
    ):
        """PRD §3.6: "the elapsed time between the lien's created_at
        and the current instant MUST be at least 30 days; a recordation
        attempted before that point is rejected with
        ERR_LIEN_COOLING_OFF (HTTP 409)".

        Claim: when a lien exists in NOTICE_SENT but only a few days
        have elapsed since its created_at, POST /record returns
        ERR_LIEN_COOLING_OFF — and PRD §3.6 makes this take precedence
        over the resolution and overdue-threshold checks.

        To set up a NOTICE_SENT lien that's freshly created, we need to
        already have the unit owner over 180000 cents and a charge that
        has been OVERDUE >= 60d at the moment of lien creation. We use
        a large levy and advance 60+ days past due_date so the late-
        fee accrual is satisfied, then create the lien; the test then
        attempts to record without further clock advance.
        """
        from test_helpers import (
            current_clock, advance_clock_to, get_member,
        )
        # Set up: levy large enough that principal alone is well over
        # 180000 even before late fees (so threshold is satisfied).
        member, unit, cycle = setup_issued_cycle(
            total_levy_cents=200_000,  # already over 180k
        )
        # Advance to due+60d so a charge has been OVERDUE >= 60 days.
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=61))
        # Verify the owner is over threshold before creating the lien.
        m = get_member(member["id"])
        assert m["total_overdue_amount_cents"] >= 180_000, (
            f"setup precondition: owner overdue must be >= 180000; got "
            f"{m['total_overdue_amount_cents']}"
        )
        # Create the lien NOW — created_at == current clock.
        lien = create_lien_for_unit(unit["id"])
        # Try to record immediately — only 0 days have elapsed.
        # No PASSED resolution yet either; PRD §3.6 explicitly says
        # cooling-off takes precedence over later checks. So even with
        # a bogus resolution_id we should hit ERR_LIEN_COOLING_OFF.
        resp = api.record_lien(
            lien["id"],
            {
                "resolution_id": NON_EXISTENT_UUID,
                "version": lien.get("version", 1),
            },
            president_role_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LIEN_COOLING_OFF.value)


class TestLienListPagination:

    def test_list_liens_with_default_pagination(
        self, api, president_role_headers,
    ):
        """PRD §2.3 + PRD §4: "GET /hoa/liens" — paginated list.

        Claim: list endpoint returns the standard paginated envelope.
        """
        from test_helpers import validate_paginated
        resp = api.list_liens(president_role_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "total_count" in meta
        assert "has_more" in meta


class TestLienFiltering:

    def test_list_liens_with_status_filter(
        self, api, president_role_headers,
    ):
        """PRD §4: "GET /hoa/liens — List liens with optional unit_id
        and status filters; paginated".

        Claim: passing ?status=RECORDED narrows total_count to liens in
        that status (we accept zero results — the focus is on the
        endpoint surfacing a filter parameter without erroring).
        """
        from test_helpers import validate_paginated
        resp = api.list_liens(
            president_role_headers, params={"status": "RECORDED"},
        )
        data, meta = validate_paginated(resp)
        for lien in data:
            assert lien.get("status") == "RECORDED", (
                f"filter status=RECORDED returned a lien with "
                f"status={lien.get('status')}"
            )
