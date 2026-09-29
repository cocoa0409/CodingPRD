"""Priority conflicts, overlapping temporal resources and the two conservation laws."""

from test_helpers import (
    TAX_SUPERVISOR_ALT_ID,
    TAX_SUPERVISOR_ID,
    ApiErrorId,
    assert_assessment_money,
    assert_balance_matches_ledger,
    assert_bond_instrument,
    assert_bond_position,
    assert_case_dimensions,
    assert_cents,
    assert_gallons,
    assert_ledger_sequence,
    assert_return_money,
    assert_return_statuses,
    assert_total_count,
    cents_for,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    audit_case_payload,
    certificate_payload,
    rack_removal_payload,
)


class TestRefilePrefersStateOverSafety:
    def test_a_refiling_of_a_filed_return_reports_the_state_clash_not_the_dead_certificate(
        self, api, world, examiner_headers, officer_headers
    ):
        """Both the 409 state rule and the 422 certificate rule fire; the ladder must return the 409.

        PRD: "Seven conditions guard the transition, in this order. The filer must not be revoked
        (`ERR_LICENSEE_REVOKED`). The return's `filing_status` must be `DRAFT`
        (`ERR_RETURN_ALREADY_FILED`). The period must be closed — the logical clock must have reached
        at least the first instant of the month following `period_month`, so a period still in flight
        cannot be filed; the refusal carries `ERR_PERIOD_NOT_CLOSED` (HTTP 422). Every exempt-sales
        and exports line must carry a certificate that is still valid on that line's `document_date`
        (`ERR_CERTIFICATE_NOT_VALID_ON_DATE`)."
        PRD: "Within band 9 the state check for the addressed resource always precedes the state
        checks of related rows, and within bands 10 through 14 the relative order of individual rules
        is stated at each rule in §3 wherever two rules could both fire on the same request."
        PRD: "The floored net is added to `taxable_gallons_total`, and the floored net multiplied by
        that product's cents-per-gallon rate, rounded half up to a whole cent **once for that
        product**, is added to `tax_due_cents`."

        Design: Difficulty/priority_pair_validation_conflict/refile_with_revoked_certificate_prefers_state_over_safety_error
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        filer = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        fleet = world.active_licensee(
            "RETAILER", legal_name="Dakota County Fleet Services", fein="41-2000001"
        )
        certificate = world.certificate(
            fleet["id"],
            exemption_type="GOVERNMENT",
            document_number="GOV-CERT-2553-B",
            valid_from="2026-01-01",
            valid_to="2026-12-31",
        )
        assert certificate["status"] == "ACTIVE"
        world.set_clock("2026-09-05T00:00:00Z")

        built = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "UNDYED_DIESEL",
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 500.00,
                            "date": "2026-08-06",
                            "bill_of_lading_number": "BOL-D2-UND-010",
                        }
                    ],
                },
                {
                    "code": "SCH_6_EXEMPT_SALES",
                    "product": "UNDYED_DIESEL",
                    "lines": [
                        {
                            "counterparty": fleet["id"],
                            "gallons": 200.00,
                            "date": "2026-08-14",
                            "transaction_type": "SALE",
                            "exemption_certificate_id": certificate["id"],
                            "bill_of_lading_number": "BOL-D6-UND-010",
                        }
                    ],
                },
            ],
            file=True,
            attest_name="D. Ridgeway",
        )
        assert_return_statuses(built.row, "FILED", "NOT_MATCHED")
        assert_return_money(built.row, 300.00, 9270, 0, 0, 9270, 0)
        assert cents_for(300.00, "UNDYED_DIESEL") == 9270
        filed_at = built.row["filed_at"]
        assert filed_at is not None

        revoked_certificate = validate_success(
            api.revoke_certificate(
                certificate["id"], "Fleet exemption withdrawn by the county", officer_headers
            )
        )
        assert revoked_certificate["status"] == "REVOKED", "the safety condition really is violated"

        validate_error(
            api.file_return(built.id, "D. Ridgeway", examiner_headers),
            ApiErrorId.RETURN_ALREADY_FILED,
            expected_status=409,
        )

        reread = validate_success(api.get_return(built.id, examiner_headers))
        assert_return_statuses(reread, "FILED", "NOT_MATCHED")
        assert_return_money(reread, 300.00, 9270, 0, 0, 9270, 0)
        assert reread["filed_at"] == filed_at, "the rejected call did not restamp the filing"
        licensee = validate_success(api.get_licensee(filer["id"], officer_headers))
        assert_cents(licensee["balance_cents"], 9270, "balance_cents")
        assert_ledger_sequence(world.ledger(filer["id"]), [("RETURN_TAX", 9270)])


class TestRackRemovalPrefersSafetyOverFiscal:
    def test_a_revoked_and_unbonded_purchaser_reports_the_licence_bar_not_the_bond_bar(
        self, api, world, examiner_headers, officer_headers
    ):
        """The licence check runs among the first five, the bond check last, so the licence wins.

        PRD: "Before any tax is computed, five business checks run in this order. The purchaser's
        `status` must be `ACTIVE` or `SUSPENDED`; a purchaser still in `PENDING_BOND` or already
        `REVOKED` may not take delivery at a rack at all, and the report is refused with
        `ERR_PURCHASER_LICENSE_INVALID` (HTTP 422)."
        PRD: "One fiscal check then runs last, after the duplicate-bill-of-lading check. When a
        removal has the shape that would defer tax — the purchaser's `license_type` is `SUPPLIER` or
        `DISTRIBUTOR`, the `destination_state` equals the home state `MN`, and no valid exemption
        certificate has been presented — the removal is refused if that purchaser's
        `bond_deficiency_cents` is greater than zero, whatever the purchaser's `status` happens to
        be. That refusal carries `ERR_PURCHASER_BOND_DEFICIENT` (HTTP 422)."
        PRD: "Every bond instrument of the licensee whose `status` is `ACTIVE` becomes `FORFEITED`
        with `release_reason` set to `LICENSE_REVOKED`, while instruments already `RELEASED` are left
        untouched — so a revoked licensee whose bonds were previously released carries a full
        deficiency once `posted_bond_cents` and `bond_deficiency_cents` are re-derived."

        Design: Difficulty/priority_pair_validation_conflict/revoked_and_underbonded_purchaser_prefers_safety_over_fiscal_error
        """
        holder = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        purchaser = world.new_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        bond = world.post_bond(purchaser["id"], 1500000)
        world.activate(purchaser["id"])
        revoked = world.revoke(purchaser["id"], "Evasion referral - licence revoked")
        assert revoked["status"] == "REVOKED"
        assert_bond_position(revoked, 1500000, 0, 1500000)
        bonds, _ = validate_paginated(api.list_bonds(purchaser["id"], officer_headers))
        assert_bond_instrument(bonds[0], "FORFEITED", "LICENSE_REVOKED", 1500000)
        assert bonds[0]["id"] == bond["id"]

        terminal = world.terminal(name="Saint Paul Park Rack")

        validate_error(
            api.create_rack_removal(
                rack_removal_payload(
                    terminal["id"],
                    holder["id"],
                    purchaser["id"],
                    bill_of_lading_number="BOL-CONF-0001",
                ),
                examiner_headers,
            ),
            ApiErrorId.PURCHASER_LICENSE_INVALID,
            expected_status=422,
        )

        _, meta = validate_paginated(
            api.list_rack_removals(
                examiner_headers, params={"purchaser_licensee_id": purchaser["id"]}
            )
        )
        assert_total_count(meta, 0)
        still_revoked = validate_success(api.get_licensee(purchaser["id"], officer_headers))
        assert still_revoked["status"] == "REVOKED"
        assert_bond_position(still_revoked, 1500000, 0, 1500000)


class TestCertificateWindowOverlap:
    def test_a_shared_endpoint_day_collides_while_the_next_day_and_another_type_do_not(
        self, api, world, officer_headers
    ):
        """Closed day intervals collide on a touch, and the resource key includes the exemption type.

        PRD: "Both bounds are ISO 8601 calendar dates and the window is **closed**: a transaction
        dated exactly on `valid_from` or exactly on `valid_to` is covered."
        PRD: "After the named purchaser is confirmed to exist, the system looks for a collision: no
        other `ACTIVE` certificate for the same combination of `purchaser_licensee_id` and
        `exemption_type` may have a window that overlaps or even merely *touches* the requested one.
        Because both windows are closed intervals, sharing a single endpoint date is a collision, and
        the request is refused with `ERR_CERTIFICATE_PERIOD_OVERLAP` (HTTP 422)."
        PRD: "Finally, `document_number` must be unique across **all** certificates in the system —
        not merely across one purchaser's certificates — and a collision is refused with
        `ERR_DUPLICATE_CERTIFICATE_NUMBER` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/exemption_certificate_closed_interval_shared_endpoint_collides
        """
        fleet = world.active_licensee(
            "RETAILER", legal_name="Dakota County Fleet Services", fein="41-2000001"
        )
        assert_bond_position(fleet, 400000, 400000, 0)
        first_half = world.certificate(
            fleet["id"],
            exemption_type="GOVERNMENT",
            document_number="GOV-CERT-2553-H1",
            valid_from="2026-01-01",
            valid_to="2026-06-30",
        )
        assert first_half["status"] == "ACTIVE"

        validate_error(
            api.create_certificate(
                certificate_payload(
                    fleet["id"],
                    exemption_type="GOVERNMENT",
                    document_number="GOV-CERT-2553-TOUCH",
                    valid_from="2026-06-30",
                    valid_to="2026-12-31",
                ),
                officer_headers,
            ),
            ApiErrorId.CERTIFICATE_PERIOD_OVERLAP,
            expected_status=422,
        )

        second_half = validate_success(
            api.create_certificate(
                certificate_payload(
                    fleet["id"],
                    exemption_type="GOVERNMENT",
                    document_number="GOV-CERT-2553-H2",
                    valid_from="2026-07-01",
                    valid_to="2026-12-31",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        assert second_half["status"] == "ACTIVE"
        assert second_half["valid_from"] == "2026-07-01"
        assert second_half["valid_to"] == "2026-12-31"

        agriculture = validate_success(
            api.create_certificate(
                certificate_payload(
                    fleet["id"],
                    exemption_type="AGRICULTURE",
                    document_number="AG-CERT-2553-H1",
                    valid_from="2026-01-01",
                    valid_to="2026-06-30",
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        assert agriculture["valid_from"] == "2026-01-01", "a different type is a different resource"
        assert agriculture["valid_to"] == "2026-06-30"

        untouched = validate_success(api.get_certificate(first_half["id"], officer_headers))
        assert untouched["status"] == "ACTIVE"
        assert untouched["valid_from"] == "2026-01-01"
        assert untouched["valid_to"] == "2026-06-30"

        rows, meta = validate_paginated(
            api.list_certificates(officer_headers, params={"purchaser_licensee_id": fleet["id"]})
        )
        assert_total_count(meta, 3)
        assert set(ids_of(rows)) == {first_half["id"], second_half["id"], agriculture["id"]}


class TestAuditWindowBufferedOverlap:
    def test_a_one_month_calendar_gap_still_collides_while_a_two_month_gap_does_not(
        self, api, world, manager_headers, officer_headers
    ):
        """Each window is widened by a month on both ends, so a single-month gap is still a clash.

        PRD: "No other non-closed case for the same subject may cover an overlapping period, and the
        comparison is deliberately generous: each window is widened by one month on **both** ends
        before the two are compared, and the semantics are half-open so that windows separated by a
        single month still collide."
        PRD: "A non-closed case covering 2026-03 through 2026-04 therefore blocks a new case for
        2026-05, because the first widens to 2026-02 through 2026-05 and the second to 2026-04
        through 2026-06. A violation is refused with `ERR_AUDIT_PERIOD_OVERLAP` (HTTP 422). Closed
        cases never block anything."
        PRD: "Opening the case increments the subject's `open_audit_count` and, because that count is
        now positive, moves the subject's `SUBMITTED` and `REVIEWED` refund claims to `HELD` with
        `hold_reason` `OPEN_AUDIT`."

        Design: Difficulty/resource_temporal_overlap/audit_case_period_buffer_collides_across_one_month_gap
        """
        subject = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        spring = world.audit_case(
            subject["id"], "2026-03", "2026-05", selection_method="ROADSIDE_REFERRAL"
        )
        assert_case_dimensions(spring, "OPEN", "NONE")

        validate_error(
            api.create_audit_case(
                audit_case_payload(
                    subject["id"], "2026-07", "2026-08", selection_method="ROADSIDE_REFERRAL"
                ),
                manager_headers,
            ),
            ApiErrorId.AUDIT_PERIOD_OVERLAP,
            expected_status=422,
        )

        late = validate_success(
            api.create_audit_case(
                audit_case_payload(
                    subject["id"], "2026-08", "2026-09", selection_method="ROADSIDE_REFERRAL"
                ),
                manager_headers,
            ),
            expected_status=201,
        )
        assert_case_dimensions(late, "OPEN", "NONE")
        assert late["period_start_month"] == "2026-08"
        assert late["period_end_month"] == "2026-09"

        untouched = validate_success(api.get_audit_case(spring["id"], manager_headers))
        assert_case_dimensions(untouched, "OPEN", "NONE")
        assert untouched["period_start_month"] == "2026-03"
        assert untouched["period_end_month"] == "2026-05"

        licensee = validate_success(api.get_licensee(subject["id"], officer_headers))
        assert licensee["open_audit_count"] == 2, "the refused case was never created"
        rows, meta = validate_paginated(
            api.list_audit_cases(manager_headers, params={"subject_licensee_id": subject["id"]})
        )
        assert_total_count(meta, 2)
        assert set(ids_of(rows)) == {spring["id"], late["id"]}


class TestAssessmentThenAbatementConservesMoney:
    def test_abating_an_assessment_returns_the_balance_to_its_pre_assessment_value(
        self, api, world, manager_headers, supervisor_headers, supervisor_alt_headers
    ):
        """Invariant M: the compensation is an offsetting ledger row, never a deletion or an edit.

        PRD: "At every instant, and for every licensee, `balance_cents` equals the signed sum of that
        licensee's ledger entries' `amount_cents`; a positive balance means the licensee owes the
        state. The ledger is never edited: an assessment that is later abated leaves *both* rows in
        place, and the balance returns to exactly its pre-assessment value."
        PRD: "Issuance sets `assessment_status` to `ISSUED` and `assessed_by_user_id` to the acting
        `X-User-ID`, then appends an `ASSESSMENT` ledger entry for the positive `assessed_total_cents`
        naming the case as its source and re-derives the subject's `balance_cents`."
        PRD: "Abatement, available from `ISSUED` or `PROTESTED`, is the compensating counterpart of
        issuance. It takes an `abatement_reason`, sets `assessment_status` to `ABATED`, appends an
        `ABATEMENT` ledger entry for the negative of `assessed_total_cents` naming the case as its
        source, and re-derives `balance_cents` back to exactly its pre-assessment value — with both
        ledger rows retained, because the ledger is append-only."
        PRD: "Abatement also carries its own segregation rule: the acting `X-User-ID` must differ
        from `assessed_by_user_id`, and a supervisor abating its own assessment is refused with
        `ERR_ASSESSMENT_SEGREGATION_VIOLATION`."

        Design: Difficulty/compensating_invariant/assessment_then_abatement_restores_licensee_balance_invariant_m
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        subject = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        built = world.build_return(
            subject["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 17482.52,
                            "date": "2026-08-08",
                            "bill_of_lading_number": "BOL-D2-GAS-040",
                        }
                    ],
                }
            ],
            file=True,
            attest_name="D. Ridgeway",
        )
        assert_return_money(built.row, 17482.52, 500000, 0, 0, 500000, 0)
        assert cents_for(17482.52, "GASOLINE") == 500000
        before = validate_success(api.get_licensee(subject["id"], world.officer))
        assert_cents(before["balance_cents"], 500000, "balance_cents")

        case = world.audit_case(
            subject["id"], "2026-08", "2026-08", selection_method="ROADSIDE_REFERRAL"
        )
        world.advance(case["id"], "FIELDWORK")
        world.advance(case["id"], "PRELIM_FINDINGS")
        world.set_clock("2026-11-19T23:59:59Z")

        issued = world.issue_assessment(case["id"], 250000, False, as_headers=supervisor_headers)
        assert_case_dimensions(issued, "PRELIM_FINDINGS", "ISSUED")
        assert_assessment_money(issued, 250000, 25000, 3750, 278750)
        assert issued["assessed_by_user_id"] == TAX_SUPERVISOR_ID
        during = validate_success(api.get_licensee(subject["id"], world.officer))
        assert_cents(during["balance_cents"], 778750, "balance_cents")

        abated = world.abate(
            case["id"],
            "Fieldwork re-read of the terminal schedules withdrew the deficiency",
            as_headers=supervisor_alt_headers,
        )
        assert_case_dimensions(abated, "PRELIM_FINDINGS", "ABATED")
        assert_assessment_money(abated, 250000, 25000, 3750, 278750)
        assert abated["assessed_by_user_id"] == TAX_SUPERVISOR_ID
        assert TAX_SUPERVISOR_ALT_ID != TAX_SUPERVISOR_ID, "the abating user is a second human"

        entries = world.ledger(subject["id"])
        assert_ledger_sequence(
            entries,
            [("RETURN_TAX", 500000), ("ASSESSMENT", 278750), ("ABATEMENT", -278750)],
        )
        after = validate_success(api.get_licensee(subject["id"], world.officer))
        assert_cents(after["balance_cents"], 500000, "balance_cents")
        assert sum(entry["amount_cents"] for entry in entries) == 500000
        assert_balance_matches_ledger(after, entries)


