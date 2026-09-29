"""Read surface and request-plumbing corners.

Covers what a client sees when it asks the board a question and what it gets
back when the question is malformed: the licence snapshot the approval cascade
minted, paginated and filtered complaint listings, and the plumbing band that
rejects an unresolvable identifier, a missing required field or an empty
scheduling block before any business rule is ever consulted.
"""

from test_helpers import (
    HEARING_OFFICER_USER_ID,
    assert_coverage_record,
    assert_fields,
    assert_license,
    factories as F,
    fixtures as X,
    ids_of,
    make_consumer_headers,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_reading_a_licence_returns_the_minted_snapshot(api, licensing_analyst_headers):
    """The licence read back is exactly the row the approval cascade wrote.

    "**First**, a new licence row is created in `ACTIVE` status, with
    `licensee_id`, `classification_id` and `predecessor_license_id` copied from
    the application, `application_id` pointing back at the application that
    minted it, `issued_on` set to the clock date, `expires_on` set to
    `issued_on` advanced by twenty-four months — a two-year term — a freshly
    minted unique `license_number`, and `ce_hours_completed` at zero."

    "A brand-new licence is thus simultaneously `ACTIVE` and `NON_COMPLIANT`,
    and it will stay that way until a bond is verified against it."

    Design: Corner/entities/corner_get_license_by_id_returns_the_stored_snapshot
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = X.mint_active_license(
        api,
        legal_name="Read Electric LLC",
        contact_email="read@x.test",
        full_name="Reed Reader",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )

    snapshot = validate_success(
        api.get_license(ctx.license_id, licensing_analyst_headers)
    )
    assert_license(
        snapshot,
        status="ACTIVE",
        issued_on="2026-08-01",
        expires_on="2028-08-01",
        application_id=ctx.application_id,
        licensee_id=ctx.licensee_id,
        classification_id=ctx.classification_id,
        renewal_count=0,
        compliance_posture="NON_COMPLIANT",
    )


def test_complaint_listing_pages_within_one_consumer_only(api, licensing_analyst_headers):
    """Paging a consumer's complaints never spills a stranger's file into the page.

    "Unless a specific endpoint says otherwise, list results are ordered by
    `created_at` ascending — oldest first."

    "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/corner_list_complaints_paginates_and_filters_by_consumer
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    lister = X.register_consumer(
        api, full_name="Lee Lister", contact_email="lee@home.test", mailing_state="CA"
    )
    other = X.register_consumer(
        api, full_name="Otto Other", contact_email="otto@home.test", mailing_state="CA"
    )

    def file(consumer_id, business, loss_cents, contract_date, description):
        payload = {
            "consumer_id": consumer_id,
            "subject_business_name": business,
            "alleged_loss_cents": loss_cents,
            "contract_date": contract_date,
            "description": description,
        }
        return validate_success(
            api.create_complaint(payload, make_consumer_headers(consumer_id)),
            expected_status=201,
        )

    first = file(
        lister["id"],
        "Cash Only Contracting",
        300000,
        "2026-07-01",
        "Deposit taken for a re-roof, no work performed",
    )
    X.set_clock(api, "2026-08-02T00:00:00Z")
    file(
        lister["id"],
        "Cash Only Contracting",
        400000,
        "2026-07-02",
        "Second deposit taken for gutters",
    )
    X.set_clock(api, "2026-08-03T00:00:00Z")
    third = file(
        lister["id"], "Handy Andy", 500000, "2026-07-03", "Bathroom left unusable"
    )
    X.set_clock(api, "2026-08-04T00:00:00Z")
    stranger = file(
        other["id"], "Handy Andy", 600000, "2026-07-04", "Deck collapsed"
    )

    page1_response = api.list_complaints(
        licensing_analyst_headers,
        {"consumer_id": lister["id"], "limit": 2, "offset": 0},
    )
    page1, meta1 = validate_paginated(page1_response)
    assert page1_response.json()["response_type"] == "array", (
        "a list answers response_type array, got "
        f"{page1_response.json()['response_type']!r}"
    )
    assert len(page1) == 2, f"the first page holds two rows, got {len(page1)}"
    assert meta1["total_count"] == 3, (
        f"the filtered file count is three, got {meta1['total_count']}"
    )
    assert meta1["has_more"] is True, "a third row remains, so has_more is true"
    assert page1[0]["id"] == first["id"], "the oldest complaint leads the first page"

    page2, meta2 = validate_paginated(
        api.list_complaints(
            licensing_analyst_headers,
            {"consumer_id": lister["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1, f"the second page holds the remaining row, got {len(page2)}"
    assert meta2["total_count"] == 3, (
        f"the filtered file count is still three, got {meta2['total_count']}"
    )
    assert meta2["has_more"] is False, "nothing follows the second page"
    assert page2[0]["id"] == third["id"], "the third complaint lands on the second page"

    assert stranger["id"] not in ids_of(page1) + ids_of(page2), (
        "another consumer's complaint must never appear in this filtered listing"
    )


def test_reading_an_unissued_licence_identifier_is_not_found(
    api, licensing_analyst_headers
):
    """A well-formed identifier that names no licence answers the error envelope.

    "`ERR_TRADE_CLASSIFICATION_NOT_FOUND` covers an unresolvable
    `classification_id`; `ERR_RECOVERY_FUND_ACCOUNT_NOT_FOUND` an unresolvable
    `fund_account_id`; `ERR_LICENSEE_NOT_FOUND` an unresolvable `licensee_id`;
    `ERR_QUALIFYING_INDIVIDUAL_NOT_FOUND` an unresolvable
    `qualifying_individual_id`; `ERR_CONSUMER_NOT_FOUND` an unresolvable
    `consumer_id`; `ERR_LICENSE_APPLICATION_NOT_FOUND` a missing application;
    `ERR_LICENSE_NOT_FOUND` an unresolvable licence identifier in any position,
    including `license_id`, `subject_license_id` and `predecessor_license_id`;
    `ERR_COVERAGE_RECORD_NOT_FOUND` a missing coverage record;
    `ERR_QUALIFIER_ASSIGNMENT_NOT_FOUND` a missing designation;
    `ERR_COMPLAINT_NOT_FOUND` an unresolvable complaint identifier including
    `complaint_id`; `ERR_INVESTIGATION_NOT_FOUND` an unresolvable investigation
    identifier including `investigation_id`; `ERR_CITATION_NOT_FOUND` an
    unresolvable citation identifier including `citation_id`;
    `ERR_DISCIPLINARY_HEARING_NOT_FOUND` a missing hearing; and
    `ERR_RECOVERY_FUND_CLAIM_NOT_FOUND` a missing claim."

    "All fourteen carry HTTP 404."

    Design: Corner/entities/corner_get_unknown_license_id_returns_license_not_found
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")

    response = api.get_license(
        "00000000-0000-4000-8000-000000000000", licensing_analyst_headers
    )
    validate_error(response, "ERR_LICENSE_NOT_FOUND", expected_status=404)

    body = response.json()
    assert body["response_type"] == "error", (
        f"a failure answers response_type error, got {body['response_type']!r}"
    )
    assert body["data"]["message"], "the error envelope carries a human-readable message"


def test_a_complaint_without_a_narrative_is_rejected(api, licensing_analyst_headers):
    """Intake needs the allegation in words, so an omitted description writes nothing.

    "Schema validation, which fires before any of them, rejects a missing
    required field, a value of the wrong JSON type (including money sent as a
    string), an unrecognised enum member, an unparseable date or datetime, and
    each of the ordering and range rules named in §2.5 and §2.7."

    "Every one of those failures reports `ERR_INVALID_REQUEST` with HTTP 400."

    Design: Corner/entities/corner_complaint_creation_without_description_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    consumer = X.register_consumer(
        api, full_name="Mia Missing", contact_email="mia@home.test", mailing_state="CA"
    )

    payload = {
        "consumer_id": consumer["id"],
        "subject_business_name": "Vague Ventures",
        "alleged_loss_cents": 300000,
        "contract_date": "2026-07-01",
    }
    validate_error(
        api.create_complaint(payload, make_consumer_headers(consumer["id"])),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )

    _, meta = validate_paginated(
        api.list_complaints(licensing_analyst_headers, {"consumer_id": consumer["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a rejected intake must leave no complaint behind, got {meta['total_count']}"
    )


def test_a_filed_bond_waits_unverified_and_lifts_nothing(api, licensing_analyst_headers):
    """A bond only counts once the carrier confirms it, so the posture holds.

    "The record lands in `PENDING_VERIFICATION`, and — importantly — **filing an
    instrument does not improve a licence's compliance posture**."

    Design: Corner/entities/corner_coverage_record_defaults_to_pending_verification
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = X.mint_active_license(
        api,
        legal_name="Default Electric LLC",
        contact_email="def@x.test",
        full_name="Dee Fault",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )

    payload = {
        "license_id": ctx.license_id,
        "coverage_type": "BOND",
        "carrier_name": "Surety One",
        "policy_number": "BND-DEF",
        "amount_cents": 1500000,
        "effective_date": "2026-08-01",
        "expiration_date": "2027-08-01",
    }
    filed = validate_success(
        api.create_coverage_record(payload, ctx.licensee_headers), expected_status=201
    )
    assert filed["status"] == "PENDING_VERIFICATION", (
        f"a freshly filed instrument waits for the carrier, got {filed['status']!r}"
    )

    stored = validate_success(
        api.get_coverage_record(filed["id"], licensing_analyst_headers)
    )
    assert_coverage_record(stored, verified_on=None, cancellation_date=None)

    licence = X.read_license(api, ctx.license_id)
    assert_license(licence, compliance_posture="NON_COMPLIANT")


def test_an_application_naming_an_unissued_classification_is_not_found(
    api, licensing_analyst_headers
):
    """A body foreign key that resolves to nothing names its own not-found error.

    "The same precedence applies to foreign keys in a request body: the entity a
    missing identifier names determines which not-found error is returned."

    Design: Corner/entities/corner_application_with_unknown_classification_id_is_not_found
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    licensee = X.register_licensee(
        api, legal_name="Dangling Electric LLC", contact_email="dang@x.test"
    )
    individual = X.register_qualifying_individual(
        api, full_name="Dan Dangling", verified_experience_months=60
    )

    payload = {
        "licensee_id": licensee["id"],
        "classification_id": "33333333-3333-4333-8333-333333333333",
        "qualifying_individual_id": individual["id"],
        "application_type": "ORIGINAL",
        "declared_net_worth_cents": 400000,
    }
    validate_error(
        api.create_application(payload, make_licensee_headers(licensee["id"])),
        "ERR_TRADE_CLASSIFICATION_NOT_FOUND",
        expected_status=404,
    )

    _, meta = validate_paginated(
        api.list_applications(licensing_analyst_headers, {"licensee_id": licensee["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no application row may survive the rejection, got {meta['total_count']}"
    )


def test_a_hearing_block_that_ends_when_it_starts_is_rejected(
    api, board_admin_headers, licensing_analyst_headers
):
    """An empty calendar slot is a schema failure, so the appeal stays where it was.

    "The block must be non-empty: `scheduled_end_utc` strictly after
    `scheduled_start_utc`, or the request draws `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_hearing_end_not_after_start_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c20_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="Interval Air LLC",
        contact_email="int@x.test",
        full_name="Ivy Interval",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    consumer = X.register_consumer(
        api, full_name="Ivan Interval", contact_email="ivan@home.test", mailing_state="CA"
    )
    X.set_clock(api, "2026-09-01T00:00:00Z")
    _, _, citation = X.substantiated_citation(
        api,
        ctx,
        consumer["id"],
        severity="SERIOUS",
        violation_code="B-7109",
        correction_due_date="2026-10-15",
        alleged_loss_cents=500000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
    )
    X.appeal_citation(api, citation["id"], ctx.licensee_id)

    validate_error(
        api.create_hearing(
            F.hearing_payload(
                citation["id"],
                HEARING_OFFICER_USER_ID,
                "2026-09-10T14:00:00Z",
                "2026-09-10T14:00:00Z",
            ),
            board_admin_headers,
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )

    stored_citation = validate_success(
        api.get_citation(citation["id"], licensing_analyst_headers)
    )
    assert_fields(stored_citation, {"status": "APPEAL_REQUESTED"})

    _, meta = validate_paginated(
        api.list_hearings(licensing_analyst_headers, {"citation_id": citation["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused slot must calendar no hearing, got {meta['total_count']}"
    )
