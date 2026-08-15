"""Authentication, role gating, ownership, share-sum integrity, and
validation-tier precedence (PRD sections 2.1, 2.8, 3.2, 3.6)."""
from test_helpers import (
    ApiErrorId,
    create_accepted_report,
    create_active_agreement,
    create_agreement_payload,
    create_licensee,
    create_licensee_payload,
    create_royalty_report_payload,
    make_licensee_headers,
    make_report_line,
    submit_report,
    terminate_agreement,
    validate_error,
)


def test_request_without_role_header_unauthenticated(api):
    """PRD section 2.1: "A request with a missing header, or a role value
    outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_without_role_header_unauthenticated
    """
    # Headers carrying only an X-User-ID, no X-User-Role.
    resp = api.create_licensee(
        {"legal_name": "NoHdr", "tax_id": "TAX-NH-1", "contact_email": "nh@x.test"},
        {"X-User-ID": "someone"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_licensee_role_forbidden_to_validate(api, analyst_headers):
    """PRD section 2.1: "A request whose role is well-formed but not
    permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)." PRD section 3.6: "Intake screening is an analyst function. A
    `LicensingAnalyst` validates a `SUBMITTED` report".

    Design: Corner/validations/licensee_role_forbidden_to_validate
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-55556-F2", underreport_tolerance_bp=1000
    )
    report = submit_report(
        agreement, licensee, lines=[make_report_line(gross_sales_cents=10_000)]
    )
    resp = api.validate_report(
        report["id"], {"benchmark_net_sales_cents": 0},
        make_licensee_headers(licensee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_licensee_ownership_enforced_on_report_submit(api, analyst_headers):
    """PRD section 2.1: "ownership checks on any resource that references a
    licensee compare the resource's `licensee_id` field to `X-User-ID`, and a
    mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This
    ownership rule governs report submission, sublicense requests, finding
    acceptance, finding disputes, dispute offers and offer acceptance, and
    read access to the licensee's own record".

    Design: Corner/validations/licensee_ownership_enforced
    """
    la = create_licensee(legal_name="Own A")
    lb = create_licensee(legal_name="Own B")
    _, agreement = create_active_agreement(la, patent_reference="US-44445-E2")

    # B submits a report naming A's licensee_id under A's agreement.
    payload = create_royalty_report_payload(
        agreement["id"], la["id"], lines=[make_report_line(gross_sales_cents=1000)]
    )
    resp = api.create_royalty_report(payload, make_licensee_headers(lb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_inventor_share_sum_invalid(api, analyst_headers):
    """PRD section 3.2: "the shares must sum to exactly 10000 basis points
    and each `inventor_name` must be unique within the agreement — a
    submission violating either rule is rejected with `ERR_SHARE_SUM_INVALID`
    (HTTP 422)."

    Design: Corner/validations/inventor_share_sum_invalid
    """
    licensee = create_licensee(legal_name="Sh Co")
    payload = create_agreement_payload(
        licensee["id"], patent_reference="US-88889-I2",
        inventor_shares=[{"inventor_name": "Ada", "share_bp": 5000},
                         {"inventor_name": "Alan", "share_bp": 4000}],
    )
    resp = api.create_agreement(payload, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID)


def test_inventor_share_duplicate_name_invalid(api, analyst_headers):
    """PRD section 3.2: "the shares must sum to exactly 10000 basis points
    and each `inventor_name` must be unique within the agreement — a
    submission violating either rule is rejected with `ERR_SHARE_SUM_INVALID`
    (HTTP 422)."

    Design: Corner/validations/inventor_share_sum_invalid
    """
    licensee = create_licensee(legal_name="Sh2 Co")
    payload = create_agreement_payload(
        licensee["id"], patent_reference="US-88890-I3",
        inventor_shares=[{"inventor_name": "Ada", "share_bp": 6000},
                         {"inventor_name": "Ada", "share_bp": 4000}],
    )
    resp = api.create_agreement(payload, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID)


def test_state_beats_constraint_on_report_create(api, analyst_headers):
    """PRD section 2.8: "Every request is validated against an ordered
    pipeline of check tiers. A request that fails an earlier tier never
    surfaces an error from a later tier — the first failing tier determines
    the response." Tier 7 is "Agreement standing. Operations that require the
    agreement in a particular status set are checked here; failures yield
    `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)." and tier 10 carries
    "`ERR_REPORT_PERIOD_OVERLAP`". PRD section 3.6: "A colliding submission is
    rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_constraint_on_report_create
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-90900-H1", underreport_tolerance_bp=1000
    )
    # An ACCEPTED report over [2026-02-01, 2026-02-28).
    create_accepted_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="A", gross_sales_cents=100_000)],
    )
    terminate_agreement(agreement["id"])

    # Same period collides (tier 10) AND agreement is TERMINATED (tier 7).
    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"],
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=5000)],
    )
    resp = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    # The earlier tier (agreement standing) determines the response.
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_constraint_fires_when_state_passes(api, analyst_headers):
    """PRD section 2.8: "A request that fails an earlier tier never surfaces
    an error from a later tier — the first failing tier determines the
    response." PRD section 3.6: "A colliding submission is rejected with
    `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)." With the agreement ACTIVE, the
    overlap rule is the first failing tier.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_constraint_on_report_create
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-90901-H2", underreport_tolerance_bp=1000
    )
    create_accepted_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="A", gross_sales_cents=100_000)],
    )
    # Identical period on the still-ACTIVE agreement: only the overlap fires.
    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"],
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=5000)],
    )
    resp = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)
