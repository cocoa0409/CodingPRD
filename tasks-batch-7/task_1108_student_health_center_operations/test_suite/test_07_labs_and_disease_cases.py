"""Lab-order chain and disease-case workflow claims: step gating, reportable
cascade, report window and segregation of duties (PRD §2.1, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_disease_case,
    assert_lab_order,
    assert_timestamp_prefix,
    confirm_case,
    make_health_admin_headers,
    make_lab_order,
    make_suspected_case,
    result_lab_order_payload,
    set_clock,
    setup_open_encounter,
    validate_error,
    validate_success,
)


def test_lab_order_invalid_transition_matrix(api, nurse_headers, clinician_headers):
    """PRD §3.7: "a `Nurse` collects the sample, moving the order from `ORDERED`
    to `SAMPLE_COLLECTED` (any other starting status fails with
    `ERR_LAB_ORDER_NOT_ORDERED`); a `Nurse` enters the result, moving it from
    `SAMPLE_COLLECTED` to `RESULTED` (else `ERR_LAB_ORDER_NOT_COLLECTED`); and a
    `Clinician` reviews it, moving it from `RESULTED` to `REVIEWED` (else
    `ERR_LAB_ORDER_NOT_RESULTED`)."
    PRD §3.7: "When `flags_reportable` is true, the order must have been created
    with a `reportable_disease_code` — flagging a reportable result on an order
    without one is rejected with `ERR_REPORTABLE_CODE_REQUIRED`."

    Design: Corner/state_machines/lab_order_invalid_transition_matrix
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, enc = setup_open_encounter(external_ref="S17")
    lab1 = make_lab_order(enc["id"], "FLU_PCR", reportable_disease_code="INFLUENZA")
    lab2 = make_lab_order(enc["id"], "CBC")
    assert_lab_order(lab1)
    assert lab1["status"] == "ORDERED"

    # Result before collect.
    res1 = api.result_lab_order(
        lab1["id"],
        result_lab_order_payload(result_summary="early", flags_reportable=False),
        nurse_headers,
    )
    validate_error(res1, ApiErrorId.ERR_LAB_ORDER_NOT_COLLECTED, expected_status=409)

    # Review before result.
    res2 = api.review_lab_order(lab1["id"], clinician_headers)
    validate_error(res2, ApiErrorId.ERR_LAB_ORDER_NOT_RESULTED, expected_status=409)

    # Collect, then collect again.
    collected = validate_success(api.collect_lab_order(lab1["id"], nurse_headers), 200)
    assert collected["status"] == "SAMPLE_COLLECTED"
    res3 = api.collect_lab_order(lab1["id"], nurse_headers)
    validate_error(res3, ApiErrorId.ERR_LAB_ORDER_NOT_ORDERED, expected_status=409)

    # Reportable result on an order without a reportable disease code.
    validate_success(api.collect_lab_order(lab2["id"], nurse_headers), 200)
    res4 = api.result_lab_order(
        lab2["id"],
        result_lab_order_payload(result_summary="odd", flags_reportable=True),
        nurse_headers,
    )
    validate_error(res4, ApiErrorId.ERR_REPORTABLE_CODE_REQUIRED, expected_status=422)


