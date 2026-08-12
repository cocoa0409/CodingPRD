"""Service-account ingest defaults, field validity, existence, and list surface."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_service_account,
    bootstrap_authority,
    create_account_spec,
    create_billing_extract_payload,
    create_ingest_payload,
    create_notice,
    get_account,
    ingest_accounts,
    issue_notice,
    set_clock,
    setup_active_authority,
    validate_error,
    validate_paginated,
    validate_success,
)

BD = TEST_USERS["board_director_headers"]
PO = TEST_USERS["program_operator_headers"]
CS = TEST_USERS["customer_service_headers"]
BC = TEST_USERS["billing_coordinator_headers"]


def test_service_account_ingest_defaults_and_atomic_duplicate_rejection(api):
    """PRD §3.3: "Every ingested account begins life as a `PROSPECT`, with `product_election` at `DEFAULT`, its cumulative billed and remitted ledgers at zero, and `uncollectible_flag` false."
    PRD §3.3: "Each ingested record carries the incumbent utility's `utility_account_number` (unique within the authority and immutable — a duplicate anywhere in the batch aborts the whole ingest atomically, all-or-nothing, with `ERR_UNIQUENESS_CONFLICT`), a `service_class` drawn from `RESIDENTIAL`, `SMALL_COMMERCIAL`, `LARGE_COMMERCIAL`, `INDUSTRIAL`, `AGRICULTURAL`, or `STREETLIGHT`, a forecast `annual_kwh_estimate` and `annual_peak_kw` (both at least zero), and a `da_eligible` flag."

    Design: Corner/entities/service_account_ingest_defaults_and_atomic_duplicate_rejection
    """
    bootstrap_authority()

    first = validate_success(
        api.ingest_service_accounts(
            create_ingest_payload([create_account_spec(utility_account_number="U-0001")]),
            PO,
        ),
        201,
    )
    assert first["ingested_count"] == 1

    account = validate_success(
        api.get_service_account(first["account_ids"][0], CS), 200
    )
    assert_service_account(account)
    assert account["enrollment_state"] == "PROSPECT"
    assert account["product_election"] == "DEFAULT"
    assert account["uncollectible_flag"] is False
    assert account["cumulative_billed_cents"] == 0
    assert account["cumulative_remitted_cents"] == 0

    # Second batch contains a duplicate of the existing U-0001: the whole batch
    # must abort atomically — U-0002 must not be ingested.
    dup = api.ingest_service_accounts(
        create_ingest_payload(
            [
                create_account_spec(utility_account_number="U-0002"),
                create_account_spec(
                    utility_account_number="U-0001", service_class="SMALL_COMMERCIAL"
                ),
            ]
        ),
        PO,
    )
    validate_error(dup, ApiErrorId.ERR_UNIQUENESS_CONFLICT)

    data, meta = validate_paginated(api.list_service_accounts(PO))
    assert meta["total_count"] == 1, (
        "atomic all-or-nothing rejection: U-0002 must not have been ingested"
    )


def test_enum_and_format_type_constraints(api):
    """PRD §2.9: "16. **Field-level validity** — bad enum values, non-positive quantities, malformed `YYYY-MM` strings, a delivery window whose end is not after its start, and missing required fields yield `ERR_INVALID_REQUEST`."

    Design: Corner/entities/enum_and_format_type_constraints
    """
    bootstrap_authority()

    for bad_month in ("2026-13", "2026-5"):
        res = api.create_billing_extract(
            create_billing_extract_payload(billing_month=bad_month), BC
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    bad_enum = api.ingest_service_accounts(
        create_ingest_payload(
            [create_account_spec(utility_account_number="U-B01", service_class="MUNICIPAL")]
        ),
        PO,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)


def test_entity_not_found_returns_404(api):
    """PRD §2.9: "3. **Path existence** — path-parameter resources are validated left to right (product before schedule, extract before line, notice before the accounts in its sweep); the first missing id yields `ERR_NOT_FOUND`."

    Design: Corner/entities/entity_not_found_returns_404
    """
    bootstrap_authority()

    res = api.get_service_account(NON_EXISTENT_UUID, CS)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_list_pagination_envelope_fields(api):
    """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/endpoints/list_pagination_envelope_fields
    """
    bootstrap_authority()
    specs = [
        create_account_spec(utility_account_number=f"U-P{i:02d}") for i in range(1, 13)
    ]
    ingested = validate_success(
        api.ingest_service_accounts(create_ingest_payload(specs), PO), 201
    )
    assert ingested["ingested_count"] == 12

    first_page = api.list_service_accounts(PO)
    data, meta = validate_paginated(first_page)
    assert len(data) == 10, "default limit is 10"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    body = first_page.json()
    assert body["response_type"] == "array"
    assert body["meta"]["api_request_id"].startswith("req_")

    data2, meta2 = validate_paginated(
        api.list_service_accounts(PO, params={"limit": 10, "offset": 10})
    )
    assert len(data2) == 2
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 12


def test_notice_issue_sweeps_only_target_class_prospects(api):
    """PRD §3.2: "On a successful issue, the system sweeps every service account that is still a `PROSPECT`, is not direct-access eligible, and whose `service_class` is in the wave's target set, transitioning each to `NOTICED` and stamping its `current_enrollment_notice_id` with this notice."
    PRD §3.2: "The wave's `account_count_noticed` is set to the sweep count, and issuance increments the Authority's `version` by 1."

    Design: Corner/endpoints/filtered_list_by_enrollment_state
    """
    setup_active_authority()
    ids = ingest_accounts(
        [
            create_account_spec(utility_account_number="U-F01"),
            create_account_spec(utility_account_number="U-F02"),
            create_account_spec(
                utility_account_number="U-F03",
                service_class="STREETLIGHT",
                annual_kwh_estimate=5000,
                annual_peak_kw=1.0,
            ),
        ]
    )
    notice = create_notice(target_service_classes=("RESIDENTIAL",))
    issued = issue_notice(notice["id"])
    assert issued["account_count_noticed"] == 2, (
        "only the two RESIDENTIAL PROSPECT accounts are swept"
    )

    for account_id in (ids[0], ids[1]):
        account = get_account(account_id)
        assert account["enrollment_state"] == "NOTICED"
        assert account["current_enrollment_notice_id"] == notice["id"]

    streetlight = get_account(ids[2])
    assert streetlight["enrollment_state"] == "PROSPECT", (
        "STREETLIGHT account is outside the wave's target set"
    )
    assert streetlight.get("current_enrollment_notice_id") is None
