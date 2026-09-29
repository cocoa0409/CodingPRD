"""Pre-built identity headers for the seven roles named by the PRD.

Two of the roles are scoped to a record: an ``InstitutionOfficer`` acts as the
lender itself, so its ``X-User-ID`` must be the institution's own identifier,
and a ``Borrower`` acts as the obligor of record, so its ``X-User-ID`` must be
the borrower's own identifier. Every call that is ownership-gated must go
through the per-instance builders below rather than the shared constants.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque identities used verbatim across the suite; the same reviewer,
# underwriter, committee member, analyst and administrator identifiers are
# reused so that segregation-of-duties assertions can be stated explicitly.
REVIEWER_ONE = "rev-1"
REVIEWER_TWO = "rev-2"
UNDERWRITER_ONE = "uw-1"
UNDERWRITER_TWO = "uw-2"
COMMITTEE_ONE = "cc-1"
COMMITTEE_TWO = "cc-2"
ANALYST_ONE = "ops-1"
ADMINISTRATOR_ONE = "adm-1"
ADMINISTRATOR_TWO = "adm-2"

TEST_USERS = {
    # Record-scoped roles: these shared constants are only safe for requests
    # whose outcome does not depend on the caller owning the subject record
    # (bad-payload rejections, unknown-identifier rejections, role checks).
    "institution_officer_headers": build_user_headers(
        "test-institution-officer-1", "InstitutionOfficer"
    ),
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    # Opaque roles: the shared constant is the canonical form.
    "certification_reviewer_headers": build_user_headers(
        REVIEWER_ONE, "CertificationReviewer"
    ),
    "certification_reviewer_two_headers": build_user_headers(
        REVIEWER_TWO, "CertificationReviewer"
    ),
    "credit_underwriter_headers": build_user_headers(
        UNDERWRITER_ONE, "CreditUnderwriter"
    ),
    "credit_underwriter_two_headers": build_user_headers(
        UNDERWRITER_TWO, "CreditUnderwriter"
    ),
    "credit_committee_headers": build_user_headers(COMMITTEE_ONE, "CreditCommittee"),
    "credit_committee_two_headers": build_user_headers(
        COMMITTEE_TWO, "CreditCommittee"
    ),
    "compliance_analyst_headers": build_user_headers(ANALYST_ONE, "ComplianceAnalyst"),
    "award_administrator_headers": build_user_headers(
        ADMINISTRATOR_ONE, "AwardAdministrator"
    ),
    "award_administrator_two_headers": build_user_headers(
        ADMINISTRATOR_TWO, "AwardAdministrator"
    ),
}


def make_institution_officer_headers(institution_id: str) -> dict:
    """Headers for the officer of one specific lender.

    Pass the institution's own identifier: institution scope is enforced by
    comparing ``X-User-ID`` against the owning institution of the record.
    """
    return build_user_headers(institution_id, "InstitutionOfficer")


def make_borrower_headers(borrower_id: str) -> dict:
    """Headers for one specific borrower of record.

    Pass the borrower's own identifier: borrower scope is enforced by
    comparing ``X-User-ID`` against the borrower obligated on the loan.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_certification_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CertificationReviewer")


def make_credit_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditUnderwriter")


def make_credit_committee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditCommittee")


def make_compliance_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_award_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AwardAdministrator")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity/role pair, for role-matrix and identity tests."""
    return build_user_headers(user_id, role)
