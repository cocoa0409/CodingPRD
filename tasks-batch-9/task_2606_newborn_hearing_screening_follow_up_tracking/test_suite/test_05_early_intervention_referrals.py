"""Referral placement, the manual override, decisions and enrollment."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_ei_coordinator_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()


def _network_without_an_ei_program(client):
    """A birth hospital and an audiology clinic, with no early intervention program."""
    birth_hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    return fixtures.Registry(
        birth_hospital=birth_hospital,
        clinic=clinic,
        ei_program=None,
        screener=fixtures.create_provider(
            client, birth_hospital["id"], "SCREENER", "S1", "R1"
        ),
        audiologist=fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1"),
        second_audiologist=fixtures.create_provider(
            client, clinic["id"], "AUDIOLOGIST", "A2", "R1"
        ),
        navigator=fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1"),
        coordinator=None,
    )


def _confirmed_loss(client, registry, phone, left=90, right=90, method="ASSR"):
    """Carry one infant from a referring birth screen to a finalized loss diagnosis."""
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-EI",
        guardian_contact_phone=phone,
    )
    track = fixtures.diagnostic_track(client, registry, infant["id"], clock.at(hours=4))
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], track["episode"]["id"], clock.at(hours=5), method=method
    )
    fixtures.submit_evaluation(client, registry, evaluation["id"], left, right, "BILATERAL_LOSS")
    fixtures.attest_evaluation(client, registry, evaluation["id"])
    fixtures.finalize_evaluation(client, registry, evaluation["id"])
    return infant, track["episode"], evaluation


def test_an_unplaced_referral_is_routed_by_hand_and_only_to_a_program(client):
    """An empty candidate pool leaves the referral unplaced for the admin to route.

    PRD: "When both tiers come up empty, the referral is created with
    `ei_program_facility_id` null; the infant still advances to
    `intervention_status` `REFERRED`, and the unplaced referral waits for a
    `ProgramAdmin` to place it by hand."

    Design: Corner/endpoints/assign_program_places_a_referral_the_selector_left_unplaced
    """
    registry = _network_without_an_ei_program(client)
    infant, _, _ = _confirmed_loss(client, registry, "5555201")

    referral = check.assert_total_count(
        client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    assert referral["ei_program_facility_id"] is None
    assert referral["status"] == "PENDING"

    program = fixtures.create_facility(client, "EI-North", "EI_PROGRAM", "R1")

    wrong_type = client.assign_referral_program(
        referral["id"], {"ei_program_facility_id": registry.ac_id}, headers=ADMIN
    )
    check.assert_error_envelope(wrong_type, errors.ERR_FACILITY_TYPE_MISMATCH)
    assert fixtures.read_referral(client, referral["id"])["ei_program_facility_id"] is None

    placed = check.assert_ok(
        client.assign_referral_program(
            referral["id"], {"ei_program_facility_id": program["id"]}, headers=ADMIN
        )
    )
    assert placed["ei_program_facility_id"] == program["id"]
    assert placed["status"] == "PENDING"

    check.assert_infant_dimensions(
        fixtures.read_infant(client, infant["id"]), "DIAGNOSED_LOSS", "REFERRED"
    )


def test_a_suspended_regional_program_pushes_placement_to_the_statewide_tier(client, registry):
    """The posture filter empties the regional tier before it is judged empty.

    PRD: "The selector first builds a regional tier: every facility whose
    `facility_type` is `EI_PROGRAM`, whose `reporting_compliance_status` is
    `COMPLIANT` or `WATCH`, and whose `region_code` equals the region code of the
    infant's birth facility, minus any facility excluded by a previous attempt on
    this diagnosis."

    Design: Corner/calculations/ei_selector_falls_through_to_the_statewide_tier_when_the_regional_program_is_suspended
    """
    fixtures.suspend_facility(client, registry.ei_id)
    out_of_region = fixtures.create_facility(client, "EI-R2", "EI_PROGRAM", "R2")

    suspended = fixtures.read_facility(client, registry.ei_id)
    assert suspended["penalty_points_balance"] == 18
    assert suspended["reporting_compliance_status"] == "SUSPENDED"

    infant, episode, evaluation = _confirmed_loss(
        client, registry, "5554601", left=80, right=80, method="DIAGNOSTIC_ABR"
    )

    referral = check.assert_total_count(
        client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    assert referral["ei_program_facility_id"] == out_of_region["id"]
    assert referral["status"] == "PENDING"
    check.assert_instant_equals(referral["referred_at"], clock.at(hours=6))

    assert fixtures.read_evaluation(client, evaluation["id"])["status"] == "FINALIZED_LOSS"
    check.assert_episode_state(
        fixtures.read_episode(client, episode["id"]),
        "RESOLVED_DIAGNOSED",
        closure_reason="DIAGNOSIS_CONFIRMED",
    )
    check.assert_infant_dimensions(
        fixtures.read_infant(client, infant["id"]), "DIAGNOSED_LOSS", "REFERRED"
    )

    task = check.assert_total_count(
        client.list_tasks(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    assert task["task_type"] == "EI_LINKAGE"
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == registry.n1_id
    assert task["units_reserved"] == 2
    check.assert_facility_ledger(
        fixtures.read_facility(client, registry.bh_id), navigation_budget_units_remaining=38
    )


def test_enrollment_demands_an_accepted_referral_from_both_sides(client, registry):
    """Enroll is refused on the pending referral and again once it is terminal.

    PRD: "The referral must be in `ACCEPTED`, else `ERR_REFERRAL_INVALID_STATE`; the
    referral's `diagnostic_evaluation_id` row must be in `FINALIZED_LOSS`, because an
    infant cannot be enrolled on an unconfirmed diagnosis"

    Design: Corner/errors/enrolling_a_referral_before_acceptance_is_rejected
    """
    infant, _, _ = _confirmed_loss(
        client, registry, "5555801", left=95, right=95, method="DIAGNOSTIC_ABR"
    )
    referral = check.assert_total_count(
        client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    linkage = check.assert_total_count(
        client.list_tasks(headers=ADMIN, infant_id=infant["id"], task_type="EI_LINKAGE"), 1
    )[0]
    ifsp = {"ifsp_date": clock.at(hours=6)}

    too_early = client.enroll_referral(referral["id"], ifsp, headers=registry.c1)
    check.assert_error_envelope(too_early, errors.ERR_REFERRAL_INVALID_STATE)
    assert fixtures.read_referral(client, referral["id"])["status"] == "PENDING"
    assert fixtures.read_infant(client, infant["id"])["intervention_status"] == "REFERRED"

    accepted = check.assert_ok(
        client.decide_referral(referral["id"], {"decision": "ACCEPT"}, headers=registry.c1)
    )
    assert accepted["status"] == "ACCEPTED"
    check.assert_instant_equals(accepted["accepted_at"], clock.at(hours=6))

    enrolled = check.assert_ok(client.enroll_referral(referral["id"], ifsp, headers=registry.c1))
    assert enrolled["status"] == "ENROLLED"
    check.assert_instant_equals(enrolled["ifsp_date"], clock.at(hours=6))
    assert enrolled["enrollment_age_days"] == 0
    assert enrolled["ei_timeliness_status"] == "ON_TIME"
    assert fixtures.read_infant(client, infant["id"])["intervention_status"] == "ENROLLED"
    completed = fixtures.read_task(client, linkage["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "LINKED"
    assert completed["units_reserved"] == linkage["units_reserved"]

    again = client.enroll_referral(referral["id"], ifsp, headers=registry.c1)
    check.assert_error_envelope(again, errors.ERR_REFERRAL_INVALID_STATE)
    assert fixtures.read_referral(client, referral["id"])["status"] == "ENROLLED"


def test_the_decision_endpoint_is_shared_but_the_identity_binding_is_not(client, registry):
    """Another program's coordinator is refused; the navigator's decline is not.

    PRD: "`FAMILY_DECLINED` is a `Navigator` action available while the referral is
    `PENDING` or `ACCEPTED`: it advances the referral to `DECLINED_BY_FAMILY` with the
    reason stored in `resolution_reason`, moves the infant's `intervention_status` to
    `DECLINED`, and cancels any `EI_LINKAGE` navigation task for that infant still in
    `UNASSIGNED` or `OPEN`, crediting its `units_reserved` back to the funding
    facility's `navigation_budget_units_remaining`."

    Design: Corner/rbac/referral_decision_is_shared_between_the_program_coordinator_and_the_navigator
    """
    second_program = fixtures.create_facility(client, "EI2", "EI_PROGRAM", "R1")
    other_coordinator = fixtures.create_provider(
        client, second_program["id"], "EI_COORDINATOR", "C2", "R1"
    )
    other_headers = make_ei_coordinator_headers(other_coordinator["id"])

    infant, _, _ = _confirmed_loss(
        client, registry, "5556501", left=85, right=85, method="DIAGNOSTIC_ABR"
    )
    referral = check.assert_total_count(
        client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    assert referral["ei_program_facility_id"] == registry.ei_id
    assert referral["status"] == "PENDING"
    check.assert_facility_ledger(
        fixtures.read_facility(client, registry.bh_id), navigation_budget_units_remaining=38
    )
    linkage = check.assert_total_count(
        client.list_tasks(headers=ADMIN, infant_id=infant["id"], task_type="EI_LINKAGE"), 1
    )[0]

    intruder = client.decide_referral(
        referral["id"], {"decision": "ACCEPT"}, headers=other_headers
    )
    check.assert_error_envelope(intruder, errors.ERR_IDENTITY_MISMATCH)
    untouched = fixtures.read_referral(client, referral["id"])
    assert untouched["status"] == "PENDING"
    assert untouched["accepted_at"] is None

    declined = check.assert_ok(
        client.decide_referral(
            referral["id"],
            {"decision": "FAMILY_DECLINED", "reason": "family moving abroad"},
            headers=registry.n1,
        )
    )
    assert declined["status"] == "DECLINED_BY_FAMILY"
    assert declined["resolution_reason"] == "family moving abroad"
    assert fixtures.read_infant(client, infant["id"])["intervention_status"] == "DECLINED"
    assert fixtures.read_task(client, linkage["id"])["status"] == "CANCELLED"
    check.assert_facility_ledger(
        fixtures.read_facility(client, registry.bh_id), navigation_budget_units_remaining=40
    )
