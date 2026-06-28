"""Breadth tests for business-rule validations: PWN licensure/age, appointment
slot/fasting, home-kit geography, cart-line addability, bundle membership, and
HSA sufficiency at capture.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]
PHYSICIAN = TEST_USERS["ordering_physician_headers"]


# ---------------------------------------------------------------------------
# Corner/validations/pwn_approve_unlicensed_state_returns_409
# ---------------------------------------------------------------------------
def test_pwn_approve_unlicensed_state_returns_409(api):
    """PRD 3.5: "the patient's state_code must be one of the network-licensed
    states — CA, TX, or FL — or the approval is rejected with
    ERR_PWN_STATE_UNLICENSED".

    Design: Corner/validations/pwn_approve_unlicensed_state_returns_409
    """
    ctx = fx.setup_restricted_order(test_code="TSTU", patient_overrides={"state_code": "XX", "date_of_birth": "1990-01-01"}, api=api)
    po = ctx["physician_order"]
    resp = api.decide_physician_order(po["id"], F.physician_decision_payload("APPROVE"), PHYSICIAN)
    validate_error(resp, ApiErrorId.ERR_PWN_STATE_UNLICENSED.value)


# ---------------------------------------------------------------------------
# Corner/validations/pwn_approve_underage_returns_409
# ---------------------------------------------------------------------------
def test_pwn_approve_underage_returns_409(api):
    """PRD 3.5: "and the patient's age, derived as the logical-clock today minus
    date_of_birth, must be at least 18 years, or the approval is rejected with
    ERR_PWN_AGE_INELIGIBLE".

    Patient DOB 2020-01-01 against the default clock 2026-01-01 is under 18.

    Design: Corner/validations/pwn_approve_underage_returns_409
    """
    ctx = fx.setup_restricted_order(test_code="TSTY", patient_overrides={"state_code": "CA", "date_of_birth": "2020-01-01"}, api=api)
    po = ctx["physician_order"]
    resp = api.decide_physician_order(po["id"], F.physician_decision_payload("APPROVE"), PHYSICIAN)
    validate_error(resp, ApiErrorId.ERR_PWN_AGE_INELIGIBLE.value)


# ---------------------------------------------------------------------------
# Corner/validations/appointment_invalid_slot_window_returns_422
# ---------------------------------------------------------------------------
def test_appointment_invalid_slot_window_returns_422(api):
    """PRD 3.7: "The slot window must be valid — slot_end strictly after slot_start,
    or the booking is rejected with ERR_INVALID_SLOT_WINDOW."

    Design: Corner/validations/appointment_invalid_slot_window_returns_422
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="PSC",
        offering_overrides={"test_code": "AP", "display_name": "Appt Test", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order = ctx["patient"], ctx["order"]
    resp = api.create_appointment(
        F.create_appointment_payload(order["id"], "PSC-3", "2026-02-01T10:00:00Z", "2026-02-01T10:00:00Z"),
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_WINDOW.value)


# ---------------------------------------------------------------------------
# Corner/validations/appointment_fasting_not_confirmed_returns_409
# ---------------------------------------------------------------------------
def test_appointment_fasting_not_confirmed_returns_409(api):
    """PRD 3.7: "If any of the order's line offerings has requires_fasting true, the
    appointment's fasting_confirmed must be true, or the booking is rejected with
    ERR_FASTING_NOT_CONFIRMED."
    PRD 3.7: "an optional fasting_confirmed attestation defaulting to false."

    Design: Corner/validations/appointment_fasting_not_confirmed_returns_409
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="PSC",
        offering_overrides={"test_code": "FAST", "display_name": "Fasting Test", "list_price_cents": 4000, "specimen_type": "BLOOD", "requires_fasting": True},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order = ctx["patient"], ctx["order"]
    resp = api.create_appointment(
        F.create_appointment_payload(order["id"], "PSC-4", "2026-02-01T08:00:00Z", "2026-02-01T08:30:00Z"),
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FASTING_NOT_CONFIRMED.value)


# ---------------------------------------------------------------------------
# Corner/validations/home_kit_banned_state_returns_409
# ---------------------------------------------------------------------------
def test_home_kit_banned_state_returns_409(api):
    """PRD 3.5: "The shipping state must equal the patient's state_code and must not
    be one of the banned states — NY, NJ, or RI — and the offering must be
    home_kit_eligible; a violation of any of these is rejected with
    ERR_HOME_KIT_STATE_BANNED. The same eligibility check applies both at HOME_KIT
    checkout and at the home-kit minting step."

    Patient in NY (banned): HOME_KIT checkout is rejected.

    Design: Corner/validations/home_kit_banned_state_returns_409
    """
    off = fx.create_offering(api=api, test_code="HKB", display_name="Home Kit Banned", list_price_cents=4000, specimen_type="SALIVA", home_kit_eligible=True)
    patient = fx.create_patient(api=api, state_code="NY")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    resp = api.create_order(
        F.create_order_payload(cart["id"], "HOME_KIT", cart_read["version"]),
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOME_KIT_STATE_BANNED.value)


# ---------------------------------------------------------------------------
# Corner/validations/add_archived_offering_to_cart_returns_409
# ---------------------------------------------------------------------------
def test_add_archived_offering_to_cart_returns_409(api):
    """PRD 3.2: "The offering must be ACTIVE and the cart must be OPEN; otherwise
    the add is rejected with ERR_OFFERING_NOT_ADDABLE."

    Design: Corner/validations/add_archived_offering_to_cart_returns_409
    """
    off = fx.create_offering(api=api, test_code="ARCX", display_name="Archived X", list_price_cents=4000, specimen_type="BLOOD")
    fx.archive_offering(off["id"], api=api)
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    resp = api.create_cart_line(
        F.create_cart_line_payload(cart["id"], off["id"]),
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_ADDABLE.value)


# ---------------------------------------------------------------------------
# Corner/validations/panel_bundle_one_member_returns_422
# ---------------------------------------------------------------------------
def test_panel_bundle_one_member_returns_422(api):
    """PRD 3.1: "The members must be at least two distinct codes, and each must
    reference an ACTIVE offering at create time; a bundle that violates either rule
    is rejected with ERR_INVALID_BUNDLE_MEMBERS."

    Design: Corner/validations/panel_bundle_one_member_returns_422
    """
    fx.create_offering(api=api, test_code="SOLO", display_name="Solo", list_price_cents=4000, specimen_type="BLOOD")
    resp = api.create_panel_bundle(
        {"bundle_code": "B1", "display_name": "One Member", "member_test_codes": ["SOLO"], "bundle_price_cents": 3000},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_BUNDLE_MEMBERS.value)


# ---------------------------------------------------------------------------
# Corner/validations/insufficient_hsa_funds_at_capture_returns_402
# ---------------------------------------------------------------------------
def test_insufficient_hsa_funds_at_capture_returns_402(api):
    """PRD 3.7: "should the required draw exceed the patient's available
    hsa_balance_cents, the capture is rejected with ERR_INSUFFICIENT_HSA_FUNDS."
    PRD 3.1: "A patient — or an admin acting for them — may later update
    consent_share_results and/or hsa_balance_cents."

    HSA balance drained to 0 (via PATCH) after a completed HSA_FSA order whose
    hsa_applied > 0: capture fails 402.

    Design: Corner/validations/insufficient_hsa_funds_at_capture_returns_402
    """
    ctx = fx.setup_order_with_fund_source(
        fund_source="HSA_FSA",
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "HF", "display_name": "HSA Fund", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA", "hsa_balance_cents": 4000},
        api=api,
    )
    patient, order, line = ctx["patient"], ctx["order"], ctx["order_line"]
    p_headers = make_patient_headers(patient["id"])
    spec = fx.collect_line(line["id"], api=api)
    res = fx.process_specimen(spec["id"], 5, api=api)
    get_success_data(api.release_lab_result(res["id"], LAB2))

    # Drain HSA balance to 0 before capture.
    get_success_data(api.update_patient(patient["id"], {"hsa_balance_cents": 0}, p_headers))
    order_now = validate_success(api.get_order(order["id"], p_headers))
    resp = api.capture_payment(order["id"], {"expected_order_version": order_now["version"]}, p_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_HSA_FUNDS.value)
