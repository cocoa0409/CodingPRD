"""Diagnosis/procedure line capture rules: enum validity, POA safety,
sequence uniqueness, and immediate read-your-write consistency."""
from test_helpers import (
    ApiErrorId,
    add_diagnosis,
    assert_diagnosis_line,
    make_coder_headers,
    setup_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_diagnosis_invalid_poa_enum_returns_invalid_request(api, manager_headers):
    """PRD §3.3: "a present-on-admission indicator `poa` of `Y`, `N`, `U`,
    `W`, or `EXEMPT`" — and per §2.8 tier 7 "invalid enum members" yield
    `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/entities/create_diagnosis_invalid_poa_enum_returns_invalid_request
    """
    ctx = setup_in_progress("MRN-EN5", "E-EN5", acuity="MEDICAL_LOW", credential="CCS")
    res = api.create_diagnosis_line(
        {
            "chart_id": ctx["chart"]["id"],
            "icd_code": "I21.09",
            "poa": "X",
            "sequence": 1,
            "is_principal": True,
        },
        make_coder_headers(ctx["coder"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_create_diagnosis_poa_u_on_mcc_rejected(api, manager_headers):
    """PRD §3.3: "A `poa` of `U` is forbidden on any line whose `cc_level` is
    `CC` or `MCC` — documentation "unable to determine" cannot support a
    severity-raising condition — and such a line is rejected with
    `ERR_POA_INVALID_FOR_CODE`, both at capture and on later edits."

    Design: Corner/validations/create_diagnosis_poa_u_on_mcc_rejected
    """
    ctx = setup_in_progress("MRN-VA7", "E-VA7", acuity="MEDICAL_LOW", credential="CCS")
    res = api.create_diagnosis_line(
        {
            "chart_id": ctx["chart"]["id"],
            "icd_code": "N18.6",
            "poa": "U",
            "sequence": 1,
            "cc_level": "MCC",
        },
        make_coder_headers(ctx["coder"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_POA_INVALID_FOR_CODE, expected_status=422)


def test_create_diagnosis_duplicate_sequence_rejected(api, manager_headers):
    """PRD §3.3: "a `sequence` — an integer of at least 1 that must be unique
    among the chart's `ACTIVE` lines, with duplicates refused at creation time
    by `ERR_DUPLICATE_SEQUENCE`."

    Design: Corner/validations/create_diagnosis_duplicate_sequence_rejected
    """
    ctx = setup_in_progress("MRN-VAA", "E-VAA", acuity="MEDICAL_LOW", credential="CCS")
    coder = make_coder_headers(ctx["coder"]["id"])
    first = add_diagnosis(
        ctx["chart"]["id"], ctx["coder"]["id"],
        icd_code="I21.09", poa="Y", sequence=1, is_principal=True,
    )
    assert_diagnosis_line(first)
    res = api.create_diagnosis_line(
        {
            "chart_id": ctx["chart"]["id"],
            "icd_code": "J44.1",
            "poa": "Y",
            "sequence": 1,
        },
        coder,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SEQUENCE, expected_status=422)


def test_diagnosis_create_then_list_immediate_consistency(api, manager_headers):
    """PRD §2.10: "The consistency model is immediate: when one operation
    mutates several resources through a cascade, every one of those mutations
    is applied atomically and is visible in the response of the same request
    that triggered it."

    Design: Corner/consistency_model/diagnosis_create_then_list_immediate_consistency
    """
    ctx = setup_in_progress("MRN-CM1", "E-CM1", acuity="MEDICAL_LOW", credential="CCS")
    line = validate_success(
        api.create_diagnosis_line(
            {
                "chart_id": ctx["chart"]["id"],
                "icd_code": "I21.09",
                "poa": "Y",
                "sequence": 1,
                "is_principal": True,
            },
            make_coder_headers(ctx["coder"]["id"]),
        ),
        201,
    )
    data, meta = validate_paginated(
        api.list_diagnosis_lines(manager_headers, params={"chart_id": ctx["chart"]["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == line["id"]
    assert data[0]["icd_code"] == "I21.09"
