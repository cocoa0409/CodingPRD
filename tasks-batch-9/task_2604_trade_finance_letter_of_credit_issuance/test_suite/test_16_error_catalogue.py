"""The error catalogue: each guard answers with its own error id and its own status.

Unknown path identifiers resolve to the not-found error of their own entity type; the
uniqueness, clock and facility-reinstatement guards each keep their own status class; the
amendment, presentation, claim, waiver, screening and credit-lifecycle guards are separated
from the neighbouring errors they must not be confused with.
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
    TRADE_FINANCE_OFFICER_2,
    add_invoice,
    add_transport_document,
    api_client,
    assert_end_of_day_instant,
    assert_facility_ledger,
    assert_fields_equal,
    cancel_credit,
    compliance_officer_headers,
    conclude_examination,
    create_applicant,
    create_bank,
    credit_officer_headers,
    document_examiner_headers,
    draft_amendment,
    factories,
    issue_amendment,
    issued_credit,
    list_amendment_rows,
    list_discrepancy_rows,
    list_facility_allocation_rows,
    list_presentation_screening_rows,
    list_waiver_request_rows,
    lodge_claim,
    open_presentation,
    raise_discrepancy,
    request_waiver,
    rescreen_presentation,
    respond_to_waiver,
    set_clock,
    settle_claim,
    setup_parties,
    submitted_presentation,
    system_operator_headers,
    trade_finance_officer_headers,
)

BEFORE_THE_CLOCK = "2026-08-01T09:00:00Z"
THE_DAY_AFTER_THE_CONSENT_DEADLINE = "2026-08-21T09:00:00Z"
THE_DAY_AFTER_THE_WAIVER_DEADLINE = "2026-08-13T09:00:00Z"
AFTER_THE_PRESENTATION_DEADLINE = "2026-11-22T09:00:00Z"
_APPLICANT = {"country_code": "NO"}
_BANK = {"country_code": "NO", "country_risk_score": 12, "credit_rating": "AA"}
_BENEFICIARY = {"country_code": "LV"}


def _parties(limit_cents=50000000, **facility_overrides):
    """The standard NO applicant, its USD facility, a NO advising bank and an LV exporter."""
    facility = {"limit_cents": limit_cents, "collateral_required_pct": 0}
    facility.update(facility_overrides)
    return setup_parties(
        applicant=dict(_APPLICANT),
        facility=facility,
        bank=dict(_BANK),
        beneficiary=dict(_BENEFICIARY),
    )


def _assert_error_envelope(response):
    """An error body carries only the two meta keys and only `error_id` and `message`."""
    body = response.json()
    assert body["response_type"] == "error"
    assert sorted(body["data"]) == ["error_id", "message"]
    assert sorted(body["meta"]) == ["api_request_id", "api_request_timestamp"]


class TestUnknownPathIdsCarryTheirOwnNotFoundError:
    """Six endpoints, one unknown id, six different error ids — never one shared 404."""

    def test_each_endpoint_answers_with_the_error_of_its_own_entity_type(self, clock):
        """The bank, beneficiary, amendment, presentation, claim and check errors stay distinct.

        PRD 2.7: "Each unresolvable reference maps to its own dedicated 404:
        `ERR_APPLICANT_NOT_FOUND` for an applicant path id or an `applicant_id`,
        `ERR_FACILITY_NOT_FOUND` for a facility path id or a `facility_id`,
        `ERR_BANK_NOT_FOUND` for a bank path id or any of `nominated_bank_id`,
        `advising_bank_id`, `confirming_bank_id` and `presenting_bank_id`,
        `ERR_BENEFICIARY_NOT_FOUND` for a beneficiary path id or a `beneficiary_id`,
        `ERR_CREDIT_NOT_FOUND` for a credit path id or a `credit_id`,
        `ERR_AMENDMENT_NOT_FOUND` for an amendment path id, `ERR_PRESENTATION_NOT_FOUND` for a
        presentation path id or a `presentation_id`, `ERR_WAIVER_REQUEST_NOT_FOUND` for a
        waiver-request path id, `ERR_SETTLEMENT_CLAIM_NOT_FOUND` for a settlement-claim path id
        and `ERR_SCREENING_CHECK_NOT_FOUND` for a screening-check path id."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        responses = {
            "ERR_BANK_NOT_FOUND": api_client.get_bank(
                NON_EXISTENT_UUID, credit_officer_headers()
            ),
            "ERR_BENEFICIARY_NOT_FOUND": api_client.get_beneficiary(
                NON_EXISTENT_UUID, trade_finance_officer_headers()
            ),
            "ERR_AMENDMENT_NOT_FOUND": api_client.issue_amendment(
                NON_EXISTENT_UUID,
                factories.amendment_issue_payload(),
                trade_finance_officer_headers(),
            ),
            "ERR_PRESENTATION_NOT_FOUND": api_client.get_presentation(
                NON_EXISTENT_UUID, document_examiner_headers()
            ),
            "ERR_SETTLEMENT_CLAIM_NOT_FOUND": api_client.settle_claim(
                NON_EXISTENT_UUID, factories.settle_payload(), trade_finance_officer_headers()
            ),
            "ERR_SCREENING_CHECK_NOT_FOUND": api_client.review_screening_check(
                NON_EXISTENT_UUID,
                factories.screening_review_payload("RELEASE"),
                compliance_officer_headers(),
            ),
        }

        for error_id, response in responses.items():
            validate_error(response, error_id, 404)
            _assert_error_envelope(response)
        assert len(set(response.json()["data"]["error_id"] for response in responses.values())) == 6


