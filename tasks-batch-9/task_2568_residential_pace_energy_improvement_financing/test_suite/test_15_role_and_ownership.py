"""Who may call, who may call it on this row, and who may not call it twice in two hats.

The three refusals kept apart here are the role check (403 unauthorized), the ownership check
(403 wrong row) and segregation of duties (422 right role, wrong person).
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import ROLE_COMPLIANCE_OFFICER
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    FUNDING_OFFICER_RELEASER,
    FUNDING_OFFICER_VERIFIER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
    contractor_headers,
    headers_for_role,
    owner_headers,
)


def _free_and_clear_draft(client, with_measure=True):
    """A DRAFT application on a parcel with no liens, plus a second parcel to intrude from."""
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(client)
    parcel = fixtures.seed_parcel(client, with_senior_lien=False)
    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                parcel["property_id"], contractor["contractor_id"], 20
            ),
            parcel["owner_headers"],
        )
    )
    world = {
        "solar_product_id": catalog["solar_product_id"],
        "contractor_id": contractor["contractor_id"],
        "property_id": parcel["property_id"],
        "owner_headers": parcel["owner_headers"],
        "owner_full_name": parcel["owner_full_name"],
        "application_id": application["id"],
        "opening_version": application["version"],
    }
    if with_measure:
        measure = A.expect_created(
            client.add_measure(
                application["id"],
                factories.solar_measure_payload(
                    catalog["solar_product_id"], application["version"]
                ),
                parcel["owner_headers"],
            )
        )
        world["solar_measure_id"] = measure["id"]
    return world


def test_neither_the_owner_nor_the_contractor_may_borrow_the_others_endpoint(client):
    """Exclusive writes are refused on the role alone, while the shared reads stay open to both.

    The declared `X-User-Role` must be among the endpoint's authorized roles, otherwise
    `ERR_UNAUTHORIZED` (403).

    Design: Corner/rbac/owner_and_contractor_cannot_use_each_others_exclusive_endpoints
    """
    world = _free_and_clear_draft(client)
    contractor_caller = contractor_headers(world["contractor_id"])

    A.expect_error(
        client.open_application(
            factories.application_payload(
                world["property_id"], world["contractor_id"], 20
            ),
            contractor_caller,
        ),
        ERR_UNAUTHORIZED,
    )
    A.expect_error(
        client.file_certificate(
            factories.certificate_payload(
                world["application_id"], [world["solar_measure_id"]], 3000000
            ),
            world["owner_headers"],
        ),
        ERR_UNAUTHORIZED,
    )
    A.expect_error(
        client.submit_application(world["application_id"], COUNTY_OFFICER),
        ERR_UNAUTHORIZED,
    )

    shared = A.expect_ok(
        client.get_application(world["application_id"], contractor_caller)
    )
    A.assert_fields(shared, status="DRAFT")

    _apps, app_meta = A.expect_page(
        client.list_applications(
            PROGRAM_ADMIN, params={"property_id": world["property_id"]}
        )
    )
    A.assert_total_count(app_meta, 1)
    _certs, cert_meta = A.expect_page(
        client.list_application_certificates(world["application_id"], PROGRAM_ADMIN)
    )
    A.assert_total_count(cert_meta, 0)


def test_the_analyst_who_underwrote_may_not_approve_in_a_compliance_hat(client):
    """Right role, wrong human: 422 rather than 403, and a second officer completes the call.

    The approver must differ from the underwriter, and the releaser must differ from the
    certificate verifier, otherwise `ERR_SEGREGATION_OF_DUTIES` (422).

    Design: Corner/rbac/approval_by_the_underwriting_user_violates_segregation_of_duties
    """
    world = _free_and_clear_draft(client)
    A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    underwritten = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        consent_posture="CLEARED",
        underwriter_user_id="u_ana_1",
    )

    A.expect_error(
        client.approve_application(
            world["application_id"],
            headers_for_role(ROLE_COMPLIANCE_OFFICER, "u_ana_1"),
            {"note": "self approval attempt"},
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    blocked = A.expect_ok(
        client.get_application(world["application_id"], PROGRAM_ADMIN)
    )
    A.assert_fields(blocked, status="CONSENT_PENDING")
    A.assert_absent_or_none(blocked, "approver_user_id")

    approved = A.expect_ok(
        client.approve_application(
            world["application_id"], COMPLIANCE_OFFICER, {"note": "independent review"}
        )
    )
    A.assert_fields(
        approved,
        status="APPROVED",
        approver_user_id="u_comp_1",
        underwriter_user_id="u_ana_1",
        consent_posture="CLEARED",
    )
    _liens, lien_meta = A.expect_page(
        client.list_mortgage_liens(
            PROGRAM_ADMIN,
            params={"consent_application_id": world["application_id"]},
        )
    )
    A.assert_total_count(lien_meta, 0)


def test_the_officer_who_verified_the_certificate_may_request_but_not_release(client):
    """Requesting is not a segregated act; releasing is, and the second officer completes it.

    The releasing officer's `X-User-ID` must differ from the certificate's
    `verified_by_user_id`, or the call fails with `ERR_SEGREGATION_OF_DUTIES`.

    Design: Corner/rbac/release_by_the_certificate_verifier_violates_segregation_of_duties
    """
    world = _free_and_clear_draft(client)
    A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    approved = A.expect_ok(
        client.approve_application(world["application_id"], COMPLIANCE_OFFICER)
    )
    agreement = A.expect_created(
        client.issue_agreement(
            factories.agreement_payload(
                world["application_id"], approved["version"], 20, 800
            ),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(agreement, contractor_payable_cents=3000000)
    A.expect_ok(
        client.sign_agreement(
            agreement["id"],
            factories.sign_agreement_payload(world["owner_full_name"]),
            world["owner_headers"],
        )
    )

    fixtures.move_clock(client, fixtures.RELEASE_CLOCK)
    certificate = A.expect_created(
        client.file_certificate(
            factories.certificate_payload(
                world["application_id"], [world["solar_measure_id"]], 3000000
            ),
            contractor_headers(world["contractor_id"]),
        )
    )
    A.expect_ok(
        client.sign_certificate(
            certificate["id"],
            factories.sign_certificate_payload(world["owner_full_name"]),
            world["owner_headers"],
        )
    )
    verified = A.expect_ok(
        client.verify_certificate(
            certificate["id"],
            factories.verify_certificate_payload("APPROVE"),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    A.assert_fields(verified, verified_by_user_id="u_fund_v")
    draw = A.expect_created(
        client.request_disbursement(
            factories.disbursement_payload(
                world["application_id"],
                certificate["id"],
                world["contractor_id"],
                3000000,
            ),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    A.assert_fields(draw, status="REQUESTED")

    A.expect_error(
        client.release_disbursement(draw["id"], FUNDING_OFFICER_VERIFIER),
        ERR_SEGREGATION_OF_DUTIES,
    )
    held_back = A.expect_ok(client.get_disbursement(draw["id"], PROGRAM_ADMIN))
    A.assert_fields(held_back, status="REQUESTED")
    A.assert_absent_or_none(held_back, "released_at", "released_by_user_id")
    A.assert_contractor_ledger(
        A.expect_ok(client.get_contractor(world["contractor_id"], PROGRAM_ADMIN)), 0, 0
    )
    A.assert_fields(
        A.expect_ok(client.get_agreement(agreement["id"], PROGRAM_ADMIN)),
        status="SIGNED",
    )

    released = A.expect_ok(
        client.release_disbursement(draw["id"], FUNDING_OFFICER_RELEASER)
    )
    A.assert_fields(released, status="RELEASED", released_by_user_id="u_fund_r")
    ledger = A.expect_ok(
        client.get_contractor(world["contractor_id"], PROGRAM_ADMIN)
    )
    A.assert_contractor_ledger(ledger, 3000000, 0)
    A.assert_fields(ledger, net_disbursed_cents=3000000)
    A.assert_fields(
        A.expect_ok(client.get_agreement(agreement["id"], PROGRAM_ADMIN)),
        status="EFFECTIVE",
    )
    A.assert_fields(
        A.expect_ok(client.get_application(world["application_id"], PROGRAM_ADMIN)),
        status="FUNDED",
    )


def test_a_neighbour_cannot_write_on_a_foreign_application(client):
    """Same role, wrong row: 403 ERR_NOT_RESOURCE_OWNER, and the owner's version survives it.

    An identity-bearing caller's `X-User-ID` must equal the identifier of the entity it acts
    for: a `PropertyOwner` must match the application's parcel reference, a `Contractor` must
    match the application's `contractor_id`. Otherwise `ERR_NOT_RESOURCE_OWNER` (403).

    Design: Corner/rbac/owner_of_another_parcel_cannot_add_measures_to_a_foreign_application
    """
    world = _free_and_clear_draft(client, with_measure=False)
    neighbour = fixtures.seed_parcel(
        client, payload=factories.second_property_payload(), with_senior_lien=False
    )
    intruder = owner_headers(neighbour["property_id"])

    A.expect_error(
        client.add_measure(
            world["application_id"],
            factories.solar_measure_payload(
                world["solar_product_id"], world["opening_version"]
            ),
            intruder,
        ),
        ERR_NOT_RESOURCE_OWNER,
    )
    A.expect_error(
        client.submit_application(world["application_id"], intruder),
        ERR_NOT_RESOURCE_OWNER,
    )

    A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.solar_measure_payload(
                world["solar_product_id"], world["opening_version"]
            ),
            world["owner_headers"],
        )
    )
    _rows, meta = A.expect_page(
        client.list_measures(
            PROGRAM_ADMIN, params={"application_id": world["application_id"]}
        )
    )
    A.assert_total_count(meta, 1)
    A.assert_fields(
        A.expect_ok(client.get_application(world["application_id"], PROGRAM_ADMIN)),
        status="DRAFT",
    )


def test_the_contractor_is_off_the_report_but_keeps_the_shared_reads(client):
    """One read is role-restricted and the neighbouring ones are not, and no read writes.

    The **eligibility report** is a computed read available to the owner, to underwriting, to
    compliance and to the program administrator, which recomputes every eligibility figure
    under *both* valuation bases and persists nothing.

    Design: Corner/rbac/contractor_is_excluded_from_the_eligibility_report_but_shares_the_reads
    """
    world = _free_and_clear_draft(client)
    A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    contractor_caller = contractor_headers(world["contractor_id"])

    A.expect_error(
        client.get_eligibility_report(world["application_id"], contractor_caller),
        ERR_UNAUTHORIZED,
    )

    for caller in (world["owner_headers"], PROGRAM_ADMIN):
        report = A.expect_ok(
            client.get_eligibility_report(world["application_id"], caller)
        )
        A.assert_fields(
            report, approved_principal_cents=3000000, portfolio_sir_bps=12770
        )
        A.assert_absent_or_none(report, "blocking_error_id")

    rows, meta = A.expect_page(
        client.list_measures(
            contractor_caller, params={"application_id": world["application_id"]}
        )
    )
    A.assert_total_count(meta, 1)
    A.assert_fields(rows[0], sir_bps=12770)
    A.assert_fields(
        A.expect_ok(client.get_application(world["application_id"], contractor_caller)),
        status="UNDER_REVIEW",
    )

    final = A.expect_ok(client.get_application(world["application_id"], PROGRAM_ADMIN))
    A.assert_fields(final, status="UNDER_REVIEW")
    A.assert_absent_or_none(final, "underwriter_user_id")
