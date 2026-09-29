"""The release gate chain, the fiscal gates, the residual timing gate and the
identity rules that guard the whole API."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    build_cycle_scenario,
    close_dosimetry,
    create_customer,
    create_lot,
    create_lot_payload,
    create_product,
    create_product_payload,
    fetch_aeration_record,
    get_customer,
    get_cycle,
    get_lot,
    make_customer_rep_headers,
    officer,
    open_aeration_record,
    place_indicator,
    record_residual_test,
    release_lot,
    set_clock,
    set_customer_status,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["regulatory_admin_headers"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

BI_RECIPE = {
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 1,
}


def test_a_request_without_identity_headers_is_unauthenticated():
    """PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which they
    act."
    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of
    those five strings, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/corner_missing_auth_headers_returns_unauthenticated
    """
    response = api_client.get_customer(UNKNOWN_UUID, {"Content-Type": "application/json"})

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.json()["response_type"] == "error"


def test_parametric_release_is_refused_when_the_recipe_demands_a_biological_indicator():
    """PRD 3.9: "Next, the two release modes are checked against their own
    eligibility rules: a `PARAMETRIC` release is permitted only when the
    governing cycle's recipe has `required_biological_indicators` equal to 0,
    and is otherwise refused with `ERR_PARAMETRIC_NOT_PERMITTED`; a
    `DOSIMETRIC` release requires every `BIOLOGICAL` indicator on the governing
    cycle to have `reading_status` `READ`, and is otherwise refused with
    `ERR_BI_INCUBATION_PENDING`."

    Design: Corner/validations/corner_parametric_release_refused_when_recipe_requires_biological_indicators
    """
    env = build_cycle_scenario(
        stage="closed", recipe_overrides=BI_RECIPE, bi_result="NEGATIVE"
    )

    refused = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer()
    )
    validate_error(refused, ApiErrorId.ERR_PARAMETRIC_NOT_PERMITTED)

    released = release_lot(env["lot"]["id"], "DOSIMETRIC")

    assert released["release_mode"] == "DOSIMETRIC"
    assert released["status"] == "RELEASED"
    assert released["release_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert get_customer(env["customer"]["id"])["open_lot_count"] == 0


def test_dosimetric_release_is_refused_while_a_biological_indicator_is_unread():
    """PRD 3.9: "a `DOSIMETRIC` release requires every `BIOLOGICAL` indicator
    on the governing cycle to have `reading_status` `READ`, and is otherwise
    refused with `ERR_BI_INCUBATION_PENDING`."
    PRD 3.5: "Every indicator is born with `reading_status` `UNREAD`,
    `bi_result` `PENDING`, and `measured_dose_kgy`, `read_at` and
    `read_by_user_id` all null."

    Design: Corner/validations/corner_dosimetric_release_requires_every_biological_indicator_read
    """
    env = build_cycle_scenario(
        stage="closed", recipe_overrides=BI_RECIPE, bi_result="NEGATIVE"
    )
    second_bi = place_indicator(
        env["position"]["id"],
        indicator_type="BIOLOGICAL",
        placement_zone="ROUTINE",
        serial_code="B-002",
        spore_population=1000000,
    )
    assert second_bi["reading_status"] == "UNREAD"
    assert second_bi["bi_result"] == "PENDING"

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "DOSIMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_BI_INCUBATION_PENDING)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["release_mode"] == "NONE"


def test_a_suspended_customer_cannot_book_new_lots():
    """PRD 3.4: "A customer whose `status` is `SUSPENDED` may not book lots at
    all, and the attempt is refused with `ERR_CUSTOMER_SUSPENDED`."

    Design: Corner/validations/corner_suspended_customer_cannot_receive_new_lots
    """
    env = setup_reference_data(qualify=False)
    set_customer_status(env["customer"]["id"], "SUSPENDED")

    response = api_client.create_lot(
        create_lot_payload(env["customer"]["id"], env["product"]["id"]),
        make_customer_rep_headers(env["customer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_SUSPENDED)
    customer = get_customer(env["customer"]["id"])
    assert customer["status"] == "SUSPENDED"
    assert customer["open_lot_count"] == 0
    _, meta = validate_paginated(
        api_client.list_lots(ADMIN, params={"customer_id": env["customer"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_suspended_customer_blocks_release_at_the_last_gate():
    """PRD 3.9: "Last, the owning customer must be `ACTIVE`, with a suspended
    account refused as `ERR_CUSTOMER_SUSPENDED`."
    PRD 3.1: "The administrator may move an account between those two values at
    any time, and a `SUSPENDED` account may neither receive new lots into the
    facility nor have any of its lots released — both attempts are refused with
    `ERR_CUSTOMER_SUSPENDED`."

    Design: Corner/validations/corner_suspended_customer_blocks_release_at_the_last_gate
    """
    env = build_cycle_scenario(stage="closed")
    set_customer_status(env["customer"]["id"], "SUSPENDED")

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_SUSPENDED)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["release_mode"] == "NONE"
    assert lot["released_at"] is None
    assert get_customer(env["customer"]["id"])["open_lot_count"] == 1


def test_release_by_either_stamped_identity_violates_segregation_of_duties():
    """PRD 2.10: "A lot is released by a `QualityReleaseOfficer`, and the
    officer's `X-User-ID` must differ from both `operator_user_id` and
    `dosimetry_closed_by_user_id` on the lot's governing cycle."
    PRD 2.10: "The rule is symmetric — matching either stamped identity is
    disqualifying — and it applies to no operation other than release."
    PRD 3.9: "Next comes the segregation-of-duties test of §2.10, refusing with
    `ERR_SEGREGATION_OF_DUTIES` when the officer's `X-User-ID` matches either
    the governing cycle's `operator_user_id` or its
    `dosimetry_closed_by_user_id`."

    Design: Corner/validations/corner_release_by_the_cycle_operator_identity_violates_segregation_of_duties
    """
    env = build_cycle_scenario(stage="closed")
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["operator_user_id"] == "op-1"
    assert cycle["dosimetry_closed_by_user_id"] == "ana-1"

    as_operator = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer("op-1")
    )
    validate_error(as_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    as_analyst = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer("ana-1")
    )
    validate_error(as_analyst, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    released = release_lot(env["lot"]["id"], "PARAMETRIC", officer_user_id="qro-1")

    assert released["released_by_user_id"] == "qro-1"
    assert released["status"] == "RELEASED"


def test_schema_validation_is_reported_before_a_missing_body_foreign_key():
    """PRD 2.7: "**Payload schema.** On every write, required fields are
    present, types are correct, enum members are recognised and numeric ranges
    hold"
    PRD 2.7: "**Body foreign keys.** Every foreign key supplied in a request
    body must resolve, each raising its own 404: `customer_id` raises
    `ERR_CUSTOMER_NOT_FOUND`, `product_id` raises `ERR_PRODUCT_NOT_FOUND`,
    `permit_id` raises `ERR_PERMIT_NOT_FOUND`, `recipe_id` raises
    `ERR_RECIPE_NOT_FOUND`, `chamber_id` raises `ERR_CHAMBER_NOT_FOUND` and
    `lot_id` raises `ERR_LOT_NOT_FOUND`."
    PRD 2.7: "Requests are screened in a strictly ascending order of checks,
    and the **first** check that fails determines the error returned."

    Design: Corner/validations/corner_schema_validation_outranks_body_foreign_key_existence
    """
    set_clock("2026-08-10T00:00:00Z")
    payload = create_product_payload(UNKNOWN_UUID)
    payload.pop("pallet_mass_kg")

    response = api_client.create_product(payload, ADMIN)

    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_aeration_record_is_not_applicable_to_a_gamma_lot():
    """PRD 3.8: "A lot whose `residual_status` is `NOT_APPLICABLE` has no
    degassing obligation at all and the attempt is refused with
    `ERR_AERATION_NOT_APPLICABLE`."
    PRD 3.6: "Lots of gamma or electron-beam work, and lots of products that do
    not require aeration, stay at `NOT_APPLICABLE` forever and are releasable
    on the residual axis without any further step."

    Design: Corner/validations/corner_aeration_record_not_applicable_for_a_gamma_lot
    """
    env = build_cycle_scenario(stage="closed")
    assert get_lot(env["lot"]["id"])["residual_status"] == "NOT_APPLICABLE"

    response = api_client.create_aeration_record(env["lot"]["id"], TEST_USERS["cycle_operator_headers"])

    validate_error(response, ApiErrorId.ERR_AERATION_NOT_APPLICABLE)
    assert get_lot(env["lot"]["id"])["residual_status"] == "NOT_APPLICABLE"
    _, meta = validate_paginated(
        api_client.list_aeration_records(env["lot"]["id"], TEST_USERS["cycle_operator_headers"])
    )
    assert meta["total_count"] == 0


def test_residual_sample_one_second_early_is_refused():
    """PRD 3.8: "`target_end_at` is the earliest instant at which the
    laboratory may sample."
    PRD 3.8: "If the logical clock has not yet reached the record's
    `target_end_at`, the sample is refused with `ERR_AERATION_INCOMPLETE`."

    Design: Corner/validations/corner_residual_test_before_target_end_rejected
    """
    env = build_cycle_scenario(
        stage="closed", modality="ETO", product_overrides={"requires_aeration": True}
    )
    set_clock("2026-08-12T08:00:00Z")
    record = open_aeration_record(env["lot"]["id"])
    set_clock("2026-08-12T22:59:59Z")

    early = api_client.record_residual_test(
        record["id"],
        {"eto_residual_ppm": 1.0, "ech_residual_ppm": 1.0},
        TEST_USERS["dosimetry_analyst_headers"],
    )

    validate_error(early, ApiErrorId.ERR_AERATION_INCOMPLETE)
    unchanged = fetch_aeration_record(env["lot"]["id"], record["id"])
    assert unchanged["status"] == "IN_PROGRESS"
    assert unchanged["retest_count"] == 0
    assert unchanged["last_eto_ppm"] is None

    set_clock("2026-08-12T23:00:00Z")
    passed = record_residual_test(record["id"], eto_residual_ppm=1.0, ech_residual_ppm=1.0)

    assert passed["status"] == "PASSED"
    assert get_lot(env["lot"]["id"])["residual_status"] == "RESIDUAL_PASS"


def test_a_processed_lot_is_not_releasable():
    """PRD 3.9: "The chain begins with the lot's own posture: the lot must be
    in `QUARANTINE`, must not carry a `residual_status` of `RESIDUAL_FAIL`, and
    must have a governing cycle at all, with any of those three failures
    reported as `ERR_LOT_NOT_RELEASABLE`."

    Design: Corner/validations/corner_release_of_a_processed_lot_rejected
    """
    env = build_cycle_scenario(stage="completed")
    assert get_lot(env["lot"]["id"])["status"] == "PROCESSED"

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_LOT_NOT_RELEASABLE)
    assert get_lot(env["lot"]["id"])["status"] == "PROCESSED"
    assert get_cycle(env["cycle"]["id"])["status"] == "COMPLETED"


def test_a_deviated_governing_cycle_blocks_release():
    """PRD 3.9: "Next, the governing cycle's `status` must be
    `DOSE_CONFORMING`; a cycle still under review, or one parked in
    `DOSE_DEVIATION`, blocks release with
    `ERR_CYCLE_DEVIATION_BLOCKS_RELEASE`."

    Design: Corner/validations/corner_deviated_cycle_blocks_release
    """
    env = build_cycle_scenario(stage="review", min_zone_dose=19.00, routine_dose=20.00)
    deviated = close_dosimetry(env["cycle"]["id"])
    assert deviated["deviation_code"] == "UNDERDOSE"

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_CYCLE_DEVIATION_BLOCKS_RELEASE)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["quarantine_reason"] == "DOSE_DEVIATION"
    assert lot["schedulable"] is False


def test_a_residual_test_on_a_passed_record_is_refused():
    """PRD 3.8: "If the record has already reached `PASSED` or `EXHAUSTED`, no
    further sample is accepted and the attempt is refused with
    `ERR_RETEST_LIMIT_EXHAUSTED`."

    Design: Corner/validations/corner_residual_test_on_a_passed_record_rejected
    """
    env = build_cycle_scenario(
        stage="closed", modality="ETO", product_overrides={"requires_aeration": True}
    )
    set_clock("2026-08-12T08:00:00Z")
    record = open_aeration_record(env["lot"]["id"])
    set_clock("2026-08-12T23:00:00Z")
    record_residual_test(record["id"], eto_residual_ppm=1.0, ech_residual_ppm=1.0)

    response = api_client.record_residual_test(
        record["id"],
        {"eto_residual_ppm": 1.0, "ech_residual_ppm": 1.0},
        TEST_USERS["dosimetry_analyst_headers"],
    )

    validate_error(response, ApiErrorId.ERR_RETEST_LIMIT_EXHAUSTED)
    stored = fetch_aeration_record(env["lot"]["id"], record["id"])
    assert stored["status"] == "PASSED"
    assert stored["retest_count"] == 0
    assert get_lot(env["lot"]["id"])["residual_status"] == "RESIDUAL_PASS"


def test_a_customer_rep_cannot_read_another_customers_lot():
    """PRD 2.1: "When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of
    the acting `Customer`; ownership checks on any resource that references a
    `Customer` compare the resource's `customer_id` to `X-User-ID`."
    PRD 2.1: "In each of them, a `CustomerRep` whose `X-User-ID` differs from
    the `customer_id` of the addressed customer, of the product's owning
    customer, or of the lot's owning customer is rejected with
    `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/validations/corner_customer_rep_cannot_read_another_customers_lot
    """
    set_clock("2026-08-10T00:00:00Z")
    customer_a = create_customer(account_code="ACME-01")
    customer_b = create_customer(account_code="BETA-02")
    product_b = create_product(customer_b["id"], product_code="P2")
    lot_b = create_lot(customer_b["id"], product_b["id"], lot_code="L-B")

    response = api_client.get_lot(lot_b["id"], make_customer_rep_headers(customer_a["id"]))

    validate_error(response, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION)

    allowed = validate_success(
        api_client.get_lot(lot_b["id"], make_customer_rep_headers(customer_b["id"]))
    )
    assert allowed["id"] == lot_b["id"]