class TestWriteOffConservesGallons:
    def test_a_write_off_moves_gallons_between_the_live_counters_and_leaves_the_frozen_gross(
        self, api, world, examiner_headers, officer_headers
    ):
        """The conserved quantity is gallons: gross stays put while the live pair rebalances.

        PRD: "For every created discrepancy whose direction is `UNREPORTED_BY_PURCHASER`, the
        variance is added to both `gross_unreported_gallons_total` and `unreported_gallons_total`."
        PRD: "`gross_unreported_gallons_total` is **frozen** at creation time and is never re-derived
        by any later action. `unreported_gallons_total` is the live sum over the run's
        `UNREPORTED_BY_PURCHASER` discrepancies whose status is not `WRITTEN_OFF`, and
        `written_off_gallons_total` is the live sum over those whose status **is** `WRITTEN_OFF`."
        PRD: "`WRITTEN_OFF` sets `status` to `WRITTEN_OFF` and moves the gallons: the run's
        `unreported_gallons_total` decreases by `variance_gallons` and its `written_off_gallons_total`
        increases by the same amount, conserving the frozen gross."
        PRD: "It requires a `write_off_reason`, and it is permitted only when the absolute value of
        `variance_gallons` is strictly less than 10000.00 gallons; a variance at or above the
        auto-escalation threshold must be explained or escalated and can never be written off."
        PRD: "All three branches decrease the purchaser's `open_discrepancy_count` by one and
        re-derive the purchaser's `unreported_gallons_total`, so an explained, written-off or
        escalated variance drops out of the licensee-level figure that feeds risk scoring even where
        it stays in the run-level figure."

        Design: Difficulty/compensating_invariant/discrepancy_write_off_conserves_run_gross_unreported_gallons
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        distributor = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        world.build_return(
            supplier["id"],
            "2026-08",
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": "GASOLINE",
                    "lines": [
                        {
                            "counterparty": distributor["id"],
                            "gallons": 3000.00,
                            "date": "2026-08-10",
                            "transaction_type": "SALE",
                            "bill_of_lading_number": "BOL-S5-GAS-050",
                        }
                    ],
                },
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": "UNDYED_DIESEL",
                    "lines": [
                        {
                            "counterparty": distributor["id"],
                            "gallons": 4000.00,
                            "date": "2026-08-11",
                            "transaction_type": "SALE",
                            "bill_of_lading_number": "BOL-S5-UND-050",
                        }
                    ],
                },
            ],
            file=True,
            attest_name="S. Northline",
        )
        purchaser_return = world.build_return(
            distributor["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "BIODIESEL_B100",
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.00,
                            "date": "2026-08-12",
                            "bill_of_lading_number": "BOL-D1-BIO-050",
                        }
                    ],
                }
            ],
            file=True,
            attest_name="D. Ridgeway",
        )

        run = world.run_cross_match("2026-08")
        gasoline = world.discrepancies(run_id=run["id"], product_code="GASOLINE")[0]
        diesel = world.discrepancies(run_id=run["id"], product_code="UNDYED_DIESEL")[0]
        assert_gallons(gasoline["variance_gallons"], 3000.00, "variance_gallons")
        assert_gallons(diesel["variance_gallons"], 4000.00, "variance_gallons")

        before = validate_success(api.get_cross_match_run(run["id"], examiner_headers))
        assert before["discrepancy_count"] == 2
        assert_gallons(
            before["gross_unreported_gallons_total"], 7000.00, "gross_unreported_gallons_total"
        )
        assert_gallons(before["unreported_gallons_total"], 7000.00, "unreported_gallons_total")
        assert_gallons(before["written_off_gallons_total"], 0.00, "written_off_gallons_total")

        world.send_inquiry(
            gasoline["id"],
            question=(
                "Your 2026-08 return reports no GASOLINE receipts from Northline; explain the "
                "3000.00 gallon gap"
            ),
            response_due_date="2026-09-30",
        )
        answered = world.answer_inquiry(
            gasoline["id"],
            distributor["id"],
            explanation=(
                "The supplier billed a load that our terminal never received; the counterparty has "
                "since ceased trading"
            ),
        )
        assert answered["status"] == "RESPONSE_RECEIVED"
        assert answered["inquiry_round"] == 1
        mid_run = validate_success(api.get_cross_match_run(run["id"], examiner_headers))
        assert_gallons(mid_run["unreported_gallons_total"], 7000.00, "unreported_gallons_total")
        assert_gallons(mid_run["written_off_gallons_total"], 0.00, "written_off_gallons_total")

        written_off = world.resolve(
            gasoline["id"],
            "WRITTEN_OFF",
            write_off_reason="Counterparty ceased trading; the gallons are uncollectible",
        )
        assert written_off["status"] == "WRITTEN_OFF"
        assert_gallons(written_off["variance_gallons"], 3000.00, "variance_gallons")

        after = validate_success(api.get_cross_match_run(run["id"], examiner_headers))
        assert_gallons(
            after["gross_unreported_gallons_total"], 7000.00, "gross_unreported_gallons_total"
        )
        assert_gallons(after["unreported_gallons_total"], 4000.00, "unreported_gallons_total")
        assert_gallons(after["written_off_gallons_total"], 3000.00, "written_off_gallons_total")
        assert round(
            after["unreported_gallons_total"] + after["written_off_gallons_total"], 2
        ) == round(after["gross_unreported_gallons_total"], 2)

        still_open = validate_success(api.get_discrepancy(diesel["id"], examiner_headers))
        assert still_open["status"] == "OPEN"
        assert_gallons(still_open["variance_gallons"], 4000.00, "variance_gallons")

        licensee = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert licensee["open_discrepancy_count"] == 1
        assert_gallons(
            licensee["unreported_gallons_total"], 4000.00, "unreported_gallons_total"
        )
        assert_cents(licensee["balance_cents"], 0, "balance_cents")
        assert_ledger_sequence(world.ledger(distributor["id"]), [("RETURN_TAX", 0)])

        reread = validate_success(api.get_return(purchaser_return.id, examiner_headers))
        assert_return_statuses(reread, "FILED", "MATCH_VARIANCE")
