"""Optimistic concurrency, race-condition outcomes.

PRD §2.5 (OCC version check + race outcomes for route, issue, claim
creation, prescription edit).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_exactly_one_succeeds,
    create_prescription,
    make_physician_headers,
    occ_payload,
    patch_prescription_payload,
    re_get_consult,
    route_consult_payload,
    run_race,
    setup_in_progress_consult,
    setup_routed_consult,
    setup_two_routes_for_concurrency,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.5 OCC — version conflict
# ===========================================================================
class TestOptimisticConcurrencyControl:
    """PRD §2.5: "When version is supplied and it does not equal the
    resource's current version, the request is rejected with
    ERR_VERSION_CONFLICT."""

    def test_stale_version_on_route_rejected(self, api):
        """PRD §2.5: "When version is supplied and it does not equal the
        resource's current version, the request is rejected with
        ERR_VERSION_CONFLICT."

        Claim: routing with an out-of-date version returns
        ERR_VERSION_CONFLICT.
        """
        physician, _, consult = setup_two_routes_for_concurrency()
        # Send a clearly stale version.
        res = api.route_consult(
            consult["id"],
            route_consult_payload(
                physician_id=physician["id"],
                version=consult["version"] + 99,
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_stale_version_on_prescription_patch_rejected(self, api):
        """PRD §2.5: "Any endpoint that mutates a resource accepts an
        optional version field in its request body. When version is
        supplied and it does not equal the resource's current version,
        the request is rejected with ERR_VERSION_CONFLICT."

        Claim: PATCH /prescriptions/{id} with a stale version returns
        ERR_VERSION_CONFLICT.
        """
        physician, _, _, consult = setup_in_progress_consult()
        rx = create_prescription(
            consult=consult, physician=physician,
            dea_schedule="NONE", days_supply=15, refills=0,
        )
        res = api.patch_prescription(
            rx["id"],
            patch_prescription_payload(
                days_supply=20,
                version=rx["version"] + 99,
            ),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_omitted_version_skips_check(self, api):
        """PRD §2.5: "When version is omitted, the check is skipped and
        the mutation proceeds against whatever version the resource
        currently holds".

        Claim: PATCH without a version field succeeds against current
        state.
        """
        physician, _, _, consult = setup_in_progress_consult()
        rx = create_prescription(
            consult=consult, physician=physician,
            dea_schedule="NONE", days_supply=15, refills=0,
        )
        # No `version` in payload.
        res = api.patch_prescription(
            rx["id"],
            patch_prescription_payload(days_supply=20),
            make_physician_headers(physician["id"]),
        )
        data = validate_success(res, 200)
        assert data["days_supply"] == 20


# ===========================================================================
# §2.5 Race conditions — exactly-one-winner semantics
# ===========================================================================
class TestRaceConditions:
    """PRD §2.5: "exactly one wins: two simultaneous attempts to route
    the same REQUESTED consult serialize so that the first succeeds and
    the second receives ERR_INVALID_STATE because the consult is no
    longer REQUESTED.\""""

    def test_two_routes_serialize_one_wins(self, api):
        """PRD §2.5: "two simultaneous attempts to route the same
        REQUESTED consult serialize so that the first succeeds and the
        second receives ERR_INVALID_STATE because the consult is no
        longer REQUESTED."

        Claim: exactly one of two concurrent /route calls succeeds; the
        other fails (we do not pin the loser's specific error_id beyond
        what PRD §2.5 says — ERR_INVALID_STATE).
        """
        physician, _, consult = setup_two_routes_for_concurrency()
        headers = TEST_USERS["compliance_officer_headers"]

        def call_route():
            return api.route_consult(
                consult["id"],
                route_consult_payload(physician_id=physician["id"]),
                headers,
            )

        result_a, result_b = run_race(call_route, call_route)
        outcome = assert_exactly_one_succeeds(result_a, result_b)
        # PRD §2.5 names the loser's error_id explicitly.
        loser = outcome["failures"][0]
        assert loser.json()["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"PRD §2.5: race loser on /route must see "
            f"ERR_INVALID_STATE; got "
            f"{loser.json()['data']['error_id']!r}"
        )

    def test_two_issues_on_same_draft_serialize(self, api):
        """PRD §2.5: "two simultaneous attempts to issue the same DRAFT
        prescription serialize so that the first succeeds and the
        second sees ERR_INVALID_STATE".

        Claim: exactly one of two concurrent /issue calls on the same
        DRAFT prescription succeeds; the other fails with
        ERR_INVALID_STATE.
        """
        physician, _, _, consult = setup_in_progress_consult()
        rx = create_prescription(
            consult=consult, physician=physician,
            dea_schedule="NONE", days_supply=15, refills=0,
        )
        headers = make_physician_headers(physician["id"])

        def call_issue():
            return api.issue_prescription(rx["id"], occ_payload(), headers)

        result_a, result_b = run_race(call_issue, call_issue)
        outcome = assert_exactly_one_succeeds(result_a, result_b)
        loser = outcome["failures"][0]
        assert loser.json()["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"PRD §2.5: race loser on /issue must see "
            f"ERR_INVALID_STATE; got "
            f"{loser.json()['data']['error_id']!r}"
        )