def test_disease_case_invalid_transition_matrix(api, nurse_headers,
                                                clinician_headers):
    """PRD §3.7: "Reporting requires the case to be `CONFIRMED`
    (`ERR_CASE_NOT_REPORTABLE`)".
    PRD §3.7: "a `Clinician` may resolve a case from either `CONFIRMED` or
    `REPORTED` (anything else fails with `ERR_CASE_NOT_RESOLVABLE`)".
    PRD §3.7: "A `Clinician` confirms a `SUSPECTED` case (any other status is
    rejected with `ERR_CASE_NOT_CONFIRMABLE`), stamping `confirmed_at` with the
    current logical time and `confirmed_by_user_id` with the confirming
    clinician's `X-User-ID`."

    Design: Corner/state_machines/disease_case_invalid_transition_matrix
    """
    set_clock("2026-05-01T12:00:00Z")
    _, _, _, enc = setup_open_encounter(
        external_ref="S18", visit_type="PRIMARY_URGENT",
        start="2026-05-01T13:00:00Z", end="2026-05-01T13:30:00Z",
    )
    case = make_suspected_case(enc["id"])
    assert_disease_case(case)
    assert case["status"] == "SUSPECTED"

    # Report before confirm.
    res1 = api.report_disease_case(case["id"], make_health_admin_headers("admin-1"))
    validate_error(res1, ApiErrorId.ERR_CASE_NOT_REPORTABLE, expected_status=409)

    # Resolve from SUSPECTED.
    res2 = api.resolve_disease_case(case["id"], clinician_headers)
    validate_error(res2, ApiErrorId.ERR_CASE_NOT_RESOLVABLE, expected_status=409)

    # Confirm succeeds and stamps the confirmation metadata.
    confirmed = confirm_case(case["id"], "clin-1")
    assert confirmed["status"] == "CONFIRMED"
    assert_timestamp_prefix(confirmed["confirmed_at"], "2026-05-01T12:00",
                            label="confirmed_at")
    assert confirmed["confirmed_by_user_id"] == "clin-1"

    # Double confirm.
    res3 = api.confirm_disease_case(case["id"], clinician_headers)
    validate_error(res3, ApiErrorId.ERR_CASE_NOT_CONFIRMABLE, expected_status=409)


def test_disease_case_report_window_and_segregation(api, clinician_headers):
    """PRD §3.7: "it must occur within twenty-four hours of `confirmed_at`, a
    boundary-inclusive window (`ERR_REPORT_WINDOW_EXPIRED` once the current
    logical time passes `confirmed_at` plus 24 hours); and the reporting
    operator's `X-User-ID` must differ from `confirmed_by_user_id`, enforcing
    segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). A successful report
    stamps `reported_at` and `reported_by_user_id` and moves the case
    `CONFIRMED → REPORTED`."

    Design: Corner/state_machines/disease_case_report_window_and_segregation
    """
    set_clock("2026-05-01T12:00:00Z")
    # Two cases confirmed by the same clinician (2 < 3: no outbreak opens).
    _, _, _, enc1 = setup_open_encounter(
        external_ref="S19", visit_type="PRIMARY_URGENT",
        start="2026-05-01T13:00:00Z", end="2026-05-01T13:30:00Z",
    )
    case1 = confirm_case(make_suspected_case(enc1["id"])["id"], "clin-1")

    _, _, _, enc2 = setup_open_encounter(
        external_ref="S20", visit_type="PRIMARY_URGENT",
        start="2026-05-01T14:00:00Z", end="2026-05-01T14:30:00Z",
    )
    case2 = confirm_case(make_suspected_case(enc2["id"])["id"], "clin-1")

    # Happy path: a different operator reports within the window.
    reported = validate_success(
        api.report_disease_case(case2["id"], make_health_admin_headers("admin-9")),
        200,
    )
    assert reported["status"] == "REPORTED"
    assert reported["reported_by_user_id"] == "admin-9"
    assert reported["reported_by_user_id"] != reported["confirmed_by_user_id"]

    # Segregation of duties: the confirming clinician may not report.
    res1 = api.report_disease_case(case1["id"], make_health_admin_headers("clin-1"))
    validate_error(res1, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    # Past confirmed_at + 24h (confirmed 2026-05-01T12:00; now 2026-05-02T13:00).
    set_clock("2026-05-02T13:00:00Z")
    res2 = api.report_disease_case(case1["id"], make_health_admin_headers("admin-9"))
    validate_error(res2, ApiErrorId.ERR_REPORT_WINDOW_EXPIRED, expected_status=403)

    # Failed reports mutate nothing: case1 remains CONFIRMED.
    case1_after = validate_success(
        api.get_disease_case(case1["id"], clinician_headers), 200
    )
    assert case1_after["status"] == "CONFIRMED"
    assert case1_after.get("reported_at") in (None, "")
