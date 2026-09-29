"""Opening a short sale file, registering vendor firms, and assembling and
deciding the seller's hardship package."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_bpo_vendor,
    assert_case,
    assert_hardship_package,
    create_bpo_vendor_payload,
    create_case,
    create_case_payload,
    create_hardship_package_payload,
    file_document,
    is_valid_uuid,
    package_decision_payload,
    setup_accepted_package,
    setup_case_after_two_rejected_offers,
    setup_submitted_package,
    validate_error,
    validate_paginated,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_open_case_starts_both_dimensions_with_empty_ledger(api):
    """PRD §3.1: "`negotiation_status` begins at `INTAKE` and travels through
    `PACKAGE_REVIEW`, `MARKETED`, `OFFER_UNDER_REVIEW`, `APPROVAL_ACTIVE` and possibly
    `RENEGOTIATION` before settling at one of the two terminal values, `CLOSED` or
    `DECLINED`."
    PRD §3.1: "Alongside them the case carries a set of derived ledger quantities that
    begin empty and are maintained by the server thereafter: `junior_lien_count` and
    `failed_offer_count` at 0, `junior_contribution_total_cents` at 0,
    `price_reduction_required` at false, and both `final_value_cents` and
    `minimum_acceptable_net_cents` at null, since no opinion of value has yet been
    recorded."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the current
    instant on every mutation of that resource, and `version`, an integer that starts at
    1 when the resource is created and increases by exactly 1 on every mutation."

    Design: Corner/entities/create_case_returns_declared_defaults_and_version_one
    """
    payload = create_case_payload(property_address="1 Aspen Row, Reno NV")
    case = validate_success(api.create_case(payload, NEG), 201)

    assert_case(case)
    assert case["negotiation_status"] == "INTAKE"
    assert case["documentation_status"] == "DOC_PENDING"
    assert case["version"] == 1, f"a new case starts at version 1, got {case['version']}"
    assert case["junior_lien_count"] == 0
    assert case["failed_offer_count"] == 0
    assert case["junior_contribution_total_cents"] == 0
    assert case["price_reduction_required"] is False
    assert case["final_value_cents"] is None
    assert case["minimum_acceptable_net_cents"] is None
    assert case["deficiency_waiver_permitted"] is True
    assert case["assigned_negotiator_user_id"] == "neg-001", (
        "the opening write stamps assigned_negotiator_user_id with the acting X-User-ID"
    )
    assert is_valid_uuid(case["id"]), "the id must be a bare UUID with no type prefix"


def test_open_case_without_servicer_name_is_malformed(api):
    """PRD §3.1: "A `Negotiator` opens a short sale file by recording the
    `property_address` of the distressed property, the `servicer_name` of the shop that
    will review it, the `unpaid_principal_balance_cents` outstanding on the first-lien
    note — a whole-cent integer of at least 1 — and the `investor_type` that owns that
    note."
    PRD §2.6: "Required fields present, types correct, enum members recognised, numeric
    bounds honoured — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_case_missing_required_field_returns_invalid_request
    """
    payload = create_case_payload(property_address="2 Birch Way, Reno NV")
    del payload["servicer_name"]

    validate_error(
        api.create_case(payload, NEG), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    _, meta = validate_paginated(api.list_cases(NEG))
    assert meta["total_count"] == 0, "a malformed opening write must persist no case"


def test_open_case_with_unrecognised_investor_type_is_malformed(api):
    """PRD §3.1: "Only three investor types are recognised: `GSE`, `PORTFOLIO`, and
    `FHA`."
    PRD §2.6: "Required fields present, types correct, enum members recognised, numeric
    bounds honoured — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_case_invalid_enum_rejected
    """
    payload = create_case_payload(
        property_address="3 Cedar Ct, Reno NV", investor_type="PRIVATE"
    )

    validate_error(api.create_case(payload, NEG), ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_cases(NEG))
    assert meta["total_count"] == 0, "an unrecognised investor type must persist no case"


def test_open_case_ignores_client_supplied_server_owned_fields(api):
    """PRD §3.1: "`negotiation_status` begins at `INTAKE` and travels through
    `PACKAGE_REVIEW`, `MARKETED`, `OFFER_UNDER_REVIEW`, `APPROVAL_ACTIVE` and possibly
    `RENEGOTIATION` before settling at one of the two terminal values, `CLOSED` or
    `DECLINED`."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the current
    instant on every mutation of that resource, and `version`, an integer that starts at
    1 when the resource is created and increases by exactly 1 on every mutation."

    Design: Corner/entities/create_case_system_field_input_ignored
    """
    payload = create_case_payload(
        property_address="4 Dogwood Dr, Reno NV",
        investor_type="FHA",
        unpaid_principal_balance_cents=19_900_000,
    )
    payload["negotiation_status"] = "CLOSED"
    payload["version"] = 9

    case = validate_success(api.create_case(payload, NEG), 201)

    assert case["negotiation_status"] == "INTAKE", (
        "the negotiation dimension begins at INTAKE regardless of what the client sent"
    )
    assert case["version"] == 1, "version starts at 1 regardless of what the client sent"
    assert case["deficiency_waiver_permitted"] is True


def test_read_case_returns_the_stored_row_in_the_object_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/get_case_by_id_returns_stored_entity
    """
    case = create_case(property_address="5 Elder Ln, Reno NV")

    response = api.get_case(case["id"], NEG)
    stored = validate_success(response, 200)
    body = response.json()

    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert stored["unpaid_principal_balance_cents"] == 26_800_000
    assert stored["servicer_name"] == "Cascade Servicing"
    assert_case(stored)


