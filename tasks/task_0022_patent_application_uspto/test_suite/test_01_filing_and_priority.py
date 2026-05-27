"""Filing applications, claim-count validation, the system-stamped filing_date,
default entity-size on the applicant, and the priority-date inheritance rule
that distinguishes a CONTINUATION (inherits parent's filing_date) from a CIP
(uses its own filing_date).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_applicant_headers,
    create_applicant_payload, create_application_payload,
    set_clock, create_applicant, create_application,
    setup_parent_application_in_filed,
    api_client,
)

ADMIN = TEST_USERS["admin_headers"]


# =============================================================================
# Difficulty / dual_variant_calc / priority_date_continuation_vs_cip_diverges
# =============================================================================

def test_continuation_inherits_parent_filing_date_as_priority_date(api):
    """A CONTINUATION child filed off a parent UTILITY on a later day inherits
    the parent's filing_date as its priority_date.

    PRD §3.2: "For a `CONTINUATION`, the priority date is inherited from the
    parent's `filing_date` — preserving the earlier priority for prior-art
    purposes and (for a utility) anchoring the future term-expiration
    calculation 20 years from that earlier date."

    Design: Difficulty/dual_variant_calc/priority_date_continuation_vs_cip_diverges
    """
    set_clock("2024-02-01T00:00:00.000Z")
    applicant, parent = setup_parent_application_in_filed(entity_size="LARGE")
    parent_filing_date = parent["filing_date"]

    set_clock("2026-05-27T12:00:00.000Z")
    cont = create_application(
        applicant, application_type="UTILITY",
        title="Child A continuation", claim_count=10, independent_claim_count=2,
        parent_application_id=parent["id"], continuation_type="CONTINUATION",
    )
    assert cont["priority_date"] == parent_filing_date, (
        f"CONTINUATION priority_date must equal parent.filing_date "
        f"({parent_filing_date}), got {cont['priority_date']}"
    )


def test_cip_uses_its_own_filing_date_as_priority_date(api):
    """A CIP child filed off the same parent on the same later day uses its
    own filing_date as priority_date (not the parent's earlier filing_date).

    PRD §3.2: "For a `CIP`, the priority date is the new application's own
    `filing_date`, because a continuation-in-part introduces new matter that
    must be treated as filed today; this is the deliberate difference between
    the two continuation kinds, and the same parent-and-dates input yields
    two different `priority_date` values depending on which kind was chosen."

    Design: Difficulty/dual_variant_calc/priority_date_continuation_vs_cip_diverges
    """
    set_clock("2024-02-01T00:00:00.000Z")
    applicant, parent = setup_parent_application_in_filed(entity_size="LARGE")
    parent_filing_date = parent["filing_date"]

    set_clock("2026-05-27T12:00:00.000Z")
    cip = create_application(
        applicant, application_type="UTILITY",
        title="Child B CIP", claim_count=12, independent_claim_count=3,
        parent_application_id=parent["id"], continuation_type="CIP",
    )
    # CIP uses its own filing_date — observably different from parent's.
    assert cip["priority_date"] != parent_filing_date, (
        f"CIP priority_date must NOT equal parent.filing_date "
        f"({parent_filing_date}); got {cip['priority_date']}"
    )
    assert cip["priority_date"] == cip["filing_date"], (
        f"CIP priority_date must equal this filing_date ({cip['filing_date']}), "
        f"got {cip['priority_date']}"
    )


# =============================================================================
# Corner / entities / create_application_missing_title_returns_invalid_request
# =============================================================================

def test_create_application_missing_title_rejected(api):
    """Filing an application without `title` is rejected with ERR_INVALID_REQUEST.

    PRD §3.2: "An applicant files a patent application by submitting their
    `applicant_id`, the `application_type` (one of `UTILITY`, `DESIGN`,
    `PROVISIONAL`, or `PCT_NATIONAL`, immutable after creation), the
    invention's `title` (3 to 500 characters), and the two claim counts..."

    Design: Corner/entities/create_application_missing_title_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant = create_applicant(legal_name="NoTitle Co", entity_size="LARGE")
    payload = {
        "applicant_id": applicant["id"],
        "application_type": "UTILITY",
        # title intentionally omitted
        "claim_count": 10,
        "independent_claim_count": 2,
    }
    res = api.create_application(payload, make_applicant_headers(applicant["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# =============================================================================
# Corner / entities / create_applicant_default_entity_size_is_large
# =============================================================================

def test_create_applicant_default_entity_size_is_large(api, admin_headers):
    """Omitting `entity_size` on POST /applicants defaults the value to LARGE.

    PRD §3.1: "Creating an applicant requires the applicant's `legal_name`
    (a string of 2 to 200 characters) and, optionally, their declared
    `entity_size` (defaulting to `LARGE` when omitted, otherwise one of
    `SMALL` or `MICRO`)."

    Design: Corner/entities/create_applicant_default_entity_size_is_large
    """
    set_clock("2026-01-01T00:00:00.000Z")
    payload = {"legal_name": "Default Co", "prior_applications_filed": 0}
    res = api.create_applicant(payload, admin_headers)
    applicant = validate_success(res, 201)
    assert applicant["entity_size"] == "LARGE", (
        f"Default entity_size must be LARGE per PRD §3.1, got {applicant['entity_size']!r}"
    )


# =============================================================================
# Corner / entities / create_application_system_filing_date_overrides_client_input
# =============================================================================

def test_application_filing_date_equals_server_clock_at_creation(api):
    """filing_date is server-stamped from current_utc at creation; the field
    is not part of the POST input.

    PRD §3.2: "Upon successful creation, the application is stamped with
    `filing_date` equal to the server's current UTC instant (which also
    equals `created_at`, but the two are surfaced separately because
    business deadlines key off `filing_date` and not `created_at`)..."

    Design: Corner/entities/create_application_system_filing_date_overrides_client_input
    """
    set_clock("2026-05-27T08:00:00.000Z")
    applicant = create_applicant(legal_name="Sys Co", entity_size="LARGE")
    app = create_application(applicant, application_type="UTILITY",
                             title="Sys widget", claim_count=10,
                             independent_claim_count=2)
    assert app["filing_date"] == "2026-05-27T08:00:00.000Z", (
        f"filing_date must equal server clock at creation; "
        f"expected 2026-05-27T08:00:00.000Z, got {app['filing_date']}"
    )
    assert app["status"] == "FILED", (
        f"Initial status must be FILED, got {app['status']}"
    )


# =============================================================================
# Corner / entities / create_application_independent_greater_than_total_rejected
# =============================================================================

def test_independent_claim_count_greater_than_claim_count_rejected(api):
    """independent_claim_count exceeding claim_count is rejected with
    ERR_CLAIM_COUNTS_INVALID.

    PRD §3.2: "and `independent_claim_count` (the number of independent claims,
    an integer at least 1 and not exceeding `claim_count`). A violation of
    either claim-count rule rejects the request with `ERR_CLAIM_COUNTS_INVALID`."

    Design: Corner/entities/create_application_independent_greater_than_total_rejected
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant = create_applicant(legal_name="CC Co", entity_size="LARGE")
    res = api.create_application(
        create_application_payload(
            applicant_id=applicant["id"], application_type="UTILITY",
            title="CC widget", claim_count=5, independent_claim_count=10,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CLAIM_COUNTS_INVALID.value)


# =============================================================================
# Corner / entities / get_application_nonexistent_returns_not_found
# =============================================================================

def test_get_nonexistent_application_returns_not_found(api, admin_headers):
    """GET on a random UUID returns 404 ERR_APPLICATION_NOT_FOUND.

    PRD §2.5: "If a path-templated id does not match any existing record of
    the corresponding entity, the request is rejected with
    `ERR_APPLICATION_NOT_FOUND` (HTTP 404) before any body parsing or role
    check on the request body takes place."

    Design: Corner/entities/get_application_nonexistent_returns_not_found
    """
    set_clock("2026-01-01T00:00:00.000Z")
    res = api.get_application("00000000-0000-0000-0000-000000000000", admin_headers)
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value)
