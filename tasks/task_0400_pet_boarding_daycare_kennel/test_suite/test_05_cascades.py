"""Transitive cascades from reservation transitions (depth-3 chains).

Translates difficulty (A) transitive_cascade instances (confirm and cancel) and
corner (B) consistency_model/confirm_effects_visible_same_response.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_assignment_payload,
    setup_held_reservation, setup_package_funded_confirmed,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_confirm_flips_held_assignment_to_occupied(api):
    """PRD §3.6: "Every `HELD` run assignment of the reservation advances to `OCCUPIED`
    (the first cascade hop, reservation driving its assignments), and each newly
    `OCCUPIED` assignment marks its run busy for the window in capacity accounting (the
    second hop, assignment driving its run)."

    Design: Difficulty/transitive_cascade/confirm_cascade_reservation_assignment_run_depth3
    """
    ctx = setup_held_reservation(
        service_type="OVERNIGHT", start_date="2026-02-10", end_date="2026-02-12",
        deposit_policy="NONE")
    res = ctx["reservation"]
    assignment = ctx["assignment"]
    assert assignment["status"] == "HELD"
    confirmed = validate_success(api.confirm_reservation(res["id"], MGR), 200)
    assert confirmed["status"] == "CONFIRMED"
    asgs = api.list_assignments(res["id"], MGR).json()["data"]
    assert asgs[0]["status"] == "OCCUPIED", "HELD assignment cascades to OCCUPIED on confirm"


def test_confirm_run_marked_busy_blocks_overlapping_assignment(api):
    """PRD §3.6: "each newly `OCCUPIED` assignment marks its run busy for the window in
    capacity accounting (the second hop, assignment driving its run)."
    PRD §3.6: "For an `OVERNIGHT_SUITE`, the assignment interval must not overlap any
    non-`RELEASED` assignment already on that same suite, using half-open intervals so
    that adjacent intervals sharing an endpoint do not conflict; a clash is rejected with
    `ERR_RUN_OVERLAP`."

    After confirm marks the suite busy (hop C), a second overlapping OVERNIGHT assignment
    on the same run is rejected ERR_RUN_OVERLAP.

    Design: Difficulty/transitive_cascade/confirm_cascade_reservation_assignment_run_depth3
    """
    ctx = setup_held_reservation(
        service_type="OVERNIGHT", start_date="2026-02-10", end_date="2026-02-12",
        deposit_policy="NONE")
    facility, pet, run, res = ctx["facility"], ctx["pet"], ctx["run"], ctx["reservation"]
    validate_success(api.confirm_reservation(res["id"], MGR), 200)
    # A second reservation for a different pet on an overlapping window wanting the same suite.
    owner2 = get_success_data(api_client.create_owner(
        facility["id"], {"full_name": "Other", "email": "other-cascade@x.com", "phone": "555-9"}, MGR))
    pet2 = get_success_data(api_client.create_pet(
        owner2["id"], {"name": "P2", "species": "CAT", "weight_kg": 6}, MGR))
    res2 = get_success_data(api_client.create_reservation(
        facility["id"],
        {"pet_id": pet2["id"], "service_type": "OVERNIGHT",
         "start_date": "2026-02-11", "end_date": "2026-02-13"},
        MGR,
    ))
    out = api.create_assignment(
        res2["id"], create_assignment_payload(run["id"], res2["version"]), MGR)
    validate_error(out, "ERR_RUN_OVERLAP")


def test_cancel_reverses_redemption_and_restores_credit(api):
    """PRD §3.8: "if the reservation's `redeemed_credit` is true, the linked
    `PackageRedemption` has its `reversed` set true (the first cascade hop, reservation
    driving the redemption) and the owning package's `credits_remaining` is then
    recomputed (the second hop)."

    A package-funded confirm consumes a credit (10 -> 9); cancel reverses it (9 -> 10).

    Design: Difficulty/transitive_cascade/cancel_cascade_reservation_redemption_package_depth3
    """
    ctx = setup_package_funded_confirmed(tier="DAYCARE_10", start_date="2026-01-10")
    package, res = ctx["package"], ctx["reservation"]
    assert package["credits_remaining"] == 9, "confirm consumed one credit"
    validate_success(api.cancel_reservation(res["id"], MGR), 200)
    pkg_after = validate_success(api.get_package(package["id"], MGR), 200)
    assert pkg_after["credits_remaining"] == 10, "cancel reversal restores the credit"


def test_cancel_marks_redemption_reversed_true(api):
    """PRD §3.8: "if the reservation's `redeemed_credit` is true, the linked
    `PackageRedemption` has its `reversed` set true (the first cascade hop, reservation
    driving the redemption)".

    Design: Difficulty/transitive_cascade/cancel_cascade_reservation_redemption_package_depth3
    """
    ctx = setup_package_funded_confirmed(tier="DAYCARE_10", start_date="2026-01-10")
    package, res = ctx["package"], ctx["reservation"]
    validate_success(api.cancel_reservation(res["id"], MGR), 200)
    redemptions = api.list_redemptions(package["id"], MGR).json()["data"]
    assert len(redemptions) == 1
    assert redemptions[0]["reversed"] is True, "the redemption is marked reversed on cancel"


def test_confirm_effects_visible_in_same_response(api):
    """PRD §2.5: "no child is left inconsistent with its parent after a request completes,
    and that every such mutation is reflected immediately rather than deferred."
    PRD §3.6: "Confirming a reservation moves it from `REQUESTED` to `CONFIRMED`".

    The confirm response itself already reflects status CONFIRMED.

    Design: Corner/consistency_model/confirm_effects_visible_same_response
    """
    ctx = setup_held_reservation(
        service_type="DAYCARE", start_date="2026-03-01", end_date="2026-03-01",
        deposit_policy="NONE")
    res = ctx["reservation"]
    confirmed = validate_success(api.confirm_reservation(res["id"], MGR), 200)
    assert confirmed["status"] == "CONFIRMED", "confirm response reflects CONFIRMED immediately"
