"""Operations whose legality is decided by the state of a *different* entity.

Each test establishes a locally valid target — a requested draw, a proposed measure, a
countersigned certificate — and shows the call refused purely because of a neighbouring
agreement, catalog row or application, then lifts that neighbour's state and repeats.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_AGREEMENT_STATE_INVALID,
    ERR_APPLICATION_STATE_INVALID,
    ERR_FUNDS_ALREADY_RELEASED,
    ERR_RESCISSION_PERIOD_ACTIVE,
    ERR_WORKMANSHIP_GATE_NOT_MET,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    FUNDING_OFFICER_RELEASER,
    FUNDING_OFFICER_VERIFIER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)


def _draw_awaiting_the_window(client):
    """A verified certificate and a requested draw, with the clock still inside the window."""
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    fixtures.add_solar_measure(client, world)
    fixtures.submitted_application(client, world)
    fixtures.underwritten_application(client, world)
    fixtures.consented_application(client, world)
    fixtures.approved_application(client, world)
    fixtures.issued_agreement(client, world)
    fixtures.signed_agreement(client, world)
    fixtures.move_clock(client, "2026-08-17T12:00:00Z")
    fixtures.filed_certificate(
        client, world, measure_ids=[world["solar_measure_id"]], certified_cost_cents=3000000
    )
    fixtures.countersigned_certificate(client, world)
    fixtures.verified_certificate(client, world)
    fixtures.requested_disbursement(client, world, amount_cents=3000000)
    return world


def test_release_is_blocked_while_the_agreements_rescission_window_is_open(client):
    """A locally perfect draw is refused because the agreement is still rescindable.

    Money may not move before the logical clock reaches or passes
    `rescission_expires_at`, otherwise `ERR_RESCISSION_PERIOD_ACTIVE` (422). Applies to
    release. This consumer-protection check outranks every fiscal check on the same call.

    Design: Difficulty/cross_entity_state_dependency/release_blocked_until_agreement_rescission_window_closes
    """
    world = _draw_awaiting_the_window(client)
    A.assert_fields(
        fixtures.read_agreement(client, world),
        status="SIGNED",
        rescission_expires_at="2026-08-18T00:00:00Z",
        financed_amount_cents=3084500,
        contractor_payable_cents=3000000,
        oral_confirmation_required=False,
    )
    A.assert_fields(fixtures.read_certificate(client, world), status="VERIFIED")
    A.assert_fields(fixtures.read_disbursement(client, world), status="REQUESTED")

    A.expect_error(
        client.release_disbursement(world["disbursement_id"], FUNDING_OFFICER_RELEASER),
        ERR_RESCISSION_PERIOD_ACTIVE,
    )
    A.assert_fields(
        fixtures.read_disbursement(client, world), status="REQUESTED", released_at=None
    )
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 0, 0)
    A.assert_fields(fixtures.read_application(client, world), status="FUNDING_PENDING")


def test_the_expiry_instant_itself_permits_release_and_closes_the_rescission_path(client):
    """The comparison is inclusive, and the first release spends the right of rescission.

    Rescinding takes an optional `reason`, requires the agreement to be `SIGNED`, and
    additionally requires that no disbursement of the application has yet reached
    `RELEASED` — if cash has already left, the attempt fails with
    `ERR_FUNDS_ALREADY_RELEASED` (409).

    Design: Difficulty/cross_entity_state_dependency/release_blocked_until_agreement_rescission_window_closes
    """
    world = _draw_awaiting_the_window(client)
    A.expect_error(
        client.release_disbursement(world["disbursement_id"], FUNDING_OFFICER_RELEASER),
        ERR_RESCISSION_PERIOD_ACTIVE,
    )

    fixtures.move_clock(client, "2026-08-18T00:00:00Z")
    released = A.expect_ok(
        client.release_disbursement(world["disbursement_id"], FUNDING_OFFICER_RELEASER)
    )
    A.assert_fields(
        released, status="RELEASED", released_at="2026-08-18T00:00:00Z"
    )
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 3000000, 0)
    A.assert_fields(fixtures.read_application(client, world), status="FUNDED")

    # The rescission path is closed, but the PRD admits two identifiers for closing it:
    # stage 27 names ERR_FUNDS_ALREADY_RELEASED, while the release has also carried the
    # agreement from SIGNED to EFFECTIVE and the earlier stage 14 agreement-state check
    # is what "an attempt to rescind once the window has closed ... is reported as
    # ERR_AGREEMENT_STATE_INVALID (409)" describes.
    A.expect_one_of(
        client.rescind_agreement(
            world["agreement_id"], factories.rescind_payload(), world["owner_headers"]
        ),
        [ERR_FUNDS_ALREADY_RELEASED, ERR_AGREEMENT_STATE_INVALID],
    )


def _submitted_then_retired_catalog(client):
    """The canonical two-measure set, with the heat-pump product retired after submit."""
    world = fixtures.submitted_application(client)
    A.assert_fields(
        world["application"],
        requested_principal_cents=4200000,
        portfolio_sir_bps=12396,
        min_measure_sir_bps=11461,
        weighted_useful_life_years=23,
        screening_cltv_bps=7300,
    )
    A.expect_ok(
        client.patch_product(
            world["hvac_product_id"], {"status": "RETIRED"}, PROGRAM_ADMIN
        )
    )
    return world


def test_a_retired_catalog_row_forces_a_measure_ineligible_despite_a_passing_ratio(client):
    """The measure's own ratio clears the floor, so only the retirement explains it.

    **First**, every `PROPOSED` measure is classified individually: it becomes `APPROVED`
    when its `sir_bps` is at least 10000 basis points and its catalog product is still
    `ACTIVE` at this instant, and `INELIGIBLE` otherwise.

    Design: Difficulty/cross_entity_state_dependency/underwrite_marks_measure_ineligible_when_product_retired
    """
    world = _submitted_then_retired_catalog(client)

    underwritten = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    hvac_measure = fixtures.read_measure(client, world["hvac_measure_id"])
    A.assert_fields(hvac_measure, status="INELIGIBLE", sir_bps=11461)
    assert hvac_measure["sir_bps"] >= 10000
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]),
        status="APPROVED",
        sir_bps=12770,
    )
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        requested_principal_cents=3000000,
        portfolio_sir_bps=12770,
        underwriting_cltv_bps=7000,
    )


def test_the_retired_product_stays_readable_and_stays_attached_to_its_measure(client):
    """Retirement previews in the report and never detaches the existing measure.

    Retiring a product by patching its `status` to `RETIRED` does not disturb existing
    project measures — they keep pointing at it — but a `RETIRED` product may not back a
    new measure, and any measure still pointing at a retired product is forced to
    `INELIGIBLE` at the next underwrite.

    Design: Difficulty/cross_entity_state_dependency/underwrite_marks_measure_ineligible_when_product_retired
    """
    world = _submitted_then_retired_catalog(client)

    report = A.expect_ok(
        client.get_eligibility_report(world["application_id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(
        report,
        approved_principal_cents=3000000,
        proposed_principal_cents=4200000,
        portfolio_sir_bps=12770,
        cltv_bps_assessed=7000,
        ptv_bps=750,
        blocking_error_id=None,
    )
    assert "{0}:11461".format(world["hvac_measure_id"]) in report["measure_sir_report"]

    A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        A.expect_ok(client.get_product(world["hvac_product_id"], PROGRAM_ADMIN)),
        status="RETIRED",
    )
    A.assert_fields(
        fixtures.read_measure(client, world["hvac_measure_id"]),
        product_id=world["hvac_product_id"],
    )
    # Nothing is committed to the parcel until the agreement is signed.
    A.assert_fields(
        fixtures.read_property(client, world), committed_pace_principal_cents=0
    )


def _two_projects_frozen_by_one_defect(client):
    """One installer, two parcels: a defect on the first freezes funding on the second."""
    world = fixtures.solar_only_project(client)
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
    solar2 = A.expect_created(
        client.add_measure(
            app2["id"],
            factories.measure_payload(
                world["solar_product_id"],
                A.expect_ok(client.get_application(app2["id"], owner2))["version"],
                3000000,
                220000,
            ),
            owner2,
        )
    )
    hvac2 = A.expect_created(
        client.add_measure(
            app2["id"],
            factories.measure_payload(
                world["hvac_product_id"],
                A.expect_ok(client.get_application(app2["id"], owner2))["version"],
                1200000,
                100000,
            ),
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
    agreement2 = A.expect_created(
        client.issue_agreement(
            factories.agreement_payload(
                app2["id"],
                A.expect_ok(client.get_application(app2["id"], owner2))["version"],
                20,
                800,
            ),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        agreement2, financed_amount_cents=4314500, contractor_payable_cents=4200000
    )
    A.expect_ok(
        client.sign_agreement(
            agreement2["id"],
            factories.sign_agreement_payload(world["second_owner_full_name"]),
            owner2,
        )
    )

    # The solar half is certified, verified and drawn; the heat-pump half stops at
    # the homeowner countersignature and is the call the cascade will block.
    cc2a = A.expect_created(
        client.file_certificate(
            factories.certificate_payload(app2["id"], [solar2["id"]], 3000000),
            world["contractor_caller"],
        )
    )
    A.expect_ok(
        client.sign_certificate(
            cc2a["id"],
            factories.sign_certificate_payload(world["second_owner_full_name"]),
            owner2,
        )
    )
    A.expect_ok(
        client.verify_certificate(
            cc2a["id"], factories.verify_certificate_payload("APPROVE"), FUNDING_OFFICER_VERIFIER
        )
    )
    draw2 = A.expect_created(
        client.request_disbursement(
            factories.disbursement_payload(
                app2["id"], cc2a["id"], world["contractor_id"], 3000000
            ),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    cc2b = A.expect_created(
        client.file_certificate(
            factories.certificate_payload(app2["id"], [hvac2["id"]], 1200000),
            world["contractor_caller"],
        )
    )
    A.expect_ok(
        client.sign_certificate(
            cc2b["id"],
            factories.sign_certificate_payload(world["second_owner_full_name"]),
            owner2,
        )
    )

    fixtures.move_clock(client, "2026-08-20T00:00:00Z")
    fixtures.upheld_complaint(client, world, "2026-09-30", severity="SEVERE")

    world["second_application_id"] = app2["id"]
    world["second_draw_id"] = draw2["id"]
    world["blocked_certificate_id"] = cc2b["id"]
    world["second_owner_caller"] = owner2
    return world


def test_a_countersigned_certificate_cannot_be_verified_while_funding_is_held(client):
    """Both rows in the call are locally valid; only the sibling hold refuses it.

    This is also the moment the application must be healthy: a certificate belonging to
    an application sitting in `FUNDING_HELD` cannot be verified at all.

    Design: Difficulty/cross_entity_state_dependency/certificate_verify_blocked_while_application_funding_held
    """
    world = _two_projects_frozen_by_one_defect(client)

    A.assert_fields(
        fixtures.read_contractor(client, world),
        enrollment_status="PROBATION",
        workmanship_score=8000,
        lifetime_workmanship_score=8000,
    )
    A.assert_fields(
        A.expect_ok(client.get_disbursement(world["second_draw_id"], PROGRAM_ADMIN)),
        status="HELD",
        hold_reason="CONTRACTOR_PROBATION",
    )
    A.assert_fields(
        A.expect_ok(
            client.get_application(
                world["second_application_id"], world["second_owner_caller"]
            )
        ),
        status="FUNDING_HELD",
        funding_hold_reason="CONTRACTOR_PROBATION",
    )
    certificate = A.expect_ok(
        client.get_certificate(world["blocked_certificate_id"], PROGRAM_ADMIN)
    )
    A.assert_fields(certificate, status="HOMEOWNER_SIGNED")

    A.expect_error(
        client.verify_certificate(
            world["blocked_certificate_id"],
            factories.verify_certificate_payload("APPROVE"),
            FUNDING_OFFICER_VERIFIER,
        ),
        ERR_APPLICATION_STATE_INVALID,
    )

    after = A.expect_ok(
        client.get_certificate(world["blocked_certificate_id"], PROGRAM_ADMIN)
    )
    A.assert_fields(after, status="HOMEOWNER_SIGNED")
    A.assert_absent_or_none(after, "verified_by_user_id", "verified_at")
    # The hold cannot be lifted on demand: the trailing gate is still 1000 bps short.
    A.expect_error(
        client.reinstate_contractor(
            world["contractor_id"], PROGRAM_ADMIN, factories.reinstate_payload("remedy under way")
        ),
        ERR_WORKMANSHIP_GATE_NOT_MET,
    )


def test_reinstating_the_installer_unwinds_the_hold_and_frees_the_blocked_verify(client):
    """The blocked call becomes legal the instant the third entity recovers.

    On success `enrollment_status` returns to `ENROLLED`, `suspension_reason` is cleared
    to null, every disbursement of that contractor standing at `HELD` returns to
    `REQUESTED` with `hold_reason` cleared to null, and every application of that
    contractor standing at `FUNDING_HELD` returns to `FUNDING_PENDING` with
    `funding_hold_reason` cleared to null.

    Design: Difficulty/cross_entity_state_dependency/certificate_verify_blocked_while_application_funding_held
    """
    world = _two_projects_frozen_by_one_defect(client)

    fixtures.move_clock(client, "2026-08-25T00:00:00Z")
    remedied = A.expect_ok(
        client.adjudicate_complaint(
            world["complaint_id"],
            factories.adjudicate_payload("REMEDY_VERIFIED"),
            COMPLIANCE_OFFICER,
        )
    )
    A.assert_fields(remedied, status="CLOSED_REMEDIED")
    A.assert_fields(
        fixtures.read_contractor(client, world),
        enrollment_status="PROBATION",
        upheld_open_remedy_count=0,
        workmanship_score=8000,
    )

    # 742 days after the adjudication the deduction has left the trailing window.
    fixtures.move_clock(client, "2028-09-01T00:00:00Z")
    reinstated = A.expect_ok(
        client.reinstate_contractor(
            world["contractor_id"],
            PROGRAM_ADMIN,
            factories.reinstate_payload("trailing window cleared"),
        )
    )
    A.assert_fields(
        reinstated,
        enrollment_status="ENROLLED",
        workmanship_score=10000,
        lifetime_workmanship_score=8000,
    )
    A.assert_absent_or_none(reinstated, "suspension_reason")
    A.assert_fields(
        A.expect_ok(client.get_disbursement(world["second_draw_id"], PROGRAM_ADMIN)),
        status="REQUESTED",
    )
    A.assert_absent_or_none(
        A.expect_ok(client.get_disbursement(world["second_draw_id"], PROGRAM_ADMIN)),
        "hold_reason",
    )
    A.assert_fields(
        A.expect_ok(
            client.get_application(
                world["second_application_id"], world["second_owner_caller"]
            )
        ),
        status="FUNDING_PENDING",
    )

    verified = A.expect_ok(
        client.verify_certificate(
            world["blocked_certificate_id"],
            factories.verify_certificate_payload("APPROVE"),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    A.assert_fields(
        verified,
        status="VERIFIED",
        verified_by_user_id="u_fund_v",
        verified_at="2028-09-01T00:00:00Z",
    )
    # The unrelated first project never moved through any of this.
    A.assert_fields(fixtures.read_application(client, world), status="FUNDED")
    A.assert_fields(fixtures.read_disbursement(client, world), status="RELEASED")
    A.assert_contractor_ledger(
        fixtures.read_contractor(client, world), 3000000, 0
    )
