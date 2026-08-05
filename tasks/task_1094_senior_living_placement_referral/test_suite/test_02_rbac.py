"""Authentication, role authorization, VA-certification and segregation-of-duties.

Each test translates exactly one non-stub corner-design instance.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_error, validate_paginated, validate_success, get_success_data,
    create_community_payload,
    create_advisor, create_community, create_inventory, create_family, create_inquiry,
    assign_advisor, create_approved_assessment, set_clock,
    make_advisor_headers, make_counselor_headers,
    build_scenario,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_request_without_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    six role names enumerated below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first check the server
    performs".

    Design: Corner/rbac/request_without_auth_headers_returns_unauthenticated
    """
    create_community(api)  # a row exists so the endpoint would otherwise return data
    resp = api.list_communities({})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.json()["response_type"] == "error"


def test_family_cannot_create_a_community(api):
    """PRD §2.1: "Once authentication succeeds, the server checks whether the acting
    role appears in the authorized-role list for the endpoint being called, as
    tabulated in §4. A role that is not listed there is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/family_cannot_create_a_community
    """
    resp = api.create_community(
        create_community_payload(name="Rogue Manor", contract_tier="PREMIER",
                                 referral_fee_pct=1.0, tour_slot_capacity=9,
                                 quality_rating=5.0),
        TEST_USERS["family_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    _, meta = validate_paginated(api.list_communities(ADMIN))
    assert meta["total_count"] == 0


def test_community_manager_cannot_issue_a_referral_invoice(api):
    """PRD §3.12: "A billing specialist issues a `DRAFT` invoice".
    PRD §2.1: "A role that is not listed there is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/community_manager_cannot_issue_a_referral_invoice
    """
    sc = build_scenario(api, "moved_in")
    invoice = sc["invoice"]
    resp = api.issue_invoice(invoice["id"], sc["cm_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    inv = validate_success(api.get_invoice(invoice["id"], ADMIN))
    assert inv["status"] == "DRAFT"
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == 0
    rows, _ = validate_paginated(api.list_ledger_entries(ADMIN, params={"invoice_id": invoice["id"]}))
    assert rows == []


def test_advisor_cannot_review_an_assessment_they_authored(api):
    """PRD §3.4: "Segregation of duties governs the reviewer: when the reviewing
    actor's role is `Advisor`, their `X-User-ID` must not equal the assessment's
    `author_advisor_id`, else `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/rbac/advisor_cannot_review_an_assessment_they_authored
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    ann_hdr = make_advisor_headers(ann["id"])
    assessment = get_success_data(api.create_assessment(
        {"inquiry_id": inquiry["id"], "adl_score": 6, "cognitive_score": 4,
         "mobility_score": 5, "budget_monthly_cents": 520000,
         "gross_monthly_income_cents": 320000, "va_eligible": True,
         "marital_status": "MARRIED"}, ann_hdr))
    api.submit_assessment(assessment["id"], ann_hdr)
    resp = api.review_assessment(assessment["id"], {"decision": "APPROVE"}, ann_hdr)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    s = validate_success(api.get_assessment(assessment["id"], ADMIN))
    assert s["status"] == "SUBMITTED"
    assert s["affordability_ceiling_cents"] == 0
    inq = validate_success(api.get_inquiry(inquiry["id"], ADMIN))
    assert inq["status"] == "ASSIGNED"


def _approved_va_inquiry(api, *, advisor_va_certified, va_eligible=True):
    """Approved, va_eligible assessment on an inquiry assigned to Ann.
    Returns (ann, inquiry, assessment)."""
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes", is_va_certified=advisor_va_certified)
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    assessment = create_approved_assessment(api, inquiry["id"], ann["id"],
                                            va_eligible=va_eligible)
    return ann, inquiry, assessment


def test_non_certified_advisor_cannot_act_as_benefits_counselor(api):
    """PRD §2.1: "The advisor row behind the header must have `is_va_certified` set
    to true; when it is false the request is rejected with
    `ERR_ADVISOR_NOT_VA_CERTIFIED` (HTTP 403)."

    Design: Corner/rbac/non_certified_advisor_cannot_act_as_a_benefits_counselor
    """
    ann, inquiry, assessment = _approved_va_inquiry(api, advisor_va_certified=True)
    cara = create_advisor(api, full_name="Cara Diaz", region_code="TX-AUS",
                          is_va_certified=False)
    resp = api.create_guidance(
        {"inquiry_id": inquiry["id"], "benefit_type": "VA_AID_ATTENDANCE",
         "expected_assessment_version": assessment["version"]},
        make_counselor_headers(cara["id"]))
    validate_error(resp, ApiErrorId.ERR_ADVISOR_NOT_VA_CERTIFIED)
    s = validate_success(api.get_assessment(assessment["id"], ADMIN))
    assert s["affordability_ceiling_cents"] == 572000
    rows, _ = validate_paginated(api.list_guidances(ADMIN, params={"inquiry_id": inquiry["id"]}))
    assert rows == []


def test_assigned_advisor_cannot_issue_guidance_on_own_inquiry(api):
    """PRD §3.5: "the counselor's `X-User-ID` must not equal the inquiry's
    `assigned_advisor_id`, enforcing that the guidance author is not the case
    advisor (`ERR_SEGREGATION_OF_DUTIES`)".

    Design: Corner/rbac/assigned_advisor_cannot_issue_benefit_guidance_on_their_own_inquiry
    """
    ann, inquiry, assessment = _approved_va_inquiry(api, advisor_va_certified=True)
    resp = api.create_guidance(
        {"inquiry_id": inquiry["id"], "benefit_type": "VA_AID_ATTENDANCE",
         "expected_assessment_version": assessment["version"]},
        make_counselor_headers(ann["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    s = validate_success(api.get_assessment(assessment["id"], ADMIN))
    assert s["benefit_offset_cents"] == 0
    rows, _ = validate_paginated(api.list_guidances(ADMIN, params={"inquiry_id": inquiry["id"]}))
    assert rows == []
