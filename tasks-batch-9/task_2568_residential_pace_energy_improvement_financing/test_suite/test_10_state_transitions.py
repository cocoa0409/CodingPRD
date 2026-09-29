"""Declared transitions, their side effects, and the refusals from a wrong from-state.

Every test drives one edge of one status axis and then proves the refused replay wrote
nothing: no version bump, no counter movement and no neighbouring row touched.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPLICATION_STATE_INVALID,
    ERR_CONTRACTOR_STATE_INVALID,
    ERR_LICENSE_EXPIRED,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)


def test_enrollment_approval_advances_the_axis_once_and_refuses_the_replay(client):
    """The second approval finds ENROLLED, not PENDING_REVIEW, and writes nothing.

    Approving the applicant advances `enrollment_status` from `PENDING_REVIEW` to
    `ENROLLED` and clears `suspension_reason` to null.

    Design: Corner/state_machines/contractor_enroll_moves_pending_review_to_enrolled
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    contractor = A.expect_created(
        client.create_contractor(factories.contractor_payload(), PROGRAM_ADMIN)
    )
    A.assert_fields(contractor, enrollment_status="PENDING_REVIEW")

    enrolled = A.expect_ok(client.enroll_contractor(contractor["id"], PROGRAM_ADMIN))

    A.assert_fields(
        enrolled,
        enrollment_status="ENROLLED",
        workmanship_score=10000,
        lifetime_workmanship_score=10000,
    )
    A.assert_absent_or_none(enrolled, "suspension_reason")
    A.assert_version(enrolled, 2)

    A.expect_error(
        client.enroll_contractor(contractor["id"], PROGRAM_ADMIN),
        ERR_CONTRACTOR_STATE_INVALID,
    )
    replayed = A.expect_ok(client.get_contractor(contractor["id"], PROGRAM_ADMIN))
    A.assert_fields(replayed, enrollment_status="ENROLLED")
    A.assert_version(replayed, 2)


def test_an_expired_licence_bars_enrollment_and_leaves_the_applicant_pending(client):
    """Licence currency is checked against the logical date, not the calendar.

    Three conditions must hold at that moment: the `license_expires_on` date must be
    strictly after the current logical date, the offered `workmanship_warranty_years` must
    be at least 5, and `counties_served` must be non-empty.

    Design: Corner/state_machines/enroll_on_expired_license_rejected
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    contractor = A.expect_created(
        client.create_contractor(
            factories.contractor_payload(license_expires_on="2026-06-30"), PROGRAM_ADMIN
        )
    )

    A.expect_error(
        client.enroll_contractor(contractor["id"], PROGRAM_ADMIN), ERR_LICENSE_EXPIRED
    )

    unchanged = A.expect_ok(client.get_contractor(contractor["id"], PROGRAM_ADMIN))
    A.assert_fields(unchanged, enrollment_status="PENDING_REVIEW")
    A.assert_version(unchanged, 1)
    _rows, meta = A.expect_page(
        client.list_contractors(PROGRAM_ADMIN, {"enrollment_status": "ENROLLED"})
    )
    A.assert_total_count(meta, 0)


def test_a_declined_application_cannot_be_cured_back_into_underwriting(client):
    """DECLINED is terminal, and the refused cure spends none of the owner's rounds.

    A decision of `DECLINE` closes the application immediately. On this path every
    `PROPOSED` measure moves to `INELIGIBLE`, no mortgage holder is notified, and
    `consent_posture` remains `NOT_STARTED`.

    Design: Corner/state_machines/cure_on_declined_application_rejected
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    fixtures.add_solar_measure(client, world)
    fixtures.submitted_application(client, world)

    declined = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_decline_payload("SIR_FLOOR"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        declined,
        status="DECLINED",
        decline_reason_code="SIR_FLOOR",
        underwriter_user_id="u_ana_1",
        consent_posture="NOT_STARTED",
        notified_lien_count=0,
    )
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]), status="INELIGIBLE"
    )
    lien = A.expect_ok(client.get_mortgage_lien(world["lien_id"], COMPLIANCE_OFFICER))
    A.assert_fields(lien, consent_response="NOT_NOTIFIED")
    A.assert_absent_or_none(lien, "consent_application_id")

    A.expect_error(
        client.cure_application(
            world["application_id"],
            world["owner_headers"],
            factories.cure_payload("Owner wants another round"),
        ),
        ERR_APPLICATION_STATE_INVALID,
    )
    A.assert_fields(
        fixtures.read_application(client, world),
        status="DECLINED",
        cure_round_count=0,
    )


