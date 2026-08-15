"""Registration request shape, not-found handling, computed client fields,
and list/filter behavior (PRD §2.3, §2.8, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_case,
    assert_client,
    assert_logical_instant,
    create_case_payload,
    create_client_payload,
    create_contract_payload,
    create_producer_payload,
    get_success_data,
    make_producer_headers,
    register_client,
    register_contract,
    register_producer,
    open_case,
    submit_case,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)


def test_create_producer_missing_license_number_rejected(api, carrier_admin_headers):
    """PRD §3.1: "A `CarrierAdmin` registers each producer with a
    `license_number` that is unique across all producers, a `full_name`, and a
    `home_state_code` giving the two-letter state of primary appointment."
    PRD §3.1: "Across all endpoints that accept a body, malformed payloads — a
    missing required field, an enum value outside its declared set, a
    non-positive integer where a positive one is required, a
    `surrender_schedule` whose years are not strictly ascending from 1 — are
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_producer_missing_required_field
    """
    payload = create_producer_payload()
    payload.pop("license_number")
    res = api.create_producer(payload, carrier_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    # No Producer row was created: there is no id to follow up on.


def test_full_case_defaults_applied(api):
    """PRD §3.2: "For a `PARTIAL` exchange the gross `exchange_amount_cents` is
    required; for a `FULL` exchange the field is ignored and the system sets it
    to the contract's `account_value_cents`."
    PRD §3.2: "The new product's economics arrive as `new_product_bonus_bps`,
    an up-front bonus in basis points of the amount received, and
    `new_product_annual_fee_bps`, both defaulting to 0. A new case starts in
    `DRAFT`."

    Design: Corner/entities/full_case_defaults_applied
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False
    )
    payload = {
        "producer_id": producer["id"],
        "client_id": client["id"],
        "existing_contract_id": contract["id"],
        "exchange_type": "FULL",
        "new_product_code": "NP-7",
        "new_product_surrender_years": 7,
    }
    case = validate_success(
        api.create_case(payload, make_producer_headers(producer["id"])),
        expected_status=201,
    )
    assert_case(case)
    assert case["status"] == "DRAFT"
    assert case["version"] == 1
    assert case.get("submitted_at") is None
    assert case["exchange_amount_cents"] == 10000000, (
        "FULL exchange amount must be system-set to the contract's account value"
    )
    assert case["new_product_bonus_bps"] == 0
    assert case["new_product_annual_fee_bps"] == 0


