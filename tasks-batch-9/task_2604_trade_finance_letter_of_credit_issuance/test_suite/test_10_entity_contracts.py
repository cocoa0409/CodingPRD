"""The record contracts themselves: fields, defaults, derivations and the reference graph.

Each entity in this service declares which of its fields the client supplies, which the
server mints and which it derives on the spot, and the reference graph that joins them is
constrained rather than free. These tests hold the API to those declarations one entity at
a time — the round trip of a create, the derived ledger on a read, the directory's own
ordering and pagination, the defaults an omitted optional input must produce, the
immutability of presented evidence, and the two ways a bad reference is refused.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    api_client,
    assert_absent,
    assert_facility_ledger,
    create_applicant,
    create_bank,
    create_facility,
    credit_officer_headers,
    document_examiner_headers,
    draft_credit,
    factories,
    issued_credit,
    set_clock,
    setup_parties,
    submitted_presentation,
    trade_finance_officer_headers,
    CREDIT_OFFICER_1,
    TRADE_FINANCE_OFFICER_1,
)

APPLICANT_INPUTS = {
    "legal_name": "Hanseatic Grain BV",
    "country_code": "NL",
    "industry_code": "4620",
    "internal_risk_grade": "BBB",
    "kyc_status": "CLEARED",
}


def _list_credits(**params):
    return validate_paginated(
        api_client.list_credits(trade_finance_officer_headers(), params or None)
    )


def _list_banks(**params):
    return validate_paginated(
        api_client.list_banks(credit_officer_headers(), params or None)
    )


class TestApplicantRecordContract:
    """The onboarding round trip and the one required input that has no default."""

    def test_applicant_creation_returns_every_declared_field(self, clock):
        """All five required inputs come back verbatim beside the minted system fields.

        PRD 3.1: "The server records the acting operator as `onboarded_by_user_id` and sets
        the applicant's `status` to `ACTIVE`; the field's other two declared values,
        `SUSPENDED` and `CLOSED`, are never produced at onboarding."

        Design: Corner/entities/applicant_creation_returns_every_declared_field
        """
        response = api_client.create_applicant(
            dict(APPLICANT_INPUTS), credit_officer_headers(CREDIT_OFFICER_1)
        )

        applicant = validate_success(response, 201)

        assert applicant["legal_name"] == "Hanseatic Grain BV"
        assert applicant["country_code"] == "NL"
        assert applicant["industry_code"] == "4620"
        assert applicant["internal_risk_grade"] == "BBB"
        assert applicant["kyc_status"] == "CLEARED"
        assert applicant["sanctions_flag"] is False
        assert applicant["status"] == "ACTIVE"
        assert applicant["onboarded_by_user_id"] == CREDIT_OFFICER_1
        assert applicant["version"] == 1
        assert is_valid_uuid(applicant["id"])
        assert is_iso8601_timestamp(applicant["created_at"])
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_applicant_missing_required_kyc_status_returns_invalid_request(self, clock):
        """`kyc_status` has no default, so omitting it is a malformed request.

        PRD 2.9: "**Shape, then existence** — required fields present, correctly typed, enum
        members declared, money and day-count integers non-negative except where a field
        explicitly permits a negative value, else `ERR_INVALID_REQUEST` (422); then every
        path identifier and payload foreign key resolves, path identifiers first and payload
        keys in declaration order, else the matching 404 from §2.7."

        Design: Corner/entities/applicant_missing_required_kyc_status_returns_invalid_request
        """
        without_kyc = {k: v for k, v in APPLICANT_INPUTS.items() if k != "kyc_status"}

        response = api_client.create_applicant(without_kyc, credit_officer_headers())

        validate_error(response, "ERR_INVALID_REQUEST", 422)
        # `sanctions_flag` is the optional counterpart: omitting it is admitted and defaults.
        accepted = validate_success(
            api_client.create_applicant(dict(APPLICANT_INPUTS), credit_officer_headers()),
            201,
        )
        assert accepted["sanctions_flag"] is False


class TestCreditFacilityRecordContract:
    """The facility's derived ledger on a read, and its parent reference on a create."""

    def test_facility_retrieval_returns_the_stored_row_with_derived_ledger(self, clock):
        """A fresh 50,000,000 facility reads back empty, `OPEN`, and thresholded at 95%.

        PRD 3.1: "The new facility starts with `status` `ACTIVE`, `collateral_posted_cents`
        and `allocated_cents` at zero, `available_cents` equal to the whole `limit_cents`,
        `suspended_reason` unset, and `utilisation_posture` `OPEN`."

        Design: Corner/entities/facility_retrieval_returns_the_stored_row_with_derived_ledger
        """
        applicant = create_applicant(**APPLICANT_INPUTS)
        created = create_facility(
            applicant["id"],
            currency="USD",
            limit_cents=50000000,
            collateral_required_pct=20,
            facility_expiry_date="2027-06-30",
        )

        facility = validate_success(
            api_client.get_facility(created["id"], credit_officer_headers())
        )

        assert facility["applicant_id"] == applicant["id"]
        assert facility["currency"] == "USD"
        assert facility["limit_cents"] == 50000000
        assert facility["collateral_required_pct"] == 20
        assert facility["collateral_posted_cents"] == 0
        assert_facility_ledger(
            facility,
            allocated_cents=0,
            available_cents=50000000,
            restrict_threshold_cents=47500000,
            utilisation_posture="OPEN",
            status="ACTIVE",
            suspended_reason=None,
        )

    def test_facility_creation_under_unknown_applicant_returns_not_found(self, clock):
        """The facility's parent is the applicant, and an unstored parent stops the request.

        PRD 2.7: "The parent identifier is looked up first, and if it does not resolve the
        request fails there with that parent's own not-found error — the child identifier is
        not even examined."

        Design: Corner/entities/facility_creation_under_unknown_applicant_returns_not_found
        """
        response = api_client.create_facility(
            NON_EXISTENT_UUID, factories.facility_payload(), credit_officer_headers()
        )

        validate_error(response, "ERR_APPLICANT_NOT_FOUND", 404)