def test_a_second_submit_is_refused_and_the_stamped_figures_stand(client):
    """The idempotency guard sits on the status rung, so nothing is recomputed.

    This stage carries the idempotency guard: a second submit, a second underwrite, a
    second approve or a second assessment on the same application fails here.

    Design: Corner/state_machines/resubmit_of_under_review_application_rejected
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    fixtures.add_solar_measure(client, world)
    submitted = A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    version_after_submit = submitted["version"]

    A.expect_error(
        client.submit_application(world["application_id"], world["owner_headers"]),
        ERR_APPLICATION_STATE_INVALID,
    )

    final = fixtures.read_application(client, world)
    A.assert_version(final, version_after_submit)
    A.assert_fields(
        final,
        status="UNDER_REVIEW",
        requested_principal_cents=3000000,
        portfolio_sir_bps=12770,
        min_measure_sir_bps=12770,
        weighted_useful_life_years=25,
        screening_cltv_bps=7000,
    )
    A.assert_absent_or_none(final, "underwriter_user_id")


def test_a_successful_proceed_notifies_the_holder_and_dates_the_deadline(client):
    """Notice is a side effect of the decision, and the deadline is exactly 30 days out.

    Notification is not a separate call: it is a side effect of a successful `PROCEED`. At
    that instant every `MortgageLien` on the parcel whose `status` is `ACTIVE` moves along
    its consent axis from `NOT_NOTIFIED` to `PENDING`, and each notified lien has
    `consent_application_id` set to the application being underwritten, `notified_at` set
    to the current logical instant, and `consent_deadline_at` set to that instant plus 30
    days.

    Design: Corner/state_machines/underwrite_proceed_notifies_active_liens_and_sets_deadline
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    fixtures.add_solar_measure(client, world)
    fixtures.submitted_application(client, world)
    A.assert_fields(
        A.expect_ok(client.get_mortgage_lien(world["lien_id"], COMPLIANCE_OFFICER)),
        consent_response="NOT_NOTIFIED",
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
        consent_posture="PENDING",
        notified_lien_count=1,
        consent_deadline_at="2026-09-11T00:00:00Z",
        requested_principal_cents=3000000,
        underwriting_cltv_bps=7000,
        valuation_basis="ASSESSED",
        underwriter_user_id="u_ana_1",
    )
    A.assert_fields(
        A.expect_ok(client.get_mortgage_lien(world["lien_id"], COMPLIANCE_OFFICER)),
        consent_response="PENDING",
        consent_application_id=world["application_id"],
        notified_at="2026-08-12T00:00:00Z",
        consent_deadline_at="2026-09-11T00:00:00Z",
    )
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]), status="APPROVED"
    )


def test_one_lender_refusal_vetoes_the_application_and_its_measures(client):
    """The veto cascades two levels and cannot be approved away afterwards.

    A single `DECLINE` is fatal. The application moves from `CONSENT_PENDING` to
    `DECLINED` with `decline_reason_code` set to `LENDER_DECLINED`, `consent_posture`
    becomes `VETOED`, and every measure standing at `APPROVED` falls to `INELIGIBLE`.

    Design: Corner/state_machines/lender_decline_cascades_declined_application_and_ineligible_measures
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    fixtures.add_solar_measure(client, world)
    fixtures.submitted_application(client, world)
    fixtures.underwritten_application(client, world)

    refused = A.expect_ok(
        client.record_consent_response(
            world["lien_id"],
            factories.consent_response_payload(
                "DECLINE", note="Loan documents forbid a senior assessment"
            ),
            COMPLIANCE_OFFICER,
        )
    )
    A.assert_fields(
        refused,
        consent_response="DECLINED",
        consent_responded_at="2026-08-12T00:00:00Z",
    )

    vetoed = fixtures.read_application(client, world)
    A.assert_fields(
        vetoed,
        status="DECLINED",
        decline_reason_code="LENDER_DECLINED",
        consent_posture="VETOED",
    )
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]), status="INELIGIBLE"
    )

    A.expect_error(
        client.approve_application(world["application_id"], COMPLIANCE_OFFICER),
        ERR_APPLICATION_STATE_INVALID,
    )
    settled = fixtures.read_application(client, world)
    A.assert_absent_or_none(settled, "approver_user_id")
    A.assert_fields(
        fixtures.read_property(client, world), committed_pace_principal_cents=0
    )
