"""The error catalogue: uniqueness keys, path resolution and the named refusals."""

from test_helpers import (
    ApiErrorId,
    assert_assessment_money,
    assert_balance_matches_ledger,
    assert_case_dimensions,
    assert_cents,
    assert_claim_money,
    assert_gallons,
    assert_imposition,
    assert_ledger_sequence,
    assert_total_count,
    cents_for,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    amendment_payload,
    assessment_payload,
    audit_case_payload,
    bond_payload,
    certificate_payload,
    cross_match_run_payload,
    decide_payload,
    licensee_payload,
    line_payload,
    rack_removal_payload,
    refund_claim_payload,
    response_payload,
    return_payload,
    review_payload,
    schedule_payload,
)


class TestUniquenessKeys:
    def test_a_reused_fein_and_a_reused_certificate_number_are_both_refused(
        self, api, officer_headers
    ):
        """The two registry-wide uniqueness keys answer with their own 409 codes.

        PRD: "A `fein` must be unique across all licensees; a collision is refused with
        `ERR_DUPLICATE_FEIN` (HTTP 409)."
        PRD: "Finally, `document_number` must be unique across **all** certificates in the system
        — not merely across one purchaser's certificates — and a collision is refused with
        `ERR_DUPLICATE_CERTIFICATE_NUMBER` (HTTP 409)."

        Design: Corner/errors/duplicate_fein_and_duplicate_certificate_number_are_refused
        """
        supplier = validate_success(
            api.create_licensee(
                licensee_payload(
                    "SUPPLIER", legal_name="Unique Fuel Supply LLC", fein="41-7400001"
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        farm = validate_success(
            api.create_licensee(
                licensee_payload(
                    "RETAILER",
                    legal_name="Unique Farm Depot LLC",
                    fein="41-7400002",
                    retail_channel="FARM",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        certificate = validate_success(
            api.create_certificate(
                certificate_payload(
                    farm["id"],
                    "AGRICULTURE",
                    "2026-08-01",
                    "2026-08-31",
                    document_number="AG-7400-001",
                ),
                officer_headers,
            ),
            expected_status=201,
        )

        response = api.create_licensee(
            licensee_payload(
                "DISTRIBUTOR",
                legal_name="Copycat Distribution Inc",
                fein="41-7400001",
                mailing_state="WI",
            ),
            officer_headers,
        )

        validate_error(response, ApiErrorId.DUPLICATE_FEIN, expected_status=409)
        _rows, meta = validate_paginated(api.list_licensees(officer_headers))
        assert_total_count(meta, 2, "licensees after the refused duplicate registration")

        duplicate_number = api.create_certificate(
            certificate_payload(
                supplier["id"],
                "GOVERNMENT",
                "2026-09-01",
                "2026-09-30",
                document_number="AG-7400-001",
            ),
            officer_headers,
        )

        validate_error(
            duplicate_number, ApiErrorId.DUPLICATE_CERTIFICATE_NUMBER, expected_status=409
        )
        cert_rows, cert_meta = validate_paginated(api.list_certificates(officer_headers))
        assert_total_count(cert_meta, 1, "certificates after the refused duplicate number")
        assert ids_of(cert_rows) == [certificate["id"]]

    def test_the_four_reporting_uniqueness_keys_each_refuse_their_own_repeat(self, api, world):
        """Period, schedule, bill of lading and match run each carry a distinct 409 key.

        PRD: "At most one non-superseded return may exist for a given filer and period; a second
        attempt is refused with `ERR_DUPLICATE_RETURN_PERIOD` (HTTP 409)."
        PRD: "At most one schedule may exist per combination of return, schedule code and product
        code, and a duplicate is refused with `ERR_DUPLICATE_SCHEDULE` (HTTP 409) — a check that
        runs after the product-legality check."
        PRD: "Bill-of-lading numbers on lines must be unique within the combination of the parent
        schedule's return and the line's `counterparty_licensee_id`; a repeat is refused with
        `ERR_DUPLICATE_BOL` (HTTP 409)."
        PRD: "And at most one run may exist per period, so a second run for the same `period_month`
        fails with `ERR_DUPLICATE_MATCH_RUN` (HTTP 409)."

        Design: Corner/errors/duplicate_return_period_schedule_bol_and_match_run_are_refused
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Dup Key Fuel Supply LLC")
        filer = world.new_licensee("DISTRIBUTOR", legal_name="Dup Key Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        built = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 1000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 600.00,
                            "date": "2026-08-06",
                            "bill_of_lading_number": "BOL-DUP-0001",
                        }
                    ],
                }
            ],
        )

        response = api.create_return(return_payload(filer["id"], "2026-08"), world.examiner)

        validate_error(response, ApiErrorId.DUPLICATE_RETURN_PERIOD, expected_status=409)
        _rows, meta = validate_paginated(
            api.list_returns(world.examiner, params={"licensee_id": filer["id"]})
        )
        assert_total_count(meta, 1, "returns of the filer after the refused second open")

        duplicate_schedule = api.create_schedule(
            built.id,
            schedule_payload("SCH_2_RECEIVED_TAX_UNPAID", "GASOLINE", 500.00),
            world.examiner,
        )
        validate_error(duplicate_schedule, ApiErrorId.DUPLICATE_SCHEDULE, expected_status=409)

        other_product = api.create_schedule(
            built.id,
            schedule_payload("SCH_2_RECEIVED_TAX_UNPAID", "UNDYED_DIESEL", 10.00),
            world.examiner,
        )
        validate_success(other_product, expected_status=201)

        duplicate_bol = api.create_line(
            built.schedule["id"],
            line_payload(
                supplier["id"], 400.00, "2026-08-07", bill_of_lading_number="BOL-DUP-0001"
            ),
            world.examiner,
        )
        validate_error(duplicate_bol, ApiErrorId.DUPLICATE_BOL, expected_status=409)
        schedule = validate_success(api.get_schedule(built.schedule["id"], world.examiner))
        assert schedule["line_count"] == 1, "the refused repeat must not add a line"

        run = world.run_cross_match("2026-08")
        duplicate_run = api.create_cross_match_run(
            cross_match_run_payload("2026-08"), world.examiner
        )
        validate_error(duplicate_run, ApiErrorId.DUPLICATE_MATCH_RUN, expected_status=409)
        run_rows, run_meta = validate_paginated(
            api.list_cross_match_runs(world.examiner, params={"period_month": "2026-08"})
        )
        assert_total_count(run_meta, 1, "cross-match runs for the period")
        assert ids_of(run_rows) == [run["id"]]


class TestPaginationBandAndPathResolution:
    def test_pagination_arguments_outside_the_declared_band_are_refused(
        self, api, world, officer_headers
    ):
        """limit lives in [1,100] and offset at 0 or above, and a violation is a 400, not an empty page.

        PRD: "List endpoints accept two query parameters. `limit` caps the number of rows returned;
        when omitted it defaults to 10, its minimum accepted value is 1 and its maximum is 100.
        `offset` is the number of rows to skip; when omitted it defaults to 0 and its minimum
        accepted value is 0. A `limit` that is not an integer in the inclusive range 1 through 100,
        or an `offset` that is not an integer of at least 0, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/errors/pagination_arguments_outside_the_declared_band_are_refused
        """
        world.terminal(name="Pager North Terminal")
        world.terminal(name="Pager South Terminal")

        response = api.list_terminals(officer_headers, params={"limit": 0})

        validate_error(response, ApiErrorId.INVALID_PAGINATION, expected_status=400)
        for params in ({"limit": 101}, {"offset": -1}):
            refused = api.list_terminals(officer_headers, params=params)
            validate_error(refused, ApiErrorId.INVALID_PAGINATION, expected_status=400)

        rows, meta = validate_paginated(
            api.list_terminals(officer_headers, params={"limit": 100, "offset": 0})
        )
        assert_total_count(meta, 2, "terminals under the largest accepted limit")
        assert meta["has_more"] is False, "both rows fit on a page of 100"
        assert len(rows) == 2, "the accepted page carries both terminals"

        _default_rows, default_meta = validate_paginated(api.list_terminals(officer_headers))
        assert default_meta["limit"] == 10, "an omitted limit defaults to 10"
        assert default_meta["offset"] == 0, "an omitted offset defaults to 0"

    def test_every_addressed_entity_answers_with_its_own_404_code(
        self, api, world, officer_headers
    ):
        """An unused id names the entity the request addresses, and existence outranks state.

        PRD: "The per-resource 404 codes are `ERR_LICENSEE_NOT_FOUND`, `ERR_BOND_NOT_FOUND`,
        `ERR_TERMINAL_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_RACK_REMOVAL_NOT_FOUND`,
        `ERR_RETURN_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_SCHEDULE_LINE_NOT_FOUND`,
        `ERR_CROSS_MATCH_RUN_NOT_FOUND`, `ERR_DISCREPANCY_NOT_FOUND`,
        `ERR_REFUND_CLAIM_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND` and
        `ERR_AUDIT_CASE_NOT_FOUND`, each HTTP 404."
        PRD: "6. **Path existence**, left to right, as described above."
        PRD: "9. **State preconditions** — the addressed resource is in a state that admits the
        requested action (the HTTP 409 family)."

        Design: Corner/errors/every_path_id_404_names_its_own_entity
        """
        terminal = world.terminal(name="Notfound Anchor Terminal")
        unused = "00000000-0000-4000-8000-0000000000"
        probes = [
            (api.get_licensee(f"{unused}01", officer_headers), ApiErrorId.LICENSEE_NOT_FOUND),
            (
                api.get_rack_removal(f"{unused}02", world.examiner),
                ApiErrorId.RACK_REMOVAL_NOT_FOUND,
            ),
            (api.get_return(f"{unused}03", world.examiner), ApiErrorId.RETURN_NOT_FOUND),
            (
                api.get_cross_match_run(f"{unused}04", world.examiner),
                ApiErrorId.CROSS_MATCH_RUN_NOT_FOUND,
            ),
            (api.get_audit_case(f"{unused}05", world.manager), ApiErrorId.AUDIT_CASE_NOT_FOUND),
            (api.release_bond(f"{unused}06", officer_headers), ApiErrorId.BOND_NOT_FOUND),
            (
                api.get_certificate(f"{unused}07", officer_headers),
                ApiErrorId.CERTIFICATE_NOT_FOUND,
            ),
            (
                api.get_schedule_line(f"{unused}08", world.examiner),
                ApiErrorId.SCHEDULE_LINE_NOT_FOUND,
            ),
            (api.get_discrepancy(f"{unused}09", world.examiner), ApiErrorId.DISCREPANCY_NOT_FOUND),
            (
                api.get_refund_claim(f"{unused}0a", world.examiner),
                ApiErrorId.REFUND_CLAIM_NOT_FOUND,
            ),
            (api.get_inspection(f"{unused}0b", world.inspector), ApiErrorId.INSPECTION_NOT_FOUND),
        ]

        for response, expected in probes:
            validate_error(response, expected, expected_status=404)

        subject = world.new_licensee("DISTRIBUTOR", legal_name="Notfound Distribution Inc")
        built = world.build_return(
            subject["id"],
            "2026-07",
            [{"code": "SCH_2_RECEIVED_TAX_UNPAID", "product": "GASOLINE", "total": 100.00}],
        )
        body_discrepancy = api.create_audit_case(
            audit_case_payload(
                subject["id"],
                "2026-07",
                "2026-07",
                selection_method="CROSS_MATCH_ESCALATION",
                source_discrepancy_id=f"{unused}09",
            ),
            world.manager,
        )
        validate_error(body_discrepancy, ApiErrorId.DISCREPANCY_NOT_FOUND, expected_status=404)

        body_certificate = api.create_line(
            built.schedule["id"],
            line_payload(
                subject["id"],
                50.00,
                "2026-07-10",
                exemption_certificate_id=f"{unused}07",
            ),
            world.examiner,
        )
        validate_error(body_certificate, ApiErrorId.CERTIFICATE_NOT_FOUND, expected_status=404)

        alive = validate_success(api.get_terminal(terminal["id"], officer_headers))
        assert alive["id"] == terminal["id"], "the fixture terminal itself stays reachable"


class TestProvenanceOfReferences:
    def test_a_discrepancy_source_and_a_cited_return_must_both_be_the_right_ones(self, api, world):
        """Both rules police where a reference came from, not merely that it resolves.

        PRD: "When `source_discrepancy_id` is supplied, three things must hold together:
        `selection_method` must be `CROSS_MATCH_ESCALATION`; the discrepancy's escalation subject —
        its `distributor_licensee_id` when `direction` is `UNREPORTED_BY_PURCHASER`, otherwise its
        `supplier_licensee_id` — must equal the requested `subject_licensee_id`; and the
        discrepancy's `status` must be `OPEN`, `INQUIRY_SENT` or `RESPONSE_RECEIVED`, since a
        discrepancy already at `ESCALATED_TO_AUDIT` cannot seed a second case."
        PRD: "A supplied `referenced_return_id` must belong to that same `distributor_licensee_id`,
        or the response is refused with `ERR_RESPONSE_RETURN_MISMATCH` (HTTP 422)."
        PRD: "Inquiries may be sent from `OPEN` or from `RESPONSE_RECEIVED`; from any other status
        the request fails with `ERR_DISCREPANCY_STATE_INVALID` (HTTP 409)."

        Design: Corner/errors/discrepancy_source_and_response_return_mismatches_are_refused
        """
        world.set_clock("2026-09-05T00:00:00Z")
        cell = world.unreported_cell(3000.00, 1000.00, "2026-08", "GASOLINE", run=False)
        supplier = cell["supplier"]
        distributor_one = cell["distributor"]
        distributor_two = world.active_licensee(
            "DISTRIBUTOR", legal_name="Provenance Two Distribution Inc"
        )
        unrelated_return = world.build_return(
            distributor_two["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 500.00,
                    "lines": [
                        {"counterparty": supplier["id"], "gallons": 500.00, "date": "2026-08-09"}
                    ],
                }
            ],
            file=True,
        )
        run = world.run_cross_match("2026-08")
        discrepancy = world.only_discrepancy(run["id"])
        assert discrepancy["direction"] == "UNREPORTED_BY_PURCHASER"
        assert_gallons(discrepancy["variance_gallons"], 2000.00, "variance_gallons")
        world.send_inquiry(
            discrepancy["id"],
            question=(
                "Your 2026-08 return shows 1000.00 GASOLINE gallons against the supplier's "
                "3000.00; explain the gap"
            ),
        )

        response = api.create_audit_case(
            audit_case_payload(
                distributor_one["id"],
                "2026-08",
                "2026-08",
                selection_method="ROADSIDE_REFERRAL",
                source_discrepancy_id=discrepancy["id"],
            ),
            world.manager,
        )

        validate_error(response, ApiErrorId.DISCREPANCY_SOURCE_MISMATCH, expected_status=422)
        _cases, case_meta = validate_paginated(
            api.list_audit_cases(
                world.manager, params={"source_discrepancy_id": discrepancy["id"]}
            )
        )
        assert_total_count(case_meta, 0, "cases seeded by the discrepancy")

        wrong_return = api.post_response(
            discrepancy["id"],
            response_payload(referenced_return_id=unrelated_return.id),
            world.agent(distributor_one["id"]),
        )
        validate_error(wrong_return, ApiErrorId.RESPONSE_RETURN_MISMATCH, expected_status=422)
        still_sent = validate_success(api.get_discrepancy(discrepancy["id"], world.examiner))
        assert still_sent["status"] == "INQUIRY_SENT", "the refused response changes nothing"

        answered = world.answer_inquiry(
            discrepancy["id"],
            distributor_one["id"],
            referenced_return_id=cell["distributor_return"].id,
        )
        assert answered["status"] == "RESPONSE_RECEIVED"
        assert answered["inquiry_round"] == 1, "one inquiry has been sent on this row"

        world.resolve(discrepancy["id"], "ESCALATE_TO_AUDIT")
        late_inquiry = api.send_inquiry(
            discrepancy["id"],
            {"question": "One more question after escalation", "response_due_date": "2026-09-30"},
            world.examiner,
        )
        validate_error(late_inquiry, ApiErrorId.DISCREPANCY_STATE_INVALID, expected_status=409)


class TestAuditProgressGuards:
    def test_a_third_return_to_fieldwork_is_refused_while_the_case_stays_usable(self, api, world):
        """The round counter guards only the re-opening leg, and a refused attempt increments nothing.

        PRD: "The cycle back into fieldwork is bounded: `response_rounds` must be below 2 before the
        case may re-enter `FIELDWORK` from `TAXPAYER_RESPONSE`, and each traversal of that edge
        increments it, so a third attempt fails with `ERR_AUDIT_ROUND_LIMIT` (HTTP 422)."
        PRD: "The case's `assessment_status` must be `NONE` — one assessment per case, and a second
        issuance is refused with `ERR_ASSESSMENT_ALREADY_ISSUED` (HTTP 409) rather than replacing
        the first — and `case_status` must be `PRELIM_FINDINGS` or `TAXPAYER_RESPONSE`, or the
        request fails with `ERR_AUDIT_CASE_STATE_INVALID`."

        Design: Corner/errors/third_reopened_fieldwork_round_returns_audit_round_limit
        """
        subject = world.new_licensee("DISTRIBUTOR", legal_name="Rounds Distribution Inc")
        case = world.audit_case(subject["id"], "2026-08", "2026-08")
        for _round in range(3):
            world.advance(case["id"], "FIELDWORK")
            world.advance(case["id"], "PRELIM_FINDINGS")
            reached = world.advance(case["id"], "TAXPAYER_RESPONSE")
        assert reached["response_rounds"] == 2, "two traversals of the re-opening edge were legal"

        response = api.advance_case(case["id"], "FIELDWORK", world.manager)

        validate_error(response, ApiErrorId.AUDIT_ROUND_LIMIT, expected_status=422)
        after = validate_success(api.get_audit_case(case["id"], world.manager))
        assert_case_dimensions(after, "TAXPAYER_RESPONSE", "NONE")
        assert after["response_rounds"] == 2, "the refused attempt did not increment the counter"
        assert_cents(after["additional_tax_cents"], 0, "additional_tax_cents of an unassessed case")

        assessed = world.issue_assessment(case["id"], 100000)
        assert_case_dimensions(assessed, "TAXPAYER_RESPONSE", "ISSUED")
        assert_assessment_money(assessed, 100000, 10000, 0, 110000)


class TestRefundGuards:
    def test_a_reefer_claim_ten_times_over_the_cap_is_refused_while_a_modest_one_is_capped(
        self, api, world
    ):
        """The factor-of-ten check rejects, the cap clamps, and a PTO claim needs its class.

        PRD: "The `equipment_class` field is also checked here: a power-take-off or
        refrigeration-unit claim may not name a class outside the three recognized power-take-off
        classes, and a refrigeration-unit claim's `claimed_gallons` may not exceed the monthly reefer
        cap of 1500.00 gallons by more than a factor of ten — a claim for 20000 gallons of reefer
        fuel is a data-entry error and is rejected outright rather than quietly capped."
        PRD: "For a `REFRIGERATION_UNIT` claim the basis is the lesser of `claimed_gallons` and the
        1500.00-gallon monthly cap, so a claim between the cap and ten times the cap is silently
        capped rather than rejected."
        PRD: "`equipment_class` supplied when and only when `claim_type` is `PTO`"

        Design: Corner/errors/refrigeration_claim_far_above_the_cap_returns_equipment_class_invalid
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Reefer Cap Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Reefer Cap Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        world.build_return(
            claimant["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 30000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 30000.00,
                            "date": "2026-08-16",
                        }
                    ],
                }
            ],
            file=True,
        )

        response = api.create_refund_claim(
            refund_claim_payload(claimant["id"], "2026-08", 20000.00, "REFRIGERATION_UNIT"),
            world.examiner,
        )

        validate_error(response, ApiErrorId.EQUIPMENT_CLASS_INVALID, expected_status=422)
        _rows, meta = validate_paginated(
            api.list_refund_claims(world.examiner, params={"licensee_id": claimant["id"]})
        )
        assert_total_count(meta, 0, "claims after the absurd reefer entry")

        capped = validate_success(
            api.create_refund_claim(
                refund_claim_payload(claimant["id"], "2026-08", 1600.00, "REFRIGERATION_UNIT"),
                world.examiner,
            ),
            expected_status=201,
        )
        assert_claim_money(capped, 1500.00, 46350)
        assert_gallons(capped["claimed_gallons"], 1600.00, "claimed_gallons as submitted")

        missing_class = api.create_refund_claim(
            refund_claim_payload(claimant["id"], "2026-08", 100.00, "PTO"), world.examiner
        )
        validate_error(missing_class, ApiErrorId.INVALID_REQUEST, expected_status=400)
        _after_rows, after_meta = validate_paginated(
            api.list_refund_claims(world.examiner, params={"licensee_id": claimant["id"]})
        )
        assert_total_count(after_meta, 1, "only the capped claim survives")

    def test_a_partial_decision_without_a_partial_review_is_refused(self, api, world):
        """PARTIALLY_APPROVED needs recommended_gallons from the review to stand on.

        PRD: "`PARTIALLY_APPROVED` is the only branch that changes the money. It is legal only when
        the review recorded a `recommendation` of `PARTIAL` with a non-null `recommended_gallons`;
        the decider supplies no gallons of its own, and a decision that cannot draw on such a review
        is refused with `ERR_DECISION_AMOUNT_INVALID` (HTTP 422)."
        PRD: "a `PARTIAL` recommendation must be accompanied by `recommended_gallons` greater than
        zero and not greater than the claim's current `allowable_gallons`, and a violation is
        refused with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/partially_approved_after_a_full_recommendation_returns_decision_amount_invalid
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Decision Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Decision Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        world.build_return(
            claimant["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 200.00,
                    "lines": [
                        {"counterparty": supplier["id"], "gallons": 200.00, "date": "2026-08-13"}
                    ],
                }
            ],
            file=True,
        )
        claim = world.refund_claim(claimant["id"], "2026-08", 100.00)
        assert_claim_money(claim, 100.00, 3090)
        world.review_claim(claim["id"], "APPROVE")

        response = api.decide_claim(
            claim["id"], decide_payload("PARTIALLY_APPROVED"), world.supervisor
        )

        validate_error(response, ApiErrorId.DECISION_AMOUNT_INVALID, expected_status=422)
        unchanged = validate_success(api.get_refund_claim(claim["id"], world.examiner))
        assert unchanged["status"] == "REVIEWED", "the refused decision leaves the claim REVIEWED"
        assert unchanged["recommendation"] == "APPROVE"
        assert unchanged["recommended_gallons"] is None, "a full review records no gallons"
        assert unchanged["decider_user_id"] is None, "no decider is stamped by a refusal"
        assert_claim_money(unchanged, 100.00, 3090)

        approved = world.decide_claim(claim["id"], "APPROVED")
        assert approved["status"] == "APPROVED"
        assert_claim_money(approved, 100.00, 3090)

        second = world.refund_claim(claimant["id"], "2026-08", 100.00)
        assert_claim_money(second, 100.00, 3090)
        over_review = api.review_claim(
            second["id"], review_payload("PARTIAL", 150.00), world.examiner
        )
        validate_error(over_review, ApiErrorId.INVALID_REQUEST, expected_status=400)
        still_submitted = validate_success(api.get_refund_claim(second["id"], world.examiner))
        assert still_submitted["status"] == "SUBMITTED", "the refused review does not move the claim"


class TestAssessmentDisposition:
    def test_a_full_abatement_is_refused_once_part_of_the_liability_is_paid(self, api, world):
        """Abatement is all or nothing, so a part-paid assessment may not be reversed in full.

        PRD: "That absoluteness creates one guard: an abatement is refused with
        `ERR_ABATEMENT_AMOUNT_INVALID` (HTTP 422) when the licensee's `balance_cents` is below
        `assessed_total_cents`, because a payment has already retired part of the assessed liability
        and reversing the full amount would push the balance below its pre-assessment value and mint
        a credit the state does not owe."
        PRD: "It takes an `abatement_reason`, sets `assessment_status` to `ABATED`, appends an
        `ABATEMENT` ledger entry for the negative of `assessed_total_cents` naming the case as its
        source, and re-derives `balance_cents` back to exactly its pre-assessment value — with both
        ledger rows retained, because the ledger is append-only."

        Design: Corner/errors/abatement_after_a_partial_payment_returns_abatement_amount_invalid
        """
        payer = world.new_licensee("DISTRIBUTOR", legal_name="Abate One Distribution Inc")
        untouched = world.new_licensee("DISTRIBUTOR", legal_name="Abate Two Distribution Inc")
        case_one = world.case_at(payer["id"], "PRELIM_FINDINGS", "2026-08", "2026-08")
        case_two = world.case_at(untouched["id"], "PRELIM_FINDINGS", "2026-08", "2026-08")
        world.set_clock("2026-09-25T00:00:00Z")
        issued = world.issue_assessment(case_one["id"], 250000)
        world.issue_assessment(case_two["id"], 250000)
        assert_assessment_money(issued, 250000, 25000, 250, 275250)
        world.payment(
            payer["id"], 100000, "2026-09-25", memo="Partial settlement of the audit assessment"
        )

        response = api.abate_assessment(
            case_one["id"], "Field notes misread the terminal report", world.supervisor_alt
        )

        validate_error(response, ApiErrorId.ABATEMENT_AMOUNT_INVALID, expected_status=422)
        after = validate_success(api.get_audit_case(case_one["id"], world.manager))
        assert_case_dimensions(after, "PRELIM_FINDINGS", "ISSUED")
        assert_assessment_money(after, 250000, 25000, 250, 275250)
        entries = world.ledger(payer["id"])
        assert_ledger_sequence(entries, [("ASSESSMENT", 275250), ("PAYMENT", -100000)])
        payer_row = world.licensee(payer["id"])
        assert_cents(payer_row["balance_cents"], 175250, "balance after the partial payment")
        assert_balance_matches_ledger(payer_row, entries)

        abated = world.abate(case_two["id"], "Field notes misread the terminal report")
        assert_case_dimensions(abated, "PRELIM_FINDINGS", "ABATED")
        sibling_entries = world.ledger(untouched["id"])
        assert_ledger_sequence(
            sibling_entries, [("ASSESSMENT", 275250), ("ABATEMENT", -275250)]
        )
        sibling_row = world.licensee(untouched["id"])
        assert_cents(sibling_row["balance_cents"], 0, "balance after a clean abatement")
        assert_balance_matches_ledger(sibling_row, sibling_entries)


class TestCertificateRevocation:
    def test_revoking_the_same_certificate_twice_is_refused_on_its_status(
        self, api, world, officer_headers
    ):
        """The revoke verb is not idempotent, and only ACTIVE certificates occupy a window.

        PRD: "Revocation moves a certificate from `ACTIVE` to the terminal `REVOKED` and records the
        officer's `reason`. Revoking a certificate that is not `ACTIVE` fails with
        `ERR_CERTIFICATE_NOT_ACTIVE` (HTTP 409)."
        PRD: "After the named purchaser is confirmed to exist, the system looks for a collision: no
        other `ACTIVE` certificate for the same combination of `purchaser_licensee_id` and
        `exemption_type` may have a window that overlaps or even merely *touches* the requested one."

        Design: Corner/errors/revoking_an_already_revoked_certificate_returns_certificate_not_active
        """
        farm = world.new_licensee(
            "RETAILER", legal_name="Revoke Twice Farm Depot LLC", retail_channel="FARM"
        )
        certificate = world.certificate(
            farm["id"],
            exemption_type="AGRICULTURE",
            valid_from="2026-08-01",
            valid_to="2026-08-31",
            document_number="AG-8300-001",
        )
        revoked = validate_success(
            api.revoke_certificate(
                certificate["id"], "Purchaser sold the farming operation", officer_headers
            )
        )
        assert revoked["status"] == "REVOKED"

        response = api.revoke_certificate(
            certificate["id"], "Duplicate revocation request from the field office", officer_headers
        )

        validate_error(response, ApiErrorId.CERTIFICATE_NOT_ACTIVE, expected_status=409)
        reread = validate_success(api.get_certificate(certificate["id"], officer_headers))
        assert reread["status"] == "REVOKED"
        assert (
            reread["version"] == revoked["version"]
        ), "a refused second revoke must not advance the version"
        _rows, meta = validate_paginated(
            api.list_certificates(
                officer_headers,
                params={"purchaser_licensee_id": farm["id"], "status": "ACTIVE"},
            )
        )
        assert_total_count(meta, 0, "ACTIVE certificates of the purchaser")

        replacement = validate_success(
            api.create_certificate(
                certificate_payload(
                    farm["id"],
                    "AGRICULTURE",
                    "2026-08-01",
                    "2026-08-31",
                    document_number="AG-8300-002",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        assert replacement["status"] == "ACTIVE", "a revoked window is free to be re-issued"


class TestStateGatedActions:
    def test_three_readiness_gates_answer_with_three_different_conflicts(self, api, world):
        """A draft cannot be amended, an OPEN case cannot be assessed, and no case is assessed twice.

        PRD: "The target must have `filing_status` `FILED`, or the request fails with
        `ERR_RETURN_NOT_FILED` (HTTP 409)."
        PRD: "The case's `assessment_status` must be `NONE` — one assessment per case, and a second
        issuance is refused with `ERR_ASSESSMENT_ALREADY_ISSUED` (HTTP 409) rather than replacing
        the first — and `case_status` must be `PRELIM_FINDINGS` or `TAXPAYER_RESPONSE`, or the
        request fails with `ERR_AUDIT_CASE_STATE_INVALID`."

        Design: Corner/errors/state_gated_amendment_and_assessment_actions_return_their_own_state_errors
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="State Gate Fuel Supply LLC")
        filer = world.new_licensee("DISTRIBUTOR", legal_name="State Gate Distribution Inc")
        world.set_clock("2026-09-25T00:00:00Z")
        built = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 500.00,
                    "lines": [
                        {"counterparty": supplier["id"], "gallons": 500.00, "date": "2026-08-13"}
                    ],
                }
            ],
        )
        case = world.audit_case(filer["id"], "2026-08", "2026-08")
        draft = validate_success(api.get_return(built.id, world.examiner))

        response = api.create_amendment(
            built.id,
            amendment_payload(draft["version"], "The August gasoline receipts were misposted"),
            world.examiner,
        )

        validate_error(response, ApiErrorId.RETURN_NOT_FILED, expected_status=409)
        rows, meta = validate_paginated(
            api.list_returns(world.examiner, params={"licensee_id": filer["id"]})
        )
        assert_total_count(meta, 1, "returns of the filer after the refused amendment")
        assert rows[0]["amendment_count"] == 0, "a refused amendment leaves the counter alone"

        too_early = api.issue_assessment(
            case["id"], assessment_payload(100000, False), world.supervisor
        )
        validate_error(too_early, ApiErrorId.AUDIT_CASE_STATE_INVALID, expected_status=409)
        assert_case_dimensions(
            validate_success(api.get_audit_case(case["id"], world.manager)), "OPEN", "NONE"
        )
        assert world.ledger(filer["id"]) == [], "a refused assessment posts nothing to the ledger"

        world.advance(case["id"], "FIELDWORK")
        world.advance(case["id"], "PRELIM_FINDINGS")
        issued = world.issue_assessment(case["id"], 100000)
        assert_case_dimensions(issued, "PRELIM_FINDINGS", "ISSUED")
        assert_assessment_money(issued, 100000, 10000, 100, 110100)

        second = api.issue_assessment(
            case["id"], assessment_payload(50000, False), world.supervisor_alt
        )
        validate_error(second, ApiErrorId.ASSESSMENT_ALREADY_ISSUED, expected_status=409)
        unchanged = validate_success(api.get_audit_case(case["id"], world.manager))
        assert_assessment_money(unchanged, 100000, 10000, 100, 110100)
        assert (
            len(world.ledger(filer["id"], entry_type="ASSESSMENT")) == 1
        ), "the ledger holds exactly one ASSESSMENT row"

        world.advance(case["id"], "TAXPAYER_RESPONSE")
        third = api.issue_assessment(
            case["id"], assessment_payload(50000, False), world.supervisor_alt
        )
        validate_error(third, ApiErrorId.ASSESSMENT_ALREADY_ISSUED, expected_status=409)