class TestBankRecordContract:
    """The bank directory's derived sort key, its pagination and its filter."""

    def test_bank_computed_eligibility_score_overwrites_input_ignored(self, clock):
        """An A-rated bank at country risk 35 scores 690, and its used line starts empty.

        PRD 3.1: "Its `eligibility_score` is derived immediately: take 100 minus
        `country_risk_score`, multiply by 6, and add the rating points multiplied by 4, where
        the rating points are 100 for `AA`, 75 for `A`, 50 for `BBB` and 25 for `BB`."

        Design: Corner/entities/bank_computed_eligibility_score_overwrites_input_ignored
        """
        response = api_client.create_bank(
            factories.bank_payload(
                bank_name="Raffles Confirming Bank",
                country_code="SG",
                country_risk_score=35,
                credit_rating="A",
                confirmation_appetite_cents=20000000,
            ),
            credit_officer_headers(),
        )

        bank = validate_success(response, 201)

        assert bank["eligibility_score"] == 690
        assert bank["confirming_line_used_cents"] == 0
        assert bank["status"] == "ACTIVE"
        assert bank["sanctions_flag"] is False

    def test_bank_listing_paginates_with_total_count_and_has_more(self, clock):
        """Three banks, a two-row window, then the remainder, then a one-row filter.

        PRD 2.3: "List responses report all four pagination fields in `meta`: the effective
        `limit`, the effective `offset`, the `total_count` of rows matching the filter before
        the page window is applied, and `has_more`, which is true exactly when rows remain
        beyond the current window."

        Design: Corner/entities/bank_listing_paginates_with_total_count_and_has_more
        """
        de = create_bank(
            country_code="DE",
            country_risk_score=10,
            credit_rating="AA",
            confirmation_appetite_cents=100000000,
        )
        sg = create_bank(
            country_code="SG",
            country_risk_score=35,
            credit_rating="A",
            confirmation_appetite_cents=20000000,
        )
        br = create_bank(
            country_code="BR",
            country_risk_score=55,
            credit_rating="BBB",
            confirmation_appetite_cents=30000000,
        )
        assert [de["eligibility_score"], sg["eligibility_score"], br["eligibility_score"]] == [
            940,
            690,
            470,
        ]

        first_page, first_meta = _list_banks(limit=2, offset=0)
        second_page, second_meta = _list_banks(limit=2, offset=2)
        filtered, filtered_meta = _list_banks(country_code="SG")

        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_page[0]["id"] == de["id"]
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_page[0]["id"] == br["id"]
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == sg["id"]


