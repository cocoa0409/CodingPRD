"""Policy issuance, field-shape validation, RBAC, auth, listing, and clock.

Covers foundational corner-design instances: entity creation + system fields,
required/conditional field-shape validation, not-found, listing/pagination,
clock advance, and role/auth gating.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    get_success_data,
    assert_policy, assert_claim, assert_occupation_class, assert_benefit_period,
    create_policy_payload, create_claim_payload,
    TEST_USERS, make_policyholder_headers,
    setup_book, setup_active_policy, create_insurer,
    setup_approved_total_with_periods,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]
OPR = TEST_USERS["system_operator_headers"]
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_policy_returns_201_with_system_fields(api):
    """PRD §3.2: "A freshly issued policy begins life with lifecycle_status equal
    to PENDING, premium_status equal to CURRENT, and benefit_months_consumed of 0."
    PRD §2.5: "The version is an integer that begins at 1 on creation and
    increments by one on every mutation of the resource".

    Design: Corner/entities/create_policy_returns_201_with_system_fields
    """
    book = setup_book(occ_overrides={"own_occ_window_months_cap": 60})
    resp = api.create_policy(
        create_policy_payload(
            book["insurer"]["id"], book["policyholder"]["id"], book["occupation_class"]["id"],
            monthly_benefit_cents=500000, benefit_period_months=12,
            elimination_period_days=90, occupation_definition="OWN_OCC",
            own_occ_window_months=24, cola_rider=True, cola_annual_rate=0.03,
        ),
        UW,
    )
    data = validate_success(resp, 201)
    assert_policy(data)
    assert data["lifecycle_status"] == "PENDING"
    assert data["premium_status"] == "CURRENT"
    assert data["benefit_months_consumed"] == 0
    assert data["version"] == 1


def test_create_policy_missing_monthly_benefit_rejected(api):
    """PRD §2.9: "Every create endpoint validates the shape of its payload, raising
    ERR_INVALID_REQUEST when any of the following hold: a required field is missing".

    Design: Corner/entities/create_policy_missing_monthly_benefit_returns_invalid_request
    """
    book = setup_book(occ_overrides={"own_occ_window_months_cap": 60})
    payload = {
        "insurer_id": book["insurer"]["id"],
        "policyholder_id": book["policyholder"]["id"],
        "occupation_class_id": book["occupation_class"]["id"],
        "benefit_period_months": 12,
        "elimination_period_days": 90,
        "occupation_definition": "ANY_OCC",
    }  # monthly_benefit_cents intentionally omitted
    resp = api.create_policy(payload, UW)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_policy_cola_rate_nonzero_without_rider_rejected(api):
    """PRD §2.9: "raising ERR_INVALID_REQUEST when any of the following hold: ...
    a cost-of-living annual rate (cola_annual_rate) is greater than zero while the
    cost-of-living rider (cola_rider) is not attached".

    Design: Corner/entities/create_policy_cola_rate_nonzero_without_rider_invalid
    """
    book = setup_book(occ_overrides={"own_occ_window_months_cap": 60})
    resp = api.create_policy(
        create_policy_payload(
            book["insurer"]["id"], book["policyholder"]["id"], book["occupation_class"]["id"],
            occupation_definition="ANY_OCC", cola_rider=False, cola_annual_rate=0.03,
        ),
        UW,
    )
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_policy_elimination_below_class_floor_rejected(api):
    """PRD §2.9: "raising ERR_INVALID_REQUEST when any of the following hold: ...
    a policy's elimination_period_days is below the occupation class's
    min_elimination_days".

    Design: Corner/entities/create_policy_elimination_below_class_floor_invalid
    """
    book = setup_book(occ_overrides={
        "code": "HI", "risk_tier": "HIGH", "min_elimination_days": 60,
        "own_occ_window_months_cap": 12,
    })
    resp = api.create_policy(
        create_policy_payload(
            book["insurer"]["id"], book["policyholder"]["id"], book["occupation_class"]["id"],
            elimination_period_days=30, occupation_definition="ANY_OCC",
        ),
        UW,
    )
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_get_policy_nonexistent_returns_not_found(api):
    """PRD §2.8: "an unresolved policy yields ERR_POLICY_NOT_FOUND".

    Design: Corner/entities/get_policy_nonexistent_returns_not_found
    """
    create_insurer()  # an insurer exists; no policy with the queried id
    resp = api.get_policy(NONEXISTENT_UUID, UW)
    validate_error(resp, "ERR_POLICY_NOT_FOUND")


def test_create_claim_starts_draft_and_computes_elimination_window(api):
    """PRD §3.4: "The claim is created in DRAFT status."
    PRD §3.4: "The elimination satisfied month is the onset month plus the
    elimination period converted to whole months, where the conversion divides
    elimination_period_days by 30 days per month and rounds up to the next whole
    month; this lands in the claim's elimination_satisfied_month."

    Design: Corner/entities/create_claim_ignores_client_supplied_status_system_field
    """
    book = setup_active_policy(policy_overrides={
        "elimination_period_days": 90, "occupation_definition": "ANY_OCC",
    })
    resp = api.create_claim(
        create_claim_payload(
            book["insurer"]["id"], book["policy"]["id"],
            disability_onset_month=2, claimed_disability_type="TOTAL",
        ),
        make_policyholder_headers(book["policyholder"]["id"]),
    )
    data = validate_success(resp, 201)
    assert_claim(data)
    assert data["status"] == "DRAFT"
    # onset 2 + ceil(90/30)=3 => 5
    assert data["elimination_satisfied_month"] == 5


def test_clock_advance_increments_current_month_index(api):
    """PRD §2.4: "Advancing the clock accepts a by_months amount, which must be
    between 1 and 100000 inclusive, and adds that amount to current_month_index."

    Design: Corner/endpoints/clock_advance_increments_current_month_index
    """
    insurer = create_insurer()
    resp = api.advance_clock(insurer["id"], {"by_months": 4}, OPR)
    data = validate_success(resp, 200)
    assert data["current_month_index"] == 4


def test_list_claims_pagination_envelope(api):
    """PRD §2.3: "Every list response includes the fields limit, offset,
    total_count, and has_more in the meta object of the envelope."

    Design: Corner/endpoints/list_claims_pagination_envelope
    """
    book = setup_active_policy()
    api_client.create_claim(
        create_claim_payload(book["insurer"]["id"], book["policy"]["id"]),
        make_policyholder_headers(book["policyholder"]["id"]),
    )
    resp = api.list_claims(ADJ, params={"policy_id": book["policy"]["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1


def test_occupation_class_listed_by_insurer_fk(api):
    """PRD §3.1: "Occupation classes can be listed for an insurer by supplying an
    optional insurer_id filter, and fetched individually."

    Design: Corner/entities/occupation_class_listed_by_insurer_fk
    """
    book = setup_book(occ_overrides={"own_occ_window_months_cap": 60})
    resp = api.list_occupation_classes(UW, params={"insurer_id": book["insurer"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    ids = [oc["id"] for oc in data]
    assert book["occupation_class"]["id"] in ids


def test_benefit_periods_listed_by_claim_subresource(api):
    """PRD §3.9: "Benefit periods can be listed for a claim, listed across the book
    with optional policy_id and claim_id filters, and fetched individually."

    Design: Corner/entities/benefit_periods_listed_by_claim_subresource
    """
    book = setup_approved_total_with_periods([3], clock_months=5)
    bp_id = book["benefit_periods"][0]["id"]
    resp = api.list_claim_benefit_periods(book["claim"]["id"], ADJ)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert bp_id in [bp["id"] for bp in data]


# ─── RBAC + auth (Corner/rbac) ────────────────────────

def test_policyholder_cannot_approve_claim(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/policyholder_cannot_approve_claim
    """
    from test_helpers import setup_under_review_claim
    book = setup_under_review_claim(clock_months=5)
    resp = api.approve_claim(book["claim"]["id"],
                             make_policyholder_headers(book["policyholder"]["id"]))
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


def test_underwriter_cannot_file_claim(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/underwriter_cannot_file_claim
    """
    book = setup_active_policy()
    resp = api.create_claim(
        create_claim_payload(book["insurer"]["id"], book["policy"]["id"]), UW
    )
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with ERR_MISSING_AUTH_CONTEXT."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    insurer = create_insurer()
    resp = api.get_insurer(insurer["id"], {})  # no auth headers
    validate_error(resp, "ERR_MISSING_AUTH_CONTEXT")
