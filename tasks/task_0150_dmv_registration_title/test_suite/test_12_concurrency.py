"""Race-condition tests for the concurrency rules PRD §3.8 declares
with PRD-pinned outcomes.

PRD §3.8 explicitly defines the loser-state for each declared race.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_lien_on_title,
    create_owner,
    create_vehicle,
    get_plate,
    get_vehicle,
    issue_plate_payload,
    make_plate_issuer_headers,
    make_tax_assessor_headers,
    mark_paid,
    random_plate_number,
    release_lien_payload,
    run_race,
    setup_application_at_tax_assessed,
    setup_application_completed_titled,
    validate_error_is_one_of,
)


class TestPlateIssueRace:

    def test_two_issuances_same_application_one_wins(self, api):
        """PRD §3.8: "Two PlateIssuer operators attempting to issue
        plates against the same TAX_ASSESSED application serialize on
        the application row: exactly one issuance succeeds, and the
        loser sees the state already advanced and is rejected with
        ERR_INVALID_STATE."
        """
        base = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("tax-op-race-001"),
        )
        mark_paid(base["owner"]["id"], base["application"]["id"])
        # Two distinct PlateIssuer operators, two distinct plate numbers.
        h_a = make_plate_issuer_headers("plate-op-race-A-001")
        h_b = make_plate_issuer_headers("plate-op-race-B-001")
        plate_a = random_plate_number(7)
        plate_b = random_plate_number(7)
        results = run_race(
            lambda: api.issue_plate(
                base["application"]["id"],
                issue_plate_payload(plate_number=plate_a), h_a,
            ),
            lambda: api.issue_plate(
                base["application"]["id"],
                issue_plate_payload(plate_number=plate_b), h_b,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD pins loser → ERR_INVALID_STATE.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestPlateNumberRace:

    def test_two_issuances_same_plate_number_one_wins(self, api):
        """PRD §3.8: "Two simultaneous issuances that both name the
        same plate_number serialize on the plate-number uniqueness
        constraint: the second is rejected with ERR_PLATE_NUMBER_TAKEN."
        """
        # Two distinct applications, both at TAX_ASSESSED with paid
        # marked, race to claim the same plate_number.
        base_a = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("tax-op-num-race-A"),
        )
        mark_paid(base_a["owner"]["id"], base_a["application"]["id"])
        base_b = setup_application_at_tax_assessed(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_headers=make_tax_assessor_headers("tax-op-num-race-B"),
        )
        mark_paid(base_b["owner"]["id"], base_b["application"]["id"])
        shared_plate = random_plate_number(7)
        h_a = make_plate_issuer_headers("plate-op-num-race-A")
        h_b = make_plate_issuer_headers("plate-op-num-race-B")
        results = run_race(
            lambda: api.issue_plate(
                base_a["application"]["id"],
                issue_plate_payload(plate_number=shared_plate), h_a,
            ),
            lambda: api.issue_plate(
                base_b["application"]["id"],
                issue_plate_payload(plate_number=shared_plate), h_b,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_PLATE_NUMBER_TAKEN.value],
        )


class TestLienReleaseRace:

    def test_two_lien_releases_one_wins(self, api):
        """PRD §3.6: "Two clerks releasing the same lien at the same
        time serialize at the row level: exactly one release wins and
        the loser receives ERR_LIEN_ALREADY_RELEASED once it observes
        that the record's status has already become RELEASED."
        """
        base = setup_application_completed_titled(
            application_type="INITIAL_REGISTRATION",
            tax_assessor_operator_id="tax-op-lien-race-001",
            plate_issuer_operator_id="plate-op-lien-race-001",
        )
        vehicle = get_vehicle(base["vehicle"]["id"])
        lien = create_lien_on_title(vehicle["current_title_id"])
        results = run_race(
            lambda: api.release_lien(
                lien["id"], release_lien_payload(release_reference="REL-A"),
                TEST_USERS["lien_clerk_headers"],
            ),
            lambda: api.release_lien(
                lien["id"], release_lien_payload(release_reference="REL-B"),
                TEST_USERS["lien_clerk_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_LIEN_ALREADY_RELEASED.value],
        )
