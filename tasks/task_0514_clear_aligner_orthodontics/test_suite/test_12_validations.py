"""Business-rule validation corner cases across intake, financing, retainers,
and shipment windows (PRD §3.2, §3.3, §3.7, §3.8, §3.10)."""
from test_helpers import (
    validate_success, validate_error,
    create_patient, create_case, create_clinician,
    setup_plan_approved, create_financing, setup_financing_active,
    setup_case_active_step1_manufactured,
    create_intake_record_payload, create_shipment_payload, create_retainer_payload,
    api_client, TEST_USERS, make_patient_headers,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def test_intake_channel_mismatch_rejected(api):
    """PRD §3.2: "The intake `channel` must equal the parent case's
    `intake_channel`; a mismatch is rejected with `ERR_CHANNEL_MISMATCH`
    (HTTP 422)."

    Uploading an IN_OFFICE_SCAN intake to an IMPRESSION_KIT case returns
    ERR_CHANNEL_MISMATCH (422).

    Design: Corner/validations/intake_channel_mismatch_rejected
    """
    patient = create_patient(state_code="CA")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT")
    res = api.create_intake_record(
        case["id"],
        {"channel": "IN_OFFICE_SCAN", "quality_score": 0.9, "scan_clinic_state_code": "CA"},
        make_patient_headers(patient["id"]),
    )
    validate_error(res, "ERR_CHANNEL_MISMATCH", expected_status=422)


def test_intake_kit_missing_tracking_number_rejected(api):
    """PRD §3.2: "when the channel is `IMPRESSION_KIT`, the carrier
    `kit_tracking_number` of the returned kit is required ...; the absent
    required field yields `ERR_INTAKE_FIELDS_INCOMPLETE` (HTTP 422)."

    An IMPRESSION_KIT intake with no kit_tracking_number returns
    ERR_INTAKE_FIELDS_INCOMPLETE (422).

    Design: Corner/validations/intake_kit_missing_tracking_number_rejected
    """
    patient = create_patient(state_code="CA")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT")
    res = api.create_intake_record(
        case["id"],
        {"channel": "IMPRESSION_KIT", "quality_score": 0.9},
        make_patient_headers(patient["id"]),
    )
    validate_error(res, "ERR_INTAKE_FIELDS_INCOMPLETE", expected_status=422)


def test_no_eligible_clinician_blocks_submit(api):
    """PRD §3.1: "If the candidate set is empty - no active, suitably-licensed
    clinician exists - submission is rejected with `ERR_NO_ELIGIBLE_CLINICIAN`
    (HTTP 422) and the case remains in `INTAKE_PENDING`."

    A patient in TX with only a CA-licensed clinician has no eligible reviewer,
    so submit-for-review returns ERR_NO_ELIGIBLE_CLINICIAN and the case stays
    INTAKE_PENDING.

    Design: Corner/validations/no_eligible_clinician_blocks_submit
    """
    from test_helpers import add_usable_intake
    create_clinician(license_state_codes=["CA"])
    patient = create_patient(state_code="TX")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT")
    add_usable_intake(case["id"], patient["id"], channel="IMPRESSION_KIT")
    res = api.submit_for_review(case["id"], make_patient_headers(patient["id"]))
    validate_error(res, "ERR_NO_ELIGIBLE_CLINICIAN", expected_status=422)
    fetched = validate_success(api.get_case(case["id"], BILLING), 200)
    assert fetched["status"] == "INTAKE_PENDING", fetched["status"]


def test_down_payment_exceeds_total_rejected(api):
    """PRD §3.7: "It is permitted only when the plan's case is `PLAN_APPROVED`
    and the `down_payment_cents` does not exceed the case's
    `total_contracted_cents`; a down payment larger than the contracted total is
    rejected with `ERR_DOWN_PAYMENT_EXCEEDS_TOTAL` (HTTP 422)."

    Activating financing whose down_payment_cents (400000) exceeds the case
    total (300000) returns ERR_DOWN_PAYMENT_EXCEEDS_TOTAL (422).

    Design: Corner/validations/down_payment_exceeds_total_rejected
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    fin = create_financing(ctx["case"]["id"], term_months=12,
                          down_payment_cents=400000, apr_bps=0)
    res = api.activate_financing_plan(
        fin["id"], {"expected_financing_plan_version": fin["version"]}, BILLING,
    )
    validate_error(res, "ERR_DOWN_PAYMENT_EXCEEDS_TOTAL", expected_status=422)


def test_installment_out_of_order_rejected(api):
    """PRD §3.7 Posting a payment: "Posting requires the plan's `billing_state`
    to be `ACTIVE` and requires every installment with a lower `sequence_no` to
    already be `POSTED` or `WAIVED`; an attempt to post while a lower-sequence
    installment is still `SCHEDULED` or `LATE` is rejected with
    `ERR_INSTALLMENT_OUT_OF_ORDER` (HTTP 422)."

    Posting installment 2 while installment 1 is still SCHEDULED returns
    ERR_INSTALLMENT_OUT_OF_ORDER (422).

    Design: Corner/validations/installment_out_of_order_rejected
    """
    ctx = setup_financing_active(proposed_step_count=10, term_months=12,
                                down_payment_cents=0, apr_bps=0, list_price_cents=300000)
    res = api.post_installment_payment(ctx["financing"]["id"], 2, BILLING)
    validate_error(res, "ERR_INSTALLMENT_OUT_OF_ORDER", expected_status=422)


def test_retainer_on_noncompleted_case_rejected(api):
    """PRD §3.10: "A subscription may only be created for a case in `COMPLETED`
    status; an attempt to start one for any other case status is rejected with
    `ERR_CASE_NOT_COMPLETED` (HTTP 422)."

    Creating a retainer for an INTAKE_PENDING case returns ERR_CASE_NOT_COMPLETED
    (422).

    Design: Corner/validations/retainer_on_noncompleted_case_rejected
    """
    patient = create_patient(state_code="CA")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT")
    res = api.create_retainer(
        create_retainer_payload(case["id"], cadence="QUARTERLY", per_shipment_fee_cents=5000),
        make_patient_headers(patient["id"]),
    )
    validate_error(res, "ERR_CASE_NOT_COMPLETED", expected_status=422)


def test_shipment_inverted_window_rejected(api):
    """PRD §3.8: "The `window_start` must be strictly before `window_end`; an
    inverted or empty window is rejected with `ERR_WINDOW_INVERTED` (HTTP 422)."

    Booking a shipment for a real MANUFACTURED step with window_start after
    window_end returns ERR_WINDOW_INVERTED (422).

    Design: Corner/validations/window_inverted_rejected
    """
    ctx = setup_case_active_step1_manufactured(proposed_step_count=10)
    s1 = ctx["steps"][0]
    res = api.create_shipment(
        create_shipment_payload(s1["id"], carrier_code="GROUND",
                               window_start="2026-05-05T00:00:00Z",
                               window_end="2026-05-02T00:00:00Z"),
        MFG,
    )
    validate_error(res, "ERR_WINDOW_INVERTED", expected_status=422)


def test_ground_touching_windows_book_second_shipment(api):
    """PRD §3.8: "two such windows for the same step must not overlap, though
    touching endpoints (one window's end equal to another's start) are allowed."

    A second GROUND window [05-04, 05-06) starting exactly at the first window's
    end (05-04) touches but does not overlap, so it books a second shipment (201,
    BOOKED).

    Design: Corner/validations/ground_touching_windows_allowed
    """
    ctx = setup_case_active_step1_manufactured(proposed_step_count=10)
    s1 = ctx["steps"][0]
    validate_success(
        api.create_shipment(
            create_shipment_payload(s1["id"], carrier_code="GROUND",
                                   window_start="2026-05-02T00:00:00Z",
                                   window_end="2026-05-04T00:00:00Z"),
            MFG,
        ),
        201,
    )
    second = validate_success(
        api.create_shipment(
            create_shipment_payload(s1["id"], carrier_code="GROUND",
                                   window_start="2026-05-04T00:00:00Z",
                                   window_end="2026-05-06T00:00:00Z"),
            MFG,
        ),
        201,
    )
    assert second["status"] == "BOOKED", second["status"]
