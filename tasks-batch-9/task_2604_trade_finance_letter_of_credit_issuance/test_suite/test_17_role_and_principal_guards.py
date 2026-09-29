"""Authentication, role authorization, four-eyes segregation and row-level principal scoping.

The rejection ladder puts authentication above authorization and authorization above
existence, so every negative test here aims at an id that does not exist and still expects a
401 or a 403. The positive halves prove the same tables are not over-tight: every role named
on an endpoint reaches it, and a second operator identity completes what the first was refused.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_2,
    CREDIT_OFFICER_1,
    CREDIT_OFFICER_2,
    DOCUMENT_EXAMINER_1,
    TRADE_FINANCE_OFFICER_1,
    TRADE_FINANCE_OFFICER_2,
    add_invoice,
    add_transport_document,
    api_client,
    approve_credit,
    assert_all_sweep_counters_zero,
    assert_facility_ledger,
    assert_fields_equal,
    change_facility_status,
    compliance_officer_headers,
    conclude_examination,
    consent_to_amendment,
    create_applicant,
    create_bank,
    credit_officer_headers,
    document_examiner_headers,
    draft_amendment,
    draft_credit,
    factories,
    issue_amendment,
    issue_credit,
    issued_credit,
    list_amendment_rows,
    list_discrepancy_rows,
    list_facility_allocation_rows,
    list_presentation_screening_rows,
    list_presented_document_rows,
    list_waiver_request_rows,
    lodge_claim,
    make_applicant_user_headers,
    make_beneficiary_user_headers,
    make_correspondent_bank_headers,
    open_presentation,
    post_collateral,
    raise_discrepancy,
    request_waiver,
    rescreen_presentation,
    respond_to_waiver,
    review_screening,
    run_sweep,
    settle_claim,
    setup_parties,
    submit_credit_for_approval,
    submit_presentation,
    submitted_presentation,
    system_operator_headers,
    trade_finance_officer_headers,
)

# Only the content type is sent, so both authentication headers are genuinely absent.
NO_HEADERS = {"Content-Type": "application/json"}

A_LATER_INSTANT = "2026-09-01T09:00:00Z"
THE_CLOCK_INSTANT = "2026-08-10T09:00:00.000Z"

SWEEP_COUNTERS = (
    "credits_expired",
    "presentations_precluded",
    "waiver_requests_expired",
    "amendments_lapsed",
    "allocations_released",
    "facilities_reactivated",
)

_APPLICANT = {"legal_name": "Baltic Timber Imports AS", "country_code": "NO"}
_BANK = {
    "bank_name": "Nordkyst Bank",
    "swift_bic": "NDKBNOKK",
    "country_code": "NO",
    "country_risk_score": 12,
    "credit_rating": "AA",
    "confirmation_appetite_cents": 90000000,
}
_BENEFICIARY = {"beneficiary_name": "Riga Sawmill SIA", "country_code": "LV"}


def _parties(**facility_overrides):
    """The standard four counterparties: a NO applicant, a NO bank and an LV beneficiary."""
    facility = {"limit_cents": 50000000, "collateral_required_pct": 0}
    facility.update(facility_overrides)
    return setup_parties(
        applicant=dict(_APPLICANT),
        facility=facility,
        bank=dict(_BANK),
        beneficiary=dict(_BENEFICIARY),
    )


def _assert_error_envelope(response):
    """The error envelope carries exactly `error_id` and `message` beside the two meta fields."""
    body = response.json()
    assert body["response_type"] == "error"
    assert sorted(body["data"]) == ["error_id", "message"]
    assert sorted(body["meta"]) == ["api_request_id", "api_request_timestamp"]


class TestMissingHeadersAreRejectedBeforeAnythingElse:
    """A request with neither header never learns whether its target exists or its body parses."""

    def test_a_header_less_read_and_write_answer_401_not_404_or_422(self, clock):
        """The unknown id and the blank `legal_name` are both invisible behind the 401.

        PRD 2.1: "Every request — reads included — must carry two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming the capacity it acts in."

        PRD 2.1: "If either header is missing or empty the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before anything else, so an
        unauthenticated request never learns whether the resource it addressed exists."

        Design: Corner/rbac/missing_x_user_headers_return_unauthenticated_before_anything_else
        """
        read = api_client.get_credit(NON_EXISTENT_UUID, NO_HEADERS)

        validate_error(read, "ERR_UNAUTHENTICATED", 401)
        _assert_error_envelope(read)

        write = api_client.create_applicant({"legal_name": ""}, NO_HEADERS)

        validate_error(write, "ERR_UNAUTHENTICATED", 401)
        _assert_error_envelope(write)
        message = write.json()["data"]["message"]
        assert isinstance(message, str) and message.strip()

        authenticated_read = api_client.get_credit(
            NON_EXISTENT_UUID, trade_finance_officer_headers()
        )

        assert authenticated_read.status_code == 404

    def test_a_header_less_clock_call_does_not_move_the_clock(self, clock):
        """The 401 is total: the logical clock is still the instant every derivation reads.

        PRD 2.1: "If either header is missing or empty the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before anything else, so an
        unauthenticated request never learns whether the resource it addressed exists."

        PRD 3.1: "The server records the acting operator as `onboarded_by_user_id` and sets the
        applicant's `status` to `ACTIVE`; the field's other two declared values, `SUSPENDED` and
        `CLOSED`, are never produced at onboarding."

        Design: Corner/rbac/missing_x_user_headers_return_unauthenticated_before_anything_else
        """
        response = api_client.set_clock(factories.clock_payload(A_LATER_INSTANT), NO_HEADERS)

        validate_error(response, "ERR_UNAUTHENTICATED", 401)
        _assert_error_envelope(response)

        applicant = create_applicant()

        assert_fields_equal(
            applicant,
            created_at=THE_CLOCK_INSTANT,
            status="ACTIVE",
            sanctions_flag=False,
            onboarded_by_user_id=CREDIT_OFFICER_1,
        )


class TestRolesCannotInvokeAnotherRolesExclusiveOperations:
    """Six crossings of the segregation lines, each aimed at an id that does not exist."""

    def test_four_cross_role_calls_are_refused_before_the_id_is_resolved(self, clock):
        """403 `ERR_UNAUTHORIZED` from all four, and not one of them is a 404.

        PRD 2.1: "If `X-User-Role` is not one of those eight strings, or is one of them but is
        not listed among the roles authorised for the addressed endpoint, the request is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD 2.1: "There is no hierarchical override anywhere in this system: a `CreditOfficer`
        cannot do a `TradeFinanceOfficer`'s work and a `TradeFinanceOfficer` cannot do a
        `CreditOfficer`'s, regardless of seniority."

        Design: Corner/rbac/roles_cannot_invoke_another_roles_exclusive_operations
        """
        beneficiary_approving = api_client.approve_credit(
            NON_EXISTENT_UUID,
            factories.approve_payload(),
            make_beneficiary_user_headers(NON_EXISTENT_UUID),
        )
        examiner_issuing = api_client.issue_credit(
            NON_EXISTENT_UUID, factories.issue_payload(), document_examiner_headers()
        )
        officer_raising_a_defect = api_client.create_discrepancy(
            NON_EXISTENT_UUID,
            factories.discrepancy_payload("LATE_SHIPMENT", "MATERIAL"),
            trade_finance_officer_headers(),
        )
        compliance_settling = api_client.settle_claim(
            NON_EXISTENT_UUID, factories.settle_payload(), compliance_officer_headers()
        )

        for response in (
            beneficiary_approving,
            examiner_issuing,
            officer_raising_a_defect,
            compliance_settling,
        ):
            validate_error(response, "ERR_UNAUTHORIZED", 403)
            _assert_error_envelope(response)
            assert response.status_code != 404

    def test_the_operator_and_the_bank_are_barred_from_each_others_writes(self, clock):
        """A `SystemOperator` cannot draft a credit and a `CorrespondentBank` cannot sweep.

        PRD 2.1: "If `X-User-Role` is not one of those eight strings, or is one of them but is
        not listed among the roles authorised for the addressed endpoint, the request is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD 2.1: "`SystemOperator` is likewise opaque, and nothing at all is recorded from it."

        Design: Corner/rbac/roles_cannot_invoke_another_roles_exclusive_operations
        """
        operator_drafting = api_client.create_credit(
            factories.credit_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            system_operator_headers(),
        )
        bank_sweeping = api_client.run_expiry_sweep(
            factories.sweep_payload(), make_correspondent_bank_headers(NON_EXISTENT_UUID)
        )

        for response in (operator_drafting, bank_sweeping):
            validate_error(response, "ERR_UNAUTHORIZED", 403)
            _assert_error_envelope(response)

        _rows, meta = validate_paginated(api_client.list_credits(credit_officer_headers()))
        assert meta["total_count"] == 0


class TestSegregationOfDutiesComparesOperatorIdsNotRoles:
    """The four-eyes rules read `X-User-ID`, so the same id twice fails whatever role it wears."""

    def test_a_credit_officer_presenting_the_drafters_id_cannot_approve(self, clock):
        """403 first, then the identical call under a second operator id goes through.

        PRD 2.10: "Three steps in this service are four-eyes controlled, and in each the acting
        `X-User-ID` must differ from the identifier recorded against the step being reviewed."

        PRD 2.10: "Note the shape of the rule: it compares operator identifiers, not roles, so
        two different `TradeFinanceOfficer` principals satisfy it and one principal wearing the
        same role twice does not."

        PRD 3.3: "Approval grants permission and nothing more — **no facility debit happens
        here**."

        Design: Corner/rbac/same_user_id_cannot_draft_and_approve_a_credit_or_issue_its_own_amendment
        """
        parties = _parties()
        ctx = draft_credit(parties)
        submit_credit_for_approval(ctx.credit_id)
        pending = ctx.refresh()
        assert_fields_equal(
            pending,
            status="PENDING_CREDIT_APPROVAL",
            drafted_by_user_id=TRADE_FINANCE_OFFICER_1,
        )

        refused = api_client.approve_credit(
            ctx.credit_id,
            factories.approve_payload(),
            credit_officer_headers(TRADE_FINANCE_OFFICER_1),
        )

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
        _assert_error_envelope(refused)
        assert_fields_equal(
            ctx.refresh(), status="PENDING_CREDIT_APPROVAL", version=pending["version"]
        )
        assert list_facility_allocation_rows(parties.facility_id) == []

        approved = approve_credit(ctx.credit_id, user_id=CREDIT_OFFICER_2)

        assert approved["status"] == "APPROVED"
        assert list_facility_allocation_rows(parties.facility_id) == []
        assert_facility_ledger(
            parties.refresh_facility(), allocated_cents=0, available_cents=50000000
        )
        assert issue_credit(ctx.credit_id)["status"] == "ISSUED"

    def test_the_drafting_officer_cannot_issue_its_own_amendment(self, clock):
        """The mirror rule on a second entity: tfo_1 drafts, only tfo_2 may issue.

        PRD 3.5: "The acting `X-User-ID` must differ from `drafted_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES` (403)."

        PRD 3.5: "When `requires_beneficiary_consent` is false, the amendment traverses `DRAFT →
        ISSUED → ACCEPTED` inside the single issue call — a favourable amendment binds on
        issuance."

        PRD 3.5: "When `exposure_delta_cents` is zero or negative, `amendment_fee_cents` is the
        flat 7,500 cents."

        Design: Corner/rbac/same_user_id_cannot_draft_and_approve_a_credit_or_issue_its_own_amendment
        """
        ctx = issued_credit(_parties())
        amendment = draft_amendment(ctx, {"expiry_date": "2026-12-31"})
        assert_fields_equal(
            amendment,
            status="DRAFT",
            seq=1,
            drafted_by_user_id=TRADE_FINANCE_OFFICER_1,
            requires_beneficiary_consent=False,
            exposure_delta_cents=0,
            issued_by_user_id=None,
            consent_window_start=None,
        )

        refused = api_client.issue_amendment(
            amendment["id"],
            factories.amendment_issue_payload(),
            trade_finance_officer_headers(TRADE_FINANCE_OFFICER_1),
        )

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
        _assert_error_envelope(refused)
        stored = list_amendment_rows(ctx.credit_id)[0]
        assert_fields_equal(
            stored,
            status="DRAFT",
            issued_by_user_id=None,
            consent_window_start=None,
            version=amendment["version"],
        )

        issued = issue_amendment(amendment["id"], user_id=TRADE_FINANCE_OFFICER_2)

        assert_fields_equal(
            issued,
            status="ACCEPTED",
            issued_by_user_id=TRADE_FINANCE_OFFICER_2,
            amendment_fee_cents=7500,
        )
        assert_fields_equal(
            ctx.refresh(), status="ISSUED", expiry_date="2026-12-31", amendment_seq=1
        )


class TestTheScreeningOfficerCannotClearItsOwnHit:
    """The third four-eyes rule, on a genuine dual-use hit, checked before the state guard."""

    @staticmethod
    def _hit_pending_review():
        """An 8471 invoice scores 60 on the dual-use limb, which reviews without blocking."""
        ctx = issued_credit(_parties())
        pctx = submitted_presentation(
            ctx,
            invoice_amounts=(4000000,),
            invoice_overrides={"hs_code": "8471600000"},
        )
        return ctx, pctx

    def test_the_officer_who_ran_the_screening_may_not_adjudicate_it(self, clock):
        """403 `ERR_SEGREGATION_OF_DUTIES`, and the hit keeps its result and its version.

        PRD 3.8: "The dual-use tariff prefixes are `8471`, `8542`, `9013` and `2811`, matched
        against the first four characters of a document's `hs_code`."

        PRD 3.8: "`risk_score` is 100 per country hit, plus 60 per dual-use hit, plus 40 per
        keyword hit, plus 20 per transit hit, and the total is then capped at 200 — a score never
        exceeds 200 however many hits accumulate."

        PRD 3.8: "The acting `X-User-ID` must differ from `screened_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES` (403) — the officer who ran a screening may not clear it."

        Design: Corner/rbac/same_compliance_officer_cannot_screen_and_then_review_the_hit
        """
        _ctx, pctx = self._hit_pending_review()
        check = rescreen_presentation(pctx, user_id=COMPLIANCE_OFFICER_1)
        assert_fields_equal(
            check,
            result="HIT_PENDING_REVIEW",
            risk_score=60,
            dual_use_hits=1,
            country_hits=0,
            keyword_hits=0,
            transit_hits=0,
            screened_by_user_id=COMPLIANCE_OFFICER_1,
            reviewed_by_user_id=None,
            reviewed_at=None,
        )

        refused = api_client.review_screening_check(
            check["id"],
            factories.screening_review_payload("RELEASE"),
            compliance_officer_headers(COMPLIANCE_OFFICER_1),
        )

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
        _assert_error_envelope(refused)
        stored = [
            row
            for row in list_presentation_screening_rows(pctx.presentation_id)
            if row["id"] == check["id"]
        ][0]
        assert_fields_equal(
            stored,
            result="HIT_PENDING_REVIEW",
            reviewed_by_user_id=None,
            reviewed_at=None,
            version=check["version"],
        )
        assert pctx.refresh()["examination_status"] == "UNDER_EXAMINATION"

    def test_a_second_compliance_officer_releases_the_identical_hit(self, clock):
        """The same payload from cmp_2 succeeds, and the examination is untouched by either call.

        PRD 3.8: "`RELEASE` moves `HIT_PENDING_REVIEW → RELEASED` and unblocks settlement."

        PRD 3.8: "All three branches set `reviewed_by_user_id`, `reviewed_at` and `review_note`
        and increment the check's `version`, and the three side-effect sets then diverge
        deliberately."

        Design: Corner/rbac/same_compliance_officer_cannot_screen_and_then_review_the_hit
        """
        _ctx, pctx = self._hit_pending_review()
        check = rescreen_presentation(pctx, user_id=COMPLIANCE_OFFICER_1)
        assert check["result"] == "HIT_PENDING_REVIEW"

        released = review_screening(check["id"], "RELEASE", user_id=COMPLIANCE_OFFICER_2)

        assert_fields_equal(
            released,
            result="RELEASED",
            risk_score=60,
            dual_use_hits=1,
            screened_by_user_id=COMPLIANCE_OFFICER_1,
            reviewed_by_user_id=COMPLIANCE_OFFICER_2,
            reviewed_at=THE_CLOCK_INSTANT,
            version=check["version"] + 1,
        )
        assert_fields_equal(
            pctx.refresh(), examination_status="UNDER_EXAMINATION", discrepancy_count=0
        )


class TestEntityBackedPrincipalsMustBePartyToTheRow:
    """`X-User-ID` is a primary key for three roles, so the guard is row-level, not role-level."""

    @staticmethod
    def _waiver_awaiting_the_applicant():
        """One MINOR defect waived out to the applicant, plus an unrelated applicant and bank."""
        parties = _parties()
        outsider = create_applicant(
            legal_name="Vistula Furniture Sp z o o", country_code="PL"
        )
        coastline = create_bank(
            bank_name="Coastline Trade Bank",
            swift_bic="CLTBSEXX",
            country_code="SE",
            country_risk_score=20,
            credit_rating="A",
        )
        ctx = issued_credit(parties)
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        raise_discrepancy(pctx, "GOODS_DESCRIPTION_MISMATCH", severity="MINOR")
        conclude_examination(pctx)
        waiver = request_waiver(pctx, ["GOODS_DESCRIPTION_MISMATCH"])
        return ctx, pctx, waiver, outsider, coastline

    def test_a_foreign_applicant_and_a_foreign_bank_are_both_not_party(self, clock):
        """Two 403s that are neither `ERR_UNAUTHORIZED` nor the state error the bank would hit.

        PRD 2.1: "When `X-User-Role` is `ApplicantUser`, `X-User-ID` is the `id` of the acting
        `Applicant`; ownership checks on any resource that references an `Applicant` compare the
        resource's `applicant_id` — reached directly on a credit, or through the presentation's
        credit on a waiver decision — to `X-User-ID`."

        PRD 2.1: "When `X-User-Role` is `CorrespondentBank`, `X-User-ID` is the `id` of the
        acting `Bank`; on a confirmation response the comparison is against the credit's
        `confirming_bank_id`, and on every presentation write it is against the presentation's
        `presenting_bank_id`."

        PRD 2.1: "A separate 403, `ERR_SEGREGATION_OF_DUTIES`, is reserved for the four-eyes
        rules of §2.10 and is never used for a plain ownership mismatch."

        Design: Corner/rbac/entity_backed_principals_cannot_act_on_rows_they_are_not_party_to
        """
        _ctx, pctx, waiver, outsider, coastline = self._waiver_awaiting_the_applicant()

        foreign_answer = api_client.respond_to_waiver_request(
            waiver["id"],
            factories.waiver_response_payload("GRANT"),
            make_applicant_user_headers(outsider["id"]),
        )

        validate_error(foreign_answer, "ERR_PRINCIPAL_NOT_PARTY", 403)
        _assert_error_envelope(foreign_answer)
        stored = list_waiver_request_rows(pctx.presentation_id)[0]
        assert_fields_equal(
            stored, status="PENDING", responded_at=None, version=waiver["version"]
        )

        foreign_document = api_client.create_presented_document(
            pctx.presentation_id,
            factories.invoice_document_payload(1000000),
            make_correspondent_bank_headers(coastline["id"]),
        )

        validate_error(foreign_document, "ERR_PRINCIPAL_NOT_PARTY", 403)
        _assert_error_envelope(foreign_document)
        assert len(list_presented_document_rows(pctx.presentation_id)) == 2
        assert_fields_equal(
            pctx.refresh(),
            examination_status="WAIVER_REQUESTED",
            document_count=2,
            drawn_amount_cents=4000000,
        )

    def test_the_credits_own_applicant_answers_the_same_payload_successfully(self, clock):
        """The control that makes the refusal meaningful: the party in interest may grant.

        PRD 3.7: "`GRANT` moves the request `PENDING → GRANTED` and every cited Discrepancy
        `IDENTIFIED → WAIVED`, which lowers `discrepancy_count`."

        PRD 3.7: "Where the presentation lands then depends on whether the waiver was total: if
        `discrepancy_count` reaches zero the presentation moves `WAIVER_REQUESTED → COMPLYING`
        and may be settled, but if at least one `IDENTIFIED` discrepancy remains uncited and
        therefore unwaived, the presentation returns `WAIVER_REQUESTED → DISCREPANT` instead."

        Design: Corner/rbac/entity_backed_principals_cannot_act_on_rows_they_are_not_party_to
        """
        ctx, pctx, waiver, _outsider, _coastline = self._waiver_awaiting_the_applicant()

        granted = respond_to_waiver(waiver["id"], ctx.parties.applicant_id, "GRANT")

        assert_fields_equal(granted, status="GRANTED", responded_at=THE_CLOCK_INSTANT)
        assert [row["status"] for row in list_discrepancy_rows(pctx.presentation_id)] == [
            "WAIVED"
        ]
        assert_fields_equal(
            pctx.refresh(),
            examination_status="COMPLYING",
            discrepancy_count=0,
            settlement_status="UNSETTLED",
        )


class TestTheSharedSurfaceAdmitsEveryRoleListedOnIt:
    """The positive half of the role table: every listed role reaches the endpoint it is on."""

    def test_all_seven_roles_listed_on_the_credit_read_reach_it(self, clock):
        """Seven readers, three of them entity-backed principals acting on their own row.

        PRD 2.1: "Every request — reads included — must carry two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming the capacity it acts in."

        PRD 4: "TradeFinanceOfficer, CreditOfficer, ComplianceOfficer, DocumentExaminer,
        ApplicantUser, BeneficiaryUser, CorrespondentBank"

        PRD 2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with exactly three
        fractional digits, and `version` is an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."

        Design: Corner/rbac/shared_read_surface_and_shared_bank_patch_work_for_every_permitted_role
        """
        parties = _parties()
        ctx = draft_credit(parties)
        before = ctx.refresh()

        for headers in (
            trade_finance_officer_headers(),
            credit_officer_headers(),
            compliance_officer_headers(),
            document_examiner_headers(DOCUMENT_EXAMINER_1),
            parties.applicant_headers,
            parties.beneficiary_headers,
            parties.advising_bank_headers,
        ):
            seen = validate_success(api_client.get_credit(ctx.credit_id, headers))
            assert_fields_equal(seen, id=ctx.credit_id, status="DRAFT")

        facility = validate_success(
            api_client.get_facility(parties.facility_id, parties.applicant_headers)
        )
        assert facility["id"] == parties.facility_id
        beneficiary = validate_success(
            api_client.get_beneficiary(parties.beneficiary_id, document_examiner_headers())
        )
        assert beneficiary["id"] == parties.beneficiary_id

        assert_fields_equal(
            ctx.refresh(),
            status="DRAFT",
            version=before["version"],
            updated_at=before["updated_at"],
        )

    def test_the_bank_patch_is_shared_with_compliance_and_re_derives_eligibility(self, clock):
        """928 at risk 12 becomes 820 at risk 30, and only the field sent moves.

        PRD 3.1: "Its `eligibility_score` is derived immediately: take 100 minus
        `country_risk_score`, multiply by 6, and add the rating points multiplied by 4, where the
        rating points are 100 for `AA`, 75 for `A`, 50 for `BBB` and 25 for `BB`."

        PRD 3.1: "Either a `CreditOfficer` or a `ComplianceOfficer` may revise its `status`,
        `sanctions_flag`, `country_risk_score`, `confirmation_appetite_cents` or `credit_rating`,
        and `eligibility_score` is re-derived from the new `country_risk_score` and
        `credit_rating` on the spot."

        Design: Corner/rbac/shared_read_surface_and_shared_bank_patch_work_for_every_permitted_role
        """
        bank = create_bank(**dict(_BANK))
        assert_fields_equal(
            bank,
            eligibility_score=928,
            country_risk_score=12,
            credit_rating="AA",
            status="ACTIVE",
            confirming_line_used_cents=0,
            sanctions_flag=False,
        )

        patched = validate_success(
            api_client.patch_bank(
                bank["id"], {"country_risk_score": 30}, compliance_officer_headers()
            )
        )

        assert_fields_equal(
            patched,
            country_risk_score=30,
            eligibility_score=820,
            bank_name="Nordkyst Bank",
            swift_bic="NDKBNOKK",
            country_code="NO",
            credit_rating="AA",
            confirmation_appetite_cents=90000000,
            status="ACTIVE",
            sanctions_flag=False,
            confirming_line_used_cents=0,
            version=bank["version"] + 1,
        )


class TestEveryRoleCanRunItsOwnExclusiveOperations:
    """One pass in which each of the eight roles performs an operation only it may perform."""

    def test_the_whole_instrument_runs_once_through_all_eight_roles(self, clock):
        """Onboarding, collateral, issuance, amendment, presentation, waiver and settlement.

        PRD 3.1: "Critically, a posting is forward-looking only: it never retroactively changes
        `committed_allocation_cents` on a credit that has already been issued."

        PRD 3.5: "Hop one applies the `change_set` to the credit, sets the credit's
        `amendment_seq` to this amendment's `seq`, and returns the credit `AMENDMENT_PENDING →
        ISSUED`."

        PRD 3.9: "Step four deducts the charges from the drawn amount in the fixed order
        commission, then discount, then document fees: `net_proceeds_cents` is
        `drawn_amount_cents` minus `commission_cents` minus `discount_cents` minus
        `doc_examination_fee_cents`."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations_end_to_end
        """
        parties = _parties()

        post_collateral(parties.facility_id, 1000000, parties.refresh_facility()["version"])

        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
        )
        assert parties.refresh_facility()["collateral_posted_cents"] == 1000000

        ctx = draft_credit(parties)
        submit_credit_for_approval(ctx.credit_id)
        approve_credit(ctx.credit_id, user_id=CREDIT_OFFICER_2)
        assert issue_credit(ctx.credit_id)["status"] == "ISSUED"

        amendment = draft_amendment(ctx, {"amount_cents": 9000000})
        assert_fields_equal(
            amendment, requires_beneficiary_consent=True, exposure_delta_cents=-1000000
        )
        issue_amendment(amendment["id"], user_id=TRADE_FINANCE_OFFICER_2)
        accepted = consent_to_amendment(amendment["id"], parties.beneficiary_id, "ACCEPT")

        assert_fields_equal(accepted, status="ACCEPTED", amendment_fee_cents=7500)
        assert_fields_equal(
            ctx.refresh(),
            status="ISSUED",
            amount_cents=9000000,
            max_drawable_cents=9000000,
            amendment_seq=1,
        )

        pctx = open_presentation(ctx)
        add_invoice(pctx, 4000000)
        add_transport_document(pctx)
        submit_presentation(pctx)
        check = rescreen_presentation(pctx)

        assert_fields_equal(check, result="CLEAR", risk_score=0)

        raise_discrepancy(pctx, "GOODS_DESCRIPTION_MISMATCH", severity="MINOR")
        conclude_examination(pctx)
        waiver = request_waiver(pctx, ["GOODS_DESCRIPTION_MISMATCH"])
        granted = respond_to_waiver(waiver["id"], parties.applicant_id, "GRANT")

        assert granted["status"] == "GRANTED"
        assert_fields_equal(
            pctx.refresh(), examination_status="COMPLYING", discrepancy_count=0
        )

        claim = lodge_claim(pctx, "PAYMENT", 4000000)
        settled = settle_claim(claim["id"])

        assert_fields_equal(
            settled,
            status="SETTLED",
            variant_applied="SIGHT_HONOUR",
            commission_bps_applied=12,
            commission_cents=4800,
            discount_cents=0,
            days_to_maturity=0,
            doc_examination_fee_cents=5500,
            net_proceeds_cents=3989700,
            settled_by_user_id=TRADE_FINANCE_OFFICER_1,
        )
        assert pctx.refresh()["settlement_status"] == "PAID"
        assert_fields_equal(
            ctx.refresh(),
            status="ISSUED",
            reserved_cents=0,
            drawn_settled_cents=4000000,
            available_cents=5000000,
        )

    def test_the_operator_sweeps_and_the_credit_officer_drives_the_facility(self, clock):
        """A no-op sweep, then a manual suspension and the reinstatement it permits.

        PRD 3.9: "Pass four expires credits: every credit whose `presentation_deadline_date` is
        strictly before the clock date, whose `status` is `ISSUED`, and whose `reserved_cents` is
        zero moves to `EXPIRED`, which is terminal, releasing its `OPEN` FacilityAllocation and
        any confirmation occupation it held."

        PRD 3.1: "A manual suspension takes an `ACTIVE` facility to `SUSPENDED` with
        `suspended_reason` set to `MANUAL_SUSPENSION`; note the asymmetry with the automatic path
        — `utilisation_posture` is recomputed from the exposure figures as usual but is **not**
        forced to `RESTRICTED`."

        PRD 3.1: "Reinstatement takes a `SUSPENDED` facility back to `ACTIVE`, clears
        `suspended_reason`, and returns every `ON_HOLD` credit on the facility to `APPROVED` in
        `created_at` ascending order — but it is permitted only when the suspension was manual."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations_end_to_end
        """
        ctx = issued_credit(_parties())

        report = run_sweep(dry_run=True)

        assert_all_sweep_counters_zero(report, SWEEP_COUNTERS)
        assert ctx.refresh()["status"] == "ISSUED"

        suspended = change_facility_status(ctx.parties.facility_id, "SUSPEND")

        assert_facility_ledger(
            suspended,
            allocated_cents=10025000,
            available_cents=39975000,
            status="SUSPENDED",
            utilisation_posture="OPEN",
            suspended_reason="MANUAL_SUSPENSION",
        )

        reinstated = change_facility_status(ctx.parties.facility_id, "REINSTATE")

        assert_facility_ledger(
            reinstated,
            allocated_cents=10025000,
            available_cents=39975000,
            status="ACTIVE",
            utilisation_posture="OPEN",
            suspended_reason=None,
        )
        assert ctx.refresh()["status"] == "ISSUED"
