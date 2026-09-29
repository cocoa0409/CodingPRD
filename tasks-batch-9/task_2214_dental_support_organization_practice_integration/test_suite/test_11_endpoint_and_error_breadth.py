"""Endpoint and error breadth: the create-then-read round trip, a filtered
listing paged past its own limit, the enrollment reachable from both parents,
the read that computes without writing, the action that touches only its own
row, and the two error answers the request gauntlet owes a client."""

import pytest

from test_helpers import (
    COUNSEL,
    FINANCE,
    LEAD,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    ApiErrorId,
    api_client,
    assert_batch_record_ledger,
    assert_conversion_vendor,
    assert_migration_batch,
    assert_payer_contract,
    assert_payer_enrollment,
    assert_practice,
    assert_success_envelope_meta,
    build_closed_deal,
    build_scheduled_batch,
    create_conversion_vendor_payload,
    create_payer_contract,
    create_payer_enrollment,
    no_identity_headers,
    practice_version,
    read_employment,
    read_migration_batch,
    read_payer_contract,
    read_practice,
    reconcile_batch,
    set_clock,
    validate_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOSE_DAY = "2026-09-01T00:00:00Z"
CUTOVER_START = "2026-09-05T00:00:00Z"
CUTOVER_END = "2026-09-06T00:00:00Z"
INSIDE_WINDOW = "2026-09-05T12:00:00Z"
ENROLLMENT_EFFECTIVE = "2027-02-13T00:00:00Z"


@pytest.fixture
def practice_with_a_validated_batch():
    """A closed deal whose only batch validated 4,900 of 5,000 charts."""
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    batch = build_scheduled_batch(
        ctx["practice_id"],
        CUTOVER_START,
        CUTOVER_END,
        batch_label="BATCH-01",
        records_total=5000,
    )
    set_clock(INSIDE_WINDOW)
    ctx["batch"] = validate_batch(batch["id"], 100)
    return ctx


def test_a_vendor_read_echoes_the_create_response():
    """PRD §3.1: "A vendor is created with a `name` and a `max_concurrent_windows` crew capacity of at least one, and its `active_window_count` starts at zero."
    PRD §2.2: "The `data` field contains the resource object or an array of resource objects."

    Design: Corner/endpoints/conversion_vendor_create_and_read_round_trip
    """
    set_clock(CLOSE_DAY)
    response = api_client.create_conversion_vendor(create_conversion_vendor_payload(), LEAD)
    created = validate_success(response, expected_status=201)
    body = response.json()
    assert body["response_type"] == "object"
    assert_success_envelope_meta(body["meta"])

    assert_conversion_vendor(created)
    assert created["name"] == "ChartBridge Conversions"
    assert created["max_concurrent_windows"] == 3
    assert created["active_window_count"] == 0
    assert created["version"] == 1

    read_response = api_client.get_conversion_vendor(created["id"], LEAD)
    read = validate_success(read_response, expected_status=200)
    assert read_response.json()["response_type"] == "object"
    assert read == created
    assert read["created_at"].startswith("2026-09-01T00:00:00")
    assert read["updated_at"] == read["created_at"]


def test_paging_a_practices_contracts_keeps_reporting_the_whole_count():
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object; `total_count` counts the rows matching the filter before pagination is applied, and `has_more` is true when rows remain beyond the current page."
    PRD §2.3: "Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order."

    Design: Corner/endpoints/payer_contract_listing_honours_limit_offset_and_has_more
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    first = create_payer_contract(ctx["practice_id"], payer_name="Statewide Dental Plan")
    second = create_payer_contract(
        ctx["practice_id"], payer_name="Prairie Dental Benefits"
    )
    third = create_payer_contract(
        ctx["practice_id"], payer_name="Lakeshore Dental Trust"
    )

    page_one_response = api_client.list_payer_contracts(
        FINANCE, {"practice_id": ctx["practice_id"], "limit": 2, "offset": 0}
    )
    page_one, meta_one = validate_paginated(page_one_response)
    assert page_one_response.json()["response_type"] == "array"
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [first["id"], second["id"]]

    page_two, meta_two = validate_paginated(
        api_client.list_payer_contracts(
            FINANCE, {"practice_id": ctx["practice_id"], "limit": 2, "offset": 2}
        )
    )
    assert meta_two["total_count"] == 3
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False
    assert [row["id"] for row in page_two] == [third["id"]]

    for row in page_one + page_two:
        assert_payer_contract(row)
        assert row["transition_state"] == "LEGACY"


def test_one_enrollment_is_reachable_from_both_of_its_parents():
    """PRD §3.6: "A new enrollment opens in `NOT_STARTED` with `submission_round` at zero, no `lead_days`, no `submitted_at`, no `decided_at` and no `denial_reason`; it increments its contract's `enrollment_open_count` and `version`, and moves a `LEGACY` contract to `PENDING_CREDENTIALING`."
    PRD §3.4: "The precedence ladder is: if the employment has no enrollments at all, the rollup is `PENDING`; otherwise, if any one enrollment is `DENIED`, the rollup is `DENIED`; otherwise, if every enrollment is `APPROVED`, the rollup is `APPROVED`; otherwise, if any enrollment is `SUBMITTED`, the rollup is `SUBMITTED`; otherwise the rollup is `PENDING`."

    Design: Corner/endpoints/payer_enrollment_links_a_contract_and_an_employment
    """
    ctx = build_closed_deal(clock_utc=CLOSE_DAY)
    contract = create_payer_contract(ctx["practice_id"])
    assert contract["transition_state"] == "LEGACY"

    enrollment = create_payer_enrollment(
        contract["id"], ctx["employment_id"], ENROLLMENT_EFFECTIVE
    )
    assert_payer_enrollment(enrollment)
    assert enrollment["status"] == "NOT_STARTED"
    assert enrollment["submission_round"] == 0
    assert enrollment["lead_days"] is None
    assert enrollment["term_date"] is None

    by_contract, contract_meta = validate_paginated(
        api_client.list_payer_enrollments(LEAD, {"payer_contract_id": contract["id"]})
    )
    by_employment, employment_meta = validate_paginated(
        api_client.list_payer_enrollments(LEAD, {"doctor_employment_id": ctx["employment_id"]})
    )
    assert contract_meta["total_count"] == 1
    assert employment_meta["total_count"] == 1
    assert by_contract[0]["id"] == enrollment["id"]
    assert by_employment[0]["id"] == enrollment["id"]

    reread = read_payer_contract(contract["id"])
    assert reread["enrollment_open_count"] == 1
    assert reread["transition_state"] == "PENDING_CREDENTIALING"
    assert read_employment(ctx["employment_id"])["credentialing_status"] == "PENDING"


def test_reading_the_posture_twice_advances_nothing(practice_with_a_validated_batch):
    """PRD §2.6: "It is derived from the practice's own `affiliation_status`, its five integration counters and its chart target, and it is recomputed on every write that changes any of those inputs."
    PRD §2.4: "- `version` (integer): an integer that increments by one on every mutation of the row."

    Design: Corner/endpoints/computed_read_of_practice_posture_is_side_effect_free
    """
    ctx = practice_with_a_validated_batch

    first = read_practice(ctx["practice_id"], LEAD)
    second = read_practice(ctx["practice_id"], FINANCE)

    for view in (first, second):
        assert_practice(view)
        assert view["charts_migrated_count"] == 4900
        assert view["quarantined_batch_count"] == 0
        assert view["active_doctor_count"] == 1
        assert view["integration_posture"] == "STABILIZING"
        assert view["clinical_coverage_gap"] is False
        assert view["staffing_model_state"] == "LEGACY"

    assert first["version"] == second["version"]
    assert first["updated_at"] == second["updated_at"]


def test_reconciling_freezes_the_batch_and_leaves_the_practice_alone(
    practice_with_a_validated_batch
):
    """PRD §3.5: "The batch moves `VALIDATED → RECONCILED`, its `version` increments by one, and the practice's `charts_migrated_count` keeps counting that batch's `records_validated`, since reconciled batches remain inside the practice-level roll-up."
    PRD §2.8: "The practice-level invariant is that `charts_migrated_count` equals the sum of `records_validated` over that practice's batches whose status is `VALIDATED` or `RECONCILED`."

    Design: Corner/endpoints/reconcile_action_returns_the_updated_batch_without_touching_the_practice
    """
    ctx = practice_with_a_validated_batch
    practice_version_before = practice_version(ctx["practice_id"])
    batch_version_before = read_migration_batch(ctx["batch"]["id"])["version"]

    reconciled = reconcile_batch(ctx["batch"]["id"])

    assert_migration_batch(reconciled)
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["records_validated"] == 4900
    assert reconciled["records_quarantined"] == 100
    assert reconciled["records_pending"] == 0
    assert reconciled["validation_error_rate_bps"] == 200
    assert reconciled["version"] == batch_version_before + 1
    assert_batch_record_ledger(reconciled)

    practice = read_practice(ctx["practice_id"])
    assert practice["version"] == practice_version_before
    assert practice["charts_migrated_count"] == 4900


def test_ten_unknown_identifiers_answer_with_ten_distinct_codes():
    """PRD §2.10: "Templated path segments are resolved strictly left to right, and the first segment that does not name an existing row terminates the request with the 404 code belonging to the entity that the collection segment names: `ERR_AFFILIATION_NOT_FOUND`, `ERR_PRACTICE_NOT_FOUND`, `ERR_DOCTOR_NOT_FOUND`, `ERR_CONVERSION_VENDOR_NOT_FOUND`, `ERR_DOCTOR_EMPLOYMENT_NOT_FOUND`, `ERR_SERVICE_AGREEMENT_NOT_FOUND`, `ERR_MIGRATION_BATCH_NOT_FOUND`, `ERR_PAYER_CONTRACT_NOT_FOUND`, `ERR_PAYER_ENROLLMENT_NOT_FOUND`, `ERR_EARNOUT_TRANCHE_NOT_FOUND`, `ERR_SUPPLY_EXCEPTION_NOT_FOUND`, `ERR_VENDOR_CONSOLIDATION_NOT_FOUND` or `ERR_QUALITY_REVIEW_NOT_FOUND`."
    PRD §2.11: "4. Path-resource existence, resolved left to right — the entity's 404 code."

    Design: Corner/errors/every_entity_lookup_returns_its_own_not_found_code
    """
    set_clock(CLOSE_DAY)
    lookups = [
        (api_client.get_practice, ApiErrorId.ERR_PRACTICE_NOT_FOUND),
        (api_client.get_doctor, ApiErrorId.ERR_DOCTOR_NOT_FOUND),
        (api_client.get_doctor_employment, ApiErrorId.ERR_DOCTOR_EMPLOYMENT_NOT_FOUND),
        (api_client.get_service_agreement, ApiErrorId.ERR_SERVICE_AGREEMENT_NOT_FOUND),
        (api_client.get_migration_batch, ApiErrorId.ERR_MIGRATION_BATCH_NOT_FOUND),
        (api_client.get_payer_enrollment, ApiErrorId.ERR_PAYER_ENROLLMENT_NOT_FOUND),
        (api_client.get_earnout_tranche, ApiErrorId.ERR_EARNOUT_TRANCHE_NOT_FOUND),
        (api_client.get_supply_preference_exception, ApiErrorId.ERR_SUPPLY_EXCEPTION_NOT_FOUND),
        (api_client.get_vendor_consolidation, ApiErrorId.ERR_VENDOR_CONSOLIDATION_NOT_FOUND),
        (api_client.get_clinical_quality_review, ApiErrorId.ERR_QUALITY_REVIEW_NOT_FOUND),
    ]

    observed = []
    for reader, expected in lookups:
        error = validate_error(
            reader(UNKNOWN_UUID_ALT, LEAD), expected.value, 404
        )
        observed.append(error["error_id"])

    assert observed == [expected.value for _, expected in lookups]
    assert len(set(observed)) == 10


def test_a_missing_identity_is_refused_before_the_payload_is_read():
    """PRD §2.1: "If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` before any resource is looked up."
    PRD §2.11: "1. Identity headers present and non-empty on every endpoint — `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/unauthenticated_write_returns_401_before_any_other_check
    """
    set_clock(CLOSE_DAY)
    invalid_payload = create_conversion_vendor_payload(max_concurrent_windows=-4)

    validate_error(
        api_client.create_conversion_vendor(invalid_payload, no_identity_headers()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    for unknown in (UNKNOWN_UUID, UNKNOWN_UUID_ALT):
        validate_error(
            api_client.get_conversion_vendor(unknown, COUNSEL),
            ApiErrorId.ERR_CONVERSION_VENDOR_NOT_FOUND.value,
            404,
        )
