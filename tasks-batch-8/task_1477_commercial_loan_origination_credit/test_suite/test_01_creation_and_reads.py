"""Creation round-trips, defaults, required-field and schema constraints,
404 existence checks, and list/pagination behavior (PRD sections 2.2-2.4, 2.10, 3.1-3.2).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId, api_client, assert_borrower, assert_loan_application,
    borrower_payload, build_user_headers, create_borrower, get_success_data,
    is_iso8601_timestamp, is_valid_uuid, loan_application_payload, setup_officers,
    statement_payload, validate_error, validate_paginated, validate_success,
)


def test_bank_officer_and_borrower_creation_roundtrip():
    """PRD section 3.1: "A `RelationshipManager` opens a borrowing relationship by
    creating a borrower with its `legal_name`, its six-digit `naics_code`, and the
    `relationship_since` date" and "A new borrower's `status` is `ACTIVE`".
    PRD section 2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/entities/bank_officer_and_borrower_creation_roundtrip
    """
    o = setup_officers(["rm"])
    resp = api_client.create_borrower(
        borrower_payload(legal_name="Beacon Holdings LLC", naics_code="332710",
                         relationship_since="2018-01-01", is_reg_o_insider=True),
        o["rm"]["headers"])
    data = validate_success(resp, 201)
    assert_borrower(data)
    assert isinstance(data["version"], int) and data["version"] >= 1

    echoed = validate_success(api_client.get_borrower(data["id"], o["rm"]["headers"]), 200)
    assert echoed["legal_name"] == "Beacon Holdings LLC"
    assert echoed["naics_code"] == "332710"
    assert echoed["relationship_since"] == "2018-01-01"
    assert echoed["is_reg_o_insider"] is True
    assert echoed["status"] == "ACTIVE"


def test_creation_defaults_applied():
    """PRD section 3.1: "The `is_reg_o_insider` flag may be supplied at creation and
    defaults to `false`" and "its three exposure counters — `committed_exposure_cents`,
    `funded_exposure_cents`, and `total_exposure_cents` — are initialized to zero."
    PRD section 3.4: "`max_concurrent_engagements` may be supplied to override the
    default of 2" and "A new appraiser is `ELIGIBLE`."

    Design: Corner/entities/creation_defaults_applied
    """
    o = setup_officers(["rm", "apm"])
    bor = validate_success(api_client.create_borrower(
        borrower_payload(legal_name="Default Test Co", naics_code="441110",
                         relationship_since="2020-03-15"),
        o["rm"]["headers"]), 201)
    assert bor["is_reg_o_insider"] is False
    assert bor["status"] == "ACTIVE"
    assert bor["committed_exposure_cents"] == 0
    assert bor["funded_exposure_cents"] == 0
    assert bor["total_exposure_cents"] == 0

    apr = validate_success(api_client.create_appraiser(
        {"name": "AppraisalCo", "license_number": "LIC-100"}, o["apm"]["headers"]), 201)
    assert apr["max_concurrent_engagements"] == 2
    assert apr["status"] == "ELIGIBLE"


def test_missing_required_fields_rejected():
    """PRD section 2.8: "Required fields are present, types are valid, enum members
    are valid, and numeric and date ranges hold ... otherwise `ERR_VALIDATION` (HTTP 400)."
    PRD section 3.1: a borrower is created "with its `legal_name`, its six-digit
    `naics_code`, and the `relationship_since` date"; an application requires
    "the `requested_amount_cents` (strictly positive), the `term_months` (between
    12 and 360 inclusive)".

    Design: Corner/entities/missing_required_fields_rejected
    """
    o = setup_officers(["rm", "an"])
    bor = create_borrower(o)
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"]), o["rm"]["headers"]), 201)

    r1 = api_client.create_borrower(
        {"naics_code": "332710", "relationship_since": "2018-01-01"}, o["rm"]["headers"])
    validate_error(r1, ApiErrorId.ERR_VALIDATION)

    r2 = api_client.create_loan_application(
        {"borrower_id": bor["id"], "product_type": "CRE_TERM",
         "requested_amount_cents": 30_000_000}, o["rm"]["headers"])
    validate_error(r2, ApiErrorId.ERR_VALIDATION)

    stmt = statement_payload(app["id"])
    del stmt["ebitda_cents"]
    r3 = api_client.create_financial_statement(stmt, o["an"]["headers"])
    validate_error(r3, ApiErrorId.ERR_VALIDATION)


def test_field_range_enum_and_date_constraints_rejected():
    """PRD section 2.8: "`term_months` between 12 and 360 inclusive ... monetary
    amounts strictly greater than zero ... `engagement_end_date` on or after
    `engagement_start_date`, session `ends_at` strictly after `starts_at` ...
    otherwise `ERR_VALIDATION` (HTTP 400)." and "Every request is evaluated against
    a fixed pipeline of checks in strict priority order; the first failing check
    determines the error response" (body schema is stage 4; transition legality
    is stage 6).

    Design: Corner/entities/field_range_enum_and_date_constraints_rejected
    """
    o = setup_officers(["rm", "apm", "ch"])
    bor = create_borrower(o)
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"]), o["rm"]["headers"]), 201)
    apr = validate_success(api_client.create_appraiser(
        {"name": "AppraisalCo", "license_number": "LIC-100"}, o["apm"]["headers"]), 201)

    r1 = api_client.create_loan_application(
        loan_application_payload(bor["id"], term_months=6), o["rm"]["headers"])
    validate_error(r1, ApiErrorId.ERR_VALIDATION)

    r2 = api_client.create_loan_application(
        loan_application_payload(bor["id"], requested_amount_cents=0), o["rm"]["headers"])
    validate_error(r2, ApiErrorId.ERR_VALIDATION)

    r3 = api_client.create_loan_application(
        loan_application_payload(bor["id"], product_type="BRIDGE_LOAN"), o["rm"]["headers"])
    validate_error(r3, ApiErrorId.ERR_VALIDATION)

    # Bad date order on an INTAKE application: schema (stage 4) beats state (stage 6).
    r4 = api_client.create_appraisal(
        {"loan_application_id": app["id"], "appraiser_id": apr["id"],
         "collateral_class": "REAL_ESTATE", "engagement_start_date": "2026-08-07",
         "engagement_end_date": "2026-08-03"}, o["apm"]["headers"])
    validate_error(r4, ApiErrorId.ERR_VALIDATION)

    r5 = api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T14:00:00Z",
         "ends_at": "2026-08-10T14:00:00Z"}, o["ch"]["headers"])
    validate_error(r5, ApiErrorId.ERR_VALIDATION)


def test_application_computed_fields_null_before_underwriting():
    """PRD section 3.1: "A created application starts in `INTAKE` status, records the
    caller as its `originating_officer_id`, and carries nulls in its computed
    underwriting fields (`dscr_standard`, `dscr_stress`, `risk_rating`) until spreads
    are finalized."
    PRD section 3.8: "`bank_hold_amount_cents` ... is zero until a commitment letter
    exists" and "`bank_hold_fee_cents` is null until a commitment letter exists".

    Design: Corner/entities/application_computed_fields_null_before_underwriting
    """
    o = setup_officers(["rm"])
    bor = create_borrower(o)
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"], requested_amount_cents=30_000_000, term_months=60),
        o["rm"]["headers"]), 201)

    data = validate_success(api_client.get_loan_application(app["id"], o["rm"]["headers"]), 200)
    assert_loan_application(data)
    assert data["status"] == "INTAKE"
    assert data["dscr_standard"] is None
    assert data["dscr_stress"] is None
    assert data["risk_rating"] is None
    assert data["total_appraised_value_cents"] == 0
    assert data["total_eligible_collateral_cents"] == 0
    assert data["total_liquidation_collateral_cents"] == 0
    assert data["bank_hold_amount_cents"] == 0
    assert data["bank_hold_fee_cents"] is None
    assert data["funded_amount_cents"] == 0
    assert data["originating_officer_id"] == o["rm"]["id"]


def test_unknown_ids_return_not_found():
    """PRD section 2.10: "Any request path containing resource identifiers is
    validated left to right, and the request is rejected with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not correspond to an existing
    resource."

    Design: Corner/entities/unknown_ids_return_not_found
    """
    o = setup_officers(["rm", "an"])
    r1 = api_client.get_borrower(NON_EXISTENT_UUID, o["an"]["headers"])
    validate_error(r1, ApiErrorId.ERR_NOT_FOUND)

    r2 = api_client.submit_application(NON_EXISTENT_UUID, o["rm"]["headers"])
    validate_error(r2, ApiErrorId.ERR_NOT_FOUND)

    r3 = api_client.get_commitment_letter(NON_EXISTENT_UUID, o["an"]["headers"])
    validate_error(r3, ApiErrorId.ERR_NOT_FOUND)


def test_borrower_list_pagination_defaults_and_offsets():
    """PRD section 2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
    states how many items to skip and defaults to 0." and "The `meta` object of a
    list response carries the pagination fields `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/borrower_list_pagination_defaults_and_offsets
    """
    o = setup_officers(["rm"])
    for name, naics, since in (("Alpha LLC", "332710", "2018-01-01"),
                               ("Beta LLC", "441110", "2019-01-01"),
                               ("Gamma LLC", "531120", "2020-01-01")):
        create_borrower(o, legal_name=name, naics_code=naics, relationship_since=since)

    resp = api_client.list_borrowers(o["rm"]["headers"])
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(data) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    data2, meta2 = validate_paginated(api_client.list_borrowers(o["rm"]["headers"], params={"limit": 2}))
    assert len(data2) == 2 and meta2["total_count"] == 3 and meta2["has_more"] is True

    data3, meta3 = validate_paginated(api_client.list_borrowers(
        o["rm"]["headers"], params={"limit": 2, "offset": 2}))
    assert len(data3) == 1 and meta3["total_count"] == 3 and meta3["has_more"] is False


def test_loan_application_list_filters():
    """PRD section 3.1: "The application book can be listed with `borrower_id`,
    `status`, and `originating_officer_id` filters".

    Design: Corner/entities/loan_application_list_filters
    """
    o = setup_officers(["rm", "an"])
    bor1 = create_borrower(o, legal_name="Alpha LLC")
    bor2 = create_borrower(o, legal_name="Beta LLC", naics_code="441110",
                           relationship_since="2019-01-01")
    app1 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor1["id"], product_type="EQUIPMENT",
                                 requested_amount_cents=5_000_000, term_months=36),
        o["rm"]["headers"]), 201)
    stmt1 = validate_success(api_client.create_financial_statement(
        statement_payload(app1["id"], shape="WINDOW"), o["an"]["headers"]), 201)
    validate_success(api_client.submit_application(app1["id"], o["rm"]["headers"]), 200)
    app2 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor2["id"], requested_amount_cents=7_000_000, term_months=48),
        o["rm"]["headers"]), 201)

    data, _ = validate_paginated(api_client.list_loan_applications(
        o["an"]["headers"], params={"borrower_id": bor1["id"]}))
    assert [a["id"] for a in data] == [app1["id"]]

    data, _ = validate_paginated(api_client.list_loan_applications(
        o["an"]["headers"], params={"status": "SPREADING"}))
    assert [a["id"] for a in data] == [app1["id"]]

    data, _ = validate_paginated(api_client.list_loan_applications(
        o["an"]["headers"], params={"status": "INTAKE"}))
    assert [a["id"] for a in data] == [app2["id"]]

    data, meta = validate_paginated(api_client.list_loan_applications(o["an"]["headers"]))
    assert meta["total_count"] == 2
