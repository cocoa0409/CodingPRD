"""Dual-variant calculation difficulty tests.

Queue A / dual_variant_calc:
  - donor_interval_final_vs_provisional_eligibility_date
  - unit_expiry_collection_anchored_vs_release_anchored
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    create_test_result_payload,
    create_blood_unit_payload,
    advance_clock_payload,
    create_center, create_donor, create_slot, book_appointment,
    setup_collected_donation,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]
LAB = TEST_USERS["lab_technician_headers"]


# ─── donor_interval_final_vs_provisional_eligibility_date ─────────────────────
def test_checkin_succeeds_when_final_interval_elapsed_despite_open_appointment(api):
    """PRD §3.5: "If the donor has no qualifying donation, the base is the epoch
    (1970-01-01T00:00:00.000Z), so the interval is always already elapsed. This FINAL
    variant considers only the actual last qualifying collection and ignores any open
    appointment."
    PRD §3.4: "the inter-donation interval for the slot's donation type must have
    elapsed, else ERR_INTERVAL_NOT_ELAPSED — this is the authoritative interval gate
    described in §3.5."

    A donor with no prior collection but an open WHOLE appointment checks in: FINAL
    (epoch base) is elapsed even though PROVISIONAL would fold in the open appointment.

    Design: Difficulty/dual_variant_calc/donor_interval_final_vs_provisional_eligibility_date
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], full_name="Dana Donor",
                         date_of_birth="1990-05-01", weight_kg=60, blood_type="O_POS")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T09:00:00.000Z", ends_at="2025-01-02T17:00:00.000Z",
                       capacity=5)
    appt = book_appointment(donor["id"], slot)

    res = api.check_in_appointment(appt["id"], NURSE)
    checked_in = validate_success(res, 200)
    assert checked_in["status"] == "CHECKED_IN", (
        "FINAL gate (epoch base, no qualifying donation) must pass at check-in")


def test_provisional_input_present_while_final_input_absent(api):
    """PRD §3.3: "A donor's pending_donation_type mirrors the donation type of their
    single open appointment and is NONE when they have none; its possible values are
    WHOLE, PLASMA, PLATELET, and NONE."
    PRD §3.5: "Its base is the collected_at of the donation pointed to by the donor's
    last_qualifying_donation_id — that is, the donor's most recent donation that reached
    COLLECTED or beyond, ranked by collected_at descending and then created_at descending."

    The open WHOLE appointment makes pending_donation_type WHOLE (PROVISIONAL input),
    while last_qualifying_donation_id is null (FINAL input absent) since no collection.

    Design: Difficulty/dual_variant_calc/donor_interval_final_vs_provisional_eligibility_date
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], date_of_birth="1990-05-01", weight_kg=60, blood_type="O_POS")
    slot = create_slot(center["id"], donation_type="WHOLE",
                       starts_at="2025-01-02T09:00:00.000Z", ends_at="2025-01-02T17:00:00.000Z",
                       capacity=5)
    book_appointment(donor["id"], slot)

    fetched = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert fetched["pending_donation_type"] == "WHOLE", "open WHOLE appointment drives PROVISIONAL input"
    assert fetched["last_qualifying_donation_id"] is None, "no collection -> FINAL input absent"


# ─── unit_expiry_collection_anchored_vs_release_anchored ──────────────────────
def test_rbc_unit_expiry_is_collection_anchored_fixed_at_labeling(api):
    """PRD §3.7: "For RBC, PLASMA, and WHOLE_BLOOD the expiry is collection-anchored
    and fixed at labeling: expires_at is the collected_at plus the component's shelf
    life — 42 days for RBC, 365 days for PLASMA, and 35 days for WHOLE_BLOOD (each day
    being 86,400 seconds)."

    An RBC unit collected 2025-01-01 has expires_at 2025-02-12 (collected_at + 42d),
    set at labeling regardless of release time.

    Design: Difficulty/dual_variant_calc/unit_expiry_collection_anchored_vs_release_anchored
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE", volume_ml=450,
        donor_overrides={"blood_type": "A_POS"},
    )
    unit = validate_success(
        api.create_blood_unit(create_blood_unit_payload(donation["id"], component="RBC", din="DIN-RBC-001"), LAB),
        201,
    )
    assert unit["expires_at"] == "2025-02-12T00:00:00.000Z", (
        f"RBC collected 2025-01-01 + 42d expiry, got {unit['expires_at']}")


def test_platelet_unit_expiry_is_release_anchored_recomputed_at_release(api):
    """PRD §3.7: "For PLATELET the expiry is release-anchored: a platelet in quarantine
    has no started clock, and its expires_at is computed only when the unit becomes
    AVAILABLE, as the released_at instant plus 5 days, overwriting any prior value."
    PRD §3.6: "every QUARANTINED blood unit of that donation is released to AVAILABLE
    (with released_at set to current_utc, platelet expiry recomputed on a release-anchored
    basis per §3.7 ..."

    A platelet labeled while the clock is 2025-01-01 but released at 2025-01-02 gets
    expires_at = released_at + 5d = 2025-01-07.

    Design: Difficulty/dual_variant_calc/unit_expiry_collection_anchored_vs_release_anchored
    """
    center, donor, slot, appt, donation = setup_collected_donation(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="PLATELET", volume_ml=300,
        screening_overrides={"weight_kg": 80}, donor_overrides={"weight_kg": 80, "blood_type": "O_NEG"},
    )
    unit = validate_success(
        api.create_blood_unit(create_blood_unit_payload(donation["id"], component="PLATELET", din="DIN-PLT-001"), LAB),
        201,
    )
    # Advance the clock before releasing so released_at = 2025-01-02.
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-01-02T00:00:00.000Z"), ADMIN))
    validate_success(
        api.create_test_result(donation["id"], create_test_result_payload(panel_outcome="NEGATIVE"), LAB), 201
    )

    released = validate_success(api.get_blood_unit(unit["id"], LAB), 200)
    assert released["released_at"] == "2025-01-02T00:00:00.000Z", (
        f"released_at must equal current_utc at release, got {released['released_at']}")
    assert released["expires_at"] == "2025-01-07T00:00:00.000Z", (
        f"platelet expiry = released_at 2025-01-02 + 5d, got {released['expires_at']}")
