"""Refusals chosen so that the plausible wrong answer is a different error id or status.

Every case here has a near neighbour — 401 against 403, 422 against 404, a mismatch against
a state error — and each test pins which one the program owes.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_INSTALLMENT_STATE_INVALID,
    ERR_INVALID_SUPERSEDE_TARGET,
    ERR_LIEN_NOT_NOTIFIED,
    ERR_MISSING_AUTH_HEADER,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_QUOTE_EXPIRED,
)
from test_helpers.constants import ROLE_PROPERTY_OWNER
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
    headers_empty_role,
    headers_missing_role,
    headers_missing_user_id,
)

BILLING_CLOCK = "2027-12-01T00:00:00Z"
QUOTING_CLOCK = "2027-12-05T00:00:00Z"
LAPSE_CLOCK = "2028-01-04T00:00:00Z"


def test_an_absent_or_empty_role_is_401_and_never_403(client):
    """No role means nothing to authorize, and an empty role counts as absent.

    `X-User-Role` must be present and non-empty, and `X-User-ID` must be present on every
    endpoint whose authorized roles include an identity-bearing role. Otherwise
    `ERR_MISSING_AUTH_HEADER` (401).

    Design: Corner/errors/request_missing_auth_headers_rejected_with_401
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(client)
    parcel = fixtures.seed_parcel(client, with_senior_lien=False)

    A.expect_error(
        client.list_products(headers_missing_role("u_admin")), ERR_MISSING_AUTH_HEADER
    )
    A.expect_error(
        client.list_products(headers_empty_role("u_admin")), ERR_MISSING_AUTH_HEADER
    )
    denied = A.expect_error(
        client.open_application(
            factories.application_payload(
                parcel["property_id"], contractor["contractor_id"], 20
            ),
            headers_missing_user_id(ROLE_PROPERTY_OWNER),
        ),
        ERR_MISSING_AUTH_HEADER,
    )
    assert denied.get("message"), "a 401 still owes the caller a message"

    _rows, meta = A.expect_page(
        client.list_applications(
            PROGRAM_ADMIN, params={"property_id": parcel["property_id"]}
        )
    )
    A.assert_total_count(meta, 0)