def test_list_cases_pages_and_filters_on_the_negotiation_dimension(api):
    """PRD §2.3: "Every list response carries the four pagination fields inside `meta`:
    `limit` and `offset` echo the effective values actually applied, `total_count`
    reports the number of rows matching the filter before the page window is applied,
    and `has_more` is true exactly when rows remain beyond the current window."
    PRD §2.3: "Cases may be filtered on either state dimension, by `negotiation_status`
    or by `documentation_status` or both."

    Design: Corner/entities/list_cases_pagination_envelope_and_filter
    """
    create_case(property_address="6 Fir Pl, Reno NV")
    create_case(
        property_address="7 Gum St, Reno NV",
        investor_type="PORTFOLIO",
        unpaid_principal_balance_cents=31_000_000,
    )
    create_case(
        property_address="8 Hazel Ave, Reno NV",
        investor_type="FHA",
        unpaid_principal_balance_cents=19_900_000,
    )

    response = api.list_cases(NEG, params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 2, f"limit 2 must return exactly 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0

    _, filtered_meta = validate_paginated(
        api.list_cases(NEG, params={"negotiation_status": "INTAKE"})
    )
    assert filtered_meta["total_count"] == 3, "all three cases are still in INTAKE"


def test_registered_vendor_firm_carries_no_updated_at_or_version(api):
    """PRD §2.4: "The single exception is the vendor firm record. A vendor firm is
    immutable configuration — it has no update and no delete route — and it therefore
    carries only `id` and `created_at`. Neither `updated_at` nor `version` exists on a
    vendor firm, and neither field should appear in its representation."
    PRD §3.6: "A `PlatformAdmin` registers a broker-price-opinion firm with its
    `vendor_name`, the `license_state` two-letter code it is licensed in, and its
    `daily_inspection_capacity` — the greatest number of inspections, at least 1, that
    the firm may hold on any single UTC calendar date."

    Design: Corner/entities/bpo_vendor_is_immutable_configuration_row
    """
    vendor = validate_success(
        api.create_bpo_vendor(create_bpo_vendor_payload(), ADMIN), 201
    )

    assert vendor["vendor_name"] == "Sierra Valuation Partners"
    assert vendor["daily_inspection_capacity"] == 2
    assert "id" in vendor and "created_at" in vendor
    assert "updated_at" not in vendor, "a vendor firm carries no updated_at"
    assert "version" not in vendor, "a vendor firm carries no version"
    assert_bpo_vendor(vendor)


def test_deficiency_waiver_permitted_tracks_the_investor_type(api):
    """PRD §3.1: "`deficiency_waiver_permitted` is set to true when the investor is
    `GSE` or `FHA`, and to false when the investor is `PORTFOLIO`."

    Design: Corner/entities/computed_deficiency_waiver_permitted_false_for_portfolio
    """
    portfolio_case = create_case(
        property_address="9 Ironwood Rd, Reno NV",
        investor_type="PORTFOLIO",
        unpaid_principal_balance_cents=42_000_000,
    )
    gse_case = create_case(property_address="10 Juniper Way, Reno NV")

    assert portfolio_case["deficiency_waiver_permitted"] is False
    assert gse_case["deficiency_waiver_permitted"] is True


def test_second_hardship_package_on_a_case_is_a_duplicate(api):
    """PRD §3.1: "Each case admits **at most one** hardship package. A second attempt to
    assemble one is refused with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_hardship_package_on_case_rejected
    """
    case = create_case()
    first = validate_success(
        api.create_hardship_package(case["id"], create_hardship_package_payload(), NEG), 201
    )

    duplicate = api.create_hardship_package(
        case["id"],
        create_hardship_package_payload(
            hardship_reason="MEDICAL",
            monthly_income_cents=400_000,
            monthly_expenses_cents=500_000,
            liquid_assets_cents=100_000,
        ),
        NEG,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    packages = validate_success(api.list_case_hardship_packages(case["id"], NEG), 200)
    assert len(packages) == 1, "the case still carries exactly one hardship package"
    assert packages[0]["id"] == first["id"]
    assert packages[0]["hardship_reason"] == "JOB_LOSS", (
        "the rejected duplicate must not overwrite the stored package"
    )


def test_submission_with_a_missing_required_document_kind_is_refused(api):
    """PRD §3.3: "Before a `DRAFT` package can move to `SUBMITTED`, every one of the four
    required document kinds must have at least one document on the package whose status
    is either `PENDING` or `VERIFIED` — a filed-but-unreviewed document counts here, a
    rejected one does not. A submission attempted with a gap is refused with
    `ERR_REQUIRED_DOCUMENT_MISSING`."
    PRD §3.1: "Both score fields, `hardship_score_intake` and `hardship_score_audit`,
    start null; neither is computed at assembly time."

    Design: Corner/validations/required_document_missing_blocks_package_submission
    """
    case = create_case()
    package = validate_success(
        api.create_hardship_package(case["id"], create_hardship_package_payload(), NEG), 201
    )
    for doc_type in ("HARDSHIP_LETTER", "FINANCIAL_WORKSHEET", "BANK_STATEMENT"):
        file_document(package["id"], doc_type)

    validate_error(
        api.submit_hardship_package(package["id"], NEG),
        ApiErrorId.ERR_REQUIRED_DOCUMENT_MISSING.value,
    )

    stored = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored["status"] == "DRAFT"
    assert stored["hardship_score_intake"] is None
    assert stored["document_count"] == 3
    assert_hardship_package(stored)

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["negotiation_status"] == "INTAKE"


def test_submitting_an_accepted_package_is_not_actionable(api):
    """PRD §3.3: "Submitting a package that is neither `DRAFT` nor
    `REVALIDATION_REQUIRED` is refused with `ERR_PACKAGE_NOT_ACTIONABLE`."

    Design: Corner/state_machines/submit_accepted_package_returns_package_not_actionable
    """
    case, package, _ = setup_accepted_package()
    assert package["status"] == "ACCEPTED"
    intake_score_before = package["hardship_score_intake"]

    validate_error(
        api.submit_hardship_package(package["id"], NEG),
        ApiErrorId.ERR_PACKAGE_NOT_ACTIONABLE.value,
    )

    stored = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored["status"] == "ACCEPTED"
    assert stored["hardship_score_intake"] == pytest.approx(76.25)
    assert stored["hardship_score_intake"] == intake_score_before, (
        "a refused submit must not recompute hardship_score_intake"
    )

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["negotiation_status"] == "MARKETED"


def test_package_rejection_stamps_the_audit_score_and_declines_the_case(api):
    """PRD §3.3: "The audit score is computed and stamped into `hardship_score_audit`
    **before** the outcome is evaluated, so it is persisted even when the decision that
    follows fails."
    PRD §3.3: "A `REJECT` carries no score floor at all: it moves the package to the
    terminal `REJECTED` and carries the case's negotiation dimension from
    `PACKAGE_REVIEW` to `DECLINED`, ending the file."

    Design: Corner/state_machines/package_reject_declines_case
    """
    case, package, _ = setup_submitted_package()

    decided = validate_success(
        api.decide_hardship_package(package["id"], package_decision_payload("REJECT"), ANALYST),
        200,
    )

    assert decided["status"] == "REJECTED"
    assert decided["hardship_score_audit"] == pytest.approx(76.25), (
        "the audit score is stamped even on a rejection"
    )

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["negotiation_status"] == "DECLINED"
    assert case_after["documentation_status"] == "DOC_COMPLETE", (
        "the documentation dimension is untouched by the package decision"
    )


def test_revalidation_resubmit_recovers_the_documentation_dimension(api):
    """PRD §3.3: "when a `REVALIDATION_REQUIRED` package is re-submitted the negotiation
    dimension is left alone and the documentation dimension instead recovers from
    `DOC_STALE` to `DOC_PENDING`."
    PRD §3.3: "Every submission stamps `hardship_score_intake`. Every servicer decision
    stamps `hardship_score_audit`."

    Design: Corner/state_machines/package_revalidation_resubmit_restores_documentation_pending
    """
    scenario = setup_case_after_two_rejected_offers()
    assert scenario["package"]["status"] == "REVALIDATION_REQUIRED"
    assert scenario["case"]["documentation_status"] == "DOC_STALE"

    resubmitted = validate_success(
        api.submit_hardship_package(scenario["package"]["id"], NEG), 200
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["hardship_score_intake"] == pytest.approx(76.25)

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["documentation_status"] == "DOC_PENDING"
    assert case_after["price_reduction_required"] is True, (
        "re-submitting the package does not clear the price-reduction gate"
    )
    assert case_after["failed_offer_count"] == 2
