"""Who may act, whose record they may act on, and what an unrecognised caller gets."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures, test_users

CLOCK = "2026-08-10T00:00:00Z"


def test_a_partner_cannot_issue_the_bill_it_is_going_to_be_charged_by(api):
    """Issuance is the bookkeeper's act; the party being billed has no hand in it.

    The acting role appears in the endpoint's role list, else `ERR_UNAUTHORIZED` (403).
    Issuance is the single most consequential operation in the service. A `JointInterestAccountant` issues a draft; the request carries no body.

    Design: Corner/rbac/a_partner_representative_cannot_issue_a_jib_statement
    """
    context = fixtures.setup_standard_june_statement(api, clock=CLOCK)

    validate_error(
        api.issue_jib_statement(context["statement_id"], context["partner_b_headers"]),
        "ERR_UNAUTHORIZED",
        403,
    )

    draft = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert draft["statement_status"] == "DRAFT"
    assert draft["issued_at"] is None

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 0

    issued = validate_success(
        api.issue_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert issued["statement_status"] == "ISSUED"


def test_the_land_department_has_no_standing_to_adjudicate_a_billing_dispute(api):
    """Role comes before conflict of interest: the land department is simply not the reviewer.

    Only an `AuditReviewer` resolves, and only a dispute whose `dispute_status` is `OPERATOR_RESPONDED` or `ESCALATED` (else `ERR_DISPUTE_NOT_RESOLVABLE`).
    The acting role appears in the endpoint's role list, else `ERR_UNAUTHORIZED` (403).

    Design: Corner/rbac/a_land_administrator_cannot_resolve_a_dispute
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)
    dispute = validate_success(
        api.file_dispute(
            context["statement_id"],
            factories.file_dispute_payload(
                context["partner_a_id"],
                100_000,
                basis_note="Overhead allocation questioned",
            ),
            context["partner_a_headers"],
        ),
        201,
    )

    validate_error(
        api.resolve_dispute(
            dispute["id"],
            factories.dispute_resolution_payload("UPHELD", 0),
            fixtures.LAND_ADMIN,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    read_dispute = validate_success(
        api.get_dispute(dispute["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert read_dispute["dispute_status"] == "OPEN"
    assert read_dispute["resolved_by_user_id"] is None

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "DISPUTED"


def test_one_partner_cannot_lodge_a_contest_in_another_partners_name(api):
    """The partner header is an owner identity, so it has to match the owner being represented.

    Concretely, a `PartnerRepresentative` may only submit an AFE election whose `owner_id` is itself, may only file a dispute whose `owner_id` is itself, may only record an exchange on a dispute whose `owner_id` is itself, and when listing owner disbursements sees only rows whose `owner_id` is itself. A violation of any of these is rejected with `ERR_OWNER_MISMATCH` (HTTP 403).

    Design: Corner/rbac/a_partner_representative_cannot_file_a_dispute_for_another_owner
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)
    body = factories.file_dispute_payload(
        context["partner_b_id"], 500_000, basis_note="Filed by the wrong partner"
    )

    validate_error(
        api.file_dispute(
            context["statement_id"], dict(body), context["partner_a_headers"]
        ),
        "ERR_OWNER_MISMATCH",
        403,
    )

    _, meta = validate_paginated(
        api.list_disputes(
            fixtures.JIB_ACCOUNTANT, params={"statement_id": context["statement_id"]}
        )
    )
    assert meta["total_count"] == 0

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "ISSUED"

    validate_success(
        api.file_dispute(
            context["statement_id"], dict(body), context["partner_b_headers"]
        ),
        201,
    )


def test_the_bookkeeper_cannot_edit_an_owners_bonding_posture(api):
    """Bond and taxpayer posture is a compliance record, not a billing one.

    A `ComplianceOfficer` — and only a `ComplianceOfficer` — updates that posture afterwards, supplying any subset of `tax_id_on_file`, `bond_posted_cents` and `audit_window_days`.

    Design: Corner/rbac/a_joint_interest_accountant_cannot_patch_owner_compliance_fields
    """
    fixtures.set_clock(api, CLOCK)
    owner = validate_success(
        api.create_interest_owner(
            factories.create_interest_owner_payload(
                owner_name="Epsilon Resources Inc",
                contact_email="epsilon@example.com",
                tax_id_on_file=False,
                bond_posted_cents=0,
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    validate_error(
        api.update_owner_compliance(
            owner["id"],
            factories.compliance_update_payload(bond_posted_cents=25_000_000),
            fixtures.JIB_ACCOUNTANT,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    for headers in (fixtures.JIB_ACCOUNTANT, fixtures.COMPLIANCE_OFFICER):
        read_owner = validate_success(api.get_interest_owner(owner["id"], headers), 200)
        assert read_owner["bond_posted_cents"] == 0
        assert read_owner["version"] == 1


def test_a_caller_with_no_recognised_role_never_gets_as_far_as_permissions(api):
    """A missing or unknown role is not a permission question; the caller is simply unknown.

    Both headers present and `X-User-Role` recognised, else `ERR_UNAUTHENTICATED` (401).

    Design: Corner/rbac/a_request_without_the_role_header_is_unauthenticated
    """
    fixtures.set_clock(api, CLOCK)

    validate_error(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-009",
                lessor_name="Omega Minerals",
                gross_acres=100.0,
                royalty_rate=0.125,
                primary_term_end_date="2027-03-31",
            ),
            test_users.headers_without_role("u-land-1"),
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-010",
                lessor_name="Theta Minerals",
                gross_acres=200.0,
                royalty_rate=0.2,
                primary_term_end_date="2027-03-31",
            ),
            test_users.make_headers("u-land-1", "RoyaltyAnalyst"),
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    _, meta = validate_paginated(api.list_leases(fixtures.LAND_ADMIN))
    assert meta["total_count"] == 0
