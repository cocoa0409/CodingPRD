"""Laboratory testing: terminal-state lockdown and per-receipt listing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_lab_test_payload,
    get_success_data,
    make_hauler,
    make_producer,
    make_receipt,
    record_lab_result,
    set_clock,
    validate_error,
    validate_paginated,
)

PC = TEST_USERS["plant_controller_headers"]
QA = TEST_USERS["qa_manager_headers"]
LAB = TEST_USERS["lab_technician_headers"]


def test_completed_lab_test_is_terminal(api):
    """PRD §2.10: "then state-machine precondition (→ `ERR_INVALID_STATE`)".
    PRD §3.3: "When a test moves from `DRAFT` to `COMPLETED`, the server stamps
    `completed_at` from the logical clock and derives `result_disposition` from
    the test-type threshold" — no transition out of `COMPLETED` exists, so a
    second completion attempt violates the state-machine precondition.

    Design: Corner/state_machines/lab_test_terminal_state_lockdown
    """
    set_clock()
    producer = make_producer()
    hauler = make_hauler()
    receipt = make_receipt(producer["id"], hauler["id"])
    test = get_success_data(
        api.create_lab_test(
            receipt["id"],
            create_lab_test_payload(test_type="ANTIBIOTIC", result_value=0),
            LAB,
        )
    )
    completed = get_success_data(api.complete_lab_test(receipt["id"], test["id"], {}, LAB))
    assert completed["status"] == "COMPLETED"
    assert completed["result_disposition"] == "PASS"
    assert completed["completed_at"] is not None

    res = api.complete_lab_test(receipt["id"], test["id"], {}, LAB)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_list_lab_tests_for_receipt(api):
    """PRD §3.3: "A lab test is created with `tanker_receipt_id` bound to the
    parent receipt, a `test_type` of `ANTIBIOTIC`, `SCC`, or
    `TEMPERATURE_RECHECK`". PRD §2.3: "List responses always populate
    `meta.limit`, `meta.offset`, `meta.total_count`, and `meta.has_more`."

    Design: Corner/endpoints/get_lab_tests_reverse_reachability
    """
    set_clock()
    producer = make_producer()
    hauler = make_hauler()
    receipt = make_receipt(producer["id"], hauler["id"])
    t1 = record_lab_result(receipt["id"], "ANTIBIOTIC", 0)
    t2 = record_lab_result(receipt["id"], "SCC", 300000)

    data, meta = validate_paginated(api.list_lab_tests(receipt["id"], QA))
    assert len(data) == 2, f"expected 2 lab tests, got {len(data)}"
    assert meta["total_count"] == 2
    returned_ids = {t["id"] for t in data}
    assert returned_ids == {t1["id"], t2["id"]}
    assert all(t["tanker_receipt_id"] == receipt["id"] for t in data)
