"""Account registration, chart completeness, and deficiency interlock tests."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_chart,
    assert_deficiency,
    assert_patient_account,
    create_patient_account_payload,
    discharge_account,
    get_success_data,
    is_valid_uuid,
    make_account,
    make_chart,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_account_creation_defaults(api, manager_headers):
    """PRD §3.1: "A new account begins `ADMITTED`; its `discharge_at` and
    `discharge_disposition` remain unset, and its `dnfb_flag` reads false,
    until later events say otherwise."

    Design: Corner/entities/account_creation_defaults
    """
    res = api.create_patient_account(
        create_patient_account_payload(mrn="MRN-EN1"), manager_headers
    )
    account = validate_success(res, 201)
    assert_patient_account(account)
    assert account["status"] == "ADMITTED"
    assert account["dnfb_flag"] is False
    assert account["dnfb_flagged_at"] is None
    assert account["discharge_at"] is None
    assert is_valid_uuid(account["id"])
    assert isinstance(account["version"], int) and account["version"] >= 1


def test_list_accounts_pagination_envelope(api, clerk_headers, manager_headers):
    """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100." and "Paginated and non-paginated list-based responses
    include the following fields in the `meta` object of the response
    envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_accounts_pagination_envelope
    """
    make_account(
        "MRN-EN2",
        total_charges_cents=100000,
        patient_class="OBSERVATION",
        financial_class="SELF_PAY",
    )
    res = api.list_patient_accounts(clerk_headers)
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def test_chart_not_found_returns_404(api, manager_headers):
    """PRD §2.8: "a referenced resource that does not exist yields its
    dedicated 404: `ERR_ACCOUNT_NOT_FOUND` for patient accounts,
    `ERR_CHART_NOT_FOUND` for charts".

    Design: Corner/entities/chart_not_found_returns_404
    """
    res = api.get_chart(NON_EXISTENT_UUID, manager_headers)
    validate_error(res, ApiErrorId.ERR_CHART_NOT_FOUND, expected_status=404)


def test_create_account_missing_mrn_returns_invalid_request(api, manager_headers):
    """PRD §2.8: "malformed or missing input and invalid enum members
    (`ERR_INVALID_REQUEST`, HTTP 400)". PRD §3.1 requires the `mrn` at
    registration.

    Design: Corner/entities/create_account_missing_mrn_returns_invalid_request
    """
    payload = create_patient_account_payload(mrn="MRN-X")
    del payload["mrn"]
    res = api.create_patient_account(payload, manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_create_chart_unknown_account_not_found(api, manager_headers):
    """PRD §2.8: "a referenced resource that does not exist yields its
    dedicated 404: `ERR_ACCOUNT_NOT_FOUND` for patient accounts".

    Design: Corner/validations/create_chart_unknown_account_not_found
    """
    res = api.create_chart(
        {"account_id": NON_EXISTENT_UUID, "acuity": "MEDICAL_LOW"}, manager_headers
    )
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_FOUND, expected_status=404)


def test_chart_readies_after_last_deficiency_resolved(api, manager_headers):
    """PRD §3.1: "a discharge over outstanding deficiencies leaves the chart
    `OPEN` until a `CodingManager` resolves the last one, at which point the
    chart readies itself." and "Resolving a deficiency sets its `resolved_at`,
    moves it to `RESOLVED`, and decrements the count."

    Design: Corner/state_machines/chart_readies_after_last_deficiency_resolved
    """
    account = make_account("MRN-SM1")
    chart = make_chart(account["id"], acuity="MEDICAL_LOW")
    deficiency = get_success_data(
        api.create_deficiency(
            {
                "chart_id": chart["id"],
                "type": "MISSING_DISCHARGE_SUMMARY",
                "due_at": "2026-04-30T00:00:00Z",
            },
            manager_headers,
        )
    )
    account = discharge_account(account["id"])

    chart_mid = get_success_data(api.get_chart(chart["id"], manager_headers))
    assert chart_mid["status"] == "OPEN"
    assert chart_mid["open_deficiency_count"] == 1

    resolved = validate_success(
        api.resolve_deficiency(deficiency["id"], manager_headers), 200
    )
    assert_deficiency(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None

    chart_after = get_success_data(api.get_chart(chart["id"], manager_headers))
    assert_chart(chart_after)
    assert chart_after["status"] == "READY_FOR_CODING"
    assert chart_after["open_deficiency_count"] == 0
