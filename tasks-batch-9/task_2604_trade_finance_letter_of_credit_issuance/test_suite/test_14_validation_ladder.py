"""The validation ladder: referential, temporal, conditional and aggregate rungs.

A credit pointed at a stranger's facility, a shipment date that outlives its own expiry, the
fully compliant credit that must walk every rung and land `ISSUED`, the pair of credits that
each fit but together do not, the insurance certificate that only `CIF` demands, the
examination that has to wait for compliance to adjudicate, and the bank that exists but was
never nominated.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    add_requirement,
    api_client,
    approve_credit,
    approved_credit,
    assert_credit_drawing_ledger,
    assert_facility_ledger,
    assert_fields_equal,
    assert_issuance_charges,
    assert_screening_outcome,
    conclude_examination,
    create_applicant,
    create_bank,
    create_facility,
    credit_officer_headers,
    document_examiner_headers,
    draft_credit,
    factories,
    issue_credit,
    issued_credit,
    list_facility_allocation_rows,
    make_correspondent_bank_headers,
    newest_presentation_screening,
    open_presentation,
    review_screening,
    set_clock,
    setup_parties,
    submit_credit_for_approval,
    submitted_presentation,
    trade_finance_officer_headers,
)

MONDAY_14 = "2026-09-14T09:00:00Z"

# A Norwegian applicant and advising bank against a Latvian beneficiary: no party sits in a
# sanctioned country, so nothing in these scenarios is decided by the sanctions rungs.
_APPLICANT = {"country_code": "NO"}
_BANK = {"country_code": "NO", "country_risk_score": 12, "credit_rating": "AA"}
_BENEFICIARY = {"country_code": "LV"}


def _parties(limit_cents=50000000, applicant=None, **facility_overrides):
    facility = {"limit_cents": limit_cents, "collateral_required_pct": 0}
    facility.update(facility_overrides)
    return setup_parties(
        applicant=dict(_APPLICANT if applicant is None else applicant),
        facility=facility,
        bank=dict(_BANK),
        beneficiary=dict(_BENEFICIARY),
    )


def _read_facility(facility_id):
    return validate_success(api_client.get_facility(facility_id, credit_officer_headers()))


def _list_credits(**params):
    return validate_paginated(
        api_client.list_credits(trade_finance_officer_headers(), params or None)
    )


def _list_requirements(credit_id):
    return validate_paginated(
        api_client.list_documentary_requirements(credit_id, trade_finance_officer_headers())
    )


class TestACreditMaySitOnlyOnItsOwnApplicantsFacility:
    """Both ids exist, so only the referential rung can catch the pairing."""

    def test_naming_another_applicants_facility_is_a_referential_refusal(self, clock):
        """Applicant A1 with facility FA2 is refused, and FA2 is left completely untouched.

        The facility id resolves to a real, `ACTIVE`, same-currency row with the whole
        50,000,000 free, so nothing but the applicant-to-facility relationship can decide
        this request.

        PRD 3.2: "The named facility must belong to the named applicant and be denominated in
        the credit's own `currency`, failing which the draft is refused with
        `ERR_FACILITY_APPLICANT_MISMATCH` (422)"

        Design: Corner/validations/credit_on_another_applicants_facility_is_rejected
        """
        parties = _parties(applicant={"country_code": "NO", "legal_name": "Baltic Timber Imports AS"})
        stranger = create_applicant(country_code="FI", legal_name="Suomi Puutuote Oy")
        other_facility = create_facility(
            stranger["id"], limit_cents=50000000, collateral_required_pct=0
        )

        response = api_client.create_credit(
            factories.credit_payload(
                parties.applicant_id,
                parties.beneficiary_id,
                other_facility["id"],
                parties.advising_bank_id,
            ),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_FACILITY_APPLICANT_MISMATCH", 422)
        _rows, meta = _list_credits(applicant_id=parties.applicant_id)
        assert meta["total_count"] == 0
        assert_facility_ledger(
            _read_facility(other_facility["id"]),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )
        assert list_facility_allocation_rows(other_facility["id"]) == []


class TestAShipmentDateMayNotOutliveTheExpiryDate:
    """The impossible credit is refused outright rather than stored and papered over.

    A `latest_shipment_date` of 2026-12-15 against an `expiry_date` of 2026-11-30 would leave
    the deadline derivation to hide the contradiction behind its own minimum, so the
    contradiction is caught before any date is derived.
    """

    def test_a_shipment_date_after_expiry_is_refused_before_any_deadline_is_derived(
        self, clock
    ):
        """No credit row survives the attempt and the facility never sees the request.

        PRD 3.2: "A `latest_shipment_date` falling after the `expiry_date` is a logically
        impossible credit and yields `ERR_SHIPMENT_AFTER_EXPIRY` (422)"

        PRD 3.2: "The `presentation_deadline_date` is the earlier of the `expiry_date` and the
        date obtained by adding `presentation_period_days` calendar days to
        `latest_shipment_date`; that resulting date is an inclusive upper bound."

        Design: Corner/validations/latest_shipment_after_expiry_is_rejected
        """
        parties = _parties()

        response = api_client.create_credit(
            factories.credit_payload(
                parties.applicant_id,
                parties.beneficiary_id,
                parties.facility_id,
                parties.advising_bank_id,
                latest_shipment_date="2026-12-15",
                expiry_date="2026-11-30",
            ),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_SHIPMENT_AFTER_EXPIRY", 422)
        _rows, meta = _list_credits(facility_id=parties.facility_id)
        assert meta["total_count"] == 0
        assert_facility_ledger(
            parties.refresh_facility(), allocated_cents=0, available_cents=50000000
        )


class TestTheFullyCompliantCreditWalksEveryRung:
    """The positive control: nothing is refused and every derived figure lands."""

    def test_a_compliant_credit_runs_draft_to_issued_with_its_whole_derived_set(self, clock):
        """DRAFT to PENDING_CREDIT_APPROVAL to APPROVED to ISSUED, debited only at the end.

        Every rung is satisfied at once - a `CLEARED` applicant, a matching unexpired facility
        with ample headroom, a shipment date before expiry, both mandatory document types and
        an eligible advising bank - so the 10,000,000 credit prices at the 25,000-cent floor
        rather than at the 20,000 its own tier arithmetic would give.

        PRD 3.3: "Approval grants permission and nothing more — **no facility debit happens
        here**. The limit is consumed at issuance."

        PRD 3.3: "`base_commission_cents` is the larger of a 25,000-cent floor and the result
        of multiplying `gross_exposure_cents` by `commission_bps_applied` and by the quarter
        count, dividing by 10,000 and rounding half up."

        Design: Corner/validations/fully_compliant_credit_passes_the_whole_validation_ladder
        """
        parties = _parties()

        ctx = draft_credit(parties)
        assert ctx.credit["status"] == "DRAFT"

        pending = submit_credit_for_approval(ctx.credit_id)
        assert pending["status"] == "PENDING_CREDIT_APPROVAL"

        approved = approve_credit(ctx.credit_id)
        assert approved["status"] == "APPROVED"
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )

        issued = issue_credit(ctx.credit_id)

        assert issued["status"] == "ISSUED"
        assert_issuance_charges(
            issued,
            max_drawable_cents=10000000,
            gross_exposure_cents=10000000,
            committed_allocation_cents=10000000,
            commission_bps_applied=10,
            base_commission_cents=25000,
            confirmation_charge_cents=0,
            total_charge_cents=25000,
            chargeable_utilisation_cents=10025000,
        )
        assert issued["base_commission_cents"] != 20000
        assert issued["presentation_deadline_date"] == "2026-11-21"
        assert issued["presentation_deadline_date"] != "2026-11-30"
        assert issued["issue_date"] == "2026-08-10"
        assert_credit_drawing_ledger(
            issued, reserved_cents=0, drawn_settled_cents=0, available_cents=10000000
        )
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=10025000,
            available_cents=39975000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )


class TestHeadroomIsAggregatedAcrossOpenAllocationsNotCheckedPerCredit:
    """Two 10,025,000 requirements on a 20,000,000 line: each fits, the pair does not."""

    def test_the_second_issuance_is_refused_on_the_sum_of_the_open_rows(self, clock):
        """G1 leaves 9,975,000 free, so G2 needs 10,025,000 it cannot have.

        No per-row check can catch G2 - its own requirement is comfortably below the
        20,000,000 limit - and only the aggregate over the facility's `OPEN` rows does. G2 must
        stay `APPROVED` with nothing committed, so the beneficiary of the refusal is a credit
        that may still be issued once headroom returns.

        PRD 3.1: "`allocated_cents` is recomputed as the sum, over every allocation row on this
        facility whose `status` is `OPEN`, of that row's `allocated_cents` plus its
        `charge_cents`; released rows are excluded from the sum entirely"

        PRD 3.3: "The committed allocation plus the issuance charges must fit inside the
        facility's `available_cents`, with exact equality admitted, else
        `ERR_FACILITY_LIMIT_EXCEEDED` (422)."

        Design: Corner/validations/aggregate_validation_each_credit_fits_but_the_pair_exceeds_the_facility
        """
        parties = _parties(limit_cents=20000000)
        g1 = approved_credit(parties)
        g2 = approved_credit(parties)

        issue_credit(g1.credit_id)
        assert_facility_ledger(
            parties.refresh_facility(), allocated_cents=10025000, available_cents=9975000
        )

        response = api_client.issue_credit(
            g2.credit_id, factories.issue_payload(), trade_finance_officer_headers()
        )

        validate_error(response, "ERR_FACILITY_LIMIT_EXCEEDED", 422)
        assert_fields_equal(
            g2.refresh(), status="APPROVED", committed_allocation_cents=0, total_charge_cents=0
        )
        assert g2.refresh()["issue_date"] is None
        assert g1.refresh()["status"] == "ISSUED"
        rows = list_facility_allocation_rows(parties.facility_id)
        assert len(rows) == 1
        assert_fields_equal(
            rows[0], credit_id=g1.credit_id, status="OPEN", allocated_cents=10000000
        )
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=10025000,
            available_cents=9975000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )


class TestInsuranceIsDemandedOnlyByTheCarriageAndInsuranceTerms:
    """Two credits with an identical requirement set differing only in `incoterm`."""

    @staticmethod
    def _pair(parties):
        """K_FOB and K_CIF: one mandatory invoice and one mandatory bill of lading each."""
        requirements = [
            factories.invoice_requirement_payload(),
            factories.transport_requirement_payload(),
        ]
        fob = draft_credit(
            parties, requirements=requirements, incoterm="FOB", incoterm_place="Port of Riga"
        )
        cif = draft_credit(
            parties, requirements=requirements, incoterm="CIF", incoterm_place="Oslo"
        )
        return fob, cif

    def test_the_fob_credit_submits_while_the_cif_credit_is_refused_uninsured(self, clock):
        """The same two requirements pass under FOB and fail under CIF.

        An implementation that demands insurance unconditionally rejects the FOB credit too,
        and one that never reads the `incoterm` admits the CIF credit uninsured.

        PRD 3.2: "On top of that, a credit whose `incoterm` is `CIF` or `CIP` must carry a
        mandatory `INSURANCE_CERTIFICATE` requirement, because under those terms the seller
        insures the goods; conversely, a credit whose `incoterm` is `FOB`, `FCA` or `EXW` must
        **not** carry an `INSURANCE_CERTIFICATE` requirement, because under those terms it is
        not the seller's insurance to produce."

        Design: Corner/validations/conditional_validation_insurance_requirement_bites_only_for_cif
        """
        parties = _parties()
        fob, cif = self._pair(parties)

        submitted = submit_credit_for_approval(fob.credit_id)
        response = api_client.submit_credit_for_approval(
            cif.credit_id,
            factories.submit_for_approval_payload(),
            trade_finance_officer_headers(),
        )

        assert submitted["status"] == "PENDING_CREDIT_APPROVAL"
        validate_error(response, "ERR_INCOTERM_DOCUMENT_MISMATCH", 422)
        assert cif.refresh()["status"] == "DRAFT"
        assert cif.refresh()["incoterm"] == "CIF"
        _rows, meta = _list_requirements(cif.credit_id)
        assert meta["total_count"] == 2

    def test_adding_the_insurance_certificate_lets_the_cif_credit_through(self, clock):
        """The refusal is about the missing document, so supplying it clears the rung.

        PRD 3.2: "A credit must carry at least one mandatory `COMMERCIAL_INVOICE` requirement
        and at least one transport requirement, meaning a requirement whose `doc_type` is
        `BILL_OF_LADING` or `AIR_WAYBILL`."

        PRD 3.2: "Every one of these failures reports `ERR_INCOTERM_DOCUMENT_MISMATCH` (422)."

        Design: Corner/validations/conditional_validation_insurance_requirement_bites_only_for_cif
        """
        parties = _parties()
        _fob, cif = self._pair(parties)
        first_attempt = api_client.submit_credit_for_approval(
            cif.credit_id,
            factories.submit_for_approval_payload(),
            trade_finance_officer_headers(),
        )
        validate_error(first_attempt, "ERR_INCOTERM_DOCUMENT_MISMATCH", 422)

        certificate = add_requirement(cif.credit_id, factories.insurance_requirement_payload())
        submitted = submit_credit_for_approval(cif.credit_id)

        assert_fields_equal(
            certificate, doc_type="INSURANCE_CERTIFICATE", is_mandatory=True, amended_in_seq=0
        )
        assert submitted["status"] == "PENDING_CREDIT_APPROVAL"
        rows, meta = _list_requirements(cif.credit_id)
        assert meta["total_count"] == 3
        assert sorted(row["doc_type"] for row in rows) == [
            "BILL_OF_LADING",
            "COMMERCIAL_INVOICE",
            "INSURANCE_CERTIFICATE",
        ]


class TestAnExaminationWaitsForComplianceToAdjudicate:
    """A 40-point transit hit does not block submission, but it does block conclusion."""

    @staticmethod
    def _file_awaiting_review():
        """Submit a 4,000,000 invoice routed through two high-risk transit countries."""
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)
        pctx = submitted_presentation(
            ctx,
            invoice_amounts=(4000000,),
            invoice_overrides={"transit_country_codes": ["AE", "HK"]},
        )
        return ctx, pctx

    def test_the_conclusion_is_barred_while_the_newest_screening_awaits_review(self, clock):
        """Two high-risk legs score exactly 40, which reviews rather than blocks.

        The submission itself succeeded and the drawing is reserved, so an implementation that
        only inspects `BLOCKED` would let the conclusion through while compliance is still
        deciding.

        PRD 3.8: "`transit_hits` is counted differently from the others: it is the number of
        document-and-transit-code **pairs** where the transit code is a high-risk transit code
        and is not also a sanctioned code, so one document routed through two high-risk
        countries contributes two transit hits, while a transit through a sanctioned country
        contributes to `country_hits` and never to `transit_hits`."

        PRD 3.8: "The `result` follows from the score against two inclusive lower bounds: a
        score of 100 or more gives `BLOCKED`, a score of 40 or more but below 100 gives
        `HIT_PENDING_REVIEW`, and anything below 40 gives `CLEAR`."

        PRD 3.6: "The conclusion is also barred while the newest `PRESENTED_DOCUMENTS`
        screening for the presentation still sits at `HIT_PENDING_REVIEW`, which returns
        `ERR_SCREENING_REVIEW_PENDING` (409)."

        Design: Corner/validations/cascading_validation_screening_review_must_resolve_before_conclusion
        """
        ctx, pctx = self._file_awaiting_review()

        check = newest_presentation_screening(pctx.presentation_id)
        response = api_client.conclude_examination(
            pctx.presentation_id,
            factories.conclude_examination_payload(),
            document_examiner_headers(),
        )

        assert_screening_outcome(
            check,
            scope="PRESENTED_DOCUMENTS",
            result="HIT_PENDING_REVIEW",
            risk_score=40,
            country_hits=0,
            dual_use_hits=0,
            keyword_hits=0,
            transit_hits=2,
        )
        assert check["result"] != "BLOCKED"
        validate_error(response, "ERR_SCREENING_REVIEW_PENDING", 409)
        assert pctx.refresh()["examination_status"] == "UNDER_EXAMINATION"
        assert_credit_drawing_ledger(
            ctx.refresh(), reserved_cents=4000000, drawn_settled_cents=0, available_cents=6000000
        )

    def test_a_compliance_release_lifts_the_bar_and_the_same_call_then_concludes(self, clock):
        """The very same conclude call returns the file `COMPLYING` once the hit is released.

        PRD 3.8: "`RELEASE` moves `HIT_PENDING_REVIEW → RELEASED` and unblocks settlement."

        PRD 3.6: "The outcome is decided purely by the count: `discrepancy_count` equal to zero
        moves `UNDER_EXAMINATION → COMPLYING`, and a count of one or more moves
        `UNDER_EXAMINATION → DISCREPANT`."

        Design: Corner/validations/cascading_validation_screening_review_must_resolve_before_conclusion
        """
        ctx, pctx = self._file_awaiting_review()
        check = newest_presentation_screening(pctx.presentation_id)

        released = review_screening(check["id"], "RELEASE")
        concluded = conclude_examination(pctx)

        assert_screening_outcome(released, result="RELEASED", risk_score=40, transit_hits=2)
        assert released["version"] == check["version"] + 1
        assert_fields_equal(concluded, examination_status="COMPLYING", discrepancy_count=0)
        assert newest_presentation_screening(pctx.presentation_id)["result"] == "RELEASED"
        assert_credit_drawing_ledger(
            ctx.refresh(), reserved_cents=4000000, drawn_settled_cents=0, available_cents=6000000
        )


class TestOnlyANominatedBankMayOpenAPresentation:
    """The outsider bank is real, `ACTIVE` and acting for itself, and still cannot present."""

    def test_an_unconnected_bank_is_refused_where_the_nominated_bank_succeeds(self, clock):
        """Alpina Handelsbank is refused; the nominated bank's own file opens `RECEIVED`.

        The outsider is the acting principal and its `presenting_bank_id` is its own id, so
        neither the existence check nor the principal check bites - the refusal is about the
        relationship to this credit and not about the bank.

        PRD 3.6: "The presenting bank must be nominated, meaning `presenting_bank_id` equals
        the beneficiary's `nominated_bank_id`, or the credit's `advising_bank_id`, or the
        credit's `confirming_bank_id`; any other bank is refused with `ERR_BANK_NOT_NOMINATED`
        (422)."

        PRD 3.6: "The new file takes `examination_status` `RECEIVED`, `settlement_status`
        `UNSETTLED`, `received_at` at the clock instant, `received_date` as the clock date,
        `document_count` 0 and `drawn_amount_cents` 0."

        Design: Corner/validations/cross_entity_validation_presenting_bank_must_be_nominated
        """
        parties = _parties()
        ctx = issued_credit(parties)
        outsider = create_bank(
            bank_name="Alpina Handelsbank",
            country_code="AT",
            country_risk_score=18,
            credit_rating="AA",
        )
        set_clock(MONDAY_14)

        response = api_client.create_presentation(
            factories.presentation_payload(ctx.credit_id, outsider["id"]),
            make_correspondent_bank_headers(outsider["id"]),
        )

        validate_error(response, "ERR_BANK_NOT_NOMINATED", 422)
        assert validate_success(
            api_client.get_bank(outsider["id"], credit_officer_headers())
        )["status"] == "ACTIVE"

        accepted = open_presentation(ctx).presentation

        assert_fields_equal(
            accepted,
            presenting_bank_id=parties.nominated_bank_id,
            examination_status="RECEIVED",
            settlement_status="UNSETTLED",
            document_count=0,
            drawn_amount_cents=0,
            received_date="2026-09-14",
        )
        rows, meta = validate_paginated(
            api_client.list_presentations(
                document_examiner_headers(), {"credit_id": ctx.credit_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["presenting_bank_id"] == parties.nominated_bank_id