class TestInputShapeRefusals:
    def test_the_position_holder_the_schedule_product_and_the_windows_are_shape_checked(
        self, api, world, officer_headers
    ):
        """Three refusals no state can excuse: who may hold the position, which product, which window.

        PRD: "The position holder must be a licensee whose `license_type` is `SUPPLIER` and whose
        `status` is `ACTIVE`, or the report fails with `ERR_POSITION_HOLDER_INVALID` (HTTP 422)."
        PRD: "Product legality is tied to the code: `SCH_10_DYED_SALES` accepts `DYED_DIESEL` and
        nothing else, and every other schedule code rejects `DYED_DIESEL` outright; a violation is
        refused with `ERR_SCHEDULE_PRODUCT_NOT_ALLOWED` (HTTP 422)."
        PRD: "Next, `valid_from` must not be later than `valid_to`, or the request fails with
        `ERR_DATE_RANGE_INVALID` (HTTP 422)."
        PRD: "An `effective_date` later than the logical clock is refused with
        `ERR_DATE_RANGE_INVALID` (HTTP 422)."

        Design: Corner/errors/position_holder_schedule_product_and_date_window_shapes_are_refused
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Shape Check Fuel Supply LLC", gross_net_election="NET"
        )
        distributor = world.new_licensee(
            "DISTRIBUTOR", legal_name="Shape Check Distribution Inc", gross_net_election="NET"
        )
        farm = world.active_licensee(
            "RETAILER", legal_name="Shape Check Farm Depot LLC", retail_channel="FARM"
        )
        terminal = world.terminal(name="Shape Check Terminal")
        draft = world.draft_return(distributor["id"], "2026-07")

        response = api.create_rack_removal(
            rack_removal_payload(
                terminal["id"],
                distributor["id"],
                farm["id"],
                product_code="UNDYED_DIESEL",
                gross_gallons=1000.00,
                net_gallons=995.00,
                removal_date="2026-07-20",
            ),
            world.examiner,
        )

        validate_error(response, ApiErrorId.POSITION_HOLDER_INVALID, expected_status=422)
        _rows, meta = validate_paginated(
            api.list_rack_removals(world.examiner, params={"terminal_id": terminal["id"]})
        )
        assert_total_count(meta, 0, "removals after the refused position holder")

        accepted = validate_success(
            api.create_rack_removal(
                rack_removal_payload(
                    terminal["id"],
                    supplier["id"],
                    farm["id"],
                    product_code="UNDYED_DIESEL",
                    gross_gallons=1000.00,
                    net_gallons=995.00,
                    removal_date="2026-07-20",
                ),
                world.examiner,
            ),
            expected_status=201,
        )
        assert_imposition(
            accepted,
            basis_used="NET",
            imposition_point="TERMINAL_RACK",
            taxable_gallons=995.00,
            tax_imposed=True,
            tax_amount_cents=cents_for(995.00, "UNDYED_DIESEL"),
            deferred_tax_cents=0,
        )

        for code, product in (
            ("SCH_2_RECEIVED_TAX_UNPAID", "DYED_DIESEL"),
            ("SCH_10_DYED_SALES", "GASOLINE"),
        ):
            refused = api.create_schedule(
                draft["id"], schedule_payload(code, product, 100.00), world.examiner
            )
            validate_error(
                refused, ApiErrorId.SCHEDULE_PRODUCT_NOT_ALLOWED, expected_status=422
            )

        backwards = api.create_certificate(
            certificate_payload(
                farm["id"],
                "AGRICULTURE",
                "2026-09-30",
                "2026-09-01",
                document_number="AG-9500-001",
            ),
            officer_headers,
        )
        validate_error(backwards, ApiErrorId.DATE_RANGE_INVALID, expected_status=422)
        _certs, cert_meta = validate_paginated(api.list_certificates(officer_headers))
        assert_total_count(cert_meta, 0, "certificates after the backwards window")

        current = world.licensee(distributor["id"])
        future_bond = api.post_bond(
            distributor["id"],
            bond_payload(1500000, current["version"], effective_date="2026-08-15"),
            officer_headers,
        )
        validate_error(future_bond, ApiErrorId.DATE_RANGE_INVALID, expected_status=422)
        _bonds, bond_meta = validate_paginated(
            api.list_bonds(distributor["id"], officer_headers)
        )
        assert_total_count(bond_meta, 0, "bonds after the future effective date")
