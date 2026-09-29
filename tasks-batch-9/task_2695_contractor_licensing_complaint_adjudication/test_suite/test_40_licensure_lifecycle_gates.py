"""Validation gates along the licensure lifecycle.

Covers the gates that guard filing and submitting a licence application, the
carrier-confirmation tests on a bond, the window and ownership rules on a
qualifier designation, the continuing-education credit constraint and the
present-compliance gate on renewal. Every test drives the API from an empty
database through the endpoints the PRD declares.
"""

from test_helpers import (
    LICENSING_ANALYST_HEADERS,
    assert_fields,
    factories as F,
    fixtures as X,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_second_live_application_for_the_same_classification_is_refused(api):
    """A second non-terminal application for one trade is refused.

    PRD: "A contracting entity may not hold two applications for the same
    `classification_id` in a non-terminal status — that is, while another
    application of theirs for that trade sits in `DRAFT`, `SUBMITTED` or
    `DEFICIENT` — and a second such filing is refused with
    `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/validations/corner_second_live_application_for_the_same_classification_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    licensee = X.register_licensee(
        api, legal_name="Twice Electric LLC", contact_email="twice@x.test"
    )
    individual = X.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        full_name="Tia Twice",
    )
    first = X.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=400000,
    )

    response = api.create_application(
        F.application_payload(
            licensee["id"],
            classification["id"],
            individual["id"],
            declared_net_worth_cents=500000,
        ),
        make_licensee_headers(licensee["id"]),
    )

    validate_error(response, "ERR_DUPLICATE_APPLICATION")
    assert_fields(
        validate_success(api.get_application(first["id"], LICENSING_ANALYST_HEADERS)),
        {"status": "DRAFT"},
    )
    _, meta = validate_paginated(
        api.list_applications(
            LICENSING_ANALYST_HEADERS, {"licensee_id": licensee["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_declared_net_worth_below_minimum_is_refused_at_submission(api):
    """Submitting with net worth under the classification floor is refused.

    PRD: "The financial-responsibility test is direct: `declared_net_worth_cents`
    must be at least the classification's `min_net_worth_cents`, or the
    submission is refused with `ERR_NET_WORTH_INSUFFICIENT`."

    Design: Corner/validations/corner_declared_net_worth_below_the_minimum_is_rejected_at_submit
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    licensee = X.register_licensee(
        api, legal_name="Thin Electric LLC", contact_email="thin@x.test"
    )
    individual = X.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        full_name="Thea Thin",
    )
    application = X.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=100000,
    )

    response = api.submit_application(
        application["id"], make_licensee_headers(licensee["id"])
    )

    validate_error(response, "ERR_NET_WORTH_INSUFFICIENT")
    assert_fields(
        validate_success(
            api.get_application(application["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": "DRAFT", "submitted_at": None},
    )


def test_bond_below_required_face_amount_is_refused_at_verification(api):
    """A bond whose face amount misses the trade floor cannot be confirmed.

    PRD: "Second, and only for a `BOND`, the **amount floor**: `amount_cents`
    must be at least the `required_bond_amount_cents` of the licence's own trade
    classification, or the verification is refused with
    `ERR_BOND_AMOUNT_INSUFFICIENT`."

    Design: Corner/validations/corner_bond_below_the_required_face_amount_is_rejected_at_verification
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="Short Bond Electric LLC",
        contact_email="shortbond@x.test",
        full_name="Shorty Bond",
        verified_experience_months=60,
        education_credential="NONE",
        declared_net_worth_cents=400000,
    )
    record = X.file_coverage(
        api,
        ctx.license_id,
        coverage_type="BOND",
        carrier_name="Thin Surety",
        policy_number="BND-SHORT",
        amount_cents=900000,
        effective_date="2026-08-01",
        expiration_date="2027-08-01",
    )

    response = api.verify_coverage_record(
        record["id"], F.verification_payload("VERIFY"), LICENSING_ANALYST_HEADERS
    )

    validate_error(response, "ERR_BOND_AMOUNT_INSUFFICIENT")
    assert_fields(
        validate_success(
            api.get_coverage_record(record["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": "PENDING_VERIFICATION", "verified_on": None},
    )
    assert_fields(
        X.read_license(api, ctx.license_id), {"compliance_posture": "NON_COMPLIANT"}
    )


def test_designation_starting_before_the_license_term_is_refused(api):
    """A designation window opening before the licence issued is refused.

    PRD: "Finally the **window containment**: `effective_from` must be on or
    after the licence's `issued_on`, and `effective_to`, when supplied, must be
    on or before the licence's `expires_on`; a window escaping either boundary
    draws `ERR_ASSIGNMENT_EFFECTIVE_DATE_INVALID`."

    Design: Corner/validations/corner_designation_starting_before_the_license_term_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="Backdate Electric LLC",
        contact_email="backdate@x.test",
        full_name="Bart Backdate",
        verified_experience_months=60,
        education_credential="NONE",
        declared_net_worth_cents=400000,
    )
    newcomer = X.register_qualifying_individual(
        api, full_name="Nora Newqualifier", verified_experience_months=72
    )
    before = X.read_license(api, ctx.license_id)

    response = X.designate_qualifier(
        api,
        ctx.license_id,
        newcomer["id"],
        before["version"],
        effective_from="2026-07-01",
    )

    validate_error(response, "ERR_ASSIGNMENT_EFFECTIVE_DATE_INVALID")
    assert_fields(
        X.read_license(api, ctx.license_id),
        {
            "version": before["version"],
            "qualifying_individual_id": ctx.individual_id,
        },
    )
    assert_fields(
        validate_success(
            api.get_qualifying_individual(newcomer["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"active_qualification_count": 0},
    )


def test_managing_officer_below_ten_percent_ownership_is_refused(api):
    """An officer designation under the ownership floor is refused.

    PRD: "Then the **ownership floor**: a `RESPONSIBLE_MANAGING_OFFICER` must own
    at least ten percent of the entity, so an `ownership_pct` below 10 with that
    relationship type draws `ERR_OWNERSHIP_PCT_INSUFFICIENT`; a
    `RESPONSIBLE_MANAGING_EMPLOYEE` carries no ownership requirement."

    Design: Corner/validations/corner_rmo_designation_below_ten_percent_ownership_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="Sliver Stake Electric LLC",
        contact_email="sliver@x.test",
        full_name="Sam Sliver",
        verified_experience_months=60,
        education_credential="NONE",
        declared_net_worth_cents=400000,
    )
    owner = X.register_qualifying_individual(
        api, full_name="Owen Owner", verified_experience_months=84
    )
    before = X.read_license(api, ctx.license_id)

    response = X.designate_qualifier(
        api,
        ctx.license_id,
        owner["id"],
        before["version"],
        relationship_type="RESPONSIBLE_MANAGING_OFFICER",
        effective_from="2026-08-15",
        ownership_pct=5,
    )

    validate_error(response, "ERR_OWNERSHIP_PCT_INSUFFICIENT")
    assert_fields(
        validate_success(
            api.get_qualifying_individual(owner["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"active_qualification_count": 0},
    )
    accepted = validate_success(
        X.designate_qualifier(
            api,
            ctx.license_id,
            owner["id"],
            before["version"],
            relationship_type="RESPONSIBLE_MANAGING_EMPLOYEE",
            effective_from="2026-08-15",
            ownership_pct=5,
        ),
        201,
    )
    assert_fields(accepted, {"status": "ACTIVE"})


def test_continuing_education_credit_of_zero_hours_is_refused(api):
    """A credit carrying no hours at all is refused.

    PRD: "A non-positive credit or one that would push the running total past
    forty hours is refused with `ERR_CE_HOURS_CEILING_EXCEEDED`."

    Design: Corner/validations/corner_ce_credit_of_zero_hours_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="Zero Hour Electric LLC",
        contact_email="zerohour@x.test",
        full_name="Zeke Zero",
        verified_experience_months=60,
        education_credential="NONE",
        declared_net_worth_cents=400000,
    )

    response = api.bank_ce_credits(
        ctx.license_id,
        F.ce_credit_payload(0, "2026-09-01", "Empty Seminar Co"),
        ctx.licensee_headers,
    )

    validate_error(response, "ERR_CE_HOURS_CEILING_EXCEEDED")
    assert_fields(X.read_license(api, ctx.license_id), {"ce_hours_completed": 0})


def test_renewal_of_a_license_with_no_qualifier_of_record_is_refused(api):
    """A licence left without a qualifier cannot renew, however else it complies.

    PRD: "Second, present compliance: the licence's `compliance_posture` must not
    be `NON_COMPLIANT`, and a non-compliant licence draws
    `ERR_LICENSE_NOT_COMPLIANT` — a `CONDITIONAL` posture, by contrast, renews
    perfectly well."

    Design: Corner/validations/corner_renewing_a_license_with_no_qualifier_of_record_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="No Qualifier Electric LLC",
        contact_email="noqual@x.test",
        full_name="Quinn Quitter",
        verified_experience_months=60,
        education_credential="NONE",
        declared_net_worth_cents=400000,
    )
    X.verify_bond(
        api,
        ctx.license_id,
        amount_cents=1500000,
        effective_date="2026-08-01",
        expiration_date="2028-09-01",
        carrier_name="Full Term Surety",
        policy_number="BND-FULL",
    )
    X.bank_ce_hours(api, ctx, 8, "2028-06-01")
    validate_success(
        api.withdraw_qualifier_assignment(
            ctx.assignment["id"],
            {"withdrawn_on": "2028-07-01"},
            LICENSING_ANALYST_HEADERS,
        )
    )

    response = api.renew_license(ctx.license_id, ctx.licensee_headers)

    validate_error(response, "ERR_LICENSE_NOT_COMPLIANT")
    assert_fields(
        X.read_license(api, ctx.license_id),
        {
            "compliance_posture": "NON_COMPLIANT",
            "qualifying_individual_id": None,
            "expires_on": "2028-08-01",
            "renewal_count": 0,
        },
    )
