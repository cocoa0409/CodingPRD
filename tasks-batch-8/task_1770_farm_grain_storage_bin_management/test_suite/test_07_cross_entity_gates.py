"""Difficulty Rule 7: cross-entity state dependencies.

Covers:
- loadout_create_gated_by_bin_posture (LoadOut x Bin)
- permit_approve_gated_by_fumigation (BinEntryPermit x FumigationRecord)
- claim_submit_gated_by_alert (InsuranceClaim x SpoilageAlert)
"""
import pytest

from test_helpers import (
    get_success_data, validate_error, validate_success,
    ApiErrorId,
    TEST_USERS, make_applicator_headers, make_site_manager_headers,
    make_safety_officer_headers,
    create_bin, create_lot, create_contract, create_policy,
    setup_bin_with_lot, setup_active_fumigation,
    get_bin, get_first_alert_for_bin, create_hotspot_reading,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_loadout_payload, create_permit_payload, create_claim_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: loadout_create_gated_by_bin_posture
# ============================================================

def test_loadout_create_rejected_when_bin_alert(api):
    """PRD section 2.7: "Three operations are gated on posture: filling a
    new lot, scheduling a load-out, and dispatching a scheduled load-out
    each require the bin's posture to be `SOUND` or `WATCH`. Against a bin
    in `ALERT` or `FUMIGATION_LOCKOUT`, any of the three is rejected with
    `ERR_BIN_POSTURE_BLOCKED` (HTTP 409)."

    A hotspot reading flips the bin to ALERT; loadout create is then
    rejected.

    Design: Difficulty/cross_entity_state_dependency/loadout_create_gated_by_bin_posture
    """
    b, lot = setup_bin_with_lot(bin_name="BIN-G1", original_bu=800.00)
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    assert get_bin(b["id"])["posture"] == "ALERT"
    con = create_contract(contracted_bu=2000.00)
    resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=400.00,
    ), SM)
    validate_error(resp, ApiErrorId.ERR_BIN_POSTURE_BLOCKED, expected_status=409)


def test_loadout_create_succeeds_on_sound_bin_and_rejected_on_alert(api):
    """PRD section 2.7: "filling a new lot, scheduling a load-out, and
    dispatching a scheduled load-out each require the bin's posture to be
    `SOUND` or `WATCH`."

    Companion control under the same instance: a loadout create against a
    SOUND bin succeeds (201); then a hotspot flips the same bin to ALERT and
    a second create against it is rejected — the rejection depends on the
    Bin's state, not on the contract or the payload.

    Design: Difficulty/cross_entity_state_dependency/loadout_create_gated_by_bin_posture
    """
    b, lot = setup_bin_with_lot(bin_name="BIN-G1B", original_bu=800.00)
    con = create_contract(contracted_bu=2000.00)
    ok = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=100.00,
    ), SM)
    assert ok.status_code == 201

    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    con_now = get_success_data(api_client.get_contract(con["id"], SM))
    bad = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con_now["version"], planned_bu=100.00,
        scheduled_start="2026-08-11T08:00:00Z",
        scheduled_end="2026-08-11T12:00:00Z",
    ), SM)
    validate_error(bad, ApiErrorId.ERR_BIN_POSTURE_BLOCKED, expected_status=409)


# ============================================================
# Instance: permit_approve_gated_by_fumigation
# ============================================================

def test_permit_approve_rejected_while_active_fumigation(api):
    """PRD section 3.4: "The checks then proceed in a fixed order: the
    permit must still be `REQUESTED` (otherwise `ERR_PERMIT_NOT_REQUESTED`);
    no `ACTIVE` fumigation with an `application_start` at or before now may
    exist on the bin (otherwise `ERR_ACTIVE_FUMIGATION_EXISTS`)".

    Permit is REQUESTED with passing atmosphere/LOTO, but the bin has an
    ACTIVE fumigation whose application_start is at the default clock.

    Design: Difficulty/cross_entity_state_dependency/permit_approve_gated_by_fumigation
    """
    b, app, fum = setup_active_fumigation(bin_name="BIN-G2")
    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"]), make_site_manager_headers("mgr-1")))
    resp = api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-1"))
    validate_error(resp, ApiErrorId.ERR_ACTIVE_FUMIGATION_EXISTS,
                   expected_status=409)


def test_permit_approve_succeeds_after_fumigation_cleared(api):
    """PRD section 3.4: "no `ACTIVE` fumigation with an `application_start`
    at or before now may exist on the bin (otherwise
    `ERR_ACTIVE_FUMIGATION_EXISTS`); and only then are the physical
    preconditions evaluated — both `atmosphere_test_passed` and
    `loto_confirmed` must be true, otherwise `ERR_ATMOSPHERE_UNSAFE`."

    Control: once the fumigation is cleared (past REI) the permit can be
    approved — the rejection depends on FumigationRecord state.

    Design: Difficulty/cross_entity_state_dependency/permit_approve_gated_by_fumigation
    """
    from test_helpers import set_clock
    b, app_a, fum = setup_active_fumigation(
        bin_name="BIN-G2C", product="SULFURYL_FLUORIDE",
        application_start="2026-08-01T00:00:00Z",
        application_end="2026-08-01T04:00:00Z",
    )
    app_b = get_success_data(api_client.create_applicator(
        {"name": "Bob B", "license_no": "LIC-B",
         "cert_expires_at": "2027-06-01T00:00:00Z"}, SM))
    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"]), make_site_manager_headers("mgr-1")))
    # Clear the fumigation after its 24h REI
    set_clock("2026-08-02T00:00:00Z")
    get_success_data(api_client.clear_fumigation(
        fum["id"], make_applicator_headers(app_b["id"])))
    ok = api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-1"))
    data = validate_success(ok, expected_status=200)
    assert data["status"] == "APPROVED"


# ============================================================
# Instance: claim_submit_gated_by_alert
# ============================================================

def test_claim_against_open_alert_rejected(api):
    """PRD section 3.8: "the referenced alert must be in `CONFIRMED_LOSS`
    (otherwise `ERR_ALERT_LOSS_NOT_CONFIRMED`)".

    The alert is still OPEN; the claim is rejected.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_gated_by_alert
    """
    b = create_bin(name="BIN-G3")
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    assert alert["status"] == "OPEN"
    pol = create_policy(valuation_clause="SPOT")
    resp = api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM)
    validate_error(resp, ApiErrorId.ERR_ALERT_LOSS_NOT_CONFIRMED,
                   expected_status=409)


def test_claim_against_confirmed_loss_alert_accepted(api):
    """PRD section 3.8: "A submitted claim copies the alert's `loss_bu` onto
    itself and begins in `SUBMITTED` status."

    Control under the same instance: once the alert is closed as
    CONFIRMED_LOSS, the claim is accepted and its loss_bu is copied.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_gated_by_alert
    """
    b = create_bin(name="BIN-G3B")
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 100.00}, SM))
    pol = create_policy(valuation_clause="SPOT")
    resp = api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SUBMITTED"
    assert data["loss_bu"] == pytest.approx(100.00, abs=1e-9)