def test_a_declined_application_on_the_wrong_parcel_is_not_a_supersede_target(client):
    """Existence is not enough: the target must sit on the parcel doing the superseding.

    `supersedes_application_id`, when supplied, must point at an application on the same
    parcel whose status is `DECLINED` or `WITHDRAWN`, otherwise `ERR_INVALID_SUPERSEDE_TARGET`
    (422).

    Design: Corner/errors/supersede_target_on_another_parcel_is_invalid_even_when_declined
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(client)
    home = fixtures.seed_parcel(client, with_senior_lien=False)
    neighbour = fixtures.seed_parcel(
        client, payload=factories.second_property_payload(), with_senior_lien=False
    )

    dead = {}
    for label, parcel in (("home", home), ("neighbour", neighbour)):
        application = A.expect_created(
            client.open_application(
                factories.application_payload(
                    parcel["property_id"], contractor["contractor_id"], 20
                ),
                parcel["owner_headers"],
            )
        )
        A.expect_created(
            client.add_measure(
                application["id"],
                factories.solar_measure_payload(
                    catalog["solar_product_id"], application["version"]
                ),
                parcel["owner_headers"],
            )
        )
        A.expect_ok(
            client.submit_application(application["id"], parcel["owner_headers"])
        )
        A.expect_ok(
            client.underwrite_application(
                application["id"],
                factories.underwrite_decline_payload("SIR_FLOOR"),
                UNDERWRITING_ANALYST,
            )
        )
        dead[label] = application["id"]

    A.expect_error(
        client.open_application(
            factories.application_payload(
                home["property_id"],
                contractor["contractor_id"],
                20,
                supersedes_application_id=dead["neighbour"],
            ),
            home["owner_headers"],
        ),
        ERR_INVALID_SUPERSEDE_TARGET,
    )

    replacement = A.expect_created(
        client.open_application(
            factories.application_payload(
                home["property_id"],
                contractor["contractor_id"],
                20,
                supersedes_application_id=dead["home"],
            ),
            home["owner_headers"],
        )
    )
    A.assert_fields(
        replacement, status="DRAFT", supersedes_application_id=dead["home"]
    )

    _own, own_meta = A.expect_page(
        client.list_applications(
            PROGRAM_ADMIN, params={"property_id": home["property_id"]}
        )
    )
    A.assert_total_count(own_meta, 2)
    _superseding, superseding_meta = A.expect_page(
        client.list_applications(
            PROGRAM_ADMIN, params={"supersedes_application_id": dead["home"]}
        )
    )
    A.assert_total_count(superseding_meta, 1)
    _none, none_meta = A.expect_page(
        client.list_applications(
            PROGRAM_ADMIN, params={"supersedes_application_id": dead["neighbour"]}
        )
    )
    A.assert_total_count(none_meta, 0)


def test_a_holder_who_was_never_notified_cannot_answer(client):
    """Consent is an answer to a notice, so an un-notified lien has nothing to answer.

    The lien must actually have been notified: a response posted against a lien whose
    `consent_application_id` is still null is rejected with `ERR_LIEN_NOT_NOTIFIED`, and the
    referenced application must be in `CONSENT_PENDING`.

    Design: Corner/errors/consent_response_on_a_never_notified_lien_returns_422
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    A.assert_fields(world["lien"], consent_response="NOT_NOTIFIED")

    A.expect_error(
        client.record_consent_response(
            world["lien_id"],
            factories.consent_response_payload("CONSENT", note="holder called in"),
            COMPLIANCE_OFFICER,
        ),
        ERR_LIEN_NOT_NOTIFIED,
    )

    untouched = A.expect_ok(
        client.get_mortgage_lien(world["lien_id"], COMPLIANCE_OFFICER)
    )
    A.assert_fields(untouched, consent_response="NOT_NOTIFIED", status="ACTIVE")
    A.assert_absent_or_none(
        untouched,
        "consent_application_id",
        "notified_at",
        "consent_deadline_at",
        "consent_responded_at",
    )
    A.assert_fields(
        fixtures.read_application(client, world),
        status="DRAFT",
        consent_posture="NOT_STARTED",
        notified_lien_count=0,
    )
    _rows, meta = A.expect_page(
        client.list_mortgage_liens(
            PROGRAM_ADMIN,
            params={"consent_application_id": world["application_id"]},
        )
    )
    A.assert_total_count(meta, 0)


