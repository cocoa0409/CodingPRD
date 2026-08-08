"""Case filing, service, the answer window, and default gating (PRD §3.2)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_case,
    make_landlord_headers, make_tenant_headers, TEST_USERS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]


def test_case_create_returns_201_filed_pending(api):
    """PRD §3.2: "A case is opened by the plaintiff or on their behalf, and enters
    the world in status FILED with its outcome dimension set to PENDING and sealed
    false." PRD §3.2: "At filing the case's outstanding balance, net_arrears_cents,
    is seeded to the claimed amount".

    Design: Corner/entities/case_create_returns_201_with_fields
    """
    ctx = fx.seed_parties(api)
    payload = f.create_case_payload(ctx["court"]["id"], ctx["landlord"]["id"],
                                    ctx["tenant"]["id"], filing_type="NONPAYMENT",
                                    claimed_arrears_cents=400000)
    resp = api.create_case(payload, make_landlord_headers(ctx["landlord"]["id"]))
    data = validate_success(resp, expected_status=201)
    assert_case(data)
    assert data["status"] == "FILED"
    assert data["outcome"] == "PENDING"
    assert data["net_arrears_cents"] == 400000
    assert data["sealed"] is False


def test_case_get_nonexistent_returns_not_found(api):
    """PRD §2.10: "the first unresolved reference yields ERR_NOT_FOUND."

    Design: Corner/entities/case_get_nonexistent_returns_not_found
    """
    resp = api.get_case(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_case_create_missing_filing_type_returns_validation(api):
    """PRD §2.8: "(3) body well-formedness — required fields present, enum values in
    range, numeric fields at least their declared minimums ... else ERR_VALIDATION".

    Design: Corner/entities/case_create_missing_filing_type_returns_validation
    """
    ctx = fx.seed_parties(api)
    payload = {"court_id": ctx["court"]["id"], "landlord_id": ctx["landlord"]["id"],
               "tenant_id": ctx["tenant"]["id"], "claimed_arrears_cents": 400000}
    resp = api.create_case(payload, make_landlord_headers(ctx["landlord"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_case_holdover_defaults_arrears_zero(api):
    """PRD §3.2: "A money claim, claimed_arrears_cents, is optional and defaults to 0
    (holdover and nuisance filings claim no arrears)". PRD §3.2: "the provisional
    variant of the arrears calculation, which simply equals claimed_arrears_cents".

    Design: Corner/entities/case_holdover_defaults_arrears_zero
    """
    ctx = fx.seed_parties(api)
    payload = f.create_case_payload(ctx["court"]["id"], ctx["landlord"]["id"],
                                    ctx["tenant"]["id"], filing_type="HOLDOVER")
    resp = api.create_case(payload, make_landlord_headers(ctx["landlord"]["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["claimed_arrears_cents"] == 0
    assert data["net_arrears_cents"] == 0


def test_case_answer_due_at_computed_14_days(api):
    """PRD §3.2: "The deadline by which the tenant must respond, answer_due_at, is
    fixed at creation as the case's created_at instant plus a two-week answer window
    (fourteen days)." PRD §2.5: startup clock reads 2026-05-01T00:00:00Z.

    Design: Corner/entities/case_answer_due_at_computed_14_days
    """
    ctx = fx.seed_parties(api)
    payload = f.create_case_payload(ctx["court"]["id"], ctx["landlord"]["id"],
                                    ctx["tenant"]["id"], filing_type="NONPAYMENT",
                                    claimed_arrears_cents=400000)
    resp = api.create_case(payload, make_landlord_headers(ctx["landlord"]["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["answer_due_at"] == "2026-05-15T00:00:00.000Z"


def test_case_create_invalid_filing_type_enum_returns_validation(api):
    """PRD §2.8: "(3) body well-formedness — required fields present, enum values in
    range ... else ERR_VALIDATION".

    Design: Corner/entities/case_create_invalid_filing_type_enum_returns_validation
    """
    ctx = fx.seed_parties(api)
    payload = f.create_case_payload(ctx["court"]["id"], ctx["landlord"]["id"],
                                    ctx["tenant"]["id"], filing_type="FORECLOSURE",
                                    claimed_arrears_cents=400000)
    resp = api.create_case(payload, make_landlord_headers(ctx["landlord"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_case_create_bad_court_fk_returns_not_found(api):
    """PRD §2.8: "(4) existence — every path identifier and every foreign key in the
    body resolves, left to right, to a live resource, else ERR_NOT_FOUND".

    Design: Corner/entities/case_create_bad_court_fk_returns_not_found
    """
    landlord = get_success_data(api.create_landlord(f.create_landlord_payload(), CLERK))
    tenant = get_success_data(api.create_tenant(f.create_tenant_payload(), CLERK))
    payload = f.create_case_payload(NON_EXISTENT_UUID, landlord["id"], tenant["id"],
                                    filing_type="NONPAYMENT", claimed_arrears_cents=400000)
    resp = api.create_case(payload, make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_default_before_answer_due_returns_window_open(api):
    """PRD §3.2: "the current logical-clock instant must be at or after answer_due_at
    (attempting it while the window is still open yields ERR_ANSWER_WINDOW_OPEN)".

    Design: Corner/validations/default_before_answer_due_returns_window_open
    """
    ctx = fx.setup_served_case(api, claimed_arrears_cents=600000)
    resp = api.transition_case(ctx["case"]["id"], {"to_status": "DEFAULTED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_ANSWER_WINDOW_OPEN.value, expected_status=409)


def test_default_with_existing_answer_returns_already_answered(api):
    """PRD §3.2: "no answer may already exist for the case (otherwise
    ERR_ALREADY_ANSWERED)."

    Design: Corner/validations/default_with_existing_answer_returns_already_answered
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    fx.set_clock(api, "2026-05-16T00:00:00Z")
    resp = api.transition_case(ctx["case"]["id"], {"to_status": "DEFAULTED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_ALREADY_ANSWERED.value, expected_status=409)


def test_answer_after_default_returns_window_closed(api):
    """PRD §3.2: "once the case has moved to DEFAULTED, an attempt to answer is
    refused with ERR_ANSWER_WINDOW_CLOSED."

    Design: Corner/validations/answer_after_default_returns_window_closed
    """
    ctx = fx.setup_served_case(api, claimed_arrears_cents=600000)
    fx.set_clock(api, "2026-05-16T00:00:00Z")
    get_success_data(api.transition_case(ctx["case"]["id"], {"to_status": "DEFAULTED"}, CLERK))
    resp = api.create_answer(f.create_answer_payload(ctx["case"]["id"]),
                             make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ANSWER_WINDOW_CLOSED.value, expected_status=409)
