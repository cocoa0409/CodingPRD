"""Cross-entity cascades, dismissal cascade, SoL hard boundary, sweeps,
OCC.

PRD §2.6, §2.10, §3.3 (dismissal cascade), §3.6 (sweep), §3.7
(LITIGATION cascade).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_clock_seconds,
    advance_clock_to_iso,
    create_court_event,
    create_offer,
    dismiss_case,
    get_case,
    iso_utc,
    parse_iso_date,
    patch_damages_payload,
    server_now_dt,
    setup_demand_sent,
    setup_negotiating,
    setup_negotiating_with_two_pending_offers,
    setup_ready_for_demand,
    setup_records_pending,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDismissalCascade:

    def test_dismiss_cancels_open_record_requests(self, api):
        """PRD §3.3: "A case that is dismissed by a ManagingPartner
        while still in INTAKE, RECORDS_PENDING, or READY_FOR_DEMAND
        cascades through every open medical-record request still in
        DRAFT or SENT and flips each to CANCELED; the case itself
        moves to DISMISSED."

        Claim: After dismiss, the DRAFT record request is CANCELED.
        """
        _, case, _, request = setup_records_pending()
        dismiss_case(case["id"])
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "DISMISSED"
        # List records to inspect cascade.
        resp = api_client.list_medical_record_requests(
            case["id"], TEST_USERS["paralegal_headers"],
        )
        data, _ = validate_paginated(resp)
        by_id = {r["id"]: r for r in data}
        assert by_id[request["id"]]["status"] == "CANCELED", (
            "PRD §3.3: dismissal cascade must flip open requests to "
            "CANCELED"
        )

    def test_operations_on_dismissed_case_return_case_closed(
        self, api, paralegal_headers,
    ):
        """PRD §3.3: "Operations against a case whose status is already
        DISMISSED or CLOSED are rejected with ERR_CASE_CLOSED."

        Claim: Attempting to create a new record request on a
        DISMISSED case → ERR_CASE_CLOSED.
        """
        _, case, _, _ = setup_records_pending()
        dismiss_case(case["id"])
        from test_helpers import create_medical_record_request_payload
        resp = api.create_medical_record_request(
            case["id"],
            create_medical_record_request_payload(),
            paralegal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_CLOSED.value)


class TestLitigationCascade:

    def test_complaint_filed_in_negotiating_withdraws_pending_offers(
        self, api,
    ):
        """PRD §3.7: "If the case is in NEGOTIATING with at least one
        offer of any round on file and the sol_deadline is still in
        the future, filing the complaint cascades every offer still
        in PENDING to WITHDRAWN, flips Case.filed_in_court to true,
        and advances the case from NEGOTIATING to LITIGATION."

        Claim: After COMPLAINT_FILED in NEGOTIATING:
        - Case.status == LITIGATION
        - Case.filed_in_court == true
        - The previously-PENDING offer is now WITHDRAWN.
        """
        chain = setup_negotiating_with_two_pending_offers()
        # o3 is currently PENDING (o1 COUNTERED, o2 COUNTERED).
        now_dt = server_now_dt()
        create_court_event(
            chain["case"]["id"], "COMPLAINT_FILED",
            scheduled_at=iso_utc(now_dt + timedelta(days=14)),
            duration_minutes=30,
        )
        refreshed = get_case(chain["case"]["id"])
        assert refreshed["status"] == "LITIGATION"
        assert refreshed["filed_in_court"] is True
        # Re-fetch offers
        resp = api_client.list_settlement_offers(
            chain["case"]["id"], TEST_USERS["attorney_headers"],
        )
        data, _ = validate_paginated(resp)
        by_id = {o["id"]: o for o in data}
        # o3 was PENDING → must now be WITHDRAWN.
        assert by_id[chain["o3"]["id"]]["status"] == "WITHDRAWN"
        # o1/o2 were COUNTERED → unchanged (NOT WITHDRAWN).
        assert by_id[chain["o1"]["id"]]["status"] == "COUNTERED"
        assert by_id[chain["o2"]["id"]]["status"] == "COUNTERED"


class TestSolHardBoundary:

    def test_send_demand_at_exact_midnight_blocked(self, api):
        """PRD §2.10: "from the instant the server's current time
        reaches or passes sol_deadline, every state-advancing mutation
        on the case is blocked with ERR_STATUTE_OF_LIMITATIONS_EXPIRED
        (HTTP 422). The comparison is inclusive on the boundary — a
        request that arrives at exactly the deadline is already too
        late."

        Claim: At now() == sol_deadline midnight, send-demand →
        ERR_STATUTE_OF_LIMITATIONS_EXPIRED.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        from test_helpers import create_demand_letter
        letter = create_demand_letter(case["id"], damages["total_damages_cents"])
        sol_iso = f"{case['sol_deadline']}T00:00:00.000Z"
        advance_clock_to_iso(sol_iso)
        resp = api.send_demand_letter(
            case["id"], letter["id"],
            TEST_USERS["attorney_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_STATUTE_OF_LIMITATIONS_EXPIRED.value,
        )


class TestSolSweep:

    def test_sweep_dismisses_out_of_statute_case(
        self, api, managing_partner_headers,
    ):
        """PRD §2.10: "A daily statute sweep run by a ManagingPartner
        examines every non-terminal case and, for any case whose
        sol_deadline is on or before the current server time, flips
        that case's status to DISMISSED".

        Claim: After advancing clock past sol_deadline, the sweep
        flips the case to DISMISSED.
        """
        _, case, _, _ = setup_records_pending()
        sol_iso = f"{case['sol_deadline']}T00:00:00.000Z"
        advance_clock_to_iso(sol_iso)
        resp = api_client.sweep_sol(managing_partner_headers)
        validate_success(resp)
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "DISMISSED"


class TestOccVersionConflict:

    def test_patch_with_wrong_version_returns_version_mismatch(
        self, api,
    ):
        """PRD §2.4: "Clients may include version in the request body
        to assert the version they expect to be updating; if the
        supplied version does not equal the stored version, the
        request is rejected with ERR_VERSION_MISMATCH (HTTP 409)."

        Claim: PATCH /costs with mismatched version →
        ERR_VERSION_MISMATCH.
        """
        from test_helpers import setup_case_with_fee, patch_case_costs
        _, case, _ = setup_case_with_fee()
        # First bump
        patch_case_costs(case["id"], 100_000)
        # Now case_costs are 100_000 and case.version is at least 2.
        # Send a stale version.
        from test_helpers import case_costs_payload
        resp = api.patch_case_costs(
            case["id"],
            case_costs_payload(200_000, version=case["version"]),
            TEST_USERS["attorney_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_patch_without_version_skips_occ_check(self, api):
        """PRD §2.4: "Omitting version from the body skips the
        concurrency check entirely and the patch proceeds against
        whatever the current stored row is."

        Claim: PATCH /costs without version succeeds even after a
        prior bump.
        """
        from test_helpers import setup_case_with_fee, patch_case_costs
        _, case, _ = setup_case_with_fee()
        patch_case_costs(case["id"], 100_000)
        # No version supplied — should succeed.
        from test_helpers import case_costs_payload
        resp = api.patch_case_costs(
            case["id"], case_costs_payload(200_000),
            TEST_USERS["attorney_headers"],
        )
        validate_success(resp)


class TestCaseCostsAppendOnly:

    def test_costs_decrease_rejected(self, api):
        """PRD §3.9: "Case costs are append-only: a patch whose new
        value is strictly less than the stored value is rejected with
        ERR_COSTS_DECREASE_NOT_ALLOWED".

        Claim: PATCH /costs with new < old → ERR_COSTS_DECREASE_NOT_ALLOWED.
        """
        from test_helpers import setup_case_with_fee, patch_case_costs
        _, case, _ = setup_case_with_fee()
        patch_case_costs(case["id"], 500_000)
        # Attempt to decrease.
        from test_helpers import case_costs_payload
        resp = api.patch_case_costs(
            case["id"], case_costs_payload(400_000),
            TEST_USERS["attorney_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_COSTS_DECREASE_NOT_ALLOWED.value,
        )

    def test_costs_equal_old_value_accepted(self, api):
        """PRD §3.9: "a patch whose new value is greater than or equal
        to the stored value updates the row and bumps its version."

        Claim: PATCH /costs with new == old → accepted (version bumps).
        """
        from test_helpers import setup_case_with_fee, patch_case_costs
        _, case, _ = setup_case_with_fee()
        first = patch_case_costs(case["id"], 500_000)
        # Equal value should still succeed.
        from test_helpers import case_costs_payload
        resp = api.patch_case_costs(
            case["id"], case_costs_payload(500_000),
            TEST_USERS["attorney_headers"],
        )
        result = validate_success(resp)
        assert result["case_costs_cents"] == 500_000