class TestTheUniquenessClockAndReinstateGuardsKeepTheirOwnStatus:
    """A duplicate is 409, a clock rewind is 422, and a breached facility stays suspended."""

    def test_a_second_bank_with_the_same_bic_is_a_duplicate_not_a_validation_error(self, clock):
        """409 `ERR_DUPLICATE_KEY`, and the directory still holds exactly one bank.

        PRD 3.1: "A bank carries a `bank_name` of 1 to 200 non-blank characters, a `swift_bic`
        of either 8 or 11 uppercase alphanumeric characters which must be unique across all
        banks (a duplicate is refused with `ERR_DUPLICATE_KEY`, 409), a `country_code` of
        exactly two uppercase letters, a `country_risk_score` between 0 and 100 inclusive where
        higher means riskier, an external `credit_rating` drawn from `AA`, `A`, `BBB` and `BB`,
        a `confirmation_appetite_cents` of at least zero representing the maximum peak
        concurrent confirmed exposure the bank will carry, and an optional `sanctions_flag`
        defaulting to false."

        Design: Corner/errors/uniqueness_clock_and_facility_reinstate_guards_are_rejected
        """
        first = create_bank(
            bank_name="Nordkyst Bank",
            swift_bic="NDKBNOKK",
            country_code="NO",
            country_risk_score=12,
            credit_rating="AA",
            confirmation_appetite_cents=90000000,
        )

        response = api_client.create_bank(
            factories.bank_payload(
                bank_name="Nordkyst Bank Oslo Branch", swift_bic="NDKBNOKK", country_code="NO"
            ),
            credit_officer_headers(),
        )

        validate_error(response, "ERR_DUPLICATE_KEY", 409)
        _assert_error_envelope(response)
        rows, meta = validate_paginated(api_client.list_banks(credit_officer_headers()))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first["id"]]
        assert [row["swift_bic"] for row in rows] == ["NDKBNOKK"]

    def test_rewinding_the_clock_is_refused_and_the_clock_does_not_move(self, clock):
        """422 `ERR_CLOCK_REGRESSION`, and the next write is still stamped 2026-08-10.

        PRD 3.10: "Setting the clock mutates no entity at all — deadlines are re-evaluated only
        when a sweep or an ordinary write runs — and an instant earlier than the current logical
        clock is refused with `ERR_CLOCK_REGRESSION` (422)."

        Design: Corner/errors/uniqueness_clock_and_facility_reinstate_guards_are_rejected
        """
        response = api_client.set_clock(
            factories.clock_payload(BEFORE_THE_CLOCK), system_operator_headers()
        )

        validate_error(response, "ERR_CLOCK_REGRESSION", 422)
        _assert_error_envelope(response)
        applicant = create_applicant(legal_name="Baltic Timber Imports AS", country_code="NO")
        assert applicant["created_at"] == "2026-08-10T09:00:00.000Z"

    def test_a_threshold_breached_facility_cannot_be_talked_back_into_life(self, clock):
        """19,050,000 against a 19,000,000 threshold: `REINSTATE` is 409, not a state change.

        PRD 3.1: "When a recomputation leaves `allocated_cents` at or above
        `restrict_threshold_cents` on a facility that was `ACTIVE`, the facility moves
        `ACTIVE → SUSPENDED` with `suspended_reason` set to `RESTRICT_THRESHOLD_BREACH` and
        `utilisation_posture` set to `RESTRICTED`, its `version` increments, and every credit
        sitting on that facility in status `APPROVED` is moved to `ON_HOLD`, processed in
        `created_at` ascending order, each such credit's `version` incrementing by one."

        PRD 3.1: "A facility suspended for a threshold breach cannot be talked back into life:
        while `allocated_cents` remains at or above `restrict_threshold_cents` the request is
        rejected with `ERR_FACILITY_STILL_RESTRICTED` (409), because a threshold breach is
        cleared only by releasing exposure."

        Design: Corner/errors/uniqueness_clock_and_facility_reinstate_guards_are_rejected
        """
        parties = _parties(limit_cents=20000000)
        issued_credit(parties, amount_cents=9500000)
        issued_credit(parties, amount_cents=9500000)
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=19050000,
            available_cents=950000,
            restrict_threshold_cents=19000000,
            status="SUSPENDED",
            utilisation_posture="RESTRICTED",
            suspended_reason="RESTRICT_THRESHOLD_BREACH",
        )

        response = api_client.create_facility_status_change(
            parties.facility_id,
            factories.facility_status_change_payload(
                "REINSTATE", reason="applicant asked for the line back"
            ),
            credit_officer_headers(),
        )

        validate_error(response, "ERR_FACILITY_STILL_RESTRICTED", 409)
        _assert_error_envelope(response)
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=19050000,
            status="SUSPENDED",
            utilisation_posture="RESTRICTED",
            suspended_reason="RESTRICT_THRESHOLD_BREACH",
        )