def test_a_cent_short_and_a_cent_over_are_both_refused_and_the_exact_figure_pays(client):
    """318163 or nothing, and only the 67403 of principal comes off the balance.

    The amount must be exact: `total_due_cents` for a `BILLED` installment, or
    `total_due_cents` plus `penalty_cents` for a `DELINQUENT` one.

    Design: Corner/errors/installment_payment_amount_must_match_total_due_exactly
    """
    world = fixtures.assessed_project(client, fixtures.solar_only_project(client), 2027)
    fixtures.move_clock(client, BILLING_CLOCK)
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-12-01"), COUNTY_OFFICER
        )
    )
    first = A.find_installment(fixtures.schedule_of(client, world), 2027)
    A.assert_installment_row(first, 1, 2027, 67403, 246760)
    A.assert_fields(first, total_due_cents=318163, status="BILLED")

    for wrong_amount in (300000, 318164):
        A.expect_error(
            client.pay_installment(
                world["assessment_id"],
                first["id"],
                factories.installment_payment_payload(
                    wrong_amount, paid_on="2027-12-08"
                ),
                COUNTY_OFFICER,
            ),
            ERR_PAYMENT_AMOUNT_MISMATCH,
        )

    still_open = A.expect_ok(
        client.get_installment(world["assessment_id"], first["id"], COUNTY_OFFICER)
    )
    # "Each installment opens with billed_on and paid_on null, paid_amount_cents,
    # penalty_cents and months_past_due at 0", and a refused payment records nothing.
    A.assert_fields(still_open, status="BILLED", paid_amount_cents=0)
    A.assert_absent_or_none(still_open, "paid_on")
    A.assert_fields(
        fixtures.read_assessment(client, world), principal_balance_cents=3084500
    )

    A.expect_ok(
        client.pay_installment(
            world["assessment_id"],
            first["id"],
            factories.installment_payment_payload(318163, paid_on="2027-12-08"),
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        A.expect_ok(
            client.get_installment(world["assessment_id"], first["id"], COUNTY_OFFICER)
        ),
        status="PAID",
        paid_amount_cents=318163,
        paid_on="2027-12-08",
    )
    A.assert_fields(
        fixtures.read_assessment(client, world), principal_balance_cents=3017097
    )
    A.assert_parcel_exposure(
        fixtures.read_property(client, world), 3017097, 3017097
    )

    A.expect_error(
        client.pay_installment(
            world["assessment_id"],
            first["id"],
            factories.installment_payment_payload(318163, paid_on="2027-12-09"),
            COUNTY_OFFICER,
        ),
        ERR_INSTALLMENT_STATE_INVALID,
    )


def test_a_quote_recorded_on_its_last_day_expires_first_and_is_refused_second(client):
    """The comparison is strict, and the lapse is written down before the refusal is returned.

    Recording a closing requires the current logical date to be strictly before the transfer's
    `good_through_date`, otherwise `ERR_QUOTE_EXPIRED` (409).

    Design: Corner/errors/expired_payoff_quote_is_moved_to_expired_before_the_record_is_refused
    """
    world = fixtures.assessed_project(client, fixtures.solar_only_project(client), 2027)
    A.assert_fields(
        world["assessment"],
        original_principal_cents=3084500,
        principal_balance_cents=3084500,
        interest_accrual_from="2026-08-20",
        apr_bps=800,
    )
    fixtures.move_clock(client, BILLING_CLOCK)
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-12-01"), COUNTY_OFFICER
        )
    )

    fixtures.move_clock(client, QUOTING_CLOCK)
    quote = A.expect_created(
        client.quote_transfer(
            factories.transfer_quote_payload(
                world["assessment_id"], "2027-12-20", mode="PAYOFF_AT_CLOSING"
            ),
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        quote,
        status="QUOTED",
        good_through_date="2028-01-04",
        payoff_principal_cents=3084500,
        accrued_interest_cents=329239,
        payoff_admin_fee_cents=7500,
        base_payoff_cents=3421239,
        prepayment_premium_bps=200,
        prepayment_premium_cents=68425,
        payoff_total_cents=3489664,
    )

    fixtures.move_clock(client, LAPSE_CLOCK)
    A.expect_error(
        client.record_transfer(
            quote["id"], COUNTY_OFFICER, {"recorded_on": "2028-01-04"}
        ),
        ERR_QUOTE_EXPIRED,
    )

    lapsed = A.expect_ok(client.get_transfer(quote["id"], COUNTY_OFFICER))
    A.assert_fields(lapsed, status="EXPIRED")
    A.assert_absent_or_none(lapsed, "recorded_on")
    A.assert_fields(
        fixtures.read_assessment(client, world),
        transfer_status="NONE",
        billing_status="ON_ROLL",
        lien_status="SENIOR_RECORDED",
        principal_balance_cents=3084500,
    )
    A.assert_fields(fixtures.read_property(client, world), owner_full_name="Ada Ruiz")
    _cancelled, cancelled_meta = A.expect_page(
        client.list_installments(
            world["assessment_id"], COUNTY_OFFICER, {"status": "CANCELLED"}
        )
    )
    A.assert_total_count(cancelled_meta, 0)
