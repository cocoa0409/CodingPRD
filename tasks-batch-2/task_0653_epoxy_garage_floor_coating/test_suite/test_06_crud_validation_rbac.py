"""Entity creation and computed/system fields, input validation, cross-entity
validations, RBAC (authentication, role authorization, resource ownership),
listing/pagination, the condition-score tier boundary, and reverse-reachability.
"""
from test_helpers import (
    api_client, TEST_USERS, get_success_data, validate_success, validate_error,
    validate_paginated, make_customer_headers,
    assert_coating_system, assert_crew, assert_customer, assert_project,
    create_system_with_color, create_customer, create_project, record_assessment,
    create_estimate_quote, send_quote, project_version,
)
from test_helpers.factories import (
    create_coating_system_payload, create_crew_payload, create_customer_payload,
    create_project_payload, create_assessment_payload, create_referral_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# ===========================================================================
# Corner/entities/create_coating_system_returns_201_with_computed_flag
# ===========================================================================
def test_create_metallic_coating_system_sets_computed_flag():
    """PRD §3.1: "The system also derives a read-only
    `requires_metallic_certified_crew` flag, which is true exactly when the family
    is `METALLIC` and false otherwise".

    Design: Corner/entities/create_coating_system_returns_201_with_computed_flag
    """
    resp = api_client.create_coating_system(
        create_coating_system_payload(name="Metallic Lava", family="METALLIC", sku="METALLIC"),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_coating_system(data)
    assert data["requires_metallic_certified_crew"] is True, (
        f"METALLIC family -> computed flag true, got {data['requires_metallic_certified_crew']}"
    )


# ===========================================================================
# Corner/entities/create_crew_metallic_certified_defaults_false
# ===========================================================================
def test_create_crew_defaults_metallic_certified_false():
    """PRD §3.1: "A **crew** is created with a `name`, an optional
    `metallic_certified` flag (defaulting to false) recording whether the crew may
    install metallic systems".

    Design: Corner/entities/create_crew_metallic_certified_defaults_false
    """
    payload = {"name": "Default Crew", "max_sqft_per_day": 500}  # omit metallic_certified
    resp = api_client.create_crew(payload, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["metallic_certified"] is False, (
        f"omitted metallic_certified defaults to false, got {data['metallic_certified']}"
    )


# ===========================================================================
# Corner/entities/create_customer_mints_referral_code_and_zero_balance
# ===========================================================================
def test_create_customer_mints_code_and_zero_balance():
    """PRD §3.2: "On creation the server mints a `referral_code` - a short code
    that other customers can cite to credit this customer - and initializes
    `account_credit_balance_cents` to 0."

    Design: Corner/entities/create_customer_mints_referral_code_and_zero_balance
    """
    resp = api_client.create_customer(
        create_customer_payload(full_name="Cora Customer", email="cora-mint@example.com"),
        SALES,
    )
    data = validate_success(resp, expected_status=201)
    assert_customer(data)
    assert isinstance(data["referral_code"], str) and data["referral_code"], "referral_code minted"
    assert data["account_credit_balance_cents"] == 0, (
        f"balance initialized to 0, got {data['account_credit_balance_cents']}"
    )


# ===========================================================================
# Corner/entities/project_initial_dimensions_lead_and_pre_build
# ===========================================================================
def test_new_project_initial_dimensions():
    """PRD §3.3: "A new project starts with `sales_status` of `LEAD`,
    `build_status` of `PRE_BUILD`, and `version` of 1".

    Design: Corner/entities/project_initial_dimensions_lead_and_pre_build
    """
    cust = create_customer("Cora Customer", email="cora-init@example.com")
    resp = api_client.create_project(create_project_payload(cust["id"], site_zip="94016"), SALES)
    data = validate_success(resp, expected_status=201)
    assert_project(data)
    assert data["sales_status"] == "LEAD", f"got {data['sales_status']}"
    assert data["build_status"] == "PRE_BUILD", f"got {data['build_status']}"
    assert data["version"] == 1, f"got {data['version']}"


# ===========================================================================
# Corner/entities/get_project_nonexistent_returns_not_found
# ===========================================================================
def test_get_nonexistent_project_not_found():
    """PRD §2.6: "the system validates them strictly left to right and rejects the
    request with `ERR_NOT_FOUND` at the *first* identifier that does not resolve to
    an existing resource".

    Design: Corner/entities/get_project_nonexistent_returns_not_found
    """
    resp = api_client.get_project(NON_EXISTENT, ADMIN)
    validate_error(resp, "ERR_NOT_FOUND")


# ===========================================================================
# Corner/entities/create_project_missing_required_field_returns_validation
# ===========================================================================
def test_create_project_missing_site_zip_validation():
    """PRD §2.8: "the catch-all field-presence and constraint check
    (`ERR_VALIDATION`)."
    PRD §3.3: "A `SalesRep` opens a **project** for a homeowner by supplying the
    `customer_id` it is for, the five-digit `site_zip` of the install address".

    Design: Corner/entities/create_project_missing_required_field_returns_validation
    """
    cust = create_customer("Cora Customer", email="cora-nozip@example.com")
    resp = api_client.create_project({"customer_id": cust["id"]}, SALES)  # no site_zip
    validate_error(resp, "ERR_VALIDATION")


# ===========================================================================
# Corner/entities/assessment_oil_pct_out_of_range_returns_validation
# ===========================================================================
def test_assessment_oil_pct_out_of_range_validation():
    """PRD §3.3: "the `oil_stain_pct` of the floor showing oil staining (0 through
    100)".

    Design: Corner/entities/assessment_oil_pct_out_of_range_returns_validation
    """
    cust = create_customer("Cora Customer", email="cora-oil@example.com")
    proj = create_project(cust["id"])
    resp = api_client.create_assessment(
        proj["id"],
        create_assessment_payload(oil_stain_pct=150),  # out of 0..100
        SALES,
    )
    validate_error(resp, "ERR_VALIDATION")


# ===========================================================================
# Corner/entities/create_project_unknown_customer_returns_reference_not_found
# ===========================================================================
def test_create_project_unknown_customer_reference_not_found():
    """PRD §2.6: "On create operations whose body names another row - `customer_id`
    ... each such reference must resolve to an existing row; if any does not, the
    request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_project_unknown_customer_returns_reference_not_found
    """
    resp = api_client.create_project(
        create_project_payload(NON_EXISTENT, site_zip="94016"), SALES
    )
    validate_error(resp, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# Corner/calculations/condition_score_tier_boundary_heavy_70_vs_moderate_69
# ===========================================================================
def test_condition_score_70_is_heavy_tier():
    """PRD §3.3: "the system derives the `prep_tier` ... which is `HEAVY` when the
    score is at least 70, otherwise `MODERATE` when the score is at least 35, and
    otherwise `LIGHT`. Both threshold comparisons are inclusive of their lower
    bound."

    Design: Corner/calculations/condition_score_tier_boundary_heavy_70_vs_moderate_69
    """
    cust = create_customer("Cora Customer", email="cora-cs70@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=100, crack_density=50,
        crack_linear_ft=0, spalling=False, moisture_pct=0,
    )
    assert assess["condition_score"] == 70, f"expected 70, got {assess['condition_score']}"
    assert assess["prep_tier"] == "HEAVY", f"score 70 -> HEAVY (inclusive), got {assess['prep_tier']}"


def test_condition_score_69_is_moderate_tier():
    """PRD §3.3: "otherwise `MODERATE` when the score is at least 35 ... Both
    threshold comparisons are inclusive of their lower bound."

    Design: Corner/calculations/condition_score_tier_boundary_heavy_70_vs_moderate_69
    """
    cust = create_customer("Cora Customer", email="cora-cs69@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=100, crack_density=49,
        crack_linear_ft=0, spalling=False, moisture_pct=0,
    )
    assert assess["condition_score"] == 69, f"expected 69, got {assess['condition_score']}"
    assert assess["prep_tier"] == "MODERATE", f"score 69 -> MODERATE, got {assess['prep_tier']}"


# ===========================================================================
# Corner/validations/quote_color_not_in_system_returns_mismatch
# ===========================================================================
def test_quote_color_system_mismatch_rejected():
    """PRD §3.4: "The chosen color must belong to the chosen system - that is, the
    color option's `coating_system_id` must equal the quote's `coating_system_id` -
    or the request is rejected with `ERR_COLOR_SYSTEM_MISMATCH`."

    Design: Corner/validations/quote_color_not_in_system_returns_mismatch
    """
    sys_a, _ = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    sys_b, color_b = create_system_with_color(family="FLAKE", sku="FLAKE_PREMIUM")
    cust = create_customer("Cora Customer", email="cora-mismatch@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(proj["id"])
    resp = api_client.create_quote(
        proj["id"],
        {"assessment_id": assess["id"], "coating_system_id": sys_a["id"],
         "color_option_id": color_b["id"], "install_season": "STANDARD"},
        SALES,
    )
    validate_error(resp, "ERR_COLOR_SYSTEM_MISMATCH")


# ===========================================================================
# Corner/validations/self_referral_rejected
# ===========================================================================
def test_self_referral_rejected():
    """PRD §3.2: "The referred customer must differ from the referrer; a request
    where the two are the same is rejected with `ERR_SELF_REFERRAL`."

    Design: Corner/validations/self_referral_rejected
    """
    cust = create_customer("Cora Customer", email="cora-self@example.com")
    proj = create_project(cust["id"])
    resp = api_client.create_referral(
        create_referral_payload(cust["id"], cust["id"], proj["id"]), SALES
    )
    validate_error(resp, "ERR_SELF_REFERRAL")


# ===========================================================================
# Corner/validations/quote_on_superseded_assessment_rejected
# ===========================================================================
def test_quote_on_superseded_assessment_rejected():
    """PRD §3.4: "The referenced assessment must be the project's `APPROVED`
    assessment and not a `SUPERSEDED` one; otherwise the quote is rejected with
    `ERR_ASSESSMENT_NOT_APPROVED`."

    Design: Corner/validations/quote_on_superseded_assessment_rejected
    """
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Cora Customer", email="cora-superseded@example.com")
    proj = create_project(cust["id"])
    assess1 = record_assessment(proj["id"])
    record_assessment(  # second assessment supersedes the first
        proj["id"], measured_sqft=650, oil_stain_pct=60, crack_density=25,
        crack_linear_ft=20, spalling=True, moisture_pct=40,
    )
    resp = api_client.create_quote(
        proj["id"],
        {"assessment_id": assess1["id"], "coating_system_id": sys["id"],
         "color_option_id": color["id"], "install_season": "STANDARD"},
        SALES,
    )
    validate_error(resp, "ERR_ASSESSMENT_NOT_APPROVED")


# ===========================================================================
# Corner/validations/financing_principal_too_low_rejected
# ===========================================================================
def test_financing_principal_too_low_rejected():
    """PRD §3.4: "A financing plan may be selected only if the quote's
    `grand_total_cents` is at least the plan's `min_principal_cents`; a principal
    below that floor is rejected with `ERR_FINANCING_PRINCIPAL_TOO_LOW`."

    Design: Corner/validations/financing_principal_too_low_rejected
    """
    fp = get_success_data(api_client.create_financing_plan(
        {"name": "Big Min", "apr_bps": 999, "term_months": 36, "min_principal_cents": 200000},
        ADMIN,
    ))
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Cora Customer", email="cora-fintoolow@example.com")
    proj = create_project(cust["id"])
    # 100 sqft FLAKE LIGHT -> grand 150000 < 200000.
    assess = record_assessment(
        proj["id"], measured_sqft=100, oil_stain_pct=20, crack_density=5,
        crack_linear_ft=0, spalling=False, moisture_pct=10,
    )
    resp = api_client.create_quote(
        proj["id"],
        {"assessment_id": assess["id"], "coating_system_id": sys["id"],
         "color_option_id": color["id"], "install_season": "STANDARD",
         "financing_plan_id": fp["id"]},
        SALES,
    )
    validate_error(resp, "ERR_FINANCING_PRINCIPAL_TOO_LOW")


# ===========================================================================
# Corner/rbac/missing_headers_returns_unauthenticated
# ===========================================================================
def test_missing_headers_unauthenticated():
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api_client.create_customer(
        create_customer_payload(full_name="Anon", email="anon@example.com"),
        headers={},  # no X-User-ID / X-User-Role
    )
    validate_error(resp, "ERR_UNAUTHENTICATED")


# ===========================================================================
# Corner/rbac/customer_cannot_create_coating_system_forbidden
# ===========================================================================
def test_customer_cannot_create_coating_system_forbidden():
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_create_coating_system_forbidden
    """
    cust = create_customer("Cora Customer", email="cora-forbidden@example.com")
    resp = api_client.create_coating_system(
        create_coating_system_payload(name="Sneaky", family="FLAKE", sku="FLAKE_STANDARD"),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# Corner/rbac/customer_cannot_accept_other_customers_quote_not_owner
# ===========================================================================
def test_non_owner_customer_accept_rejected():
    """PRD §2.1: "when a `Customer` accepts or declines a quote, files a warranty
    claim, or resubmits a claim, the system requires `X-User-ID` to equal the
    `customer_id` of the owning project; otherwise the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_accept_other_customers_quote_not_owner
    """
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust_a = create_customer("Cust A", email="a-owner@example.com")
    cust_b = create_customer("Cust B", email="b-other@example.com")
    proj = create_project(cust_a["id"])
    assess = record_assessment(proj["id"])
    q = create_estimate_quote(proj["id"], assess["id"], sys["id"], color["id"])
    send_quote(q["id"])
    pv = project_version(proj["id"])
    resp = api_client.accept_quote(
        q["id"], {"expected_project_version": pv}, make_customer_headers(cust_b["id"])
    )
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER")


# ===========================================================================
# Corner/endpoints/list_customer_projects_pagination_envelope
# ===========================================================================
def test_list_customer_projects_pagination():
    """PRD §2.3: "The `limit` parameter caps the number of items returned".
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_customer_projects_pagination_envelope
    """
    cust = create_customer("Cora Customer", email="cora-page@example.com")
    create_project(cust["id"], site_zip="94016")
    create_project(cust["id"], site_zip="94020")
    resp = api_client.list_customer_projects(cust["id"], SALES, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"limit 1 of 2 -> has_more true, got {meta['has_more']}"
    assert len(data) == 1, f"limit 1 returns 1 item, got {len(data)}"


# ===========================================================================
# Corner/endpoints/customer_referrals_reverse_reachability_after_referral
# ===========================================================================
def test_referral_discoverable_from_referrer():
    """PRD §3.9: "a customer's projects and referrals can be listed; the referrals
    listing accepts an optional `role` query parameter to filter to referrals where
    the customer is the referrer versus the referred."

    Design: Corner/endpoints/customer_referrals_reverse_reachability_after_referral
    """
    referrer = create_customer("Refa", email="refa-rev@example.com")
    referred = create_customer("Newt", email="newt-rev@example.com")
    proj = create_project(referred["id"])
    ref = get_success_data(api_client.create_referral(
        create_referral_payload(referrer["id"], referred["id"], proj["id"]), SALES
    ))
    resp = api_client.list_customer_referrals(referrer["id"], SALES)
    data, _ = validate_paginated(resp)
    ids = [r["id"] for r in data]
    assert ref["id"] in ids, f"referral {ref['id']} must be discoverable from referrer, got {ids}"
