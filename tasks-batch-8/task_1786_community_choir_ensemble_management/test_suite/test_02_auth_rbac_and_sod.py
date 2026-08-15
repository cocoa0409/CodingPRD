"""Authentication, role-based access control, ownership, segregation of duties."""
from test_helpers import (
    ApiErrorId,
    activate_member,
    advance_posture,
    book_audition,
    contract_in_state,
    create_member,
    create_open_season_with_section,
    create_pledge,
    create_rehearsal_payload,
    create_season_payload,
    enroll_member,
    issue_invoice,
    make_member_headers,
    make_president_headers,
    make_treasurer_headers,
    pay_dues,
    score_audition_payload,
    setup_active_committee_with_pledges,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this list, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_seasons(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_librarian_cannot_create_season_forbidden(self, api,
                                                      librarian_headers):
        """PRD §2.1: "An authenticated caller attempting an operation that
        their role is not permitted to perform is rejected with
        `ERR_FORBIDDEN`."
        PRD §4: POST `/v1/seasons` is authorized for President only.

        Design: Corner/rbac/librarian_cannot_create_season_forbidden
        """
        resp = api.create_season(create_season_payload(), librarian_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_treasurer_cannot_score_audition_forbidden(self, api,
                                                       treasurer_headers):
        """PRD §2.1: "An authenticated caller attempting an operation that
        their role is not permitted to perform is rejected with
        `ERR_FORBIDDEN`."
        PRD §4: POST `/v1/auditions/{id}/score` is authorized for ChoirDirector
        only.

        Design: Corner/rbac/treasurer_cannot_score_audition_forbidden
        """
        season, _section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"])
        resp = api.score_audition(
            audition["id"], score_audition_payload(), treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_director_cannot_pay_contract_forbidden(self, api,
                                                    director_headers):
        """PRD §2.1: "An authenticated caller attempting an operation that
        their role is not permitted to perform is rejected with
        `ERR_FORBIDDEN`."
        PRD §4: POST `/v1/guest-contracts/{id}/pay` is authorized for Treasurer
        only.

        Design: Corner/rbac/director_cannot_pay_contract_forbidden
        """
        season, section = create_open_season_with_section()
        activate_member(season["id"], section["id"])
        contract = contract_in_state(
            season["id"], "APPROVED", rate_cents=10000,
            approver_headers=make_president_headers("pres-1"))
        resp = api.pay_contract(contract["id"], director_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_member_cannot_create_rehearsal_forbidden(self, api):
        """PRD §2.1: "An authenticated caller attempting an operation that
        their role is not permitted to perform is rejected with
        `ERR_FORBIDDEN`."
        PRD §4: POST `/v1/rehearsals` is authorized for ChoirDirector only.

        Design: Corner/rbac/member_cannot_create_rehearsal_forbidden
        """
        season, section = create_open_season_with_section()
        member = activate_member(season["id"], section["id"])
        advance_posture(season["id"], "REHEARSING")
        resp = api.create_rehearsal(
            create_rehearsal_payload(season["id"], "2026-08-05T19:00:00Z"),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestMemberOwnership:
    def test_member_reads_other_members_invoice_forbidden_ownership(
            self, api):
        """PRD §2.1: "A `Member` caller may touch only their own record, their
        own invoices and payments, their own scholarship grants, their own
        attendance records, their own score checkouts, and their own tour
        registrations; acting on a resource owned by a different member is
        rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/member_reads_other_members_invoice_forbidden_ownership
        """
        season, section = create_open_season_with_section(target_max=4)
        m1 = enroll_member(season["id"], section["id"], "A One", "a1@x.org",
                           "2026-08-02T10:00:00Z")
        invoice = issue_invoice(m1["id"])
        pay_dues(m1["id"])
        m2 = enroll_member(season["id"], section["id"], "A Two", "a2@x.org",
                           "2026-08-02T11:00:00Z")
        issue_invoice(m2["id"])
        pay_dues(m2["id"])

        resp = api.get_invoice(invoice["id"], make_member_headers(m2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        # The owner themselves can read it.
        own = api.get_invoice(invoice["id"], make_member_headers(m1["id"]))
        validate_success(own, 200)


class TestSegregationOfDuties:
    def test_sod_contract_pay_by_approver_rejected(self, api):
        """PRD §3.7: "Treasurer payment moves `APPROVED` to the terminal
        `PAID`, but only under two guards: the paying user must differ from the
        `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and the
        treasury must cover `quoted_fee_cents`, else
        `ERR_INSUFFICIENT_TREASURY`; payment debits the quoted fee from the
        treasury and records `paid_by_user_id`."

        Design: Corner/rbac/sod_contract_pay_by_approver_rejected
        """
        season, section = create_open_season_with_section()
        activate_member(season["id"], section["id"])  # treasury: 18000
        contract = contract_in_state(
            season["id"], "APPROVED", rate_cents=10000,
            approver_headers=make_president_headers("user-77"))

        # The same user id that approved cannot pay.
        resp = api.pay_contract(
            contract["id"], make_treasurer_headers("user-77"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # A different treasurer user completes the payment.
        paid = validate_success(
            api.pay_contract(contract["id"], make_treasurer_headers("treas-9")))
        assert paid["status"] == "PAID"
        assert paid["paid_by_user_id"] == "treas-9"
        season_data = validate_success(
            api.get_season(season["id"], make_treasurer_headers("treas-9")))
        assert season_data["treasury_balance_cents"] == 8000, \
            "18000 dues minus 10000 quoted fee"

    def test_sod_pledge_fulfill_by_recorder_rejected(self, api):
        """PRD §3.9: "Fulfilment converts the promise to cash: a Treasurer
        fulfills a `PLEDGED` pledge, but the fulfilling officer — recorded as
        `fulfilled_by_user_id` — must differ from the `recorded_by_user_id`,
        else `ERR_SEGREGATION_OF_DUTIES`. Fulfilment credits the treasury with
        `amount_cents`, recomputes the committee's `raised_cents` (the sum of
        its `FULFILLED` pledge amounts), and computes the donor's
        `recognition_tier`"

        Design: Corner/rbac/sod_pledge_fulfill_by_recorder_rejected
        """
        season, _section, _chair, committee = (
            setup_active_committee_with_pledges())
        pledge = create_pledge(committee["id"], "D1", 5000,
                               recorder_headers=make_treasurer_headers("treas-1"))

        resp = api.fulfill_pledge(
            pledge["id"], make_treasurer_headers("treas-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        fulfilled = validate_success(api.fulfill_pledge(
            pledge["id"], make_treasurer_headers("treas-2")))
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["fulfilled_by_user_id"] == "treas-2"
        committee_data = validate_success(api.get_committee(
            committee["id"], make_treasurer_headers("treas-2")))
        assert committee_data["raised_cents"] == 5000