class TestDocumentaryCreditRecordContract:
    """The credit's optional-input defaults, its type constraints and its unknown-id read."""

    def test_credit_optional_inputs_apply_declared_defaults(self, clock):
        """Omitting all four optional inputs yields 0, 0, false, false and a zero tolerance.

        PRD 3.2: "Four inputs are optional: `tolerance_pct`, the upward drawing tolerance,
        between 0 and 10 inclusive and defaulting to 0; `tenor_days`, between 0 and 360
        inclusive and defaulting to 0; and the two shipment permissions
        `partial_shipment_allowed` and `transhipment_allowed`, both booleans defaulting to
        false."

        Design: Corner/entities/credit_optional_inputs_apply_declared_defaults
        """
        parties = setup_parties()
        payload = factories.credit_payload(
            parties.applicant_id,
            parties.beneficiary_id,
            parties.facility_id,
            parties.advising_bank_id,
            amount_cents=10000000,
            available_by="SIGHT_PAYMENT",
        )
        for optional in ("tolerance_pct", "tenor_days"):
            payload.pop(optional)

        credit = validate_success(
            api_client.create_credit(payload, trade_finance_officer_headers()), 201
        )

        assert credit["tolerance_pct"] == 0
        assert credit["tenor_days"] == 0
        assert credit["partial_shipment_allowed"] is False
        assert credit["transhipment_allowed"] is False
        assert credit["max_drawable_cents"] == 10000000
        assert credit["max_drawable_cents"] != 10500000
        assert credit["status"] == "DRAFT"

    def test_credit_available_by_undeclared_enum_member_rejected(self, clock):
        """An undeclared enum member, an out-of-range day count and a sub-minimum amount.

        PRD 2.9: "**Shape, then existence** — required fields present, correctly typed, enum
        members declared, money and day-count integers non-negative except where a field
        explicitly permits a negative value, else `ERR_INVALID_REQUEST` (422); then every
        path identifier and payload foreign key resolves, path identifiers first and payload
        keys in declaration order, else the matching 404 from §2.7."

        Design: Corner/entities/credit_available_by_undeclared_enum_member_rejected
        """
        parties = setup_parties()

        def attempt(**overrides):
            return api_client.create_credit(
                factories.credit_payload(
                    parties.applicant_id,
                    parties.beneficiary_id,
                    parties.facility_id,
                    parties.advising_bank_id,
                    **overrides,
                ),
                trade_finance_officer_headers(),
            )

        validate_error(attempt(available_by="RED_CLAUSE"), "ERR_INVALID_REQUEST", 422)
        validate_error(attempt(presentation_period_days=31), "ERR_INVALID_REQUEST", 422)
        validate_error(attempt(amount_cents=99999), "ERR_INVALID_REQUEST", 422)

        _rows, meta = _list_credits()
        assert meta["total_count"] == 0

    def test_credit_get_with_unknown_id_returns_not_found(self, clock):
        """A well-formed but unstored UUID is a 404 on its own dedicated error id.

        PRD 2.7: "Each unresolvable reference maps to its own dedicated 404:
        `ERR_APPLICANT_NOT_FOUND` for an applicant path id or an `applicant_id`,
        `ERR_FACILITY_NOT_FOUND` for a facility path id or a `facility_id`,
        `ERR_BANK_NOT_FOUND` for a bank path id or any of `nominated_bank_id`,
        `advising_bank_id`, `confirming_bank_id` and `presenting_bank_id`,
        `ERR_BENEFICIARY_NOT_FOUND` for a beneficiary path id or a `beneficiary_id`,
        `ERR_CREDIT_NOT_FOUND` for a credit path id or a `credit_id`,
        `ERR_AMENDMENT_NOT_FOUND` for an amendment path id, `ERR_PRESENTATION_NOT_FOUND`
        for a presentation path id or a `presentation_id`, `ERR_WAIVER_REQUEST_NOT_FOUND`
        for a waiver-request path id, `ERR_SETTLEMENT_CLAIM_NOT_FOUND` for a
        settlement-claim path id and `ERR_SCREENING_CHECK_NOT_FOUND` for a screening-check
        path id."

        Design: Corner/entities/credit_get_with_unknown_id_returns_not_found
        """
        response = api_client.get_credit(
            NON_EXISTENT_UUID, trade_finance_officer_headers(TRADE_FINANCE_OFFICER_1)
        )

        validate_error(response, "ERR_CREDIT_NOT_FOUND", 404)
        assert response.json()["response_type"] == "error"


