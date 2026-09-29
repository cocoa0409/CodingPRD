"""Requests that break two ladder rules at once, plus the isolating probes for each.

Every test here fires one call that violates a pair of rules and asserts the earlier
rule's identifier and status code, then fires the two single-violation probes that
prove the later rule was implemented all along and merely outranked.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPLICATION_STATE_INVALID,
    ERR_ASSESSMENT_STATE_INVALID,
    ERR_CERTIFICATE_APPLICATION_MISMATCH,
    ERR_CLOSING_DATE_IN_PAST,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import NON_EXISTENT_UUID
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    FUNDING_OFFICER_RELEASER,
    FUNDING_OFFICER_VERIFIER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)


def _pending_and_funded_applications(client):
    """First parcel stops at a verified certificate; second parcel is fully funded."""
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    fixtures.add_solar_measure(client, world)
    fixtures.submitted_application(client, world)
    fixtures.underwritten_application(client, world)
    fixtures.consented_application(client, world)
    fixtures.approved_application(client, world)
    fixtures.issued_agreement(client, world)
    fixtures.signed_agreement(client, world)
    fixtures.move_clock(client, fixtures.RELEASE_CLOCK)
    fixtures.filed_certificate(
        client, world, measure_ids=[world["solar_measure_id"]], certified_cost_cents=3000000
    )
    fixtures.countersigned_certificate(client, world)
    fixtures.verified_certificate(client, world)

    fixtures.second_parcel(client, world)
    owner2 = world["second_owner_headers"]
    app2 = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["second_property_id"], world["contractor_id"], 20
            ),
            owner2,
        )
    )
    version = A.expect_ok(client.get_application(app2["id"], owner2))["version"]
    measure2 = A.expect_created(
        client.add_measure(
            app2["id"],
            factories.measure_payload(world["solar_product_id"], version, 1000000, 100000),
            owner2,
        )
    )
    A.expect_ok(client.submit_application(app2["id"], owner2))
    A.expect_ok(
        client.underwrite_application(
            app2["id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.expect_ok(
        client.record_consent_response(
            world["second_lien_id"],
            factories.consent_response_payload(),
            COMPLIANCE_OFFICER,
        )
    )
    A.expect_ok(client.approve_application(app2["id"], COMPLIANCE_OFFICER))
    approved_version = A.expect_ok(client.get_application(app2["id"], owner2))["version"]
    agreement2 = A.expect_created(
        client.issue_agreement(
            factories.agreement_payload(app2["id"], approved_version, 20, 800),
            UNDERWRITING_ANALYST,
        )
    )
    A.expect_ok(
        client.sign_agreement(
            agreement2["id"],
            factories.sign_agreement_payload(world["second_owner_full_name"]),
            owner2,
        )
    )
    certificate2 = A.expect_created(
        client.file_certificate(
            factories.certificate_payload(app2["id"], [measure2["id"]], 1000000),
            world["contractor_caller"],
        )
    )
    A.expect_ok(
        client.sign_certificate(
            certificate2["id"],
            factories.sign_certificate_payload(world["second_owner_full_name"]),
            owner2,
        )
    )
    A.expect_ok(
        client.verify_certificate(
            certificate2["id"],
            factories.verify_certificate_payload("APPROVE"),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    draw2 = A.expect_created(
        client.request_disbursement(
            factories.disbursement_payload(
                app2["id"], certificate2["id"], world["contractor_id"], 1000000
            ),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    # The second agreement was signed on 2026-08-18; its window closes on 2026-08-22.
    fixtures.move_clock(client, "2026-08-22T00:00:00Z")
    A.expect_ok(client.release_disbursement(draw2["id"], FUNDING_OFFICER_RELEASER))

    world["funded_application_id"] = app2["id"]
    world["funded_certificate_id"] = certificate2["id"]
    world["funded_disbursement_id"] = draw2["id"]
    return world


def test_cross_parent_wiring_outranks_the_application_state_check_on_a_draw(client):
    """A certificate from the wrong application reports the 422, not the state 409.

    Every identifier in `measure_ids` must name a project measure of the same
    application; a disbursement's `completion_certificate_id` must belong to the
    application named in the same body; the installment named in the path must belong to
    the assessment named in the path; and a mortgage lien receiving a consent response
    must have a `consent_application_id` already set.

    Design: Difficulty/priority_pair_validation_conflict/disbursement_referential_mismatch_beats_application_state
    """
    world = _pending_and_funded_applications(client)

    # Both rules broken: the certificate hangs from the other application, and the
    # named application is already FUNDED.
    both = client.request_disbursement(
        factories.disbursement_payload(
            world["funded_application_id"],
            world["certificate_id"],
            world["contractor_id"],
            1000000,
        ),
        FUNDING_OFFICER_VERIFIER,
    )
    A.expect_error(both, ERR_CERTIFICATE_APPLICATION_MISMATCH)
    assert both.status_code == 422

    # Isolating probe for the later rule: correct wiring, wrong application state.
    state_only = client.request_disbursement(
        factories.disbursement_payload(
            world["funded_application_id"],
            world["funded_certificate_id"],
            world["contractor_id"],
            1000000,
        ),
        FUNDING_OFFICER_VERIFIER,
    )
    A.expect_error(state_only, ERR_APPLICATION_STATE_INVALID)
    assert state_only.status_code == 409


def test_the_wiring_rule_also_fires_on_a_perfectly_staged_application(client):
    """The referential check rejects a foreign certificate even on a FUNDING_PENDING deal.

    These are deliberately distinguished from a plain 404: the row exists, but it hangs
    from a different parent.

    Design: Difficulty/priority_pair_validation_conflict/disbursement_referential_mismatch_beats_application_state
    """
    world = _pending_and_funded_applications(client)

    reference_only = client.request_disbursement(
        factories.disbursement_payload(
            world["application_id"],
            world["funded_certificate_id"],
            world["contractor_id"],
            1000000,
        ),
        FUNDING_OFFICER_VERIFIER,
    )
    A.expect_error(reference_only, ERR_CERTIFICATE_APPLICATION_MISMATCH)
    assert reference_only.status_code == 422

    # No side effect belonging to a later stage was applied by any rejected probe.
    _, meta = A.expect_page(
        client.list_disbursements(PROGRAM_ADMIN, {"application_id": world["application_id"]})
    )
    A.assert_total_count(meta, 0)
    _, funded_meta = A.expect_page(
        client.list_disbursements(
            PROGRAM_ADMIN, {"application_id": world["funded_application_id"]}
        )
    )
    A.assert_total_count(funded_meta, 1)
    A.assert_fields(
        A.expect_ok(
            client.get_application(world["funded_application_id"], PROGRAM_ADMIN)
        ),
        status="FUNDED",
    )
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 1000000, 0)


def _referred_then_curable_assessment(client):
    """A referred assessment whose two delinquent years can be paid off in place."""
    world = fixtures.assessed_project(client, first_tax_year=2027)
    fixtures.move_clock(client, "2027-10-01T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-10-01"), COUNTY_OFFICER
        )
    )
    fixtures.move_clock(client, "2028-12-15T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2028, "2028-12-15"), COUNTY_OFFICER
        )
    )
    world["installments"] = fixtures.schedule_of(client, world)
    return world


def test_assessment_state_outranks_the_back_dated_closing_date(client):
    """A referred lien answers the quote before the past closing date is even reached.

    The two assessment status axes are checked independently, otherwise
    `ERR_ASSESSMENT_STATE_INVALID` (409). A payoff quote and a prepayment both require
    `billing_status` of `ON_ROLL` **and** `lien_status` of `SENIOR_RECORDED`.

    Design: Difficulty/priority_pair_validation_conflict/transfer_assessment_state_beats_past_closing_date
    """
    world = _referred_then_curable_assessment(client)
    A.assert_fields(
        fixtures.read_assessment(client, world), lien_status="LIEN_SALE_REFERRED"
    )

    # Both broken: the lien axis is referred and the closing date is two weeks past.
    both = client.quote_transfer(
        factories.transfer_quote_payload(
            world["assessment_id"], "2028-12-01", "PAYOFF_AT_CLOSING"
        ),
        COUNTY_OFFICER,
    )
    A.expect_error(both, ERR_ASSESSMENT_STATE_INVALID)
    assert both.status_code == 409

    # Isolating probe for the state rule alone: a perfectly future closing date.
    state_only = client.quote_transfer(
        factories.transfer_quote_payload(
            world["assessment_id"], "2029-01-15", "PAYOFF_AT_CLOSING"
        ),
        COUNTY_OFFICER,
    )
    A.expect_error(state_only, ERR_ASSESSMENT_STATE_INVALID)
    assert state_only.status_code == 409

    _, meta = A.expect_page(
        client.list_assessment_transfers(world["assessment_id"], COUNTY_OFFICER)
    )
    A.assert_total_count(meta, 0)
    A.assert_fields(fixtures.read_assessment(client, world), transfer_status="NONE")


def test_the_closing_date_rule_surfaces_once_the_lien_axis_recovers(client):
    """Curing both delinquencies exposes the temporal rule the state rule had masked.

    A payoff quote's `closing_date` must be on or after the current logical date,
    otherwise `ERR_CLOSING_DATE_IN_PAST` (422). Applies to payoff-quote creation.
    Interest accrues to the closing date, so a back-dated closing would understate the
    payoff.

    Design: Difficulty/priority_pair_validation_conflict/transfer_assessment_state_beats_past_closing_date
    """
    world = _referred_then_curable_assessment(client)
    rows = world["installments"]
    A.expect_ok(
        client.pay_installment(
            world["assessment_id"],
            A.find_installment(rows, 2027)["id"],
            factories.installment_payment_payload(549867),
            COUNTY_OFFICER,
        )
    )
    A.expect_ok(
        client.pay_installment(
            world["assessment_id"],
            A.find_installment(rows, 2028)["id"],
            factories.installment_payment_payload(487785),
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        fixtures.read_assessment(client, world),
        lien_status="SENIOR_RECORDED",
        delinquent_installment_count=0,
        accrued_penalty_cents=0,
        principal_balance_cents=4118396,
    )

    temporal_only = client.quote_transfer(
        factories.transfer_quote_payload(
            world["assessment_id"], "2028-12-01", "PAYOFF_AT_CLOSING"
        ),
        COUNTY_OFFICER,
    )
    A.expect_error(temporal_only, ERR_CLOSING_DATE_IN_PAST)
    assert temporal_only.status_code == 422

    _, meta = A.expect_page(
        client.list_assessment_transfers(world["assessment_id"], COUNTY_OFFICER)
    )
    A.assert_total_count(meta, 0)
    A.assert_fields(fixtures.read_assessment(client, world), transfer_status="NONE")


def test_role_authorization_outranks_path_existence_on_reinstatement(client):
    """A compliance officer aiming at a missing contractor gets 403, never 404.

    The declared `X-User-Role` must be among the endpoint's authorized roles, otherwise
    `ERR_UNAUTHORIZED` (403). Because this precedes schema validation, a wrong role sent
    with a malformed body still reports `ERR_UNAUTHORIZED`.

    Design: Difficulty/priority_pair_validation_conflict/reinstate_unauthorized_role_beats_missing_contractor
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)

    # Both broken: reinstatement is the ProgramAdmin's alone and the row is absent.
    both = client.reinstate_contractor(
        NON_EXISTENT_UUID, COMPLIANCE_OFFICER, factories.reinstate_payload("please lift")
    )
    A.expect_error(both, ERR_UNAUTHORIZED)
    assert both.status_code == 403

    # Isolating probe for the later rule: the authorized role, still no such row.
    existence_only = client.reinstate_contractor(
        NON_EXISTENT_UUID, PROGRAM_ADMIN, factories.reinstate_payload("please lift")
    )
    A.expect_error(existence_only, ERR_CONTRACTOR_NOT_FOUND)
    assert existence_only.status_code == 404


def test_role_authorization_also_outranks_the_contractor_state_check(client):
    """An enrolled contractor never reports its own state to an unauthorized caller.

    A request that violates more than one rule must fail on the *earliest* rule it
    violates, and no side effect belonging to a later stage may be applied.

    Design: Difficulty/priority_pair_validation_conflict/reinstate_unauthorized_role_beats_missing_contractor
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    world = fixtures.seed_enrolled_contractor(client)
    A.assert_fields(
        A.expect_ok(client.get_contractor(world["contractor_id"], PROGRAM_ADMIN)),
        enrollment_status="ENROLLED",
        suspension_reason=None,
    )

    # The row exists and is ENROLLED, which reinstatement forbids; the role check wins.
    auth_only = client.reinstate_contractor(
        world["contractor_id"], COMPLIANCE_OFFICER, factories.reinstate_payload("please lift")
    )
    A.expect_error(auth_only, ERR_UNAUTHORIZED)
    assert auth_only.status_code == 403

    A.assert_fields(
        A.expect_ok(client.get_contractor(world["contractor_id"], PROGRAM_ADMIN)),
        enrollment_status="ENROLLED",
        suspension_reason=None,
    )
