"""Program setup, household/landlord registration, and creation-time validation.

Translates SCAFFOLD_CORNER_DESIGN.yaml queue-B entity instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    make_tenant_headers, make_landlord_headers,
    create_program_payload, create_tenant_payload, create_landlord_payload,
    create_unit_payload, create_application_payload,
    income_source_payload, ledger_payload,
    set_clock,
    assert_program, assert_tenant, assert_income_source,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_create_program_initializes_remaining_equal_to_total(api):
    """PRD §3.1: "On creation the remaining pool is initialized equal to the total,
    and `status` is set to `OPEN`, or to `EXHAUSTED` immediately if the total is zero."

    Design: Corner/entities/create_program_returns_201_with_remaining_equals_total
    """
    set_clock(api)
    resp = api.create_program(create_program_payload(
        name="ERAP-New", funding_pool_total_cents=500000,
        monthly_income_limit_by_size={"1": 500000}), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["funding_pool_remaining_cents"] == 500000
    assert data["status"] == "OPEN"
    assert_program(data)


def test_program_with_zero_funding_starts_exhausted(api):
    """PRD §3.1: "On creation the remaining pool is initialized equal to the total,
    and `status` is set to `OPEN`, or to `EXHAUSTED` immediately if the total is zero."

    Design: Corner/entities/program_zero_funding_starts_exhausted
    """
    resp = api.create_program(create_program_payload(
        name="ERAP-Zero", funding_pool_total_cents=0,
        monthly_income_limit_by_size={"1": 500000}), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "EXHAUSTED"
    assert data["funding_pool_remaining_cents"] == 0


def test_new_tenant_months_used_defaults_to_zero(api):
    """PRD §3.2: "The household is created with `months_used` initialized to 0."

    Design: Corner/entities/tenant_months_used_system_default_zero
    """
    resp = api.create_tenant(create_tenant_payload(
        full_name="T New", email="tn@x.com", household_size=3))
    data = validate_success(resp, expected_status=201)
    assert data["months_used"] == 0
    assert_tenant(data)


def test_income_source_countable_computed_from_wages_type(api):
    """PRD §3.4: "Each source carries a computed `countable` flag: it is true for
    `WAGES`, `SELF_EMPLOYMENT`, and `UNEMPLOYMENT`, and false for `SSI`, `TANF`,
    and `CHILD_SUPPORT`, which are excluded from the area-median-income comparison."

    Design: Corner/entities/income_source_countable_computed_from_type
    """
    pid = get_success_data(api.create_program(create_program_payload(
        monthly_income_limit_by_size={"2": 566667}), ADMIN))["id"]
    tid = get_success_data(api.create_tenant(create_tenant_payload(household_size=2)))["id"]
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    lh = make_landlord_headers(lid)
    uid = get_success_data(api.create_unit(create_unit_payload(lid), lh))["id"]
    th = make_tenant_headers(tid)
    aid = get_success_data(api.create_application(create_application_payload(
        pid, tid, lid, uid, requested_prospective_months=1,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31"), th))["id"]

    resp = api.add_income_source(aid, income_source_payload("WAGES", 400000), th)
    data = validate_success(resp, expected_status=201)
    assert data["countable"] is True
    assert_income_source(data)


def test_fetch_unknown_application_returns_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve produces the matching
    not-found error for that resource type — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_TENANT_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_LEDGER_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`,
    `ERR_RECERT_NOT_FOUND`, or `ERR_RECAPTURE_NOT_FOUND` — each carrying HTTP 404."

    Design: Corner/entities/application_not_found_returns_404
    """
    resp = api.get_application(NON_EXISTENT_UUID, TEST_USERS["caseworker_headers"])
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, expected_status=404)


def test_create_application_missing_program_id_is_invalid_request(api):
    """PRD §2.6: "Structural payload validation — required fields present, enum values
    drawn from the declared sets, integers and dates well-formed, and declared numeric
    constraints satisfied — is reported as `ERR_INVALID_REQUEST` (HTTP 400) and is the
    lowest-priority family, applying to all write endpoints."

    Design: Corner/entities/create_application_missing_required_field_returns_invalid_request
    """
    tid = get_success_data(api.create_tenant(create_tenant_payload(household_size=2)))["id"]
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    uid = get_success_data(api.create_unit(create_unit_payload(lid), make_landlord_headers(lid)))["id"]
    payload = {
        "tenant_id": tid, "landlord_id": lid, "unit_id": uid,
        "monthly_rent_cents": 200000, "requested_prospective_months": 1,
    }  # program_id omitted
    resp = api.create_application(payload, make_tenant_headers(tid))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_create_application_unit_landlord_mismatch_rejected(api):
    """PRD §3.3: "The named unit's `landlord_id` must equal the application's
    `landlord_id`; a mismatch is rejected at creation with `ERR_UNIT_LANDLORD_MISMATCH`
    (HTTP 422)."

    Design: Corner/entities/create_application_unit_landlord_mismatch_rejected
    """
    pid = get_success_data(api.create_program(create_program_payload(
        monthly_income_limit_by_size={"2": 566667}), ADMIN))["id"]
    tid = get_success_data(api.create_tenant(create_tenant_payload(household_size=2)))["id"]
    lid1 = get_success_data(api.create_landlord(create_landlord_payload(email="l1@x.com")))["id"]
    lid2 = get_success_data(api.create_landlord(create_landlord_payload(email="l2@x.com")))["id"]
    uid1 = get_success_data(api.create_unit(create_unit_payload(lid1), make_landlord_headers(lid1)))["id"]

    resp = api.create_application(create_application_payload(
        pid, tid, lid2, uid1, requested_prospective_months=1,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31"),
        make_tenant_headers(tid))
    validate_error(resp, ApiErrorId.ERR_UNIT_LANDLORD_MISMATCH.value, expected_status=422)


def test_second_ledger_for_application_rejected(api):
    """PRD §3.5: "A second ledger for the same application is rejected with
    `ERR_LEDGER_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/entities/second_ledger_for_application_returns_already_exists
    """
    pid = get_success_data(api.create_program(create_program_payload(
        monthly_income_limit_by_size={"2": 566667}), ADMIN))["id"]
    tid = get_success_data(api.create_tenant(create_tenant_payload(household_size=2)))["id"]
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    lh = make_landlord_headers(lid)
    uid = get_success_data(api.create_unit(create_unit_payload(lid), lh))["id"]
    aid = get_success_data(api.create_application(create_application_payload(
        pid, tid, lid, uid, requested_prospective_months=1,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31"),
        make_tenant_headers(tid)))["id"]
    get_success_data(api.create_ledger(aid, ledger_payload([]), lh))

    resp = api.create_ledger(aid, ledger_payload([]), lh)
    validate_error(resp, ApiErrorId.ERR_LEDGER_ALREADY_EXISTS.value, expected_status=409)
