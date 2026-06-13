"""Entity creation, required/typed fields, not-found, snapshots, system fields,
listing, pagination, and FK reverse-reachability.

Queue B (Corner) — section: entities.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_funeral_home, assert_case,
    create_funeral_home, create_gpl_item, create_disclosed_case, add_line,
    create_contract,
)

ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]


def test_create_funeral_home_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created funeral home begins with its computed
    trust_balance_cents at 0."
    PRD §3.1: "chapel_buffer_minutes, the mandatory cleanup buffer enforced
    between consecutive chapel bookings on the same venue, which must be at least
    0 and defaults to 30."
    PRD §2.4: "a version, an integer that starts at 1 on creation".

    Design: Corner/entities/create_funeral_home_returns_201_with_computed_trust_balance_zero
    """
    resp = api.create_funeral_home(
        {"name": "Rose Hill", "sales_tax_pct": 0.08, "state_trust_pct": 0.90}, ADMIN)
    home = validate_success(resp, expected_status=201)
    assert_funeral_home(home)
    assert home["trust_balance_cents"] == 0
    assert home["version"] == 1
    assert home["chapel_buffer_minutes"] == 30


def test_create_at_need_case_missing_date_of_death_rejected(api):
    """PRD §3.2: "An AT_NEED case requires date_of_death to be supplied ...
    omitting it on an at-need case, is a malformed request rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_case_at_need_missing_date_returns_invalid_request
    """
    home = create_funeral_home()
    resp = api.create_case(
        {"funeral_home_id": home["id"], "decedent_name": "Jane Doe",
         "case_mode": "AT_NEED"}, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_create_preneed_case_supplying_date_of_death_rejected(api):
    """PRD §3.2: "a PRENEED case must omit it (leaving it null). Supplying a date
    of death on a preneed case ... is a malformed request rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_case_preneed_supplying_date_returns_invalid_request
    """
    home = create_funeral_home()
    resp = api.create_case(
        {"funeral_home_id": home["id"], "decedent_name": "Jane Doe",
         "case_mode": "PRENEED", "date_of_death": "2026-06-01T00:00:00.000Z"}, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_gpl_item_bad_category_rejected(api):
    """PRD §2.9: "a missing required field, an invalid enum, an out-of-range
    integer, or a case-mode/date-of-death mismatch yields ERR_INVALID_REQUEST
    (HTTP 422)."
    PRD §3.1: "a category that is either SERVICE or MERCHANDISE".

    Design: Corner/entities/create_gpl_item_bad_category_enum_returns_invalid_request
    """
    home = create_funeral_home()
    resp = api.create_gpl_item(
        {"funeral_home_id": home["id"], "code": "X", "name": "Bad",
         "category": "FLOWERS", "unit_price_cents": 100}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_case_unknown_id_returns_not_found(api):
    """PRD §2.5: "The first identifier in the path that does not resolve to an
    existing resource causes immediate rejection with ERR_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/get_case_non_existent_id_returns_not_found
    """
    resp = api.get_case(NON_EXISTENT_UUID, ARRANGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_statement_line_price_snapshot_immune_to_later_gpl_change(api):
    """PRD §3.3: "its category, taxable, non_declinable, preneed_trustable, and
    unit_price_cents are each snapshotted from the corresponding item field, so
    later catalog price changes never disturb an existing line."
    PRD §3.1: "Such an update never retroactively changes statement lines already
    snapshotted from the item".

    A line added at 150000 stays 150000 after the GPL item is repriced to 999999.

    Design: Corner/entities/statement_line_snapshots_price_ignoring_later_gpl_change
    """
    home = create_funeral_home()
    casket = create_gpl_item(home["id"], code="CASKET-A", name="Oak casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             preneed_trustable=True, unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    line = add_line(case["id"], casket["id"])

    get_success_data(api.update_gpl_item(casket["id"], {"unit_price_cents": 999999}, ADMIN))
    snap = validate_success(api.get_statement_line(line["id"], ARRANGER))
    assert snap["unit_price_cents"] == 150000


def test_case_create_mints_system_fields(api):
    """PRD §3.2: "A newly opened case starts with arrangement_status of INTAKE,
    interment_status of NOT_READY, disclosure_acknowledged false, and gfs_issued
    false ... and its version begins at 1."

    Design: Corner/entities/system_fields_minted_input_ignored_on_case_create
    """
    home = create_funeral_home()
    case = validate_success(api.create_case(
        {"funeral_home_id": home["id"], "decedent_name": "Jane Doe",
         "case_mode": "PRENEED"}, ARRANGER), expected_status=201)
    assert_case(case)
    assert case["arrangement_status"] == "INTAKE"
    assert case["interment_status"] == "NOT_READY"
    assert case["disclosure_acknowledged"] is False
    assert case["version"] == 1


def test_list_cases_returns_pagination_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/list_cases_pagination_envelope_fields_present
    """
    home = create_funeral_home()
    get_success_data(api.create_case(
        {"funeral_home_id": home["id"], "decedent_name": "Jane Doe",
         "case_mode": "PRENEED"}, ARRANGER))

    data, meta = validate_paginated(api.list_cases(ARRANGER, params={"funeral_home_id": home["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_limit_above_max_rejected(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100 ... A limit or
    offset outside its allowed bounds is rejected with ERR_VALIDATION_OUT_OF_RANGE
    (HTTP 422)."

    Design: Corner/entities/pagination_limit_out_of_range_returns_validation_error
    """
    home = create_funeral_home()
    resp = api.list_cases(ARRANGER, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_OUT_OF_RANGE.value)


def test_list_contracts_filtered_by_case(api):
    """PRD §4 (GET /contracts): "List contracts, optionally by case".
    PRD §3.4: "Exactly one contract is created per case".

    GET /contracts?case_id={id} returns the single contract for that case.

    Design: Corner/entities/fk_reverse_list_contracts_by_case
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "AT_NEED_DIRECT")

    data, meta = validate_paginated(api.list_contracts(ARRANGER, params={"case_id": case["id"]}))
    ids = [c["id"] for c in data]
    assert contract["id"] in ids
    assert all(c["case_id"] == case["id"] for c in data)