class TestPresentedDocumentRecordContract:
    """Immutable evidence: no version, no update path, and a closed window for additions."""

    def test_presented_document_is_immutable_with_no_version_field(self, clock):
        """Once the file is submitted no further document is admitted, and the rows are frozen.

        PRD 3.6: "Documents may be added only while `examination_status` is `RECEIVED`, else
        `ERR_PRESENTATION_NOT_EXAMINABLE` (409)." And: "Presented documents are immutable
        once recorded: there is no update path, no delete path, and — as noted in the record
        conventions — no `updated_at` and no `version` on them at all."

        Design: Corner/entities/presented_document_is_immutable_with_no_version_field
        """
        ctx = issued_credit(
            setup_parties(facility={"limit_cents": 50000000}),
            None,
            amount_cents=10000000,
            available_by="SIGHT_PAYMENT",
            tenor_days=0,
            tolerance_pct=0,
            latest_shipment_date="2026-10-31",
            expiry_date="2026-11-30",
            presentation_period_days=21,
        )
        set_clock("2026-09-14T09:00:00Z")
        pctx = submitted_presentation(ctx, (2000000,))
        assert pctx.presentation["examination_status"] == "UNDER_EXAMINATION"
        invoice_id = pctx.documents[0]["id"]

        late = api_client.create_presented_document(
            pctx.presentation_id,
            {
                "doc_type": "PACKING_LIST",
                "originals_presented": 1,
                "copies_presented": 0,
                "issue_date": "2026-09-09",
                "issuer_name": "Kallang Garments Pte Ltd",
            },
            pctx.bank_headers,
        )

        validate_error(late, "ERR_PRESENTATION_NOT_EXAMINABLE", 409)
        rows, meta = validate_paginated(
            api_client.list_presented_documents(
                pctx.presentation_id, document_examiner_headers()
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2
        assert rows[0]["id"] == invoice_id
        assert rows[0]["invoice_amount_cents"] == 2000000
        assert is_iso8601_timestamp(rows[0]["created_at"])
        assert_absent(rows[0], "version", "updated_at")


class TestCreditReferenceGraph:
    """The credit is the junction of four references, and one of them must close the cycle."""

    def test_credit_is_the_graph_junction_of_applicant_beneficiary_facility_and_banks(
        self, clock
    ):
        """Two credits share a beneficiary and a bank but sit on two facilities of one applicant.

        PRD 3.2: "The credit register can be narrowed by `applicant_id`, `beneficiary_id`,
        `facility_id`, `advising_bank_id`, `confirming_bank_id`, `status` and
        `confirmation_status`; a credit's requirement list can be narrowed by `doc_type` and
        `is_mandatory`."

        Design: Corner/entities/credit_is_the_graph_junction_of_applicant_beneficiary_facility_and_banks
        """
        parties = setup_parties(facility={"limit_cents": 50000000})
        second_facility = create_facility(
            parties.applicant_id, limit_cents=50000000, facility_expiry_date="2027-12-31"
        )
        first = draft_credit(parties, None, amount_cents=10000000)
        second = draft_credit(
            parties, None, facility_id=second_facility["id"], amount_cents=10000000
        )

        _by_beneficiary, beneficiary_meta = _list_credits(
            beneficiary_id=parties.beneficiary_id
        )
        by_facility, facility_meta = _list_credits(facility_id=second_facility["id"])
        _by_bank, bank_meta = _list_credits(advising_bank_id=parties.advising_bank_id)
        _facilities, applicant_facility_meta = validate_paginated(
            api_client.list_applicant_facilities(
                parties.applicant_id, credit_officer_headers()
            )
        )

        assert beneficiary_meta["total_count"] == 2
        assert facility_meta["total_count"] == 1
        assert by_facility[0]["id"] == second.credit_id
        assert bank_meta["total_count"] == 2
        assert applicant_facility_meta["total_count"] == 2
        assert first.credit["facility_id"] == parties.facility_id
        assert second.credit["facility_id"] == second_facility["id"]
        assert first.credit["beneficiary_id"] == second.credit["beneficiary_id"]

    def test_credit_cannot_be_drawn_on_another_applicants_facility_cycle_constraint(
        self, clock
    ):
        """The applicant, facility and credit triangle must close on the same applicant.

        PRD 3.2: "The named facility must belong to the named applicant and be denominated in
        the credit's own `currency`, failing which the draft is refused with
        `ERR_FACILITY_APPLICANT_MISMATCH` (422); and separately, a facility whose
        `facility_expiry_date` falls earlier than the credit's `expiry_date` yields
        `ERR_FACILITY_EXPIRED` (422), since the facility must outlive the instrument it
        supports."

        Design: Corner/entities/credit_cannot_be_drawn_on_another_applicants_facility_cycle_constraint
        """
        parties = setup_parties(facility={"limit_cents": 50000000})
        other_applicant = create_applicant()
        other_facility = create_facility(other_applicant["id"], limit_cents=50000000)

        response = api_client.create_credit(
            factories.credit_payload(
                parties.applicant_id,
                parties.beneficiary_id,
                other_facility["id"],
                parties.advising_bank_id,
                amount_cents=10000000,
            ),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_FACILITY_APPLICANT_MISMATCH", 422)
        _rows, meta = _list_credits()
        assert meta["total_count"] == 0
        assert parties.refresh_facility()["allocated_cents"] == 0
        assert (
            validate_success(
                api_client.get_facility(other_facility["id"], credit_officer_headers())
            )["allocated_cents"]
            == 0
        )