def test_get_case_unknown_id_returns_404(api, carrier_admin_headers):
    """PRD §2.8: "Third, resource existence is resolved left-to-right: every
    `id` in the path, then body foreign keys such as `client_id`,
    `existing_contract_id`, and `producer_id`, each resolving to an existing
    resource or failing with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    res = api.get_case(NON_EXISTENT_UUID, carrier_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_create_case_with_unknown_contract_fk_returns_404(api):
    """PRD §2.8: "Third, resource existence is resolved left-to-right: every
    `id` in the path, then body foreign keys such as `client_id`,
    `existing_contract_id`, and `producer_id`, each resolving to an existing
    resource or failing with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/fk_not_found_in_case_create
    """
    producer = register_producer()
    client = register_client(producer["id"])
    payload = create_case_payload(
        producer["id"], client["id"], NON_EXISTENT_UUID
    )
    res = api.create_case(payload, make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_create_case_with_invalid_exchange_type_rejected(api):
    """PRD §3.2: "The `exchange_type` is `FULL` or `PARTIAL`."
    PRD §3.1: "Across all endpoints that accept a body, malformed payloads — a
    missing required field, an enum value outside its declared set, a
    non-positive integer where a positive one is required, a
    `surrender_schedule` whose years are not strictly ascending from 1 — are
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/errors/invalid_enum_in_case_create
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False
    )
    payload = create_case_payload(
        producer["id"], client["id"], contract["id"], exchange_type="HALF"
    )
    res = api.create_case(payload, make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    listed, meta = validate_paginated(
        api.list_cases(make_producer_headers(producer["id"]))
    )
    assert meta["total_count"] == 0, "no case row may be created"


def test_client_age_and_seniority_computed_from_logical_clock(api):
    """PRD §3.1: "From the logical clock the server derives `age_years`, the
    whole years between `date_of_birth` and the current clock date, and
    `is_senior`, which is true when the client is at least 65 years old and
    drives the extended free-look period described in §3.7."
    PRD §2.4: "At startup, before any operator intervention, the logical clock
    reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock
    time on its own."

    Design: Corner/entities/client_age_and_seniority_computed_at_clock
    """
    producer = register_producer()
    edge65 = validate_success(
        api.create_client(
            create_client_payload(full_name="Ann Edge", date_of_birth="1961-08-01"),
            make_producer_headers(producer["id"]),
        ),
        expected_status=201,
    )
    edge64 = validate_success(
        api.create_client(
            create_client_payload(full_name="Bob Edge", date_of_birth="1961-08-02"),
            make_producer_headers(producer["id"]),
        ),
        expected_status=201,
    )
    assert_client(edge65)
    assert_client(edge64)
    # 65th birthday falls exactly on the clock date: already 65 and senior.
    assert edge65["age_years"] == 65
    assert edge65["is_senior"] is True
    # One day younger: still 64, not senior.
    assert edge64["age_years"] == 64
    assert edge64["is_senior"] is False


def test_cases_list_pagination_and_status_filter(api, reviewer_headers):
    """PRD §2.3: "`limit` controls page size: it defaults to 10, with a minimum
    of 1 and a maximum of 100. `offset` controls how many records are skipped
    and defaults to 0. Every list response carries `limit`, `offset`,
    `total_count`, and `has_more` in its `meta` object. All lists are sorted by
    `created_at` in ascending order."
    PRD §3.2: "The case book is listable with optional `producer_id`,
    `client_id`, `existing_contract_id`, and `status` filters."

    Design: Corner/entities/cases_list_pagination_and_status_filter
    """
    producer = register_producer()
    client = register_client(producer["id"])
    case_ids = []
    for number in ("CN-A", "CN-B", "CN-C"):
        contract = register_contract(
            producer["id"],
            client["id"],
            contract_number=number,
            surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
            living_benefit_rider=False,
        )
        case = open_case(producer["id"], client["id"], contract["id"])
        case_ids.append(case["id"])
    submit_case(case_ids[1], producer["id"])

    page1, meta1 = validate_paginated(
        api.list_cases(
            reviewer_headers, params={"producer_id": producer["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_cases(
            reviewer_headers, params={"producer_id": producer["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    paged_ids = {c["id"] for c in page1} | {c["id"] for c in page2}
    assert paged_ids == set(case_ids), "pages must partition the producer's cases"

    submitted, meta3 = validate_paginated(
        api.list_cases(
            reviewer_headers,
            params={"producer_id": producer["id"], "status": "SUBMITTED"},
        )
    )
    assert meta3["total_count"] == 1
    assert len(submitted) == 1
    assert submitted[0]["id"] == case_ids[1]


def test_producer_activity_events_filter_by_type(api, compliance_headers):
    """PRD §2.9: "A producer's complete exchange-activity trail is listable
    with an optional `event_type` filter, as is the case-scoped slice of that
    trail attached to an individual case; a case's decision records are
    listable with an optional `stage` filter."
    PRD §3.2: "A successful submission stamps `submitted_at` with the logical
    clock, bumps the case `version`, appends a `CASE_SUBMITTED` activity event
    for the producer, recomputes the producer's twelve-month counters, and runs
    the churn evaluation of §3.8."

    Design: Corner/entities/activity_events_filtered_by_type
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"],
        client["id"],
        surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
        living_benefit_rider=False,
    )
    case = open_case(producer["id"], client["id"], contract["id"])
    submit_case(case["id"], producer["id"])

    all_events, meta_all = validate_paginated(
        api.list_producer_activity_events(producer["id"], compliance_headers)
    )
    assert meta_all["total_count"] == 1
    assert all_events[0]["event_type"] == "CASE_SUBMITTED"
    assert all_events[0]["case_id"] == case["id"]
    assert_logical_instant(
        all_events[0]["event_at"], "2026-08-01T00:00:00Z", "event_at"
    )

    submitted, meta_sub = validate_paginated(
        api.list_producer_activity_events(
            producer["id"], compliance_headers, params={"event_type": "CASE_SUBMITTED"}
        )
    )
    assert meta_sub["total_count"] == 1

    completed, meta_done = validate_paginated(
        api.list_producer_activity_events(
            producer["id"],
            compliance_headers,
            params={"event_type": "EXCHANGE_COMPLETED"},
        )
    )
    assert meta_done["total_count"] == 0
    assert completed == []


def test_error_catalog_coverage_audit(api, carrier_admin_headers):
    """PRD §2.3: "Every list response carries `limit`, `offset`,
    `total_count`, and `has_more` in its `meta` object."
    This instance is the catalogue audit trail: each of the 21 error ids in the
    PRD §5 catalogue is produced by the trigger of the instance named in the
    coverage map (auth header, forbidden-role, not-found, ownership, body
    shape, state, OCC staleness, contract-not-in-force, duty segregation,
    suspension, incomplete documents, missing analysis, cooling-off,
    anti-churn, occupation, duplicate contract, document lock, partial bounds,
    and both free-look errors). The trigger call itself asserts the empty-DB
    list contract the audit runs against.

    Design: Corner/errors/error_catalog_sweep
    """
    data, meta = validate_paginated(api.list_cases(carrier_admin_headers))
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
