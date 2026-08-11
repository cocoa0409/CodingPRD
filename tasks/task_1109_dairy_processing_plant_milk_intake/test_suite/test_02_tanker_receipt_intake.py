"""Tanker receipt intake: computed net weight, input shape, initial state,
rejection criterion, lab-test gate, and the 45F temperature boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_tanker_receipt,
    create_tanker_receipt_payload,
    get_producer,
    make_hauler,
    make_permit,
    make_producer,
    make_receipt,
    record_lab_result,
    release_receipt,
    set_clock,
    setup_releasable_receipt,
    validate_error,
    validate_success,
)

PC = TEST_USERS["plant_controller_headers"]
QA = TEST_USERS["qa_manager_headers"]


def _producer_and_hauler():
    set_clock()
    producer = make_producer()
    hauler = make_hauler()
    return producer, hauler


def test_net_weight_computed_as_gross_minus_tare(api):
    """PRD §3.2: "On creation the server computes `net_weight_lbs` as the gross
    weight minus the tare weight, sets `disposition` to `QUARANTINE`,
    initializes `antibiotic_result` to `PENDING`, leaves `scc_cells_per_ml` and
    `rejection_reason` unset, and stamps `created_at` from the logical clock."

    Design: Corner/entities/tanker_receipt_net_weight_computed
    """
    producer, hauler = _producer_and_hauler()
    res = api.create_tanker_receipt(
        create_tanker_receipt_payload(
            producer["id"], hauler["id"], gross_weight_lbs=75000, tare_weight_lbs=30000
        ),
        QA,
    )
    receipt = validate_success(res, 201)
    assert_tanker_receipt(receipt)
    assert receipt["net_weight_lbs"] == 45000, (
        f"net_weight_lbs must be 75000 - 30000 = 45000, got {receipt['net_weight_lbs']}"
    )


def test_tare_must_be_strictly_less_than_gross(api):
    """PRD §3.2: "The tare weight must be strictly less than the gross weight;
    a payload that violates this shape is rejected with `ERR_INVALID_INPUT`."

    Design: Corner/entities/tanker_receipt_tare_must_be_less_than_gross
    """
    producer, hauler = _producer_and_hauler()
    res = api.create_tanker_receipt(
        create_tanker_receipt_payload(
            producer["id"], hauler["id"], gross_weight_lbs=30000, tare_weight_lbs=30000
        ),
        QA,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_INPUT)


def test_new_receipt_starts_in_quarantine(api):
    """PRD §3.2: "On creation the server computes `net_weight_lbs` as the gross
    weight minus the tare weight, sets `disposition` to `QUARANTINE`"."

    Design: Corner/state_machines/tanker_receipt_initial_state_quarantine
    """
    producer, hauler = _producer_and_hauler()
    receipt = make_receipt(producer["id"], hauler["id"])
    assert receipt["disposition"] == "QUARANTINE"
    assert receipt["antibiotic_result"] == "PENDING"


def test_reject_without_criterion_fails(api):
    """PRD §3.4: "Rejection requires that at least one rejection criterion is
    met — antibiotic result `POSITIVE`, somatic-cell count at or above 750000
    cells per millilitre, temperature above 45 degrees Fahrenheit, or a hauler
    license expired relative to `arrived_at`. If none of these criteria holds,
    the rejection is rejected with `ERR_NO_REJECTION_CRITERION`."

    Design: Corner/state_machines/receipt_reject_without_criterion_fails
    """
    producer, hauler = _producer_and_hauler()
    receipt = setup_releasable_receipt(producer["id"], hauler["id"])
    res = api.reject_tanker_receipt(receipt["id"], {}, QA)
    validate_error(res, ApiErrorId.ERR_NO_REJECTION_CRITERION)


def test_release_blocked_when_lab_tests_pending(api):
    """PRD §3.3: "All required lab tests — at minimum one `ANTIBIOTIC` and one
    `SCC` — for this receipt must be `COMPLETED`, otherwise
    `ERR_LAB_TESTS_PENDING`."

    Design: Corner/state_machines/release_blocked_when_lab_tests_pending
    """
    producer, hauler = _producer_and_hauler()
    make_permit()
    receipt = make_receipt(producer["id"], hauler["id"])
    record_lab_result(receipt["id"], "ANTIBIOTIC", 0)
    # SCC test never recorded → required set incomplete.
    producer_now = get_producer(producer["id"])
    res = api.release_tanker_receipt(
        receipt["id"], {"expected_producer_version": producer_now["version"]}, QA
    )
    validate_error(res, ApiErrorId.ERR_LAB_TESTS_PENDING)


def test_temperature_46_rejected_on_release(api):
    """PRD §3.3: "The receipt's `temperature_f` must be at most 45 degrees
    Fahrenheit, otherwise `ERR_TEMPERATURE_EXCEEDED`."

    Design: Corner/state_machines/temperature_boundary_45F
    """
    producer, hauler = _producer_and_hauler()
    make_permit()
    receipt = setup_releasable_receipt(producer["id"], hauler["id"], temp=46)
    producer_now = get_producer(producer["id"])
    res = api.release_tanker_receipt(
        receipt["id"], {"expected_producer_version": producer_now["version"]}, QA
    )
    validate_error(res, ApiErrorId.ERR_TEMPERATURE_EXCEEDED)


def test_temperature_45_released(api):
    """PRD §3.3: "The receipt's `temperature_f` must be at most 45 degrees
    Fahrenheit, otherwise `ERR_TEMPERATURE_EXCEEDED`." — 45 is "at most 45", so
    a receipt at exactly 45 passes the temperature precondition.

    Design: Corner/state_machines/temperature_boundary_45F
    """
    producer, hauler = _producer_and_hauler()
    make_permit()
    receipt = setup_releasable_receipt(producer["id"], hauler["id"], temp=45)
    released = release_receipt(receipt["id"], producer["id"])
    assert released["disposition"] == "RELEASED_FOR_PROCESSING"