class TestTheAmendmentLifecycleGuardsRefuseOutOfOrderCalls:
    """Four amendment errors, each pinned to its own reason for refusing the same two calls."""

    @staticmethod
    def _issued_credit():
        """The standard 10,000,000 sight credit, `ISSUED` on a 50,000,000 facility."""
        return issued_credit(_parties())

    def test_a_change_set_that_only_restates_the_current_amount_creates_nothing(self, clock):
        """422 `ERR_EMPTY_CHANGE_SET`, and the credit still carries no amendment at all.

        PRD 3.5: "Before the set is judged, every key whose new value equals the credit's
        current value is discarded as a no-op; if the surviving set is empty, or if any key
        names a field outside the amendable set, the draft is refused with
        `ERR_EMPTY_CHANGE_SET` (422)."

        Design: Corner/errors/amendment_lifecycle_guards_reject_out_of_order_calls
        """
        ctx = self._issued_credit()

        response = api_client.create_amendment(
            ctx.credit_id,
            factories.amendment_payload({"amount_cents": 10000000}, ctx.refresh()["version"]),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_EMPTY_CHANGE_SET", 422)
        _assert_error_envelope(response)
        rows, meta = validate_paginated(
            api_client.list_credit_amendments(ctx.credit_id, trade_finance_officer_headers())
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert_fields_equal(ctx.refresh(), status="ISSUED", amount_cents=10000000)

    def test_consent_on_a_draft_amendment_is_the_not_pending_consent_error(self, clock):
        """409 `ERR_AMENDMENT_NOT_PENDING_CONSENT` — the row exists, it is simply too early.

        PRD 3.5: "The amendment's `status` must be `PENDING_CONSENT`, else
        `ERR_AMENDMENT_NOT_PENDING_CONSENT` (409)."

        PRD 3.5: "`exposure_delta_cents` is the committed-issuance exposure of the credit as it
        would stand after applying the `change_set`, minus the credit's current
        `committed_allocation_cents`."

        Design: Corner/errors/amendment_lifecycle_guards_reject_out_of_order_calls
        """
        ctx = self._issued_credit()
        amendment = draft_amendment(ctx, {"amount_cents": 9000000})
        assert_fields_equal(
            amendment,
            status="DRAFT",
            seq=1,
            requires_beneficiary_consent=True,
            exposure_delta_cents=-1000000,
        )
        assert amendment["consent_window_start"] is None

        response = api_client.consent_amendment(
            amendment["id"], factories.consent_payload("ACCEPT"), ctx.parties.beneficiary_headers
        )

        validate_error(response, "ERR_AMENDMENT_NOT_PENDING_CONSENT", 409)
        _assert_error_envelope(response)
        rows = list_amendment_rows(ctx.credit_id)
        assert len(rows) == 1
        assert_fields_equal(rows[0], status="DRAFT", version=amendment["version"])

    def test_issuing_the_same_amendment_twice_is_the_not_draft_error(self, clock):
        """409 `ERR_AMENDMENT_NOT_DRAFT` — a different error from the consent guard.

        PRD 3.5: "The amendment's `status` must be `DRAFT`, else `ERR_AMENDMENT_NOT_DRAFT`
        (409), and the credit must still be `ISSUED` or `AMENDMENT_PENDING`, else
        `ERR_CREDIT_NOT_ISSUED` (409)."

        PRD 3.5: "On both branches, and before the branch is taken, the amendment acquires its
        window: `consent_window_start` is set to the clock date, `consent_deadline_date` to the
        clock date plus ten days, and `window_end_effective` to `consent_deadline_date`."

        Design: Corner/errors/amendment_lifecycle_guards_reject_out_of_order_calls
        """
        ctx = self._issued_credit()
        amendment = draft_amendment(ctx, {"amount_cents": 9000000})
        issued = issue_amendment(amendment["id"])
        assert_fields_equal(
            issued,
            status="PENDING_CONSENT",
            consent_window_start="2026-08-10",
            consent_deadline_date="2026-08-20",
            window_end_effective="2026-08-20",
            issued_by_user_id=TRADE_FINANCE_OFFICER_2,
        )

        response = api_client.issue_amendment(
            amendment["id"],
            factories.amendment_issue_payload(),
            trade_finance_officer_headers(TRADE_FINANCE_OFFICER_2),
        )

        validate_error(response, "ERR_AMENDMENT_NOT_DRAFT", 409)
        _assert_error_envelope(response)
        rows = list_amendment_rows(ctx.credit_id)
        assert_fields_equal(rows[0], status="PENDING_CONSENT", version=issued["version"])
        assert ctx.refresh()["status"] == "AMENDMENT_PENDING"

    def test_consent_one_day_past_the_deadline_is_the_window_error_not_a_lapse(self, clock):
        """409 `ERR_CONSENT_WINDOW_CLOSED`, and the row stays `PENDING_CONSENT` and unresolved.

        PRD 3.5: "The clock date must be on or before `consent_deadline_date` — the interval is
        closed, so a response landing exactly on the deadline date is in time — and a later
        response is refused with `ERR_CONSENT_WINDOW_CLOSED` (409)."

        PRD 3.5: "When `requires_beneficiary_consent` is true, the amendment traverses
        `DRAFT → ISSUED → PENDING_CONSENT`, `window_end_effective` stays at
        `consent_deadline_date`, the credit moves `ISSUED → AMENDMENT_PENDING`, and the
        `change_set` is **not** applied."

        Design: Corner/errors/amendment_lifecycle_guards_reject_out_of_order_calls
        """
        ctx = self._issued_credit()
        amendment = draft_amendment(ctx, {"amount_cents": 9000000})
        issue_amendment(amendment["id"])
        set_clock(THE_DAY_AFTER_THE_CONSENT_DEADLINE)

        response = api_client.consent_amendment(
            amendment["id"], factories.consent_payload("ACCEPT"), ctx.parties.beneficiary_headers
        )

        validate_error(response, "ERR_CONSENT_WINDOW_CLOSED", 409)
        _assert_error_envelope(response)
        row = list_amendment_rows(ctx.credit_id)[0]
        assert_fields_equal(
            row, status="PENDING_CONSENT", resolved_at=None, window_end_effective="2026-08-20"
        )
        assert_fields_equal(ctx.refresh(), status="AMENDMENT_PENDING", amount_cents=10000000)


class TestThePresentationAndClaimGuardsCarryDistinctErrors:
    """Six guards from tender to settlement, each separated from its nearest neighbour."""

    @staticmethod
    def _issued_credit():
        """A 10,000,000 sight credit whose mandatory set is one invoice and one bill of lading."""
        return issued_credit(_parties())

    def test_a_file_missing_the_mandatory_transport_document_is_incomplete(self, clock):
        """422 `ERR_PRESENTATION_INCOMPLETE` — the documents never reach examination at all.

        PRD 3.6: "The file must carry at least one document, and every mandatory
        `DocumentaryRequirement` of the credit must be answered by at least one document of the
        matching `doc_type` whose `originals_presented` is at least the requirement's
        `originals_required`; a file with no documents or an unanswered mandatory requirement is
        refused with `ERR_PRESENTATION_INCOMPLETE` (422)."

        Design: Corner/errors/presentation_and_claim_guards_are_rejected_with_distinct_errors
        """
        ctx = self._issued_credit()
        pctx = open_presentation(ctx)
        add_invoice(pctx, 2000000)

        response = api_client.submit_presentation(
            pctx.presentation_id, factories.submit_presentation_payload(), pctx.bank_headers
        )

        validate_error(response, "ERR_PRESENTATION_INCOMPLETE", 422)
        _assert_error_envelope(response)
        assert_fields_equal(
            pctx.refresh(),
            examination_status="RECEIVED",
            document_count=1,
            drawn_amount_cents=0,
            submitted_at=None,
            examination_deadline=None,
        )
        assert list_discrepancy_rows(pctx.presentation_id) == []

    def test_a_tender_above_the_credit_ceiling_is_the_drawable_error(self, clock):
        """422 `ERR_CREDIT_DRAWABLE_EXCEEDED`, not the facility's own limit error.

        PRD 3.6: "That frozen drawn amount must be less than or equal to the credit's
        `available_cents`; exact equality is admitted, and only a strict excess is refused, with
        `ERR_CREDIT_DRAWABLE_EXCEEDED` (422)."

        Design: Corner/errors/presentation_and_claim_guards_are_rejected_with_distinct_errors
        """
        ctx = self._issued_credit()
        pctx = open_presentation(ctx)
        add_invoice(pctx, 10500000)
        add_transport_document(pctx)

        response = api_client.submit_presentation(
            pctx.presentation_id, factories.submit_presentation_payload(), pctx.bank_headers
        )

        validate_error(response, "ERR_CREDIT_DRAWABLE_EXCEEDED", 422)
        _assert_error_envelope(response)
        assert_fields_equal(
            pctx.refresh(), examination_status="RECEIVED", drawn_amount_cents=0, submitted_at=None
        )
        assert_fields_equal(
            ctx.refresh(),
            max_drawable_cents=10000000,
            reserved_cents=0,
            available_cents=10000000,
        )

    def test_claiming_too_early_and_claiming_one_cent_short_are_different_errors(self, clock):
        """409 while `UNDER_EXAMINATION`, then 422 for 3,999,999 against a frozen 4,000,000.

        PRD 3.9: "Anything else is refused with `ERR_PRESENTATION_NOT_COMPLYING` (409)."

        PRD 3.9: "`claimed_amount_cents` must equal the presentation's frozen
        `drawn_amount_cents` exactly — no partial claim and no over-claim — else
        `ERR_CLAIM_AMOUNT_MISMATCH` (422)."

        Design: Corner/errors/presentation_and_claim_guards_are_rejected_with_distinct_errors
        """
        ctx = self._issued_credit()
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        assert_fields_equal(
            pctx.refresh(), examination_status="UNDER_EXAMINATION", drawn_amount_cents=4000000
        )

        too_early = api_client.create_settlement_claim(
            pctx.presentation_id,
            factories.settlement_claim_payload("PAYMENT", 4000000),
            pctx.bank_headers,
        )
        validate_error(too_early, "ERR_PRESENTATION_NOT_COMPLYING", 409)

        assert_fields_equal(
            conclude_examination(pctx), examination_status="COMPLYING", discrepancy_count=0
        )
        one_cent_short = api_client.create_settlement_claim(
            pctx.presentation_id,
            factories.settlement_claim_payload("PAYMENT", 3999999),
            pctx.bank_headers,
        )

        validate_error(one_cent_short, "ERR_CLAIM_AMOUNT_MISMATCH", 422)
        _assert_error_envelope(one_cent_short)
        _rows, meta = validate_paginated(
            api_client.list_settlement_claims(
                pctx.presentation_id, trade_finance_officer_headers()
            )
        )
        assert meta["total_count"] == 0
        assert pctx.refresh()["settlement_status"] == "UNSETTLED"

    def test_a_second_claim_while_the_first_is_lodged_is_refused(self, clock):
        """409 `ERR_LIVE_REQUEST_EXISTS`, and the presentation still carries exactly one claim.

        PRD 3.9: "At most one claim per presentation may be live, so a second attempt while one
        is `LODGED` is refused with `ERR_LIVE_REQUEST_EXISTS` (409)."

        PRD 3.9: "Lodging sets the claim's `status` to `LODGED`, derives `variant_applied` from
        `claim_type` and the credit's `available_by`, and moves the presentation's
        `settlement_status` `UNSETTLED → CLAIM_LODGED`."

        Design: Corner/errors/presentation_and_claim_guards_are_rejected_with_distinct_errors
        """
        ctx = self._issued_credit()
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        conclude_examination(pctx)
        claim = lodge_claim(pctx, "PAYMENT", 4000000)
        assert_fields_equal(
            claim, status="LODGED", variant_applied="SIGHT_HONOUR", claimed_amount_cents=4000000
        )
        assert pctx.refresh()["settlement_status"] == "CLAIM_LODGED"

        response = api_client.create_settlement_claim(
            pctx.presentation_id,
            factories.settlement_claim_payload("PAYMENT", 4000000),
            pctx.bank_headers,
        )

        validate_error(response, "ERR_LIVE_REQUEST_EXISTS", 409)
        _assert_error_envelope(response)
        rows, meta = validate_paginated(
            api_client.list_settlement_claims(
                pctx.presentation_id, trade_finance_officer_headers()
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [claim["id"]]

    def test_settling_the_same_claim_twice_is_refused_rather_than_idempotent(self, clock):
        """The waterfall is written once; the second settle is 409 `ERR_CLAIM_NOT_LODGED`.

        PRD 3.9: "The claim must be `LODGED`, else `ERR_CLAIM_NOT_LODGED` (409), and the
        presentation must be at `CLAIM_LODGED`."

        PRD 3.9: "Step four deducts the charges from the drawn amount in the fixed order
        commission, then discount, then document fees: `net_proceeds_cents` is
        `drawn_amount_cents` minus `commission_cents` minus `discount_cents` minus
        `doc_examination_fee_cents`."

        Design: Corner/errors/presentation_and_claim_guards_are_rejected_with_distinct_errors
        """
        ctx = self._issued_credit()
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        conclude_examination(pctx)
        claim = lodge_claim(pctx, "PAYMENT", 4000000)
        settled = settle_claim(claim["id"])
        assert_fields_equal(
            settled,
            status="SETTLED",
            variant_applied="SIGHT_HONOUR",
            commission_bps_applied=12,
            commission_cents=4800,
            discount_cents=0,
            doc_examination_fee_cents=5500,
            days_to_maturity=0,
            net_proceeds_cents=3989700,
            settled_at="2026-08-10T09:00:00.000Z",
        )
        assert pctx.refresh()["settlement_status"] == "PAID"

        response = api_client.settle_claim(
            claim["id"], factories.settle_payload(), trade_finance_officer_headers()
        )

        validate_error(response, "ERR_CLAIM_NOT_LODGED", 409)
        _assert_error_envelope(response)
        rows, _meta = validate_paginated(
            api_client.list_settlement_claims(
                pctx.presentation_id, trade_finance_officer_headers()
            )
        )
        assert_fields_equal(
            rows[0],
            status="SETTLED",
            settled_at=settled["settled_at"],
            version=settled["version"],
            net_proceeds_cents=3989700,
        )
        assert pctx.refresh()["settlement_status"] == "PAID"


class TestTheWaiverAndScreeningGuardsCarryDistinctErrors:
    """Five errors around the discrepancy-waiver loop, each with its own status and scope."""

    @staticmethod
    def _under_examination():
        """A clean 4,000,000 tender submitted on Monday 2026-08-10, so examination runs to 08-17."""
        ctx = issued_credit(_parties())
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        return ctx, pctx

    @staticmethod
    def _two_minor_defects(pctx):
        """Two waivable defects, so a waiver can cite one and leave the other outstanding."""
        raise_discrepancy(pctx, "GOODS_DESCRIPTION_MISMATCH", severity="MINOR")
        raise_discrepancy(pctx, "INCOTERM_MISMATCH", severity="MINOR")
        return conclude_examination(pctx)

    def test_reviewing_a_clear_check_is_refused_rather_than_silently_ignored(self, clock):
        """409 `ERR_SCREENING_NOT_REVIEWABLE`, and the check keeps its result and its version.

        PRD 3.8: "Only a check at `HIT_PENDING_REVIEW` is reviewable; any other `result` gives
        `ERR_SCREENING_NOT_REVIEWABLE` (409)."

        PRD 3.8: "The `result` follows from the score against two inclusive lower bounds: a
        score of 100 or more gives `BLOCKED`, a score of 40 or more but below 100 gives
        `HIT_PENDING_REVIEW`, and anything below 40 gives `CLEAR`."

        Design: Corner/errors/waiver_and_screening_guards_are_rejected_with_distinct_errors
        """
        ctx, pctx = self._under_examination()
        check = rescreen_presentation(pctx)
        assert_fields_equal(
            check,
            scope="PRESENTED_DOCUMENTS",
            presentation_id=pctx.presentation_id,
            credit_id=ctx.credit_id,
            result="CLEAR",
            risk_score=0,
            country_hits=0,
            dual_use_hits=0,
            keyword_hits=0,
            transit_hits=0,
            screened_by_user_id=COMPLIANCE_OFFICER_1,
            reviewed_by_user_id=None,
        )

        response = api_client.review_screening_check(
            check["id"],
            factories.screening_review_payload("RELEASE"),
            compliance_officer_headers(COMPLIANCE_OFFICER_2),
        )

        validate_error(response, "ERR_SCREENING_NOT_REVIEWABLE", 409)
        _assert_error_envelope(response)
        stored = [
            row
            for row in list_presentation_screening_rows(pctx.presentation_id)
            if row["id"] == check["id"]
        ][0]
        assert_fields_equal(
            stored,
            result="CLEAR",
            reviewed_by_user_id=None,
            reviewed_at=None,
            version=check["version"],
        )

    def test_a_waiver_naming_a_defect_that_was_never_raised_is_refused(self, clock):
        """422 `ERR_DISCREPANCY_CODE_UNKNOWN`, and no waiver request is created at all.

        PRD 3.7: "Every element must match a Discrepancy of this presentation whose `status` is
        `IDENTIFIED` **and** whose `severity` is `MINOR`; a `MATERIAL` defect cannot be waived by
        the applicant at all, and citing one, or citing a code that is not an identified
        discrepancy of this presentation, is refused with `ERR_DISCREPANCY_CODE_UNKNOWN` (422)."

        Design: Corner/errors/waiver_and_screening_guards_are_rejected_with_distinct_errors
        """
        _ctx, pctx = self._under_examination()
        assert_fields_equal(
            self._two_minor_defects(pctx), examination_status="DISCREPANT", discrepancy_count=2
        )

        response = api_client.create_waiver_request(
            pctx.presentation_id,
            factories.waiver_request_payload(["TRANSHIPMENT_NOT_ALLOWED"]),
            document_examiner_headers(),
        )

        validate_error(response, "ERR_DISCREPANCY_CODE_UNKNOWN", 422)
        _assert_error_envelope(response)
        assert list_waiver_request_rows(pctx.presentation_id) == []
        assert sorted(row["code"] for row in list_discrepancy_rows(pctx.presentation_id)) == [
            "GOODS_DESCRIPTION_MISMATCH",
            "INCOTERM_MISMATCH",
        ]
        assert_fields_equal(
            pctx.refresh(), examination_status="DISCREPANT", refusal_notice_sent_at=None
        )

    def test_a_pending_waiver_bars_refusal_and_a_second_answer(self, clock):
        """The specific 409 for a live waiver, then the specific 409 for an answered one.

        PRD 3.7: "No waiver request may still be `PENDING`; because a pending waiver leaves the
        presentation in `WAIVER_REQUESTED`, that situation returns the specific
        `ERR_WAIVER_RESPONSE_PENDING` (409) rather than the generic state error."

        PRD 3.7: "`DENY` moves the request `PENDING → DENIED`, moves every cited Discrepancy
        `IDENTIFIED → UPHELD`, leaves `discrepancy_count` unchanged because upheld rows still
        count, and returns the presentation `WAIVER_REQUESTED → DISCREPANT`."

        Design: Corner/errors/waiver_and_screening_guards_are_rejected_with_distinct_errors
        """
        ctx, pctx = self._under_examination()
        self._two_minor_defects(pctx)
        waiver = request_waiver(pctx, ["GOODS_DESCRIPTION_MISMATCH"])
        assert_fields_equal(
            waiver,
            status="PENDING",
            discrepancy_codes=["GOODS_DESCRIPTION_MISMATCH"],
            requested_at="2026-08-10T09:00:00.000Z",
            responded_at=None,
        )
        assert_end_of_day_instant(waiver["deadline_at"], "2026-08-12", "the waiver window")
        assert pctx.refresh()["examination_status"] == "WAIVER_REQUESTED"

        refusal = api_client.refuse_presentation(
            pctx.presentation_id,
            factories.refusal_payload("RETURN_TO_PRESENTER"),
            document_examiner_headers(),
        )

        validate_error(refusal, "ERR_WAIVER_RESPONSE_PENDING", 409)
        _assert_error_envelope(refusal)
        assert_fields_equal(
            pctx.refresh(), examination_status="WAIVER_REQUESTED", refusal_notice_sent_at=None
        )

        denied = respond_to_waiver(waiver["id"], ctx.parties.applicant_id, "DENY")
        assert_fields_equal(
            denied, status="DENIED", responded_at="2026-08-10T09:00:00.000Z"
        )
        assert {
            row["code"]: row["status"] for row in list_discrepancy_rows(pctx.presentation_id)
        } == {"GOODS_DESCRIPTION_MISMATCH": "UPHELD", "INCOTERM_MISMATCH": "IDENTIFIED"}
        assert_fields_equal(
            pctx.refresh(), examination_status="DISCREPANT", discrepancy_count=2
        )

        second_answer = api_client.respond_to_waiver_request(
            waiver["id"],
            factories.waiver_response_payload("GRANT"),
            ctx.parties.applicant_headers,
        )

        validate_error(second_answer, "ERR_WAIVER_NOT_PENDING", 409)
        stored = [
            row
            for row in list_waiver_request_rows(pctx.presentation_id)
            if row["id"] == waiver["id"]
        ][0]
        assert_fields_equal(
            stored,
            status="DENIED",
            responded_at=denied["responded_at"],
            version=denied["version"],
        )

    def test_answering_one_day_past_the_two_day_window_is_the_window_error(self, clock):
        """409 `ERR_WAIVER_WINDOW_CLOSED`, and only the sweep may ever move the row to `EXPIRED`.

        PRD 3.7: "Its own `deadline_at` is the **earlier** of two instants: the date part of
        `requested_at` plus two days at `23:59:59.999Z`, and the presentation's
        `examination_deadline`."

        PRD 3.7: "The request must be `PENDING`, else `ERR_WAIVER_NOT_PENDING` (409), and the
        clock instant must be at or before `deadline_at` — that instant included — else
        `ERR_WAIVER_WINDOW_CLOSED` (409), in which case the request must instead be swept to
        `EXPIRED`."

        Design: Corner/errors/waiver_and_screening_guards_are_rejected_with_distinct_errors
        """
        ctx, pctx = self._under_examination()
        self._two_minor_defects(pctx)
        waiver = request_waiver(pctx, ["INCOTERM_MISMATCH"])
        assert_end_of_day_instant(waiver["deadline_at"], "2026-08-12", "the waiver window")
        assert_end_of_day_instant(
            pctx.refresh()["examination_deadline"], "2026-08-17", "the examination period"
        )
        set_clock(THE_DAY_AFTER_THE_WAIVER_DEADLINE)

        response = api_client.respond_to_waiver_request(
            waiver["id"],
            factories.waiver_response_payload("GRANT"),
            ctx.parties.applicant_headers,
        )

        validate_error(response, "ERR_WAIVER_WINDOW_CLOSED", 409)
        _assert_error_envelope(response)
        stored = list_waiver_request_rows(pctx.presentation_id)[0]
        assert_fields_equal(
            stored, status="PENDING", responded_at=None, version=waiver["version"]
        )
        assert {
            row["code"]: row["status"] for row in list_discrepancy_rows(pctx.presentation_id)
        } == {"GOODS_DESCRIPTION_MISMATCH": "IDENTIFIED", "INCOTERM_MISMATCH": "IDENTIFIED"}
        assert pctx.refresh()["examination_status"] == "WAIVER_REQUESTED"


class TestTheCreditLifecycleGuardsCarryDistinctErrors:
    """Four guards on the credit's own life, each aimed at a different credit."""

    def test_cancelling_an_issued_credit_needs_the_consent_reference(self, clock):
        """422 without the reference, then the same call with it releases the allocation.

        PRD 3.3: "Cancelling an `ISSUED` credit is different, because an irrevocable undertaking
        cannot be withdrawn unilaterally: the request must carry a present and non-blank
        `beneficiary_consent_reference`, else it is refused with
        `ERR_BENEFICIARY_CONSENT_REQUIRED` (422)."

        PRD 3.3: "Every `OPEN` allocation row of the credit flips to `RELEASED` with
        `released_cents` set to that row's own `allocated_cents` plus its `charge_cents` and
        `released_at` set to the clock instant, and the row's `version` increments."

        Design: Corner/errors/credit_lifecycle_guards_are_rejected_with_distinct_errors
        """
        ctx = issued_credit(_parties())

        response = api_client.cancel_credit(
            ctx.credit_id, factories.cancel_payload(), trade_finance_officer_headers()
        )

        validate_error(response, "ERR_BENEFICIARY_CONSENT_REQUIRED", 422)
        _assert_error_envelope(response)
        assert ctx.refresh()["status"] == "ISSUED"

        cancelled = cancel_credit(
            ctx.credit_id, beneficiary_consent_reference="BEN-CONSENT-2026-0007"
        )

        assert cancelled["status"] == "CANCELLED"
        rows = list_facility_allocation_rows(ctx.parties.facility_id)
        assert len(rows) == 1
        assert_fields_equal(rows[0], status="RELEASED", released_cents=10025000)
        assert_facility_ledger(
            ctx.parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )

    def test_a_credit_carrying_a_live_presentation_may_not_be_cancelled(self, clock):
        """409 `ERR_CREDIT_HAS_LIVE_PRESENTATION` even though the consent reference is present.

        PRD 3.3: "It must also find the credit clean of drawings — every presentation on the
        credit must have `examination_status` `REFUSED` or a `settlement_status` among `VOID`,
        `PAID`, `NEGOTIATED` and `REIMBURSED`, and the credit's own `reserved_cents` and
        `drawn_settled_cents` must both be zero — failing which the request is refused with
        `ERR_CREDIT_HAS_LIVE_PRESENTATION` (409)."

        Design: Corner/errors/credit_lifecycle_guards_are_rejected_with_distinct_errors
        """
        ctx = issued_credit(_parties())
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))

        response = api_client.cancel_credit(
            ctx.credit_id,
            factories.cancel_payload(beneficiary_consent_reference="BEN-CONSENT-2026-0008"),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_CREDIT_HAS_LIVE_PRESENTATION", 409)
        _assert_error_envelope(response)
        assert_fields_equal(
            ctx.refresh(), status="ISSUED", reserved_cents=4000000, drawn_settled_cents=0
        )
        assert pctx.refresh()["examination_status"] == "UNDER_EXAMINATION"
        assert [row["status"] for row in list_facility_allocation_rows(ctx.parties.facility_id)] == [
            "OPEN"
        ]

    def test_a_suspended_advising_bank_is_caught_at_drafting_not_at_issuance(self, clock):
        """422 `ERR_ADVISING_BANK_INELIGIBLE` from `POST /credits`, and no credit row is created.

        PRD 3.2: "An advising bank whose `status` is not `ACTIVE`, or which carries
        `sanctions_flag` true, yields `ERR_ADVISING_BANK_INELIGIBLE` (422)."

        Design: Corner/errors/credit_lifecycle_guards_are_rejected_with_distinct_errors
        """
        parties = _parties()
        coastline = create_bank(
            bank_name="Coastline Trade Bank",
            swift_bic="CLTBSEXX",
            country_code="SE",
            country_risk_score=20,
            credit_rating="A",
            confirmation_appetite_cents=50000000,
        )
        patched = validate_success(
            api_client.patch_bank(
                coastline["id"], {"status": "SUSPENDED"}, credit_officer_headers()
            )
        )
        assert patched["status"] == "SUSPENDED"

        response = api_client.create_credit(
            factories.credit_payload(
                parties.applicant_id,
                parties.beneficiary_id,
                parties.facility_id,
                coastline["id"],
            ),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_ADVISING_BANK_INELIGIBLE", 422)
        _assert_error_envelope(response)
        _rows, meta = validate_paginated(
            api_client.list_credits(trade_finance_officer_headers())
        )
        assert meta["total_count"] == 0

    def test_submitting_after_the_presentation_deadline_is_barred(self, clock):
        """2026-11-21 binds, not the 2026-11-30 expiry, so a 2026-11-22 tender is 422.

        PRD 3.3: "The `presentation_deadline_date` is re-derived as the earlier of `expiry_date`
        and `latest_shipment_date` advanced by `presentation_period_days` days, inclusive."

        PRD 3.6: "The clock date must be on or before the credit's
        `presentation_deadline_date`, that date itself included, else
        `ERR_PRESENTATION_WINDOW_CLOSED` (422)."

        Design: Corner/errors/credit_lifecycle_guards_are_rejected_with_distinct_errors
        """
        ctx = issued_credit(_parties())
        assert_fields_equal(
            ctx.refresh(), presentation_deadline_date="2026-11-21", expiry_date="2026-11-30"
        )
        pctx = open_presentation(ctx)
        add_invoice(pctx, 4000000)
        add_transport_document(pctx)
        set_clock(AFTER_THE_PRESENTATION_DEADLINE)

        response = api_client.submit_presentation(
            pctx.presentation_id, factories.submit_presentation_payload(), pctx.bank_headers
        )

        validate_error(response, "ERR_PRESENTATION_WINDOW_CLOSED", 422)
        _assert_error_envelope(response)
        assert_fields_equal(
            pctx.refresh(),
            examination_status="RECEIVED",
            submitted_at=None,
            examination_deadline=None,
            drawn_amount_cents=0,
        )
        assert_fields_equal(ctx.refresh(), status="ISSUED", reserved_cents=0)
