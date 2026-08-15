"""Certificates of Appropriateness: issuance gates, the 365-day commence
deadline, conditions verification, and layered validation ordering
(PRD §2.8, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_certificate,
    assert_instant_equal,
    create_violation,
    get_application,
    set_clock,
    setup_certificate_issued,
    setup_staff_approved,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["staff_headers"]


def test_certificate_issue_success_and_deadline(api):
    """PRD §3.9: "Issuance stamps `issued_at` with the logical clock, sets the
    `work_commence_deadline` to exactly three hundred sixty-five days after
    issuance, copies the application's `decision_conditions` onto the
    certificate's `conditions`, and starts the certificate in `ISSUED`."

    Design: Corner/endpoints/certificate_issue_success_and_deadline
    """
    ctx = setup_certificate_issued(issue_clock="2026-08-01T00:00:00Z")
    certificate = ctx["certificate"]
    assert_certificate(certificate)
    assert certificate["status"] == "ISSUED"
    assert certificate["application_id"] == ctx["application"]["id"]
    assert_instant_equal(certificate["issued_at"], "2026-08-01T00:00:00Z", "issued_at")
    assert_instant_equal(
        certificate["work_commence_deadline"], "2027-08-01T00:00:00Z",
        "work_commence_deadline (issued_at + 365 days)",
    )


def test_certificate_fee_gate_unpaid_rejected(api):
    """PRD §3.9: "Finally the fee account must be settled: a
    `fee_balance_cents` greater than zero is rejected with
    `ERR_FEE_BALANCE_OUTSTANDING`."

    Design: Corner/endpoints/certificate_fee_gate_unpaid_rejected
    """
    ctx = setup_staff_approved()  # assessed 10400, unpaid
    assert ctx["application"]["fee_balance_cents"] == 10400
    response = api.create_certificate(
        {"application_id": ctx["application"]["id"]}, STAFF
    )
    validate_error(response, ApiErrorId.ERR_FEE_BALANCE_OUTSTANDING)


def test_certificate_duplicate_rejected(api):
    """PRD §3.9: "There must be no existing certificate for the same
    application — the relationship is one-to-one, and a second issuance is
    rejected with `ERR_CERTIFICATE_EXISTS`."

    Design: Corner/endpoints/certificate_duplicate_rejected
    """
    ctx = setup_certificate_issued()
    response = api.create_certificate(
        {"application_id": ctx["application"]["id"]}, STAFF
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATE_EXISTS)


def test_certificate_expire_boundary(api):
    """PRD §3.9: "Should the deadline lapse first, staff expires the
    certificate: from `ISSUED` or `CONDITIONS_VERIFIED`, expiry is permitted
    only once the logical clock has passed the `work_commence_deadline` — at or
    before the deadline the request is rejected with
    `ERR_CERTIFICATE_NOT_YET_EXPIRED` — and moves the certificate to
    `EXPIRED`."
    PRD §3.9: "Staff completes a `CONDITIONS_VERIFIED` certificate by supplying
    the `commenced_at` instant; both the current logical clock and the
    payload's `commenced_at` must be at or before the `work_commence_deadline`,
    and either being late is rejected with `ERR_CERTIFICATE_EXPIRED`."

    Design: Corner/endpoints/certificate_expire_boundary
    """
    ctx = setup_certificate_issued(issue_clock="2026-08-01T00:00:00Z")
    cert_id = ctx["certificate"]["id"]
    validate_success(
        api.verify_conditions(cert_id, {"conditions_met_count": 0}, STAFF)
    )

    # At exactly the deadline (2027-08-01T00:00:00Z) expiry is not yet due.
    set_clock("2027-08-01T00:00:00Z")
    not_yet = api.expire_certificate(cert_id, STAFF)
    validate_error(not_yet, ApiErrorId.ERR_CERTIFICATE_NOT_YET_EXPIRED)

    # One second past the deadline, completion is barred (clock and
    # commenced_at both late), and expiry succeeds.
    set_clock("2027-08-01T00:00:01Z")
    late_complete = api.complete_certificate(
        cert_id, {"commenced_at": "2027-08-01T00:00:01Z"}, STAFF
    )
    validate_error(late_complete, ApiErrorId.ERR_CERTIFICATE_EXPIRED)

    expired = validate_success(api.expire_certificate(cert_id, STAFF))
    assert expired["status"] == "EXPIRED"


def test_conditions_copied_and_verify_gates_count(api):
    """PRD §3.9: "Issuance stamps `issued_at` with the logical clock, sets the
    `work_commence_deadline` to exactly three hundred sixty-five days after
    issuance, copies the application's `decision_conditions` onto the
    certificate's `conditions`, and starts the certificate in `ISSUED`."
    PRD §3.9: "From there, staff verifies conditions by reporting the
    `conditions_met_count`; the reported count must equal the number of
    recorded `conditions` — every condition satisfied — or the verification is
    rejected with `ERR_CONDITIONS_UNMET`, and a successful verification moves
    the certificate from `ISSUED` to `CONDITIONS_VERIFIED`."

    Design: Corner/endpoints/decide_with_conditions_records_and_gates_certificate
    """
    conditions = ["Use matching brick", "Inspect mortar"]
    ctx = setup_certificate_issued(conditions=conditions)
    certificate = ctx["certificate"]
    assert ctx["application"]["decision_conditions"] == conditions
    assert certificate["conditions"] == conditions, (
        "issuance copies the application's decision_conditions"
    )

    short = api.verify_conditions(certificate["id"], {"conditions_met_count": 1}, STAFF)
    validate_error(short, ApiErrorId.ERR_CONDITIONS_UNMET)

    verified = validate_success(
        api.verify_conditions(certificate["id"], {"conditions_met_count": 2}, STAFF)
    )
    assert verified["status"] == "CONDITIONS_VERIFIED"


class TestCertificateReferentialGateMasksFiscal:
    def test_certificate_issuance_referential_gate_masks_fiscal(self, api):
        """PRD §3.9: "The property must be clean of enforcement: an
        `open_violation_count` greater than zero is rejected with
        `ERR_UNRESOLVED_VIOLATION_EXISTS`, and this referential check runs
        before the fiscal one."
        PRD §2.8: "Because of this ordering, a stale property version surfaces
        even when the payload would also fail a business rule, an
        unresolved-violation rejection at certificate issuance surfaces before
        any outstanding-balance check, and an applicant-ownership failure on a
        resubmission surfaces before the resubmission window is ever
        evaluated."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_certificate
        """
        ctx = setup_staff_approved()  # assessed 10400, unpaid (fiscal also fails)
        create_violation(ctx["property"]["id"])  # open_violation_count == 1

        response = api.create_certificate(
            {"application_id": ctx["application"]["id"]}, STAFF
        )
        validate_error(response, ApiErrorId.ERR_UNRESOLVED_VIOLATION_EXISTS)

    def test_referential_rejection_leaves_no_certificate_and_fee_untouched(self, api):
        """PRD §3.9: "The property must be clean of enforcement: an
        `open_violation_count` greater than zero is rejected with
        `ERR_UNRESOLVED_VIOLATION_EXISTS`, and this referential check runs
        before the fiscal one."
        PRD §2.10: "every such cascade commits atomically within the triggering request: there is no eventual-consistency window in which a client could observe a decision without its hearing mirror, a demolition approval without its delay window, or a violation resolution without its property counter adjustment."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_certificate
        """
        ctx = setup_staff_approved()
        create_violation(ctx["property"]["id"])

        validate_error(
            api.create_certificate({"application_id": ctx["application"]["id"]}, STAFF),
            ApiErrorId.ERR_UNRESOLVED_VIOLATION_EXISTS,
        )
        certificates, meta = validate_paginated(
            api.list_certificates(STAFF, params={"application_id": ctx["application"]["id"]})
        )
        assert meta["total_count"] == 0, "no certificate may be persisted"

        application = get_application(ctx["application"]["id"])
        # SITE_WORK verified at 200000: 10000 + round_half_up(0.002*200000).
        assert application["fee_balance_cents"] == 10400
        assert application["paid_fee_cents"] == 0
