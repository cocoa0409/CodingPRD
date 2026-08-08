"""Case and obligation creation basics: defaults, referential rules, auth, and listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    clerk_headers, finance_headers, NO_ROLE_HEADERS,
    make_case, make_obligation,
    create_case_payload, create_obligation_payload,
    api_client,
)


def test_case_create_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created case starts with status OPEN, delinquency_status
    CURRENT, and every monetary aggregate initialized to zero."
    PRD §2.4: "version — a system-managed integer that starts at 1 on creation."

    Design: Corner/entities/case_create_returns_201_with_defaults
    """
    resp = api.create_case(create_case_payload(case_number="C-CREATE", defendant_name="Ada Vale"),
                           clerk_headers())
    case = validate_success(resp, expected_status=201)
    assert case["status"] == "OPEN"
    assert case["delinquency_status"] == "CURRENT"
    assert case["total_assessed_cents"] == 0
    assert case["balance_cents"] == 0
    assert case["version"] == 1


def test_obligation_priority_rank_defaults_from_type(api):
    """PRD §3.1: "If the client omits priority_rank, it defaults from the obligation
    type: restitution takes rank 1, court fees rank 2, fines rank 3, and surcharges
    rank 4."

    Design: Corner/entities/obligation_priority_rank_defaults_from_type
    """
    case = make_case(case_number="C-DEFRANK")
    resp = api.create_obligation(
        create_obligation_payload(case_id=case["id"], obligation_type="COURT_FEE",
                                  assessed_amount_cents=5000),
        clerk_headers(),
    )
    obl = validate_success(resp, expected_status=201)
    assert obl["priority_rank"] == 2
    assert obl["status"] == "OUTSTANDING"


def test_restitution_without_victim_rejected(api):
    """PRD §3.1: "An obligation of type RESTITUTION must name the `victim_id` it is owed
    to ... Violating either half of that rule — a restitution obligation with no victim,
    or a non-restitution obligation carrying a victim — is rejected with
    `ERR_VICTIM_REQUIRED`."

    Design: Corner/entities/obligation_restitution_missing_victim_returns_victim_required
    """
    case = make_case(case_number="C-NOVIC")
    resp = api.create_obligation(
        create_obligation_payload(case_id=case["id"], obligation_type="RESTITUTION",
                                  assessed_amount_cents=5000),
        clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_VICTIM_REQUIRED.value, expected_status=422)


def test_get_unknown_case_returns_404(api):
    """PRD §2.7: "The system validates every such reference for existence, in
    left-to-right order — path identifiers first ... and rejects the first unresolved
    reference with ERR_NOT_FOUND."

    Design: Corner/entities/case_get_unknown_id_returns_404
    """
    resp = api.get_case("00000000-0000-4000-8000-000000000000", clerk_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_obligations_list_pagination_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and has_more
    in the meta object of the envelope."

    Design: Corner/endpoints/obligations_list_pagination_envelope
    """
    case = make_case(case_number="C-PAGE")
    make_obligation(case["id"], "COURT_FEE", 1000)
    make_obligation(case["id"], "FINE", 2000)
    make_obligation(case["id"], "SURCHARGE", 3000)

    data, meta = validate_paginated(api.list_obligations(clerk_headers(), params={"case_id": case["id"]}))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(data) == 3


def test_duplicate_case_number_rejected(api):
    """PRD §3.1: "the case_number (the court docket number, which must be unique across
    all cases) ... If the supplied case_number is already used by another case, the
    request is rejected with ERR_CASE_NUMBER_TAKEN."

    Design: Corner/errors/duplicate_case_number_returns_case_number_taken
    """
    make_case(case_number="C-DUP", defendant_name="Pia Orr")
    resp = api.create_case(create_case_payload(case_number="C-DUP", defendant_name="Rex Tan"),
                           clerk_headers())
    validate_error(resp, ApiErrorId.ERR_CASE_NUMBER_TAKEN.value, expected_status=409)


def test_missing_role_header_returns_401(api):
    """PRD §2.1: "If X-User-Role is missing or is not one of the four roles below, the
    request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/missing_role_header_returns_401
    """
    resp = api.create_case(create_case_payload(case_number="C-NOAUTH", defendant_name="Kip All"),
                           NO_ROLE_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_wrong_role_create_case_returns_403(api):
    """PRD §2.1: "If the header is present and valid but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN."

    Design: Corner/validations/wrong_role_create_case_returns_403
    """
    resp = api.create_case(create_case_payload(case_number="C-WRONGROLE", defendant_name="Lea Bond"),
                           finance_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
